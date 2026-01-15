import os
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure
import logging

logger = logging.getLogger(__name__)
from dotenv import load_dotenv

load_dotenv() 

# MongoDB connection
MONGODB_URI = os.getenv('MONGODB_URI')
DB_NAME = 'Cluster0'

# Global MongoDB client
mongo_client = None
db = None

def get_database():
    """Get MongoDB database instance"""
    global mongo_client, db
    
    if db is None:
        try:
            mongo_client = MongoClient(MONGODB_URI)
            # Test connection
            mongo_client.admin.command('ping')
            db = mongo_client[DB_NAME]
            logger.info(f"Connected to MongoDB: {DB_NAME}")
            
            # Create indexes for better performance
            db.users.create_index("email", unique=True)
            db.trial_usage.create_index([("email", 1), ("mode", 1)], unique=True)
            
        except ConnectionFailure as e:
            logger.error(f"Failed to connect to MongoDB: {e}")
            raise
    
    return db

def get_user_collection():
    """Get users collection"""
    db = get_database()
    return db.users

def get_trial_usage_collection():
    """Get trial usage collection"""
    db = get_database()
    return db.trial_usage

