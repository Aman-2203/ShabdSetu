import os
import threading
import uuid
from datetime import datetime
from flask import Blueprint, request, jsonify, send_file, session, current_app
from werkzeug.utils import secure_filename
import logging
from concurrent.futures import ThreadPoolExecutor

from config import progress_tracker
from auth import check_trial_available, increment_trial_usage, login_required
from utils import (
    calculate_page_usage, validate_trial_limits, send_document_email,
    calculate_pages_from_words, get_docx_word_count
)
from db_config import get_jobs_collection
from .payment_routes import get_pricing

# ==============================================================
# GLOBAL THREAD POOL FOR GEMINI API (40 WORKERS)
# This pool is shared by ALL users to control concurrency
# and prevent rate limit issues with paid tier
# ==============================================================
GLOBAL_GEMINI_EXECUTOR = ThreadPoolExecutor(
    max_workers=10,
    thread_name_prefix="gemini_worker")

logger = logging.getLogger(__name__)

# Create blueprint
document_bp = Blueprint('document', __name__)
bp = Blueprint('main', __name__)


def get_process_document_background():
    """Get the background processing function from the main app module."""
    from process_document import process_document_background
    return process_document_background


# Cleanup executor on application shutdown
def cleanup_executor():
    logger.info("Shutting down global Gemini executor...")
    GLOBAL_GEMINI_EXECUTOR.shutdown(wait=True)
    logger.info("Executor shutdown complete")


@document_bp.route('/process', methods=['POST'])
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

        # Validate audio file for mode 6
        if mode == 6:
            if file_extension not in ('mp3', 'wav'):
                return jsonify({
                    'error': f"Unsupported audio format '.{file_extension}'. "
                             "Only .mp3 and .wav files are accepted for Audio Transcription."
                }), 400
        job_id = str(uuid.uuid4())
        input_path = os.path.join(current_app.config['UPLOAD_FOLDER'], f"{job_id}_{filename}")
        file.save(input_path)
        
        PRICING = get_pricing()
        AUDIO_TRIAL_MINUTES = 3  # free trial limit for mode 6

        try:
            if mode == 6:
                # ── Audio mode: billing unit = minutes ──────────────────────
                from processors.audio_processor import AudioProcessor
                duration_min = AudioProcessor.get_duration_minutes(input_path)
                import math as _math
                billable_minutes = _math.ceil(duration_min)

                payment_id = request.form.get('payment_id')
                is_paid = payment_id and payment_id.startswith('pay_')
                is_dev_mode = current_app.env == "development"

                if is_paid:
                    logger.info(f"Paid audio request: {payment_id} for {email} ({duration_min:.2f} min)")
                    page_usage = billable_minutes

                elif is_dev_mode:
                    page_usage = billable_minutes

                else:
                    trial_info = check_trial_available(email, mode)
                    remaining_min = trial_info['pages_remaining']

                    if duration_min > remaining_min:
                        if os.path.exists(input_path):
                            os.remove(input_path)
                            
                        if remaining_min <= 0:
                            msg = 'You have used all your free trial minutes for Audio Transcription.'
                        elif duration_min > AUDIO_TRIAL_MINUTES:
                            msg = f"Your audio is {duration_min:.1f} minutes, but the free trial allows up to {AUDIO_TRIAL_MINUTES} minutes. Please upgrade to process longer audio files."
                        else:
                            msg = f"Your audio is {duration_min:.1f} minutes, but you only have {remaining_min:.1f} minute{'s' if remaining_min != 1 else ''} remaining in your trial. Please upload a smaller file or upgrade."

                        return jsonify({
                            'error': 'Trial limit exceeded',
                            'message': msg,
                            'pages_used': trial_info['pages_used'],
                            'pages_remaining': remaining_min,
                            'limit': trial_info['limit'],
                            'billable_pages': billable_minutes,
                            'estimated_cost': billable_minutes * PRICING.get(mode, 0),
                            'page_usage': duration_min,
                        }), 403

                    page_usage = duration_min
                    increment_trial_usage(email, mode, pages=page_usage)

            else:
                # ── Document modes 1-5: billing unit = pages ────────────────
                page_usage_info = calculate_page_usage(input_path, file_extension)

                billable_pages = 0
                if page_usage_info['file_type'] == 'pdf':
                    billable_pages = page_usage_info['actual_pages']
                else:
                    word_count = get_docx_word_count(input_path)
                    billable_pages = calculate_pages_from_words(word_count)
                    page_usage_info['word_count'] = word_count
                    page_usage_info['billable_pages'] = billable_pages

                payment_id = request.form.get('payment_id')
                is_paid = False
                if payment_id and payment_id.startswith('pay_'):
                    is_paid = True
                    logger.info(f"Processing paid request: {payment_id} for {email}")

                is_dev_mode = current_app.env == "development"

                if not is_paid and not is_dev_mode:
                    trial_info = check_trial_available(email, mode)
                    remaining_pages = trial_info['pages_remaining']
                    validation_result = validate_trial_limits(page_usage_info, remaining_pages)

                    MAX_PAGES = 200
                    if page_usage_info['file_type'] == 'pdf' and page_usage_info['actual_pages'] > MAX_PAGES:
                        if os.path.exists(input_path):
                            os.remove(input_path)
                        return jsonify({
                            'error': f'Document exceeds maximum limit of {MAX_PAGES} pages.',
                            'page_count': page_usage_info['actual_pages']
                        }), 400

                    if not validation_result['valid']:
                        if os.path.exists(input_path):
                            os.remove(input_path)
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

                    page_usage = validation_result['page_usage']
                    increment_trial_usage(email, mode, pages=page_usage)
                else:
                    page_usage = billable_pages

        except Exception as e:
            if os.path.exists(input_path):
                os.remove(input_path)
            logger.error(f"Error validating document: {e}")
            return jsonify({'error': f'Error processing file: {str(e)}'}), 400
        
        # Get additional parameters
        language = request.form.get('language')
        source_lang = request.form.get('source_lang')
        target_lang = request.form.get('target_lang')
        
        # Mode name mapping
        MODE_NAMES = {
            1: 'OCR Only', 2: 'OCR + Proofread', 3: 'Proofread',
            4: 'OCR + Translation', 5: 'Translation', 6: 'Audio Transcription'
        }
        
        # Get file size for analytics
        file_size_bytes = os.path.getsize(input_path) if os.path.exists(input_path) else 0
        
        # Insert job record into MongoDB for analytics
        try:
            jobs = get_jobs_collection()
            job_record = {
                'job_id': job_id,
                'user_email': email,
                'mode': mode,
                'mode_name': MODE_NAMES.get(mode, f'Mode {mode}'),
                'language': language or target_lang or 'english',
                'source_lang': source_lang,
                'target_lang': target_lang,
                'original_filename': filename,
                'file_extension': file_extension,
                'file_size_bytes': file_size_bytes,
                'status': 'processing',
                'error_message': None,
                'page_usage': page_usage,
                'is_paid': bool(request.form.get('payment_id', '').startswith('pay_')),
                'payment_id': request.form.get('payment_id'),
                'created_at': datetime.utcnow(),
                'completed_at': None,
                'processing_time_seconds': None
            }
            jobs.insert_one(job_record)
        except Exception as e:
            logger.error(f"Failed to insert job record: {e}")
        
        # Initialize progress
        progress_tracker[job_id] = {
            'current': 0,
            'total': 100,
            'status': 'Starting...',
            'percentage': 0,
            'user_email': email,
            'page_usage': page_usage
        }
        
        # Get the background processing function
        process_document_background = get_process_document_background()
        
        # Process in background thread
        thread = threading.Thread(
            target=process_document_background,
            args=(GLOBAL_GEMINI_EXECUTOR, job_id, mode, input_path, language, source_lang, target_lang, filename, email)
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


@document_bp.route('/progress/<job_id>')
def get_progress(job_id):
    """Get progress for a job"""
    if job_id in progress_tracker:
        return jsonify(progress_tracker[job_id])
    return jsonify({'error': 'Job not found'}), 404


@document_bp.route('/download/<filename>')
def download_file(filename):
    """Download processed file"""
    try:
        file_path = os.path.join(current_app.config['OUTPUT_FOLDER'], filename)
        if os.path.exists(file_path):
            return send_file(file_path, as_attachment=True, download_name=filename)
        return "File not found", 404
    except Exception as e:
        return str(e), 500


@document_bp.route('/send-document/<job_id>', methods=['POST'])
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
        output_path = os.path.join(current_app.config['OUTPUT_FOLDER'], output_file)
        
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
