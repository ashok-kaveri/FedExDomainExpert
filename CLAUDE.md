# FedexDomainExpert — Claude Session Context

> **Read this first in every session.** Captures all design decisions, bugs fixed, and current state of every component.

---

## Project Overview

**FedexDomainExpert** is an AI-powered QA platform for the PluginHive FedEx Shopify App.
Three main capabilities:

1. **Domain Expert Chat** — RAG-backed chatbot. Answers questions about the FedEx Shopify app from real docs, wiki, codebase, and past approved cards.
2. **AI QA Agent** — Autonomous browser agent (formerly "Smart AC Verifier"). Opens the real app, verifies every AC scenario, creates Shopify orders automatically, configures settings, downloads logs, reads label JSON, and reports pass/fail per scenario. Asks QA when genuinely stuck.
3. **Pipeline Dashboard** — Streamlit UI orchestrating: Trello card → AC writing → AI QA Agent → Playwright test generation → sign-off.

---

## Key File Map

| File | Purpose |
|------|---------|
| `pipeline/smart_ac_verifier.py` | **AI QA Agent** — core agentic AC verifier (most complex file) |
| `pipeline/order_creator.py` | Shopify order creation for AI QA Agent (single + bulk, reads same config as TS helper) |
| `ui/pipeline_dashboard.py` | Streamlit dashboard — threading for non-blocking runs |
| `pipeline/card_processor.py` | AC writer + test case generator (uses backend/frontend/automation RAG) |
| `pipeline/feature_detector.py` | Classifies card as new vs existing feature |
| `pipeline/rag_updater.py` | Auto-embeds approved Trello cards into ChromaDB after each sprint |
| `pipeline/trello_client.py` | Trello REST API wrapper |
| `rag/code_indexer.py` | Indexes automation POM + backend + frontend code into ChromaDB |
| `rag/vectorstore.py` | ChromaDB operations (fedex_knowledge collection) |
| `config.py` | All env-driven config: models, paths, ChromaDB, seed URLs |
| `ingest/run_ingest.py` | Master ingestion pipeline — requires `import config` at top |

---

## AI QA Agent — Full Architecture

### Name
- **Display name:** AI QA Agent
- **File:** `pipeline/smart_ac_verifier.py` (filename kept for import compatibility)
- **Old name:** Smart AC Verifier (do not use this name in new docs or UI)

### Flow
```
AC Text
  ↓
1. Claude extracts testable scenarios (JSON array)
  ↓ (per scenario)
2. Domain Expert — queries RAG (PluginHive + FedEx API + wiki + code RAG)
   Returns ≤200 words: expected behaviour, API signals, key checks
  ↓
3. Planning — Claude outputs JSON plan including:
   - nav_clicks[]        navigation path
   - look_for[]          what to verify
   - api_to_watch[]      network calls to watch
   - order_action        what order to create/find (see below)
  ↓
4. Order Setup (before browser loop):
   - "create_new"    → order_creator.py creates 1 Shopify order via REST API
   - "create_bulk"   → order_creator.py creates 5–10 orders (capped for AC verification)
   - "existing_unfulfilled" → injected as context: find in Shopify Orders → Unfulfilled tab
   - "existing_fulfilled"   → injected as context: find in app Shipping → Label Generated tab
   - "none"          → no order action taken
  ↓ (agentic loop — up to 10 steps)
5. Browser action: navigate / click / fill / scroll / observe / download_zip / switch_tab / close_tab
6. Capture: AX tree (depth 6, 150 lines) + screenshot (base64 PNG) + network calls
7. Claude decides next action OR gives verdict OR asks QA
  ↓
✅ pass / ❌ fail / ⚠️ partial / 🔶 qa_needed  per scenario
```

### Order Decision Logic

| order_action | When used | What happens |
|---|---|---|
| `create_bulk` | "bulk", "50 orders", "select all orders", "batch label" | Creates 5 orders via Shopify REST API (capped at 10 for AC) |
| `create_new` | Any single label gen: dry ice, alcohol, signature, HAL, COD, international, domestic | Creates 1 order via Shopify REST API with right product + address |
| `existing_unfulfilled` | Address update scenarios | Context injected: find in Shopify Orders → Unfulfilled |
| `existing_fulfilled` | Return label, verify label, download docs, next/prev navigation | Context injected: find in app Shipping → Label Generated tab |
| `none` | Settings, configure, navigation, order grid, rate log, pickup scheduling | No order action |

### Order Creator (`pipeline/order_creator.py`)
- Reads `testData/products/productsconfig.json` and `testData/products/addressconfig.json` from the automation codebase (same files as TypeScript `ShopifyOrderUploader`)
- Reads `STORE`, `SHOPIFY_ACCESS_TOKEN`, `SHOPIFY_API_VERSION` from automation `.env`
- Supports product types: `simple`, `variable`, `digital`, `dangerous`
- Supports address types: `default` (US), `UK`, `CA`
- Infers product type from scenario keywords (dry ice/alcohol/battery → dangerous, etc.)
- Infers address type from scenario keywords (international/UK → UK, Canada/CA → CA)
- `infer_order_decision(scenario)` — fallback if plan JSON missing `order_action`

### Actions Available to Claude (agentic loop)
- `observe` — take stock of current page (always first step)
- `click` — click button/link/checkbox (tries iframe first, then full page)
- `fill` — type into input field
- `scroll` — scroll page down 400px
- `navigate` — go to a URL path
- `switch_tab` — switch to most recently opened browser tab (e.g. PDF viewer)
- `close_tab` — close current tab, return to first tab
- `download_zip` — click element → intercept ZIP → unzip → parse JSON → inject into next step context
- `verify` — final verdict (pass/fail/partial) with finding
- `qa_needed` — Claude is stuck, asks QA a specific question

### ZIP Download (document verification)
"More Actions" → "Download Documents" downloads a ZIP with label PDF + createShipment request/response JSON.

```
click "More Actions"
→ download_zip target="Download Documents"
→ JSON auto-extracted, prepended to context
→ observe (sees JSON)
→ verify based on field values
```

### Verification Strategies
1. **Strategy 1** — label exists: look for "label generated" badge on Order Summary
2. **Strategy 2** — field values (signature, special services, HAL, declared value): download ZIP → read JSON
3. **Strategy 3** — alternative ZIP: More Actions → How To → download_zip "Click Here"
4. **Strategy 4** — rate log (during manual label BEFORE generating): ⋯ → View Logs → screenshot dialog
5. **Strategy 5** — label visual (ICE, ALCOHOL, ASR codes): Print Documents → switch_tab → screenshot → close_tab

---

## FedEx App UI Architecture (Critical)

### Iframe Structure
- FedEx app embedded inside Shopify admin: `iframe[name="app-iframe"]`
- App sidebar (Shipping, Settings, PickUp, Products, FAQ, Rates Log) → **INSIDE** iframe
- Shopify admin sidebar (Orders, Products) → **OUTSIDE** iframe
- Nav strategy: app nav → search iframe first; Shopify nav → search full page first

### Label Generation Flows

**Manual Label:**
Shopify Orders → order row → More Actions → "Generate Label"
→ LEFT: Generate Packages → Get Rates → select service
  RIGHT: SideDock (ALWAYS VISIBLE — configure BEFORE generating)
→ "Generate Label" → Order Summary

**Auto Label:**
Shopify Orders → order row → More Actions → "Auto-Generate Label"
→ Label generated automatically → Order Summary

**SideDock (right panel, manual label page):**
1. Address Classification (Residential/Commercial)
2. Signature Options (ADULT/DIRECT/INDIRECT/NO_SIGNATURE_REQUIRED/SERVICE_DEFAULT)
3. Hold at Location (HAL) — button → modal → select location → Yes
4. Insurance — checkbox → pencil icon → modal
5. COD — checkbox → COD Amount, TIN Type, contact, address
6. Duties & Taxes (international) — Purpose, Terms of Sale, Duties Payment Type
7. Freight — Additional freight info

### Return Label
**Way A:** Order Summary → Return packages tab → Return Packages button → Refresh Rates → select → Generate Return Label
**Way B:** Shopify Orders → order → More Actions → "Generate Return Label" (NOT "Create return label")

### Bulk Label Generation (Shopify admin orders list)
1. Navigate to Shopify admin → Orders list
2. Click header `<label>` (NOT the `<input>` — it has `opacity:0`) → selects all 50 orders
3. Bulk actions bar appears → "Actions" button (`aria-label="Actions"`, scoped to `[class*="StickyBulkActions"]`)
4. Click "Auto-Generate Labels" — it's a `<a>` LINK not a button: `getByRole('link', { name: 'Auto-Generate Labels' })`
5. After click: `waitForURL(url => !url.includes('/orders'))` → `waitForLoadState('domcontentloaded')`
   (DO NOT use `networkidle` — Shopify has constant background XHR that prevents it from settling)

### Request JSON Field Paths
```
# Package level
requestedShipment.requestedPackageLineItems[0].dimensions
requestedShipment.requestedPackageLineItems[0].weight.value
requestedShipment.requestedPackageLineItems[0].declaredValue.amount
requestedShipment.requestedPackageLineItems[0].packageSpecialServices.signatureOptionType
requestedShipment.requestedPackageLineItems[0].packageSpecialServices.dryIceWeight.value

# Shipment level special services
requestedShipment.shipmentSpecialServices.specialServiceTypes
  → "HOLD_AT_LOCATION" | "DRY_ICE" | "ALCOHOL" | "BATTERY" | "FEDEX_ONE_RATE"
requestedShipment.shipmentSpecialServices.holdAtLocationDetail.locationId
requestedShipment.shipmentSpecialServices.alcoholDetail.alcoholRecipientType
requestedShipment.shipmentSpecialServices.batteryDetails[0].materialType

# Visual label codes (Strategy 5)
"ICE" → dry ice | "ASR" → Adult Signature | "DSR" → Direct | "ISA" → Indirect
"SS AVXA" → Service Default | "ALCOHOL" → alcohol shipment
```

---

## RAG / Knowledge Base

### Collections
- `fedex_knowledge` — domain docs (PluginHive, FedEx API, wiki, app UI, test cases, approved cards)
- `fedex_code_knowledge` — source code (automation POM + backend + frontend)

### Sources (`ingest/run_ingest.py`)
Default sources: `fedex_rest pluginhive_docs pluginhive_seeds app codebase pdf wiki shopify_actions`

⚠️ `run_ingest.py` requires `import config` at the top (was missing, now fixed — do not remove it)

### Partial re-ingest (fast)
```bash
PYTHONPATH=. .venv/bin/python ingest/run_ingest.py --sources wiki shopify_actions
```

### Self-learning
After every approved Trello card cycle, `pipeline/rag_updater.py` embeds the card's description, AC, and test cases into ChromaDB automatically. The system gets smarter every sprint.

---

## Streamlit Threading (Critical — Stop Button)

AI QA Agent runs in a background `threading.Thread` so the UI stays responsive.

```python
_sav_running_key = f"sav_running_{card_id}"   # bool — thread running
_sav_stop_key    = f"sav_stop_{card_id}"       # bool — stop requested
_sav_result_key  = f"sav_result_{card_id}"     # dict — {done, report, error}
_sav_prog_key    = f"sav_prog_{card_id}"       # dict — {pct, text}
```

---

## Claude Models

| Purpose | Model | Config key |
|---|---|---|
| AI QA Agent, domain expert chat | `claude-sonnet-4-6` | `CLAUDE_SONNET_MODEL` |
| Card processing, feature detection | `claude-haiku-4-5-20251001` | `CLAUDE_HAIKU_MODEL` |

---

## Config Fix (critical — do not revert)

`config.py` uses `load_dotenv(dotenv_path=Path(__file__).parent / ".env", override=True)`
NOT plain `load_dotenv()` — the explicit path is required because the dashboard is launched
from different working directories and `load_dotenv()` without a path fails silently.

---

## Known Issues Fixed (do not re-introduce)

1. **Stop button never appeared** → fixed by threading
2. **All scenarios qa_needed** → nav failures were fatal → fixed: non-fatal, agentic loop continues
3. **Wrong nav element clicked** → Shopify's own Settings/Shipping clicked instead of app's → fixed: iframe-first for app nav items
4. **Claude flying blind** → no screenshot → fixed: base64 PNG passed as Anthropic image block in `_decide_next()`
5. **AX tree too shallow** → depth 4, 70 lines → fixed: depth 6, 150 lines
6. **Frontend main branch missing** → fixed: `git fetch origin --prune` in `get_repo_info()`
7. **Download Documents opens ZIP not PDF** → fixed: `download_zip` action + 5-strategy verification guide
8. **ANTHROPIC_API_KEY not loading** → fixed: explicit dotenv path in `config.py`
9. **shopify_actions not indexed** → folder had trailing space `shopify-actions ` → fixed in `config.py`
10. **`import config` missing in `run_ingest.py`** → caused NameError on shopify_actions source → fixed

---

## Running the Project

```bash
cd ~/Documents/Fed-Ex-automation/FedexDomainExpert

# Dashboard (QA Pipeline)
PYTHONPATH=. .venv/bin/streamlit run ui/pipeline_dashboard.py
# → http://localhost:8501

# Domain Expert Chat
PYTHONPATH=. .venv/bin/streamlit run ui/chat_app.py
# → http://localhost:8502

# Re-ingest (partial)
PYTHONPATH=. .venv/bin/python ingest/run_ingest.py --sources wiki shopify_actions

# Re-ingest (full)
PYTHONPATH=. .venv/bin/python ingest/run_ingest.py
```
