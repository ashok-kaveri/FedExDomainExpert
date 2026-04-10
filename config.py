import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).parent

# Anthropic / Claude
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
# Primary model — deep reasoning, code gen, visual exploration
CLAUDE_SONNET_MODEL = os.getenv("CLAUDE_SONNET_MODEL", "claude-sonnet-4-6")
# Fast/cheap model — card processing, feature detection, lightweight tasks
CLAUDE_HAIKU_MODEL = os.getenv("CLAUDE_HAIKU_MODEL", "claude-haiku-4-5-20251001")
# Default model used by the domain expert chat
DOMAIN_EXPERT_MODEL = os.getenv("DOMAIN_EXPERT_MODEL", CLAUDE_SONNET_MODEL)

# Ollama — kept ONLY for embeddings (Anthropic has no embedding model)
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "nomic-embed-text")

# ChromaDB
CHROMA_PATH = str(BASE_DIR / "data" / "chroma_db")
CHROMA_COLLECTION = "fedex_knowledge"
# Separate collection for source code (backend + frontend)
CHROMA_CODE_COLLECTION = "fedex_code_knowledge"

# Source code paths (set via .env or indexed via the dashboard)
BACKEND_CODE_PATH  = os.getenv("BACKEND_CODE_PATH",  str(Path.home() / "Documents" / "fedex-Backend-Code"  / "shopifyfedexapp"))
FRONTEND_CODE_PATH = os.getenv("FRONTEND_CODE_PATH", str(Path.home() / "Documents" / "fedex-Frontend-Code" / "shopify-fedex-web-client"))

# File extensions to index from source code directories
CODE_FILE_EXTENSIONS = [".ts", ".tsx", ".js", ".jsx", ".php", ".java", ".py", ".go", ".rb", ".cs"]

# Knowledge sources
PLUGINHIVE_BASE_URL = "https://www.pluginhive.com/set-up-shopify-fedex-rates-labels-tracking-app/"

# Guaranteed seed URLs — always crawled first before BFS expansion.
# These are high-value FAQ/guide pages that may not be reachable within the
# page limit from the base URL alone.
PLUGINHIVE_SEED_URLS: list[str] = [
    # Core knowledge base
    "https://www.pluginhive.com/knowledge-base/setting-up-shopify-fedex-app/",
    "https://www.pluginhive.com/knowledge-base/install-shopify-fedex-app/",
    "https://www.pluginhive.com/knowledge-base/troubleshooting-shopify-fedex-shipping-app/",
    "https://www.pluginhive.com/knowledge-base/understanding-fedex-shipping-rates-in-your-shopify-store/",
    "https://www.pluginhive.com/knowledge-base/fedex-one-rate-shipping-with-shopify/",
    "https://www.pluginhive.com/knowledge-base/fedex-freight-shipping-with-shopify/",
    "https://www.pluginhive.com/knowledge-base/how-to-set-up-shopify-shipping-for-fedex-special-shipments/",
    "https://www.pluginhive.com/knowledge-base/pack-products-optimally-and-save-shipping-costs-with-shopify-fedex-app/",
    # Shopify FedEx FAQ pages
    "https://www.pluginhive.com/fedex-label-generation-api-errors-multi-carrier-shipping-label-app-for-shopify-faqs/",
    "https://www.pluginhive.com/fedex-freight-rate-issues-on-shopify-faqs/",
    "https://www.pluginhive.com/fedex-billing-clarifications-in-shopify-faqs/",
    "https://www.pluginhive.com/fedex-freight-account-integration-on-shopify-faqs/",
    "https://www.pluginhive.com/fedex-customs-documentation-in-shopify-faqs/",
    "https://www.pluginhive.com/fedex-shipping-payments-in-shopify-faqs/",
    "https://www.pluginhive.com/fedex-shipping-package-management-and-configuration-on-shopify-faqs/",
    "https://www.pluginhive.com/shopify-shipping-location-configuration-for-fedex-rates-faqs/",
    "https://www.pluginhive.com/shopify-carrier-calculated-shipping-setup-for-fedex-faqs/",
    "https://www.pluginhive.com/fedex-account-switching-and-multi-account-setup-in-shopify-faqs/",
    "https://www.pluginhive.com/fedex-settings-update-and-sync-confirmation-in-shopify-faqs/",
    "https://www.pluginhive.com/fedex-shipping-errors-multi-carrier-shipping-label-app-for-shopify-faqs/",
    # High-value guide pages
    "https://www.pluginhive.com/shopify-fedex-shipping-cost-updates/",
    "https://www.pluginhive.com/fedex-pickups-for-shopify/",
    "https://www.pluginhive.com/fedex-freight-shipping-in-shopify/",
    "https://www.pluginhive.com/fedex-shipping-with-shopify/",
    "https://www.pluginhive.com/shopify-fedex-shipping-guide/",
    "https://www.pluginhive.com/product/shopify-fedex-shipping-app-with-print-label-tracking/",
]

SHOPIFY_APP_STORE_URL = "https://apps.shopify.com/fedex-shipping"

FEDEX_API_DOCS_URL = "https://developer.fedex.com/api/en-us/catalog.html"
AUTOMATION_CODEBASE_PATH = os.getenv(
    "AUTOMATION_CODEBASE_PATH",
    str(BASE_DIR.parent / "fedex-test-automation"),
)

# Internal FedEx wiki (markdown knowledge base)
WIKI_PATH = os.getenv(
    "WIKI_PATH",
    str(Path.home() / "Documents" / "fedex-wiki"),
)

# PDF test cases
PDF_TEST_CASES_PATH = os.getenv(
    "PDF_TEST_CASES_PATH",
    str(Path.home() / "Downloads" / "FedExApp Master sheet .pdf"),
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
TOP_K_RESULTS = 8
MEMORY_WINDOW = 10
