# FedexDomainExpert — Claude Session Context

> **Read this first in every session.** It captures all design decisions, bugs fixed,
> and current state of every major component.

---

## Project Overview

**FedexDomainExpert** is an AI-powered QA assistant for the PluginHive FedEx Shopify App.
It has three main capabilities:

1. **Domain Expert Chat** — RAG-backed chatbot answering questions about the FedEx Shopify app
2. **Smart AC Verifier** — Agentic browser-based acceptance criteria verifier (most complex component)
3. **Pipeline Dashboard** — Streamlit UI that orchestrates Trello cards → AC generation → verification

---

## Key File Map

| File | Purpose |
|------|---------|
| `pipeline/smart_ac_verifier.py` | Core agentic AC verifier (most worked-on file) |
| `ui/pipeline_dashboard.py` | Streamlit dashboard — threading for non-blocking runs |
| `pipeline/trello_client.py` | Trello REST API wrapper |
| `rag/code_indexer.py` | Indexes automation POM + backend code into ChromaDB |
| `rag/vectorstore.py` | PluginHive docs RAG search |
| `config.py` | All env-driven config: models, paths, ChromaDB, seed URLs |
| `ingest/web_scraper.py` | Web scraping for PluginHive docs |
| `ingest/run_ingest.py` | Ingestion pipeline entry point |

---

## Smart AC Verifier — Full Architecture

### Flow
```
AC Text
  ↓
1. Claude extracts testable scenarios (JSON array)
  ↓ (per scenario)
2. Domain Expert consultation — Claude queries domain RAG + code RAG,
   synthesises ≤200 words about: expected behaviour, API signals, key checks
  ↓
3. Code RAG — automation POM + backend API context fetched
  ↓
4. Claude plans: nav_clicks[], look_for[], api_to_watch[], plan sentence
  ↓ (agentic loop — up to 10 steps)
5. Browser action: navigate / click / fill / scroll / observe / download_zip
6. Capture: AX tree (depth 6, 150 lines) + screenshot (base64) + network calls
7. Claude decides next action OR gives verdict OR asks QA
  ↓
✅ pass / ❌ fail / ⚠️ partial / 🔶 qa_needed  per scenario
```

### Actions Available to Claude
- `observe` — take stock of current page state (always first step)
- `click` — click button/link/checkbox (tries iframe first, then full page)
- `fill` — type into input field
- `scroll` — scroll page down 400px
- `navigate` — go to a URL path
- `switch_tab` — switch to most recently opened browser tab
- `close_tab` — close current tab, return to first tab
- `download_zip` — click element, intercept ZIP download, unzip, parse JSON files,
                    store content in `action["_zip_content"]` → injected into next step's context
- `verify` — final verdict (pass/fail/partial) with finding
- `qa_needed` — Claude is genuinely stuck, asks QA a question

### ZIP Download Feature (document verification)
The "More Actions" → "Download Documents" button on the Order Summary page downloads a ZIP
containing the label PDF + createShipment request/response JSON files.

Flow Claude should follow for field-level verification:
1. `click` "More Actions"
2. `download_zip` target="Download Documents"
   → ZIP extracted automatically, JSON content prepended to context for step 3
3. `observe` (sees JSON in context)
4. `verify` based on JSON field values

Alternative (How To modal):
1. `click` "More Actions" → `click` "How To" → modal opens
2. `download_zip` target="Click Here" → RequestResponse ZIP downloaded

This mirrors the automation's `downloadLogs()` + `getLabelRequestLog()` pattern in BasePage.ts.

---

## FedEx App UI Architecture (Critical)

### Iframe Structure
- The FedEx app is embedded inside Shopify admin as an iframe: `iframe[name="app-iframe"]`
- App sidebar items (Shipping, Settings, PickUp, Products, FAQ, Rates Log) are **INSIDE** the iframe
- Shopify admin items (Orders, Products in admin sidebar) are **OUTSIDE** the iframe
- Navigation strategy: app nav items → search iframe first; Shopify nav → search full page first

### App Sidebar Navigation (inside iframe)
- **Shipping** → "All Orders" grid (All / Pending / Label Generated tabs)
- **PickUp** → Schedule FedEx pickup
- **Products** → Map products to FedEx packages (DIFFERENT from Shopify Products)
- **Settings** → FedEx account, services, packages, additional services
- **FAQ** → Help articles
- **Rates Log** → Historical rate request log

### Shopify Admin Navigation (outside iframe, left sidebar)
- **Orders** — Shopify orders list (where you click More Actions → Generate Label)
- **Products** — Shopify product catalog (create/edit products)

### All Orders Grid (app Shipping page)
Columns: Order#, Label created date, Customer, Label status, Shipping Service,
         Subtotal, Shipping Cost, Packages, Products, Weight, Messages
Tab filters: All | Pending | Label Generated
Status values: "label generated" (green), "inprogress" (yellow), "failed" (red),
               "auto cancelled" (grey), "label cancelled"
**Click an order ROW → opens Order Summary page for that order**
Top-right buttons: "Generate New Labels", "How to", "Help", "Generate Report"

### Order Summary Page (after clicking an order or after label generation)
Buttons:
- "Print Documents" — opens **PluginHive document viewer** in a NEW TAB
  URL: `qa01-document-viewer.pluginhive.io/?status=https://...amazonaws.com/...pdf`
  NOT the browser's built-in PDF viewer — it's a web viewer. Use `switch_tab` → screenshot → read visually
- "Upload Documents" — upload custom docs
- "More Actions" dropdown:
  - "Download Documents" → downloads ZIP (label PDF + request/response JSON)
  - "Cancel Label"
  - "Return Label"
  - "How To" → modal with "Click Here" button (downloads RequestResponse ZIP)
- TWO TABS: "Packages" | "Return packages"
- "← #XXXX" back arrow → back to Shipping grid

### Label Generation Flows

**Manual Label** (user picks service):
Shopify Orders → order row → More Actions → "Generate Label"
→ App opens (iframe) with TWO areas:
  LEFT: a. "Generate Packages" → b. "Get Shipping Rates" → c. Select radio → d. "Generate Label"
  RIGHT: **The SideDock** (ALWAYS VISIBLE — configure BEFORE generating label)
→ Redirects to Order Summary

### The SideDock — Always Visible Right Panel in Manual Label Page
Contains (top to bottom):
1. **Address Classification**: Commercial / Residential dropdown
2. **Signature Options** (aria-label="FedEx® Delivery Signature Options"):
   ADULT, DIRECT, INDIRECT, NO_SIGNATURE_REQUIRED, SERVICE_DEFAULT
   ⚠️ **OVERRIDES all product-level and global signature settings**
3. **Hold at Location (HAL)**: "Hold at Location" button → modal → select location → Yes
4. **Insurance**: "Add Third Party Insurance To Packages?" checkbox → Edit pencil icon → modal:
   - Liability Type (New / Used or Reconditioned)
   - Amount Type (Declared Value / Percentage of Product Price)
   - Percentage input if Percentage selected
5. **COD** (Cash on Delivery): "Add COD Collect" checkbox (isCodRequired) → fields:
   COD Amount, TIN Type (BUSINESS_NATIONAL/STATE/UNION, PERSONAL_NATIONAL/STATE),
   TIN Number, contact name/company/phone, address, reference indicator
6. **International / Duties & Taxes**:
   Purpose of Shipment (GIFT/SAMPLE/RETURN/REPAIR/OTHERS),
   Terms of Sale (CFR/CIF/CIP/EXW/FOB/FAS/DAF),
   Duties Payment Type (SENDER/RECIPIENT/THIRD_PARTY → account number if THIRD_PARTY),
   "Add Additional Commercial Invoice Info" checkbox → customs value, comments, freight charge
7. **Freight**: "Add Additional Freight Info" checkbox → Collect Terms, Freight ID, packaging, instructions

**Auto Label** (app picks service):
Shopify Orders → order row → More Actions → "Auto-Generate Label"
→ Label generated automatically → Order Summary shown

### Return Label Flows (two entry points)
**WAY A — From app Order Summary**:
Order Summary → "Return packages" tab → "Return Packages" button
→ Enter return quantity → "Refresh Rates" → select service → "Generate Return Label"
→ Verify: "SUCCESS" badge + "Download Label" link visible

**WAY B — From Shopify admin order page**:
Shopify Orders → click order → More Actions → **"Generate Return Label"**
(NOT "Create return label" — that is a Shopify-native feature, different thing)
Other More Actions options visible: Auto-Generate Label, Generate Label, Print Label, Create return label

### Rate Logs (ALL JSON — REST API only, no SOAP/XML)
**Rate log (in-page, during manual label)**:
After "Get Shipping Rates" → click ⋯ → "View Logs"
→ Dialog shows JSON Request (left) + Response (right) IN THE PAGE (no download)

**Label log (ZIP, after label generated)**:
Strategy 2: More Actions → Download Documents → ZIP with label PDF + JSON
Strategy 3: More Actions → How To → Click Here → ZIP with JSON only
Strategy 4 (rate only): ⋯ → "Download Logs" → ZIP download

### Pickup Scheduling Flow
1. Shipping grid → select order checkbox → More actions → "Request Pick Up" → Yes
2. Navigate to PickUp sidebar → verify row: pickup number, Status="SUCCESS", timestamp, order ID
3. Pagination: "Page N of M" — Previous/Next buttons

### FedEx One Rate Settings Flow
1. Settings → Packaging → "more settings" → Packing Method = Box Packing → keep only FedEx Small Box
2. Settings → Additional Services → "FedEx One Rate®" → Enable checkbox → Save
3. Toast: "Fedex One Rate® updated"
4. Verify JSON: specialServiceTypes includes "FEDEX_ONE_RATE"

---

## Product Workflows

### When to Create vs Use Existing Products
- **DEFAULT**: Use existing products in Shopify admin. Do NOT create new ones unless explicitly needed.
- **FedEx App Products**: Search existing in app Products page (use "Test Product A" or "Test Product B")

### FedEx App Product Config (inside iframe)
1. Click "Products" in app sidebar
2. Click search/filter → type product name → press Enter
3. Click product row
4. NORMAL product: set Dimensions (L/W/H + unit) + Signature Option only
   Do NOT touch: Alcohol / Battery / Dry Ice / Dangerous Goods (unless scenario tests them)
5. SPECIAL services: enable ONLY if scenario explicitly tests them
6. Click "Save" → toast: "Products Successfully Saved"

### Special Services (only when scenario mentions them)
- "Is Alcohol" → Alcohol Recipient Type: CONSUMER or LICENSEE
- "Is Battery" → Battery Material Type + Battery Packing Type
- "Is Dry Ice Needed" → Dry Ice Weight (kg)
- "Is Dangerous Goods" → LIMITED_QUANTITIES_COMMODITIES / HAZARDOUS_MATERIALS / ORM_D

---

## Request JSON Field Paths (for verification)
All logs are **JSON** (REST API only — SOAP/XML is deprecated and not used).
```
# Package-level
requestedShipment.requestedPackageLineItems[0].dimensions               → L/W/H/units
requestedShipment.requestedPackageLineItems[0].weight.value             → weight
requestedShipment.requestedPackageLineItems[0].declaredValue.amount     → declared value
requestedShipment.requestedPackageLineItems[0].packageSpecialServices.signatureOptionType
requestedShipment.requestedPackageLineItems[0].packageSpecialServices.dryIceWeight.value
requestedShipment.requestedPackageLineItems[0].packageSpecialServices.dryIceWeight.units

# Shipment-level special services
requestedShipment.shipmentSpecialServices.specialServiceTypes           → array:
  "HOLD_AT_LOCATION" | "DRY_ICE" | "ALCOHOL" | "BATTERY" | "FEDEX_ONE_RATE"
requestedShipment.shipmentSpecialServices.holdAtLocationDetail.locationId
requestedShipment.shipmentSpecialServices.holdAtLocationDetail.locationType
requestedShipment.shipmentSpecialServices.alcoholDetail.alcoholRecipientType → CONSUMER | LICENSEE
requestedShipment.shipmentSpecialServices.batteryDetails[0].materialType     → LITHIUM_ION | LITHIUM_METAL
requestedShipment.shipmentSpecialServices.batteryDetails[0].packingType      → CONTAINED_IN_EQUIPMENT | PACKED_WITH_EQUIPMENT

# Label verification (visual — on printed label PDF via Print Documents → new tab)
"ICE" text  → dry ice
"ASR"       → Adult Signature Required
"DSR"       → Direct Signature Required
"ISA"       → Indirect Signature Allowed
"SS AVXA"   → Service Default / As per service
"ALCOHOL"   → alcohol shipment
```

---

## Streamlit Threading (Critical — Stop Button Fix)

The dashboard runs `verify_ac()` in a background `threading.Thread` so Streamlit's
UI stays responsive and the Stop button appears immediately.

### Keys used
```python
_sav_running_key = f"sav_running_{card_id}"   # bool — is thread running?
_sav_stop_key    = f"sav_stop_{card_id}"       # bool — stop requested?
_sav_result_key  = f"sav_result_{card_id}"     # dict — {"done": bool, "report": ..., "error": ...}
_sav_prog_key    = f"sav_prog_{card_id}"       # dict — {"pct": float, "text": str}
```

### Pattern
```python
# On Run click:
st.session_state[_sav_running_key] = True
thread = threading.Thread(target=_run_verify, daemon=True)
thread.start()
st.rerun()   # ← immediately shows Stop button

# Poll loop (main thread):
if st.session_state.get(_sav_running_key):
    result = st.session_state.get(_sav_result_key, {})
    if result.get("done"):
        # harvest results, clear keys, st.rerun()
    else:
        # show progress bar, time.sleep(2), st.rerun()
```

---

## Code Indexer — Remote Branch Fix

`rag/code_indexer.py` `get_repo_info()` now runs `git fetch origin --prune --quiet` before
listing branches, so remote branches (like frontend `main`) appear in the dropdown.

---

## RAG / Knowledge Base

### PluginHive Seed URLs (pluginhive_seeds source)
`config.PLUGINHIVE_SEED_URLS` has 25 high-value pages (FAQ, knowledge base, troubleshooting).
`ingest/web_scraper.py` has `scrape_pluginhive_seeds_only()` function.
`ingest/run_ingest.py` has `pluginhive_seeds` registered as a source in `_DEFAULT_SOURCES`.

### ChromaDB Collections
- `fedex_knowledge` — domain docs (PluginHive, FedEx API docs, app store)
- `fedex_code_knowledge` — source code (automation POM + backend)

---

## Claude Models Used

| Purpose | Model | Config Key |
|---------|-------|-----------|
| Deep reasoning, AC verifier | claude-sonnet-4-6 | `CLAUDE_SONNET_MODEL` |
| Fast/lightweight tasks | claude-haiku-4-5-20251001 | `CLAUDE_HAIKU_MODEL` |
| Domain expert chat | same as Sonnet (default) | `DOMAIN_EXPERT_MODEL` |

---

## Known Issues Fixed (do not re-introduce)

1. **Stop button never appeared** → fixed by threading (verify_ac runs in background thread)
2. **All scenarios qa_needed** → nav failures were fatal; fixed to be non-fatal (agentic loop continues)
3. **Wrong nav element clicked** → Shopify's own Settings/Shipping clicked instead of app's
   → fixed by searching iframe FIRST for app nav items
4. **Claude flying blind** → no screenshot passed to step decisions
   → fixed: `scr` (base64 PNG) passed as Anthropic image block in `_decide_next()`
5. **AX tree too shallow** → depth 4, 70 lines → fixed to depth 6, 150 lines
6. **Frontend main branch missing** → fixed by `git fetch origin --prune` in `get_repo_info()`
7. **Download Documents opens ZIP not PDF** → old Strategy 2 wrongly assumed PDF opens in new tab
   → fixed: new `download_zip` action + 4-strategy document verification guide

---

## Environment Variables (.env)

```
ANTHROPIC_API_KEY=...
TRELLO_API_KEY=...
TRELLO_TOKEN=...
TRELLO_BOARD_ID=...
BACKEND_CODE_PATH=~/Documents/fedex-Backend-Code/shopifyfedexapp
FRONTEND_CODE_PATH=~/Documents/fedex-Frontend-Code/shopify-fedex-web-client
AUTOMATION_CODEBASE_PATH=../fedex-test-automation   # relative to FedexDomainExpert
CLAUDE_SONNET_MODEL=claude-sonnet-4-6
CLAUDE_HAIKU_MODEL=claude-haiku-4-5-20251001
```

---

## Running the Dashboard

```bash
cd /Users/madan/Documents/Fed-Ex-automation/FedexDomainExpert
streamlit run ui/pipeline_dashboard.py
```

## Running Ingestion

```bash
# Seed URLs only (fast, ~300 chunks)
python -m ingest.run_ingest --sources pluginhive_seeds

# Full default pipeline
python -m ingest.run_ingest
```
