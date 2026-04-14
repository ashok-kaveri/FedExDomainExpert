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
3. Pre-Requirements Resolver — injects hardcoded setup steps for known scenario types:
   dry ice / alcohol / battery → enable on AppProducts, fill fields, cleanup after
   signature / HAL / insurance → configure in SideDock before generating
  ↓
4. Planning — Claude outputs JSON plan including:
   - nav_clicks[]        navigation path
   - look_for[]          what to verify
   - api_to_watch[]      network calls to watch
   - order_action        what order to create/find (see below)
  ↓
5. Order Setup (before browser loop):
   - "create_new"    → order_creator.py creates 1 Shopify order via REST API
   - "create_bulk"   → order_creator.py creates 5–10 orders (capped for AC verification)
   - "existing_unfulfilled" → injected as context: find in Shopify Orders → Unfulfilled tab
   - "existing_fulfilled"   → injected as context: find in app Shipping → Label Generated tab
   - "none"          → no order action taken
  ↓ (agentic loop — up to 15 steps)
6. Browser action: navigate / click / fill / scroll / observe / download_zip / download_file / switch_tab / close_tab
7. Capture: AX tree (depth 6, 250 lines) + screenshot (base64 PNG) + network calls (app frames only)
8. Claude decides next action OR gives verdict OR asks QA
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
- `switch_tab` — switch to most recently opened browser tab (e.g. document viewer)
- `close_tab` — close current tab, return to first (main) tab
- `download_zip` — click element → intercept ZIP download → unzip → read JSON/CSV/XML/TXT → inject into next step context
- `download_file` — click element → intercept direct file download (CSV/Excel/PDF) → read content → inject into next step context
- `verify` — final verdict (pass/fail/partial) with finding
- `qa_needed` — Claude is stuck, asks QA a specific question

### Document Verification — Critical Distinction

| Button / Action | What it does | How agent handles it |
|---|---|---|
| **Print Documents** (standalone button) | Opens a NEW BROWSER TAB with PluginHive document viewer (label + packing slip + CI) | `switch_tab` → screenshot → read visually → `close_tab` |
| **More Actions → Download Documents** | Downloads a ZIP with physical docs (label PDF + packing slip PDF + CI PDF). No JSON. | `click "More Actions"` → `download_zip target="Download Documents"` |
| **More Actions → How To → Click Here** | Downloads RequestResponse ZIP with createShipment request/response JSON. The ONLY source of JSON. | `click "More Actions"` → `click "How To"` → scroll → `download_zip target="Click Here"` |

### Verification Strategies
1. **Strategy 1** — label exists: look for "label generated" badge on Order Summary
2. **Strategy 2** — physical docs present (label PDF, packing slip, CI): More Actions → `download_zip "Download Documents"`
3. **Strategy 3** — JSON field values (signature, special services, HAL, declared value, dry ice, alcohol, battery): More Actions → How To → `download_zip "Click Here"` — **the only way to get JSON**
4. **Strategy 4** — rate log during manual label (BEFORE generating): ⋯ → View Logs → screenshot dialog
5. **Strategy 5** — visual label codes (ICE, ALCOHOL, ELB, ASR, DSR): Print Documents → `switch_tab` → screenshot → read codes → `close_tab`

### Pre-Requirements Resolver (`_get_preconditions`)
Hardcoded setup flows injected into the plan prompt for known scenario types:

| Scenario keyword | Pre-requirement | Cleanup |
|---|---|---|
| dry ice | AppProducts → "Is Dry Ice Needed" → weight 0.3 kg → Save | uncheck → Save |
| alcohol | AppProducts → "Is Alcohol" → type → Save | uncheck → Save |
| battery | AppProducts → "Is Battery" → material/packing type → Save | uncheck → Save |
| signature (product-level) | AppProducts → Signature field → set value → Save | reset to "As Per General Settings" → Save |
| HAL | SideDock → Hold at Location button → modal → select → Yes | n/a (per-order) |
| insurance | SideDock → Insurance checkbox → pencil → modal | n/a (per-order) |

PDF label codes verified via Strategy 5: `ICE` (dry ice) · `ALCOHOL` · `ELB` (battery, NOT "BATTERY") · `ASR` (adult sig) · `DSR` (direct sig) · `ISR` (indirect) · `SS AVXA` (service default)

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

### Request JSON Field Paths (Strategy 3 — via How To → Click Here ZIP)
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
requestedShipment.shipmentSpecialServices.batteryDetails[0].batteryPackingType
requestedShipment.shipmentSpecialServices.batteryDetails[0].regulatorySubType

# Visual label codes (Strategy 5 — Print Documents → new tab → screenshot)
"ICE"     → dry ice
"ALCOHOL" → alcohol shipment
"ELB"     → battery (NOT "BATTERY")
"ASR"     → Adult Signature Required
"DSR"     → Direct Signature Required
"ISR"     → Indirect Signature Required
"SS AVXA" → Service Default signature
```

### CI (Commercial Invoice)
CI is only present in Download Documents / Print Documents for **international orders** (shipments outside US).
Domestic US orders have label PDF + packing slip only — no CI.

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
5. **AX tree too shallow** → depth 4, 70 lines → fixed: depth 6, 250 lines
6. **Frontend main branch missing** → fixed: `git fetch origin --prune` in `get_repo_info()`
7. **Download Documents opens ZIP not PDF** → fixed: `download_zip` action + 5-strategy verification guide
8. **ANTHROPIC_API_KEY not loading** → fixed: explicit dotenv path in `config.py`
9. **shopify_actions not indexed** → folder had trailing space `shopify-actions ` → fixed in `config.py`
10. **`import config` missing in `run_ingest.py`** → caused NameError on shopify_actions source → fixed
11. **Iframe filter inverted** → `and frame_url == "about:blank"` made condition wrong — all non-blank frames passed through → fixed: removed that clause
12. **`except Exception as re:`** → shadowed stdlib `re` module → fixed: renamed to `reset_err`
13. **`_WG_ALWAYS` dead entries** → "App Sidebar Navigation"/"Shopify Admin Navigation" didn't match actual headers → fixed
14. **`reverify_failed` missing stop_flag** → stop button ignored during re-verification → fixed
15. **Print Documents documented as ZIP download** → Print Documents opens a NEW TAB viewer — fixed everywhere in workflow guide
16. **`download_zip` only read JSON inside ZIPs** → now reads CSV, XML, TXT, log files too
17. **`download_file` NameError** → logger referenced `zip_summary` instead of `file_summary` → fixed
18. **`download_zip` temp dir leak** → `os.rmdir()` fails on non-empty dirs → fixed: `shutil.rmtree()`
19. **`_parse_json` fallback can't extract arrays** → regex `\{…\}` never matches `[…]` → fixed: also matches `[…]`
20. **`close_tab` stale page snapshot** → read `ctx.pages` before `page.close()` → fixed: re-fetch after close
21. **`_network()` no iframe filter** → evaluated XHR in all iframes including analytics/GTM → fixed: same URL filter as `_ax_tree`
22. **`_plan_scenario` preconditions never injected** → search string `"Respond with ONLY a JSON object"` didn't exist in `_PLAN_PROMPT` → fixed: matches `"Respond ONLY in JSON:"`

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
