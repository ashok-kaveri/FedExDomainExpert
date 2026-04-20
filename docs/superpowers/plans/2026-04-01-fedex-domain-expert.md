# FedEx Domain Expert — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local RAG-powered domain expert chat system for the FedEx Shopify App using qwen2.5:14b, ChromaDB, and Streamlit.

**Architecture:** Conversational RAG — documents are scraped/loaded, chunked, embedded with `nomic-embed-text`, and stored in ChromaDB. Each user question is reformulated with chat history, matched against the vector store, and answered by qwen2.5:14b with retrieved context. A Streamlit web UI provides the chat interface; a FastAPI server provides programmatic access.

**Tech Stack:** Python 3.11+, LangChain, LangChain-Ollama, ChromaDB, Streamlit, FastAPI, BeautifulSoup4, gspread, pytest

---

## File Map

| File | Responsibility |
|---|---|
| `config.py` | All settings — model names, paths, URLs, chunk sizes |
| `rag/vectorstore.py` | ChromaDB init, add documents, similarity search, clear |
| `rag/prompts.py` | Domain expert system prompt + condense-question prompt |
| `rag/chain.py` | LangChain ConversationalRetrievalChain builder + `ask()` helper |
| `ingest/web_scraper.py` | Crawl PluginHive docs + scrape FedEx API catalog page |
| `ingest/codebase_loader.py` | Load Playwright spec/page/helper files from automation repo |
| `ingest/sheets_loader.py` | Load Google Sheets test cases (service account or public CSV) |
| `ingest/run_ingest.py` | Master runner: clear → load all sources → embed → store |
| `ui/chat_app.py` | Streamlit web chat UI at localhost:8501 |
| `api/server.py` | FastAPI `/ask` and `/health` endpoints at localhost:8000 |
| `tests/conftest.py` | pytest fixtures shared across tests |
| `tests/test_vectorstore.py` | Unit tests for vectorstore operations (needs Ollama) |
| `tests/test_codebase_loader.py` | Unit tests for codebase loader (no Ollama needed) |
| `tests/test_api.py` | Unit tests for FastAPI endpoints (mocked chain) |

---

## Task 1: Project Bootstrap

**Files:**
- Create: `config.py`
- Create: `requirements.txt`
- Create: `.gitignore`
- Create: `.env.example`
- Create: `ingest/__init__.py`, `rag/__init__.py`, `ui/__init__.py`, `api/__init__.py`, `tests/__init__.py`
- Create: `data/chroma_db/.gitkeep`

- [ ] **Step 1: Create the full directory structure**

```bash
cd ~/Documents/Fed-Ex-automation/FedexDomainExpert

mkdir -p ingest rag ui api tests data/chroma_db

touch ingest/__init__.py rag/__init__.py ui/__init__.py api/__init__.py tests/__init__.py
touch data/chroma_db/.gitkeep
```

- [ ] **Step 2: Create `.gitignore`**

```
# Python
__pycache__/
*.py[cod]
*.egg-info/
.venv/
venv/
dist/
build/

# Data (vector store — large, rebuild with run_ingest.py)
data/chroma_db/

# Secrets
.env
credentials.json

# Streamlit
.streamlit/

# OS
.DS_Store
```

Write this to `.gitignore`.

- [ ] **Step 3: Create `.env.example`**

```env
# Ollama
OLLAMA_BASE_URL=http://localhost:11434
DOMAIN_EXPERT_MODEL=qwen2.5:14b
EMBEDDING_MODEL=nomic-embed-text

# Paths
AUTOMATION_CODEBASE_PATH=
BACKEND_CODE_PATH=
FRONTEND_CODE_PATH=
SHOPIFY_ACTIONS_PATH=
WIKI_PATH=
PDF_TEST_CASES_PATH=

# Google Sheets (optional — leave blank to use public CSV fallback)
GOOGLE_SHEETS_ID=1i7YQWLSmiJ0wK-lAoAmaNe3gNvbm9T0ry3TwWSxB-Wc
GOOGLE_CREDENTIALS_PATH=
```

Write this to `.env.example`.

- [ ] **Step 4: Create `config.py`**

```python
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
AUTOMATION_CODEBASE_PATH = os.getenv("AUTOMATION_CODEBASE_PATH", "")

# Google Sheets
GOOGLE_SHEETS_ID = os.getenv(
    "GOOGLE_SHEETS_ID", "1i7YQWLSmiJ0wK-lAoAmaNe3gNvbm9T0ry3TwWSxB-Wc"
)
GOOGLE_CREDENTIALS_PATH = os.getenv("GOOGLE_CREDENTIALS_PATH", "")

# RAG settings
CHUNK_SIZE = 500
CHUNK_OVERLAP = 50
TOP_K_RESULTS = 5
MEMORY_WINDOW = 10
```

Write this to `config.py`.

- [ ] **Step 5: Create `requirements.txt`**

```
# LangChain
langchain>=0.3.0
langchain-community>=0.3.0
langchain-ollama>=0.2.0

# Vector DB
chromadb>=0.5.0

# Web UI
streamlit>=1.39.0

# API
fastapi>=0.115.0
uvicorn>=0.32.0

# Scraping
beautifulsoup4>=4.12.3
requests>=2.32.3

# Google Sheets
gspread>=6.1.2
google-auth>=2.35.0

# Utils
python-dotenv>=1.0.1

# Testing
pytest>=8.3.3
httpx>=0.27.2
```

Write this to `requirements.txt`.

- [ ] **Step 6: Install dependencies**

```bash
cd ~/Documents/Fed-Ex-automation/FedexDomainExpert
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Expected: All packages install without errors. `pip show langchain chromadb streamlit` should show installed versions.

- [ ] **Step 7: Commit**

```bash
cd ~/Documents/Fed-Ex-automation/FedexDomainExpert
git add -A
git commit -m "feat: project bootstrap — config, requirements, structure"
```

---

## Task 2: Vector Store

**Files:**
- Create: `rag/vectorstore.py`
- Create: `tests/conftest.py`
- Create: `tests/test_vectorstore.py`

- [ ] **Step 1: Write the failing test**

Create `tests/conftest.py`:

```python
import pytest


@pytest.fixture
def temp_chroma(monkeypatch, tmp_path):
    """Point ChromaDB at a temp directory so tests don't pollute real data."""
    import config
    monkeypatch.setattr(config, "CHROMA_PATH", str(tmp_path / "chroma"))
    return str(tmp_path / "chroma")
```

Create `tests/test_vectorstore.py`:

```python
from langchain.schema import Document


def test_add_and_search_documents(temp_chroma):
    from rag.vectorstore import clear_collection, add_documents, search

    clear_collection()

    docs = [
        Document(
            page_content="FedEx label generation creates shipping labels via the FedEx REST API.",
            metadata={"source": "test", "source_url": "test://doc1", "source_type": "test"},
        ),
        Document(
            page_content="The FedEx Shopify App supports Ground, Express, and SmartPost services.",
            metadata={"source": "test", "source_url": "test://doc2", "source_type": "test"},
        ),
    ]
    add_documents(docs)

    results = search("label generation", k=1)
    assert len(results) == 1
    assert "label" in results[0].page_content.lower()


def test_clear_collection_removes_documents(temp_chroma):
    from rag.vectorstore import clear_collection, add_documents, search

    docs = [
        Document(
            page_content="Pickup scheduling allows merchants to request a FedEx courier.",
            metadata={"source": "test", "source_url": "test://doc3", "source_type": "test"},
        )
    ]
    add_documents(docs)
    clear_collection()

    results = search("pickup scheduling", k=5)
    assert len(results) == 0
```

- [ ] **Step 2: Run the test — verify it fails**

```bash
cd ~/Documents/Fed-Ex-automation/FedexDomainExpert
source .venv/bin/activate
pytest tests/test_vectorstore.py -v
```

Expected: `ImportError: cannot import name 'clear_collection' from 'rag.vectorstore'` (module doesn't exist yet).

- [ ] **Step 3: Implement `rag/vectorstore.py`**

```python
import chromadb
from langchain_ollama import OllamaEmbeddings
from langchain_community.vectorstores import Chroma
from langchain.schema import Document

import config


def get_embeddings() -> OllamaEmbeddings:
    return OllamaEmbeddings(
        model=config.EMBEDDING_MODEL,
        base_url=config.OLLAMA_BASE_URL,
    )


def get_vectorstore() -> Chroma:
    return Chroma(
        collection_name=config.CHROMA_COLLECTION,
        embedding_function=get_embeddings(),
        persist_directory=config.CHROMA_PATH,
    )


def add_documents(documents: list[Document]) -> None:
    """Embed and store documents in ChromaDB."""
    vectorstore = get_vectorstore()
    vectorstore.add_documents(documents)


def clear_collection() -> None:
    """Delete and recreate the ChromaDB collection."""
    client = chromadb.PersistentClient(path=config.CHROMA_PATH)
    try:
        client.delete_collection(config.CHROMA_COLLECTION)
    except Exception:
        pass  # Collection didn't exist — that's fine


def search(query: str, k: int = 5) -> list[Document]:
    """Return top-k documents most relevant to the query. Returns [] if collection is empty."""
    try:
        vectorstore = get_vectorstore()
        return vectorstore.similarity_search(query, k=k)
    except Exception:
        return []
```

- [ ] **Step 4: Run the tests — verify they pass**

```bash
pytest tests/test_vectorstore.py -v
```

Expected output:
```
tests/test_vectorstore.py::test_add_and_search_documents PASSED
tests/test_vectorstore.py::test_clear_collection_removes_documents PASSED
2 passed
```

Note: These tests call Ollama to embed text — Ollama must be running (`ollama serve`).

- [ ] **Step 5: Commit**

```bash
git add rag/vectorstore.py tests/conftest.py tests/test_vectorstore.py
git commit -m "feat: ChromaDB vector store with add, search, clear operations"
```

---

## Task 3: Domain Expert Prompts

**Files:**
- Create: `rag/prompts.py`

- [ ] **Step 1: Create `rag/prompts.py`**

```python
from langchain.prompts import PromptTemplate

DOMAIN_EXPERT_SYSTEM = """You are a senior domain expert for the FedEx Shopify App built by PluginHive.

You have deep knowledge of:
- Every feature, setting, and workflow in the FedEx Shopify App
- FedEx API services: rates, label generation, tracking, pickup, returns
- The Playwright + TypeScript test automation suite for this app
- All test cases, expected behaviours, and acceptance criteria

Rules you MUST follow:
1. Answer ONLY from the provided context below. Do not use outside knowledge.
2. If the answer is not in the context, say exactly: "I don't have that information in my knowledge base. You may want to check [suggest a relevant source]."
3. Always end your answer with "Source: [source name]" citing where the information came from.
4. Use bullet points for steps or lists. Be concise but complete.
5. When asked to "take me on a tour", walk through the app section by section in this order: Rates & Carriers → Label Generation → Return Labels → Packaging → Pickup → Products & Settings.
6. Never invent FedEx API behaviour. Only state what is explicitly in the retrieved context.

Context from knowledge base:
{context}"""

QA_PROMPT = PromptTemplate(
    input_variables=["context", "question"],
    template=DOMAIN_EXPERT_SYSTEM + "\n\nQuestion: {question}\n\nAnswer:",
)

CONDENSE_QUESTION_PROMPT = PromptTemplate(
    input_variables=["chat_history", "question"],
    template="""Given the conversation history below and a follow-up question, rewrite the follow-up as a standalone question that makes sense without the history. If the question already makes sense on its own, return it unchanged.

Chat History:
{chat_history}

Follow-up question: {question}

Standalone question:""",
)
```

- [ ] **Step 2: Verify the prompts load correctly**

```bash
cd ~/Documents/Fed-Ex-automation/FedexDomainExpert
source .venv/bin/activate
python -c "from rag.prompts import QA_PROMPT, CONDENSE_QUESTION_PROMPT; print('QA_PROMPT variables:', QA_PROMPT.input_variables); print('CONDENSE variables:', CONDENSE_QUESTION_PROMPT.input_variables)"
```

Expected output:
```
QA_PROMPT variables: ['context', 'question']
CONDENSE variables: ['chat_history', 'question']
```

- [ ] **Step 3: Commit**

```bash
git add rag/prompts.py
git commit -m "feat: domain expert persona and RAG prompt templates"
```

---

## Task 4: RAG Chain

**Files:**
- Create: `rag/chain.py`
- Create: `tests/test_chain.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_chain.py`:

```python
from unittest.mock import MagicMock, patch
from langchain.schema import Document


def test_ask_returns_answer_and_sources():
    mock_chain = MagicMock()
    mock_chain.invoke.return_value = {
        "answer": "Label generation creates a FedEx shipping label via the REST API.",
        "source_documents": [
            Document(
                page_content="Label generation workflow...",
                metadata={"source_url": "https://pluginhive.com/label-gen"},
            ),
            Document(
                page_content="FedEx API label endpoint...",
                metadata={"source_url": "https://pluginhive.com/label-gen"},
            ),
        ],
    }

    from rag.chain import ask

    result = ask("How does label generation work?", mock_chain)

    assert "answer" in result
    assert "sources" in result
    assert result["answer"] == "Label generation creates a FedEx shipping label via the REST API."
    assert "https://pluginhive.com/label-gen" in result["sources"]


def test_ask_deduplicates_sources():
    mock_chain = MagicMock()
    mock_chain.invoke.return_value = {
        "answer": "Some answer.",
        "source_documents": [
            Document(page_content="chunk 1", metadata={"source_url": "https://same-url.com"}),
            Document(page_content="chunk 2", metadata={"source_url": "https://same-url.com"}),
        ],
    }

    from rag.chain import ask

    result = ask("Any question", mock_chain)
    assert result["sources"].count("https://same-url.com") == 1
```

- [ ] **Step 2: Run the test — verify it fails**

```bash
pytest tests/test_chain.py -v
```

Expected: `ImportError: cannot import name 'ask' from 'rag.chain'`

- [ ] **Step 3: Implement `rag/chain.py`**

```python
from langchain.chains import ConversationalRetrievalChain
from langchain.memory import ConversationBufferWindowMemory
from langchain.schema import Document
from langchain_ollama import OllamaLLM

import config
from rag.vectorstore import get_vectorstore
from rag.prompts import QA_PROMPT, CONDENSE_QUESTION_PROMPT


def get_llm() -> OllamaLLM:
    return OllamaLLM(
        model=config.DOMAIN_EXPERT_MODEL,
        base_url=config.OLLAMA_BASE_URL,
        temperature=0.1,
    )


def build_chain(
    memory: ConversationBufferWindowMemory | None = None,
) -> ConversationalRetrievalChain:
    """Build and return a ConversationalRetrievalChain backed by ChromaDB."""
    llm = get_llm()
    vectorstore = get_vectorstore()
    retriever = vectorstore.as_retriever(
        search_kwargs={"k": config.TOP_K_RESULTS}
    )

    if memory is None:
        memory = ConversationBufferWindowMemory(
            k=config.MEMORY_WINDOW,
            memory_key="chat_history",
            return_messages=True,
            output_key="answer",
        )

    return ConversationalRetrievalChain.from_llm(
        llm=llm,
        retriever=retriever,
        memory=memory,
        condense_question_prompt=CONDENSE_QUESTION_PROMPT,
        combine_docs_chain_kwargs={"prompt": QA_PROMPT},
        return_source_documents=True,
        verbose=False,
    )


def ask(question: str, chain: ConversationalRetrievalChain) -> dict:
    """
    Ask a question and return the answer with deduplicated source URLs.

    Returns:
        {"answer": str, "sources": list[str]}
    """
    result = chain.invoke({"question": question})
    source_docs: list[Document] = result.get("source_documents", [])
    sources = list(
        {
            doc.metadata.get("source_url", doc.metadata.get("source", "Unknown"))
            for doc in source_docs
        }
    )
    return {"answer": result["answer"], "sources": sources}
```

- [ ] **Step 4: Run the tests — verify they pass**

```bash
pytest tests/test_chain.py -v
```

Expected output:
```
tests/test_chain.py::test_ask_returns_answer_and_sources PASSED
tests/test_chain.py::test_ask_deduplicates_sources PASSED
2 passed
```

- [ ] **Step 5: Commit**

```bash
git add rag/chain.py tests/test_chain.py
git commit -m "feat: conversational RAG chain with memory and source deduplication"
```

---

## Task 5: Web Scraper

**Files:**
- Create: `ingest/web_scraper.py`

- [ ] **Step 1: Create `ingest/web_scraper.py`**

```python
import time
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from langchain.schema import Document
from langchain.text_splitter import RecursiveCharacterTextSplitter

import config


def _make_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0 FedexDomainExpert/1.0"})
    return session


def _scrape_text(url: str, session: requests.Session) -> str:
    """Download a page and return its cleaned plain text."""
    try:
        resp = session.get(url, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        for tag in soup.find_all(["nav", "footer", "script", "style", "header"]):
            tag.decompose()
        return soup.get_text(separator="\n", strip=True)
    except Exception as e:
        print(f"[scraper] Failed: {url} — {e}")
        return ""


def _get_same_domain_links(url: str, base_domain: str, session: requests.Session) -> list[str]:
    """Return all links on a page that stay within base_domain."""
    try:
        resp = session.get(url, timeout=15)
        soup = BeautifulSoup(resp.text, "html.parser")
        links = []
        for a in soup.find_all("a", href=True):
            full = urljoin(url, a["href"]).split("?")[0].split("#")[0]
            if urlparse(full).netloc == base_domain:
                links.append(full)
        return list(set(links))
    except Exception:
        return []


def _chunk_text(text: str, source_url: str, source_type: str) -> list[Document]:
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=config.CHUNK_SIZE,
        chunk_overlap=config.CHUNK_OVERLAP,
    )
    chunks = splitter.split_text(text)
    return [
        Document(
            page_content=chunk,
            metadata={
                "source": source_url,
                "source_url": source_url,
                "source_type": source_type,
                "chunk_index": i,
            },
        )
        for i, chunk in enumerate(chunks)
    ]


def scrape_pluginhive_docs() -> list[Document]:
    """Recursively crawl PluginHive docs and return chunked Documents."""
    print("[scraper] Scraping PluginHive docs...")
    session = _make_session()
    base_domain = urlparse(config.PLUGINHIVE_BASE_URL).netloc
    visited: set[str] = set()
    to_visit = [config.PLUGINHIVE_BASE_URL]
    documents: list[Document] = []

    while to_visit:
        url = to_visit.pop(0)
        if url in visited:
            continue
        visited.add(url)

        text = _scrape_text(url, session)
        if text and len(text) > 100:
            documents.extend(_chunk_text(text, url, "pluginhive_docs"))

        for link in _get_same_domain_links(url, base_domain, session):
            if link not in visited:
                to_visit.append(link)

        time.sleep(0.5)

    print(f"[scraper] PluginHive: {len(documents)} chunks from {len(visited)} pages")
    return documents


def scrape_fedex_api_docs() -> list[Document]:
    """Scrape FedEx API catalog page and return chunked Documents."""
    print("[scraper] Scraping FedEx API docs...")
    session = _make_session()
    text = _scrape_text(config.FEDEX_API_DOCS_URL, session)
    documents = _chunk_text(text, config.FEDEX_API_DOCS_URL, "fedex_api_docs") if text else []
    print(f"[scraper] FedEx API: {len(documents)} chunks")
    return documents
```

- [ ] **Step 2: Smoke-test the scraper manually**

```bash
cd ~/Documents/Fed-Ex-automation/FedexDomainExpert
source .venv/bin/activate
python -c "
from ingest.web_scraper import scrape_fedex_api_docs
docs = scrape_fedex_api_docs()
print(f'Got {len(docs)} chunks')
print('First chunk:', docs[0].page_content[:200] if docs else 'EMPTY')
"
```

Expected: At least 1 chunk printed with FedEx API text. If 0 chunks, the page may require JavaScript — note this and proceed (PluginHive scrape is more important).

- [ ] **Step 3: Commit**

```bash
git add ingest/web_scraper.py
git commit -m "feat: web scraper for PluginHive docs and FedEx API catalog"
```

---

## Task 6: Codebase Loader

**Files:**
- Create: `ingest/codebase_loader.py`
- Create: `tests/test_codebase_loader.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_codebase_loader.py`:

```python
from pathlib import Path


def test_loads_ts_and_md_files(tmp_path, monkeypatch):
    import config
    monkeypatch.setattr(config, "AUTOMATION_CODEBASE_PATH", str(tmp_path))

    (tmp_path / "example.spec.ts").write_text(
        "test('should generate label', async ({ pages }) => { expect(true).toBe(true); });"
    )
    (tmp_path / "README.md").write_text("# FedEx Automation\nThis is the test suite.")

    from ingest.codebase_loader import load_codebase

    docs = load_codebase()

    assert len(docs) >= 2
    assert all(d.metadata["source_type"] == "codebase" for d in docs)


def test_excludes_node_modules(tmp_path, monkeypatch):
    import config
    monkeypatch.setattr(config, "AUTOMATION_CODEBASE_PATH", str(tmp_path))

    node_modules = tmp_path / "node_modules"
    node_modules.mkdir()
    (node_modules / "fake.ts").write_text("this should never appear in results")
    (tmp_path / "real.spec.ts").write_text("real test content here for the codebase loader")

    from ingest.codebase_loader import load_codebase

    docs = load_codebase()
    all_content = " ".join(d.page_content for d in docs)
    assert "this should never appear in results" not in all_content


def test_returns_empty_list_for_missing_path(monkeypatch):
    import config
    monkeypatch.setattr(config, "AUTOMATION_CODEBASE_PATH", "/does/not/exist")

    from ingest.codebase_loader import load_codebase

    docs = load_codebase()
    assert docs == []
```

- [ ] **Step 2: Run the test — verify it fails**

```bash
pytest tests/test_codebase_loader.py -v
```

Expected: `ImportError: cannot import name 'load_codebase' from 'ingest.codebase_loader'`

- [ ] **Step 3: Implement `ingest/codebase_loader.py`**

```python
from pathlib import Path

from langchain.schema import Document
from langchain.text_splitter import RecursiveCharacterTextSplitter

import config

INCLUDE_EXTENSIONS = {".ts", ".json", ".md"}
EXCLUDE_DIRS = {"node_modules", ".git", "test-results", "reports", ".vscode", "dist"}


def load_codebase() -> list[Document]:
    """
    Walk the Playwright automation codebase and return chunked Documents
    from TypeScript, JSON, and Markdown files.
    """
    print("[codebase] Loading automation codebase...")
    base = Path(config.AUTOMATION_CODEBASE_PATH)

    if not base.exists():
        print(f"[codebase] Warning: path not found — {base}")
        return []

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=config.CHUNK_SIZE,
        chunk_overlap=config.CHUNK_OVERLAP,
    )

    documents: list[Document] = []

    for path in base.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix not in INCLUDE_EXTENSIONS:
            continue
        if any(exc in path.parts for exc in EXCLUDE_DIRS):
            continue

        try:
            text = path.read_text(encoding="utf-8", errors="ignore").strip()
            if len(text) < 50:
                continue

            relative = path.relative_to(base)
            for i, chunk in enumerate(splitter.split_text(text)):
                documents.append(
                    Document(
                        page_content=chunk,
                        metadata={
                            "source": str(relative),
                            "source_url": f"file://{path}",
                            "source_type": "codebase",
                            "file_type": path.suffix,
                            "chunk_index": i,
                        },
                    )
                )
        except Exception as e:
            print(f"[codebase] Skipped {path}: {e}")

    print(f"[codebase] {len(documents)} chunks loaded")
    return documents
```

- [ ] **Step 4: Run the tests — verify they pass**

```bash
pytest tests/test_codebase_loader.py -v
```

Expected output:
```
tests/test_codebase_loader.py::test_loads_ts_and_md_files PASSED
tests/test_codebase_loader.py::test_excludes_node_modules PASSED
tests/test_codebase_loader.py::test_returns_empty_list_for_missing_path PASSED
3 passed
```

- [ ] **Step 5: Commit**

```bash
git add ingest/codebase_loader.py tests/test_codebase_loader.py
git commit -m "feat: codebase loader indexes Playwright spec and page object files"
```

---

## Task 7: Google Sheets Loader

**Files:**
- Create: `ingest/sheets_loader.py`

- [ ] **Step 1: Create `ingest/sheets_loader.py`**

```python
import csv
import io
from pathlib import Path

import requests
from langchain.schema import Document
from langchain.text_splitter import RecursiveCharacterTextSplitter

import config

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]


def _fetch_public_csv(sheet_id: str) -> list[list[str]]:
    """Download sheet as CSV (works when sheet is publicly readable)."""
    url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv"
    resp = requests.get(url, timeout=20)
    resp.raise_for_status()
    reader = csv.reader(io.StringIO(resp.text))
    return list(reader)


def _fetch_with_service_account(sheet_id: str, creds_path: str) -> list[list[str]]:
    """Load sheet via service account JSON (for private sheets)."""
    from google.oauth2.service_account import Credentials
    import gspread

    creds = Credentials.from_service_account_file(creds_path, scopes=SCOPES)
    client = gspread.authorize(creds)
    spreadsheet = client.open_by_key(sheet_id)
    all_rows: list[list[str]] = []
    for worksheet in spreadsheet.worksheets():
        all_rows.extend(worksheet.get_all_values())
    return all_rows


def load_test_cases() -> list[Document]:
    """
    Load test cases from Google Sheets.
    Tries service account first, falls back to public CSV export.
    """
    print("[sheets] Loading Google Sheets test cases...")
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=config.CHUNK_SIZE,
        chunk_overlap=config.CHUNK_OVERLAP,
    )

    rows: list[list[str]] = []
    creds_path = Path(config.GOOGLE_CREDENTIALS_PATH)

    try:
        if creds_path.exists():
            print("[sheets] Using service account credentials...")
            rows = _fetch_with_service_account(config.GOOGLE_SHEETS_ID, str(creds_path))
        else:
            print("[sheets] GOOGLE_CREDENTIALS_PATH not set or file missing — trying public CSV access...")
            rows = _fetch_public_csv(config.GOOGLE_SHEETS_ID)
    except Exception as e:
        print(f"[sheets] Primary method failed ({e}) — trying public CSV fallback...")
        try:
            rows = _fetch_public_csv(config.GOOGLE_SHEETS_ID)
        except Exception as e2:
            print(f"[sheets] Both methods failed: {e2}. Skipping sheets.")
            return []

    # Convert rows to plain text (join cells with " | ")
    text_lines = [
        " | ".join(cell.strip() for cell in row if cell.strip())
        for row in rows
    ]
    full_text = "\n".join(line for line in text_lines if line)

    if not full_text.strip():
        print("[sheets] Sheet appears empty — skipping.")
        return []

    sheet_url = f"https://docs.google.com/spreadsheets/d/{config.GOOGLE_SHEETS_ID}"
    documents = [
        Document(
            page_content=chunk,
            metadata={
                "source": f"Google Sheets: {config.GOOGLE_SHEETS_ID}",
                "source_url": sheet_url,
                "source_type": "test_cases",
                "chunk_index": i,
            },
        )
        for i, chunk in enumerate(splitter.split_text(full_text))
    ]

    print(f"[sheets] {len(documents)} chunks loaded from test cases")
    return documents
```

- [ ] **Step 2: Smoke-test sheets loader**

```bash
cd ~/Documents/Fed-Ex-automation/FedexDomainExpert
source .venv/bin/activate
python -c "
from ingest.sheets_loader import load_test_cases
docs = load_test_cases()
print(f'Got {len(docs)} chunks')
if docs:
    print('Sample:', docs[0].page_content[:300])
"
```

Expected: Chunks from the test cases sheet. If the sheet is private and no `GOOGLE_CREDENTIALS_PATH` file exists, you'll see "Both methods failed" — that's OK, it degrades gracefully.

- [ ] **Step 3: Commit**

```bash
git add ingest/sheets_loader.py
git commit -m "feat: Google Sheets loader with service account and public CSV fallback"
```

---

## Task 8: Ingestion Runner

**Files:**
- Create: `ingest/run_ingest.py`

- [ ] **Step 1: Create `ingest/run_ingest.py`**

```python
#!/usr/bin/env python3
"""
Master ingestion pipeline.
Clears the knowledge base and rebuilds it from all configured sources.

Usage:
    python ingest/run_ingest.py                    # Ingest all sources
    python ingest/run_ingest.py --sources codebase # Only index codebase
    python ingest/run_ingest.py --sources pluginhive fedex
"""
import argparse
import sys
import time


def run_ingest(sources: list[str] | None = None) -> None:
    from rag.vectorstore import clear_collection, add_documents
    from ingest.web_scraper import scrape_pluginhive_docs, scrape_fedex_api_docs
    from ingest.codebase_loader import load_codebase
    from ingest.sheets_loader import load_test_cases

    ingest_all = sources is None
    start = time.time()

    print("=" * 60)
    print("FedEx Domain Expert — Knowledge Base Ingestion")
    print("=" * 60)
    print("\n[ingest] Clearing existing knowledge base...")
    clear_collection()

    all_documents = []

    if ingest_all or "pluginhive" in sources:
        all_documents.extend(scrape_pluginhive_docs())

    if ingest_all or "fedex" in sources:
        all_documents.extend(scrape_fedex_api_docs())

    if ingest_all or "codebase" in sources:
        all_documents.extend(load_codebase())

    if ingest_all or "sheets" in sources:
        all_documents.extend(load_test_cases())

    if not all_documents:
        print("\n[ingest] ERROR: No documents loaded. Check your sources and try again.")
        sys.exit(1)

    print(f"\n[ingest] Embedding and storing {len(all_documents)} chunks in ChromaDB...")
    add_documents(all_documents)

    elapsed = time.time() - start
    print(f"\n✅ Done: {len(all_documents)} chunks indexed in {elapsed:.1f}s")
    print("=" * 60)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Rebuild FedEx Domain Expert knowledge base")
    parser.add_argument(
        "--sources",
        nargs="*",
        choices=["pluginhive", "fedex", "codebase", "sheets"],
        help="Which sources to ingest (default: all)",
    )
    args = parser.parse_args()
    run_ingest(args.sources)
```

- [ ] **Step 2: Run a quick ingest with only the codebase (fastest — no web scraping)**

```bash
cd ~/Documents/Fed-Ex-automation/FedexDomainExpert
source .venv/bin/activate
python ingest/run_ingest.py --sources codebase
```

Expected:
```
============================================================
FedEx Domain Expert — Knowledge Base Ingestion
============================================================
[ingest] Clearing existing knowledge base...
[codebase] Loading automation codebase...
[codebase] NNN chunks loaded
[ingest] Embedding and storing NNN chunks in ChromaDB...
✅ Done: NNN chunks indexed in X.Xs
============================================================
```

- [ ] **Step 3: Commit**

```bash
git add ingest/run_ingest.py
git commit -m "feat: master ingestion runner with per-source and full rebuild modes"
```

---

## Task 9: FastAPI Server

**Files:**
- Create: `api/server.py`
- Create: `tests/test_api.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_api.py`:

```python
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    """TestClient with chain mocked so no Ollama call is made."""
    mock_chain = MagicMock()

    with patch("api.server.build_chain", return_value=mock_chain), \
         patch("api.server.ask", return_value={
             "answer": "Label generation creates a FedEx label via the REST API.",
             "sources": ["https://pluginhive.com/label-gen"],
         }):
        from api.server import app
        yield TestClient(app)


def test_health_returns_ok(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_ask_returns_answer_and_sources(client):
    resp = client.post("/ask", json={"question": "How does label generation work?"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["answer"] == "Label generation creates a FedEx label via the REST API."
    assert "https://pluginhive.com/label-gen" in data["sources"]
    assert data["session_id"] == "default"


def test_ask_with_custom_session_id(client):
    resp = client.post("/ask", json={
        "question": "How does label generation work?",
        "session_id": "team-member-123",
    })
    assert resp.status_code == 200
    assert resp.json()["session_id"] == "team-member-123"


def test_clear_session(client):
    resp = client.delete("/sessions/team-member-123")
    assert resp.status_code == 200
    assert resp.json() == {"status": "cleared", "session_id": "team-member-123"}
```

- [ ] **Step 2: Run the test — verify it fails**

```bash
pytest tests/test_api.py -v
```

Expected: `ImportError: cannot import name 'app' from 'api.server'`

- [ ] **Step 3: Implement `api/server.py`**

```python
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

import config
from rag.chain import ask, build_chain
from langchain.memory import ConversationBufferWindowMemory

app = FastAPI(title="FedEx Domain Expert API", version="1.0.0")

# In-memory session store: session_id → {memory, chain}
_sessions: dict[str, dict] = {}


class AskRequest(BaseModel):
    question: str
    session_id: str = "default"


class AskResponse(BaseModel):
    answer: str
    sources: list[str]
    session_id: str


def _get_or_create_session(session_id: str) -> dict:
    if session_id not in _sessions:
        memory = ConversationBufferWindowMemory(
            k=config.MEMORY_WINDOW,
            memory_key="chat_history",
            return_messages=True,
            output_key="answer",
        )
        _sessions[session_id] = {
            "memory": memory,
            "chain": build_chain(memory),
        }
    return _sessions[session_id]


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/ask", response_model=AskResponse)
def ask_expert(request: AskRequest) -> AskResponse:
    try:
        session = _get_or_create_session(request.session_id)
        result = ask(request.question, session["chain"])
        return AskResponse(
            answer=result["answer"],
            sources=result["sources"],
            session_id=request.session_id,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/sessions/{session_id}")
def clear_session(session_id: str) -> dict:
    _sessions.pop(session_id, None)
    return {"status": "cleared", "session_id": session_id}
```

- [ ] **Step 4: Run the tests — verify they pass**

```bash
pytest tests/test_api.py -v
```

Expected output:
```
tests/test_api.py::test_health_returns_ok PASSED
tests/test_api.py::test_ask_returns_answer_and_sources PASSED
tests/test_api.py::test_ask_with_custom_session_id PASSED
tests/test_api.py::test_clear_session PASSED
4 passed
```

- [ ] **Step 5: Commit**

```bash
git add api/server.py tests/test_api.py
git commit -m "feat: FastAPI server with /ask endpoint, session memory, and /health"
```

---

## Task 10: Streamlit Web UI

**Files:**
- Create: `ui/chat_app.py`

- [ ] **Step 1: Create `ui/chat_app.py`**

```python
"""
FedEx Domain Expert — Streamlit Web Chat UI
Run with: streamlit run ui/chat_app.py
"""
import subprocess

import streamlit as st
from langchain.memory import ConversationBufferWindowMemory

import config
from rag.chain import ask, build_chain

st.set_page_config(
    page_title="FedEx Domain Expert",
    page_icon="📦",
    layout="wide",
)

QUICK_ASKS = [
    "Take me on a tour of the FedEx app",
    "How does label generation work?",
    "What FedEx shipping services are supported?",
    "Show me the test cases for label generation",
    "How do I configure a new store?",
    "What is the difference between manual and auto label generation?",
    "How does return label generation work?",
    "What packaging types are supported?",
]


def _init_session() -> None:
    if "messages" not in st.session_state:
        st.session_state.messages = []
    if "memory" not in st.session_state:
        st.session_state.memory = ConversationBufferWindowMemory(
            k=config.MEMORY_WINDOW,
            memory_key="chat_history",
            return_messages=True,
            output_key="answer",
        )
    if "chain" not in st.session_state:
        with st.spinner("Loading domain expert model..."):
            st.session_state.chain = build_chain(st.session_state.memory)


def _render_sidebar() -> None:
    with st.sidebar:
        st.title("🧠 FedEx Domain Expert")
        st.caption(f"Model: `{config.DOMAIN_EXPERT_MODEL}`")

        st.divider()
        st.subheader("⚡ Quick Questions")
        for question in QUICK_ASKS:
            if st.button(question, use_container_width=True, key=f"q_{hash(question)}"):
                st.session_state.pending_question = question

        st.divider()
        st.subheader("📚 Knowledge Base")
        st.caption("🌐 PluginHive Docs")
        st.caption("📡 FedEx API Docs")
        st.caption("📊 Google Sheets Test Cases")
        st.caption("💻 Playwright Codebase")

        st.divider()
        if st.button("🔄 Refresh Knowledge Base", use_container_width=True):
            with st.spinner("Re-ingesting all documents… (takes a few minutes)"):
                result = subprocess.run(
                    ["python", "ingest/run_ingest.py"],
                    capture_output=True,
                    text=True,
                    cwd=str(config.BASE_DIR),
                )
            if result.returncode == 0:
                st.success("✅ Knowledge base refreshed!")
            else:
                st.error(f"❌ Ingestion failed:\n{result.stderr[:400]}")

        if st.button("🗑️ Clear Chat History", use_container_width=True):
            st.session_state.messages = []
            st.session_state.memory = ConversationBufferWindowMemory(
                k=config.MEMORY_WINDOW,
                memory_key="chat_history",
                return_messages=True,
                output_key="answer",
            )
            st.session_state.chain = build_chain(st.session_state.memory)
            st.rerun()


def main() -> None:
    _init_session()
    _render_sidebar()

    st.header("💬 Ask your FedEx App Expert")
    st.caption("Ask anything about the FedEx Shopify App — features, test cases, API, setup, and more.")

    # Render chat history
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
            if msg["role"] == "assistant" and msg.get("sources"):
                with st.expander("📚 Sources", expanded=False):
                    for src in msg["sources"]:
                        st.caption(src)

    # Resolve question — quick-ask button or chat input
    question: str | None = None
    if "pending_question" in st.session_state:
        question = st.session_state.pop("pending_question")
    else:
        question = st.chat_input("Ask anything about the FedEx Shopify App…")

    if question:
        st.session_state.messages.append({"role": "user", "content": question})
        with st.chat_message("user"):
            st.markdown(question)

        with st.chat_message("assistant"):
            with st.spinner("Thinking…"):
                result = ask(question, st.session_state.chain)
            st.markdown(result["answer"])
            if result["sources"]:
                with st.expander("📚 Sources", expanded=False):
                    for src in result["sources"]:
                        st.caption(src)

        st.session_state.messages.append({
            "role": "assistant",
            "content": result["answer"],
            "sources": result["sources"],
        })
        st.rerun()


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Manual smoke test — launch the UI**

```bash
cd ~/Documents/Fed-Ex-automation/FedexDomainExpert
source .venv/bin/activate
streamlit run ui/chat_app.py
```

Open **http://localhost:8501** in browser.

Verify:
- [ ] Sidebar shows Quick Questions buttons
- [ ] Chat input box is visible at the bottom
- [ ] Click "Take me on a tour of the FedEx app" → answer appears with sources
- [ ] Type a follow-up "tell me more about label generation" → answer uses chat context
- [ ] "Clear Chat History" button resets the conversation

- [ ] **Step 3: Commit**

```bash
git add ui/chat_app.py
git commit -m "feat: Streamlit chat UI with sidebar quick-asks, memory, and source citations"
```

---

## Task 11: Full Ingest + End-to-End Verification

**Files:**
- No new files — runs against all sources

- [ ] **Step 1: Run full ingestion (all sources)**

```bash
cd ~/Documents/Fed-Ex-automation/FedexDomainExpert
source .venv/bin/activate
python ingest/run_ingest.py
```

Expected: All 4 sources complete. Final chunk count printed.

- [ ] **Step 2: Verify end-to-end via CLI**

```bash
python -c "
from rag.chain import build_chain, ask

chain = build_chain()

# Test 1: Knowledge question
r1 = ask('How does label generation work?', chain)
print('=== Label Generation ===')
print(r1['answer'][:400])
print('Sources:', r1['sources'])

# Test 2: Tour
r2 = ask('Take me on a tour of the FedEx app', chain)
print('\n=== Tour ===')
print(r2['answer'][:400])

# Test 3: Follow-up (tests memory)
r3 = ask('Tell me more about the first section you mentioned', chain)
print('\n=== Follow-up ===')
print(r3['answer'][:300])
"
```

Expected: All 3 questions answered. Test 3 should reference the first section from Test 2's tour (proving memory works).

- [ ] **Step 3: Run all unit tests**

```bash
pytest tests/ -v --ignore=tests/test_vectorstore.py
```

Expected: All tests pass (vectorstore tests excluded here as they need live Ollama).

- [ ] **Step 4: Start the API server and verify**

```bash
# Terminal 1:
uvicorn api.server:app --reload --port 8000

# Terminal 2:
curl -s -X POST http://localhost:8000/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "What FedEx shipping services are supported?"}' | python -m json.tool
```

Expected: JSON response with `answer`, `sources`, `session_id`.

- [ ] **Step 5: Final commit**

```bash
git add -A
git commit -m "feat: complete FedexDomainExpert Phase 1 — RAG chat system with web UI and API"
```

---

## Running the System

### First-time setup
```bash
cd ~/Documents/Fed-Ex-automation/FedexDomainExpert
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Make sure Ollama is running
ollama serve &

# Ingest all knowledge sources
python ingest/run_ingest.py

# Launch the chat UI
streamlit run ui/chat_app.py
# → open http://localhost:8501

# (Optional) Launch the API in a second terminal
uvicorn api.server:app --port 8000
```

### Daily use
```bash
source .venv/bin/activate
streamlit run ui/chat_app.py
```

### Refresh knowledge base (when docs update)
```bash
python ingest/run_ingest.py
# or use "Refresh Knowledge Base" button in the UI sidebar
```
