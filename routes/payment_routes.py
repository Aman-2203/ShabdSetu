from flask import Blueprint, request, jsonify, session, current_app
import uuid
import logging

from auth import login_required
from payment_handler import payment_handler

logger = logging.getLogger(__name__)

# Pricing Configuration (Rs. per page)
PRICING = {
    1: 3,  # OCR
    2: 9,  # OCR + Proofread (3 + 6)
    3: 6,  # Proofread
    4: 9,  # OCR + Translation (3 + 6)
    5: 6   # Translation
}

# Create blueprint
payment_bp = Blueprint('payment', __name__)


@payment_bp.route('/create-payment', methods=['POST'])
@login_required
def create_payment():
    """Create a Razorpay payment order"""
    try:
        # Bypass payment in development mode
        if current_app.env == "development":
            data = request.get_json()
            mode = int(data.get('mode'))
            pages = int(data.get('pages'))
            cost_per_page = PRICING.get(mode, 0)
            total_amount = cost_per_page * pages
            return jsonify({
                'success': True,
                'order_id': 'dev_order_' + str(uuid.uuid4().hex[:12]),
                'amount': total_amount,
                'amount_paise': total_amount * 100,
                'currency': 'INR',
                'pages': pages,
                'rate': cost_per_page,
                'key_id': 'dev_key_id',
                'dev_mode': True
            })
        
        data = request.get_json()
        mode = int(data.get('mode'))
        pages = int(data.get('pages'))
        
        if mode not in PRICING:
            return jsonify({'error': 'Invalid mode'}), 400
            
        cost_per_page = PRICING[mode]
        total_amount = cost_per_page * pages
        
        # Get user email from session
        user_email = session.get('user_email', 'unknown')
        
        # Create Razorpay order
        receipt = f"receipt_{uuid.uuid4().hex[:12]}"
        notes = {
            'user_email': user_email,
            'mode': mode,
            'pages': pages,
            'rate': cost_per_page
        }
        
        order = payment_handler.create_order(
            amount=total_amount,
            currency='INR',
            receipt=receipt,
            notes=notes
        )
        
        return jsonify({
            'success': True,
            'order_id': order['id'],
            'amount': total_amount,
            'amount_paise': order['amount'],
            'currency': order['currency'],
            'pages': pages,
            'rate': cost_per_page,
            'key_id': payment_handler.key_id
        })
        
    except Exception as e:
        logger.error(f"Error creating payment: {e}")
        return jsonify({'error': str(e)}), 500


@payment_bp.route('/verify-payment', methods=['POST'])
@login_required
def verify_payment():
    """Verify Razorpay payment signature"""
    try:
        # Bypass payment verification in development mode
        if current_app.env == "development" and  not current_app.config['TEST_PAYMENT']:
            data = request.get_json()
            return jsonify({
                'success': True,
                'payment_id': 'dev_pay_' + str(uuid.uuid4().hex[:12]),
                'message': 'Payment verified successfully (dev mode)',
                'dev_mode': True
            })
        
        data = request.get_json()
        order_id = data.get('razorpay_order_id')
        payment_id = data.get('razorpay_payment_id')
        signature = data.get('razorpay_signature')
        mode = int(data.get('mode'))
        pages = int(data.get('pages'))
        amount = float(data.get('amount'))
        
        if not all([order_id, payment_id, signature]):
            return jsonify({'error': 'Missing payment details'}), 400
        
        # Verify payment signature
        is_valid = payment_handler.verify_payment_signature(
            order_id=order_id,
            payment_id=payment_id,
            signature=signature
        )
        
        if not is_valid:
            return jsonify({
                'success': False,
                'error': 'Invalid payment signature'
            }), 400
        
        # Store payment record
        user_email = session.get('user_email')
        payment_handler.store_payment_record(
            user_email=user_email,
            order_id=order_id,
            payment_id=payment_id,
            amount=amount,
            mode=mode,
            pages=pages,
            status='success'
        )
        
        logger.info(f"Payment verified and recorded for {user_email}: {payment_id}")
        
        return jsonify({
            'success': True,
            'payment_id': payment_id,
            'message': 'Payment verified successfully'
        })
        
    except Exception as e:
        logger.error(f"Error verifying payment: {e}")
        return jsonify({'error': str(e)}), 500


# Export PRICING for use in other modules
def get_pricing():
    return PRICING
