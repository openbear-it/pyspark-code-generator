import os
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent
load_dotenv(ROOT_DIR.parent / ".env")

DATABASE_PATH = Path(os.getenv("DATABASE_PATH", ROOT_DIR.parent / "data" / "chats.db"))
MAX_FILE_SIZE = 2 * 1024 * 1024
LLM_BASE_URL = os.getenv("LLM_BASE_URL")
LLM_API_KEY = os.getenv("LLM_API_KEY")
LLM_MODEL = os.getenv("LLM_MODEL")