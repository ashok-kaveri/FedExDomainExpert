import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).parent

# Ollama
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
DOMAIN_EXPERT_MODEL = os.getenv("DOMAIN_EXPERT_MODEL", "qwen2.5:14b")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "nomic-embed-text")

# ChromaDB
CHROMA_PATH = str(BASE_DIR / "data" / "chroma_db")
CHROMA_COLLECTION = "fedex_knowledge"

# Knowledge sources
PLUGINHIVE_BASE_URL = "https://www.pluginhive.com/set-up-shopify-fedex-rates-labels-tracking-app/"
FEDEX_API_DOCS_URL = "https://developer.fedex.com/api/en-us/catalog.html"
AUTOMATION_CODEBASE_PATH = os.getenv(
    "AUTOMATION_CODEBASE_PATH",
    str(BASE_DIR.parent / "fedex-test-automation"),
)

# Google Sheets
# NOTE: The default below is the real FedEx test cases sheet.
# Override via GOOGLE_SHEETS_ID env var or credentials.json for private access.
GOOGLE_SHEETS_ID = os.getenv(
    "GOOGLE_SHEETS_ID", "1i7YQWLSmiJ0wK-lAoAmaNe3gNvbm9T0ry3TwWSxB-Wc"
)
GOOGLE_CREDENTIALS_PATH = os.getenv(
    "GOOGLE_CREDENTIALS_PATH", str(BASE_DIR / "credentials.json")
)

# RAG settings
CHUNK_SIZE = 500
CHUNK_OVERLAP = 50
PLUGINHIVE_MAX_PAGES = int(os.getenv("PLUGINHIVE_MAX_PAGES", "200"))
TOP_K_RESULTS = 5
MEMORY_WINDOW = 10
