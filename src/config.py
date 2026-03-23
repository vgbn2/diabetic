import os
from dotenv import load_dotenv

# Load environment variables from a .env file if it exists
load_dotenv()

class Config:
    """Configuration class for Bio-Quant."""
    
    # Nightscout Configuration
    NIGHTSCOUT_URL = os.getenv("NIGHTSCOUT_URL", "https://your-nightscout-url.herokuapp.com")
    NIGHTSCOUT_API_SECRET = os.getenv("NIGHTSCOUT_API_SECRET", "")
    
    # Ensure URL doesn't have a trailing slash
    if NIGHTSCOUT_URL.endswith('/'):
        NIGHTSCOUT_URL = NIGHTSCOUT_URL[:-1]
    
    # Feature Engineering defaults
    FATIGUE_INDEX_THRESHOLD = 1.3
    
    # Telegram Bot
    TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
    
    # External APIs
    GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
