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
AUTH_JSON = Path(config.AUTOMATION_CODEBASE_PATH) / "auth.json" if config.AUTOMATION_CODEBASE_PATH else None

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
        "name": "Settings — Full Page Overview",
        "path": "/settings/0",
        # No more_settings_heading — captures everything visible on settings page before any expansion
        "description": (
            "FedEx Shopify App — Settings Page (top-level view)\n"
            "Sections visible on the Settings page without expanding:\n"
            "  1. Account Settings — FedEx account number, subscription plan\n"
            "  2. Subscription Settings — current plan (Starter $19 / Premium $49 / Enterprise $99)\n"
            "  3. Packaging Settings — packing method, weight & dimensions unit (has 'more settings')\n"
            "  4. Default product dimensions and weight — length, width, height, default weight (gm)\n"
            "  5. Documents/Labels Settings — label format, size (has 'more settings')\n"
            "  6. International Shipping Settings — ETD, commercial invoice (has 'more settings')\n"
            "  7. Return Settings — return label configuration (has 'more settings')\n"
            "  8. Additional Services — dry ice, signature, Saturday delivery, alcohol, battery, insurance\n"
            "  9. Rate Settings — carrier services, rate display, fallback rate\n"
            " 10. Shop Contact Details — shipper from-address for labels\n"
            " 11. Notifications — email alerts for shipment/delivery events\n"
        ),
    },
    # ── Settings sections with 'more settings' buttons (live capture of expanded content) ──
    {
        "name": "Settings — Packaging Configuration (expanded)",
        "path": "/settings/0",
        "more_settings_heading": "Packaging Settings",
        "description": (
            "Packaging Settings — expanded view (click 'more settings' to reveal)."
            "\n• Use Volumetric Weight For Package Generation (checkbox)"
            "\n  Formula: L×W×H ÷ 139 (inches) or ÷ 5000 (cm)"
            "\n• Max Weight Per Package (lbs)"
            "\n• Add Additional Weight To All Packages"
            "\n• Do You Stack Products In Boxes?"
            "\n• For FedEx Freight: Freight Length, Width, Height (in)"
            "\n• FedEx Boxes table: Envelope, Pak, Small, Medium, Large, Extra Large, 10kg, 25kg"
            "\n• Custom Boxes: Name, Inner/Outer dimensions, Empty weight, Max weight"
            "\n• Button: Restore FedEx Boxes"
        ),
    },
    {
        "name": "Settings — Documents & Labels (expanded)",
        "path": "/settings/0",
        "more_settings_heading": "Documents/Labels Settings",
        "description": (
            "Documents/Labels Settings — expanded view (click 'more settings' to reveal)."
            "\n• Label Format: PDF / ZPL / EPL / PNG"
            "\n• Label Stock Size: 4x6 / 4x8 / Letter (8.5x11)"
            "\n• Doc Tab: LEADING DOC_TAB (top) / TRAILING DOC_TAB (bottom) — thermal printers only"
            "\n• Number of Label Copies"
            "\n• Auto-print vs manual download"
        ),
    },
    {
        "name": "Settings — International Shipping (expanded)",
        "path": "/settings/0",
        "more_settings_heading": "International Shipping Settings",
        "description": (
            "International Shipping Settings — expanded view (click 'more settings' to reveal)."
            "\n• FedEx Electronic Trade Documents (ETD) — enable/disable"
            "\n• Commercial Invoice — auto-generate for international shipments"
            "\n• Customer Signature / Letter Head — mandatory for ETD in certain countries"
            "\n• Purpose of Shipment: SOLD / GIFT / SAMPLE / REPAIR_AND_RETURN / PERSONAL_EFFECTS / NOT_SOLD"
            "\n• Terms of Sale: DDP / DDU / EXW / FCA / CPT / CIP / DAT / DAP"
            "\n• Duties Payment: SENDER / RECIPIENT / THIRD_PARTY"
            "\n• TIN Type: Business National / Business State / Personal State etc."
            "\n• USMCA certificate of origin options"
        ),
    },
    {
        "name": "Settings — Return Settings (expanded)",
        "path": "/settings/0",
        "more_settings_heading": "Return Settings",
        "description": (
            "Return Settings — expanded view (click 'more settings' to reveal)."
            "\n• Enable Return Labels"
            "\n• Return Label packaging type"
            "\n• Return signature option"
            "\n• Return carrier service selection"
            "\n• rmaAssociation — link return to original tracking number"
        ),
    },
    # ── Account Settings — capture Add Account form ──
    {
        "name": "Settings — Account Add Account Form",
        "path": "/settings/0",
        "click_btn": "Add Account",   # click this button to reveal the add-account form
        "description": (
            "Account Settings — Add Account form (revealed by clicking 'Add Account' button)."
            "\n• FedEx Account Number"
            "\n• Account Name"
            "\n• API Key (OAuth client ID from developer.fedex.com)"
            "\n• API Secret (OAuth client secret)"
            "\n• Ship To Countries — restrict this account to specific destination countries"
            "\n• Account type: Primary or Secondary"
            "\n• FedEx Freight Account Number (optional, for LTL freight)"
            "\n• SmartPost Hub ID (for FedEx Ground Economy)"
            "\n• Test Mode toggle"
        ),
    },
    # ── Inline-only settings sections (fully visible in full page capture, no expansion needed) ──
    {
        "name": "Settings — Additional Services",
        "path": None,   # visible in full page, no more settings button — inline description only
        "description": (
            "Additional Services — visible on settings page without expanding."
            "\n• FedEx One Rate® — enable flat-rate shipping with FedEx packaging"
            "\n• Dry Ice — enable + set weight per package (KG); Express services only"
            "\n• Signature Options: No Signature / Indirect / Direct / Adult Signature Required"
            "\n• Saturday Delivery — adds SATURDAY_DELIVERY special service"
            "\n• Hold at Location: FedEx Office / Walgreens / Dollar General / FedEx OnSite / Ship Center"
            "\n• Alcohol Shipping — LICENSEE or CONSUMER recipient type"
            "\n• Battery Shipping — Lithium Ion / Lithium Metal; contained/packed/standalone"
            "\n• Third Party Insurance — declared value or percentage of product price"
        ),
    },
    {
        "name": "Settings — Rate Settings",
        "path": None,   # visible in full page, no more settings button — inline description only
        "description": (
            "Rate Settings — visible on settings page without expanding."
            "\n• Enable/disable individual FedEx carrier services for checkout"
            "\n• Display name override per service"
            "\n• Markup: flat amount ($) or percentage (%) per service"
            "\n• Free shipping threshold"
            "\n• Rate request mode: Live rates or Flat rate"
            "\n• Show transit days / delivery date / Saturday delivery indicator at checkout"
            "\n• Fallback rate — shown if FedEx API returns no rates"
            "\n• Display Estimated Delivery Time (if available) — buffer hours field"
        ),
    },
    {
        "name": "Settings — Shop Contact Details",
        "path": None,   # visible in full page — inline description only
        "description": (
            "Shop Contact Details — shipper From address used on all FedEx labels."
            "\n• First Name, Last Name, Company Name, MID Code"
            "\n• Phone Number (required by FedEx)"
            "\n• Email Address"
            "\n• Street Address Line 1 & 2, City, State, ZIP, Country"
            "\n• At least one of First+Last Name OR Company Name is mandatory"
        ),
    },
    {
        "name": "Settings — Notifications",
        "path": None,   # visible in full page — inline description only
        "description": (
            "Notifications — email alerts configuration."
            "\n• Shipment notification to customer: on label generation / pickup / delivery"
            "\n• Send copy to merchant email"
            "\n• FedEx notification types: ON_DELIVERY / ON_ESTIMATED_DELIVERY / ON_EXCEPTION / ON_PICKUP / ON_SHIPMENT"
            "\n• Notification language options"
            "\n• Recipient types: SHIPPER / RECIPIENT / BROKER / OTHER"
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
        "path": None,   # side dock drawer — no dedicated URL, opened by clicking an order from /shopify
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
        "path": None,   # modal triggered from Shipping page — no dedicated URL
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
        "path": "/pickup",
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
        "path": "/rateslog",
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
    {
        "name": "FAQ — Frequently Asked Questions",
        "path": "/faq",
        "description": (
            "In-app FAQ page covering common merchant questions about the FedEx Shopify app. "
            "Topics covered: rate display setup, label printing, return labels, "
            "special services configuration, account setup, troubleshooting."
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
                headless=False,   # must be False — Shopify detects headless and serves login page
                args=launch_args,
            )
        except Exception:
            logger.debug("Chrome channel unavailable, falling back to Chromium")
            browser = pw.chromium.launch(headless=False, args=launch_args)

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

            # ── Warm-up: load Shopify admin first so session cookies activate ──
            logger.info("  Warm-up: loading Shopify admin…")
            page.goto(
                f"https://admin.shopify.com/store/{STORE}",
                wait_until="domcontentloaded",
                timeout=60_000,
            )
            page.wait_for_timeout(3000)

            # ── Navigate to app once so sidebar loads ─────────────────────────
            page.goto(f"{BASE_URL}/shopify", wait_until="domcontentloaded", timeout=60_000)
            page.wait_for_timeout(4000)

            # FrameLocator — same pattern used in BasePage / AppFrameHelper in tests
            app_frame = page.frame_locator('iframe[name="app-iframe"]')
            app_main  = app_frame.locator("#AppFrameMain")

            import re

            current_path: str | None = None  # track last navigated path to avoid duplicate navigations

            for section in sections:
                name = section["name"]
                path = section.get("path")

                # Skip modal/drawer sections — no dedicated URL, covered by inline descriptions
                if path is None:
                    logger.info("  Skipping (modal, no URL): %s", name)
                    continue

                route = path.lstrip("/")
                url   = f"{BASE_URL}/{route}"

                logger.info("  Navigating to: %s", name)
                try:
                    # Only navigate if we're not already on this path
                    # (avoids re-clicking same sidebar link for settings sub-sections)
                    if path != current_path:
                        nav_link = page.locator(f'a[href*="/apps/{APP_SLUG}/{route}"]').first
                        try:
                            nav_link.click(force=True, timeout=3000)
                        except Exception:
                            page.goto(url, wait_until="domcontentloaded", timeout=60_000)

                        # Wait for #AppFrameMain to have content — same as test suite
                        try:
                            app_main.wait_for(state="visible", timeout=15_000)
                        except Exception:
                            pass
                        page.wait_for_timeout(4000)  # let React finish rendering
                        current_path = path

                    # For Account Settings: click a specific button (e.g. "Add Account") to reveal form
                    click_btn = section.get("click_btn")
                    if click_btn:
                        try:
                            btn = app_frame.locator("button").filter(has_text=click_btn).first
                            btn.click(timeout=5000)
                            page.wait_for_timeout(2000)
                            logger.info("    Clicked '%s' button", click_btn)
                        except Exception as be:
                            logger.debug("    Could not click '%s': %s", click_btn, be)

                    # For Settings sections: click 'more settings' — navigates to a new sub-page
                    # (not inline expansion). Capture the new page, then go back to /settings.
                    more_heading = section.get("more_settings_heading")
                    navigated_away = False
                    if more_heading:
                        try:
                            heading_loc = app_frame.locator(f':text-is("{more_heading}")').first
                            container   = heading_loc.locator("xpath=ancestor::div[4]")
                            more_btn    = container.locator("button").filter(has_text="more settings").first
                            more_btn.click(timeout=5000)
                            page.wait_for_timeout(3000)   # wait for sub-page to load
                            navigated_away = True
                            logger.info("    Clicked 'more settings' for %s → sub-page loaded", more_heading)
                        except Exception as me:
                            logger.debug("    No 'more settings' button for %s: %s", more_heading, me)

                    # Capture full #AppFrameMain (whether on settings page or sub-page)
                    captured = ""
                    try:
                        captured = app_main.inner_text(timeout=10_000)
                    except Exception:
                        try:
                            captured = app_frame.locator("body").inner_text(timeout=8_000)
                        except Exception:
                            pass

                    # If we navigated into a sub-page, click the Settings sidebar link to go back
                    if navigated_away:
                        try:
                            settings_link = page.locator(f'a[href*="/apps/{APP_SLUG}/settings"]').first
                            settings_link.click(force=True, timeout=5000)
                            page.wait_for_timeout(3000)
                        except Exception:
                            page.goto(f"{BASE_URL}/settings/0", wait_until="domcontentloaded", timeout=30_000)
                            page.wait_for_timeout(3000)
                        current_path = None   # force re-check on next iteration

                    captured = re.sub(r'\n{4,}', '\n\n', captured)
                    captured = re.sub(r' {3,}', '  ', captured)
                    captured = captured.strip()[:8000]

                    if captured and len(captured) > 150:
                        docs.append(Document(
                            page_content=(
                                f"App Section: {name}\n"
                                f"URL: {url}\n\n"
                                f"[Live captured UI content]\n"
                                f"{captured}"
                            ),
                            metadata={
                                "source": "app_navigation_live",
                                "source_type": "app",
                                "section": name,
                                "url": url,
                            },
                        ))
                        logger.info("    ✓ Captured %d chars from %s", len(captured), name)
                    else:
                        logger.info(
                            "    ⚠ Little/no content from %s (%d chars)",
                            name, len(captured),
                        )

                    page.wait_for_timeout(800)

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
                "source_type": "app",
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
                "source_type": "app",
                "section": item["name"],
                "type": "structured_knowledge",
            },
        ))

    # ── 2. Load manually-captured content (from interactive_capture.py) ─────
    captured_json = Path(__file__).parent / "captured_app_content.json"
    manual_count = 0
    if captured_json.exists():
        try:
            import json as _json
            with open(captured_json) as f:
                manual_captures = _json.load(f)
            for item in manual_captures:
                all_docs.append(Document(
                    page_content=(
                        f"App Section: {item['name']}\n\n"
                        f"[Manually captured UI content]\n"
                        f"{item['content']}"
                    ),
                    metadata={
                        "source": "app_navigation_manual",
                        "source_type": "app",
                        "section": item["name"],
                        "type": "manual_capture",
                    },
                ))
                manual_count += 1
            logger.info("Loaded %d manually-captured sections from %s", manual_count, captured_json.name)
        except Exception as e:
            logger.warning("Failed to load captured_app_content.json: %s", e)

    # ── 3. Live browser capture (best effort) ─────────────────────────────
    if AUTH_JSON is not None:
        live_docs = _capture_page_via_browser(_APP_SECTIONS)
        all_docs.extend(live_docs)
    else:
        live_docs = []
        logger.warning("AUTOMATION_CODEBASE_PATH is not set — skipping live app browser capture.")
    logger.info(
        "App knowledge: %d structured + %d manual + %d live-captured docs",
        len(_APP_SECTIONS) + len(_INLINE_KNOWLEDGE), manual_count, len(live_docs),
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
