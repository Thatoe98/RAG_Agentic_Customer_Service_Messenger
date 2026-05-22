import os
from dotenv import load_dotenv

load_dotenv()

# Facebook
FB_PAGE_ACCESS_TOKEN = os.environ["FB_PAGE_ACCESS_TOKEN"]
FB_VERIFY_TOKEN = os.environ["FB_VERIFY_TOKEN"]
FB_APP_SECRET = os.environ.get("FB_APP_SECRET", "")

# Gemini
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
GEMINI_MODEL = "gemini-2.0-flash"

# Google Drive
GOOGLE_SERVICE_ACCOUNT_JSON = os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"]
GOOGLE_DRIVE_FOLDER_ID = os.environ.get("GOOGLE_DRIVE_FOLDER_ID", "")

# Telegram
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_SUPERVISOR_CHAT_ID = os.environ["TELEGRAM_SUPERVISOR_CHAT_ID"]

# Bot behavior
GREETING_MESSAGE = os.environ.get(
    "GREETING_MESSAGE",
    "Hi there! Thanks for reaching out. How can I help you today?",
)
