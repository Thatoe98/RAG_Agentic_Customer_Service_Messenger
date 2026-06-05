import os
from dotenv import load_dotenv

load_dotenv()

# Facebook
FB_PAGE_ACCESS_TOKEN = os.environ["FB_PAGE_ACCESS_TOKEN"]
FB_VERIFY_TOKEN = os.environ["FB_VERIFY_TOKEN"]
FB_APP_SECRET = os.environ.get("FB_APP_SECRET", "")

# Gemini
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
GEMINI_MODEL = "gemini-3-flash-preview"

# RAG / knowledge base
EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "gemini-embedding-001")
EMBEDDING_DIM = int(os.environ.get("EMBEDDING_DIM", "768"))
DB_PATH = os.environ.get("DB_PATH", "data/knowledge.db")

# Admin webapp
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")
SESSION_SECRET = os.environ.get("SESSION_SECRET", "change-me-in-production")

# Telegram
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_SUPERVISOR_CHAT_ID = os.environ["TELEGRAM_SUPERVISOR_CHAT_ID"]

# Bot behavior
GREETING_MESSAGE = os.environ.get(
    "GREETING_MESSAGE",
    "Hi there! Thanks for reaching out. How can I help you today?",
)
ADMIN_SILENCE_TIMEOUT = int(os.environ.get("ADMIN_SILENCE_TIMEOUT_MINUTES", "30")) * 60
