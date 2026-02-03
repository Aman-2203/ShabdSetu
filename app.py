import os
import atexit
import logging
from flask import Flask


from config import (
    UPLOAD_FOLDER, OUTPUT_FOLDER, MAX_CONTENT_LENGTH,
    SESSION_COOKIE_HTTPONLY, SESSION_COOKIE_SAMESITE, PERMANENT_SESSION_LIFETIME
)
from auth import start_otp_cleanup_thread
from routes import register_blueprints
from routes.document_routes import cleanup_executor

from dotenv import load_dotenv

load_dotenv() 

logger = logging.getLogger(__name__)

# Start OTP cleanup thread
start_otp_cleanup_thread()

atexit.register(cleanup_executor)
logger.info(f"Initialized global Gemini executor with 40 workers")

def create_app():
    # Flask app setup
    app = Flask(__name__)
    app.secret_key = os.getenv('FLASK_SECRET_KEY', os.urandom(24))

    # Apply Flask configuration from config.py
    
    app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
    app.config['OUTPUT_FOLDER'] = OUTPUT_FOLDER
    app.config['MAX_CONTENT_LENGTH'] = MAX_CONTENT_LENGTH
    app.config['SESSION_COOKIE_HTTPONLY'] = SESSION_COOKIE_HTTPONLY
    app.config['SESSION_COOKIE_SAMESITE'] = SESSION_COOKIE_SAMESITE
    app.config['PERMANENT_SESSION_LIFETIME'] = PERMANENT_SESSION_LIFETIME
    app.config['TEST_OTP'] = False
    app.config['TEST_PAYMENT'] = False

    app.env = os.getenv("ENV")
    
    # Register all route blueprints
    register_blueprints(app)

    return app
