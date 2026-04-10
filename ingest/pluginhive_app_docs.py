"""
PluginHive FedEx Shopify App — Official Documentation Loader

Full content from the official master setup guide:
https://www.pluginhive.com/set-up-shopify-fedex-rates-labels-tracking-app/

Single page only — no recursive scraping.
"""
from __future__ import annotations
import logging

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

import config

logger = logging.getLogger(__name__)

_SOURCE_URL = "https://www.pluginhive.com/set-up-shopify-fedex-rates-labels-tracking-app/"

_ARTICLES = [
    {
        "title": "FedEx Shopify App — Installation, Plans and Account Setup",
        "section": "setup",
        "content": """
How to Set Up the FedEx Shopify App (PH Ship, Rate, and Track)

INSTALLATION:
Navigate to Shopify Settings → Apps and sales channels → Shopify App Store.
Search for "PH Ship, Rate, and Track" and click Install.

SUBSCRIPTION PLANS:
- Starter Plan ($19/30 days): 100,000 Rates API calls, 5,000 labels/month
- Premium Plan ($49/30 days): 300,000 Rates API calls, 12,000 labels/month
- Enterprise Plan ($99/30 days): 500,000 Rates API calls, 25,000 labels/month
- Custom Plan: for merchants exceeding 25,000 labels monthly

Click "Approve" on the subscription confirmation page.
Complete App Installation: enter email and phone number, click "Get Started" to start setup wizard.

FEDEX ACCOUNT INTEGRATION — Two methods:

1. REST API (Recommended):
   Accept FedEx End User License Agreement.
   Enter account details EXACTLY as registered with FedEx:
   - Account Name, Account Number
   - First Name, Last Name, Company Name
   - Phone Number, Email Address
   - Complete street address, Country/Region, City, State, ZIP Code
   Select validation method: OTP via SMS/Phone/Email, Invoice validation, or Help Desk confirmation.
   Complete verification and click "Finish."

2. WebServices / SOAP API (Being Discontinued):
   Enter account details as registered with FedEx.
   Follow FedEx Web Services Permissions prompts, click "Finish."
   WARNING: "FedEx WebServices (SOAP API) will be discontinued and will no longer be
   supported by FedEx starting from June 2026."

IMPORTANT POSTAL CODE NOTE:
Postal code format must match EXACTLY for these countries:
Argentina, Brunei, Canada, Ireland, Kazakhstan, Malta, Netherlands, Peru,
Somalia, United Kingdom, Swaziland.

After integration, the app automatically retrieves required FedEx details for
displaying rates, printing labels, and generating tracking numbers.

SHOP CONTACT DETAILS:
Edit in App Settings → Shop Contact Details:
- First Name, Last Name, Company Name, MID Code
Note: "Any one of First & Last Names OR Company Name is mandatory to ship with FedEx."

MULTIPLE FEDEX ACCOUNTS:
Navigate to Settings → Account Details → Add Account.
Set "Ship To Countries" for each account.
If Order Destination Country doesn't match account conditions, the MAIN account is used.
Useful for multi-warehouse operations with separate rates per account.
""",
    },
    {
        "title": "FedEx Shopify App — Address Verification (Shipper and Customer)",
        "section": "address",
        "content": """
Address Verification in the FedEx Shopify App

SHIPPER ADDRESS SETUP:
Verify ship-from address: Shopify Settings → Location.
Add multiple locations and designate one as "Default" for processing shipments.
CRITICAL: "FedEx does not recognize special characters other than the English language."
Avoid non-English characters in ALL addresses.

CUSTOMER ADDRESS VALIDATION:
FedEx Address Validation confirms whether customer addresses are residential or commercial.
Check availability: Account Settings → Account Health → shows "Active" if enabled.

If FedEx Address Validation is NOT available on your account:
Navigate to App Settings → Additional Settings → Address Classification Settings.
Enable FedEx Address Classification and manually choose Residential or Commercial.

Recommendation: "To get the most accurate rates based on your customer's address,
enable the Address Validation service for your FedEx account."

MULTIPLE WAREHOUSES:
Add warehouse locations: Shopify Settings → Locations → Add location.
View them in app: Settings → Locations.
Select desired warehouse when processing individual orders.
Each warehouse can have its own FedEx account with independent rates.
""",
    },
    {
        "title": "FedEx Shopify App — Product Configuration (Weight, Dimensions, International)",
        "section": "products_basic",
        "content": """
Product Configuration in the FedEx Shopify App

WEIGHT AND DIMENSIONS (Required):
Add product weight: Shopify → Products → Shipping tab.
Add dimensions: app's Products section.
Verify units match your shipper's address location (time zone and measurement settings).

For FedEx Freight services: DEFAULT DIMENSIONS are mandatory.
Configure in Packaging Settings → More Settings.

PRICING AND INVENTORY:
Add product prices: Shopify Store → Products → Pricing tab.
Verify inventory: Inventory tab, ensure stock is available for your store location(s).

INTERNATIONAL SHIPMENTS — Additional required fields:
Fill in under the Shipping tab:
- HS Tariff Code (mandatory)
- Country Of Manufacture (mandatory)
"Product names should not contain special characters.
An alternative option is to update the Customs description without a special character."
Minimum declared value: $1 per product for all international shipments.
Configure minimum value: App Settings → International Shipping Settings → More Settings
→ Product And Shipping Information.

DELIVERY CONFIRMATION WITH SIGNATURE:
Global setting: App Settings → Additional Services → FedEx® Delivery Signature.
Per-product: Products settings → click product → Shipping Details → select confirmation option.
Signature options:
- ADULT — adult 21+ must sign (required for alcohol)
- DIRECT — adult must be present
- INDIRECT — adult or neighbor can sign
- SERVICE_DEFAULT — use FedEx service default
- NO_SIGNATURE_REQUIRED
- AS_PER_THE_GENERAL_SETTINGS — inherit global setting

SHIPPING INSURANCE / DECLARED VALUE:
Set Declared Value per product: Products → Shipping Details.
For insurance: Additional Services → Third Party Insurance Settings
→ enable "Is Third Party Insurance required for Forward Shipments?"
Insurance calculation methods:
- Declared Value of Product: uses product's declared value as insurance amount
- Percentage of Product Price: uses specified percentage of product price

BULK PRODUCT IMPORT / EXPORT:
Export CSV: Products → Export
Import updated CSV: Products → Import → Add Files → Upload File

Modifiable CSV fields:
1. Dimensions
2. Dimension Units (MANDATORY when updating dimensions)
3. Signature
4. Is Alcohol
5. Is Dry Ice Needed
6. Is this Product Pre-Packed

Valid Dimension Unit values: in (Inches), cm (CentiMeters), m (Meters), ft (Feet)
Valid Signature option types:
  ADULT, DIRECT, INDIRECT, SERVICE_DEFAULT, NO_SIGNATURE_REQUIRED, AS_PER_THE_GENERAL_SETTINGS
Valid Is Alcohol / Is Dry Ice Needed / Is Pre-Packed values:
  true, false, TRUE, FALSE
""",
    },
    {
        "title": "FedEx Shopify App — Special Product Types (Dry Ice, Battery, Alcohol, Hazardous)",
        "section": "products_special",
        "content": """
Special Product Configuration in the FedEx Shopify App

Navigate to Products settings → select product → Supplementary Details for all below.

DRY ICE / PERISHABLE PRODUCTS:
Enable: "Is Dry Ice Needed" checkbox in Supplementary Details.
Then enter: required dry ice weight for the product.
IMPORTANT: Dry Ice is only valid for FedEx Express services (NOT Ground).
Must be set at BOTH product level (here) AND at shipment level in API request.
Regulatory: dry ice shipments require hazmat documentation.
In API: adds specialServicesRequested.specialServiceTypes=['DRY_ICE'] + dryIceWeight
to both rate and label requests.

BATTERY PRODUCTS:
Enable: "Is Battery" checkbox in Supplementary Details.
Then configure ALL THREE fields:
1. Battery Material Type: Lithium Ion OR Lithium Metal
2. Packaging Type: contained in equipment / packed with equipment / standalone
3. Regulatory Subtype
In API: adds dangerousGoodsDetail to label request.

ALCOHOL / WINE PRODUCTS:
Enable: "Is Alcohol" checkbox in Supplementary Details.
Then choose recipient type: Consumer OR Licensee.
Note: alcohol requires Adult Signature automatically.
In API: adds alcoholDetail.alcoholRecipientType = LICENSEE or CONSUMER.
Cannot mix alcohol products with non-alcohol products in same package.

HAZARDOUS / DANGEROUS GOODS:
Enable: "Is Dangerous Goods" checkbox in Supplementary Details.
Then select the specific goods type from dropdown.
Configure packaging: Auto Setting → Special Services → specify type and packaging material.

PRODUCTS WITH SIGNATURE REQUIREMENT:
Enable in Supplementary Details under Shipping Details.
Or set globally in Additional Services → FedEx® Delivery Signature.

SHIPPING INSURANCE PER PRODUCT:
Set Declared Value under Products → Shipping Details.
Default is retail price; edit to set custom declared value.
"Declared value represents maximum liability of FedEx in case of any loss, damage,
delay, or misdelivery of the shipment."
""",
    },
    {
        "title": "FedEx Shopify App — Packaging Configuration (All 7 Methods)",
        "section": "packaging",
        "content": """
Packaging Configuration in the FedEx Shopify App — 7 Methods

Navigate to Packaging Settings to configure.

1. PREPACKED PRODUCTS:
   For products with their own boxes (electronics, shoes, etc.).
   Products settings → select product → Supplementary Details
   → enable "Is this product pre-packed?"
   The product's own dimensions and weight are used directly.

2. CUSTOM BOX PACKING (YOUR PACKAGING):
   Packaging Settings → Box Packing → Add Custom Box.
   Required fields:
   - Box name
   - Inner dimensions (L × W × H)
   - Outer dimensions (L × W × H)
   - Empty box weight
   - Max box weight capacity
   The app automatically matches products that fit inside each box.

3. FEDEX FLAT-RATE BOXES:
   Full list of available FedEx-provided boxes:
   - FedEx Envelope
   - FedEx Pak
   - FedEx Small Box
   - FedEx Medium Box
   - FedEx Large Box
   - FedEx Extra Large Box
   - FedEx 10 Kg Box
   - FedEx 25 Kg Box
   - FedEx Tube
   - FedEx Standard Freight Box
   Enable in Packaging Settings → Box Packing.
   Button: "Restore FedEx Boxes" to reset to defaults.

4. WEIGHT-BASED PACKING:
   Select Weight Based Packing in Packaging Settings.
   Set Max Weight (maximum weight per package).
   When product weight exceeds limit → items distributed into additional packages.
   Enable "Add Additional Weight To All Packages" (for packaging material weight):
   - Constant: add fixed Constant Weight value to every package
   - Percentage: add Percentage Of Package Weight to be Added

5. VOLUMETRIC WEIGHT-BASED PACKING:
   Enable "Use Volumetric Weight For Package Generation" in Packaging Settings.
   Formula: L × W × H ÷ 139 (inches) OR ÷ 5000 (cm)
   Uses max(actual weight, volumetric weight) for accurate FedEx rate calculations.
   For space-consuming items with low actual weight.

6. PACK ITEMS INDIVIDUALLY:
   Select "Pack Items Individually" in Packaging Settings.
   Each product ships in its own separate package.
   "Do You Stack Products In Boxes?" — controls whether multiple products share a box.

7. DANGEROUS GOODS PACKAGING:
   Navigate to Auto Setting → Special Services.
   Specify:
   - Dry Ice: Maximum dry ice weight per package (KG)
   - Dangerous Goods: Type and packaging material for hazardous goods

DEFAULT DIMENSIONS (for products without dimensions set):
Configure in Packaging Settings → More Settings:
- Default Length, Width, Height (with unit: in / cm / ft / mt)
- Default weight for products (gm)

FEDEX FREIGHT MINIMUM DIMENSIONS:
Configure in Packaging Settings → More Settings:
- Freight Length, Width, Height (in)
Required for LTL freight services.
""",
    },
    {
        "title": "FedEx Shopify App — Shipping Services (Domestic, International, Freight, Saturday)",
        "section": "shipping_services",
        "content": """
FedEx Shipping Services Configuration — App Settings → Rate Settings

By default ALL services are enabled. Disable services not required.
For each service: add Adjustment value (fixed $) or Adjustment (%) for shipping charges.

DOMESTIC SERVICES:
- FedEx First Overnight
- FedEx Priority Overnight
- FedEx Standard Overnight
- FedEx 2Day A.M.
- FedEx 2Day
- FedEx Express Saver
- FedEx Ground
- FedEx Home Delivery
- FedEx Ground Economy

INTERNATIONAL SERVICES:
- FedEx International Economy
- FedEx International First
- FedEx International Priority
- FedEx Europe First International Priority
- FedEx International Ground

FEDEX FREIGHT SERVICES:
First enable Freight: App settings → Account Settings.
Required fields to add:
- Freight Account Number
- Billing Address
- Default Freight Class
- Physical Package Type

Then enable individual freight services in Rate Settings → Carrier Services:
- FedEx 1Day Freight
- FedEx 2Day Freight
- FedEx 3Day Freight
- FedEx International Economy Freight
- FedEx International Priority Freight
- FedEx Freight
- FedEx National Freight
- FedEx Freight Priority
- FedEx Freight Economy
- FedEx First Freight

SATURDAY DELIVERY:
Enable: App settings → Account Settings → FedEx Saturday Delivery.
Then select Saturday services in Rate Settings → Carrier Service.
Surcharges:
- $16 per package: Priority Overnight, 2Day, First Overnight
- $16 per package: International Priority Express, International Priority
- $210 per package: Freight services

ESTIMATED DELIVERY TIME:
Navigate to: App Settings → Rates Settings → Display Estimated Delivery Time for FedEx Services (If Available).
Tick the checkbox to show estimated delivery date/time on Shopify checkout.
"Add Buffer Time For Estimated Delivery in Hours" — enter hours to extend displayed estimate.
Example: 24 hours buffer = adds 1 extra day to the displayed delivery estimate.

FALLBACK RATES (when FedEx API unavailable):
App Settings → Rate Settings → Fallback Services.
Configure flat rates SEPARATELY for:
- Domestic fallback
- International fallback
- Freight fallback

COLLECT ON DELIVERY (COD):
Navigate to: Accounts Settings → COD Options.
FedEx COD collects invoice value from recipient via Cash/Cheque/Demand Draft/Pays Order.
Payment returned to merchant within 10 working days.

COD Type options:
- ANY            — accept all listed collection methods
- CASH           — cash only (recommended for domestic India orders)
- COMPANY CHECK
- GUARANTEED FUNDS
- PERSONAL CHECK

For domestic India orders: opt for "Cash".
For international orders: select appropriate type.
If "ANY" selected: all listed collection methods accepted.

DELAYED SHIPPING (ship later):
App Settings → Documents/Labels Settings → Change Shipment Date.
Select 0-5 days delay from today.

RATE DISPLAY OPTIONS:
App Settings → Rate Settings:
- Display Rates for: Business and Residential Addresses / Business Only / Residential Only
- Shipment Cut Off Time (e.g., 23:30)
- Display Rates: Without tax / With tax
- Display Published/Account Rates: Account Rates / Published Rates

FEDEX ONE RATE:
Enable FedEx One Rate® (Additional Services → FedEx One Rate).
Flat-rate shipping using FedEx-branded packaging.
packagingType = FEDEX_ENVELOPE, FEDEX_PAK, FEDEX_BOX, FEDEX_TUBE, etc.
No dimensional weight calculation — price depends on destination zone only.
""",
    },
    {
        "title": "FedEx Shopify App — Checkout Rate Display Setup",
        "section": "checkout_rates",
        "content": """
Displaying Live FedEx Shipping Rates on Shopify Checkout

PREREQUISITES:
1. Enable Carrier-Calculated Shipping on Shopify store (requires Basic plan or higher)
2. Enable "Ship Rate & Track" app in Shopify Shipping Profile

VERIFICATION:
Visit your Shopify store → add product to cart → proceed to checkout.
After entering shipping address → FedEx rates appear on checkout page.

RATE DISPLAY CONFIGURATION (App Settings → Rate Settings):
- Display Rates for: Business and Residential Addresses (recommended) / Business Only / Residential Only
- Shipment Cut Off Time: orders after this time are processed next day
- Display Rates: Without tax or With tax
- Display Published/Account Rates: Account Rates or Published Rates
- Display Estimated Delivery Time for FedEx Services (If Available): checkbox
- Add Buffer Time For Estimated Delivery in Hours: numeric field

CUSTOMER NOTIFICATIONS:
FedEx Notifications automatically emails customers on shipment status changes.
Supported languages: English and French.
Enable: App Settings → Notifications → Enable FedEx Notifications.

BUSINESS EMAIL (SMTP):
Send notifications from your business email:
App Settings → Notifications → SMTP Settings.
Enter your SMTP server credentials.
""",
    },
    {
        "title": "FedEx Shopify App — Label Printing (Bulk, Single, Edit, Cancel, Return)",
        "section": "labels",
        "content": """
FedEx Label Printing in the Shopify App

IMPORTANT ORDER STATUS REQUIREMENT:
Orders MUST be in "Unfulfilled" status to print labels.
CANNOT print labels for: Fulfilled, Draft, Archived orders, or any other non-Unfulfilled status.

LABEL SETTINGS SETUP (configure before printing):
App Settings → Documents/Labels Settings:
- Print Label Size options:
  - "Paper 4 x 6" — for label/thermal printers
  - "Paper 4 x 8" — for label/thermal printers
  - "Paper 8.5 x 11 Bottom Half Label" — for conventional/office printers
  - LEADING DOC_TAB — thermal printer only (doc tab at top)
  - TRAILING DOC_TAB — thermal printer only (doc tab at bottom)
- Copy quantity: maximum 5 copies per label type

BULK LABEL GENERATION (multiple orders at once):
1. Go to Shopify Order details page
2. Select multiple orders using checkboxes
3. More Actions → "Auto-Generate Labels"
4. App redirects to Shipping section
5. Under Label Generated → click "Print Documents" to batch print all labels

SINGLE ORDER LABEL WITH CUSTOM OPTIONS:
From order details → More Actions → "Generate Label"
Click "Generate Package" to create packages.

Package edit options BEFORE finalizing:
- EDIT: select shipping box and product quantities
- SPLIT: divide into multiple packages (requires single product per box)
- REMOVE: delete existing packages
- REGENERATE: recreate packaging configuration

Additional options for international shipments:
- "Add Third Party Insurance To Packages" (if applicable)
- "FedEx® Delivery Signature Options" — select from dropdown
- "Duties Payment Type" — choose who pays customs duties (Sender/Recipient/Third Party)
- "Enable ETD" — Electronic Trade Documents (replaces physical paper customs documents)

Click "Get FedEx Shipping Rates" → select a service → click "Generate Label".
From order summary → More Action → print/download documents.

LABEL CANCELLATION:
Shipping tab → Label Generated section → click order → More Actions → "Cancel Label"

RESTRICTIONS — Labels CANNOT be cancelled through the app if:
- Label was generated MORE than 24 hours ago
- It is a FedEx LTL Freight label
For these: contact your FedEx Account Representative directly.

RETURN LABELS:
Shipping → Label Generated dropdown → select "Return Order"
1. Enter return quantity
2. Select packaging type
3. Click "Refresh Rates" to get return rates
4. Click "Generate Return Label"

Configure return settings in advance: App Settings → Return Settings.
Can print return labels simultaneously with forward labels OR when customer requests later.

ALTERNATE ADDRESS ON LABEL:
App Settings → Documents/Labels Settings → More Settings
→ enable "Display Alternate Address On Label"
→ choose address from dropdown.

RESIDENTIAL ADDRESS — HIDE COMPANY NAME:
App Settings → Documents/Labels Settings → Additional Label Settings
→ disable "Display Company Name on Label for Residential Address".

DOC TAB LABELS:
App Settings → Documents/Label Settings → Print Label Size → select LEADING or TRAILING DOC_TAB.
Works ONLY with thermal printers.
LEADING = doc tab at top of label.
TRAILING = doc tab at bottom of label.
""",
    },
    {
        "title": "FedEx Shopify App — International Shipping, Customs and Documents",
        "section": "international",
        "content": """
International Shipping Configuration in the FedEx Shopify App

CUSTOMS DOCUMENTS PRINTED BY APP:
- FedEx shipping label
- Commercial Invoice
- Tax Invoice
- Packing Slip

ETD (ELECTRONIC TRADE DOCUMENTS):
Enable "Enable ETD" during label generation for international shipments.
ETD eliminates need to physically attach paper customs documents to package.

PRO FORMA INVOICE:
App Settings → International Shipping Settings → More Settings
→ Additional Customs Documents → enable "Generate Pro Forma Invoice"

USMCA CERTIFICATE OF ORIGIN (US-Mexico-Canada trade):
App Settings → International Shipping Settings → More Settings
→ Additional Customs Documents → enable "Generate Certificate Of Origin"
Configure:
- USMCA Certifier Specification: Exporter, Producer, or Importer
- USMCA Importer Specification: UNKNOWN, VARIOUS, or specific importer name
- USMCA Producer Specification: SAME_AS_EXPORTER, VARIOUS, or AVAILABLE_UPON_REQUEST

DUTIES PAYMENT TYPE (set during label generation):
- SENDER — seller pays customs duties
- RECIPIENT — buyer pays customs duties (DDU)
- THIRD_PARTY — designated third party pays duties
- COLLECT — collect duties from recipient

TERMS OF SALE (INCOTERMS):
DDP = Delivered Duty Paid (seller pays), DDU = Delivered Duty Unpaid (buyer pays)
Also: EXW, FCA, CPT, CIP, DAT, DAP

INTERNATIONAL PRODUCT REQUIREMENTS:
- HS Tariff Code: mandatory, add under product Shipping tab
- Country of Manufacture: mandatory
- Product names: must NOT contain special characters
  (use Customs Description field as workaround)
- Minimum declared value: $1 per product
  Configure: App Settings → International Shipping Settings → More Settings
  → Product And Shipping Information

TAX IDENTIFICATION NUMBER (TIN):
Settings → Account → Tax Identification Number
Set TIN Type from dropdown:
- Business National: tax number at country level
- Business State: tax number at local/state level
- Business Union: tax number across trade zones (e.g., IOSS number in EU)
- Personal State: individual local/state tax number
- Personal Union: individual national tax number

LABEL TROUBLESHOOTING FOR INTERNATIONAL:
1. Verify print settings in app match your printer
2. Ensure printer is properly configured for selected label size
3. Check that all products have declared value of at least $1
4. Verify no special characters in product names
""",
    },
    {
        "title": "FedEx Shopify App — Pickup Scheduling and Shipment Tracking",
        "section": "pickup_tracking",
        "content": """
Pickup Scheduling and Tracking in the FedEx Shopify App

REQUESTING A PICKUP:
1. Navigate to Shipping tab in app settings
2. Select orders using checkboxes
3. Click "Request Pickup"

The Pickup page displays:
- Current pickup status
- Pickup number
- Location
- Order number(s)

Click the Pickup Number to view full Pickup Details.

TRACKING SHIPMENTS:
Once FedEx agent picks up the packages:
1. Navigate to Shipping → Label Generated section
2. Click the Label Generated dropdown
3. Select "Track Shipment"
4. View full tracking details

CUSTOMER TRACKING NOTIFICATIONS:
FedEx automatically emails customers when shipment status changes.
Enable: App Settings → Notifications → Enable FedEx Notifications.
Languages: English and French.
Can send from business email via SMTP settings.
""",
    },
    {
        "title": "FedEx Shopify App — FAQ (All Questions and Answers)",
        "section": "faq",
        "content": """
FedEx Shopify App — Complete FAQ

Q: What customs documents does the app print?
A: FedEx shipping label, Commercial Invoice, Tax Invoice, Packing Slip.

Q: How do I handle insurance for expensive products?
A: Use FedEx Declared Value — set per product in Products section (default is retail price).
   Edit to set custom declared value.
   "Declared value = maximum liability of FedEx in case of any loss, damage, delay, or misdelivery."
   Alternatively: Additional Services → Third Party Insurance Settings.

Q: Can I print return labels?
A: Yes. Navigate to Shipping → Label Generated dropdown → Return Order.
   Configure return settings first: App Settings → Return Settings.
   Can print with forward labels simultaneously OR when customer requests.

Q: How do customers get notified about shipment status?
A: Enable FedEx Notifications: App Settings → Notifications → Enable FedEx Notifications.
   Customers get automatic email updates when shipment status changes (English and French).

Q: How do I send tracking updates from my business email?
A: App Settings → Notifications → SMTP Settings. Enter your SMTP server credentials.

Q: Can I use multiple FedEx accounts?
A: Yes. Settings → Account Details → Add Account.
   Set "Ship To Countries" per account.
   If destination country doesn't match account conditions, the main account is used.

Q: How do I ship from multiple warehouses?
A: Shopify Settings → Locations → Add location.
   View in app: Settings → Locations.
   Select desired warehouse when processing orders.

Q: Why aren't international shipping labels printing?
A: Check these 4 things:
   1. Print settings in app match your printer type
   2. Printer is properly configured for selected label size
   3. All products have declared value of at least $1
   4. No special characters in product names (use Customs Description field)

Q: Where do I add Tax Identification Numbers?
A: Settings → Account → Tax Identification Number → select TIN Type.
   Types: Business National, Business State, Business Union, Personal State, Personal Union.

Q: How do I print Doc Tab labels?
A: App Settings → Documents/Label Settings → Print Label Size → select LEADING or TRAILING DOC_TAB.
   REQUIRES thermal printer. LEADING = tab at top, TRAILING = tab at bottom.

Q: How do I show a different address on the shipping label?
A: App Settings → Documents/Labels Settings → More Settings
   → enable "Display Alternate Address On Label" → choose address from dropdown.

Q: How do I generate Pro Forma Invoices?
A: App Settings → International Shipping Settings → More Settings
   → Additional Customs Documents → enable "Generate Pro Forma Invoice".

Q: How do I generate USMCA Certificates of Origin?
A: App Settings → International Shipping Settings → More Settings
   → Additional Customs Documents → enable "Generate Certificate Of Origin".
   Configure Certifier, Importer, and Producer specifications.

Q: How do I hide company name on residential address labels?
A: App Settings → Documents/Labels Settings → Additional Label Settings
   → disable "Display Company Name on Label for Residential Address".

Q: How do I set fallback rates if FedEx API goes down?
A: App Settings → Rate Settings → Fallback Services.
   Configure flat-rate backups SEPARATELY for Domestic, International, and Freight.

Q: How do I generate labels today but ship tomorrow or later?
A: App Settings → Documents/Labels Settings → Change Shipment Date.
   Select 0-5 days delay.

Q: Why isn't FedEx Address Validation available on my account?
A: Check Account Settings → Account Health.
   If unavailable: use App Settings → Additional Settings → Address Classification Settings
   → manually choose Residential or Commercial classification.

Q: I can't cancel a label — why?
A: Two reasons labels cannot be cancelled through the app:
   1. Label was generated more than 24 hours ago
   2. It is a FedEx LTL Freight label
   Contact your FedEx Account Representative for these cancellations.

Q: How does Saturday Delivery pricing work?
A: Surcharges apply:
   - $16 per package for: Priority Overnight, 2Day, First Overnight
   - $16 per package for: International Priority Express, International Priority
   - $210 per package for Freight services

Q: What order statuses support label generation?
A: ONLY "Unfulfilled" orders. Cannot print labels for:
   Fulfilled, Draft, Archived, or any other status.
""",
    },
]


def load_pluginhive_app_docs() -> list[Document]:
    """
    Returns chunked Documents from the official PluginHive FedEx app setup guide.
    Complete content extracted from:
    https://www.pluginhive.com/set-up-shopify-fedex-rates-labels-tracking-app/
    """
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=config.CHUNK_SIZE,
        chunk_overlap=config.CHUNK_OVERLAP,
    )

    all_docs: list[Document] = []

    for article in _ARTICLES:
        chunks = splitter.split_text(article["content"].strip())
        for i, chunk in enumerate(chunks):
            all_docs.append(
                Document(
                    page_content=chunk,
                    metadata={
                        "source": "pluginhive_app_docs",
                        "source_url": _SOURCE_URL,
                        "type": "product_documentation",
                        "title": article["title"],
                        "section": article["section"],
                        "chunk_index": i,
                    },
                )
            )

    logger.info(
        "PluginHive app docs: %d articles → %d chunks", len(_ARTICLES), len(all_docs)
    )
    return all_docs
