# FedEx Domain Expert

An AI-powered QA platform for the PluginHive FedEx Shopify App.
Combines a RAG knowledge base, an autonomous browser agent, and a full delivery pipeline — from Trello card to verified Playwright test.

---

## What's Inside

| Component | What it does |
|---|---|
| **Domain Expert Chat** | Ask anything about the app — features, test cases, API, bugs. Answers from real docs + codebase. |
| **AI QA Agent** | Autonomous agent that opens the real app in a browser, verifies every AC scenario, creates orders, configures settings, downloads logs, and reports pass/fail. |
| **QA Pipeline** | Full delivery pipeline: Trello card → AC generation → AI QA Agent verification → Playwright test writing → sign-off dashboard. |

---

## Models

| Purpose | Model |
|---|---|
| Reasoning (AC verifier, test writer, domain expert) | `claude-sonnet-4-6` via Anthropic API |
| Fast tasks (card processing, feature detection) | `claude-haiku-4-5-20251001` |
| Embeddings | `nomic-embed-text` via Ollama (local) |

```bash
ollama pull nomic-embed-text
```

---

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-lock.txt
```

Copy `.env.example` → `.env` and fill in your keys:

```
ANTHROPIC_API_KEY=sk-ant-...
TRELLO_API_KEY=...
TRELLO_TOKEN=...
TRELLO_BOARD_ID=...
BACKEND_CODE_PATH=~/Documents/fedex-Backend-Code/shopifyfedexapp
FRONTEND_CODE_PATH=~/Documents/fedex-Frontend-Code/shopify-fedex-web-client
AUTOMATION_CODEBASE_PATH=../fedex-test-automation
SHOPIFY_ACTIONS_PATH=~/Documents/shopify-actions
WIKI_PATH=~/Documents/fedex-wiki
```

---

## Knowledge Base

### Ingest all sources (full rebuild)
```bash
cd ~/Documents/Fed-Ex-automation/FedexDomainExpert
PYTHONPATH=. .venv/bin/python ingest/run_ingest.py
```

### Ingest specific sources only
```bash
# Wiki + Shopify Actions only (fast, ~2 min)
PYTHONPATH=. .venv/bin/python ingest/run_ingest.py --sources wiki shopify_actions

# Codebase only
PYTHONPATH=. .venv/bin/python ingest/run_ingest.py --sources codebase

# All sources
PYTHONPATH=. .venv/bin/python ingest/run_ingest.py --sources fedex_rest pluginhive_docs pluginhive_seeds app codebase pdf wiki shopify_actions
```

### Knowledge sources indexed

| Source | What it contains |
|---|---|
| `fedex_rest` | FedEx REST API: rate/label requests, special services, error codes |
| `pluginhive_docs` | Official PluginHive setup guide, UX flows, feature docs |
| `pluginhive_seeds` | 25 high-value FAQ + knowledge base pages (guaranteed crawled) |
| `app` | Live browser capture of every FedEx app screen |
| `codebase` | Playwright TypeScript automation suite (POMs, specs, helpers) |
| `pdf` | FedExApp Master sheet test cases |
| `wiki` | Internal fedex-wiki (bugs, features, ADRs, support tickets, engineering notes) |
| `shopify_actions` | Bulk order creation JS tool (Order.js, Generator.js, API.js) |

### ChromaDB collections

| Collection | Contents |
|---|---|
| `fedex_knowledge` | All domain knowledge (docs, wiki, test cases, app UI) |
| `fedex_code_knowledge` | Source code (automation POM + backend + frontend) |

---

## Running the Dashboard (QA Pipeline)

```bash
cd ~/Documents/Fed-Ex-automation/FedexDomainExpert
PYTHONPATH=. .venv/bin/streamlit run ui/pipeline_dashboard.py
```

Opens at **http://localhost:8501**

### Dashboard tabs

| Tab | Purpose |
|---|---|
| User Story | Write AC from a raw feature request |
| Move Cards | Process Trello backlog → Ready for Dev |
| Release QA | Run AI QA Agent on a release (card → verify → write tests) |
| History | Past pipeline run results |
| Sign Off | Feature sign-off dashboard |
| Write Automation | Generate Playwright tests |
| Run Automation | Trigger test suite |

---

## Running the Domain Expert Chat

```bash
PYTHONPATH=. .venv/bin/streamlit run ui/chat_app.py
```

Opens at **http://localhost:8502** (if dashboard is already on 8501)

Quick questions available in the sidebar:
- "Take me on a tour of the FedEx app"
- "How does label generation work?"
- "What FedEx shipping services are supported?"
- "Show me the test cases for label generation"

---

## AI QA Agent — How It Works

The AI QA Agent is an autonomous browser agent that verifies every AC scenario end-to-end.

### Decision flow per scenario

```
Scenario text
      ↓
1. Domain Expert — queries RAG (PluginHive docs + FedEx API + wiki + code)
      ↓
2. Pre-Requirements Resolver — injects known setup steps:
   dry ice / alcohol / battery → enable on AppProducts, fill fields, cleanup after
   signature / HAL / insurance → configure in SideDock before generating
      ↓
3. Planning — Claude decides:
   • What ORDER is needed? (none / existing / create single / create bulk)
   • What SETTINGS to configure first?
   • Which NAVIGATION path to take?
      ↓
4. Order setup (if needed):
   • create_new    → creates 1 fresh Shopify order via REST API
   • create_bulk   → creates 5–10 orders for bulk scenarios
   • existing_unfulfilled → finds unfulfilled order in Shopify admin
   • existing_fulfilled   → finds order with label in app Shipping tab
   • none          → skip (settings/navigation scenarios)
      ↓
5. Agentic browser loop (up to 15 steps):
   observe → click → fill → scroll → download_zip → download_file → switch_tab → verify
      ↓
6. Verdict: ✅ pass | ❌ fail | ⚠️ partial | 🔶 qa_needed
```

### Order judgment

| Scenario type | Order decision |
|---|---|
| "bulk label", "50 orders", "select all orders", "batch label" | `create_bulk` (5 orders for AC check) |
| "generate label", "dry ice", "alcohol", "battery", "signature", "HAL", "COD", "international" | `create_new` (dangerous product for DG scenarios) |
| "return label", "verify existing label", "download docs", "next/prev navigation" | `existing_fulfilled` |
| "address update", "edit shipping address" | `existing_unfulfilled` |
| "settings", "configure", "order grid", "navigation", "pickup scheduling" | `none` |

### Verification strategies

| Strategy | When to use | How |
|---|---|---|
| 1 — Label exists | "label is generated", "label status" | Look for "label generated" badge on Order Summary |
| 2 — Physical docs | "label PDF exists", "packing slip", "CI present" | More Actions → Download Documents ZIP |
| 3 — JSON fields | signature type, special services, HAL, dry ice weight, declared value | More Actions → How To → Click Here ZIP |
| 4 — Rate log | Rate request JSON DURING manual label (before generate) | ⋯ → View Logs → screenshot |
| 5 — Visual label | Text codes on printed label | Print Documents → new tab → screenshot → read ICE / ALCOHOL / ELB / ASR / DSR |

> **CI (Commercial Invoice)** is only present for international orders. Domestic US orders have label + packing slip only.

### When it asks QA
If AI QA Agent can't locate a feature after 15 browser steps, it sets `qa_needed` status
and asks a specific question. The dashboard shows the question with a text input —
QA answers → the scenario re-runs with that guidance injected.

---

## Project Structure

```
FedexDomainExpert/
├── ingest/
│   ├── run_ingest.py         # Master ingestion pipeline
│   ├── codebase_loader.py    # TypeScript/JS/JSON code loader
│   ├── wiki_loader.py        # Internal fedex-wiki markdown loader
│   ├── web_scraper.py        # PluginHive docs scraper
│   ├── fedex_rest_api.py     # FedEx REST API reference
│   ├── pdf_loader.py         # Test cases PDF
│   ├── app_navigator.py      # Live app UI capture
│   └── pluginhive_app_docs.py
├── rag/
│   ├── vectorstore.py        # ChromaDB operations
│   ├── chain.py              # Conversational RAG chain (Claude Sonnet)
│   ├── prompts.py            # Domain expert persona + prompts
│   └── code_indexer.py       # Separate code knowledge base
├── pipeline/
│   ├── smart_ac_verifier.py  # AI QA Agent — agentic AC verifier
│   ├── order_creator.py      # Shopify order creation (single + bulk)
│   ├── card_processor.py     # AC writer + test case generator
│   ├── feature_detector.py   # New vs existing feature classifier
│   ├── rag_updater.py        # Auto-embed approved cards into ChromaDB
│   ├── test_writer/          # Playwright spec + POM generator
│   ├── trello_client.py      # Trello REST API wrapper
│   └── chrome_agent.py       # Claude Chrome browser agent
├── ui/
│   ├── pipeline_dashboard.py # QA Pipeline Streamlit dashboard
│   └── chat_app.py           # Domain Expert Streamlit chat
├── api/
│   └── server.py             # FastAPI REST API
├── data/chroma_db/           # Persisted vector store (gitignored)
└── config.py                 # All settings (env-driven)
```

---

## API Server (optional)

```bash
uvicorn api.server:app --port 8000
```

API docs: **http://localhost:8000/docs**

```bash
curl -X POST http://localhost:8000/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "How does label generation work?"}'
```

---

## Tests

```bash
pytest tests/ -v
```
