import os
import threading
import logging
from config import UPLOAD_FOLDER, OUTPUT_FOLDER, MAX_CONTENT_LENGTH, progress_tracker
from processors import ProofreadingProcessor, TranslationProcessor, OCRProcessor
from document_handler import DocumentHandler
from utils import send_document_email


logger = logging.getLogger(__name__)


def process_document_background(thread_pool, job_id, mode, input_path, language, source_lang, target_lang, original_filename, user_email='', user_prompt=''):
    """Background processing function"""
    try:
        # Get API keys from environment
        vision_api_key = os.getenv('GOOGLE_VISION_API_KEY')
        gemini_api_key = os.getenv('GEMINI_API_KEY')
        
        output_filename = None
        # Extract base name from original filename (without extension)
        base_name = os.path.splitext(original_filename)[0]
        
        if mode == 1:
            # OCR Only
            ocr = OCRProcessor(vision_api_key, job_id)
            text = ocr.perform_ocr(input_path)
            output_filename = f"{base_name}_{job_id}_ocr_raw.docx"
            output_path = os.path.join(OUTPUT_FOLDER, output_filename)
            DocumentHandler.save_raw_docx(text, output_path)
            
        elif mode == 2:
            # OCR + Proofread
            ocr = OCRProcessor(vision_api_key, job_id)
            text = ocr.perform_ocr(input_path)
            text = text.replace('\n', '\r')
            
            # Use proofread_full_text() instead of manual chunking
            proofreader = ProofreadingProcessor(gemini_api_key, job_id=job_id, executor=thread_pool)
            corrected_text = proofreader.proofread_full_text(text, language)
            
            # Convert back to chunks for document formatting (if needed)
            corrected_chunks = corrected_text.split('\n')
            
            output_filename = f"{base_name}_{job_id}_ocr_proofread.docx"
            output_path = os.path.join(OUTPUT_FOLDER, output_filename)
            DocumentHandler.create_formatted_document(corrected_chunks, output_path, language, "OCR + Proofread")
            
        elif mode == 3:
            # Proofread Only
            content = DocumentHandler.read_docx(input_path)
            
            # Use proofread_full_text() instead of manual chunking
            proofreader = ProofreadingProcessor(gemini_api_key, job_id=job_id, executor=thread_pool)
            corrected_text = proofreader.proofread_full_text(content, language)
            
            # Convert back to chunks for document formatting (if needed)
            corrected_chunks = corrected_text.split('\n\n')
            
            output_filename = f"{base_name}_{job_id}_proofread.docx"
            output_path = os.path.join(OUTPUT_FOLDER, output_filename)
            DocumentHandler.create_formatted_document(corrected_chunks, output_path, language, "Proofread")
            
        elif mode == 4:
            # OCR + Translation
            ocr = OCRProcessor(vision_api_key, job_id)
            text = ocr.perform_ocr(input_path)
            
            # Use translate_full_text() instead of manual chunking
            translator = TranslationProcessor(gemini_api_key, job_id=job_id, executor=thread_pool)
            translated_text = translator.translate_full_text(text, source_lang, target_lang)
            
            # Convert back to chunks for document formatting (if needed)
            translated_chunks = translated_text.split('\n\n')
            
            output_filename = f"{base_name}_{job_id}_ocr_translated_{target_lang}.docx"
            output_path = os.path.join(OUTPUT_FOLDER, output_filename)
            DocumentHandler.create_formatted_document(translated_chunks, output_path, target_lang, "OCR + Translated")
            
        elif mode == 5:
            # Translation Only
            content = DocumentHandler.read_docx(input_path)
            
            # Use translate_full_text() instead of manual chunking
            translator = TranslationProcessor(gemini_api_key, job_id=job_id, executor=thread_pool)
            translated_text = translator.translate_full_text(content, source_lang, target_lang)
            
            # Convert back to chunks for document formatting (if needed)
            translated_chunks = translated_text.split('\n\n')
            
            output_filename = f"{base_name}_{job_id}_translated_{target_lang}.docx"
            output_path = os.path.join(OUTPUT_FOLDER, output_filename)
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
                output_path = os.path.join(OUTPUT_FOLDER, output_filename)
                email_sent = send_document_email(user_email, output_path, job_id)
                if email_sent:
                    logger.info(f"Auto-sent document email to {user_email} for job {job_id}")
                else:
                    logger.warning(f"Failed to auto-send email to {user_email} for job {job_id}")
            except Exception as e:
                logger.error(f"Error auto-sending email for job {job_id}: {e}")
                # Don't fail the job if email fails - user can still download
        
        # Schedule file cleanup after 30 minutes
        output_path = os.path.join(OUTPUT_FOLDER, output_filename) if output_filename else None
        schedule_file_cleanup(input_path, output_path, job_id)
        
    except Exception as e:
        logger.error(f"Error processing document: {e}")
        progress_tracker[job_id] = {
            'current': 0,
            'total': 100,
            'status': f'Error: {str(e)}',
            'percentage': 0,
            'error': True
        }

# File cleanup delay (30 minutes in seconds)
FILE_CLEANUP_DELAY = 30 * 60  # 30 minutes


def schedule_file_cleanup(input_path, output_path, job_id):
    """Schedule deletion of input and output files after delay."""
    def cleanup_files():
        try:
            # Delete input file
            if input_path and os.path.exists(input_path):
                os.remove(input_path)
                logger.info(f"Cleaned up input file for job {job_id}")
            
            # Delete output file
            if output_path and os.path.exists(output_path):
                os.remove(output_path)
                logger.info(f"Cleaned up output file for job {job_id}")
            
            # Clean up progress tracker entry
            if job_id in progress_tracker:
                del progress_tracker[job_id]
                logger.info(f"Cleaned up progress tracker for job {job_id}")
                
        except Exception as e:
            logger.error(f"Error during file cleanup for job {job_id}: {e}")
    
    # Schedule cleanup after delay
    timer = threading.Timer(FILE_CLEANUP_DELAY, cleanup_files)
    timer.daemon = True
    timer.start()
    logger.info(f"Scheduled file cleanup for job {job_id} in {FILE_CLEANUP_DELAY // 60} minutes")