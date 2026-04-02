# FedEx Domain Expert

A local, 100% offline RAG-powered domain expert for the FedEx Shopify App.
Ask questions about the app, its features, test cases, and FedEx API — get answers from real documentation.

## Models Required (via Ollama)

- `qwen2.5:14b` — domain expert brain
- `nomic-embed-text` — embeddings

```bash
ollama pull qwen2.5:14b
ollama pull nomic-embed-text
```

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Ingest Knowledge Base

Run once before first use, and after documentation updates:

```bash
# All sources (web scrape + codebase + Google Sheets)
python ingest/run_ingest.py

# Codebase only (fast, no web scraping)
python ingest/run_ingest.py --sources codebase

# Specific sources
python ingest/run_ingest.py --sources pluginhive fedex codebase sheets
```

## Run Web Chat UI

```bash
streamlit run ui/chat_app.py
```

Open **http://localhost:8501** in your browser.

## Run API Server (optional)

```bash
uvicorn api.server:app --port 8000
```

API docs: **http://localhost:8000/docs**

### Ask via API:
```bash
curl -X POST http://localhost:8000/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "How does label generation work?"}'
```

## Run Tests

```bash
# All tests (no Ollama required)
pytest tests/ --ignore=tests/test_vectorstore.py -v

# With Ollama running (includes vector store tests)
pytest tests/ -v
```

## Project Structure

```
FedexDomainExpert/
├── ingest/          # Knowledge base loaders
│   ├── web_scraper.py        # PluginHive + FedEx API docs
│   ├── codebase_loader.py    # Playwright automation codebase
│   ├── sheets_loader.py      # Google Sheets test cases
│   └── run_ingest.py         # Master ingestion runner
├── rag/             # RAG pipeline
│   ├── vectorstore.py        # ChromaDB operations
│   ├── prompts.py            # Domain expert persona
│   └── chain.py              # Conversational RAG chain
├── ui/
│   └── chat_app.py           # Streamlit web chat
├── api/
│   └── server.py             # FastAPI REST API
├── data/chroma_db/           # Persisted vector store (local, gitignored)
└── config.py                 # All settings
```

## Knowledge Sources

| Source | What it teaches the expert |
|---|---|
| PluginHive Docs | App features, settings, workflows |
| FedEx API Docs | API endpoints, rates, labels, tracking |
| Google Sheets | Test cases, scenarios, acceptance criteria |
| Playwright Codebase | Test patterns, page objects, automation structure |

## Phase 2 (planned)

- Connect `qwen2.5vl` (visual expert) for label/document verification
- Connect `deepseek-coder:6.7b` (code agent) for automated test generation
- Trello integration for new card → test case pipeline
- Orchestrated by Claude Code
