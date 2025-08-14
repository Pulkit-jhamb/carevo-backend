import os
import time
from dotenv import load_dotenv

load_dotenv()  # <-- Ensure .env is loaded before reading keys

GEMINI_KEYS = os.getenv("GEMINI_API_KEYS", "").split(",")
DELAY_MINUTES = int(os.getenv("GEMINI_KEY_DELAY_MINUTES", "10"))
if not GEMINI_KEYS or GEMINI_KEYS == [""]:
    raise Exception("No Gemini API keys found in .env")

def get_active_gemini_key():
    # Cycle keys every DELAY_MINUTES
    now = int(time.time())
    idx = (now // (DELAY_MINUTES * 60)) % len(GEMINI_KEYS)
    return GEMINI_KEYS[idx].strip()