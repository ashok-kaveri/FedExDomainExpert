---
name: fedex-shopify-store-actions
description: Use when the user wants to perform any Shopify Admin API action on the FedEx test store — create/update/archive/delete products (simple, variable, large variant counts), create/cancel/delete/update orders (preset, custom, draft), bulk cleanup by tag, update shipping address, manage customers, update inventory (set or adjust), list fulfillments, carrier services, webhooks, metafields, collections, locations, create refunds — all via natural language. Auth is read automatically from the automation .env.
---

# Shopify Store Actions

Use this skill when the user asks to do anything with the Shopify test store via API:

- "create 3 products" / "create a variable product with 5 sizes × 5 colors × 5 fabrics"
- "list all products and give me the IDs"
- "delete the product called Red Shirt"
- "archive that product" / "set product status to draft"
- "update variant weight to 2.5kg"
- "create a domestic order" / "create an order for John Smith at 123 Main St NY"
- "create a draft order and complete it"
- "cancel order #1801" / "delete all qa-test tagged orders"
- "update the shipping address on order #1802"
- "list all unfulfilled orders" / "how many open orders are there?"
- "this product has 0 quantity, set it to 9999" / "add 50 stock to Red Shirt"
- "check if FedEx app is registered as a carrier"
- "show fulfillments for order #1800"
- "list webhooks" / "get metafields on this product"
- "create a customer called Jane Doe" / "find customer by email"
- "list all locations" / "list collections"
- "create a refund on order #1799"
- any CRUD or management action on Shopify Products, Orders, Customers, Inventory, or Store config

---

## Auth — Always Automatic

Never ask the user for credentials. Always read from the automation `.env`:

```python
import config  # FedexDomainExpert config.py
from pathlib import Path

_automation_path = (config.AUTOMATION_CODEBASE_PATH or "").strip()
_env_file = Path(_automation_path) / ".env"

env = {}
if _env_file.exists():
    for line in _env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if "=" in line and not line.startswith("#"):
            k, _, v = line.partition("=")
            env[k.strip()] = v.strip().strip("'\"")

STORE         = env.get("STORE", "")
ACCESS_TOKEN  = env.get("SHOPIFY_ACCESS_TOKEN", "")
API_VERSION   = env.get("SHOPIFY_API_VERSION", "2024-01")
BASE_URL      = f"https://{STORE}.myshopify.com/admin/api/{API_VERSION}"
HEADERS       = {"X-Shopify-Access-Token": ACCESS_TOKEN, "Content-Type": "application/json"}
```

If `STORE` or `SHOPIFY_ACCESS_TOKEN` is empty → tell the user to check `AUTOMATION_CODEBASE_PATH` in their `.env`.

---

## API Actions

### 1. List Products

```python
import requests

resp = requests.get(f"{BASE_URL}/products.json", headers=HEADERS, params={"limit": 250})
products = resp.json().get("products", [])
# Return: id, title, status, variants[].id, variants[].price for each
```

To filter by IDs:
```python
params = {"ids": "123,456,789", "limit": 250}
```

### 2. Create Product

```python
payload = {
    "product": {
        "title": "Test Product",
        "body_html": "<p>Test product for FedEx QA</p>",
        "vendor": STORE,
        "product_type": "Test",
        "status": "active",
        "published_scope": "global",
        "variants": [{
            "price": "10.00",
            "sku": "TEST-001",
            "weight": 1.5,
            "weight_unit": "kg",
            "grams": 1500,
            "requires_shipping": True,
            "inventory_management": None,
        }]
    }
}
resp = requests.post(f"{BASE_URL}/products.json", headers=HEADERS, json=payload)
product = resp.json().get("product", {})
# Return: product id, variant id, title
```

For **dangerous goods** products (dry ice / alcohol / battery) set appropriate title/type so the FedEx app can detect them.

### 3. List Orders

```python
params = {"limit": 50, "status": "any"}  # status: open | closed | cancelled | any
resp = requests.get(f"{BASE_URL}/orders.json", headers=HEADERS, params=params)
orders = resp.json().get("orders", [])
# Return: id, name (#1234), fulfillment_status, financial_status, created_at, line_items[].title
```

Filter by fulfillment status:
```python
params = {"fulfillment_status": "unfulfilled", "limit": 50, "status": "open"}
```

Filter by IDs:
```python
params = {"ids": "111,222,333", "status": "any"}
```

### 4. Create Order

Use `order_creator.py` from the project — it already handles all product types and address types:

```python
import sys
sys.path.insert(0, "/Users/madan/Documents/Fed-Ex-automation/FedexDomainExpert")
import config
from pipeline.order_creator import create_order

# product_type: "simple" | "variable" | "digital" | "dangerous"
# address_type: "default" (US) | "UK" | "CA"
order = create_order(product_type="simple", address_type="default")
# Returns: {"order_id": ..., "order_name": "#1234", "order_url": "..."}
```

Keyword → product/address mapping (same logic as AI QA Agent):

| User says | product_type | address_type |
|-----------|-------------|--------------|
| dry ice / alcohol / battery | dangerous | default |
| UK / international UK | simple | UK |
| Canada / CA | simple | CA |
| domestic / US / default | simple | default |
| variable / configurable | variable | default |
| digital / virtual | digital | default |

### 5. Get a Single Product or Order

```python
# Product by ID
resp = requests.get(f"{BASE_URL}/products/{product_id}.json", headers=HEADERS)

# Order by ID
resp = requests.get(f"{BASE_URL}/orders/{order_id}.json", headers=HEADERS)
```

### 6. Delete Product by Name

Never require the user to provide an ID. If they give a name, search first:

```python
# Step 1 — find by title (case-insensitive substring match)
resp = requests.get(f"{BASE_URL}/products.json", headers=HEADERS, params={"title": product_name, "limit": 10})
matches = resp.json().get("products", [])

# If multiple matches, list them and ask user to confirm which one
# If exactly 1 match, delete it directly
if len(matches) == 0:
    print(f"No product found with name '{product_name}'")
elif len(matches) > 1:
    print(f"Found {len(matches)} products matching '{product_name}':")
    for p in matches:
        print(f"  - ID {p['id']} | {p['title']} | {p['status']}")
    print("Please confirm which one to delete (by ID).")
else:
    product = matches[0]
    resp = requests.delete(f"{BASE_URL}/products/{product['id']}.json", headers=HEADERS)
    if resp.status_code == 200:
        print(f"Deleted: '{product['title']}' (ID {product['id']})")
    else:
        print(f"Delete failed: {resp.status_code} {resp.text}")
```

To delete by ID directly:
```python
resp = requests.delete(f"{BASE_URL}/products/{product_id}.json", headers=HEADERS)
```

---

### 7. Create Variable Product

A variable product has multiple **variants** defined by **options** (e.g. Size + Color). Each variant combination gets its own price, SKU, weight, and inventory.

```python
payload = {
    "product": {
        "title": "FedEx Test T-Shirt",
        "body_html": "<p>Variable product for FedEx QA testing</p>",
        "vendor": STORE,
        "product_type": "Apparel",
        "status": "active",
        "published_scope": "global",
        # Define the option axes
        "options": [
            {"name": "Size", "values": ["S", "M", "L", "XL"]},
            {"name": "Color", "values": ["Red", "Blue"]},
        ],
        # One variant per combination — Shopify creates all combos automatically
        # when you only specify option1/option2 values
        "variants": [
            {"option1": "S",  "option2": "Red",  "price": "15.00", "sku": "SHIRT-S-RED",  "weight": 0.3, "weight_unit": "kg", "grams": 300,  "requires_shipping": True, "inventory_management": "shopify", "inventory_quantity": 10},
            {"option1": "S",  "option2": "Blue", "price": "15.00", "sku": "SHIRT-S-BLU",  "weight": 0.3, "weight_unit": "kg", "grams": 300,  "requires_shipping": True, "inventory_management": "shopify", "inventory_quantity": 10},
            {"option1": "M",  "option2": "Red",  "price": "15.00", "sku": "SHIRT-M-RED",  "weight": 0.4, "weight_unit": "kg", "grams": 400,  "requires_shipping": True, "inventory_management": "shopify", "inventory_quantity": 10},
            {"option1": "M",  "option2": "Blue", "price": "15.00", "sku": "SHIRT-M-BLU",  "weight": 0.4, "weight_unit": "kg", "grams": 400,  "requires_shipping": True, "inventory_management": "shopify", "inventory_quantity": 10},
            {"option1": "L",  "option2": "Red",  "price": "16.00", "sku": "SHIRT-L-RED",  "weight": 0.5, "weight_unit": "kg", "grams": 500,  "requires_shipping": True, "inventory_management": "shopify", "inventory_quantity": 10},
            {"option1": "L",  "option2": "Blue", "price": "16.00", "sku": "SHIRT-L-BLU",  "weight": 0.5, "weight_unit": "kg", "grams": 500,  "requires_shipping": True, "inventory_management": "shopify", "inventory_quantity": 10},
            {"option1": "XL", "option2": "Red",  "price": "17.00", "sku": "SHIRT-XL-RED", "weight": 0.6, "weight_unit": "kg", "grams": 600,  "requires_shipping": True, "inventory_management": "shopify", "inventory_quantity": 10},
            {"option1": "XL", "option2": "Blue", "price": "17.00", "sku": "SHIRT-XL-BLU", "weight": 0.6, "weight_unit": "kg", "grams": 600,  "requires_shipping": True, "inventory_management": "shopify", "inventory_quantity": 10},
        ]
    }
}
resp = requests.post(f"{BASE_URL}/products.json", headers=HEADERS, json=payload)
product = resp.json().get("product", {})
```

**Adapt from user input:**
- If user says "variable product with sizes S, M, L" → create one option `Size` with those values, no Color option, single variant per size
- If user says "variable product with colors Red and Blue" → one option `Color`, two variants
- If user specifies a custom price/weight per variant, use those values
- If user doesn't specify options, default to Size: [S, M, L, XL]

**Response format for variable product:**
```
Created variable product "FedEx Test T-Shirt" (ID 9700000000001)
Variants:
  - S / Red  → variant ID 49100000000001 | SKU: SHIRT-S-RED  | $15.00
  - S / Blue → variant ID 49100000000002 | SKU: SHIRT-S-BLU  | $15.00
  - M / Red  → variant ID 49100000000003 | SKU: SHIRT-M-RED  | $15.00
  ... (8 total)
```

#### Large variant counts

**No hard cap in this skill.** The actual limit depends on the store's Shopify plan — this store has been tested and confirmed working at 140+ variants. Do not assert or cap unless the API itself returns an error.

When the user asks for many variants (e.g. "5 sizes × 5 colors × 5 fabrics = 125 variants"), generate them programmatically using `itertools.product` — never write them by hand.

**Strategy A — single option axis**
Use when user says "50 variants" or "100 variants" without specifying option names:

```python
import itertools, requests

title      = "FedEx Bulk Variant Test Product"
base_price = "10.00"
base_grams = 500
init_qty   = 10

count = 125  # whatever the user asks for
option_values = [str(i) for i in range(1, count + 1)]

variants = [
    {
        "option1": v,
        "price": base_price,
        "sku": f"VAR-{v.zfill(3)}",
        "grams": base_grams,
        "weight": base_grams / 1000,
        "weight_unit": "kg",
        "requires_shipping": True,
        "inventory_management": "shopify",
        "inventory_quantity": init_qty,
    }
    for v in option_values
]

payload = {
    "product": {
        "title": title,
        "vendor": STORE,
        "status": "active",
        "published_scope": "global",
        "options": [{"name": "Variant", "values": option_values}],
        "variants": variants,
    }
}
resp = requests.post(f"{BASE_URL}/products.json", headers=HEADERS, json=payload)
product = resp.json().get("product", {})
print(f"Created '{product['title']}' with {len(product['variants'])} variants")
```

**Strategy B — 2 option axes**
Use when user says "5 sizes × 5 colors" (= 25 variants) or similar:

```python
sizes  = ["XS", "S", "M", "L", "XL"]    # 5 values — adapt to user input
colors = ["Red", "Blue", "Green", "Black", "White"]  # 5 values

variants = [
    {
        "option1": size, "option2": color,
        "price": base_price,
        "sku": f"{size[:1]}-{color[:3].upper()}",
        "grams": base_grams,
        "weight": base_grams / 1000,
        "weight_unit": "kg",
        "requires_shipping": True,
        "inventory_management": "shopify",
        "inventory_quantity": init_qty,
    }
    for size, color in itertools.product(sizes, colors)
]

payload = {
    "product": {
        "title": title,
        "vendor": STORE,
        "status": "active",
        "published_scope": "global",
        "options": [
            {"name": "Size",  "values": sizes},
            {"name": "Color", "values": colors},
        ],
        "variants": variants,
    }
}
```

**Strategy C — 3 option axes (Shopify maximum is 3 axes)**
Use when user says "5 sizes × 5 colors × 5 fabrics" (= 125 variants):

```python
sizes   = ["XS", "S", "M", "L", "XL"]
colors  = ["Red", "Blue", "Green", "Black", "White"]
fabrics = ["Cotton", "Polyester", "Wool", "Linen", "Silk"]
# 5 × 5 × 5 = 125 variants

variants = [
    {
        "option1": size, "option2": color, "option3": fabric,
        "price": base_price,
        "sku": f"{size[:1]}-{color[:3].upper()}-{fabric[:3].upper()}",
        "grams": base_grams,
        "weight": base_grams / 1000,
        "weight_unit": "kg",
        "requires_shipping": True,
        "inventory_management": "shopify",
        "inventory_quantity": init_qty,
    }
    for size, color, fabric in itertools.product(sizes, colors, fabrics)
]

payload = {
    "product": {
        "title": title,
        "vendor": STORE,
        "status": "active",
        "published_scope": "global",
        "options": [
            {"name": "Size",   "values": sizes},
            {"name": "Color",  "values": colors},
            {"name": "Fabric", "values": fabrics},
        ],
        "variants": variants,
    }
}
resp = requests.post(f"{BASE_URL}/products.json", headers=HEADERS, json=payload)
product = resp.json().get("product", {})
print(f"Created '{product['title']}' with {len(product['variants'])} variants")
```

**Which strategy to pick:**

| User says | Strategy | Example |
|---|---|---|
| "N variants" (no option names) | A — numbered | `Variant: 1, 2, ... N` |
| "5 sizes × 5 colors" | B — 2 axes | 5 × 5 = 25 variants |
| "5 sizes × 5 colors × 5 fabrics" | C — 3 axes | 5 × 5 × 5 = 125 variants |
| Lists real names ("S M L XL XXL") | B or C with their values | use exact values given |

**Note:** Shopify only supports **up to 3 option axes** (option1, option2, option3). You cannot add a 4th axis. If the user asks for 4 dimensions, combine two of them into one axis (e.g. "Color-Fabric" as a single combined option).

**If the API returns an error** (e.g. 422 variant limit exceeded for the plan), report the exact error and total variant count attempted so the user knows what the store's actual limit is.

---

### 8. Create Custom Order

When the user specifies their own customer name, address, email, or product — build the order payload from what they provide. Fill in any missing fields with sensible defaults.

```python
# User-provided fields (examples — adapt to what user actually says)
first_name    = "John"
last_name     = "Smith"
email         = "john.smith@test.com"
phone         = "+11234567890"
address1      = "123 Main St"
city          = "New York"
province      = "New York"
province_code = "NY"
zip_code      = "10001"
country       = "United States"
country_code  = "US"

# Product — use a known product_id + variant_id from the store
# If user names a product by title, search for it first (see action 1)
product_id = 9614590017847   # replace with actual
variant_id = 49091417047351  # replace with actual
quantity   = 2

address = {
    "first_name": first_name, "last_name": last_name,
    "address1": address1, "city": city,
    "province": province, "province_code": province_code,
    "zip": zip_code, "country": country, "country_code": country_code,
    "phone": phone
}

payload = {
    "order": {
        "email": email,
        "financial_status": "paid",
        "customer": {"first_name": first_name, "last_name": last_name, "email": email},
        "billing_address": address,
        "shipping_address": address,
        "line_items": [{"variant_id": variant_id, "quantity": quantity}],
        "send_receipt": False,
        "send_fulfillment_receipt": False,
    }
}
resp = requests.post(f"{BASE_URL}/orders.json", headers=HEADERS, json=payload)
order = resp.json().get("order", {})
```

**Handling user input for custom orders:**
- If user says "create order for Jane Doe, 456 Elm St, Chicago IL 60601" → parse name/address from that
- If user names a product → search by title first, get variant_id, then create order
- If user gives a specific product ID/variant ID → use it directly
- If user doesn't specify quantity → default to 1
- If user doesn't specify email → generate a test email: `qa.test+{timestamp}@pluginhive.com`
- If user wants international (UK/CA) but gives a custom address → use their address, don't override

---

### 9. Update Inventory Quantity

When user says "this product has 0 qty, set it to 9999" or "update inventory of [product/variant]":

**Step 1 — find the variant's `inventory_item_id`:**
```python
# If user gives product name, search first
resp = requests.get(f"{BASE_URL}/products.json", headers=HEADERS, params={"title": product_name, "limit": 5})
product = resp.json()["products"][0]
variant = product["variants"][0]  # or let user pick if multiple variants
inventory_item_id = variant["inventory_item_id"]
variant_id = variant["id"]
```

**Step 2 — find the location ID (required by Shopify inventory API):**
```python
resp = requests.get(f"{BASE_URL}/inventory_levels.json", headers=HEADERS,
                    params={"inventory_item_ids": inventory_item_id})
levels = resp.json().get("inventory_levels", [])
location_id = levels[0]["location_id"] if levels else None

# If no inventory level exists yet, get the default location first
if not location_id:
    resp = requests.get(f"{BASE_URL}/locations.json", headers=HEADERS)
    location_id = resp.json()["locations"][0]["id"]
```

**Step 3 — set the inventory quantity:**
```python
new_qty = 9999  # or whatever the user specifies

payload = {
    "location_id": location_id,
    "inventory_item_id": inventory_item_id,
    "available": new_qty
}
resp = requests.post(f"{BASE_URL}/inventory_levels/set.json", headers=HEADERS, json=payload)
result = resp.json().get("inventory_level", {})
print(f"Inventory updated: variant {variant_id} → {result.get('available')} units at location {location_id}")
```

**If the product has multiple variants** (variable product), loop over all of them:
```python
for variant in product["variants"]:
    inventory_item_id = variant["inventory_item_id"]
    # repeat steps 2+3 for each variant
```

**Handling user input for inventory:**
- "set qty of Red Shirt to 9999" → search product by name → set all variants
- "set qty of Red Shirt size M to 500" → search product → find variant matching option "M" → set only that one
- "this product has 0 qty" — the user may be pointing at a product in context; use the last mentioned product name/ID
- Always confirm: "Updated inventory of 'Red Shirt' (variant: M / Red, ID 49100000000003) → 9999 units"

---

## 🔴 High Value — Order & Product Management

### 10. Cancel an Order

```python
order_id = 6900000000000  # from list or user input

resp = requests.post(
    f"{BASE_URL}/orders/{order_id}/cancel.json",
    headers=HEADERS,
    json={"reason": "other", "email": False}  # reason: customer|inventory|fraud|declined|other
)
order = resp.json().get("order", {})
print(f"Cancelled order {order.get('name')} — status: {order.get('cancel_reason')}")
```

If user gives order name (#1801) instead of ID, search first:
```python
resp = requests.get(f"{BASE_URL}/orders.json", headers=HEADERS, params={"name": "#1801", "status": "any"})
order_id = resp.json()["orders"][0]["id"]
```

---

### 11. Delete a Test Order

Only works on orders where `test: true` OR in a dev/test store. Use for full cleanup.

```python
resp = requests.delete(f"{BASE_URL}/orders/{order_id}.json", headers=HEADERS)
if resp.status_code == 200:
    print(f"Deleted order {order_id}")
else:
    print(f"Cannot delete: {resp.status_code} — try cancelling first")
```

---

### 12. Update Order Shipping Address

Use for address update test scenarios — no need to create a fresh order.

```python
payload = {
    "order": {
        "shipping_address": {
            "first_name": "Jane",
            "last_name": "Doe",
            "address1": "456 Elm St",
            "city": "Chicago",
            "province": "Illinois",
            "province_code": "IL",
            "zip": "60601",
            "country": "United States",
            "country_code": "US",
            "phone": "+13125550000"
        }
    }
}
resp = requests.put(f"{BASE_URL}/orders/{order_id}.json", headers=HEADERS, json=payload)
order = resp.json().get("order", {})
print(f"Updated shipping address on order {order.get('name')}")
```

---

### 13. Bulk Cancel / Delete Orders by Tag

Tag test orders as `qa-test` during creation, then bulk-clean them:

```python
# Step 1 — fetch all orders with the tag
resp = requests.get(f"{BASE_URL}/orders.json", headers=HEADERS,
                    params={"tag": "qa-test", "status": "any", "limit": 250})
orders = resp.json().get("orders", [])
print(f"Found {len(orders)} orders tagged 'qa-test'")

# Step 2 — cancel then delete each
for o in orders:
    oid = o["id"]
    if o.get("financial_status") not in ("refunded", "voided") and not o.get("cancelled_at"):
        requests.post(f"{BASE_URL}/orders/{oid}/cancel.json", headers=HEADERS, json={"email": False})
    requests.delete(f"{BASE_URL}/orders/{oid}.json", headers=HEADERS)
    print(f"  Cleaned up order {o['name']} (ID {oid})")
```

**Add `qa-test` tag when creating orders** so cleanup is easy:
```python
payload["order"]["tags"] = "qa-test"
```

---

### 14. Add / Update Tags on Orders or Products

```python
# Add tags to an order
resp = requests.put(f"{BASE_URL}/orders/{order_id}.json", headers=HEADERS,
                    json={"order": {"tags": "qa-test, fedex-label-tested, sprint-42"}})

# Add tags to a product
resp = requests.put(f"{BASE_URL}/products/{product_id}.json", headers=HEADERS,
                    json={"product": {"tags": "qa-product, dangerous-goods"}})
```

---

### 15. Update Product Variant (price, weight, SKU)

Use to change weight and test FedEx rate changes without recreating the product:

```python
payload = {
    "variant": {
        "price": "25.00",
        "weight": 2.5,
        "weight_unit": "kg",
        "grams": 2500,
        "sku": "NEW-SKU-001",
    }
}
resp = requests.put(f"{BASE_URL}/variants/{variant_id}.json", headers=HEADERS, json=payload)
variant = resp.json().get("variant", {})
print(f"Updated variant {variant_id}: price={variant.get('price')}, weight={variant.get('weight')}kg")
```

---

### 16. Archive / Draft a Product

```python
# Archive (hides from storefront, keeps data)
resp = requests.put(f"{BASE_URL}/products/{product_id}.json", headers=HEADERS,
                    json={"product": {"status": "archived"}})

# Set back to draft
resp = requests.put(f"{BASE_URL}/products/{product_id}.json", headers=HEADERS,
                    json={"product": {"status": "draft"}})

# Re-activate
resp = requests.put(f"{BASE_URL}/products/{product_id}.json", headers=HEADERS,
                    json={"product": {"status": "active"}})

print(f"Product status → {resp.json()['product']['status']}")
```

---

## 🟡 Setup & Validation

### 17. List Carrier Services

Confirms PluginHive FedEx app is registered as a carrier on the store — good pre-test sanity check:

```python
resp = requests.get(f"{BASE_URL}/carrier_services.json", headers=HEADERS)
carriers = resp.json().get("carrier_services", [])
for c in carriers:
    print(f"  - {c['name']} | active: {c['active']} | callback: {c['callback_url']}")
```

Expected: you should see a PluginHive / FedEx entry with an active callback URL.

---

### 18. List Fulfillments for an Order

Check if the FedEx label was applied to an order via the API — shows tracking number, service, carrier:

```python
resp = requests.get(f"{BASE_URL}/orders/{order_id}/fulfillments.json", headers=HEADERS)
fulfillments = resp.json().get("fulfillments", [])

for f in fulfillments:
    print(f"  Fulfillment ID: {f['id']}")
    print(f"  Status:         {f['status']}")
    print(f"  Tracking:       {f.get('tracking_number')} via {f.get('tracking_company')}")
    print(f"  Service:        {f.get('service')}")
    for item in f.get("line_items", []):
        print(f"    - {item['title']} × {item['quantity']}")
```

---

### 19. Create Draft Order → Complete It

Create an order in draft state first (useful for controlled test data), then promote to a real order:

```python
# Step 1 — create draft
payload = {
    "draft_order": {
        "line_items": [{"variant_id": variant_id, "quantity": 1}],
        "customer": {"first_name": "QA", "last_name": "Test", "email": "qa.draft@pluginhive.com"},
        "shipping_address": {
            "first_name": "QA", "last_name": "Test",
            "address1": "123 Main St", "city": "New York",
            "province": "New York", "province_code": "NY",
            "zip": "10001", "country": "United States", "country_code": "US"
        },
        "use_customer_default_address": False,
        "tags": "qa-draft",
    }
}
resp = requests.post(f"{BASE_URL}/draft_orders.json", headers=HEADERS, json=payload)
draft = resp.json().get("draft_order", {})
draft_id = draft["id"]
print(f"Draft order created: #{draft['name']} (ID {draft_id})")

# Step 2 — complete it (becomes a real order, marked as paid)
resp = requests.put(
    f"{BASE_URL}/draft_orders/{draft_id}/complete.json",
    headers=HEADERS,
    params={"payment_pending": False}
)
order = resp.json().get("draft_order", {})
print(f"Completed → real order ID: {order.get('order_id')}")
```

---

### 20. Get Order Count

Quick sanity check before or after a test run:

```python
# Count by status
for status in ["open", "closed", "cancelled", "any"]:
    resp = requests.get(f"{BASE_URL}/orders/count.json", headers=HEADERS, params={"status": status})
    print(f"  {status}: {resp.json().get('count', 0)} orders")

# Count unfulfilled only
resp = requests.get(f"{BASE_URL}/orders/count.json", headers=HEADERS,
                    params={"fulfillment_status": "unfulfilled", "status": "open"})
print(f"  unfulfilled: {resp.json().get('count', 0)} orders")
```

---

### 21. List Webhooks

See what webhooks the FedEx / PluginHive app has registered on the store:

```python
resp = requests.get(f"{BASE_URL}/webhooks.json", headers=HEADERS)
webhooks = resp.json().get("webhooks", [])
print(f"Found {len(webhooks)} webhooks:")
for w in webhooks:
    print(f"  - [{w['id']}] {w['topic']:40s} → {w['address']}")
```

---

### 22. Get Metafields on a Product or Order

FedEx app may store label data / tracking info as metafields:

```python
# Metafields on a product
resp = requests.get(f"{BASE_URL}/products/{product_id}/metafields.json", headers=HEADERS)
mf = resp.json().get("metafields", [])

# Metafields on an order
resp = requests.get(f"{BASE_URL}/orders/{order_id}/metafields.json", headers=HEADERS)
mf = resp.json().get("metafields", [])

for m in mf:
    print(f"  {m['namespace']}.{m['key']} ({m['type']}): {m['value']}")
```

---

## 🟢 Nice to Have

### 23. Create Customer

Pre-create a customer so custom orders can be attached to a real customer record:

```python
payload = {
    "customer": {
        "first_name": "QA",
        "last_name": "Tester",
        "email": "qa.tester@pluginhive.com",
        "phone": "+12025550000",
        "verified_email": True,
        "addresses": [{
            "address1": "123 Main St",
            "city": "New York",
            "province": "New York",
            "province_code": "NY",
            "zip": "10001",
            "country": "United States",
            "country_code": "US",
            "default": True
        }],
        "tags": "qa-customer"
    }
}
resp = requests.post(f"{BASE_URL}/customers.json", headers=HEADERS, json=payload)
customer = resp.json().get("customer", {})
print(f"Created customer: {customer['first_name']} {customer['last_name']} (ID {customer['id']})")
```

---

### 24. Search Customer by Email or Name

```python
# By email (exact)
resp = requests.get(f"{BASE_URL}/customers/search.json", headers=HEADERS,
                    params={"query": "email:qa.tester@pluginhive.com"})

# By name (partial)
resp = requests.get(f"{BASE_URL}/customers/search.json", headers=HEADERS,
                    params={"query": "John Smith"})

customers = resp.json().get("customers", [])
for c in customers:
    print(f"  ID {c['id']} | {c['first_name']} {c['last_name']} | {c['email']}")
```

---

### 25. Adjust Inventory (relative ±delta)

Add or subtract from current quantity instead of setting an absolute value:

```python
delta = +50   # positive = add stock, negative = remove stock

payload = {
    "location_id": location_id,
    "inventory_item_id": inventory_item_id,
    "available_adjustment": delta
}
resp = requests.post(f"{BASE_URL}/inventory_levels/adjust.json", headers=HEADERS, json=payload)
result = resp.json().get("inventory_level", {})
print(f"Adjusted by {delta:+d} → now {result.get('available')} units")
```

Use `adjust` when user says "add 50 stock to that product" or "remove 10 units".
Use `set` (action 9) when user says "set stock to 9999" or "make it 0".

---

### 26. List Locations

Required when working with inventory across multiple store locations:

```python
resp = requests.get(f"{BASE_URL}/locations.json", headers=HEADERS)
locations = resp.json().get("locations", [])
print(f"Store has {len(locations)} location(s):")
for loc in locations:
    print(f"  ID {loc['id']} | {loc['name']} | active: {loc['active']}")
    print(f"    {loc.get('address1')}, {loc.get('city')}, {loc.get('country')}")
```

Default location is `locations[0]` — use its ID for all inventory operations unless the user specifies otherwise.

---

### 27. List Collections & Add Product to Collection

```python
# List all custom collections
resp = requests.get(f"{BASE_URL}/custom_collections.json", headers=HEADERS)
collections = resp.json().get("custom_collections", [])
for c in collections:
    print(f"  ID {c['id']} | {c['title']}")

# List all smart collections
resp = requests.get(f"{BASE_URL}/smart_collections.json", headers=HEADERS)

# Add product to a custom collection
payload = {"collect": {"product_id": product_id, "collection_id": collection_id}}
resp = requests.post(f"{BASE_URL}/collects.json", headers=HEADERS, json=payload)
print(f"Added product {product_id} to collection {collection_id}")
```

---

### 28. Create Refund on an Order

```python
# Step 1 — calculate refund first (Shopify requires this)
resp = requests.post(
    f"{BASE_URL}/orders/{order_id}/refunds/calculate.json",
    headers=HEADERS,
    json={"refund": {"shipping": {"full_refund": True}, "refund_line_items": []}}
)
calc = resp.json().get("refund", {})

# Step 2 — apply the refund
payload = {
    "refund": {
        "notify": False,
        "note": "QA test refund",
        "shipping": {"full_refund": True},
        "refund_line_items": calc.get("refund_line_items", []),
        "transactions": calc.get("transactions", [])
    }
}
resp = requests.post(f"{BASE_URL}/orders/{order_id}/refunds.json", headers=HEADERS, json=payload)
refund = resp.json().get("refund", {})
print(f"Refund created: ID {refund.get('id')} on order {order_id}")
```

---

## Execution Pattern

Always run Python in the project virtualenv:

```bash
cd /Users/madan/Documents/Fed-Ex-automation/FedexDomainExpert
PYTHONPATH=. .venv/bin/python -c "
# paste the action code here
"
```

Or write a temp script and run it:

```bash
PYTHONPATH=. .venv/bin/python /tmp/shopify_action.py
```

---

## Response Format

Always summarise what was done clearly:

**For list:**
```
Found 12 products:
- ID 9614590017847 | "Simple Product" | active | variant: 49091417047351 ($10.00)
- ID 9213872439516 | "red" | active | variant: 47470441201884 ($5.00)
...
```

**For create:**
```
Created order #1801
- Order ID: 6900000000000
- Product: Simple Product (qty 2)
- Ship to: John Smith, 123 Main St, New York, NY 10001, US
- Financial status: paid
```

**For delete by name:**
```
Deleted: "Red Shirt" (ID 9213872439516)
```
or if multiple matches found:
```
Found 3 products matching "Shirt":
  - ID 9213872439516 | "Red Shirt" | active
  - ID 9213872439517 | "Blue Shirt" | active
  - ID 9213872439518 | "Old Shirt" | draft
Which one to delete? (provide ID)
```

**For variable product:**
```
Created variable product "FedEx Test T-Shirt" (ID 9700000000001)
Variants (8 total):
  - S / Red  → variant ID 49100000000001 | $15.00
  - S / Blue → variant ID 49100000000002 | $15.00
  - M / Red  → variant ID 49100000000003 | $15.00
  ...
```

**For custom order:**
```
Created order #1802
  - Order ID: 6900000000001
  - Customer: John Smith <john.smith@test.com>
  - Ship to: 123 Main St, New York, NY 10001, US
  - Product: Simple Product × 2
  - Financial status: paid
```

**For inventory update:**
```
Updated inventory:
  - "Red Shirt" / M / Red (variant 49100000000003) → 9999 units
  - "Red Shirt" / M / Blue (variant 49100000000004) → 9999 units
```

**For errors:**
```
API error 422: {"errors": {"line_items": ["is too short (minimum is 1 character)"]}}
```

---

## Important Notes

- This skill uses the **same test store** and **same credentials** as the AI QA Agent browser flows — not a separate store.
- Products created here are real in the store and can immediately be used for FedEx label generation in the dashboard.
- Orders created here are `test: false` by default — they appear in the real Shopify admin Orders list, ready for FedEx label generation.
- The `productsconfig.json` and `addressconfig.json` in the automation repo are the source of truth for which product/variant IDs to use in orders — `order_creator.py` already reads those.
- Pagination: Shopify returns max 250 records per page. For full lists use cursor-based pagination via `page_info` in the `Link` response header.
