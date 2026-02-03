from flask import Blueprint, render_template, request, jsonify, redirect, url_for, session, current_app
import logging

from auth import (
    generate_otp, send_otp_email, store_otp, verify_otp, 
    create_or_get_user, check_trial_available, login_required
)

logger = logging.getLogger(__name__)

# Create blueprint
auth_bp = Blueprint('auth', __name__)


@auth_bp.route('/login')
def login():
    """Login page"""
    return render_template('login.html')


@auth_bp.route('/send-otp', methods=['POST'])
def send_otp():
    """Send OTP to user's email"""
    try:
        data = request.get_json()
        email = data.get('email', '').strip().lower()
        
        if not email:
            return jsonify({'success': False, 'message': 'Email is required'}), 400
        
        # Generate and send OTP
        otp = generate_otp()
        if send_otp_email(email, otp):
            store_otp(email, otp)
            # Create or get user
            create_or_get_user(email)
            return jsonify({'success': True, 'message': 'OTP sent to your email'})
        else:
            return jsonify({'success': False, 'message': 'Failed to send OTP. Please check your email.'}), 500
            
    except Exception as e:
        logger.error(f"Error sending OTP: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@auth_bp.route('/verify-otp', methods=['POST'])
def verify_otp_route():
    """Verify OTP and create session"""
    try:
        data = request.get_json()
        email = data.get('email', '').strip().lower()
        otp = data.get('otp', '').strip()
        
        if not email or not otp:
            return jsonify({'success': False, 'message': 'Email and OTP are required'}), 400
        
        # Verify OTP
        success, message = verify_otp(email, otp)
        
        if success: 
            # Create session
            session['user_email'] = email
            session.permanent = True
            return jsonify({'success': True, 'message': 'Login successful'})
        else:
            return jsonify({'success': False, 'message': message}), 400
            
    except Exception as e:
        logger.error(f"Error verifying OTP: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@auth_bp.route('/logout')
def logout():
    """Logout user"""
    session.pop('user_email', None)
    return redirect(url_for('auth.login'))


@auth_bp.route('/check-trial', methods=['POST'])
@login_required
def check_trial():
    """Check trial status for a mode"""
    try:
        data = request.get_json()
        mode = data.get('mode')
        
        if mode is None:
            return jsonify({'error': 'Mode is required'}), 400
        
        email = session['user_email']
        trial_info = check_trial_available(email, mode)
        
        return jsonify(trial_info)
        
    except Exception as e:
        logger.error(f"Error checking trial: {e}")
        return jsonify({'error': str(e)}), 500
