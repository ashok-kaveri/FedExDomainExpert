# FedEx Domain Expert — Design Spec

**Date:** 2026-04-01
**Project:** FedexDomainExpert (new standalone project)
**Status:** Approved for implementation

---

## 1. Overview

A local, 100% offline RAG-powered domain expert system for the FedEx Shopify App. It uses `qwen2.5:14b` (via Ollama) as the conversational brain, ChromaDB as the local vector store, LangChain for RAG orchestration, and Streamlit for the web chat UI.

**Primary goal (Phase 1):** Any team member — technical or not — can open a browser, ask any question about the FedEx Shopify App, and get a clear, accurate answer grounded in real documentation and test data.

**Future goals (Phase 2+):** Connect the domain expert to the visual expert (`qwen2.5vl`) and code agent (`deepseek-coder:6.7b`) to form a fully autonomous test maintenance and generation system, orchestrated by Claude Code.

---

## 2. Decisions Made

| Decision | Choice | Rationale |
|---|---|---|
| Language | Python | Best RAG ecosystem (LangChain, ChromaDB, Ollama) |
| LLM | qwen2.5:14b via Ollama | Largest local model, best reasoning |
| Embeddings | nomic-embed-text via Ollama | Fast, local, 768-dim, purpose-built for retrieval |
| Vector DB | ChromaDB (local, persisted) | No cloud, no cost, disk-persisted, simple API |
| RAG mode | Conversational RAG | Supports chat history, follow-ups, "take me on a tour" |
| UI | Streamlit | Zero-config web chat, runs with one command |
| API | FastAPI | Programmatic access for Claude Code orchestration |

---

## 3. Project Structure

```
FedexDomainExpert/
├── ingest/
│   ├── web_scraper.py        # Crawl PluginHive + FedEx API docs
│   ├── sheets_loader.py      # Pull Google Sheets test cases via gspread
│   ├── codebase_loader.py    # Index Playwright spec + page object files
│   └── run_ingest.py         # Master runner: scrape → chunk → embed → store
├── rag/
│   ├── vectorstore.py        # ChromaDB init, add, search operations
│   ├── chain.py              # LangChain ConversationalRetrievalChain setup
│   └── prompts.py            # Domain expert system prompt + persona
├── ui/
│   └── chat_app.py           # Streamlit web chat interface
├── api/
│   └── server.py             # FastAPI endpoint for programmatic access
├── data/
│   └── chroma_db/            # Persisted vector store (gitignored)
├── config.py                 # All settings: Ollama URL, model names, paths
├── requirements.txt
└── README.md
```

---

## 4. Knowledge Sources (Phase 1)

| Source | Loader | Content |
|---|---|---|
| https://www.pluginhive.com/set-up-shopify-fedex-rates-labels-tracking-app/ | BeautifulSoup web crawler (recursive, same-domain) | App features, settings, configuration guides, how-tos |
| https://developer.fedex.com/api/en-us/catalog.html | BeautifulSoup web scraper (catalog + API pages) | FedEx REST API endpoints, request/response formats, auth |
| Google Sheets (test cases spreadsheet) | gspread library with service account | All test cases, scenarios, expected results, acceptance criteria |
| Playwright automation codebase | DirectoryLoader from LangChain | Spec files, page objects, helpers — teaches expert about test structure |

All sources are tagged with metadata (`source_type`, `source_url`, `loaded_at`) so the expert can cite where its answers come from.

---

## 5. Ingestion Pipeline

**Chunking strategy:**
- Chunk size: 500 tokens
- Chunk overlap: 50 tokens
- Splitter: `RecursiveCharacterTextSplitter`
- HTML stripped, code blocks preserved

**Embedding:**
- Model: `nomic-embed-text` via Ollama
- Dimension: 768
- Stored in ChromaDB collection: `fedex_knowledge`

**Re-ingestion:** Running `python ingest/run_ingest.py` clears and rebuilds the collection. Designed to be run whenever docs are updated.

---

## 6. Query Pipeline (Conversational RAG)

```
User message
    ↓
Condense question (with chat history) — qwen2.5:14b rewrites ambiguous follow-ups
    ↓
ChromaDB similarity search — top 5 chunks retrieved
    ↓
Prompt construction — system prompt + retrieved chunks + conversation history
    ↓
qwen2.5:14b streams answer
    ↓
Streamlit renders streamed response
```

**LangChain chain:** `ConversationalRetrievalChain` with:
- `condense_question_llm`: qwen2.5:14b (fast reformulation)
- `combine_docs_chain_type`: "stuff" (all chunks in one prompt)
- `return_source_documents`: True (so UI can show sources)
- Memory: `ConversationBufferWindowMemory` (last 10 turns)

---

## 7. Domain Expert Persona (System Prompt)

The domain expert presents itself as a senior technical specialist for the FedEx Shopify App. It:
- Answers questions about app features, configuration, and workflows
- Explains test cases and automation patterns in the codebase
- Can walk a new team member through the entire app ("Take me on a tour")
- Cites the source document when answering
- Admits when it doesn't know and suggests where to look
- Never makes up FedEx API behavior — only answers from retrieved context

---

## 8. Web Chat UI (Streamlit — `localhost:8501`)

**Layout:**
- Left sidebar: Knowledge base status, quick-ask shortcuts, "Refresh Docs" button (async — shows spinner, does not block chat)
- Main area: Chat messages (user + assistant), streamed responses
- Source citations shown below each assistant message (collapsible)

**Quick-ask shortcuts (sidebar):**
- "Take me on a tour of the app"
- "How does label generation work?"
- "What FedEx services are supported?"
- "Show me the test cases for label generation"
- "How do I set up a new store?"

---

## 9. API Layer (FastAPI — `localhost:8000`)

Single endpoint for Claude Code integration:

```
POST /ask
{
  "question": "How does label generation work?",
  "session_id": "optional-for-memory"
}

Response:
{
  "answer": "...",
  "sources": ["url1", "url2"]
}
```

This API is what allows Claude Code to call the domain expert programmatically in Phase 2 (when orchestrating the 3-model system).

---

## 10. Configuration (`config.py`)

```python
OLLAMA_BASE_URL = "http://localhost:11434"
DOMAIN_EXPERT_MODEL = "qwen2.5:14b"
EMBEDDING_MODEL = "nomic-embed-text"
CHROMA_PATH = "./data/chroma_db"
CHROMA_COLLECTION = "fedex_knowledge"

PLUGINHIVE_BASE_URL = "https://www.pluginhive.com/set-up-shopify-fedex-rates-labels-tracking-app/"
FEDEX_API_DOCS_URL = "https://developer.fedex.com/api/en-us/catalog.html"
AUTOMATION_CODEBASE_PATH = os.getenv("AUTOMATION_CODEBASE_PATH", "")

CHUNK_SIZE = 500
CHUNK_OVERLAP = 50
TOP_K_RESULTS = 5
MEMORY_WINDOW = 10
```

---

## 11. Prerequisites (before first run)

These must be set up once before the system works:

1. **Ollama models pulled:**
   ```bash
   ollama pull qwen2.5:14b       # already installed ✅
   ollama pull nomic-embed-text  # needs pulling — used for embeddings
   ```

2. **Google Sheets access:** The sheets loader requires either:
   - A Google Service Account JSON key file referenced by `GOOGLE_CREDENTIALS_PATH`, OR
   - The sheet made publicly readable (view-only link) — simplest option to start

3. **Python 3.11+** with `pip install -r requirements.txt`

---

## 12. Out of Scope (Phase 1)

- Visual expert (`qwen2.5vl`) — Phase 2
- Code agent (`deepseek-coder:6.7b`) — Phase 2
- Trello integration — Phase 2
- Automatic test failure diagnosis — Phase 2
- Authentication / user accounts on the Streamlit UI — not needed for internal use
- Cloud deployment — everything runs locally

---

## 12. Success Criteria

- [ ] A new team member can ask "How does label generation work?" and get a correct, sourced answer
- [ ] "Take me on a tour" triggers a full walkthrough of the app's main features
- [ ] Follow-up questions like "tell me more about that" work correctly
- [ ] The knowledge base can be refreshed with one command
- [ ] The FastAPI endpoint responds to programmatic queries from Claude Code
- [ ] All data stays 100% local — no external API calls except to Ollama
