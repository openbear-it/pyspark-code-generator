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
LLM_MAX_OUTPUT_TOKENS = int(os.getenv("LLM_MAX_OUTPUT_TOKENS", "4096"))
LLM_MAX_CONTINUATIONS = int(os.getenv("LLM_MAX_CONTINUATIONS", "2"))
LLM_VERIFY_SSL = os.getenv("LLM_VERIFY_SSL", "false").lower() in {"1", "true", "yes", "on"}