import os
import logging
import razorpay
from datetime import datetime
from db_config import get_database
from dotenv import load_dotenv

load_dotenv() 

logger = logging.getLogger(__name__)


class PaymentHandler:
    """Handle Razorpay payment operations"""
    
    def __init__(self):
        self.key_id = os.getenv('RAZORPAY_KEY_ID', '')
        self.key_secret = os.getenv('RAZORPAY_KEY_SECRET', '')
        
        if not self.key_id or not self.key_secret:
            logger.warning("Razorpay credentials not found in environment variables")
            self.client = None
        else:
            self.client = razorpay.Client(auth=(self.key_id, self.key_secret))
    
    def create_order(self, amount, currency='INR', receipt=None, notes=None):
        """
        Create a Razorpay order
        
        Args:
            amount: Amount in rupees (will be converted to paise)
            currency: Currency code (default: INR)
            receipt: Optional receipt ID
            notes: Optional dictionary of notes
            
        Returns:
            dict: Order details from Razorpay
        """
        if not self.client:
            raise Exception("Razorpay client not initialized. Please check credentials.")
        
        try:
            # Convert amount to paise (Razorpay expects amount in smallest currency unit)
            amount_paise = int(amount * 100)
            
            order_data = {
                'amount': amount_paise,
                'currency': currency,
                'payment_capture': 1  # Auto-capture payment
            }
            
            if receipt:
                order_data['receipt'] = receipt
            
            if notes:
                order_data['notes'] = notes
            
            order = self.client.order.create(data=order_data)
            logger.info(f"Created Razorpay order: {order['id']}")
            return order
            
        except Exception as e:
            logger.error(f"Error creating Razorpay order: {e}")
            raise
    
    def verify_payment_signature(self, order_id, payment_id, signature):
        """
        Verify Razorpay payment signature
        
        Args:
            order_id: Razorpay order ID
            payment_id: Razorpay payment ID
            signature: Razorpay signature
            
        Returns:
            bool: True if signature is valid, False otherwise
        """
        if not self.client:
            raise Exception("Razorpay client not initialized. Please check credentials.")
        
        try:
            params_dict = {
                'razorpay_order_id': order_id,
                'razorpay_payment_id': payment_id,
                'razorpay_signature': signature
            }
            
            # This will raise an exception if signature is invalid
            self.client.utility.verify_payment_signature(params_dict)
            logger.info(f"Payment signature verified for order: {order_id}")
            return True
            
        except razorpay.errors.SignatureVerificationError as e:
            logger.error(f"Payment signature verification failed: {e}")
            return False
        except Exception as e:
            logger.error(f"Error verifying payment signature: {e}")
            raise
    
    def store_payment_record(self, user_email, order_id, payment_id, amount, mode, pages, status='success'):
        """
        Store payment record in MongoDB
        
        Args:
            user_email: User's email
            order_id: Razorpay order ID
            payment_id: Razorpay payment ID
            amount: Payment amount in rupees
            mode: Processing mode
            pages: Number of pages
            status: Payment status (success/failed)
        """
        try:
            db = get_database()
            payments_collection = db['payments']
            
            payment_record = {
                'user_email': user_email,
                'order_id': order_id,
                'payment_id': payment_id,
                'amount': amount,
                'mode': mode,
                'pages': pages,
                'status': status,
                'created_at': datetime.utcnow(),
                'timestamp': datetime.utcnow().isoformat()
            }
            
            result = payments_collection.insert_one(payment_record)
            logger.info(f"Stored payment record for {user_email}: {result.inserted_id}")
            return str(result.inserted_id)
            
        except Exception as e:
            logger.error(f"Error storing payment record: {e}")
            raise
    
    def get_user_payments(self, user_email, limit=10):
        """
        Get payment history for a user
        
        Args:
            user_email: User's email
            limit: Maximum number of records to return
            
        Returns:
            list: List of payment records
        """
        try:
            db = get_database()
            payments_collection = db['payments']
            
            payments = list(payments_collection.find(
                {'user_email': user_email}
            ).sort('created_at', -1).limit(limit))
            
            # Convert ObjectId to string for JSON serialization
            for payment in payments:
                payment['_id'] = str(payment['_id'])
            
            return payments
            
        except Exception as e:
            logger.error(f"Error retrieving payment history: {e}")
            raise
    
    def get_payment_by_order_id(self, order_id):
        """
        Get payment record by order ID
        
        Args:
            order_id: Razorpay order ID
            
        Returns:
            dict: Payment record or None
        """
        try:
            db = get_database()
            payments_collection = db['payments']
            
            payment = payments_collection.find_one({'order_id': order_id})
            
            if payment:
                payment['_id'] = str(payment['_id'])
            
            return payment
            
        except Exception as e:
            logger.error(f"Error retrieving payment by order ID: {e}")
            raise


# Singleton instance
payment_handler = PaymentHandler()

