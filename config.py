import os
import logging

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)

# Flask app configuration
UPLOAD_FOLDER = 'uploads'
OUTPUT_FOLDER = 'outputs'
MAX_CONTENT_LENGTH = 700 * 1024 * 1024  # 50MB max file size

# Create necessary folders
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

# Global progress tracking
# Structure: {job_id: {
#     'current': int, 'total': int, 'status': str, 'percentage': int,
#     'output_file': str (when complete),
#     'user_email': str (stored for email functionality),
#     'page_usage': float (actual pages/chars used)
# }}
progress_tracker = {}