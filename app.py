import os
import threading
import atexit
from concurrent.futures import ThreadPoolExecutor
import uuid
import logging
from flask import Flask, render_template, request, jsonify, send_file, redirect, url_for, session
from werkzeug.utils import secure_filename

from datetime import datetime, timedelta
from config import UPLOAD_FOLDER, OUTPUT_FOLDER, MAX_CONTENT_LENGTH, progress_tracker
from processors import ProofreadingProcessor, TranslationProcessor, OCRProcessor
from document_handler import DocumentHandler
from auth import (
    generate_otp, send_otp_email, store_otp, verify_otp, 
    create_or_get_user, check_trial_available, increment_trial_usage,
    start_otp_cleanup_thread, login_required
)
from utils import (
    calculate_page_usage, validate_trial_limits, send_document_email,
    calculate_pages_from_words, get_docx_word_count
)
from payment_handler import payment_handler

from dotenv import load_dotenv

load_dotenv() 


logger = logging.getLogger(__name__)

# Pricing Configuration (Rs. per page)
PRICING = {
    1: 3,  # OCR
    2: 9,  # OCR + Proofread (3 + 6)
    3: 6,  # Proofread
    4: 9,  # OCR + Translation (3 + 6)
    5: 6   # Translation
}

# Flask app setup
app = Flask(__name__)
app.secret_key = os.getenv('FLASK_SECRET_KEY', os.urandom(24))
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['OUTPUT_FOLDER'] = OUTPUT_FOLDER
app.config['MAX_CONTENT_LENGTH'] = MAX_CONTENT_LENGTH
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=24)

# Start OTP cleanup thread
start_otp_cleanup_thread()

# ==============================================================
# GLOBAL THREAD POOL FOR GEMINI API (40 WORKERS)
# This pool is shared by ALL users to control concurrency
# and prevent rate limit issues with paid tier
# ==============================================================
GLOBAL_GEMINI_EXECUTOR = ThreadPoolExecutor(
    max_workers=40,
    thread_name_prefix="gemini_worker"
)

# Cleanup executor on application shutdown
def cleanup_executor():
    logger.info("Shutting down global Gemini executor...")
    GLOBAL_GEMINI_EXECUTOR.shutdown(wait=True)
    logger.info("Executor shutdown complete")

atexit.register(cleanup_executor)
logger.info(f"Initialized global Gemini executor with 40 workers")


def process_document_background(job_id, mode, input_path, language, source_lang, target_lang, original_filename, user_email='', user_prompt=''):
    """Background processing function"""
    try:
        # Get API keys from environment
        vision_api_key = os.getenv('GOOGLE_VISION_API_KEY')
        gemini_api_key = os.getenv('GEMINI_API_KEY')
        
        output_filename = None
        if mode == 1:
            # OCR Only
            ocr = OCRProcessor(vision_api_key, job_id)
            text = ocr.perform_ocr(input_path)
            output_filename = f"{job_id}_ocr_raw.docx"
            output_path = os.path.join(app.config['OUTPUT_FOLDER'], output_filename)
            DocumentHandler.save_raw_docx(text, output_path)
            
        elif mode == 2:
            # OCR + Proofread
            ocr = OCRProcessor(vision_api_key, job_id)
            text = ocr.perform_ocr(input_path)
            text = text.replace('\n', '\r')
            
            # ✅ FIXED: Use proofread_full_text() instead of manual chunking
            proofreader = ProofreadingProcessor(gemini_api_key, job_id=job_id, executor=GLOBAL_GEMINI_EXECUTOR)
            corrected_text = proofreader.proofread_full_text(text, language)
            
            # Convert back to chunks for document formatting (if needed)
            corrected_chunks = corrected_text.split('\n')
            
            output_filename = f"{job_id}_ocr_proofread.docx"
            output_path = os.path.join(app.config['OUTPUT_FOLDER'], output_filename)
            DocumentHandler.create_formatted_document(corrected_chunks, output_path, language, "OCR + Proofread")
            
        elif mode == 3:
            # Proofread Only
            content = DocumentHandler.read_docx(input_path)
            
            # ✅ FIXED: Use proofread_full_text() instead of manual chunking
            proofreader = ProofreadingProcessor(gemini_api_key, job_id=job_id, executor=GLOBAL_GEMINI_EXECUTOR)
            corrected_text = proofreader.proofread_full_text(content, language)
            
            # Convert back to chunks for document formatting (if needed)
            corrected_chunks = corrected_text.split('\n\n')
            
            output_filename = f"{job_id}_proofread.docx"
            output_path = os.path.join(app.config['OUTPUT_FOLDER'], output_filename)
            DocumentHandler.create_formatted_document(corrected_chunks, output_path, language, "Proofread")
            
        elif mode == 4:
            # OCR + Translation
            ocr = OCRProcessor(vision_api_key, job_id)
            text = ocr.perform_ocr(input_path)
            
            # ✅ FIXED: Use translate_full_text() instead of manual chunking
            translator = TranslationProcessor(gemini_api_key, job_id=job_id, executor=GLOBAL_GEMINI_EXECUTOR)
            translated_text = translator.translate_full_text(text, source_lang, target_lang)
            
            # Convert back to chunks for document formatting (if needed)
            translated_chunks = translated_text.split('\n\n')
            
            output_filename = f"{job_id}_ocr_translated_{target_lang}.docx"
            output_path = os.path.join(app.config['OUTPUT_FOLDER'], output_filename)
            DocumentHandler.create_formatted_document(translated_chunks, output_path, target_lang, "OCR + Translated")
            
        elif mode == 5:
            # Translation Only
            content = DocumentHandler.read_docx(input_path)
            
            # ✅ FIXED: Use translate_full_text() instead of manual chunkin g
            translator = TranslationProcessor(gemini_api_key, job_id=job_id, executor=GLOBAL_GEMINI_EXECUTOR)
            translated_text = translator.translate_full_text(content, source_lang, target_lang)
            
            # Convert back to chunks for document formatting (if needed)
            translated_chunks = translated_text.split('\n\n')
            
            output_filename = f"{job_id}_translated_{target_lang}.docx"
            output_path = os.path.join(app.config['OUTPUT_FOLDER'], output_filename)
            DocumentHandler.create_formatted_document(translated_chunks, output_path, target_lang, "Translated")        
        
        # Mark as complete
        progress_tracker[job_id] = {
            'current': 100,
            'total': 100,
            'status': 'Complete',
            'percentage': 100,
            'output_file': output_filename,
            'user_email': user_email
        }
        
        # Automatically send email to user with the processed document
        if user_email and output_filename:
            try:
                output_path = os.path.join(app.config['OUTPUT_FOLDER'], output_filename)
                email_sent = send_document_email(user_email, output_path, job_id)
                if email_sent:
                    logger.info(f"Auto-sent document email to {user_email} for job {job_id}")
                else:
                    logger.warning(f"Failed to auto-send email to {user_email} for job {job_id}")
            except Exception as e:
                logger.error(f"Error auto-sending email for job {job_id}: {e}")
                # Don't fail the job if email fails - user can still download
        
    except Exception as e:
        logger.error(f"Error processing document: {e}")
        progress_tracker[job_id] = {
            'current': 0,
            'total': 100,
            'status': f'Error: {str(e)}',
            'percentage': 0,
            'error': True
        }


@app.route("/")
def initialize():
    return render_template('feature.html')  

@app.route('/login')
def login():
    """Login page"""
    return render_template('login.html')

@app.route("/terms&conditions")
def tc():
    return render_template("TC.html")

@app.route('/send-otp', methods=['POST'])
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

@app.route('/verify-otp', methods=['POST'])
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

@app.route('/logout')
def logout():
    """Logout user"""
    session.pop('user_email', None)
    return redirect(url_for('login'))

@app.route('/check-trial', methods=['POST'])
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

@app.route('/features')
def feature():
    return render_template('feature.html')

@app.route('/pricing')
def pricing():
    return render_template('pricing.html')

@app.route('/contactus')
def contactus():
    return render_template('contactus.html')

@app.route('/tool')
@login_required
def index_redirect():
    # Get trial info for all modes to display on the page
    email = session['user_email']
    trial_info_all_modes = {}
    for mode in range(1, 6):
        trial_info_all_modes[mode] = check_trial_available(email, mode)
    
    return render_template('index.html', trial_info=trial_info_all_modes)

@app.route('/mode/<int:mode_num>')
@login_required
def mode_page(mode_num):
    if mode_num not in range(1, 6):
        return "Invalid mode", 404
    
    # Get trial information
    email = session['user_email']
    trial_info = check_trial_available(email, mode_num)
    
    return render_template(f'mode{mode_num}.html', mode=mode_num, trial_info=trial_info)

@app.route('/create-payment', methods=['POST'])
@login_required
def create_payment():
    """Create a Razorpay payment order"""
    try:
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


@app.route('/verify-payment', methods=['POST'])
@login_required
def verify_payment():
    """Verify Razorpay payment signature"""
    try:
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


@app.route('/process', methods=['POST'])
@login_required
def process_file():
    try:
        # Check authentication
        if 'user_email' not in session:
            return jsonify({'error': 'Authentication required'}), 401
        
        email = session['user_email']
        mode = int(request.form.get('mode'))
        
        # Get file info
        file = request.files.get('file')
        if not file:
            return jsonify({'error': 'No file uploaded'}), 400
        
        # Get file extension
        filename = secure_filename(file.filename)
        file_extension = os.path.splitext(filename)[1].lower().strip('.')
        
        # Save uploaded file temporarily for validation
        job_id = str(uuid.uuid4())
        input_path = os.path.join(app.config['UPLOAD_FOLDER'], f"{job_id}_{filename}")
        file.save(input_path)
        
        try:
            # Calculate page usage based on file type
            page_usage_info = calculate_page_usage(input_path, file_extension)
            
            # Calculate billable pages (for pricing)
            billable_pages = 0
            if page_usage_info['file_type'] == 'pdf':
                billable_pages = page_usage_info['actual_pages']
            else:
                # For DOCX, use word count / 550
                word_count = get_docx_word_count(input_path)
                billable_pages = calculate_pages_from_words(word_count)
                # Add word count to usage info for frontend
                page_usage_info['word_count'] = word_count
                page_usage_info['billable_pages'] = billable_pages

            # Check for payment
            payment_id = request.form.get('payment_id')
            is_paid = False
            
            if payment_id:
                # Verify payment (Dummy verification)
                if payment_id.startswith('pay_'):
                    is_paid = True
                    logger.info(f"Processing paid request: {payment_id} for {email}")
            
            if not is_paid:
                # Check trial availability
                trial_info = check_trial_available(email, mode)
                remaining_pages = trial_info['pages_remaining']
                
                # Validate against trial limits
                validation_result = validate_trial_limits(page_usage_info, remaining_pages)
                
                if not validation_result['valid']:
                    # Clean up uploaded file
                    if os.path.exists(input_path):
                        os.remove(input_path)
                    
                    # Return detailed error information with pricing info
                    error_details = {
                        'error': 'Trial limit exceeded',
                        'message': validation_result['message'],
                        'pages_used': trial_info['pages_used'],
                        'pages_remaining': trial_info['pages_remaining'],
                        'limit': trial_info['limit'],
                        'document_pages': page_usage_info.get('actual_pages'),
                        'document_chars': page_usage_info.get('char_count'),
                        'billable_pages': billable_pages,
                        'estimated_cost': billable_pages * PRICING.get(mode, 0),
                        'page_usage': validation_result['page_usage']
                    }
                    return jsonify(error_details), 403
                
                # Store page usage for later increment (only for trial)
                page_usage = validation_result['page_usage']
                
                # Increment trial usage with actual page count
                increment_trial_usage(email, mode, pages=page_usage)
            else:
                # For paid requests, we don't increment trial usage
                page_usage = billable_pages
            
        except Exception as e:
            # Clean up uploaded file on error
            if os.path.exists(input_path):
                os.remove(input_path)
            logger.error(f"Error validating document: {e}")
            return jsonify({'error': f'Error processing file: {str(e)}'}), 400
        
        # Get additional parameters
        language = request.form.get('language')
        source_lang = request.form.get('source_lang')
        target_lang = request.form.get('target_lang')
        user_prompt = request.form.get('user_prompt', '')  # For mode 6
        
        # Initialize progress
        progress_tracker[job_id] = {
            'current': 0,
            'total': 100,
            'status': 'Starting...',
            'percentage': 0,
            'user_email': email,
            'page_usage': page_usage
        }
        
        # Increment trial usage is now handled inside the try block above

        
        # Process in background thread
        thread = threading.Thread(
            target=process_document_background,
            args=(job_id, mode, input_path, language, source_lang, target_lang, filename, email, user_prompt)
        )
        thread.daemon = True
        thread.start()
        
        # Get updated trial info
        updated_trial = check_trial_available(email, mode)
        
        return jsonify({
            'job_id': job_id,
            'trial_info': updated_trial
        })
        
    except Exception as e:
        logger.error(f"Error in process_file: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/progress/<job_id>')
def get_progress(job_id):
    """Get progress for a job"""
    if job_id in progress_tracker:
        return jsonify(progress_tracker[job_id])
    return jsonify({'error': 'Job not found'}), 404

@app.route('/download/<filename>')
def download_file(filename):
    """Download processed file"""
    try:
        file_path = os.path.join(app.config['OUTPUT_FOLDER'], filename)
        if os.path.exists(file_path):
            return send_file(file_path, as_attachment=True, download_name=filename)
        return "File not found", 404
    except Exception as e:
        return str(e), 500

@app.route('/send-document/<job_id>', methods=['POST'])
@login_required
def send_document(job_id):
    """Send processed document to user via email"""
    try:
        # Check if job exists
        if job_id not in progress_tracker:
            return jsonify({'error': 'Job not found'}), 404
        
        job_data = progress_tracker[job_id]
        
        # Check if job is complete
        if job_data.get('status') != 'Complete':
            return jsonify({
                'error': 'Job not complete',
                'message': 'Please wait for processing to complete'
            }), 400
        
        # Get output file
        output_file = job_data.get('output_file')
        if not output_file:
            return jsonify({'error': 'No output file found'}), 404
        
        # Get user email
        if 'user_email' not in session:
            return jsonify({'error': 'Not authenticated'}), 401
        
        user_email = session['user_email']
        output_path = os.path.join(app.config['OUTPUT_FOLDER'], output_file)
        
        # Send email
        if send_document_email(user_email, output_path, job_id):
            return jsonify({
                'success': True,
                'message': f'Document sent to {user_email}'
            })
        else:
            return jsonify({
                'error': 'Failed to send email',
                'message': 'Please try again or download the file directly'
            }), 500
            
    except Exception as e:
        logger.error(f"Error sending document: {e}")
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    os.makedirs(OUTPUT_FOLDER, exist_ok=True)
    app.run(debug=False, host='0.0.0.0', port=8080)





