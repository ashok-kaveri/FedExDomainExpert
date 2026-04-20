# FedexDomainExpert — Claude Session Context

> **Read this first in every session.** Captures all design decisions, bugs fixed, and current state of every component.

---

## Project Overview

**FedexDomainExpert** is an AI-powered QA platform for the PluginHive FedEx Shopify App.
Three main capabilities:

1. **Domain Expert Chat** — RAG-backed chatbot. Answers questions about the FedEx Shopify app from real docs, wiki, codebase, and past approved cards.
2. **AI QA Agent** — Autonomous browser agent (formerly "Smart AC Verifier"). Opens the real app, verifies reviewed test cases, creates Shopify orders automatically, configures settings, downloads logs/documents, reads request/response payloads, and reports pass/fail with evidence.
3. **Pipeline Dashboard** — Streamlit UI orchestrating: Trello card → AC writing → TC generation → AI QA Agent → Playwright test generation → sign-off.

---

## Key File Map

| File | Purpose |
|------|---------|
| `pipeline/smart_ac_verifier.py` | **AI QA Agent** — core TC-based browser verifier/orchestrator (most complex file) |
| `pipeline/order_creator.py` | Shopify order creation for AI QA Agent (single + bulk, reads same config as TS helper) |
| `ui/pipeline_dashboard.py` | Streamlit dashboard — threading for non-blocking runs |
| `pipeline/card_processor.py` | AC writer + test case generator + review passes (uses backend/frontend/automation RAG) |
| `pipeline/feature_detector.py` | Classifies card as new vs existing feature |
| `pipeline/rag_updater.py` | Auto-embeds approved Trello cards into ChromaDB after each sprint |
| `pipeline/trello_client.py` | Trello REST API wrapper |
| `rag/code_indexer.py` | Indexes automation POM + backend + frontend code into ChromaDB |
| `rag/vectorstore.py` | ChromaDB operations (fedex_knowledge collection) |
| `config.py` | All env-driven config: models, paths, ChromaDB, seed URLs |
| `ingest/run_ingest.py` | Master ingestion pipeline — requires `import config` at top |

---

## Runtime Rules

- All local repo/file paths are **env-driven only** via `.env`. Do not reintroduce hardcoded fallbacks for:
  - `AUTOMATION_CODEBASE_PATH`
  - `BACKEND_CODE_PATH`
  - `FRONTEND_CODE_PATH`
  - `SHOPIFY_ACTIONS_PATH`
  - `WIKI_PATH`
  - `PDF_TEST_CASES_PATH`
  - `GOOGLE_CREDENTIALS_PATH`
- If a required path is missing, the runtime should fail clearly instead of silently falling back to the project root or a machine-specific folder.
- Trello board access is now **workspace-aware**:
  - Validate AC loads boards first, then lists for the selected board
  - Move Cards and User Story → Push to Trello also let the user choose the board
  - `TRELLO_BOARD_ID` is still useful as the default board/workspace anchor, but not as a hard requirement for every Trello flow
- Shopify Actions path can be tricky on this machine because the real folder name ends with a trailing space:
  - exact path: `"/Users/madan/Documents/shopify-actions "`
  - do not trim this value when loading from `.env` or when indexing from the dashboard

---

## AI QA Agent — Full Architecture

### Name
- **Display name:** AI QA Agent
- **File:** `pipeline/smart_ac_verifier.py` (filename kept for import compatibility)
- **Old name:** Smart AC Verifier (do not use this name in new docs or UI)

### Flow
```
Trello card
  ↓
1. AC generation from card + research context
2. AC review pass + optional auto-rewrite
3. Domain validation + optional rewrite from validation findings
4. TC generation from approved AC
5. TC review pass + optional auto-rewrite
6. QA selects how many TCs to run
  ↓ (per selected TC)
7. AI QA Agent verification
   - parsed TC metadata
   - deterministic orchestration
   - agentic loop only where needed
  ↓
8. In `Generate TC`, reviewed TCs can be published to Trello comment + Google Sheet using the project formats
9. Bug review, re-verify, and final approval stay in AI QA Verifier
10. Automation generation from approved TCs + AI QA evidence happens in `Generate Automation Script`
11. QA uses existing sign-off pattern

### Dashboard tab split

The old single `Release QA` tab is now split into three stage tabs with the same session state and workflow:

1. `Validate AC`
   - select Trello board
   - select release list
   - load cards
   - release intelligence / suggested test order
   - toggle detection / notification flow
   - AC generation
   - AC review corrections
   - domain validation / apply fixes

2. `Generate TC`
   - uses the same loaded release context from `Validate AC`
   - TC generation
   - TC review corrections
    - TC Slack send actions
   - publish reviewed TCs to:
     - Trello comment
     - Google Sheet positive-case format
   - duplicate check before sheet publish

3. `AI QA Verifier`
   - uses the same loaded release context and reviewed TCs
   - AI QA run / stop / re-verify
   - bug review + notify developer
    - Ask Domain Expert
   - final approval
   - retrospective / bug reporter follow-on sections

4. `Generate Automation Script`
   - uses approved release cards from the same loaded release context
   - per-card automation generation
   - release automation actions
   - Run Automation & Post to Slack
   - Generate Documentation

5. `Handoff Docs`
   - works from approved cards in the active release session
   - generates:
     - `Support Guide`
     - `Business Brief`
   - supports:
     - inline editing
     - Markdown download
     - PDF download
     - Trello PDF attach + comment
     - Slack channel upload
     - Slack DM upload

`Support Guide` rules:
- include developed by
- include tested by
- include toggle/prerequisite notes when detected
- use Trello card members to split QA vs developer ownership

`Business Brief` rules:
- do not include developed by / tested by
- may include rollout/toggle notes if relevant
- keep it business/stakeholder focused instead of support/procedural

Rules:
- do not duplicate release state between these tabs
- if no release is loaded yet, `Generate TC`, `AI QA Verifier`, and `Generate Automation Script` should direct the user back to `Validate AC`
- flow behavior should remain the same; only the UI presentation is split
```

### AC / TC pipeline notes

- AC generation is now research-first:
  - card
  - PR/code references
  - internal wiki
  - Zendesk/customer issue references
  - related Trello `Backlog` cards
  - app/code/automation/FedEx docs context
- AC generation has a review pass and can auto-rewrite weak output
- Domain validation can also rewrite AC directly from validation findings
- TC generation also has a review pass and can auto-rewrite weak output
- AC review findings and TC review findings are surfaced in dashboard
- AC draft persistence now includes:
  - generated AC
  - AC review findings
  - comment-posted status

### TC-based execution

AI QA execution is now TC-based, not AC-based, for the main dashboard flow.

`ParsedTestCase` contains internal metadata:
- `tc_id`
- `title`
- `type`
- `priority`
- `preconditions`
- `body`
- `execution_flow`

Important:
- `execution_flow` is **internal-only**
- it is not added to TC markdown
- it is not added to Trello comments
- it is not added to CSV / Google Sheets

`execution_flow` currently resolves to:
- `manual`
- `auto`

Used for:
- choosing manual-label vs auto-label launch in the verifier

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
| **Print Documents** (standalone button) | Opens a NEW BROWSER TAB with PluginHive document viewer (label + packing slip + CI) | capture viewer URL → extract `document` URL → download PDF → parse text |
| **More Actions → Download Documents** | Downloads a ZIP with physical docs (label PDF + packing slip PDF + CI PDF). No JSON. | `click "More Actions"` → `download_zip target="Download Documents"` |
| **More Actions → How To → Click Here** | Downloads RequestResponse ZIP with createShipment request/response JSON. The ONLY source of JSON. | `click "More Actions"` → `click "How To"` → scroll → `download_zip target="Click Here"` |

### Verification Strategies
1. **Strategy 1** — label exists: look for `label generated` badge on Order Summary
2. **Strategy 2** — physical docs present (label PDF, packing slip, CI): More Actions → `download_zip "Download Documents"`
3. **Strategy 3** — JSON field values (signature, special services, HAL, declared value, dry ice, alcohol, battery): More Actions → How To → `download_zip "Click Here"` — **the only way to get JSON**
4. **Strategy 4** — rate log during manual label (BEFORE generating): ⋯ → View Logs → parse visible request JSON
5. **Strategy 5** — visual label / document code checks (ICE, ALCOHOL, ELB, ASR, DSR): Print Documents → capture PDF text

### Deterministic orchestration now implemented

Current flow categories with deterministic helpers:
- Shopify order search/open before label launch
- manual label launch
- auto label launch
- packaging settings flow
  - packaging readiness
  - save base settings
  - open `more settings`
  - configure advanced packaging
  - cleanup/reset
- product special services
  - dry ice
  - alcohol
  - battery
  - product-level signature
- return label generation
- pickup request + details verification
- bulk label generation + completion polling
- view logs
- request/response ZIP download and summarization
- print/download document parsing

### Request/response/document summarization

The verifier now reduces raw logs/ZIP/document payloads into compact business facts before sending them back into the agent loop.

Request-side fields summarized:
- `shipment_special_services`
- `signature_option_type`
- `hold_at_location_id`
- `hold_at_location_type`
- `declared_value_amount`
- `dimensions`
- `package_weight`
- `total_weight`
- `dry_ice_weight`
- `alcohol_recipient_type`

Response-side fields summarized:
- `master_tracking_number`
- `tracking_number`
- `service_type`
- `ship_date`
- `packaging_description`
- `service_description`
- `document_types`
- `package_document_count`
- `shipment_document_count`
- `has_label_url`
- `has_encoded_label`
- `notification_codes`
- `notification_messages`
- `error_codes`
- `error_messages`

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

### Manual vs auto label rule

Use `manual` for:
- SideDock options
- View Logs / rate-log validation
- HAL / signature / insurance / COD / duties / taxes
- packaging checks before final label generation

Use `auto` for:
- final generated output checks
- order summary verification
- request/response ZIP after label generation
- document verification after label generation

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

Current stop behavior:
- stop is cooperative
- not a hard kill in the middle of a click
- verifier stops at the next safe checkpoint
- background thread progress is rendered from a shared run store instead of direct worker-thread writes into `st.session_state`

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
23. **Trello board list fixed to one board** → fixed: dashboard now loads boards first, then lists for the selected board
24. **Environment path fallback to repo root** → fixed: automation-related flows now fail fast when `AUTOMATION_CODEBASE_PATH` is missing
25. **Shopify Actions path trimmed on load/index** → fixed: preserve exact env/UI path, including trailing-space folder names
26. **TC-based verification still guessed manual/auto only from runtime scenario text** → improved: parsed TCs now carry internal-only `execution_flow` metadata into the verifier
27. **Packaging settings stopped before `more settings`** → fixed: packaging flow now waits for packaging surface, saves base settings, opens `more settings`, then applies advanced config
28. **Auto-label flow waited for manual-label page** → fixed: auto flow now waits for generated-label / order-summary state
29. **Bulk flow stopped at Shipping handoff** → fixed: now polls until `label generated`
30. **Return label flow only opened page** → fixed: now fills quantity, refreshes rates, and generates return label
31. **Print Documents only used screenshots** → fixed: now captures viewer document URL and parses PDF text
32. **ZIP summarization was request-only** → fixed: response-side business-field summarization added

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
