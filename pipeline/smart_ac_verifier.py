"""
AI QA Agent  —  Step 2b (Agentic Upgrade)
==========================================
Replaces the old screenshot-only QA Explorer with a true agentic loop:

  AC text
    │
    ▼
  1. Claude extracts each scenario
    │
    ▼  (per scenario)
  2. Query code RAG  →  automation POM + backend API + QA knowledge
     Claude knows what locators exist, what API endpoints to watch
    │
    ▼
  3. Claude plans: which app path to navigate, what to interact with
    │
    ▼  (agentic loop — up to 10 steps)
  4. Browser action  →  navigate / click / fill / scroll / observe
  5. Capture: page accessibility tree + screenshot + network calls
  6. Claude decides next action  OR  gives verdict  OR  asks QA
    │
    ▼
  ✅ pass / ❌ fail / ⚠️ partial  per scenario
    │
    ▼
  Final report  →  feeds directly into Write Automation Code

If Claude can't find a feature:
  → status = "qa_needed"
  → Dashboard shows Claude's question + QA text input
  → QA answers → re-run that scenario with the guidance injected
"""
from __future__ import annotations

import base64
import json
import logging
import os
import re
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from textwrap import dedent
from typing import Callable

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage

import config

logger = logging.getLogger(__name__)

_CODEBASE       = Path(config.AUTOMATION_CODEBASE_PATH)
_AUTH_JSON      = _CODEBASE / "auth.json"
_ENV_FILE       = _CODEBASE / ".env"
MAX_STEPS       = 15
_ANTI_BOT_ARGS  = [
    "--disable-blink-features=AutomationControlled",
    "--no-sandbox",
    "--disable-setuid-sandbox",
]
_CHALLENGE_PHRASES = [
    "connection needs to be verified",
    "let us know you",
    "verify you are human",
    "just a moment",
    "checking your browser",
]


# ── Data models ───────────────────────────────────────────────────────────────

@dataclass
class VerificationStep:
    action: str
    description: str
    target: str = ""
    success: bool = True
    screenshot_b64: str = ""        # base64 PNG of page at this step
    network_calls: list[str] = field(default_factory=list)


@dataclass
class ScenarioResult:
    scenario: str
    status: str = "pending"         # pass | fail | partial | skipped | qa_needed
    verdict: str = ""               # Claude's finding
    steps: list[VerificationStep] = field(default_factory=list)
    qa_question: str = ""           # what Claude asks QA when stuck
    bug_report: dict = field(default_factory=dict)  # result from bug_reporter.notify_devs_of_bug


@dataclass
class VerificationReport:
    card_name: str
    app_url: str
    scenarios: list[ScenarioResult] = field(default_factory=list)
    summary: str = ""

    @property
    def passed(self) -> int:
        return sum(1 for s in self.scenarios if s.status == "pass")

    @property
    def failed(self) -> int:
        return sum(1 for s in self.scenarios if s.status in ("fail", "partial"))

    @property
    def qa_needed(self) -> "list[ScenarioResult]":
        return [s for s in self.scenarios if s.status == "qa_needed"]

    def to_automation_context(self) -> str:
        """Convert verified flows into context string for automation writer."""
        lines = [f"=== Smart AC Verification: {self.card_name} ===", f"App: {self.app_url}", ""]
        for sv in self.scenarios:
            icon = {"pass": "✅", "fail": "❌", "partial": "⚠️"}.get(sv.status, "⏭️")
            lines.append(f"{icon} {sv.scenario}")
            for step in sv.steps:
                if step.action in ("click", "fill", "navigate") and step.target:
                    lines.append(f"   [{step.action}] '{step.target}' — {step.description}")
                if step.network_calls:
                    for nc in step.network_calls[:3]:
                        lines.append(f"   [api] {nc}")
            if sv.verdict:
                lines.append(f"   Result: {sv.verdict}")
            lines.append("")
        return "\n".join(lines)


# ── Prompts ───────────────────────────────────────────────────────────────────

_EXTRACT_PROMPT = dedent("""\
    Extract each testable scenario from the acceptance criteria below.
    Return ONLY a JSON array of concise scenario title strings. No explanation.
    Example: ["User can enable Hold at Location", "Success toast shown after Save"]

    Acceptance Criteria:
    {ac}
""")

_APP_WORKFLOW_GUIDE = dedent("""\
## FedEx Shopify App — Key Workflows

### TWO DIFFERENT PRODUCTS PAGES — DO NOT CONFUSE THEM

❶  nav_clicks: "AppProducts"  →  <app_base>/products
   PURPOSE: Edit FedEx-specific settings on an EXISTING product that is already in Shopify.
   HOW: Click a product row in the list → URL becomes <app_base>/products/<product_id>

   EXACT FIELDS on the product edit page (from live app):
   ┌─ Product Dimensions ────────────────────────────────────────────┐
   │  Length [input]  cm▼   Width [input]  cm▼   Height [input]  cm▼ │
   │  Weight [input]  lb▼                                            │
   └─────────────────────────────────────────────────────────────────┘
   ┌─ Supplementary Details ─────────────────────────────────────────┐
   │  ☐ Is Alcohol                                                   │
   │  ☐ Is Battery                                                   │
   │  ☐ Is Dry Ice Needed                                            │
   │  ☐ Is this product pre-packed?                                  │
   └─────────────────────────────────────────────────────────────────┘
   ┌─ Shipping Details ──────────────────────────────────────────────┐
   │  FedEx® Delivery Signature Options [dropdown]                   │
   │    options: "As Per The General Settings" | "No Signature" |    │
   │             "Indirect" | "Direct" | "Adult"                     │
   │  Freight Class [dropdown]  e.g. CLASS_050                       │
   │  Declared Value [input]    numeric, e.g. 10                     │
   └─────────────────────────────────────────────────────────────────┘
   ┌─ Customs Information ───────────────────────────────────────────┐
   │  Country of Manufacture [dropdown]  "Select One" default        │
   │  State of Manufacture (Use 2 digit State Code) [input]          │
   └─────────────────────────────────────────────────────────────────┘
   SAVE: "Save" button (top-right of the page) → success toast "Products Successfully Saved"
   ⚠️ There is NO "Add product" button here. You CANNOT create new products here.

❷  nav_clicks: "ShopifyProducts"  →  admin.shopify.com/store/<store>/products
   PURPOSE: Shopify's own product management — the ONLY place to ADD or create new products.
   WHAT YOU CAN DO HERE:
     - Click "Add product" button (top-right) to create a new Shopify product
     - Edit product title, price, weight, SKU, barcode, variants, HS code, tags
   ⚠️ This is NOT the FedEx app — it's the Shopify admin products page.

RULE: scenario about "dry ice / alcohol / battery / signature / dimensions on a product"
  → nav_clicks: "AppProducts"  (edit FedEx settings on existing product in the app)
RULE: scenario about "add new product / create product / product with 250 variants"
  → nav_clicks: "ShopifyProducts"  (create/edit in Shopify admin)

### All App Page URLs (direct navigation — no link clicking)
- nav_clicks: "Shipping"   → <app_base>/shopify      — All Orders grid
- nav_clicks: "PickUp"     → <app_base>/pickup       — Pickups list
- nav_clicks: "Settings"   → <app_base>/settings/0   — App Settings
- nav_clicks: "FAQ"        → <app_base>/faq
- nav_clicks: "Rates Log"  → <app_base>/rateslog     — Rate request history (no hyphen)
- nav_clicks: "Orders"     → admin.shopify.com/store/<store>/orders

### ⚠️ How to Generate a Label (CORRECT FLOW — via Shopify Orders)
Label generation does NOT happen from inside the app's Shipping page.
It happens through the Shopify admin Orders section:
1. Click "Orders" in the Shopify LEFT sidebar (not the app sidebar)
2. Click on an order ID (e.g. #1612) to open the order detail page
3. Click "More Actions" button (top-right dropdown on the order page)
4. You will see two label options:
   - "Auto-Generate Label" → automatically picks service and generates
   - "Generate Label"      → manual label generation (user picks service/package)
5. Click the desired option → the FedEx app opens inside Shopify for label creation
6. Fill in package details if prompted → click Generate/Create

### How to Cancel a Label
1. Go to Shopify Orders → click the order that has a generated label
2. Click "More Actions" → click "Cancel Label" (or open the app and cancel from there)
3. Confirm cancellation

### How to Regenerate a Label (after cancel)
1. After cancelling → order status reverts to Pending/Unfulfilled
2. Go to Shopify Orders → click the same order
3. Click "More Actions" → "Generate Label" again

### App's Own Shipping / Orders Grid (inside the app iframe)
- Click "Shipping" in the app sidebar → shows "All Orders" grid inside the iframe
- Grid columns: Order#, Label created date, Customer, Label status, Shipping Service,
  Subtotal, Shipping Cost, Packages, Products, Weight, Messages
- Tab filters: All | Pending | Label Generated
- Label statuses: "label generated" (green), "inprogress" (yellow), "failed" (red),
  "auto cancelled" (grey), "label cancelled"
- Top-right buttons on Shipping page: "Generate New Labels", "How to", "Help", "Generate Report"
  ⚠️ "Generate Report" downloads a CSV file directly (NOT a ZIP) — use action=download_file, target="Generate Report"
     The CSV contains order data: order number, label status, shipping service, tracking number, weight, etc.
     After download_file, next step context shows: filename, row_count, headers[], sample_rows[], raw_preview
- ⚠️ CLICK AN ORDER ROW to open the Order Summary page for that order (inside the app)
  → The Order Summary shows label details, Download Documents, More Actions, etc.
  → Use this to access an existing label for document verification (Strategy 2/3)
- Do NOT click "Generate New Labels" — that creates a new label across multiple orders

### Settings Navigation
- Click "Settings" in app sidebar
- Tabs: General, Packages, Additional Services, Rates, etc.
- Additional Services → Freight, Signature, Dry Ice, Hold at Location, etc.

### Label Status Values (inside app's Shipping page)
- Pending          → no label yet
- In Progress      → label being generated
- Label Generated  → label created successfully
- Failed           → label generation failed

### ⚠️ Full Verification Flow by Scenario Type

NEVER create a new order. Always use existing orders. Follow the COMPLETE flow for each scenario type:

─────────────────────────────────────────────────────────
SCENARIO GROUP A — Product-Level Special Services
(Dry Ice / Alcohol / Battery / Dangerous Goods)
─────────────────────────────────────────────────────────
order_action = create_new  (verifier creates a fresh Shopify order with a dangerous goods product BEFORE the browser opens)
nav_clicks: ["AppProducts"]  (start on the FedEx app Products page)

These require 3 steps: configure product → generate label on the fresh order → verify JSON.

STEP 1 — Enable the special service checkbox on a product (AppProducts):
  You are already on the FedEx app Products page (<app_base>/products).
  - Click the FIRST product row in the list (or search for "Test Product A")
  - The product detail page opens (fields visible: Dimensions, Supplementary Details, Shipping Details)
  - Enable ONLY the checkbox the scenario tests:
      Dry Ice   → check "Is Dry Ice Needed" → fill "Dry Ice Weight" input (in kg) → Save
      Alcohol   → check "Is Alcohol" → set "Alcohol Recipient Type" dropdown (CONSUMER or LICENSEE) → Save
      Battery   → check "Is Battery" → set "Battery Material Type" (LITHIUM_ION/LITHIUM_METAL)
                                     + "Battery Packing Type" → Save
      Dangerous → check "Is Dangerous Goods" → set option → Save
  - Click "Save" button → wait for success toast "Products Successfully Saved"
  - Note the PRODUCT ID from the URL (<app_base>/products/<product_id>) — this is the product in the fresh order

STEP 2 — Generate label on the fresh order AND verify JSON DURING generation:
  action=navigate, path="orders"  → Shopify admin Orders list
  → The fresh order just created is the MOST RECENT order at the top
  → Click on it → More Actions → "Generate Label" (use MANUAL label flow — NOT auto-generate)
    Manual flow is required to access the Rate Request Log BEFORE generating.
  → Generate Packages → Get Rates (rates appear as radio buttons)

STEP 3 — Verify request JSON via Rate Log (Strategy 4 — DURING label gen, BEFORE clicking Generate):
  ⚠️ Check JSON at THIS point — BEFORE clicking Generate Label button
  - Click ⋯ (three dots) next to "Shipping rates from account" → "View Logs"
  - Dialog opens with Request (left) and Response (right) JSON
  - Verify these fields:
      Dry Ice:   specialServiceTypes contains "DRY_ICE"
                 requestedShipment.requestedPackageLineItems[0].packageSpecialServices.dryIceWeight.value = 0.3
                 weight unit = "KG"
      Alcohol:   specialServiceTypes contains "ALCOHOL"
                 requestedShipment.shipmentSpecialServices.alcoholDetail.alcoholRecipientType = "CONSUMER" or "LICENSEE"
      Battery:   specialServiceTypes contains "BATTERY"
                 requestedShipment.shipmentSpecialServices.batteryDetails[0].materialType = "LITHIUM_ION" or "LITHIUM_METAL"
                 requestedShipment.shipmentSpecialServices.batteryDetails[0].batteryPackingType = "CONTAINED_IN_EQUIPMENT" or "PACKED_WITH_EQUIPMENT"
                 requestedShipment.shipmentSpecialServices.batteryDetails[0].regulatorySubType = "IATA_SECTION_II"
  - Take screenshot → action=verify based on JSON values
  - Close dialog with "Close" button

STEP 4 — Generate Label + verify label status:
  → selectFirstShippingService (click first radio button service)
  → "Generate Label" button → Order Summary opens
  → Verify "label generated" badge visible

STEP 5 — Verify visual text on printed label (Strategy 5):
  → Print Documents button → switch_tab → screenshot → check for:
      Dry Ice:   "ICE" text on label
      Alcohol:   "ALCOHOL" text on label
      Battery:   "ELB" text on label   ← Note: Battery shows "ELB" NOT "BATTERY"
      Adult sig: "ASR" text on label
      Direct sig:"DSR" text on label
  → action=verify → close_tab

STEP 6 — Cleanup (reset product to default after test):
  action=navigate, path="products"
  → Find the same product → uncheck the special service checkbox → Save
  This prevents the setting from affecting other TCs in the same run.

─────────────────────────────────────────────────────────
SCENARIO GROUP B — Global App Settings
(FedEx One Rate / Packaging / Freight / Additional Services toggle)
─────────────────────────────────────────────────────────
These require 2 steps: configure global settings → generate label → verify.

STEP 1 — Configure the setting:
  App sidebar → Settings → relevant tab (Additional Services / Packaging / etc.)
  Enable the setting → Save → wait for success toast

STEP 2 — Generate label on existing unfulfilled order and verify:
  Shopify admin LEFT sidebar → Orders → Unfulfilled → first order
  → More Actions → Generate Label (or Auto-Generate) → Verify JSON / label

─────────────────────────────────────────────────────────
SCENARIO GROUP C — SideDock Options
(HAL / Signature / Insurance / COD / Duties & Taxes)
─────────────────────────────────────────────────────────
No product configuration needed. Configured DURING label generation on the SideDock.

STEP 1 — Navigate to an existing unfulfilled order:
  Shopify admin LEFT sidebar → Orders → Unfulfilled → first order
  → More Actions → "Generate Label" (NOT Auto-Generate — SideDock needs manual label flow)

STEP 2 — Configure SideDock BEFORE clicking Generate Label:
  - HAL          → Click "Hold at Location" → select location → confirm
  - Signature    → Dropdown "FedEx® Delivery Signature Options" → select type
  - Insurance    → Check "Add Third Party Insurance" → fill details → close modal
  - COD          → Check "Add COD Collect" → fill amount, TIN type, contact
  - Duties       → Set Purpose of Shipment, Terms of Sale, Duties Payment Type

STEP 3 — Generate Packages → Get Rates → select service → Generate Label → Verify JSON

─────────────────────────────────────────────────────────
SCENARIO GROUP D — No Label Needed
─────────────────────────────────────────────────────────
- "Next/Previous order navigation", "order grid", "pagination"
  → App sidebar → Shipping → All Orders → click ANY order row → use Prev/Next buttons

- "Verify existing label", "download documents", "label shows ICE/ALCOHOL/ASR text"
  → App sidebar → Shipping → Label Generated tab → click first "label generated" order

- "Return label generation"
  → App sidebar → Shipping → Label Generated tab → click first "label generated" order
  → Return packages tab → Return Packages button → Refresh Rates → select service → Generate Return Label

- "Settings only" (just verify a setting exists/is saved)
  → App sidebar → Settings → relevant tab → no order needed

- "App Shipping grid", "filter by status", "label status display"
  → App sidebar → Shipping → All Orders tab — grid IS the test target

─────────────────────────────────────────────────────────
SCENARIO GROUP E — Checkout / Rates
─────────────────────────────────────────────────────────
- "FedEx rates at checkout", "duties & taxes at checkout", "customer sees rates"
  → Storefront checkout flow ONLY (see storefront checkout section below)

- STOREFRONT CHECKOUT: Only use this when the scenario explicitly tests the checkout page
  (e.g. "Duties & Taxes visible at checkout", "FedEx rates shown at checkout", "customer sees rates").
  If the scenario is about label generation, address update, or order summary — use existing orders.

### How to Go Through Storefront Checkout (ONLY for checkout-specific scenarios)
1. In Shopify admin left sidebar, hover over "Online Store"
2. Click the 👁 eye icon → storefront opens in a NEW TAB
3. Browse products → click a product → "Add to cart"
4. Click cart icon (top right) → "Check out"
5. Fill Contact: test.user@example.com
6. Payment — test card details (Shopify Bogus Gateway):
   - Card number: 1231123123456781
   - Expiration: 01/37  |  Security code: 111
   - Name on card: Test (type "Test" — first name)
7. Billing address — use based on scenario type:
   DOMESTIC (US): First: Test, Last: User, Address: 123 Main St,
     City: Los Angeles, State: CA, ZIP: 90001, Country: United States
   INTERNATIONAL (Canada): First: Test, Last: User, Address: 111 Wellington St,
     City: Ottawa, Province: ON, ZIP: K1A 0A9, Country: Canada
   INTERNATIONAL (UK): First: Test, Last: User, Address: 221B Baker Street,
     City: London, ZIP: NW1 6XE, Country: United Kingdom
8. Complete order → new order appears at top of Shopify admin → Orders

### ⚠️ How to Update a Shipping Address in Shopify (for address update scenarios)
1. Go to Shopify admin → Orders → click the order
2. Click "Edit" button (top right of order page)  OR
   Click the shipping address section → "Edit address" link
3. Modify address fields → Save
4. The updated address is now the Shopify source of truth

### ⚠️ Product Strategy — When to Create vs Use Existing
- DEFAULT: Use an existing product from Shopify admin → Products list.
  Do NOT create a new product unless the scenario explicitly tests product creation.
- CREATE NEW: Only if the scenario says "create a product", "add a new product",
  or tests specific product attributes that no existing product has.
- For FedEx app product mapping (dimensions, signature, dry ice etc.) —
  always search for an existing product in the app's Products page.
  Use "Test Product A" or "Test Product B" as default test products.

### ⚠️ How to Create a New Product in Shopify Admin
1. In the Shopify admin LEFT sidebar click "Products"
2. Click "Add product" button (top right of the products list page)
3. Fill in the product form:
   - Title: type in the product name field (input[name="title"])
   - Price: fill the price field (input[name="price"])
   - Weight: fill the weight field (#ShippingCardWeight), select unit (kg/lb/g/oz)
   - SKU / Barcode: click the "SKU" button to expand → fill SKU and barcode fields
   - Country of origin / HS Code: click "Country of origin" button → select country → fill HS code
   - Tags: type in the tags input field → press Enter to add each tag
4. Click "Save" button (top right)
5. After saving the URL changes to /products/{id} — this is the product detail page

### ⚠️ How to Edit an Existing Product in Shopify Admin
1. In the Shopify admin LEFT sidebar click "Products"
2. Find the product → click its title link to open the product detail page
   OR use the search/filter button ("Search and filter products") to find it
3. Edit any field:
   - Title: input[name="title"]
   - Price: input[name="price"]
   - Weight: #ShippingCardWeight
   - Weight unit: select[name="weightUnit"]
   - SKU: click "SKU" button → input[name="sku"]
   - Barcode: input[name="barcode"]
   - Tags: input[name="tags"] → press Enter
   - HS Code: input[name="harmonizedSystemCode"]
   - Country of origin: button "Country of origin" → select[name="countryCodeOfOrigin"]
4. Click "Save" button to save changes  |  "Discard" to cancel

### ⚠️ How to Configure FedEx Product Settings (App's Products Page)
This is DIFFERENT from Shopify Products. This is inside the FedEx app.
1. Click "Products" in the FedEx app sidebar (inside the app iframe)
2. Click the search/filter button ("Search and filter results") — inside the iframe
3. Type the product name in the search field → press Enter
4. Click the product button/row that appears in search results
5. On the product detail page configure ONLY what the scenario requires:

   NORMAL product scenario (no special services mentioned):
   - Set Dimensions: Length, Width, Height + unit (cm/in/ft/mt)
   - Set Signature Option if needed: select[name="signatureOptionType"]
   - Do NOT touch Alcohol / Battery / Dry Ice / Dangerous Goods checkboxes
   - Click "Save" → expect toast "Products Successfully Saved"

   ONLY enable special service checkboxes when the scenario EXPLICITLY tests them:
   - "Is Alcohol" → enable only if scenario is about alcohol shipping
       → then set Alcohol Recipient Type: CONSUMER or LICENSEE
   - "Is Battery" → enable only if scenario is about battery shipments
       → then set Battery Material Type (LITHIUM_ION/LITHIUM_METAL) + Battery Packing Type
   - "Is Dry Ice Needed" → enable only if scenario is about dry ice
       → then fill Dry Ice Weight(kg) input
   - "Is Dangerous Goods" → enable only if scenario is about dangerous goods/hazmat
       → then set option (LIMITED_QUANTITIES_COMMODITIES / HAZARDOUS_MATERIALS / ORM_D)
   - "Is this product pre-packed?" → enable only if scenario tests pre-packed behaviour
   - Freight Class / Declared Value / Customs info → only if scenario mentions these

6. Click "Save" button (inside iframe) → success toast "Products Successfully Saved"
7. To go back to the product list: click the back navigation button (aria-label="products")

### ⚠️ Manual Label Generation — Full Flow
Manual label = user picks the FedEx service themselves.
1. Go to Shopify Orders → click an order → More Actions → "Generate Label"
   (the FedEx app opens in a new embedded page inside Shopify)
2. Inside the app (iframe), the page has TWO areas:
   LEFT SIDE — Package & Rates area:
   a. Click "Generate Packages" button → packages are auto-calculated
   b. Click "Get shipping rates" button → FedEx rates load as radio buttons
      (has retry logic — if rates fail, a "Retry" button appears; click it)
   c. Select a shipping service (click its radio button)
   RIGHT SIDE — The SideDock (ALWAYS visible, configure before generating label):
   d. Configure SideDock options as needed (see SideDock section below)
   e. Click "Generate Label" button → label is created
3. After generation the Order Summary page opens automatically

### ⚠️ Auto Label Generation — Full Flow
Auto label = FedEx app picks service and generates without user input.
1. Go to Shopify Orders → click an order → More Actions → "Auto-Generate Label"
2. Label generates automatically (no service selection needed)
3. Verify: navigate to Shipping → order shows "label generated" status
   OR the Order Summary page opens automatically

### ⚠️ The SideDock — Manual Label Options Panel (ALWAYS VISIBLE)
The SideDock is a panel on the RIGHT SIDE of the Manual Label page.
It is ALWAYS visible — no need to open or toggle it.
Settings configured here OVERRIDE any product-level or global settings.

SideDock contains (in order from top to bottom):
1. ADDRESS CLASSIFICATION
   - Dropdown: "Shipping Address Classification" (aria-label="Address classification")
   - Options: Residential, Commercial

2. SIGNATURE OPTIONS (overrides product-level signature)
   - Dropdown: aria-label="FedEx® Delivery Signature Options"
   - Options: ADULT, DIRECT, INDIRECT, NO_SIGNATURE_REQUIRED, SERVICE_DEFAULT
   - ⚠️ This overrides the product signature setting for this label only

3. HOLD AT LOCATION (HAL)
   - Button: "Hold at Location" (or "Choose Hold At Location Point")
   - Click → modal opens with location search/dropdown
   - Select HAL location code (e.g. 'HHRAA', 'FEDEX_OFFICE', 'WALGREENS')
   - Click "Yes" to confirm selection
   - Verifiable in JSON: specialServiceTypes contains "HOLD_AT_LOCATION",
     holdAtLocationDetail.locationId = selected location code
     holdAtLocationDetail.locationType = location type string

4. INSURANCE / THIRD-PARTY INSURANCE
   - Checkbox: "Add Third Party Insurance To Packages?"
   - After checking → click the Edit (pencil) icon that appears
   - Modal opens with:
     - Checkbox: "Include Third Party Insurance In Commercial Invoice?"
     - Dropdown: Liability Type (New / Used or Reconditioned)
     - Dropdown: Insurance Amount Type (Declared Value / Percentage of Product Price)
     - If Percentage selected → input: "Percentage of Product Price" (0–100)
   - Click Close button to save modal
   - Verifiable in JSON: declaredValue.amount in rate request

5. COD (CASH ON DELIVERY)
   - Checkbox: "Add COD Collect" (field: isCodRequired)
   - After checking → additional fields appear:
     - COD Amount input
     - COD TIN Type dropdown (BUSINESS_NATIONAL, BUSINESS_STATE, BUSINESS_UNION,
       PERSONAL_NATIONAL, PERSONAL_STATE)
     - TIN Number input
     - Contact: name, company name, phone number
     - Address fields: street, city, state/country, pincode
     - COD Reference Indicator

6. DUTIES & TAXES / INTERNATIONAL SETTINGS (for international shipments)
   - Purpose of Shipment dropdown: GIFT / SAMPLE / RETURN / REPAIR / OTHERS
   - Terms of Sale dropdown: CFR / CIF / CIP / EXW / FOB / FAS / DAF
   - Duties Payment Type dropdown: SENDER / RECIPIENT / THIRD_PARTY
     → If THIRD_PARTY: enter third-party account number
   - Additional Commercial Invoice Info checkbox: "Add Additional Commercial Invoice Info"
     → Fields: customs value, insurance value, customs comments, freight charge, reference

7. FREIGHT ADDITIONAL INFO (for freight scenarios)
   - Checkbox: "Add Additional Freight Info"
   - Fields: Collect Terms Type, Freight ID, Freight Packaging,
     Purchase Order Number, Delivery Instructions, Disposition Type
   - Freight contact details section

### ⚠️ How to Generate a Return Label
TWO WAYS to generate a return label:

WAY A — From Inside the App (after forward label is generated):
1. Open Order Summary page in the app (Shipping → click order with "label generated")
2. Click the "Return packages" tab (next to "Packages" tab)
3. Click "Return Packages" button → Return Label page opens
4. Enter return quantity (default 1)
5. Click "Refresh Rates" button → rates load (with retry logic, may take a moment)
6. Select a shipping service radio button
7. Click "Generate Return Label" button
8. Verify: "SUCCESS" badge appears + "Download Label" link becomes visible

WAY B — From Shopify Admin (directly from order page):
1. Go to Shopify admin → Orders → click the order
2. Click "More actions" dropdown (top-right of order page)
3. Click "Generate Return Label" (NOT "Create return label" — that is a different Shopify feature)
   Other options visible: Auto-Generate Label, Generate Label, Print Label, Create return label
4. The FedEx app opens for return label generation
5. Same steps as Way A from step 4 onwards

### ⚠️ How to View Rate Request / Label Request Logs
These logs show the EXACT JSON sent to FedEx REST API.
The app uses ONLY the FedEx REST API (no SOAP/XML — all logs are JSON).

RATE REQUEST LOG (from Manual Label page, after clicking Get Shipping Rates):
1. Complete manual label steps: Generate Packages → Get Shipping Rates (rates appear as radio buttons)
2. In the rates section, click the "⋯" (three dots / action menu) button
   next to "Shipping rates from account"
3. Click "View Logs" from the dropdown menu → dialog opens in the page (no download)
4. Dialog shows TWO sections (JSON format):
   - Left / "Request" section: JSON sent to FedEx (requestObject)
   - Right / "Response" section: JSON received from FedEx
5. Take a screenshot → read JSON values visually to verify fields:
   - requestedShipment.requestedPackageLineItems[0].dimensions → L/W/H/units
   - requestedShipment.requestedPackageLineItems[0].weight.value
   - requestedShipment.shipmentSpecialServices.specialServiceTypes → array
   - requestedShipment.requestedPackageLineItems[0].packageSpecialServices.signatureOptionType
   - requestedShipment.shipmentSpecialServices.holdAtLocationDetail → HAL info
6. Close dialog with "Close" button (aria-label="Close") or ✕

OTHER ACTIONS in the ⋯ menu:
- "View Address Logs" → shows address validation details
- "Download Logs" → downloads ZIP with rate request/response JSON (same format as Download Documents)

LABEL REQUEST LOG (after label is generated — via ZIP download):
→ See Strategy 2 or 3 in the Document Verification section below

### ⚠️ How to View Rate Log from App's "Rates Log" Sidebar
⚠️ CRITICAL — Rates Log ONLY shows requests from STOREFRONT CHECKOUT:
- Rates Log at <app_base>/rateslog ONLY populates when a customer places an order through the
  Shopify online store (storefront checkout) — the FedEx rates are fetched at checkout.
- API-created orders (used in most test cases) do NOT appear in Rates Log — it will be EMPTY.
- For API-created test orders: generate a label first, then use Download Documents ZIP
  (or "How To" → "Click Here" ZIP) to get both the createShipment request and label JSON.

WHEN TO USE Rates Log page:
- ONLY for scenarios that explicitly test "rates shown at checkout", "customer sees FedEx rates",
  or "duties & taxes at storefront checkout". These require a real storefront checkout flow.
- For all other "verify rate request JSON" scenarios → use Download Documents ZIP (Strategy 2)
  or How To → Click Here ZIP (Strategy 3) instead.

HOW TO USE (if scenario requires storefront checkout rates):
1. Click "Rates Log" in the app sidebar (inside the app iframe)
2. List of all rate requests: each row has order ID, date, status
3. Click a row → expands to show request/response JSON for that rate call

### ⚠️ How to Access the Order Summary Page (to view label details, download docs)
The Order Summary page (with label status, Download Documents, More Actions) is accessed in TWO ways:

WAY 1 — From the app's own Shipping / Orders grid (PREFERRED for verifying existing labels):
1. Click "Shipping" in the app sidebar → the "All Orders" grid loads inside the iframe
2. The grid shows orders with columns: Order#, Label status, Shipping Service, Packages, Products, Weight
3. Label statuses visible: "label generated" (green), "inprogress" (yellow), "failed" (red), "auto cancelled"
4. Click on any order ROW (e.g. #1559 with "label generated") → Order Summary page opens inside the app
5. The Order Summary now shows the full order details with action buttons

WAY 2 — After generating a label (app redirects here automatically):
- After completing manual or auto label generation, the app redirects to Order Summary directly
- No need to navigate back to the grid

### ⚠️ How to Verify Label and Documents — 4 Strategies

Order Summary Page buttons and elements:
- "← #XXXX" back arrow + order number at top left → back to Shipping grid
- Label status badge next to order number: "label generated" / "Pending" / "Failed"
- "Print Documents" button (standalone) → opens a NEW BROWSER TAB with the PluginHive document viewer
  The tab shows all documents: label, packing slip, commercial invoice (CI)
  ⚠️ Use: action=switch_tab → screenshot → read documents visually → action=close_tab
- "Upload Documents" button → upload custom customs docs
- "More Actions" dropdown → contains these exact items (in order):
  - "Track Order"         → opens FedEx tracking page for this shipment
  - "Download Documents"  → downloads a ZIP with physical shipping documents
                            (label PDF + packing slip PDF + CI PDF)
                            ⚠️ Does NOT contain request/response JSON
  - "Cancel Label"        → cancel the label
  - "Return Label"        → opens return label flow
  - "How To"              → opens a modal with usage instructions
                            ⚠️ THIS IS THE ONLY WAY to get request/response JSON:
                            scroll to bottom → "Need request/response Logs to contact FedEx? Click Here"
                            → downloads RequestResponse_#ORDERNAME.zip
                              (contains createShipment request JSON + response JSON)
  - "Help"                → opens help/support link

⚠️ CRITICAL DISTINCTION:
  - Print Documents      → opens NEW TAB viewer (visual only — no download)
  - Download Documents   → ZIP download with physical docs (label + slip + CI) — NO JSON
  - How To → Click Here → request/response JSON ONLY — the ONLY source for JSON field verification
- TWO TABS: "Packages" tab | "Return packages" tab
  - Packages tab: shows package info (box type badge, service badge, products, weight, price)
  - Return packages tab: shows return label if generated
- Customer panel (right side): name, email, phone
- Address panel (right side): street, city/state/zip, country
- Previous / Next buttons (top right) → navigate between orders

⚠️ PRINT DOCUMENTS FLOW (opens NEW BROWSER TAB — visual viewer, NOT a download):
1. On Order Summary, click "Print Documents" button (standalone button)
   → A NEW BROWSER TAB opens with the PluginHive document viewer
   → Tab shows: label, packing slip, commercial invoice (CI)
2. action=switch_tab   ← switch to the new tab
3. action=screenshot   ← capture visually (read label text, check docs present)
4. action=close_tab    ← return to Order Summary
⚠️ Do NOT use download_zip for Print Documents — it opens a tab, not a file download.

⚠️ DOWNLOAD DOCUMENTS FLOW (More Actions → ZIP with physical documents):
1. action=click, target="More Actions" → dropdown opens
2. action=download_zip, target="Download Documents"
   → ZIP downloaded and extracted automatically
   → Contents: label PDF + packing slip PDF + commercial invoice (CI) PDF
3. action=verify: confirm expected documents are present

⚠️ IMPORTANT:
  - Print Documents → NEW TAB viewer (visual) — NOT a ZIP download
  - Download Documents → ZIP with physical docs (label + slip + CI) — NO JSON
To get request/response JSON → ONLY via: More Actions → How To → Click Here (see Strategy 3)

STRATEGY 1 — Verify label EXISTS (for "label is generated" scenarios):
1. Navigate to Shipping → click order with "label generated" status → Order Summary opens
   OR after manual/auto label generation the page redirects to Order Summary automatically
2. Look for "label generated" status badge next to order number
3. Look for "Print Documents" and "More Actions" buttons visible
4. Take a screenshot — if "label generated" is visible, verdict = PASS

STRATEGY 2 — Verify physical documents exist (label + packing slip + CI):
Use for: "documents are generated", "label PDF exists", "packing slip present", "CI present"
STEPS:
1. action=click, target="More Actions" → action=download_zip, target="Download Documents"
   → ZIP extracted automatically — file list appears in your NEXT step context
2. Verify the expected files are present:
   - label PDF     → confirms label was generated
   - packing slip  → confirms slip is included
   - CI (commercial invoice) → confirms customs doc present (international shipments)
3. action=verify with finding based on files present → verdict = PASS/FAIL

STRATEGY 3 — Download request/response JSON via "How To" modal (THE ONLY WAY to get JSON):
⚠️ This is the ONLY way to get the createShipment request/response JSON after label generation.
Use for: signature type, special services, HAL, declared value, dimensions, dry ice, alcohol, battery, COD.
STEPS:
1. action=click, target="More Actions" → dropdown opens
2. action=click, target="How To" → modal opens
3. Scroll to bottom: find "Need request/response Logs to contact FedEx? Click Here"
4. action=download_zip, target="Click Here"
   → downloads RequestResponse_#ORDERNAME.zip
   → ZIP extracted automatically — JSON content appears in your NEXT step context
5. Read JSON fields:
   - Signature:        requestedShipment.requestedPackageLineItems[0].packageSpecialServices.signatureOptionType
   - Special services: requestedShipment.shipmentSpecialServices.specialServiceTypes (array)
     Values: "HOLD_AT_LOCATION", "DRY_ICE", "ALCOHOL", "BATTERY", "FEDEX_ONE_RATE"
   - HAL:              requestedShipment.shipmentSpecialServices.holdAtLocationDetail.locationId
   - Declared value:   requestedShipment.requestedPackageLineItems[0].declaredValue.amount
   - Dimensions:       requestedShipment.requestedPackageLineItems[0].dimensions
   - Weight:           requestedShipment.requestedPackageLineItems[0].weight.value
   - Dry ice weight:   requestedShipment.requestedPackageLineItems[0].packageSpecialServices.dryIceWeight.value
   - Alcohol type:     requestedShipment.shipmentSpecialServices.alcoholDetail.alcoholRecipientType
6. action=verify with finding based on JSON values → verdict = PASS/FAIL
⚠️ "Click Here" is at the BOTTOM of the How To modal — scroll down if not visible.

STRATEGY 4 — In-page Rate Log (ONLY during Manual Label generation, BEFORE label is created):
Available ONLY on the Manual Label page after "Get Shipping Rates" is clicked.
1. Click ⋯ (three dots) next to "Shipping rates from account" → click "View Logs"
2. Dialog opens in-page (NO download) with JSON Request (left) and Response (right)
3. Screenshot → read JSON values visually → action=verify
4. Close dialog with "Close" button

STRATEGY 5 — Visual Label Check (for label content visible on printed label):
Use for: special service text codes printed ON the label itself
1. Click "Print Documents" → new tab opens with PluginHive viewer
2. action=switch_tab
3. Screenshot → read label visually for these codes:
   - Dry Ice    → "ICE" text on label
   - Alcohol    → "ALCOHOL" text on label
   - Battery    → "ELB" text on label  ← NOT "BATTERY"
   - Adult sig  → "ASR" text on label
   - Direct sig → "DSR" text on label
   - Indirect   → "ISR" text on label
   - Svc Default→ "SS AVXA" on label
4. action=verify based on what text/codes appear on label
5. action=close_tab

WHICH STRATEGY TO USE:
- "label is generated" / "label status"                      → Strategy 1
- Documents present (label PDF, packing slip, CI)            → Strategy 2 (More Actions → Download Documents ZIP)
- Request/response JSON fields (signature, dry ice, HAL etc) → Strategy 3 (How To → Click Here)
- Rate request DURING manual label (before generating)       → Strategy 4
- Visual label text codes (ICE, ALCOHOL, ELB, ASR, DSR)      → Strategy 5 (Print Documents → new tab → screenshot)

⚠️ For JSON field verification: ONLY Strategy 3 works (How To → Click Here).
   Strategy 2 (Download Documents ZIP) has physical docs ONLY — no JSON inside.
⚠️ Print Documents is NOT a download — it opens a NEW TAB viewer. Use switch_tab + screenshot + close_tab.
⚠️ For download_zip (Strategy 2): More Actions → action=download_zip, target="Download Documents".
⚠️ For download_zip (Strategy 3): click "More Actions" → click "How To" → scroll to bottom → download_zip target="Click Here".

### ⚠️ FedEx One Rate — Settings Flow
FedEx One Rate = flat-rate pricing using specific FedEx boxes.
1. Settings → Packaging section:
   - Set Packing Method to "Box Packing"
   - Click "more settings" button
   - In the box list, keep ONLY the relevant FedEx box (e.g. "FedEx® Small Box")
     (delete or uncheck all other boxes)
   - Save packaging settings
2. Settings → Additional Services section:
   - Find "FedEx One Rate®" heading
   - Check "Enable FedEx One Rate®" checkbox
   - Click Save button
   - Success toast: "Fedex One Rate® updated"
3. Generate label → verify JSON contains: specialServiceTypes array includes "FEDEX_ONE_RATE"

### ⚠️ Packaging Settings — Detailed Flow
Located in: Settings → Packaging tab
Key settings:
- Packing Method dropdown: "Weight Based" or "Box Packing"
- Weight And Dimensions Unit: lb/kg, in/cm
- "more settings" button → expands additional options:
  - Checkbox: "Use Volumetric Weight For Package Generation"
  - Checkbox: "Use Longest Side Of The Product As Package Dimensions"
  - FedEx box list with restore/remove options
  - Button: "Restore FedEx Boxes" → brings back all standard FedEx boxes
  - Button: "Add Custom Box" → modal to add custom box (Name, Length, Width, Height)
- For freight: separate "FedEx® Freight Services" section with freight-specific dimensions
- Save button → saves all packaging settings

### ⚠️ Pickup Scheduling — Full Flow
1. Navigate to Shipping (app sidebar) → All Orders grid
2. Select an order using the checkbox (left column of the grid)
3. Click "More actions" button (top of the grid, NOT the order-level More Actions)
4. Click "Request Pick Up" from the dropdown
5. Confirmation popup appears → click "Yes" button
6. Navigate to "PickUp" in the app sidebar → Pickups list loads
7. Verify the new pickup row shows:
   - Pickup number (generated ID)
   - Status: "SUCCESS"
   - Requested time (formatted as "MMM D, h:mm AM/PM", e.g. "Apr 9, 3:07 PM")
   - Orders column: contains the order ID that was selected
8. Pagination: "Page N of M" pattern — use Previous/Next buttons to navigate if needed

### ⚠️ Bulk Auto-Label Generation (multiple orders at once)
From automation: bulkAutoLabelGeneration.spec.ts
1. nav_clicks: ["Orders"] → Shopify admin Orders list
2. Click the header checkbox label (NOT the <input> — it has opacity:0) to select all orders
3. Bulk actions bar appears at top → click "Actions" button (aria-label="Actions", inside StickyBulkActions)
4. Click "Auto-Generate Labels" — it is a <a> LINK not a button: getByRole('link', {name: 'Auto-Generate Labels'})
5. Wait for URL to change away from /orders (do NOT use networkidle — Shopify has constant background XHR)
6. Verify labels generated in app Shipping → Label Generated tab

### ⚠️ Weight-Based Packing — Full Settings Flow
From automation: weightBasedPackaging.spec.ts, weightVolMPSP.spec.ts, weightMPMP.spec.ts
1. Settings → Packaging tab
2. action=select target="Packing Method" value="Weight Based"  (dropdown)
3. action=select target="Weight And Dimensions Unit" value="lb" (or "kg", "in", "cm")
4. Click "more settings" to expand advanced options
5. Optional: action=click target="Use Volumetric Weight For Package Generation" (checkbox)
6. Optional: action=click target="Use Longest Side Of The Product As Package Dimensions" (checkbox)
7. Click Save → verify success toast
8. Generate label → verify package weight/dimensions in downloaded JSON

### ⚠️ Box-Based Packing — Full Settings Flow
From automation: boxBasedVolCarrierBox.spec.ts, boxPackaging.spec.ts
1. Settings → Packaging tab
2. action=select target="Packing Method" value="Box Packing"
3. Click "more settings" → FedEx box list appears
4. To use only specific box: remove all others using their delete/remove button, keep only target box
5. Click "Restore FedEx Boxes" to bring back all standard boxes if needed
6. Click "Add Custom Box" → modal: fill Name, Length, Width, Height → Save
7. Click Save → verify success toast
8. Generate label → JSON should show box dimensions in requestedPackageLineItems[0].dimensions

### ⚠️ Product Configuration in FedEx App (AppProducts page)
From automation: products.spec.ts, addProductToConfig.spec.ts
URL: /apps/testing-553/products (navigate via AppProducts)
1. Search product: click search/filter button → placeholder "Search by Product Name (Esc to cancel)" → fill product name
2. Click the product button/row to open product detail
3. Configure package assignment, dimensions, special service flags
4. For dangerous goods: action=select target="Dangerous Goods Type" value="Dry Ice" (or Battery, Alcohol)
5. For alcohol: action=select target="Alcohol Recipient Type" value="Licensee" (or Consumer)
6. For battery: action=select target="Battery Material Type" value="Lithium Ion" (or Metal)
7. Click Save → verify success toast

### ⚠️ Products with More Than 250 Variants (Shopify admin)
From automation: shopifyProducts.spec.ts
nav_clicks: ["ShopifyProducts"] → Shopify admin Products list
1. Search for the product by name → click it to open
2. Scroll to Variants section
3. Verify variant count display or add/edit variants
4. For HS code / country of origin: scroll to Shipping section on product page
   - Fill "Harmonized System (HS) code" input
   - Select "Country/Region of origin" dropdown
5. Click Save → verify success

### ⚠️ Order Summary — Next/Previous Navigation
From automation: nextPreviousOrderNavigationFromOrderSummary.spec.ts
After a label is generated and you are on Order Summary page:
- "Previous order" button → navigates to previous order in list
- "Next order" button → navigates to next order in list
- Verify order ID changes in the URL and page heading
""")

# ── Selective workflow guide trimmer ─────────────────────────────────────────
# Splits the guide on ### headers and returns only sections relevant to the
# scenario — cuts ~40-60% of tokens per step call for focused scenarios.

# Sections always included regardless of scenario type
_WG_ALWAYS = [
    "All App Page URLs",
    "TWO DIFFERENT PRODUCTS",
    "How to Generate a Label",
    "How to Cancel a Label",
    "How to Regenerate a Label",
    "App's Own Shipping",
    "Settings Navigation",
    "Label Status Values",
    "Full Verification Flow by Scenario Type",
    "How to Access the Order Summary Page",
    "How to Verify Label and Documents",
]

# (keywords_in_scenario, header_substring_to_include)
_WG_CONDITIONAL: list[tuple[list[str], str]] = [
    (["checkout", "storefront", "customer sees rates", "rates at checkout"],
     "How to Go Through Storefront Checkout"),
    (["address update", "update address", "address change", "updated address",
      "after cancell", "new address", "regenerate", "re-generate",
      "shipping address"],
     "How to Update a Shipping Address"),
    (["create product", "add product", "new product", "add new product"],
     "How to Create a New Product"),
    (["edit product", "update product", "product weight", "product variant",
      "hs code", "harmonized", "country of origin", "modify product"],
     "How to Edit an Existing Product"),
    (["product strategy", "existing product", "use existing", "product"],
     "Product Strategy"),
    (["app product", "fedex product", "product config", "appproducts",
      "dry ice", "alcohol", "battery", "dangerous goods", "is dry ice",
      "is alcohol", "is battery", "hazmat", "pre-packed", "freight class",
      "declared value", "country of manufacture"],
     "How to Configure FedEx Product Settings"),
    (["dry ice", "alcohol", "battery", "dangerous goods", "hazmat"],
     "SCENARIO GROUP A"),
    (["manual label", "generate label", "create label", "label generation",
      "signature", "hal ", "hold at location", "cod ", "cash on delivery",
      "insurance", "duties", "freight", "automatically generate",
      "residential", "commercial", "address classification"],
     "Manual Label Generation"),
    (["auto-generate", "auto generate", "auto label", "automatically generate",
      "auto-generated", "without user"],
     "Auto Label Generation"),
    (["signature", "hal ", "hold at location", "cod ", "cash on delivery",
      "insurance", "duties", "freight additional", "residential", "commercial",
      "address classification", "sidedock", "side dock"],
     "The SideDock"),
    (["return label", "generate return", "return package", "return shipment"],
     "How to Generate a Return Label"),
    (["rate log", "rate request", "view logs", "rates log", "api log",
      "api call", "network request", "json request", "fedex api"],
     "How to View Rate"),
    (["one rate", "fedex one rate", "flat rate", "flat-rate", "fedex box rate"],
     "FedEx One Rate"),
    (["packaging", "box packing", "weight based", "packing method",
      "package setting", "box setting", "fedex box"],
     "Packaging Settings"),
    (["pickup", "pick up", "schedule pickup", "request pickup",
      "pickup scheduling", "pickup request"],
     "Pickup Scheduling"),
    (["bulk", "50 orders", "select all orders", "auto-generate labels",
      "batch label", "multiple orders", "bulk label"],
     "Bulk Auto-Label"),
    (["weight based", "volumetric weight", "weight packing", "weight-based",
      "dimensional weight", "weight setting"],
     "Weight-Based Packing"),
    (["box packing", "box based", "fedex box", "custom box", "box-based",
      "box dimension"],
     "Box-Based Packing"),
    (["250 variant", "more than 250", "more than 100 variant", "high variant",
      "variant pagination", "product variant", ">250", "large variant"],
     "Products with More Than 250 Variants"),
    (["next order", "previous order", "next/previous", "order navigation",
      "navigate between orders", "prev order"],
     "Order Summary — Next/Previous"),
]


def _trim_workflow_guide(scenario: str) -> str:
    """Return only workflow guide sections relevant to this scenario."""
    s = scenario.lower()

    # Split on ### headers (keep header with its body)
    raw_sections = re.split(r"\n(?=###)", _APP_WORKFLOW_GUIDE)

    kept: list[str] = []
    for sec in raw_sections:
        sec_lower = sec.lower()

        # Always-include sections
        if any(ah.lower() in sec_lower for ah in _WG_ALWAYS):
            kept.append(sec)
            continue

        # Conditional sections
        for keywords, header_match in _WG_CONDITIONAL:
            if header_match.lower() in sec_lower:
                if any(kw in s for kw in keywords):
                    kept.append(sec)
                break  # each section matched at most once

    result = "\n".join(kept) if kept else _APP_WORKFLOW_GUIDE

    # Safety net: if result is less than 35% of full guide something went wrong — use full
    if len(result) < len(_APP_WORKFLOW_GUIDE) * 0.35:
        logger.warning("[guide] Trim too aggressive (%.0f%%) — falling back to full guide for '%s…'",
                       100 * len(result) / len(_APP_WORKFLOW_GUIDE), scenario[:50])
        return _APP_WORKFLOW_GUIDE

    saved = len(_APP_WORKFLOW_GUIDE) // 4 - len(result) // 4
    logger.debug("[guide] Trimmed workflow guide: saved ~%d tokens (%.0f%%) for scenario '%s…'",
                 saved, 100 * saved / (len(_APP_WORKFLOW_GUIDE) // 4), scenario[:50])
    return result


_DOMAIN_EXPERT_PROMPT = dedent("""\
    You are the domain expert for the PluginHive FedEx Shopify app.
    A QA engineer is about to verify this scenario in the live app.

    SCENARIO: {scenario}
    FEATURE:  {card_name}

    {preconditions_section}

    Using the domain knowledge and code context below, answer these questions
    concisely (max 200 words total):

    1. EXPECTED BEHAVIOUR — What should happen in the UI when this works correctly?
    2. API SIGNALS — What FedEx/backend API calls or request fields should appear
       (e.g. "signatureOptionType in rate request", "GET /rates with specialServices")?
    3. KEY THINGS TO CHECK — Specific UI elements, values, or network calls that
       confirm this scenario is implemented and working.

    Be specific. If the scenario mentions "Signature Type = Service Default", explain
    exactly what that option means and what changes in the request or UI.

    DOMAIN KNOWLEDGE (PluginHive docs / FedEx API):
    {domain_context}

    CODE KNOWLEDGE (automation POM / backend):
    {code_context}

    Answer in plain text — no JSON, no headings, just 3 short paragraphs.
""")

_PLAN_PROMPT = dedent("""\
    You are a QA engineer verifying a feature in the FedEx Shopify App.

    SCENARIO: {scenario}
    APP URL:  {app_url}

{app_workflow_guide}

    DOMAIN EXPERT INSIGHT (what this feature should do + what API signals to watch):
    {expert_insight}

    CODE KNOWLEDGE (automation POM patterns + backend API):
    {code_context}

    IMPORTANT: We test WEB (desktop browser) ONLY. SKIP any scenario that involves mobile
    viewports, responsive breakpoints, isMobileView, or screen widths ≤ 768 px. If the
    scenario is mobile-only, set plan = "SKIP — mobile/responsive testing is out of scope"
    and order_action = "none".

    Plan how to verify this. The browser will ALWAYS start at the app home page.

    Navigation rules:
    - For label generation scenarios (generate new label) → nav_clicks: ["Orders"]  (Shopify left sidebar)
    - For verifying an EXISTING label / downloading documents → nav_clicks: ["Shipping"]
      (app sidebar → "All Orders" grid → click an order row with "label generated" status → Order Summary)
    - For app settings scenarios    → nav_clicks: ["Settings"]  (app sidebar)
    - For DRY ICE / ALCOHOL / BATTERY / DANGEROUS GOODS scenarios:
      → nav_clicks: ["AppProducts"]  AND  order_action: "create_new"
      FLOW: AppProducts (enable checkbox on product → Save) → navigate action to "orders"
            → find fresh order → generate label → Download Documents ZIP → verify JSON
      ⚠️ Must enable the checkbox FIRST before generating the label, or the special service won't appear in the request
    - For setting other FedEx options on a product (dimensions, freight class, declared value, signature)
      → nav_clicks: ["AppProducts"]  (FedEx app Products page — edits FedEx-specific fields on existing products)
      ⚠️ Cannot add/create new products here — only configure FedEx settings for existing ones
    - For adding a new product OR editing Shopify product fields (title, price, weight, SKU, variants, HS code)
      → nav_clicks: ["ShopifyProducts"]  (Shopify admin Products — the ONLY place to create/add products)
    - ONLY use these exact values in nav_clicks: "Orders", "Shipping", "Settings", "PickUp", "AppProducts", "ShopifyProducts", "FAQ", "Rates Log"
    - Each value navigates directly to its URL — no link-clicking, instant navigation
    - Do NOT put action steps, button names, or multi-step descriptions in nav_clicks
    - All interactions after navigation (clicking order rows, More Actions, download_zip, search, fill, save etc.) happen in the agentic loop

    ORDER JUDGMENT — pick order_action by matching your scenario to the table below.
    Read the scenario carefully and pick the FIRST row that matches.

    | Scenario contains ANY of these phrases                                        | order_action                    |
    |-------------------------------------------------------------------------------|---------------------------------|
    | "cancel label", "cancel the label", "after cancellation", "address update",   |                                 |
    | "update address", "update the address", "update shipping address",            | existing_fulfilled              |
    | "updated address", "regenerate", "re-generate label",                         | existing_fulfilled              |
    | "return label", "generate return label", "download document", "verify label", |                                 |
    | "print document", "label shows", "next/previous order", "order summary nav"   |                                 |
    |-------------------------------------------------------------------------------|---------------------------------|
    | "generate label", "create label", "auto-generate label", "manual label",      |                                 |
    | "dry ice", "alcohol", "battery", "signature required", "adult signature",      | create_new                      |
    | "hold at location", "HAL", "COD", "cash on delivery", "insurance",            |                                 |
    | "declared value", "one rate", "fedex one rate", "domestic label",             |                                 |
    | "international label", "cross-border label"                                   |                                 |
    |-------------------------------------------------------------------------------|---------------------------------|
    | "bulk", "50 orders", "100 orders", "batch label", "select all orders",        | create_bulk                     |
    | "auto-generate labels", "bulk print", "bulk packing slip"                     |                                 |
    |-------------------------------------------------------------------------------|---------------------------------|
    | "250 variants", "more than 250 variants", "high variant", "variant pagination"| create_product_250_variants     |
    |-------------------------------------------------------------------------------|---------------------------------|
    | "settings", "configure", "pickup", "schedule pickup", "rates log",            | none                            |
    | "navigation", "order grid", "filter orders", "tab shows", "sidebar"           |                                 |

    When in doubt between create_new and existing_fulfilled → prefer create_new.
    When in doubt between existing_fulfilled and existing_unfulfilled → prefer existing_fulfilled.

    Respond ONLY in JSON:
    {{
      "app_path": "",
      "look_for": ["UI element or behaviour that proves this scenario is implemented"],
      "api_to_watch": ["API endpoint path fragment to watch in network calls"],
      "nav_clicks": ["e.g. Orders | Shipping | Settings | AppProducts | ShopifyProducts | PickUp | FAQ | Rates Log"],
      "plan": "one sentence: how you will verify this scenario",
      "order_action": "none" | "existing_fulfilled" | "existing_unfulfilled" | "create_new" | "create_bulk" | "create_product_250_variants"
    }}
""")

_STEP_PROMPT = dedent("""\
    You are verifying this AC scenario in the FedEx Shopify App.

    SCENARIO: {scenario}

    DOMAIN EXPERT INSIGHT (what this feature does + what to look for):
    {expert_insight}

    APP WORKFLOW GUIDE:
{app_workflow_guide}

    CURRENT PAGE: {url}
    ACCESSIBILITY TREE (what is visible):
    {ax_tree}

    NETWORK CALLS SEEN SO FAR:
    {network_calls}

    STEPS TAKEN SO FAR ({step_num}/{max_steps}):
    {steps_taken}

    CODE KNOWLEDGE:
    {code_context}

    Decide your NEXT action. Respond ONLY in JSON — no extra text:
    {{
      "action":       "click" | "fill" | "select" | "scroll" | "observe" | "navigate" | "verify" | "qa_needed" | "switch_tab" | "close_tab" | "download_zip" | "download_file" | "reset_order",
      "target":       "<exact element name from accessibility tree — required for click/fill/select/download_zip/download_file>",
      "value":        "<text to type (fill) OR option to select (select)>",
      "path":         "<relative path only e.g. 'shipping' or 'settings' — NEVER put a full URL here — required for navigate>",
      "description":  "one sentence: what you are doing and why",
      "verdict":      "pass | fail | partial  — ONLY when action=verify",
      "finding":      "what you observed      — ONLY when action=verify",
      "question":     "your question for QA   — ONLY when action=qa_needed",
      "order_action": "<required ONLY for reset_order — one of: existing_fulfilled | existing_unfulfilled | create_new | create_bulk>"
    }}

    Rules:
    - action=verify      → you have clear evidence to give a verdict
    - action=qa_needed   → you genuinely cannot locate the feature after looking carefully
    - action=reset_order → use ONLY when you discover you have the WRONG test data mid-run
                           (e.g. you need an order with a label but got an unfulfilled order, or vice versa)
                           Set "order_action" to what you actually need. The system will fetch/create the right
                           order and inject new context. Use this BEFORE wasting steps on wrong data.
                           Example: {{"action":"reset_order","order_action":"existing_fulfilled","description":"Need fulfilled order to cancel label"}}
    - action=select      → use for ANY dropdown or combobox where you need to pick an option value
                         (e.g. packing method, weight unit, signature type, alcohol type, battery type, duties terms)
                         target = dropdown label name, value = option text to select
    - action=fill      → use ONLY for free-text inputs (weight value, declared value, dimensions numbers)
    - action=click     → use for buttons, checkboxes, toggles, tabs, links — NOT for selecting dropdown options
    - ONLY reference targets that literally appear in the accessibility tree above
    - Do NOT explore unrelated sections of the app
    - action=observe on first step to capture visible elements before interacting

    TWO COMPLETELY DIFFERENT PRODUCTS PAGES:
    - nav_clicks "AppProducts"  →  <app_base>/products  (FedEx app inside iframe)
        USE FOR: configure FedEx settings on an existing product
        → dry ice, alcohol, battery, dimensions (L/W/H), signature option, declared value, freight class
        → click product row in list → URL becomes <app_base>/products/<id>
        → Save button is inside the iframe
        ⚠️ NO "Add product" button — cannot create products here
    - nav_clicks "ShopifyProducts"  →  admin.shopify.com/store/<store>/products  (Shopify admin)
        USE FOR: create new product, edit Shopify fields (title/price/weight/SKU/variants/HS code/barcode)
        → has "Add product" button at top-right
        ⚠️ This is NOT the FedEx app — no FedEx-specific fields here

    STRICT RULE: "dry ice / alcohol / battery / signature / dimensions on product" → AppProducts
    STRICT RULE: "add product / create product / 250 variants / product weight in Shopify" → ShopifyProducts

    Document verification rules:
    - To verify LABEL EXISTS: look for "label generated" status badge on Order Summary (Strategy 1)
    - To verify DOCUMENTS PRESENT (label PDF, packing slip, CI):
      Strategy 2: More Actions → download_zip target="Download Documents"
      → ZIP with physical docs — verify files are present
      ⚠️ Print Documents is NOT a download — it opens a NEW TAB viewer (use Strategy 5 for that)
    - To verify FIELD VALUES in JSON (signature, special services, HAL, dry ice, alcohol, battery, declared value):
      Strategy 3 (ONLY option): click "More Actions" → click "How To" → scroll to bottom → download_zip target="Click Here"
      → RequestResponse ZIP extracted → JSON visible in next step context → action=verify
    - Strategy 4 (rate log, ONLY during manual label BEFORE generating): click ⋯ → "View Logs" → screenshot JSON dialog
    - To verify TEXT ON THE LABEL ITSELF (ICE for dry ice, ALCOHOL, ASR/DSR/ISA signature codes, address):
      Strategy 5: click "Print Documents" → new tab opens at *document-viewer.pluginhive.io*
      → action=switch_tab → screenshot → read label visually → action=verify → action=close_tab
    - After download_zip: next step sees JSON in context → action=verify directly (no extra observe needed)
    - To download and verify a REPORT (CSV file): action=download_file, target="Generate Report"
      → next step context shows: filename, row_count, headers[], sample_rows[], raw_preview
      → action=verify: check expected columns exist and row_count > 0
    - download_file works for ANY direct file download (CSV, Excel) — NOT for ZIPs (use download_zip for those)
    - SideDock settings (signature, HAL, insurance, COD) OVERRIDE product/global settings for that label
""")

_SUMMARY_PROMPT = dedent("""\
    QA lead summary for feature: {card_name}

    Scenario results:
    {results}

    Write 2-3 sentences. Call out any failures or blockers for sign-off.
""")


# ── Browser helpers ───────────────────────────────────────────────────────────

def get_auto_app_url() -> str:
    """Auto-detect app URL from automation repo .env STORE value."""
    if _ENV_FILE.exists():
        for line in _ENV_FILE.read_text(encoding="utf-8").splitlines():
            s = line.strip()
            if s.startswith("#") or "=" not in s:
                continue
            k, _, v = s.partition("=")
            if k.strip() == "STORE":
                v = v.strip().strip('"').strip("'")
                if v and not v.startswith("your-"):
                    store = v.replace(".myshopify.com", "")
                    return f"https://admin.shopify.com/store/{store}/apps/testing-553"
    return ""


def _auth_ctx_kwargs() -> dict:
    kw: dict = {"viewport": {"width": 1400, "height": 1000}}
    if _AUTH_JSON.exists():
        try:
            json.loads(_AUTH_JSON.read_text(encoding="utf-8"))
            kw["storage_state"] = str(_AUTH_JSON)
        except Exception:
            pass
    return kw


def _ax_tree(page) -> str:
    """
    Accessibility tree as readable text.
    Captures BOTH the main Shopify page AND the FedEx app iframe so Claude can
    see elements inside the embedded app (buttons, inputs, dropdowns, etc.).
    """
    lines: list[str] = []

    def _walk(n: dict, d: int = 0, prefix: str = "") -> None:
        if d > 6 or len(lines) > 250:
            return
        role, name = n.get("role", ""), n.get("name", "")
        skip = {"generic", "none", "presentation", "document", "group", "list", "region"}
        if role and name and role not in skip:
            ln = f"{'  ' * d}{prefix}{role}: '{name}'"
            c = n.get("checked")
            if c is not None:
                ln += f" [checked={c}]"
            v = n.get("value", "")
            if v and role in ("textbox", "combobox"):
                ln += f" [value='{v[:30]}']"
            lines.append(ln)
        for ch in n.get("children", []):
            _walk(ch, d + 1, prefix)

    # 1. Main page (Shopify admin chrome — sidebar, headers)
    try:
        ax = page.accessibility.snapshot(interesting_only=True)
        if ax:
            _walk(ax)
    except Exception as e:
        lines.append(f"(main page snapshot error: {e})")

    # 2. FedEx app iframe — this is WHERE all the app UI lives.
    #    Without this, Claude is blind to buttons, dropdowns, and inputs inside the app.
    try:
        for frame in page.frames:
            if frame is page.main_frame:
                continue
            frame_url = frame.url or ""
            # Only capture app-related iframes (skip Shopify analytics/tracking iframes)
            if not frame_url or ("shopify" not in frame_url and "pluginhive" not in frame_url
                                 and "apps" not in frame_url):
                continue
            try:
                frame_ax = frame.accessibility.snapshot(interesting_only=True)
                if frame_ax:
                    lines.append(f"\n--- [APP IFRAME: {frame_url[:60]}] ---")
                    _walk(frame_ax, prefix="")
                    lines.append("--- [END IFRAME] ---")
            except Exception:
                pass
    except Exception:
        pass

    return "\n".join(lines) or "(no interactive elements)"


def _screenshot(page) -> str:
    """Base64 PNG of current page — scaled to 50% to reduce token cost."""
    try:
        # scale=0.5 halves width+height → ~4× smaller file, still readable by Claude
        raw = page.screenshot(full_page=False, scale="css")
        return base64.standard_b64encode(raw).decode()
    except Exception:
        try:
            return base64.standard_b64encode(page.screenshot(full_page=False)).decode()
        except Exception:
            return ""


_NET_JS = """() =>
    performance.getEntriesByType('resource')
      .filter(e => ['xmlhttprequest','fetch'].includes(e.initiatorType))
      .slice(-40).map(e => e.name)
"""

def _network(page, endpoints: list[str]) -> list[str]:
    """
    Recent API/XHR calls matching endpoint paths.
    Checks BOTH the main page AND iframe frames so FedEx app API calls are captured.
    """
    all_entries: list[str] = []

    # Main page
    try:
        entries = page.evaluate(_NET_JS)
        all_entries.extend(entries or [])
    except Exception:
        pass

    # Iframe frames — FedEx app API calls live here (same URL filter as _ax_tree)
    try:
        for frame in page.frames:
            if frame is page.main_frame:
                continue
            frame_url = frame.url or ""
            if not frame_url or ("shopify" not in frame_url and "pluginhive" not in frame_url
                                 and "apps" not in frame_url):
                continue
            try:
                entries = frame.evaluate(_NET_JS)
                all_entries.extend(entries or [])
            except Exception:
                pass
    except Exception:
        pass

    # Deduplicate
    seen: set[str] = set()
    hits: list[str] = []
    for e in all_entries:
        if e not in seen:
            seen.add(e)
            hits.append(e)

    if endpoints:
        return [e for e in hits if any(ep in e for ep in endpoints)]
    return [e for e in hits if "/api/" in e or "fedex" in e.lower() or "pluginhive" in e.lower()]


def _app_frame(page):
    return page.frame_locator('iframe[name="app-iframe"]')


def _do_action(page, action: dict, app_base: str) -> bool:
    """Execute a Claude-decided browser action. Returns True on success."""
    atype  = action.get("action", "observe")
    target = action.get("target", "").strip()
    value  = action.get("value", "")
    path   = action.get("path", "").strip("/")

    if atype == "navigate":
        # Guard: Claude sometimes puts a full URL or duplicated path as `path`.
        # Normalise to a clean URL before navigating.
        if not path:
            url = app_base
        elif path.startswith("http://") or path.startswith("https://"):
            # Already a full URL — use as-is
            url = path
        elif "admin.shopify.com" in path or "myshopify.com" in path:
            # Full path without scheme (e.g. "admin.shopify.com/store/...")
            url = "https://" + path.lstrip("/")
        elif path.startswith("store/"):
            # Claude put the Shopify store path (e.g. "store/mystore/apps/testing-553/shipping")
            # — prepend the scheme+domain
            url = "https://admin.shopify.com/" + path
        else:
            # Normal relative path (e.g. "shipping", "settings") — append to app_base
            url = f"{app_base}/{path}"
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            page.wait_for_timeout(800)
            return True
        except Exception:
            return False

    if atype in ("observe", "verify", "qa_needed"):
        return True

    if atype == "scroll":
        try:
            page.evaluate("window.scrollBy(0, 400)")
        except Exception:
            pass
        return True

    if atype == "switch_tab":
        # Switch to the most-recently-opened browser tab (e.g. a PDF that opened in a new tab)
        try:
            ctx = page.context
            pages = ctx.pages
            if len(pages) > 1:
                new_tab = pages[-1]   # most recently opened
                new_tab.bring_to_front()
                new_tab.wait_for_load_state("domcontentloaded", timeout=10_000)
                # Mutate caller's page reference — replace the page object in the action loop
                # by swapping the page variable in the enclosing _verify_scenario scope.
                # We can't rebind the local var, so store the new page on the action dict
                # so _verify_scenario can pick it up.
                action["_new_page"] = new_tab
            return True
        except Exception as e:
            logger.debug("switch_tab failed: %s", e)
            return False

    if atype == "close_tab":
        # Close the current tab and switch back to the first (main Shopify) tab
        try:
            ctx = page.context
            if len(ctx.pages) > 1:
                page.close()
                # Re-fetch pages AFTER close so the reference is fresh
                main_page = ctx.pages[0]
                main_page.bring_to_front()
                action["_new_page"] = main_page
            return True
        except Exception as e:
            logger.debug("close_tab failed: %s", e)
            return False

    # frame is needed by download_zip, click, fill, and other handlers below
    frame = _app_frame(page)

    if atype == "download_zip":
        # Click `target` to trigger a file download, save the ZIP, unzip it,
        # read all JSON files inside, and store the parsed content in
        # action["_zip_content"] so the agentic loop can pass it to Claude.
        try:
            tmp_dir  = tempfile.mkdtemp(prefix="sav_zip_")
            zip_path = os.path.join(tmp_dir, "fedex_download.zip")

            # Locate the element that triggers the download (iframe-first strategy)
            el_to_click = None
            for fn in [
                lambda: frame.get_by_role("button", name=target, exact=False),
                lambda: frame.get_by_role("link",   name=target, exact=False),
                lambda: frame.get_by_text(target, exact=False),
                lambda: page.get_by_role("button",  name=target, exact=False),
                lambda: page.get_by_role("link",    name=target, exact=False),
                lambda: page.get_by_text(target, exact=False),
            ]:
                try:
                    el = fn()
                    if el.count() > 0:
                        el_to_click = el.first
                        break
                except Exception:
                    continue

            if el_to_click is None:
                logger.debug("download_zip: target '%s' not found in page/iframe", target)
                return False

            # Use Playwright's expect_download context to intercept the file
            with page.expect_download(timeout=30_000) as dl_info:
                el_to_click.click(timeout=5_000)

            dl = dl_info.value
            dl.save_as(zip_path)
            page.wait_for_timeout(500)

            # Unzip and read all files inside the ZIP
            extracted: dict[str, object] = {}
            try:
                with zipfile.ZipFile(zip_path, "r") as zf:
                    for name in zf.namelist():
                        ext = name.rsplit(".", 1)[-1].lower()
                        if ext == "json":
                            raw_text = zf.read(name).decode("utf-8", errors="replace")
                            try:
                                extracted[name] = json.loads(raw_text)
                            except Exception:
                                extracted[name] = raw_text
                        elif ext in ("csv", "txt", "xml", "log"):
                            # Text files — read as string so Claude can verify content
                            raw_text = zf.read(name).decode("utf-8", errors="replace")
                            extracted[name] = raw_text[:3000]  # cap at 3000 chars
                        else:
                            # Binary file (PDF, PNG, etc.) — record size only
                            info = zf.getinfo(name)
                            extracted[name] = f"({ext.upper()} binary — {info.file_size:,} bytes)"
            except Exception as zip_err:
                logger.debug("ZIP extraction error: %s", zip_err)
                extracted["_error"] = str(zip_err)

            action["_zip_content"] = extracted
            logger.info(
                "download_zip: extracted %d file(s) from ZIP — %s",
                len(extracted), list(extracted.keys()),
            )

            # Cleanup temp files
            try:
                import shutil
                shutil.rmtree(tmp_dir, ignore_errors=True)
            except Exception:
                pass

            return True

        except Exception as e:
            logger.debug("download_zip failed: %s", e)
            return False

    if atype == "download_file":
        # Download any file (CSV, Excel, PDF) — read content and inject into context.
        # Use this for: Generate Report (CSV), any non-ZIP direct download.
        try:
            tmp_dir   = tempfile.mkdtemp(prefix="sav_file_")
            tmp_path  = os.path.join(tmp_dir, "fedex_download")

            # Locate the trigger element (iframe-first)
            el_to_click = None
            for fn in [
                lambda: frame.get_by_role("button", name=target, exact=False),
                lambda: frame.get_by_role("link",   name=target, exact=False),
                lambda: frame.get_by_text(target, exact=False),
                lambda: page.get_by_role("button",  name=target, exact=False),
                lambda: page.get_by_role("link",    name=target, exact=False),
                lambda: page.get_by_text(target, exact=False),
            ]:
                try:
                    el = fn()
                    if el.count() > 0:
                        el_to_click = el.first
                        break
                except Exception:
                    continue

            if el_to_click is None:
                logger.debug("download_file: target '%s' not found", target)
                return False

            with page.expect_download(timeout=30_000) as dl_info:
                el_to_click.click(timeout=5_000)

            dl = dl_info.value
            filename = dl.suggested_filename or "download"
            save_path = os.path.join(tmp_dir, filename)
            dl.save_as(save_path)
            page.wait_for_timeout(500)

            ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
            content: dict = {"filename": filename}

            if ext == "csv":
                # Read CSV as text — inject all rows so Claude can verify column values
                import csv as _csv
                try:
                    raw = Path(save_path).read_text(encoding="utf-8-sig", errors="replace")
                    lines = raw.splitlines()
                    reader = _csv.reader(lines)
                    rows = list(reader)
                    headers = rows[0] if rows else []
                    sample  = rows[1:6]   # first 5 data rows
                    content["headers"]    = headers
                    content["row_count"]  = len(rows) - 1  # exclude header
                    content["sample_rows"] = sample
                    content["raw_preview"] = "\n".join(lines[:20])  # first 20 lines
                    logger.info("download_file: CSV '%s' — %d rows, headers: %s",
                                filename, len(rows) - 1, headers)
                except Exception as csv_err:
                    content["raw_preview"] = Path(save_path).read_text(
                        encoding="utf-8", errors="replace")[:3000]
                    logger.debug("CSV parse error: %s", csv_err)

            elif ext in ("xlsx", "xls"):
                # Excel — record size, try reading with openpyxl if available
                size = os.path.getsize(save_path)
                content["note"] = f"Excel file ({size:,} bytes) — verify by row count or column headers"
                try:
                    import openpyxl
                    wb = openpyxl.load_workbook(save_path, read_only=True, data_only=True)
                    ws = wb.active
                    rows = list(ws.iter_rows(values_only=True))
                    content["headers"]    = [str(c) for c in (rows[0] if rows else [])]
                    content["row_count"]  = len(rows) - 1
                    content["sample_rows"] = [[str(c) for c in r] for r in rows[1:6]]
                    wb.close()
                except ImportError:
                    pass  # openpyxl not installed — size note is enough

            elif ext == "pdf":
                size = os.path.getsize(save_path)
                content["note"] = f"PDF file ({size:,} bytes)"

            else:
                size = os.path.getsize(save_path)
                raw  = Path(save_path).read_bytes()
                try:
                    content["raw_preview"] = raw.decode("utf-8", errors="replace")[:2000]
                except Exception:
                    content["note"] = f"{ext.upper()} file ({size:,} bytes)"

            action["_file_content"] = content
            logger.info("download_file: downloaded '%s' — %s", filename, list(content.keys()))

            try:
                import shutil
                shutil.rmtree(tmp_dir, ignore_errors=True)
            except Exception:
                pass

            return True

        except Exception as e:
            logger.debug("download_file failed: %s", e)
            return False

    if not target:
        return False

    if atype == "click":
        for fn in [
            lambda: frame.get_by_role("button",   name=target, exact=False),
            lambda: frame.get_by_role("checkbox", name=target, exact=False),
            lambda: frame.get_by_role("switch",   name=target, exact=False),
            lambda: frame.get_by_role("link",     name=target, exact=False),
            lambda: frame.get_by_role("tab",      name=target, exact=False),
            lambda: frame.get_by_text(target, exact=False),
            lambda: page.get_by_role("button", name=target, exact=False),
            lambda: page.get_by_text(target, exact=False),
        ]:
            try:
                el = fn()
                if el.count() > 0:
                    el.first.click(timeout=5_000)
                    page.wait_for_timeout(400)   # reduced: was 800ms
                    return True
            except Exception:
                continue
        logger.debug("Click target not found: '%s'", target)
        return False

    if atype == "fill":
        for fn in [
            lambda: frame.get_by_label(target, exact=False),
            lambda: frame.get_by_placeholder(target, exact=False),
            lambda: frame.get_by_role("textbox", name=target, exact=False),
        ]:
            try:
                el = fn()
                if el.count() > 0:
                    el.first.clear()
                    el.first.fill(value, timeout=5_000)
                    return True
            except Exception:
                continue
        return False

    if atype == "select":
        # Handle dropdown/select elements — tries both native <select> (selectOption)
        # and Polaris/React custom dropdowns (click to open → click option text).
        # target = label or aria-name of the dropdown
        # value  = the option to select (visible text)
        if not value:
            logger.debug("select action requires value — skipping")
            return False

        # Strategy 1: native <select> via label (e.g. weight unit lb/kg, packing method)
        # Matches automation's .selectOption() pattern used in PackagingSettingsPage etc.
        for fn in [
            lambda: frame.get_by_label(target, exact=False),
            lambda: frame.get_by_role("combobox", name=target, exact=False),
            lambda: page.get_by_label(target, exact=False),
            lambda: page.get_by_role("combobox", name=target, exact=False),
        ]:
            try:
                el = fn()
                if el.count() > 0:
                    # Try selectOption first (native <select>)
                    try:
                        el.first.select_option(value, timeout=5_000)
                        page.wait_for_timeout(400)
                        logger.debug("select: native selectOption('%s') on '%s'", value, target)
                        return True
                    except Exception:
                        pass
                    # Fallback: Polaris custom dropdown — click to open, then click option
                    try:
                        el.first.click(timeout=5_000)
                        page.wait_for_timeout(300)
                        for opt_fn in [
                            lambda v=value: frame.get_by_role("option", name=v, exact=False),
                            lambda v=value: frame.get_by_text(v, exact=False),
                            lambda v=value: page.get_by_role("option", name=v, exact=False),
                            lambda v=value: page.get_by_text(v, exact=False),
                        ]:
                            opt = opt_fn()
                            if opt.count() > 0:
                                opt.first.click(timeout=3_000)
                                page.wait_for_timeout(400)
                                logger.debug("select: Polaris click('%s') on '%s'", value, target)
                                return True
                    except Exception:
                        pass
            except Exception:
                continue

        logger.debug("select: could not find dropdown '%s' or option '%s'", target, value)
        return False

    return True


# ── Code RAG ─────────────────────────────────────────────────────────────────

def _code_context(scenario: str, card_name: str) -> str:
    """Query automation POM + backend API + QA knowledge for context."""
    parts: list[str] = []
    query = f"{card_name} {scenario}"

    try:
        from rag.code_indexer import search_code

        # Always fetch label generation workflow from automation — it has the exact steps
        label_docs = search_code(
            "generate label More Actions click order Shopify navigate",
            k=5, source_type="automation",
        )
        if label_docs:
            snippets = "\n---\n".join(
                f"[{d.metadata.get('file_path','').split('/')[-1]}]\n{d.page_content[:600]}"
                for d in label_docs
            )
            parts.append(f"=== Automation POM — Label Generation Workflow ===\n{snippets}")

        # Scenario-specific automation code
        scenario_docs = search_code(query, k=5, source_type="automation")
        if scenario_docs:
            snippets = "\n---\n".join(
                f"[{d.metadata.get('file_path','').split('/')[-1]}]\n{d.page_content[:600]}"
                for d in scenario_docs
            )
            parts.append(f"=== Automation POM — Scenario Specific ===\n{snippets}")

        # Backend API context
        be_docs = search_code(query, k=3, source_type="backend")
        if be_docs:
            snippets = "\n---\n".join(d.page_content[:400] for d in be_docs)
            parts.append(f"=== Backend API ===\n{snippets}")

    except Exception as e:
        logger.debug("Code RAG error: %s", e)

    try:
        from rag.vectorstore import search as qs
        docs = qs(query, k=3)
        if docs:
            snippets = "\n---\n".join(d.page_content[:400] for d in docs)
            parts.append(f"=== Domain Knowledge ===\n{snippets}")
    except Exception as e:
        logger.debug("QA knowledge RAG error: %s", e)

    return "\n\n".join(parts) if parts else "(no code context indexed yet)"


# ── Domain Expert ─────────────────────────────────────────────────────────────

def _ask_domain_expert(scenario: str, card_name: str, claude: "ChatAnthropic") -> str:
    """Ask the domain expert what this scenario should do.

    Queries both the domain RAG (PluginHive docs, FedEx API knowledge) and the
    code RAG (automation POM, backend), then asks Claude to synthesise a concise
    answer covering:
      - Expected UI behaviour
      - API/request fields to watch
      - Specific things that confirm the feature is working

    Returns a plain-text answer (≤200 words) ready to be injected into the plan
    and step prompts.
    """
    query = f"{card_name} {scenario}"
    api_query = f"{scenario} API request field FedEx"
    domain_sections: list[str] = []
    code_parts:      list[str] = []

    # ── Domain RAG — 5 targeted sub-queries, one per source type ─────────────
    # Each sub-query is filtered to a single source_type so Claude receives a
    # clearly labelled section for each knowledge category rather than an
    # anonymous blob where source attribution is impossible.
    _DOMAIN_SOURCES = [
        # (source_type,       query_to_use, label,                                   k)
        ("pluginhive_docs",  query,        "PluginHive Official Documentation",      4),
        ("pluginhive_seeds", query,        "PluginHive FAQ & Guides",                3),
        ("fedex_rest",       api_query,    "FedEx REST API Reference",               4),
        ("wiki",             query,        "Internal Wiki (Product & Engineering)",  5),
        ("pdf",              query,        "Test Cases & Acceptance Criteria",        3),
    ]

    try:
        from rag.vectorstore import search_filtered
        for src_type, q, label, k in _DOMAIN_SOURCES:
            try:
                docs = search_filtered(q, k=k, source_type=src_type)
                if docs:
                    # For wiki docs add the category tag so Claude sees sub-topic
                    def _fmt(d: "Document") -> str:
                        cat = d.metadata.get("category", "")
                        prefix = f"[{cat}] " if cat else ""
                        return f"{prefix}{d.page_content[:450]}"
                    chunks = "\n\n".join(_fmt(d) for d in docs)
                    domain_sections.append(f"[{label}]\n{chunks}")
            except Exception as e:
                logger.debug("Domain RAG sub-query failed (source_type=%s): %s", src_type, e)
    except ImportError as e:
        logger.debug("search_filtered not available — falling back to unfiltered search: %s", e)
        try:
            from rag.vectorstore import search as rag_search
            docs = rag_search(query, k=8)
            if docs:
                domain_sections.append("\n\n".join(
                    f"[{d.metadata.get('source_type','doc')}] {d.page_content[:450]}"
                    for d in docs
                ))
        except Exception as e2:
            logger.debug("Fallback domain RAG also failed: %s", e2)

    # ── Code RAG (automation POM + backend) ───────────────────────────────────
    try:
        from rag.code_indexer import search_code
        auto_docs = search_code(query, k=5, source_type="automation")
        if auto_docs:
            code_parts.append("\n---\n".join(
                f"[{d.metadata.get('file_path','').split('/')[-1]}]\n{d.page_content[:500]}"
                for d in auto_docs
            ))
        be_docs = search_code(query, k=4, source_type="backend")
        if be_docs:
            code_parts.append("\n---\n".join(
                f"[{d.metadata.get('file_path','').split('/')[-1]}]\n{d.page_content[:400]}"
                for d in be_docs
            ))
    except Exception as e:
        logger.debug("Code RAG error in expert: %s", e)

    domain_context = "\n\n---\n\n".join(domain_sections) or "(no domain knowledge indexed)"
    code_context   = "\n\n".join(code_parts)              or "(no code indexed)"

    # Inject hardcoded pre-requirements if available (from automation spec files)
    preconditions = _get_preconditions(scenario)
    preconditions_section = (
        f"KNOWN PRE-REQUIREMENTS (from automation spec files):\n{preconditions}"
        if preconditions else ""
    )

    prompt = _DOMAIN_EXPERT_PROMPT.format(
        scenario=scenario,
        card_name=card_name,
        domain_context=domain_context[:4000],
        code_context=code_context[:3000],
        preconditions_section=preconditions_section,
    )

    try:
        resp = claude.invoke([HumanMessage(content=prompt)])
        answer = resp.content.strip()
        if isinstance(answer, list):
            answer = " ".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in answer)
        return answer[:1200]   # cap so it doesn't crowd other context
    except Exception as e:
        logger.warning("Domain expert query failed: %s", e)
        return "(domain expert unavailable)"


# ── Claude helpers ────────────────────────────────────────────────────────────

def _parse_json(raw: str) -> dict:
    """Extract JSON from Claude's response — handles markdown fences, prefix/suffix text."""
    # 1. Try direct parse first
    clean = re.sub(r"```(?:json)?\n?", "", raw.strip()).strip().rstrip("`").strip()
    try:
        return json.loads(clean)
    except Exception:
        pass

    # 2. Find the first { ... } or [ ... ] block (handles "Here is the JSON: {...}" or "[...]")
    match = re.search(r"(\{[\s\S]*\}|\[[\s\S]*\])", raw)
    if match:
        try:
            return json.loads(match.group())
        except Exception:
            pass

    return {}


def _extract_scenarios(ac: str, claude: ChatAnthropic) -> list[str]:
    resp = claude.invoke([HumanMessage(content=_EXTRACT_PROMPT.format(ac=ac))])
    raw  = resp.content.strip()
    data = _parse_json(raw)
    if isinstance(data, list):
        return data
    # fallback: parse line by line
    return [
        ln.strip("- ").strip()
        for ln in ac.splitlines()
        if ln.strip().startswith(("Given", "When", "Scenario", "Then", "-"))
    ][:12]


def _validate_order_action(scenario: str, claude_choice: str) -> str:
    """
    Fix 1 — Python safety net: override clearly wrong order_action choices.
    Claude's plan is usually right; this catches obvious mismatches.
    """
    s = scenario.lower()

    # These scenarios MUST have a label to cancel/verify — needs existing_fulfilled
    _fulfilled_signals = [
        "cancel label", "cancel the label", "after cancellation", "after label cancel",
        "address update", "update address", "update the address", "update shipping address",
        "updated address", "regenerate",
        "re-generate", "return label", "generate return", "download document",
        "verify label", "print document", "label shows", "label generated",
        "next/previous order", "order summary nav",
    ]
    if any(kw in s for kw in _fulfilled_signals):
        if claude_choice in ("create_new", "existing_unfulfilled", "none"):
            logger.info(
                "[order_validate] Overriding '%s' → 'existing_fulfilled' "
                "(scenario signals a label must exist)", claude_choice
            )
            return "existing_fulfilled"

    # These scenarios create a brand-new label — needs fresh unfulfilled order
    _new_order_signals = [
        "generate label", "create label", "auto-generate label", "manual label",
        "dry ice", "alcohol", "battery", "signature required", "adult signature",
        "hold at location", " hal ", "cod ", "cash on delivery", "insurance",
        "declared value", "one rate", "fedex one rate",
        "domestic label", "international label",
    ]
    if any(kw in s for kw in _new_order_signals):
        if claude_choice == "none":
            logger.info(
                "[order_validate] Overriding 'none' → 'create_new' "
                "(scenario signals label generation)"
            )
            return "create_new"

    # Bulk keywords
    _bulk_signals = ["bulk", "50 orders", "100 orders", "batch label", "select all orders",
                     "auto-generate labels", "bulk print"]
    if any(kw in s for kw in _bulk_signals):
        if claude_choice in ("none", "create_new", "existing_fulfilled"):
            logger.info("[order_validate] Overriding '%s' → 'create_bulk'", claude_choice)
            return "create_bulk"

    return claude_choice


def _setup_order_ctx(order_action: str, scenario: str, base_ctx: str) -> str:
    """
    Fix 2 (reuse) — build the order context prefix for a given order_action.
    Called at start of scenario AND by reset_order mid-run.
    Returns the context string with order strategy prepended.
    """
    from pipeline.order_creator import resolve_order

    if order_action == "create_product_250_variants":
        from pipeline.product_creator import get_or_create_high_variant_product
        product_info = get_or_create_high_variant_product(variant_count=250)
        if product_info:
            return (
                f"HIGH-VARIANT PRODUCT READY: '{product_info['title']}' — "
                f"{product_info['variant_count']} variants (id: {product_info['id']})\n"
                f"Admin URL: {product_info['admin_url']}\n"
                f"Navigate: ShopifyProducts → search '{product_info['title']}' → open → scroll to Variants.\n\n"
                + base_ctx
            )
        return ("PRODUCT NOTE: Could not create 250-variant product via API. "
                "Navigate to ShopifyProducts and verify manually.\n\n" + base_ctx)

    if order_action == "create_bulk":
        orders = resolve_order(scenario, "create_bulk")
        if orders and isinstance(orders, list):
            names = [o["name"] for o in orders]
            return (
                f"BULK ORDERS CREATED: {len(orders)} fresh unfulfilled orders → {names}\n"
                f"Ready in Shopify admin → Orders list (Unfulfilled tab).\n"
                f"Flow: select all → Actions → Auto-Generate Labels\n\n" + base_ctx
            )
        return ("ORDER STRATEGY: Use existing unfulfilled orders in Shopify admin → "
                "Orders → Unfulfilled tab.\n\n" + base_ctx)

    if order_action == "create_new":
        order = resolve_order(scenario, "create_new")
        if order and isinstance(order, dict):
            return (
                f"FRESH ORDER CREATED: {order.get('name')} (id: {order.get('id')}) — "
                f"unfulfilled, ready for label generation. "
                f"Find it in Shopify admin → Orders → Unfulfilled tab.\n\n" + base_ctx
            )
        # Fallback to existing_unfulfilled
        return ("ORDER STRATEGY: Use an existing UNFULFILLED order. "
                "Shopify admin LEFT sidebar → Orders → Unfulfilled tab → first order.\n\n" + base_ctx)

    if order_action == "existing_unfulfilled":
        return ("ORDER STRATEGY: Use an existing UNFULFILLED order. "
                "Shopify admin LEFT sidebar → Orders → Unfulfilled tab → first order in list.\n\n"
                + base_ctx)

    if order_action == "existing_fulfilled":
        return ("ORDER STRATEGY: Use an order that already HAS a label generated. "
                "App sidebar → Shipping → Label Generated tab → click first order row.\n\n"
                + base_ctx)

    # none
    return base_ctx


def _get_preconditions(scenario: str) -> str:
    """
    Returns hardcoded pre-requirements for known scenario types.
    Based on real automation spec files — exact flows, product names, JSON fields, PDF codes.
    Returns empty string for unknown scenarios (RAG + domain expert handle those).
    """
    s = scenario.lower()

    if "dry ice" in s or "dryice" in s or "dry-ice" in s:
        return dedent("""\
            PRE-REQUIREMENTS (from automation spec: dryIce.spec.ts):
            1. nav_clicks: ["AppProducts"]
            2. AppProducts: search 'Simple 1' → check 'Is Dry Ice Needed' → fill Dry Ice Weight = '0.3' (kg) → Save
            3. order_action: create_new  (fresh Shopify order with simple product, US address)
            VERIFY during Manual Label flow (after Get Rates, BEFORE Generate Label):
            - Strategy 4: ⋯ → View Logs → JSON must contain:
                specialServiceTypes: ["DRY_ICE"]
                dryIceWeight.value = 0.3,  unit = "KG"
            VERIFY label text (Strategy 5): Print Documents → 'ICE' text on label
            CLEANUP: AppProducts → uncheck 'Is Dry Ice Needed' → Save""")

    if "alcohol" in s:
        recipient = "LICENSEE" if "licensee" in s else "CONSUMER"
        return dedent(f"""\
            PRE-REQUIREMENTS (from automation spec: alcoholRecipient{'Licensee' if recipient=='LICENSEE' else 'Consumer'}.spec.ts):
            1. nav_clicks: ["AppProducts"]
            2. AppProducts: search 'Simple 1' → check 'Is Alcohol' → set Alcohol Recipient Type = '{recipient}' → Save
            3. order_action: create_new  (fresh Shopify order with simple product, US address)
            VERIFY during Manual Label flow (after Get Rates, BEFORE Generate Label):
            - Strategy 4: ⋯ → View Logs → JSON must contain:
                specialServiceTypes: ["ALCOHOL"]
                alcoholDetail.alcoholRecipientType = "{recipient}"
            VERIFY label text (Strategy 5): Print Documents → 'ALCOHOL' text on label
            CLEANUP: AppProducts → uncheck 'Is Alcohol' → Save""")

    if "battery" in s or "lithium" in s:
        if "metal" in s or "packed with" in s:
            material, packing = "LITHIUM_METAL", "PACKED_WITH_EQUIPMENT"
        else:
            material, packing = "LITHIUM_ION", "CONTAINED_IN_EQUIPMENT"
        return dedent(f"""\
            PRE-REQUIREMENTS (from automation spec: battery{material.title().replace('_','')}.spec.ts):
            1. nav_clicks: ["AppProducts"]
            2. AppProducts: search 'Simple 1' → check 'Is Battery'
               → set Battery Material Type = '{material}'
               → set Battery Packing Type = '{packing}' → Save
            3. order_action: create_new  (fresh Shopify order with simple product)
            VERIFY during Manual Label flow (after Get Rates, BEFORE Generate Label):
            - Strategy 4: ⋯ → View Logs → JSON must contain:
                specialServiceTypes: ["BATTERY"]
                batteryDetails[0].materialType = "{material}"
                batteryDetails[0].batteryPackingType = "{packing}"
                batteryDetails[0].regulatorySubType = "IATA_SECTION_II"
            VERIFY label text (Strategy 5): Print Documents → 'ELB' text on label  ← NOTE: 'ELB' not 'BATTERY'
            CLEANUP: AppProducts → uncheck 'Is Battery' → Save""")

    # Signature at PRODUCT level (e.g. "adult signature on product")
    _SIG_MAP = {
        "adult":          ("ADULT",          "Adult Signature Required",   "ASR"),
        "direct":         ("DIRECT",         "Direct Signature Required",  "DSR"),
        "indirect":       ("INDIRECT",       "Indirect Signature Required","ISR"),
        "service default":("SERVICE_DEFAULT","Service Default",            "SS AVXA"),
    }
    if "signature" in s and any(k in s for k in _SIG_MAP):
        for key, (val, label, pdf_code) in _SIG_MAP.items():
            if key in s:
                return dedent(f"""\
                    PRE-REQUIREMENTS (from automation spec: {key.replace(' ','').title()}Signature.spec.ts):
                    1. nav_clicks: ["AppProducts"]
                    2. AppProducts: search 'BLAZER' → set 'FedEx® Delivery Signature Options' = '{label}' (value: {val}) → Save
                    3. order_action: create_new  (fresh Shopify order)
                    VERIFY during Manual Label flow (after Get Rates, BEFORE Generate Label):
                    - Strategy 4: ⋯ → View Logs → JSON must contain:
                        signatureOptionType = "{val}"
                    VERIFY label text (Strategy 5): Print Documents → '{pdf_code}' text on label
                    CLEANUP: AppProducts → search 'BLAZER' → reset Signature to 'As Per The General Settings' → Save""")

    if "hal" in s or "hold at location" in s:
        return dedent("""\
            PRE-REQUIREMENTS (from automation spec: holdAtLocationLabelGeneration.spec.ts):
            1. nav_clicks: ["Orders"]  (no product config — HAL is configured in SideDock)
            2. order_action: create_new  (fresh Shopify order)
            FLOW during Manual Label:
            - SideDock: click 'Hold at Location' → search location → select 'HHRAA' → confirm
            VERIFY BEFORE generating (Strategy 4):
            - ⋯ → View Logs → JSON must contain:
                specialServices: ["HOLD_AT_LOCATION"]
                holdAtLocationDetail.locationId = "HHRAA"
            VERIFY AFTER generating (Strategy 3 via How To ZIP):
            - More Actions → How To → Click Here ZIP → check locationId + locationType match""")

    if "insurance" in s:
        return dedent("""\
            PRE-REQUIREMENTS (from automation spec: insuranceLabelGeneration.spec.ts):
            1. nav_clicks: ["Orders"]  (no product config — Insurance is in SideDock)
            2. order_action: create_new
            FLOW during Manual Label:
            - SideDock: check 'Add Third Party Insurance'
              → Liability Type: 'New' or 'Used or Reconditioned'
              → Insurance Type: 'Percentage of Product Price' or 'Declared Value of Product'
              → fill percentage or leave as declared value
            VERIFY BEFORE generating (Strategy 4):
            - ⋯ → View Logs → JSON must contain:
                declaredValue.amount = expected computed value""")

    if ("sidedock" in s or "side dock" in s) and "signature" in s:
        return dedent("""\
            PRE-REQUIREMENTS (from automation spec: signatureSettingsLabelGeneration.spec.ts):
            1. nav_clicks: ["Orders"]  (signature set in SideDock — NOT product level)
            2. order_action: create_new
            FLOW during Manual Label:
            - SideDock: 'FedEx® Delivery Signature Options' dropdown → select one of:
              ADULT | DIRECT | INDIRECT | NO_SIGNATURE_REQUIRED
            VERIFY BEFORE generating (Strategy 4):
            - ⋯ → View Logs → JSON: signatureOptionType = selected value""")

    return ""  # Unknown scenario — RAG + domain expert will handle it


def _plan_scenario(
    scenario: str, app_url: str, ctx: str, expert_insight: str, claude: ChatAnthropic
) -> dict:
    preconditions = _get_preconditions(scenario)
    prompt = _PLAN_PROMPT.format(
        scenario=scenario, app_url=app_url,
        app_workflow_guide=_trim_workflow_guide(scenario),
        expert_insight=expert_insight or "(not available)",
        code_context=ctx[:5000],
    )
    # Inject preconditions right before the JSON output instruction if available
    if preconditions:
        prompt = prompt.replace(
            "Respond ONLY in JSON:",
            f"KNOWN PRE-REQUIREMENTS FOR THIS SCENARIO (from automation spec files):\n{preconditions}\n\n"
            "Respond ONLY in JSON:",
        )
    resp = claude.invoke([HumanMessage(content=prompt)])
    return _parse_json(resp.content) or {}


def _decide_next(
    claude: ChatAnthropic,
    scenario: str,
    url: str,
    ax: str,
    net: list[str],
    steps: list[VerificationStep],
    ctx: str,
    step_num: int,
    scr: str = "",
    expert_insight: str = "",
) -> dict:
    steps_text = "\n".join(
        f"  {i+1}. [{s.action}] {s.description} ({'✓' if s.success else '✗'})"
        for i, s in enumerate(steps)
    )
    prompt_text = _STEP_PROMPT.format(
        scenario=scenario,
        expert_insight=expert_insight or "(not available)",
        app_workflow_guide=_trim_workflow_guide(scenario),
        url=url,
        ax_tree=ax[:3000],
        network_calls="\n".join(net[-10:]) if net else "(none)",
        steps_taken=steps_text or "(just starting)",
        code_context=ctx[:3000],
        step_num=step_num,
        max_steps=MAX_STEPS,
    )
    # Pass screenshot so Claude can SEE the page, not just the AX tree
    if scr:
        msg = HumanMessage(content=[
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/png",
                    "data": scr,
                },
            },
            {"type": "text", "text": prompt_text},
        ])
    else:
        msg = HumanMessage(content=prompt_text)

    content = claude.invoke([msg]).content
    raw = content if isinstance(content, str) else \
        " ".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in content)
    parsed = _parse_json(raw)
    if parsed:
        logger.debug("[decide] action=%s target=%s", parsed.get("action"), parsed.get("target", ""))
        return parsed
    # Fallback: log what Claude said so user can see it, then observe (don't end the run)
    logger.warning("[decide] Could not parse JSON from Claude response — falling back to observe.\nRaw: %s", raw[:400])
    return {"action": "observe", "description": "JSON parse failed — re-observing page"}


# ── Core: verify one scenario ─────────────────────────────────────────────────

def _verify_scenario(
    page,
    scenario: str,
    card_name: str,
    app_base: str,
    plan_data: dict,
    ctx: str,
    claude: ChatAnthropic,
    progress_cb: Callable | None = None,
    qa_answer: str = "",
    first_scenario: bool = False,
    expert_insight: str = "",
) -> ScenarioResult:
    result       = ScenarioResult(scenario=scenario)
    net_seen: list[str] = []
    api_endpoints = plan_data.get("api_to_watch", [])

    # Inject QA guidance when resuming a stuck scenario
    if qa_answer:
        ctx = f"QA GUIDANCE: {qa_answer}\n\n{ctx}"

    # ── Order setup ───────────────────────────────────────────────────────────
    # Fix 1+2: validate Claude's choice then delegate to _setup_order_ctx
    try:
        from pipeline.order_creator import infer_order_decision
        _claude_order = plan_data.get("order_action") or infer_order_decision(scenario)
        order_action  = _validate_order_action(scenario, _claude_order)
        logger.info("[order] scenario='%s…' → claude=%s validated=%s",
                    scenario[:60], _claude_order, order_action)
        ctx = _setup_order_ctx(order_action, scenario, ctx)
    except Exception as oe:
        logger.debug("[order] Order setup skipped (non-fatal): %s", oe)

    # Only do a full page.goto() for the first scenario to avoid flickering.
    # For subsequent scenarios, click the app's "Shipping" home link in the sidebar
    # to reset to the home page without a full browser reload.
    if first_scenario or not page.url.startswith(app_base.split("/apps/")[0]):
        try:
            page.goto(app_base, wait_until="domcontentloaded", timeout=30_000)
            page.wait_for_timeout(600)  # iframe React app settle
        except Exception as e:
            result.status  = "fail"
            result.verdict = f"Could not navigate to app: {e}"
            return result
    else:
        # Soft reset — navigate back to app home via direct URL (safest — avoids clicking
        # the wrong "Shipping" link in Shopify's own sidebar which goes to Shopify settings)
        try:
            page.goto(app_base, wait_until="domcontentloaded", timeout=20_000)
            page.wait_for_timeout(600)
        except Exception:
            pass

    # Click through planned nav items to reach the right section.
    #
    # Navigation strategy:
    #  - "Orders" is a Shopify admin left-sidebar link (outside the iframe)
    #  - "Shipping", "Settings", "PickUp", "Products", "FAQ", "Rates Log"
    #    are FedEx app sidebar links (inside the app iframe)
    #
    # For app nav items: search iframe first (avoids clicking Shopify's own
    # "Shipping and delivery" or "Settings" links by mistake).
    # For Shopify nav items: search the full page first.
    #
    # Nav failures are NON-FATAL — if a click fails, we log it and continue
    # to the agentic loop; Claude will see the current page state and decide
    # what to do next (instead of immediately asking QA).
    nav_clicks = plan_data.get("nav_clicks", [])
    # ── Direct URL map for every known app page ───────────────────────────────
    # From live app screenshots: all internal pages follow {app_base}/{path} pattern.
    # Using direct goto() is 100% reliable — no link finding, no iframe confusion.
    _store = app_base.split("/store/")[1].split("/")[0] if "/store/" in app_base else ""
    _APP_URL_MAP = {
        # ── FedEx app pages (rendered inside the app iframe) ──────────────────
        # Verified from live browser URL bar:
        "shipping":    f"{app_base}/shopify",       # App's All Orders grid
        "appproducts": f"{app_base}/products",      # FedEx app Products — EDIT FedEx settings
                                                    # on existing products (dry ice, alcohol,
                                                    # battery, dimensions, signature, declared value)
                                                    # Clicking a row → {app_base}/products/{id}
        "products":    f"{app_base}/products",      # legacy alias → AppProducts
        "settings":    f"{app_base}/settings/0",    # App Settings (General tab)
        "pickup":      f"{app_base}/pickup",        # Pickups list
        "faq":         f"{app_base}/faq",           # FAQ
        "rates log":   f"{app_base}/rateslog",      # Rates Log (NO hyphen — rateslog)
        # ── Shopify admin pages (outside iframe) ──────────────────────────────
        "orders":          f"https://admin.shopify.com/store/{_store}/orders",
        # ShopifyProducts = Shopify's own product management page.
        # This is the ONLY place to ADD a new product or edit Shopify product fields
        # (title, price, weight, SKU, barcode, HS code, variants).
        # ⚠️ NOT the FedEx app Products page — that is AppProducts above.
        "shopifyproducts": f"https://admin.shopify.com/store/{_store}/products",
    }
    nav_failed: list[str] = []

    for nav_label in nav_clicks:
        clicked   = False
        label_low = nav_label.lower().strip()
        nav_url   = _APP_URL_MAP.get(label_low)

        if nav_url:
            # Direct URL navigation — instant, reliable, no link-clicking ambiguity
            try:
                page.goto(nav_url, wait_until="domcontentloaded", timeout=30_000)
                page.wait_for_timeout(600)
                clicked = True
                logger.info("Nav [%s] → %s", nav_label, nav_url)
            except Exception as e:
                logger.warning("Direct nav failed for '%s' (%s): %s", nav_label, nav_url, e)

        if not clicked:
            # Unknown nav label — fall back to clicking the link on the full page
            try:
                for fn in [
                    lambda l=nav_label: page.get_by_role("link",   name=l, exact=True),
                    lambda l=nav_label: page.get_by_role("link",   name=l, exact=False),
                    lambda l=nav_label: page.get_by_text(l, exact=False),
                ]:
                    loc = fn()
                    if loc.count() > 0:
                        loc.first.click(timeout=5_000)
                        page.wait_for_timeout(500)
                        clicked = True
                        break
            except Exception:
                pass

        if not clicked:
            nav_failed.append(nav_label)
            logger.warning("Nav '%s' not found — agentic loop will handle navigation", nav_label)
            result.steps.append(VerificationStep(
                action="observe",
                description=f"Nav '{nav_label}' not found — will navigate from current page state",
                success=False,
            ))

    # Detect bot-challenge page
    try:
        body = page.inner_text("body").lower()
        if any(p in body for p in _CHALLENGE_PHRASES):
            result.status  = "skipped"
            result.verdict = "⚠️ Shopify bot-detection challenge. Refresh auth.json and retry."
            return result
    except Exception:
        pass

    # Agentic loop ────────────────────────────────────────────────────────────
    # `active_page` may change when Claude opens/closes a new tab (e.g. PDF viewer)
    active_page = page
    # Accumulated ZIP content from download_zip actions — prepended to ctx so
    # Claude can read the extracted JSON on subsequent steps.
    zip_ctx = ""

    for step_num in range(1, MAX_STEPS + 1):
        ax  = _ax_tree(active_page)
        scr = _screenshot(active_page)
        net = _network(active_page, api_endpoints)
        net_seen.extend(n for n in net if n not in net_seen)

        if progress_cb:
            progress_cb(step_num, f"Step {step_num}/{MAX_STEPS}")

        # Prepend any previously downloaded ZIP content so Claude can reason about it
        effective_ctx = f"{zip_ctx}{ctx}" if zip_ctx else ctx

        action = _decide_next(claude, scenario, active_page.url, ax, net_seen,
                              result.steps, effective_ctx, step_num, scr=scr,
                              expert_insight=expert_insight)

        atype = action.get("action", "observe")
        _desc = action.get("description", atype)
        _tgt  = action.get("target", "")

        # Always log what the agent is doing — visible in dashboard logs
        logger.info("[step %d/%d] action=%-12s target=%-30s | %s",
                    step_num, MAX_STEPS, atype, _tgt[:30], _desc[:80])
        if progress_cb:
            progress_cb(step_num, f"[{atype}] {_desc[:60]}")

        step  = VerificationStep(
            action=atype,
            description=_desc,
            target=_tgt,
            screenshot_b64=scr,
            network_calls=list(net),
        )
        result.steps.append(step)

        if atype == "verify":
            result.status  = action.get("verdict", "partial")
            result.verdict = action.get("finding", "")
            step.screenshot_b64 = _screenshot(active_page)   # final state screenshot
            break

        if atype == "qa_needed":
            result.status      = "qa_needed"
            result.qa_question = action.get("question", "I need more guidance to find this feature.")
            break

        # Fix 3 — mid-run recovery: agent discovered wrong test data and requests a reset
        if atype == "reset_order":
            new_order_action = action.get("order_action", "existing_fulfilled")
            logger.info("[reset_order] Agent requested order reset → %s", new_order_action)
            try:
                ctx = _setup_order_ctx(new_order_action, scenario, ctx)
                step.success = True
                step.description = f"Order reset → {new_order_action}: {action.get('description', '')}"
            except Exception as reset_err:
                logger.warning("[reset_order] failed: %s", reset_err)
                step.success = False
            continue

        step.success = _do_action(active_page, action, app_base)

        # If download_zip succeeded, accumulate the extracted JSON as future context
        if "_zip_content" in action:
            zip_data = action["_zip_content"]
            # Pretty-print JSON content (cap to 4000 chars to avoid flooding context)
            zip_summary = json.dumps(zip_data, indent=2)[:4000]
            zip_ctx = (
                f"=== DOWNLOADED ZIP CONTENTS (from '{action.get('target','?')}') ===\n"
                f"{zip_summary}\n"
                f"========================================\n\n"
            )

        # If download_file succeeded, accumulate file content as future context
        if "_file_content" in action:
            file_data = action["_file_content"]
            file_summary = json.dumps(file_data, indent=2)[:4000]
            zip_ctx = (
                f"=== DOWNLOADED FILE CONTENTS ('{file_data.get('filename','?')}') ===\n"
                f"{file_summary}\n"
                f"========================================\n\n"
            )
            logger.info("File content accumulated for next step (%d chars)", len(file_summary))

        # If switch_tab / close_tab opened or closed a tab, follow the new page
        if "_new_page" in action:
            active_page = action["_new_page"]

    else:
        # Max steps exhausted without a verify/qa_needed break — ask QA instead of
        # silently marking partial (which hides real issues)
        result.status      = "qa_needed"
        _last_step_desc = result.steps[-1].description if result.steps else "nothing yet"
        result.qa_question = (
            f"I reached the step limit ({MAX_STEPS} steps) without being able to "
            f"conclusively verify this scenario. I last saw: {_last_step_desc}. "
            f"Please check the app manually and advise whether this AC passes."
        )
        result.verdict = f"Exhausted {MAX_STEPS} steps — QA review needed"

    return result


# ── Public entry point ────────────────────────────────────────────────────────

def verify_ac(
    app_url: str,
    ac_text: str,
    card_name: str,
    card_id: str = "",
    card_url: str = "",
    qa_name: str = "QA Team",
    progress_cb: "Callable[[int, str, int, str], None] | None" = None,
    qa_answers: "dict[str, str] | None" = None,
    auto_report_bugs: bool = True,
    stop_flag: "Callable[[], bool] | None" = None,
    max_scenarios: int | None = None,
) -> VerificationReport:
    """
    Verify AC scenarios for a card against the live Shopify app.

    Args:
        app_url:           Full FedEx app URL in Shopify admin
        ac_text:           Full AC markdown from the Trello card
        card_name:         Card title
        card_id:           Trello card ID — used to get dev members for bug DMs
        card_url:          Trello card URL — included in bug DM
        qa_name:           Name of QA running the verification (shown in DM)
        progress_cb:       callback(scenario_idx, scenario_title, step_num, step_desc)
        qa_answers:        {scenario_text: qa_answer} for stuck scenarios
        auto_report_bugs:  If True, automatically DM developers when a bug is found
        max_scenarios:     Cap number of scenarios tested (None = test all).
                           Simple=3, Medium=4, Complex=5. Takes the first N scenarios.

    Returns:
        VerificationReport with per-scenario results + bug_report on failures
    """
    from playwright.sync_api import sync_playwright

    if not app_url:
        app_url = get_auto_app_url()
    if not app_url:
        raise ValueError(
            "App URL required. Set STORE in the automation repo .env, "
            "or enter the URL manually."
        )
    if not config.ANTHROPIC_API_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY not set in .env")

    claude = ChatAnthropic(
        model=config.CLAUDE_SONNET_MODEL,
        api_key=config.ANTHROPIC_API_KEY,
        temperature=0.1,
        max_tokens=4096,   # 2048 caused JSON truncation → fake "partial" verdicts
    )

    report    = VerificationReport(card_name=card_name, app_url=app_url)
    scenarios = _extract_scenarios(ac_text, claude)
    total_extracted = len(scenarios)
    if max_scenarios and max_scenarios < len(scenarios):
        scenarios = scenarios[:max_scenarios]
        logger.info("SmartVerifier: capped to %d/%d scenarios for '%s' (max_scenarios=%d)",
                    len(scenarios), total_extracted, card_name, max_scenarios)
    else:
        logger.info("SmartVerifier: %d scenarios for '%s'", len(scenarios), card_name)

    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(channel="chrome", headless=False, args=_ANTI_BOT_ARGS)
            logger.debug("SmartVerifier: launched real Chrome")
        except Exception as e:
            logger.warning("Chrome not found (%s) — falling back to headless Chromium", e)
            browser = p.chromium.launch(headless=True, args=_ANTI_BOT_ARGS)

        ctx  = browser.new_context(**_auth_ctx_kwargs())
        page = ctx.new_page()

        for idx, scenario in enumerate(scenarios):
            # Check stop flag before each scenario
            if stop_flag and stop_flag():
                logger.info("SmartVerifier: stopped by user after %d scenarios", idx)
                break

            logger.info("[%d/%d] Verifying: %s", idx + 1, len(scenarios), scenario[:70])

            # ── Step 1: Ask domain expert what this scenario should do ─────────
            # This gives Claude grounded knowledge (API fields, UI behaviour,
            # expected signals) BEFORE it starts navigating — same as asking a
            # senior dev "what should I see when this works?".
            if progress_cb:
                progress_cb(idx + 1, scenario, 0, "🧠 Asking domain expert…")
            expert_insight = _ask_domain_expert(scenario, card_name, claude)
            logger.debug("Expert insight for '%s': %s", scenario[:50], expert_insight[:120])

            # ── Step 2: Gather code RAG context ──────────────────────────────
            code_ctx  = _code_context(scenario, card_name)

            # ── Step 3: Plan navigation + what to look for ───────────────────
            plan_data = _plan_scenario(scenario, app_url, code_ctx, expert_insight, claude)

            def _cb(step_num: int, desc: str, _i: int = idx, _sc: str = scenario) -> None:
                if progress_cb:
                    progress_cb(_i + 1, _sc, step_num, desc)

            qa_ans = (qa_answers or {}).get(scenario, "")

            sv = _verify_scenario(
                page=page,
                scenario=scenario,
                card_name=card_name,
                app_base=app_url,
                plan_data=plan_data,
                ctx=code_ctx,
                claude=claude,
                progress_cb=_cb,
                qa_answer=qa_ans,
                first_scenario=(idx == 0),
                expert_insight=expert_insight,
            )

            # Auto bug report — DM developer when fail/partial detected
            if auto_report_bugs and sv.status in ("fail", "partial") and card_id:
                if progress_cb:
                    progress_cb(idx + 1, scenario, MAX_STEPS, "🐛 Bug detected — notifying developer…")
                try:
                    from pipeline.bug_reporter import notify_devs_of_bug
                    steps_taken = [
                        f"{s.action}: {s.description}" for s in sv.steps
                        if s.action in ("click", "fill", "navigate", "observe")
                    ]
                    bug_result = notify_devs_of_bug(
                        card_id=card_id,
                        card_name=card_name,
                        card_url=card_url,
                        bug_description=sv.verdict,
                        scenario=scenario,
                        qa_name=qa_name,
                        verification_steps=steps_taken,
                    )
                    sv.bug_report = bug_result
                    logger.info(
                        "Bug report for '%s': sent=%s failed=%s",
                        scenario[:50], bug_result.get("sent_to"), bug_result.get("failed"),
                    )
                except Exception as e:
                    logger.warning("Bug auto-report failed: %s", e)
                    sv.bug_report = {"ok": False, "error": str(e)}

            report.scenarios.append(sv)

        ctx.close()
        browser.close()

    # Generate summary
    results_txt = "\n".join(
        f"- [{sv.status.upper()}] {sv.scenario}: {sv.verdict}"
        for sv in report.scenarios
    )
    resp = claude.invoke([HumanMessage(content=_SUMMARY_PROMPT.format(
        card_name=card_name, results=results_txt,
    ))])
    report.summary = resp.content.strip()

    return report


def reverify_failed(
    report: VerificationReport,
    app_url: str = "",
    card_id: str = "",
    card_url: str = "",
    qa_name: str = "QA Team",
    progress_cb: "Callable | None" = None,
    qa_answers: "dict[str, str] | None" = None,
    auto_report_bugs: bool = True,
    stop_flag: "Callable[[], bool] | None" = None,
) -> VerificationReport:
    """
    Re-run only the failed/partial/qa_needed scenarios from an existing report.

    Args:
        report:            Existing VerificationReport from a previous verify_ac() call
        app_url:           Full FedEx app URL (defaults to report.app_url if blank)
        card_id:           Trello card ID — used for bug DMs
        card_url:          Trello card URL — included in bug DM
        qa_name:           Name of QA running the re-verification
        progress_cb:       callback(scenario_idx, scenario_title, step_num, step_desc)
        qa_answers:        {scenario_text: qa_answer} for stuck scenarios
        auto_report_bugs:  If True, automatically DM developers when a bug is found

    Returns:
        Updated VerificationReport — previously-passing scenarios kept as-is,
        re-run results merged in, and summary regenerated.
    """
    from playwright.sync_api import sync_playwright

    # Filter to only failed scenarios
    failed_scenarios = [
        sv for sv in report.scenarios
        if sv.status in ("fail", "partial", "qa_needed")
    ]

    # Nothing to re-verify — return report unchanged
    if not failed_scenarios:
        return report

    # Resolve app URL
    _app_url = (app_url or report.app_url or "").strip()
    if not _app_url:
        _app_url = get_auto_app_url()
    if not _app_url:
        raise ValueError(
            "App URL required. Set STORE in the automation repo .env, "
            "or enter the URL manually."
        )
    if not config.ANTHROPIC_API_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY not set in .env")

    claude = ChatAnthropic(
        model=config.CLAUDE_SONNET_MODEL,
        api_key=config.ANTHROPIC_API_KEY,
        temperature=0.1,
        max_tokens=4096,   # 2048 caused JSON truncation → fake "partial" verdicts
    )

    card_name = report.card_name
    failed_count = len(failed_scenarios)
    logger.info(
        "reverify_failed: re-running %d scenario(s) for '%s'",
        failed_count, card_name,
    )

    # Build a lookup for in-place replacement
    # Maps scenario text → index in report.scenarios
    scenario_index: dict[str, int] = {
        sv.scenario: i for i, sv in enumerate(report.scenarios)
    }

    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(channel="chrome", headless=False, args=_ANTI_BOT_ARGS)
            logger.debug("reverify_failed: launched real Chrome")
        except Exception as e:
            logger.warning("Chrome not found (%s) — falling back to headless Chromium", e)
            browser = p.chromium.launch(headless=True, args=_ANTI_BOT_ARGS)

        ctx  = browser.new_context(**_auth_ctx_kwargs())
        page = ctx.new_page()

        for idx, old_sv in enumerate(failed_scenarios):
            # Honour stop button
            if stop_flag and stop_flag():
                logger.info("reverify_failed: stop requested after %d/%d scenarios", idx, failed_count)
                break

            scenario = old_sv.scenario
            logger.info(
                "[%d/%d] Re-verifying: %s", idx + 1, failed_count, scenario[:70]
            )

            if progress_cb:
                progress_cb(idx + 1, scenario, 0, "🧠 Asking domain expert…")
            expert_insight = _ask_domain_expert(scenario, card_name, claude)

            code_ctx  = _code_context(scenario, card_name)
            plan_data = _plan_scenario(scenario, _app_url, code_ctx, expert_insight, claude)

            def _cb(step_num: int, desc: str, _i: int = idx, _sc: str = scenario) -> None:
                if progress_cb:
                    progress_cb(_i + 1, _sc, step_num, desc)

            qa_ans = (qa_answers or {}).get(scenario, "")

            new_sv = _verify_scenario(
                page=page,
                scenario=scenario,
                card_name=card_name,
                app_base=_app_url,
                plan_data=plan_data,
                ctx=code_ctx,
                claude=claude,
                progress_cb=_cb,
                qa_answer=qa_ans,
                expert_insight=expert_insight,
                first_scenario=(idx == 0),
            )

            # Auto bug report on fail/partial
            if auto_report_bugs and new_sv.status in ("fail", "partial") and card_id:
                if progress_cb:
                    progress_cb(idx + 1, scenario, MAX_STEPS, "🐛 Bug detected — notifying developer…")
                try:
                    from pipeline.bug_reporter import notify_devs_of_bug
                    steps_taken = [
                        f"{s.action}: {s.description}" for s in new_sv.steps
                        if s.action in ("click", "fill", "navigate", "observe")
                    ]
                    bug_result = notify_devs_of_bug(
                        card_id=card_id,
                        card_name=card_name,
                        card_url=card_url,
                        bug_description=new_sv.verdict,
                        scenario=scenario,
                        qa_name=qa_name,
                        verification_steps=steps_taken,
                    )
                    new_sv.bug_report = bug_result
                    logger.info(
                        "Bug report for '%s': sent=%s failed=%s",
                        scenario[:50], bug_result.get("sent_to"), bug_result.get("failed"),
                    )
                except Exception as e:
                    logger.warning("Bug auto-report failed: %s", e)
                    new_sv.bug_report = {"ok": False, "error": str(e)}

            # Replace the old result in-place
            orig_idx = scenario_index.get(scenario)
            if orig_idx is not None:
                report.scenarios[orig_idx] = new_sv
            else:
                # Scenario not found by exact match (shouldn't happen) — append
                report.scenarios.append(new_sv)

        ctx.close()
        browser.close()

    # Re-generate summary with Claude
    results_txt = "\n".join(
        f"- [{sv.status.upper()}] {sv.scenario}: {sv.verdict}"
        for sv in report.scenarios
    )
    resp = claude.invoke([HumanMessage(content=_SUMMARY_PROMPT.format(
        card_name=card_name, results=results_txt,
    ))])
    report.summary = resp.content.strip()

    return report
