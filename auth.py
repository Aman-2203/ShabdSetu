import os
import random
import string
import smtplib
import threading
import time
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from functools import wraps
from flask import session, jsonify, redirect, url_for, current_app
import logging

from db_config import get_user_collection, get_trial_usage_collection

from dotenv import load_dotenv

load_dotenv() 


logger = logging.getLogger(__name__)

# OTP storage: {email: {'otp': '123456', 'timestamp': datetime}}
otp_storage = {}
OTP_EXPIRY_MINUTES = 5
TRIAL_PAGES_LIMIT = 3

# Email configuration
GMAIL_ADDRESS = os.getenv('SENDER_EMAIL', '')
GMAIL_APP_PASSWORD = os.getenv('SENDER_PASSWORD', '')


def generate_otp():
    """Generate a 6-digit OTP"""
    return ''.join(random.choices(string.digits, k=6))


def send_otp_email(email, otp):
    """Send OTP via email using Gmail SMTP"""
    try:
        # Create message
        msg = MIMEMultipart()
        msg['From'] = GMAIL_ADDRESS
        msg['To'] = email
        msg['Subject'] = 'Your OTP for AAS Clone Login'
        
        body = f"""
        <html>
        <body>
            <h2>Login Verification</h2>
            <p>Your OTP for logging into ShabdSetu is:</p>
            <h1 style="color: #4CAF50; font-size: 32px; letter-spacing: 5px;">{otp}</h1>
            <p>This OTP will expire in {OTP_EXPIRY_MINUTES} minutes.</p>
            <p>If you didn't request this OTP, please ignore this email.</p>
        </body>
        </html>
        """
        
        msg.attach(MIMEText(body, 'html'))
        
        # Send email
        with smtplib.SMTP('smtp.gmail.com', 587) as server:
            server.starttls()
            server.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
            server.send_message(msg)
        
        logger.info(f"OTP sent successfully to {email}")
        return True
        
    except Exception as e:
        logger.error(f"Failed to send OTP email: {e}")
        return False


def store_otp(email, otp):
    """Store OTP in memory with timestamp"""
    otp_storage[email] = {
        'otp': otp,
        'timestamp': datetime.now()
    }
    logger.info(f"OTP stored for {email}")


def verify_otp(email, otp):
    """Verify OTP and check expiration"""
    if email not in otp_storage:
        return False, "OTP not found or expired"
    
    stored_data = otp_storage[email]
    stored_otp = stored_data['otp']
    timestamp = stored_data['timestamp']
    
    # Check expiration
    if datetime.now() - timestamp > timedelta(minutes=OTP_EXPIRY_MINUTES):
        del otp_storage[email]
        return False, "OTP has expired"
    
    # Verify OTP
    if stored_otp == otp:
        # Remove OTP after successful verification
        del otp_storage[email]
        return True, "OTP verified successfully"
    else:
        return False, "Invalid OTP"


def cleanup_expired_otps():
    """Remove expired OTPs from storage"""
    while True:
        time.sleep(360)  # Run every 6 minutes
        now = datetime.now()
        expired_emails = []
        
        for email, data in otp_storage.items():
            if now - data['timestamp'] > timedelta(minutes=OTP_EXPIRY_MINUTES):
                expired_emails.append(email)
        
        for email in expired_emails:
            del otp_storage[email]
            logger.info(f"Cleaned up expired OTP for {email}")


def start_otp_cleanup_thread():
    """Start background thread for OTP cleanup"""
    cleanup_thread = threading.Thread(target=cleanup_expired_otps, daemon=True)
    cleanup_thread.start()
    logger.info("OTP cleanup thread started")


def create_or_get_user(email):
    """Create user if doesn't exist, or get existing user"""
    users = get_user_collection()
    
    user = users.find_one({'email': email})
    if not user:
        user_data = {
            'email': email,
            'created_at': datetime.now()
        }
        users.insert_one(user_data)
        logger.info(f"New user created: {email}")
        return user_data
    
    return user


def get_trial_usage(email, mode):
    """Get trial usage for a user and mode"""
    trial_usage = get_trial_usage_collection()
    
    usage = trial_usage.find_one({'email': email, 'mode': mode})
    if not usage:
        # Initialize trial usage for this mode
        usage_data = {
            'email': email,
            'mode': mode,
            'pages_used': 0,
            'created_at': datetime.now()
        }
        trial_usage.insert_one(usage_data)
        return usage_data
    
    return usage


def increment_trial_usage(email, mode, pages=1):
    """Increment trial usage for a user and mode"""
    trial_usage = get_trial_usage_collection()
    
    result = trial_usage.update_one(
        {'email': email, 'mode': mode},
        {
            '$inc': {'pages_used': pages},
            '$set': {'last_used': datetime.now()}
        }
    )
    
    if result.modified_count > 0:
        logger.info(f"Trial usage incremented for {email}, mode {mode}")
        return True
    return False


def check_trial_available(email, mode):
    """Check if user has trial pages available for a mode"""
    usage = get_trial_usage(email, mode)
    pages_used = usage.get('pages_used', 0)
    remaining = TRIAL_PAGES_LIMIT - pages_used
    
    return {
        'available': pages_used < TRIAL_PAGES_LIMIT,
        'pages_used': pages_used,
        'pages_remaining': max(0, remaining),
        'limit': TRIAL_PAGES_LIMIT
    }


def login_required(f):
    """Decorator to check if user is logged in"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Bypass login check in development mode
        if current_app.env == "development" and not current_app.config['TEST_OTP']:
            if 'user_email' not in session:
                session['user_email'] = "testmail@gmail.com"
            return f(*args, **kwargs)
        
        if 'user_email' not in session:
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated_function


def trial_required(mode):
    """Decorator to check if user has trial pages available"""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            # Bypass trial check in development mode
            if current_app.env == "development":
                if 'user_email' not in session:
                    session['user_email'] = "testmail@gmail.com"
                return f(*args, **kwargs)
            
            if 'user_email' not in session:
                return jsonify({'error': 'Authentication required'}), 401
            
            email = session['user_email']
            trial_info = check_trial_available(email, mode)
            
            if not trial_info['available']:
                return jsonify({
                    'error': 'Trial limit exceeded',
                    'message': f"You have used all {TRIAL_PAGES_LIMIT} free trial pages for this tool.",
                    'pages_used': trial_info['pages_used']
                }), 403
            
            return f(*args, **kwargs)
        return decorated_function
    return decorator

