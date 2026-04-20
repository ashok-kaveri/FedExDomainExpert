# FedEx Domain Expert

An AI-powered QA platform for the PluginHive FedEx Shopify App.
Combines a RAG knowledge base, an autonomous browser agent, and a full delivery pipeline — from Trello card to verified Playwright test.

---

## What's Inside

| Component | What it does |
|---|---|
| **Domain Expert Chat** | Ask anything about the app — features, test cases, API, bugs. Answers from real docs + codebase. |
| **AI QA Agent** | Autonomous agent that opens the real app in a browser, verifies reviewed test cases, creates orders, configures settings, downloads logs/documents, and reports pass/fail with evidence. |
| **QA Pipeline** | Full delivery pipeline: Trello card → AC generation → TC generation → AI QA verification → Playwright test writing → sign-off dashboard. |

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
TRELLO_WORKSPACE_ID=...
BACKEND_CODE_PATH=~/Documents/fedex-Backend-Code/shopifyfedexapp
FRONTEND_CODE_PATH=~/Documents/fedex-Frontend-Code/shopify-fedex-web-client
AUTOMATION_CODEBASE_PATH=~/Documents/Fed-Ex-automation/fedex-test-automation
SHOPIFY_ACTIONS_PATH=~/Documents/shopify-actions
WIKI_PATH=~/Documents/fedex-wiki
PDF_TEST_CASES_PATH=~/Downloads/FedExApp\ Master\ sheet\ .pdf
GOOGLE_CREDENTIALS_PATH=./credentials.json
NODE_BINARY=
NODE_BIN_DIR=
```

Notes:
- All local repo/file locations are now env-driven. If these paths are missing, the related feature will fail fast instead of using a hardcoded machine path.
- `TRELLO_BOARD_ID` is still useful as the default board/workspace anchor, but the dashboard now lets you select boards dynamically in Validate AC, Move Cards, and User Story → Push to Trello.
- If your Shopify Actions folder name contains a trailing space on disk, keep that exact value in `SHOPIFY_ACTIONS_PATH`.

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
| Move Cards | Select a Trello board, then move cards between lists on that board |
| Validate AC | Select a Trello board and release list, load cards, then generate/review AC |
| Generate TC | Use the same loaded release context to generate and review test cases |
| AI QA Verifier | Run AI QA on selected reviewed TCs, review bugs, approve/save, and continue into automation |
| History | Past pipeline run results |
| Sign Off | Feature sign-off dashboard |
| Handoff Docs | Generate Support Guide and Business Brief PDFs, then download/share to Trello or Slack |
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

## QA Pipeline — Current Flow

The current delivery flow is:

1. In `Validate AC`, select board/list and load release cards
2. AI generates AC from card + research context
3. Domain Expert validates and can rewrite AC
4. In `Generate TC`, AI generates test cases
5. TC review pass can rewrite weak/duplicate/missing TCs
6. In `AI QA Verifier`, AI QA Agent runs selected reviewed test cases
7. Bug review, re-verify, approve/save, and retrospective learning stay in `AI QA Verifier`
8. Automation generator writes 1–2 strong E2E cases from approved TCs
9. QA uses the existing sign-off pattern

Important:
- AI QA is now **TC-based**, not AC-based, for normal execution
- AC is still the source requirement document
- reviewed TCs are the execution source
- sign-off format remains separate from AI QA details

## Handoff Docs

After sign-off, the dashboard can generate two handoff documents per approved card from the current release session:

1. `Support Guide`
2. `Business Brief`

### Support Guide

Used for:
- support enablement
- demo/training handoff
- QA-to-support walkthroughs

Includes:
- feature summary
- where to find the feature
- how it works
- prerequisites / toggle notes
- developed by
- tested by
- troubleshooting / support notes

### Business Brief

Used for:
- stakeholder summaries
- product/business communication
- internal value explanation

Includes:
- problem summary
- what changed
- business scenarios
- impact / benefits
- rollout notes

### Handoff actions

For each generated document, the dashboard supports:
- inline edit
- download as Markdown
- download as PDF
- attach PDF to Trello and add a comment
- send PDF to a Slack channel
- send PDF to a Slack user by DM

Notes:
- `developed by` and `tested by` are derived from Trello card members
- tester names are matched from the internal QA team list
- toggle details are intentionally included in the Support Guide
- document generation currently works from approved cards in the active release session

## AC Generation

AC generation is now research-first, not card-text-only.

Input priority:
- Trello card title + description
- linked PR / code references
- internal wiki
- Zendesk / customer issue references
- related `Backlog` cards on the same issue
- automation/code/docs context

What the generator does:
- classifies the card type first:
  - bug/customer issue
  - toggle/rollout
  - packaging/carrier rule
  - rates/checkout
  - settings/config
  - general feature
- builds a structured research brief
- generates AC from that brief
- runs an AC review pass
- auto-rewrites if the review finds:
  - duplicate scenarios
  - vague expected results
  - missing prerequisites
  - unsupported claims
  - missing customer-impact / regression coverage
  - missing source attribution

Persistence:
- generated AC is stored in `data/ac_drafts.json`
- AC review findings are also persisted there
- posting status for AI-generated AC Trello comments is also persisted

Visible AC actions in dashboard:
- save to Trello description
- post Trello comment
- send via Slack
- skip and keep existing

## Test Case Generation

Test cases are generated after AC validation.

Current TC rules:
- minimum 4 TCs
- mix of Positive / Negative / Edge
- exact markdown format:
  - `### TC-N: Title`
  - `**Type:**`
  - `**Priority:**`
  - `**Preconditions:**`
  - `**Steps:**`
- desktop/web only

TC review pass:
- checks for duplicate or overlapping TCs
- missing Positive / Negative / Edge mix
- vague steps
- weak expected results
- missing prerequisites
- missing important AC coverage
- accidental mobile/responsive coverage
- auto-rewrites when needed

Exports:
- Trello comment gets a summarized QA test-case comment
- Google Sheet / CSV-style output gets only Positive test cases
- internal verifier metadata does **not** go into Trello or sheet

## AI QA Agent — How It Works

The AI QA Agent is an autonomous browser agent that now verifies **selected reviewed test cases** end-to-end.

### Decision flow per test case

```
Reviewed test case
      ↓
1. Parse TC into structured metadata
   • type
   • priority
   • preconditions
   • internal execution_flow hint
      ↓
2. Domain Expert / deterministic prerequisite planner
   • deterministic categories skip unnecessary model calls
   • TC still gets domain/code/wiki context where needed
      ↓
3. Pre-Requirements Resolver / orchestration
   • order setup
   • settings / products / packaging setup
   • manual or auto label flow launch
      ↓
4. Deterministic browser helpers
   • Shopify order search/open
   • manual label launch
   • auto label launch
   • return label launch/generation
   • pickup request
   • bulk auto-generate
   • view logs / request-response ZIP / print documents
      ↓
5. Agentic browser loop
   • used for the uncertain parts only
   • browser state + screenshot + logs/documents are fed back into the loop
      ↓
6. Verdict: ✅ pass | ❌ fail | ⚠️ partial | 🛑 blocked/stopped
```

### Internal TC execution-flow hint

The verifier now stores internal-only `execution_flow` metadata per parsed TC:
- `manual`
- `auto`

Important:
- this is **not** added to TC markdown
- this is **not** added to Trello comments
- this is **not** added to CSV / Google Sheet
- it is only used inside `pipeline/smart_ac_verifier.py`

Flow rule:
- `manual` for:
  - SideDock options
  - rate-log / View Logs checks
  - packaging checks before final label generation
  - HAL / signature / insurance / COD / duties / taxes
- `auto` for:
  - final generated output verification
  - order summary verification
  - request/response ZIP after label generation
  - document download / print-document checks after label generation

### Order judgment

| Scenario type | Order decision |
|---|---|
| "bulk label", "50 orders", "select all orders", "batch label" | `create_bulk` (sanity-sized set for verifier) |
| "generate label", "dry ice", "alcohol", "battery", "signature", "HAL", "COD", "international" | `create_new` |
| "return label", "verify existing label", "download docs", "next/prev navigation" | `existing_fulfilled` |
| "address update", "edit shipping address" | `existing_unfulfilled` |
| "settings", "configure", "order grid", "navigation", "pickup scheduling" | `none` |

### Deterministic playbooks implemented

Current hardcoded setup/verification playbooks include:
- packaging flow
  - settings → packaging → `more settings`
  - carrier/custom box setup
  - product dimensions/weight setup
- product special services
  - dry ice
  - alcohol
  - battery
  - product-level signature
- manual label flow launch
  - Shopify search → open order → More actions → Generate Label
- auto label flow launch
  - Shopify search → open order → More actions → Auto-Generate Label
- return label
  - app Shipping → open order → Return Packages → generate return label
- pickup
  - app Shipping → request pickup → verify pickup row/details
- bulk labels
  - Shopify Orders → select orders → Actions → Auto-Generate Labels → poll until `label generated`

### Verification strategies

| Strategy | When to use | How |
|---|---|---|
| 1 — Label exists | "label is generated", "label status" | Look for "label generated" badge on Order Summary |
| 2 — Physical docs | "label PDF exists", "packing slip", "CI present" | More Actions → Download Documents ZIP |
| 3 — JSON fields | signature type, special services, HAL, dry ice weight, declared value | More Actions → How To → Click Here ZIP |
| 4 — Rate log | Rate request JSON DURING manual label (before generate) | ⋯ → View Logs → parse visible request JSON |
| 5 — Visual label / document PDF | Text codes on printed label | Print Documents → new tab → capture document URL → parse PDF text |

> **CI (Commercial Invoice)** is only present for international orders. Domestic US orders have label + packing slip only.

### Evidence captured per test case

Each result now stores structured evidence such as:
- scenario category
- order action
- whether orchestration ran
- setup URL / final URL
- setup/final screenshots
- summarized request log / ZIP content
- evidence notes

### Stop behavior

The dashboard stop button is cooperative:
- it does not kill the browser mid-click
- it stops at the next safe checkpoint
- progress remains visible in the dashboard while the run is active

### When it asks QA
The agent now tries harder to avoid `qa_needed`, but QA input can still be used for stuck cases.

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
│   ├── smart_ac_verifier.py  # AI QA Agent — TC-based browser verifier/orchestrator
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

## Automation Generation

Automation generation now uses the reviewed pipeline outputs:
- approved/generated AC
- reviewed test cases
- AI QA evidence
- manual QA notes from dashboard

Selection rule:
- prefer `1-2` strong E2E cases
- pick top `2` Positive TCs by priority
- optionally add `1` extra automation-safe Edge/Negative case
- do not force negatives when they are poor E2E candidates

Generation rules:
- first try to reuse an existing page object
- if page exists:
  - add needed locators/functions there
- if page does not exist:
  - create a new page object + spec
- generated automation should follow the existing automation repo pattern
- after generation, run/fix loop can fix locator/assertion issues

Assertion direction:
- prefer business assertions, not shallow page-open checks
- examples:
  - `label generated`
  - request/response/log evidence
  - saved settings persistence
  - pickup confirmation/status
  - print/documents visibility

---

## Tests

```bash
pytest tests/ -v
```
