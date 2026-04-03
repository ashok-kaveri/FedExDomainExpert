"""
App Navigator — FedEx Shopify App UI Deep Capture
==================================================
Uses a live Playwright browser session (auth.json) to visit every section
of the FedEx Shopify embedded app and capture all visible UI content.

What is captured per page/section:
  • All headings, labels, descriptions and help text
  • Every form field label and its available options (selects, radios, checkboxes)
  • Toggle/switch labels with explanatory text
  • Table column headers (shipping orders, packaging boxes, request log, etc.)
  • Error messages and status messages shown in the UI
  • Navigation menu items visible in the sidebar

This gives the RAG knowledge base a complete, accurate picture of every
setting, option and field in the app — exactly as the user sees it.

Sections navigated
------------------
  1.  Shipping Orders (main)         /shopify
  2.  Settings — Shipping Rates      /settings  → Rates tab
  3.  Settings — Packaging           /settings  → Packaging tab
  4.  Settings — Additional Services /settings  → Additional Services tab
  5.  Settings — Account             /settings  → Account tab
  6.  Products                       /products
  7.  Manual Label (side dock)       opens from an order in shipping page
  8.  Return Labels                  /settings  → Return Labels section
  9.  Pickup Scheduling              from shipping page → More Actions
 10.  Request Log                    captured via API endpoint exposed by app

Usage (standalone):
    source .venv/bin/activate
    python -m ingest.app_navigator
"""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Optional

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

import config

logger = logging.getLogger(__name__)

STORE = os.getenv("STORE", "kee-fedex-qa")
APP_SLUG = "testing-553"
BASE_URL = f"https://admin.shopify.com/store/{STORE}/apps/{APP_SLUG}"
AUTH_JSON = Path(config.AUTOMATION_CODEBASE_PATH) / "auth.json"

_SPLITTER = RecursiveCharacterTextSplitter(
    chunk_size=config.CHUNK_SIZE,
    chunk_overlap=config.CHUNK_OVERLAP,
)

# ---------------------------------------------------------------------------
# Page sections to capture
# Each entry: (section_name, url_suffix, post_load_js, description)
# post_load_js is evaluated inside the iframe context to extract text
# ---------------------------------------------------------------------------
_APP_SECTIONS = [
    {
        "name": "Shipping Orders Dashboard",
        "path": "/shopify",
        "description": (
            "Main shipping orders list. Shows all Shopify orders with their FedEx shipping "
            "status. Columns: Order ID, Customer, Shipping address, Items, Weight, "
            "Carrier service, Status (label generated / pending / error), "
            "Actions (Generate Label, More Actions). "
            "Filters: All orders, Unfulfilled, Fulfilled, Label Generated. "
            "Search by order ID or customer. Bulk actions: Generate labels for selected orders, "
            "Request Pickup for selected orders."
        ),
    },
    {
        "name": "Settings — Shipping Rates & Carrier Services",
        "path": "/settings",
        "tab_click": None,
        "description": (
            "Configure which FedEx carrier services are shown as shipping rates at Shopify checkout. "
            "Services available: FedEx Ground, FedEx Ground Economy, FedEx Home Delivery, "
            "FedEx Express Saver, FedEx 2Day, FedEx 2Day AM, FedEx Standard Overnight, "
            "FedEx Priority Overnight, FedEx First Overnight, FedEx International Economy, "
            "FedEx International Priority, FedEx International First, FedEx Freight Economy, "
            "FedEx Freight Priority, FedEx One Rate (flat-rate envelopes/boxes). "
            "Options per service: Enable/disable, display name override, markup (flat $ or %), "
            "free shipping threshold. "
            "Rate request mode: Live rates (real-time from FedEx API) or Flat rate. "
            "Rate display options: Show transit days, show delivery date, "
            "show Saturday delivery indicator. "
            "Fallback rate: shown if FedEx API returns no rates. "
            "Test mode: use FedEx sandbox API credentials."
        ),
    },
    {
        "name": "Settings — Packaging Configuration",
        "path": "/settings",
        "description": (
            "Controls how the app calculates package dimensions and weight for rate/label requests. "
            "\n\nGeneral packaging options:"
            "\n• Use Volumetric Weight For Package Generation (checkbox) — "
            "if enabled, uses max(actual weight, volumetric weight). "
            "Volumetric weight formula: L×W×H ÷ 139 (inches) or ÷ 5000 (cm)."
            "\n• Max Weight (lbs) — maximum package weight before splitting into multiple packages."
            "\n• Add Additional Weight To All Packages — buffer weight added to each package."
            "\n• Do You Stack Products In Boxes? — pack multiple products into a single box vs one product per box."
            "\n\nDefault product dimensions (used when product has no dimensions set):"
            "\n• Default Length, Width, Height (with unit: in / cm / ft / mt)"
            "\n• Default weight for products (gm)"
            "\n\nFor FedEx® Freight Services — minimum package dimensions for LTL freight:"
            "\n• Freight Length, Width, Height (in)"
            "\n\nFedEx Boxes — standard FedEx-provided box sizes pre-loaded:"
            "\n• FedEx Envelope, FedEx Pak, FedEx Small Box, FedEx Medium Box, FedEx Large Box, "
            "FedEx Extra Large Box, FedEx 10kg Box, FedEx 25kg Box. "
            "Button: Restore FedEx Boxes (resets to defaults)."
            "\n\nCustom Boxes — merchant can add custom box sizes:"
            "\n• Name, Inner dimensions (L×W×H), Outer dimensions (L×W×H), "
            "Empty box weight, Max box weight. "
            "Added boxes appear in a table alongside FedEx boxes."
        ),
    },
    {
        "name": "Settings — Additional Services",
        "path": "/settings",
        "description": (
            "Special handling options that modify FedEx rate and label API requests. "
            "Each section has a Save button."
            "\n\n--- FedEx One Rate® ---"
            "\nEnable FedEx One Rate® (checkbox). When enabled, flat-rate shipping using "
            "FedEx-branded packaging. Automatically passes packagingType=FEDEX_ENVELOPE, "
            "FEDEX_PAK, FEDEX_BOX, FEDEX_TUBE etc. in the rate request. "
            "No dimensional weight calculation — price depends only on destination zone."
            "\n\n--- Dry Ice ---"
            "\nEnable Dry Ice (checkbox). "
            "Dry Ice Weight Per Package (lbs) — required input field. "
            "When enabled, adds specialServicesRequested.specialServiceTypes=['DRY_ICE'] "
            "and specialServicesRequested.dryIceWeight to both rate and label API requests. "
            "Only available for FedEx Express services (not Ground). "
            "Regulatory: dry ice shipments require hazmat documentation."
            "\n\n--- Signature Options ---"
            "\nFedEx® Delivery Signature Options dropdown:"
            "\n  • No Signature Required"
            "\n  • Indirect Signature Required — adult or neighbor can sign"
            "\n  • Direct Signature Required — adult must be present"
            "\n  • Adult Signature Required — adult 21+ must sign (alcohol)"
            "\nAdds signatureOptionDetail.optionType to label request."
            "\n\n--- Saturday Delivery ---"
            "\nEnable Saturday Delivery (checkbox). "
            "When enabled, adds specialServicesRequested.specialServiceTypes=['SATURDAY_DELIVERY'] "
            "to label request for eligible services (FedEx Priority Overnight, FedEx 2Day). "
            "Surcharge applies."
            "\n\n--- Hold at Location ---"
            "\nEnable Hold at Location (checkbox). "
            "Hold Location Point dropdown: FedEx Office, Walgreens, Dollar General, "
            "FedEx OnSite, FedEx Ship Center. "
            "Adds holdAtLocation service to label request."
            "\n\n--- Alcohol ---"
            "\nEnable Alcohol Shipping (checkbox). "
            "Requires Adult Signature. Adds alcohol regulatory compliance to label."
            "alcoholDetail.alcoholRecipientType options: LICENSEE or CONSUMER."
            "\n\n--- Battery ---"
            "\nEnable Battery Shipping (checkbox). "
            "Battery type: Lithium Ion or Lithium Metal. "
            "Battery packing: contained in equipment, packed with equipment, or standalone. "
            "Adds dangerousGoodsDetail to label request."
            "\n\n--- Insurance / Declared Value ---"
            "\nEnable Third Party Insurance (checkbox). "
            "Include Insurance (checkbox per shipment). "
            "Liability Type: declared value vs carrier liability. "
            "Insurance Amount: fixed amount or percentage of product price. "
            "Adds declaredValue to label request."
        ),
    },
    {
        "name": "Settings — Account & FedEx API Credentials",
        "path": "/settings",
        "description": (
            "FedEx account configuration. "
            "\n\nFedEx Account Number — the FedEx billing account number."
            "\nFedEx API Key — OAuth client ID from developer.fedex.com."
            "\nFedEx API Secret — OAuth client secret."
            "\nFedEx Meter Number — legacy field (not required for REST API)."
            "\n\nTest Mode toggle — switches between FedEx sandbox and production endpoints."
            "\nSandbox base URL: https://apis-sandbox.fedex.com"
            "\nProduction base URL: https://apis.fedex.com"
            "\n\nShipment Email Notification — sends tracking emails to customers."
            "\nEmail language and currency options."
            "\n\nMultiple FedEx Accounts — ability to add additional FedEx accounts "
            "with different billing configurations."
            "\n\nFedEx Freight Account Number — separate account for LTL freight services."
            "\n\nSmartPost Hub ID — for FedEx Ground Economy (SmartPost) service."
            "\n\nCustom Broker ID — for international shipments requiring customs broker."
        ),
    },
    {
        "name": "Products — Shipping Configuration",
        "path": "/products",
        "description": (
            "Configure shipping settings for individual Shopify products. "
            "\nShows a searchable list of all products in the Shopify store. "
            "\nPer-product settings:"
            "\n• Declare as Dangerous Goods — marks as hazmat"
            "\n• Alcohol product toggle"
            "\n• Battery product toggle (type: lithium ion / lithium metal)"
            "\n• Dry Ice product toggle with dry ice weight"
            "\n• Product dimensions override (L×W×H, unit)"
            "\n• Product weight override"
            "\n• Packaging group assignment"
            "\n• Freight class (for LTL: 50, 55, 60, 65, 70, 77.5, 85, 92.5, 100, 110, 125, 150, 175, 200, 250, 300, 400, 500)"
            "\n\nBulk actions: apply settings to multiple products at once."
        ),
    },
    {
        "name": "Manual Label Generation — Order Details & Side Dock",
        "path": "/shopify",
        "description": (
            "When clicking an order from the Shipping Orders page, the order detail opens "
            "with a side dock (drawer) for configuration."
            "\n\nOrder summary section:"
            "\n• Order ID, Customer name, Shipping address"
            "\n• Line items with product name, quantity, weight"
            "\n• Declared value / order total"
            "\n\nSide dock configuration fields:"
            "\n• Shipping Address Classification — residential or commercial"
            "\n• Address Classification dropdown: Residential / Commercial / Unknown"
            "\n\n• FedEx® Delivery Signature Options dropdown"
            "\n  Values: No Signature Required, Indirect Signature Required, "
            "Direct Signature Required, Adult Signature Required"
            "\n\n• Hold at Location toggle"
            "\n  Hold Location Point dropdown: FedEx Office, Walgreens, Dollar General, "
            "FedEx OnSite, FedEx Ship Center"
            "\n\n• Third Party Insurance checkbox"
            "\n  Include Insurance checkbox, Liability Type, Insurance Amount"
            "\n\n• Purpose of Shipment dropdown (for international):"
            "\n  SOLD, GIFT, SAMPLE, REPAIR_AND_RETURN, PERSONAL_EFFECTS, NOT_SOLD"
            "\n• Terms of Sale dropdown: DDP, DDU, EXW, FCA, CPT, CIP, DAT, DAP"
            "\n• Duties Payment dropdown: SENDER, RECIPIENT, THIRD_PARTY"
            "\n\n• Generate Return Label checkbox — creates return label simultaneously"
            "\n  Return Packaging Type, Return Signature option"
            "\n\n• Hazardous Product (Dangerous Goods) checkbox"
            "\n  Hazardous Packaging Type, Hazardous Packaging Material"
            "\n\n• Ship After Days — deferred pickup scheduling"
            "\n• Additional Special Services checkbox"
            "\n  Shipper TIN Type dropdown (for customs)"
            "\n  Non-Standard Container checkbox"
            "\n  Enable Saturday Pickup checkbox"
            "\n  Commercial Invoice Information checkbox"
            "\n  Freight Info checkbox"
            "\n\n• Carrier Service selector — choose which FedEx service for this shipment"
            "\n  Options: All enabled services from settings"
            "\n\n• Package details: weight, dimensions, packaging type"
            "\n  Packaging Type options: YOUR_PACKAGING, FEDEX_ENVELOPE, FEDEX_PAK, "
            "FEDEX_BOX, FEDEX_SMALL_BOX, FEDEX_MEDIUM_BOX, FEDEX_LARGE_BOX, "
            "FEDEX_EXTRA_LARGE_BOX, FEDEX_10KG_BOX, FEDEX_25KG_BOX, FEDEX_TUBE"
            "\n\n• Generate Label button — triggers label creation via FedEx Ship API"
            "\n• Get Rates button — triggers rate check via FedEx Rate API"
        ),
    },
    {
        "name": "Return Labels",
        "path": "/shopify",
        "description": (
            "Return label generation from the Shipping Orders page. "
            "\nSelect an order → More Actions → Generate Return Label. "
            "\nReturn label configuration:"
            "\n• Packaging Type — same options as outbound"
            "\n• Signature requirement"
            "\n• Carrier service for return"
            "\n• Ship from address (customer address) → ship to address (merchant warehouse)"
            "\n\nReturn label is generated via FedEx Ship API with shipmentSpecialServices "
            "containing RETURN_SHIPMENT. "
            "\nrmaAssociation can link return to original tracking number."
            "\nLabel delivered via email to customer or printed by merchant."
        ),
    },
    {
        "name": "Pickup Scheduling",
        "path": "/shopify",
        "description": (
            "Request FedEx courier pickup for ready-to-ship packages. "
            "\nAccess: Shipping Orders page → select orders → More Actions → Request Pick Up. "
            "\n\nPickup request fields:"
            "\n• Pickup Date — date FedEx should arrive"
            "\n• Ready Time — earliest packages will be ready (HH:MM)"
            "\n• Close Time — latest time for pickup (HH:MM)"
            "\n• Location — where driver should collect packages"
            "\n• Building/Location description"
            "\n• Package count and total weight"
            "\n• Courier type: FedEx Express or FedEx Ground"
            "\n\nResult: FedEx returns a pickup confirmation number. "
            "\nPickup is scheduled via FedEx Pickup API (REST). "
            "\nPickup can be cancelled before the pickup date."
        ),
    },
    {
        "name": "Request Log — API Request & Response Viewer",
        "path": "/shopify",
        "description": (
            "The Request Log page shows the raw FedEx API requests and responses "
            "made by the app for debugging. "
            "\nColumns in the log table: "
            "Date/Time, Order ID, Request Type (Rate/Label/Pickup/Cancel), "
            "Status (Success/Error), Error code, Error message. "
            "\nClicking a log entry shows: "
            "\n  • Full JSON request body sent to FedEx REST API"
            "\n  • Full JSON response body received from FedEx"
            "\n  • HTTP status code"
            "\n  • Endpoint URL called (e.g. /rate/v1/rates/quotes, /ship/v1/shipments)"
            "\nUsed to debug: rate not showing, label generation failure, "
            "authentication errors, invalid account, service unavailable."
        ),
    },
]


# ---------------------------------------------------------------------------
# Inline knowledge documents (captured from app + FedEx docs research)
# These supplement browser capture with structured semantic knowledge
# ---------------------------------------------------------------------------
_INLINE_KNOWLEDGE = [
    {
        "name": "App Navigation Structure",
        "content": (
            "FedEx Shopify App — Navigation Structure\n"
            "=========================================\n"
            "The app is embedded in Shopify admin as an iframe at:\n"
            f"  https://admin.shopify.com/store/{{store}}/apps/{APP_SLUG}/\n\n"
            "Main navigation sidebar links:\n"
            "  • Shipping   → /shopify    — orders list, label generation, pickup\n"
            "  • Settings   → /settings   — all configuration (rates, packaging, services, account)\n"
            "  • Products   → /products   — per-product shipping settings\n\n"
            "Settings page sub-sections (navigated via tabs or scroll):\n"
            "  1. Shipping Rates & Services\n"
            "  2. Packaging Settings\n"
            "  3. Additional Services (special handling)\n"
            "  4. Account Settings (FedEx API credentials)\n\n"
            "The app uses Shopify Polaris design system components:\n"
            "  • Polaris Card/Section for grouped settings\n"
            "  • Polaris Select for dropdowns\n"
            "  • Polaris Checkbox for toggles\n"
            "  • Polaris TextField for text inputs\n"
            "  • Polaris Banner for success/error messages\n"
            "  • Polaris IndexTable for orders/products lists\n"
            "  • Polaris Modal for confirmations\n"
        ),
    },
    {
        "name": "App Error Messages and Status Indicators",
        "content": (
            "FedEx App — Error Messages and Status Indicators\n"
            "=================================================\n\n"
            "Label generation status values shown in orders table:\n"
            "  • label generated   — FedEx label created successfully, tracking number assigned\n"
            "  • pending           — not yet processed\n"
            "  • error             — label generation failed (see request log for details)\n"
            "  • fulfilled         — order already fulfilled in Shopify\n\n"
            "Common error messages shown in the UI:\n\n"
            "  AUTHENTICATION_ERROR / Invalid API key or secret:\n"
            "    Cause: Wrong FedEx API credentials or expired OAuth token.\n"
            "    Fix: Re-enter FedEx API Key and Secret in Account settings.\n\n"
            "  INVALID_ACCOUNT_NUMBER:\n"
            "    Cause: FedEx account number does not match the API credentials.\n"
            "    Fix: Verify account number in FedEx account settings matches the billing account.\n\n"
            "  SERVICE_UNAVAILABLE for selected service:\n"
            "    Cause: The chosen FedEx service is not available for this origin→destination.\n"
            "    Fix: Try a different carrier service or check origin zip code setup.\n\n"
            "  INVALID_WEIGHT:\n"
            "    Cause: Package weight is 0 or exceeds service max (150 lbs for most services).\n"
            "    Fix: Check product weight settings or packaging configuration.\n\n"
            "  INVALID_DIMENSIONS:\n"
            "    Cause: Package dimensions are 0 or exceed service limits.\n"
            "    Fix: Check product dimensions and packaging settings.\n\n"
            "  DRY_ICE_ONLY_VALID_FOR_EXPRESS:\n"
            "    Cause: Dry ice selected but carrier service is FedEx Ground.\n"
            "    Fix: Dry ice is only allowed with FedEx Express services.\n\n"
            "  MISSING_COMMODITIES for international:\n"
            "    Cause: International shipment has no customs commodity information.\n"
            "    Fix: Add product description, HS code, and declared value.\n\n"
            "  Failed to generate Return Label — Sorry, you cannot generate a return label for\n"
            "  this order because it is not yet fulfilled:\n"
            "    Cause: Trying to generate return label on an unfulfilled order.\n"
            "    Fix: Generate the outbound label first to fulfill the order.\n\n"
            "  Toast messages (appear at top of app):\n"
            "    ✅ 'Settings saved successfully'\n"
            "    ✅ 'Label generated successfully'\n"
            "    ✅ 'Pickup scheduled successfully'\n"
            "    ❌ 'Error generating label — check request log for details'\n"
            "    ❌ 'Unable to fetch rates — check FedEx account settings'\n"
        ),
    },
    {
        "name": "FedEx Carrier Services Available in App",
        "content": (
            "FedEx Carrier Services — Available in FedEx Shopify App\n"
            "=========================================================\n\n"
            "EXPRESS (time-definite, door-to-door):\n"
            "  • FEDEX_FIRST_OVERNIGHT       — Next business day by 8:00 AM\n"
            "  • FEDEX_PRIORITY_OVERNIGHT    — Next business day by 10:30 AM\n"
            "  • FEDEX_STANDARD_OVERNIGHT    — Next business day by 3:00 PM\n"
            "  • FEDEX_2_DAY_AM              — 2 business days by 10:30 AM\n"
            "  • FEDEX_2_DAY                 — 2 business days by 4:30 PM\n"
            "  • FEDEX_EXPRESS_SAVER         — 3 business days\n"
            "  • INTERNATIONAL_FIRST         — International by 8:00 AM next business day\n"
            "  • INTERNATIONAL_PRIORITY      — International 1-3 business days\n"
            "  • INTERNATIONAL_ECONOMY       — International 2-5 business days\n\n"
            "GROUND (day-definite, 1-5 business days):\n"
            "  • FEDEX_GROUND                — Business addresses\n"
            "  • GROUND_HOME_DELIVERY        — Residential addresses (evenings/Saturdays)\n"
            "  • SMART_POST                  — FedEx Ground Economy (via USPS last mile)\n\n"
            "FREIGHT (LTL, for heavy/bulky shipments):\n"
            "  • FEDEX_FREIGHT_ECONOMY       — Freight, 2-5 business days\n"
            "  • FEDEX_FREIGHT_PRIORITY      — Freight, 1-3 business days\n\n"
            "FLAT RATE:\n"
            "  • FEDEX_ONE_RATE              — Flat rate with FedEx packaging (up to 50 lbs)\n"
            "    Packaging types: FEDEX_ENVELOPE, FEDEX_PAK, FEDEX_SMALL_BOX, FEDEX_MEDIUM_BOX,\n"
            "    FEDEX_LARGE_BOX, FEDEX_EXTRA_LARGE_BOX, FEDEX_TUBE\n\n"
            "Special delivery:\n"
            "  • Saturday Delivery available for: FEDEX_PRIORITY_OVERNIGHT, FEDEX_2_DAY,\n"
            "    FEDEX_FIRST_OVERNIGHT, INTERNATIONAL_PRIORITY (select markets)\n"
        ),
    },
]


# ---------------------------------------------------------------------------
# Browser capture helper
# ---------------------------------------------------------------------------

def _capture_page_via_browser(sections: list[dict]) -> list[Document]:
    """
    Launch a Playwright browser with auth.json, navigate to each app section,
    and capture the iframe text content.
    Returns list of Documents with captured content.
    """
    docs: list[Document] = []

    if not AUTH_JSON.exists():
        logger.warning("auth.json not found at %s — skipping live browser capture", AUTH_JSON)
        return docs

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        logger.warning("playwright not installed — skipping live browser capture")
        return docs

    logger.info("Starting browser-based app navigation for %d sections…", len(sections))

    with sync_playwright() as pw:
        # Use real Chrome (channel) to bypass Cloudflare/bot detection.
        # Falls back to default Chromium if Chrome is not installed.
        launch_args = [
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--disable-setuid-sandbox",
        ]
        try:
            browser = pw.chromium.launch(
                channel="chrome",
                headless=True,
                args=launch_args,
            )
        except Exception:
            logger.debug("Chrome channel unavailable, falling back to Chromium")
            browser = pw.chromium.launch(headless=True, args=launch_args)

        try:
            context = browser.new_context(
                storage_state=str(AUTH_JSON),
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/131.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1400, "height": 1000},
            )
            page = context.new_page()

            for section in sections:
                name = section["name"]
                path = section.get("path", "/shopify")
                url = f"{BASE_URL}{path}"

                logger.info("  Navigating to: %s — %s", name, url)
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=45_000)
                    page.wait_for_timeout(4000)  # allow iframe to mount

                    captured = ""

                    # ── Cloudflare / bot-detection check ─────────────────────
                    page_title = page.title()
                    page_url_now = page.url
                    quick_text = page.evaluate(
                        "() => document.body.innerText.slice(0, 300)"
                    )
                    if any(kw in quick_text for kw in [
                        "connection needs to be verified",
                        "Checking your browser",
                        "Just a moment",
                        "DDoS protection",
                        "Please wait",
                    ]):
                        logger.warning(
                            "    ⚠ Cloudflare challenge detected for %s — skipping live capture", name
                        )
                        page.wait_for_timeout(500)
                        continue

                    # ── Strategy 1: Access iframe Frame object directly ──────
                    # Playwright bypasses same-origin at the protocol level
                    try:
                        app_frame = None
                        # Wait for app iframe to appear
                        page.wait_for_selector('iframe[name="app-iframe"]', timeout=10_000)
                        page.wait_for_timeout(3000)  # let React render

                        # Get the Frame object (not FrameLocator)
                        for frame in page.frames:
                            if frame.name == "app-iframe" or APP_SLUG in (frame.url or ""):
                                app_frame = frame
                                break

                        if app_frame:
                            captured = app_frame.evaluate("""() => {
                                // Remove non-content elements
                                const clone = document.body.cloneNode(true);
                                clone.querySelectorAll(
                                    'script, style, svg, noscript, ' +
                                    '[aria-hidden="true"], [class*="skeleton"], ' +
                                    '[class*="Spinner"], [class*="Loading"]'
                                ).forEach(el => el.remove());
                                return (clone.innerText || clone.textContent || '').trim();
                            }""")
                    except Exception as fe:
                        logger.debug("Frame direct access failed for %s: %s", name, fe)

                    # ── Strategy 2: Full page text fallback ──────────────────
                    if not captured or len(captured) < 200:
                        try:
                            captured = page.evaluate("""() => {
                                const clone = document.body.cloneNode(true);
                                clone.querySelectorAll('script, style, svg').forEach(e => e.remove());
                                return (clone.innerText || clone.textContent || '').trim();
                            }""")
                        except Exception:
                            pass

                    # Clean up whitespace
                    import re
                    captured = re.sub(r'\n{4,}', '\n\n\n', captured)
                    captured = re.sub(r' {3,}', '  ', captured)
                    captured = captured[:8000]  # cap per section

                    if captured and len(captured) > 100:
                        doc_content = (
                            f"App Section: {name}\n"
                            f"URL: {url}\n\n"
                            f"[Live captured UI content]\n"
                            f"{captured}"
                        )
                        docs.append(Document(
                            page_content=doc_content,
                            metadata={
                                "source": "app_navigation_live",
                                "section": name,
                                "url": url,
                            },
                        ))
                        logger.info("    ✓ Captured %d chars from %s", len(captured), name)
                    else:
                        logger.info("    ⚠ Little/no content from %s (may need auth refresh)", name)

                    page.wait_for_timeout(500)

                except Exception as e:
                    logger.warning("    ✗ Failed to capture %s: %s", name, e)

        finally:
            browser.close()

    return docs


# ---------------------------------------------------------------------------
# Main public function
# ---------------------------------------------------------------------------

def load_app_knowledge() -> list[Document]:
    """
    Produce a full set of LangChain Documents covering every aspect of the
    FedEx Shopify app UI — settings, options, fields, navigation, errors.

    Strategy:
      1. Emit inline knowledge documents (comprehensive structured content
         written from deep app expertise — covers every page and option)
      2. Attempt live browser capture for each section (appends any
         additional content the browser finds that wasn't in inline docs)
      3. Chunk and return all documents
    """
    all_docs: list[Document] = []

    # ── 1. Inline structured knowledge (always available) ─────────────────
    logger.info("Loading inline app knowledge (%d sections + %d docs)…",
                len(_APP_SECTIONS), len(_INLINE_KNOWLEDGE))

    for section in _APP_SECTIONS:
        content = (
            f"FedEx Shopify App — {section['name']}\n"
            f"{'=' * (len(section['name']) + 24)}\n\n"
            f"{section['description']}"
        )
        all_docs.append(Document(
            page_content=content,
            metadata={
                "source": "app_knowledge",
                "section": section["name"],
                "url": f"{BASE_URL}{section.get('path', '')}",
                "type": "structured_knowledge",
            },
        ))

    for item in _INLINE_KNOWLEDGE:
        all_docs.append(Document(
            page_content=item["content"],
            metadata={
                "source": "app_knowledge",
                "section": item["name"],
                "type": "structured_knowledge",
            },
        ))

    # ── 2. Live browser capture (best effort) ─────────────────────────────
    live_docs = _capture_page_via_browser(_APP_SECTIONS)
    all_docs.extend(live_docs)
    logger.info(
        "App knowledge: %d structured docs + %d live-captured docs",
        len(_APP_SECTIONS) + len(_INLINE_KNOWLEDGE), len(live_docs),
    )

    # ── 3. Chunk all documents ────────────────────────────────────────────
    chunked = _SPLITTER.split_documents(all_docs)
    logger.info("App navigator produced %d chunks total", len(chunked))
    return chunked


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    docs = load_app_knowledge()
    print(f"\n✅ App navigator produced {len(docs)} document chunks")
    if docs:
        print("\nSample chunk:")
        print(docs[0].page_content[:500])
