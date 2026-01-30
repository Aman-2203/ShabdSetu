import os
import logging
from datetime import timedelta

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)

# Flask app configuration
UPLOAD_FOLDER = 'uploads'
OUTPUT_FOLDER = 'outputs'
MAX_CONTENT_LENGTH = 50 * 1024 * 1024  # 50MB max file size
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'
PERMANENT_SESSION_LIFETIME = timedelta(hours=24)

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
