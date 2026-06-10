import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
_owner_str = os.getenv("OWNER_ID", "0")
OWNER_ID = int(_owner_str) if _owner_str.isdigit() else 0
MAX_MESSAGE_LENGTH = 500
