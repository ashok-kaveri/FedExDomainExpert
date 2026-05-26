---
name: fedex-shopify-store-actions
description: Use when the user wants to perform any Shopify Admin API action (REST or GraphQL) on any store — create/update/archive/delete products (simple, variable, up to 2048 variants via GraphQL), create/cancel/delete/update orders (preset, custom, draft, with BYPASS_STOCK so test orders never deduct inventory), create order+fulfillment+tracking in one call, bulk inventory update across variants, bulk cleanup by tag, update shipping address, manage customers, list fulfillments/carrier services/webhooks/metafields/collections/locations, create refunds — all via natural language. Token comes from automation .env automatically; if store not found there, asks for a token.
---

# Shopify Store Actions

Use this skill when the user asks to do anything with any Shopify store via API:

**Products**
- "create 3 products" / "create a variable product with 5 sizes × 5 colors × 5 fabrics"
- "create a product with 500 variants" (GraphQL — up to 2048)
- "list all products and give me the IDs"
- "delete the product called Red Shirt"
- "archive that product" / "set product status to draft"
- "update variant weight to 2.5kg" / "change the price of size M to $25"
- "change SKU of all variants to NEW-xxx" / "set barcode on Red Shirt to 012345"
- "allow backorders on this product" / "stop selling when out of stock"
- "mark this variant as digital / no shipping required"
- "update compare at price to $30" / "remove the strikethrough price"
- "bulk update all variants: set price to $19.99 and inventory policy to continue"
- "update product title / vendor / description / tags / SEO title"

**Orders**
- "create a test order" / "create order without touching inventory" (BYPASS_STOCK)
- "create an order for John Smith at 123 Main St NY"
- "create a draft order and complete it"
- "create an order already fulfilled with tracking number 794644774000"
- "cancel order #1801" / "delete all qa-test tagged orders"
- "update the shipping address on order #1802"
- "list all unfulfilled orders" / "how many open orders are there?"

**Inventory**
- "set inventory of Red Shirt to 9999" / "add 50 stock to Red Shirt"
- "set all variants of this product to 500 qty in one call" (GraphQL bulk)

**Store & Setup**
- "check if FedEx app is registered as a carrier"
- "show fulfillments for order #1800"
- "list webhooks" / "get metafields on this product"
- "create a customer called Jane Doe" / "find customer by email"
- "list all locations" / "list collections"
- "create a refund on order #1799"
- any action on a specific store: "do this on test-madan-store-2"

---

## Store & Auth Resolution

### Logic (simple — 3 checks in order)

```
1. No store mentioned by user
   → use STORE + SHOPIFY_ACCESS_TOKEN directly from automation .env
   → no questions asked

2. User mentions a store name
   → normalize it (strip .myshopify.com, lowercase, trim spaces)
   → check if it matches STORE in automation .env or env_sample
       match  → use the token from that file
       no match → STOP and say: "I need an access token for store X"

3. User provides an explicit token along with the store name
   → use exactly what they gave, skip env lookup
```

---

### Implementation

```python
import config, requests
from pathlib import Path

def _read_env_file(path: Path) -> dict:
    env = {}
    if path and path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, _, v = line.partition("=")
                env[k.strip()] = v.strip().strip("'\"")
    return env

# Load automation .env (primary)
_automation_path = (config.AUTOMATION_CODEBASE_PATH or "").strip()
_automation_env  = _read_env_file(Path(_automation_path) / ".env") if _automation_path else {}

# Load shopify-actions env_sample (secondary fallback)
_actions_env = _read_env_file(Path("/Users/madan/Documents/shopify-actions /env_sample"))

def resolve_store(user_store: str = "", user_token: str = "") -> tuple[str, str, str]:
    """
    Returns (STORE, ACCESS_TOKEN, API_VERSION) or raises with a clear message.

    user_store : store name extracted from the user's message (empty = not mentioned)
    user_token : token explicitly provided by the user (empty = not provided)
    """
    api_version = (
        _automation_env.get("SHOPIFY_API_VERSION")
        or _actions_env.get("SHOPIFY_API_VERSION")
        or "2024-01"
    )

    # Case 1 — user gave explicit token
    if user_token:
        store = _normalize(user_store or _automation_env.get("STORE", ""))
        return store, user_token, api_version

    # Case 2 — no store mentioned → use automation .env directly
    if not user_store:
        store = _automation_env.get("STORE", "").strip()
        token = _automation_env.get("SHOPIFY_ACCESS_TOKEN", "").strip()
        if not store or not token:
            raise ValueError("STORE or SHOPIFY_ACCESS_TOKEN missing in automation .env")
        return store, token, api_version

    # Case 3 — user named a store → check if it exists in env files
    user_store_norm = _normalize(user_store)

    for env_dict, source in [
        (_automation_env, "automation .env"),
        (_actions_env,    "shopify-actions env_sample"),
    ]:
        env_store = _normalize(env_dict.get("STORE", "") or env_dict.get("SHOPIFY_STORE_NAME", ""))
        env_token = env_dict.get("SHOPIFY_ACCESS_TOKEN", "").strip()

        if env_store and env_token and user_store_norm == env_store:
            print(f"Store '{user_store}' found in {source} — using its token.")
            return env_store, env_token, api_version

    # Not found in any env file → ask for token
    raise ValueError(
        f"Store '{user_store}' is not in the automation .env or env_sample.\n"
        f"I need an access token for this store.\n"
        f"Please provide it: \"use store {user_store} with token shpat_xxx\""
    )

def _normalize(name: str) -> str:
    return name.lower().strip().replace(".myshopify.com", "")
```

**Usage in every action:**
```python
try:
    STORE, ACCESS_TOKEN, API_VERSION = resolve_store(
        user_store="test-madan-store-2",   # from user message, or "" if not mentioned
        user_token="",                      # from user message, or "" if not provided
    )
except ValueError as e:
    print(e)
    # STOP — do not proceed without a valid token

BASE_URL = f"https://{STORE}.myshopify.com/admin/api/{API_VERSION}"
HEADERS  = {"X-Shopify-Access-Token": ACCESS_TOKEN, "Content-Type": "application/json"}
```

---

### Connection check — always run before the first API call

```python
resp = requests.get(f"{BASE_URL}/shop.json", headers=HEADERS)

if resp.status_code == 200:
    shop = resp.json()["shop"]
    print(f"Connected: {shop['name']} ({shop['myshopify_domain']})")

elif resp.status_code == 401:
    print(f"Token rejected on '{STORE}'.")
    print(f"The app may not be installed on this store, or the token may have been revoked.")
    print(f"Provide a valid token: \"use store {STORE} with token shpat_xxx\"")
    # STOP

elif resp.status_code == 404:
    print(f"Store '{STORE}' not found — check the store name.")
    # STOP
```

---

### What to say to the user in each case

| Situation | Message |
|---|---|
| Store found in env, token works | `Connected: FedEx Test Store (fedexapp-rest-packaging.myshopify.com)` |
| No store mentioned, env has it | `Using default store: fedexapp-rest-packaging (from automation .env)` |
| Store named, found in env | `Store 'test-madan-store-2' found in automation .env — using its token.` |
| Store named, NOT in any env | `Store 'xyz-store' is not in the automation .env or env_sample. I need an access token for this store. Please provide it: "use store xyz-store with token shpat_xxx"` |
| Token provided explicitly | `Using store: xyz-store (token provided explicitly)` |
| Token rejected (401) | `Token rejected on 'xyz-store'. The app may not be installed on this store. Provide a valid token: "use store xyz-store with token shpat_xxx"` |

---

## GraphQL vs REST — When to Use Which

| Use REST when | Use GraphQL when |
|---|---|
| Simple list / get / delete | Creating test orders without touching inventory |
| Single product/order CRUD | Creating order + fulfillment + tracking in one call |
| Inventory set on one variant | Bulk inventory update across many variants/locations at once |
| Small variant counts | Creating products with 100–2048 variants |
| Quick scripts | You need structured per-field error reporting |

**GraphQL endpoint** — same auth header, different URL:
```python
GQL_URL = f"https://{STORE}.myshopify.com/admin/api/{API_VERSION}/graphql.json"

def gql(query: str, variables: dict = None) -> dict:
    payload = {"query": query}
    if variables:
        payload["variables"] = variables
    resp = requests.post(GQL_URL, headers=HEADERS, json=payload)
    resp.raise_for_status()
    data = resp.json()
    errors = data.get("errors") or []
    user_errors = (data.get("data") or {})
    # surface both
    if errors:
        raise ValueError(f"GraphQL errors: {errors}")
    return data.get("data", {})
```

---

## GraphQL Actions

### G1. Create Order — BYPASS_STOCK (test orders, no inventory deducted)

**Most important for QA testing.** Creates real orders without decrementing product inventory — perfect for test runs that would otherwise drain your test store's stock.

```python
query = """
mutation orderCreate($order: OrderCreateOrderInput!, $options: OrderCreateOptionsInput) {
  orderCreate(order: $order, options: $options) {
    userErrors { field message }
    order {
      id
      name
      displayFinancialStatus
      lineItems(first: 10) {
        nodes { title quantity }
      }
    }
  }
}
"""

variables = {
    "order": {
        "lineItems": [
            {
                "variantId": "gid://shopify/ProductVariant/49091417047351",
                "quantity": 1
            }
        ],
        "customer": {
            "toUpsert": {
                "email": "qa.test@pluginhive.com",
                "firstName": "QA",
                "lastName": "Tester"
            }
        },
        "shippingAddress": {
            "firstName": "QA", "lastName": "Tester",
            "address1": "123 Main St", "city": "New York",
            "provinceCode": "NY", "countryCode": "US", "zip": "10001"
        },
        "financialStatus": "PAID",
        "tags": ["qa-test"],
    },
    "options": {
        "inventoryBehaviour": "BYPASS_STOCK",   # ← does NOT deduct inventory
        "sendReceipt": False,
        "sendFulfillmentReceipt": False,
    }
}

result = gql(query, variables)
order = result["orderCreate"]["order"]
user_errors = result["orderCreate"]["userErrors"]

if user_errors:
    print(f"Errors: {user_errors}")
else:
    print(f"Created {order['name']} (ID: {order['id']})")
```

**`inventoryBehaviour` options:**
| Value | Effect |
|---|---|
| `BYPASS_STOCK` | Order created, inventory NOT touched — best for QA test orders |
| `DECREMENT_STOCK` | Reduces available inventory (normal behaviour) |

**`customer.toUpsert`** — no need to pre-create the customer. If the email already exists it updates them; if not it creates them. One step.

---

### G2. Create Order with Fulfillment + Tracking (one mutation)

Creates the order AND marks it as fulfilled with a tracking number in a single call — useful when you need a "label generated" state without going through the browser:

```python
variables = {
    "order": {
        "lineItems": [{"variantId": "gid://shopify/ProductVariant/49091417047351", "quantity": 1}],
        "shippingAddress": {
            "firstName": "QA", "lastName": "Tester",
            "address1": "123 Main St", "city": "New York",
            "provinceCode": "NY", "countryCode": "US", "zip": "10001"
        },
        "financialStatus": "PAID",
        "fulfillment": {
            "locationId": "gid://shopify/Location/LOCATION_ID",
            "trackingCompany": "FedEx",
            "trackingNumber": "794644774000",
            "shipmentStatus": "DELIVERED",
            "notifyCustomer": False,
        },
        "tags": ["qa-test", "qa-fulfilled"],
    },
    "options": {
        "inventoryBehaviour": "BYPASS_STOCK",
        "sendReceipt": False,
        "sendFulfillmentReceipt": False,
    }
}
```

Get `locationId` first if you don't have it:
```python
# REST — quick way to get location IDs
resp = requests.get(f"{BASE_URL}/locations.json", headers=HEADERS)
loc_id = resp.json()["locations"][0]["id"]
gql_loc_id = f"gid://shopify/Location/{loc_id}"
```

---

### G3. Create Product with Variants up to 2048

**GraphQL supports up to 2048 variants per product** — far beyond the REST limit. Use `productCreate` + `productVariantsBulkCreate` in two steps:

```python
import itertools

# Step 1 — create the product with options (no variants yet)
create_query = """
mutation productCreate($product: ProductCreateInput!) {
  productCreate(product: $product) {
    userErrors { field message }
    product {
      id
      title
      options { id name values }
    }
  }
}
"""

# Example: 8 sizes × 8 colors × 4 fabrics = 256 variants
sizes   = ["XS", "S", "M", "L", "XL", "XXL", "3XL", "4XL"]
colors  = ["Red", "Blue", "Green", "Black", "White", "Yellow", "Purple", "Orange"]
fabrics = ["Cotton", "Polyester", "Wool", "Linen"]

create_vars = {
    "product": {
        "title": "FedEx QA Multi-Variant Product",
        "status": "ACTIVE",
        "productOptions": [
            {"name": "Size",   "values": [{"name": v} for v in sizes]},
            {"name": "Color",  "values": [{"name": v} for v in colors]},
            {"name": "Fabric", "values": [{"name": v} for v in fabrics]},
        ]
    }
}

result    = gql(create_query, create_vars)
product   = result["productCreate"]["product"]
product_id = product["id"]

# Map option name → option ID (needed for bulk variant create)
option_map = {opt["name"]: opt["id"] for opt in product["options"]}

# Step 2 — bulk create all variant combinations
bulk_query = """
mutation productVariantsBulkCreate($productId: ID!, $variants: [ProductVariantsBulkInput!]!) {
  productVariantsBulkCreate(productId: $productId, variants: $variants) {
    userErrors { field message }
    productVariants { id title price }
  }
}
"""

variants = [
    {
        "price": "15.00",
        "optionValues": [
            {"optionId": option_map["Size"],   "name": size},
            {"optionId": option_map["Color"],  "name": color},
            {"optionId": option_map["Fabric"], "name": fabric},
        ]
    }
    for size, color, fabric in itertools.product(sizes, colors, fabrics)
]

total = len(variants)
print(f"Creating {total} variants...")  # 256 in this example

# Shopify recommends batching in chunks of 100 for large counts
CHUNK = 100
created = []
for i in range(0, total, CHUNK):
    chunk = variants[i:i+CHUNK]
    r = gql(bulk_query, {"productId": product_id, "variants": chunk})
    created.extend(r["productVariantsBulkCreate"]["productVariants"])
    print(f"  Batch {i//CHUNK + 1}: {len(chunk)} variants created")

print(f"Done — product '{product['title']}' with {len(created)} variants")
```

**Variant limit comparison:**
| API | Confirmed limit |
|---|---|
| REST | ~140+ (tested on this store) |
| GraphQL `productVariantsBulkCreate` | **2048 per product** (official Shopify limit) |

---

### G4. Bulk Inventory Update (multiple items + locations in one call)

Update inventory for many variants across many locations in a **single GraphQL mutation** — much faster than REST's one-at-a-time approach.

#### What quantity types can be updated

Shopify inventory has 8 quantity types. Not all are writable:

| Name | What it is | Writable? |
|---|---|---|
| `available` | Available for sale on storefront | ✅ Set directly |
| `on_hand` | Physical stock count | ✅ Set directly (also adjusts `available`) |
| `incoming` | Expected from purchase orders / transfers | ✅ Set directly |
| `safety_stock` | Minimum buffer stock level | ✅ Set directly |
| `damaged` | Damaged items set aside | ✅ Set directly |
| `quality_control` | Items in QC hold | ✅ Set directly |
| `committed` | Reserved for open (unfulfilled) orders | ❌ Read-only — calculated from open orders |
| `reserved` | Reserved for draft orders | ❌ Read-only — calculated from draft orders |

**Relationship:**
```
on_hand = available + committed + reserved + damaged + quality_control
available = on_hand - committed - reserved - damaged - quality_control
```
→ Setting `available` directly is the safest for QA — it's exactly "how many can be sold right now."
→ Setting `on_hand` is for physical stock counts — it recalculates `available` automatically.

**Two mutations — set vs adjust:**

| Mutation | Effect | Use when |
|---|---|---|
| `inventorySetQuantities` | Sets **absolute** value | "set stock to 9999" |
| `inventoryAdjustQuantities` | Applies **relative delta** | "add 50 stock" / "remove 10" |

---

#### inventorySetQuantities — set absolute values (bulk)

```python
SET_QUERY = """
mutation inventorySetQuantities($input: InventorySetQuantitiesInput!) {
  inventorySetQuantities(input: $input) {
    userErrors { field message code }
    inventoryAdjustmentGroup {
      reason
      changes {
        name
        delta
        quantityAfterChange
        item { id }
        location { id name }
      }
    }
  }
}
"""

location_gid = "gid://shopify/Location/LOCATION_ID"

# name can be: "available" | "on_hand" | "incoming" | "safety_stock" | "damaged" | "quality_control"
variables = {
    "input": {
        "name": "available",              # ← which quantity type to set
        "reason": "correction",
        "referenceDocumentUri": "logistics://qa-test-run",
        "ignoreCompareQuantity": True,    # skip compare-and-swap — just force-set
        "quantities": [
            {"inventoryItemId": "gid://shopify/InventoryItem/111", "locationId": location_gid, "quantity": 9999},
            {"inventoryItemId": "gid://shopify/InventoryItem/222", "locationId": location_gid, "quantity": 9999},
            # as many items as needed — all updated in ONE API call
        ]
    }
}

result = gql(SET_QUERY, variables)
changes = result["inventorySetQuantities"]["inventoryAdjustmentGroup"]["changes"]
for c in changes:
    print(f"  {c['item']['id']} @ {c['location']['name']}: delta={c['delta']:+d} → {c['quantityAfterChange']}")
```

---

#### inventoryAdjustQuantities — apply relative delta (bulk)

```python
ADJUST_QUERY = """
mutation inventoryAdjustQuantities($input: InventoryAdjustQuantitiesInput!) {
  inventoryAdjustQuantities(input: $input) {
    userErrors { field message }
    inventoryAdjustmentGroup {
      reason
      changes { name delta quantityAfterChange item { id } location { name } }
    }
  }
}
"""

variables = {
    "input": {
        "name": "available",           # which quantity type to adjust
        "reason": "correction",
        "referenceDocumentUri": "logistics://qa-delta-run",
        "changes": [
            {"inventoryItemId": "gid://shopify/InventoryItem/111", "locationId": location_gid, "delta": +50},
            {"inventoryItemId": "gid://shopify/InventoryItem/222", "locationId": location_gid, "delta": -10},
            # positive = add stock, negative = remove stock
        ]
    }
}

result = gql(ADJUST_QUERY, variables)
```

---

#### Helper — update ALL variants of a product in one call

```python
def bulk_set_product_inventory(product_id_rest: int, qty: int, name: str = "available"):
    """Set a specific inventory quantity type for ALL variants of a product at once."""

    # Get inventory_item_ids from REST
    resp = requests.get(f"{BASE_URL}/products/{product_id_rest}/variants.json", headers=HEADERS)
    variants = [v for v in resp.json()["variants"] if v.get("inventory_management") == "shopify"]

    # Get default location
    loc_id  = requests.get(f"{BASE_URL}/locations.json", headers=HEADERS).json()["locations"][0]["id"]
    loc_gid = f"gid://shopify/Location/{loc_id}"

    quantities = [
        {
            "inventoryItemId": f"gid://shopify/InventoryItem/{v['inventory_item_id']}",
            "locationId": loc_gid,
            "quantity": qty,
        }
        for v in variants
    ]

    result = gql(SET_QUERY, {
        "input": {
            "name": name,
            "reason": "correction",
            "referenceDocumentUri": "logistics://qa-bulk-set",
            "ignoreCompareQuantity": True,
            "quantities": quantities,
        }
    })
    user_errors = result["inventorySetQuantities"]["userErrors"]
    if user_errors:
        print(f"Errors: {user_errors}")
    else:
        print(f"Set '{name}' to {qty} for {len(quantities)} variants")

# Usage examples:
bulk_set_product_inventory(9614590017847, qty=9999)               # set available to 9999
bulk_set_product_inventory(9614590017847, qty=0, name="damaged")  # clear damaged stock
bulk_set_product_inventory(9614590017847, qty=50, name="incoming")# set expected incoming
```

---

#### User intent → name mapping

| User says | `name` to use |
|---|---|
| "set stock to X" / "set qty to X" / "make it X" | `available` |
| "set physical count to X" / "stock take" | `on_hand` |
| "expecting X units" / "incoming stock" | `incoming` |
| "X units are damaged" / "mark as damaged" | `damaged` |
| "put X in quality control" | `quality_control` |
| "set safety stock to X" / "minimum buffer" | `safety_stock` |
| "committed" / "reserved" (user asks to set these) | Tell user: these are read-only, calculated from orders |

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

#### Variant interpretation rule — READ THIS FIRST

| User says | What it means | How to handle |
|---|---|---|
| "variable product with 200 variants" | combination-style (axes × values) | Pick axes whose product ≈ 200 (e.g. Size×Color×Age = 5×5×8) |
| "variable product with 50 variants" | combination-style | Pick axes whose product ≈ 50 (e.g. Size×Color = 5×10) |
| "100 **unique/different/separate** variants" | 100 truly independent SKUs | Use single axis "Variant" with values 1…100 |

**Default = combo.** Any number the user gives is a target for a combination product.
Only use single-axis numbered variants when the user explicitly says "unique", "different", "separate", or "individual" variants.

**Shopify limits:**
- Max **3 option axes** per product
- REST API: max **100 variants** total → use GraphQL `productSet` for >100
- GraphQL `productSet` supports up to 2000 variants

#### Choosing axes for a target count N

```
N ≤ 100  → use REST (2–3 axes)
N > 100  → use GraphQL productSet

Example targets:
  25  → Size(5) × Color(5)            = 25
  50  → Size(5) × Color(10)           = 50
  100 → Size(5) × Color(5) × Age(4)  = 100
  125 → Size(5) × Color(5) × Age(5)  = 125
  200 → Size(5) × Color(5) × Age(8)  = 200
```

When the user asks for many variants, generate them programmatically with `itertools.product` — never write them by hand.

**Strategy A — REST, ≤100 variants (2–3 axes)**

```python
import itertools, requests

sizes  = ["XS", "S", "M", "L", "XL"]
colors = ["Red", "Blue", "Green", "Black", "White"]
# total = 5 × 5 = 25 variants

combos   = list(itertools.product(sizes, colors))
variants = [
    {
        "option1": size, "option2": color,
        "price": "15.00",
        "sku": f"TV-{size}-{color[:3].upper()}",
        "grams": 500, "weight": 0.5, "weight_unit": "kg",
        "requires_shipping": True,
    }
    for size, color in combos
]

payload = {
    "product": {
        "title": "Test Variable",
        "vendor": STORE,
        "status": "active",
        "options": [
            {"name": "Size",  "values": sizes},
            {"name": "Color", "values": colors},
        ],
        "variants": variants,
        "tags": "qa-test",
    }
}
resp    = requests.post(f"{BASE_URL}/products.json", headers=HEADERS, json=payload)
product = resp.json().get("product", {})
print(f"Created '{product['title']}' with {len(product['variants'])} variants")
```

**Strategy B — GraphQL productSet, >100 variants (required for 101–2000)**

```python
import itertools, requests

SIZES  = ["XS", "S", "M", "L", "XL"]
COLORS = ["Red", "Blue", "Green", "Black", "White"]
AGES   = ["Kids", "Teen", "Adult", "Senior", "Youth"]
# 5 × 5 × 5 = 125 variants

GQL_URL = f"https://{STORE}.myshopify.com/admin/api/{API_VERSION}/graphql.json"

variants_input = [
    {
        "optionValues": [
            {"optionName": "Size",      "name": size},
            {"optionName": "Color",     "name": color},
            {"optionName": "Age Group", "name": age},
        ],
        "price": "15.00",
        "sku": f"TV-{size}-{color[:3].upper()}-{age[:3].upper()}",
        "inventoryItem": {
            "measurement": {"weight": {"value": 0.5, "unit": "KILOGRAMS"}},
            "requiresShipping": True,
        },
    }
    for size, color, age in itertools.product(SIZES, COLORS, AGES)
]

mutation = """
mutation CreateProduct($synchronous: Boolean!, $productSet: ProductSetInput!) {
  productSet(synchronous: $synchronous, input: $productSet) {
    product {
      id
      title
      variantsCount { count }
      options { name optionValues { name } }
      variants(first: 5) { nodes { id title sku price } }
    }
    userErrors { field message code }
  }
}
"""

variables = {
    "synchronous": True,
    "productSet": {
        "title": "Test Variable",
        "vendor": STORE,
        "productType": "Test",
        "status": "ACTIVE",
        "tags": ["qa-test"],
        # NOTE: field is "productOptions" in GraphQL ProductSetInput (NOT "options")
        "productOptions": [
            {"name": "Size",      "values": [{"name": v} for v in SIZES]},
            {"name": "Color",     "values": [{"name": v} for v in COLORS]},
            {"name": "Age Group", "values": [{"name": v} for v in AGES]},
        ],
        "variants": variants_input,
    }
}

resp   = requests.post(GQL_URL, headers=HEADERS, json={"query": mutation, "variables": variables})
result = resp.json()["data"]["productSet"]
if result["userErrors"]:
    print(result["userErrors"])
else:
    p             = result["product"]
    product_id    = int(p["id"].split("/")[-1])
    variant_count = p["variantsCount"]["count"]
    print(f"Created '{p['title']}' — ID {product_id} — {variant_count} variants")
    # Extract numeric variant ID for REST order creation:
    first_variant_id = int(p["variants"]["nodes"][0]["id"].split("/")[-1])
```

**Key GraphQL notes:**
- Use `productOptions` (not `options`) in `ProductSetInput` — Shopify 2024-04+
- `synchronous: true` waits for all variants before returning
- GID format → numeric: `int(gid.split("/")[-1])` — needed for REST order creation

**Strategy C — single axis (only when user explicitly asks for unique/separate variants)**

```python
count         = 100  # user explicitly said "100 unique variants"
option_values = [str(i) for i in range(1, count + 1)]
variants      = [
    {"option1": v, "price": "10.00", "sku": f"VAR-{v.zfill(3)}",
     "grams": 500, "weight": 0.5, "weight_unit": "kg", "requires_shipping": True}
    for v in option_values
]
payload = {
    "product": {
        "title": "Test Product",
        "vendor": STORE, "status": "active",
        "options": [{"name": "Variant", "values": option_values}],
        "variants": variants,
    }
}
# REST for ≤100, GraphQL productSet for >100
```

**Note:** Shopify only supports **up to 3 option axes**. If the user asks for 4 dimensions, combine two into one (e.g. "Color-Fabric" as a single combined option).

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

### 15. Update Product — Any Field

Every writable product field via REST:

```python
payload = {
    "product": {
        # Identity
        "title":           "New Product Title",
        "handle":          "new-product-title",       # URL slug — auto-set if omitted
        "vendor":          "PluginHive",
        "product_type":    "Shipping Label Test",
        "body_html":       "<p>Updated description</p>",

        # Status
        "status":          "active",    # active | draft | archived
        "published_scope": "global",    # global | web

        # Discoverability
        "tags":            "qa-product, fedex, dangerous-goods",

        # SEO (metafield shorthand)
        "metafields_global_title_tag":       "SEO Title Here",
        "metafields_global_description_tag": "SEO description here",
    }
}
resp = requests.put(f"{BASE_URL}/products/{product_id}.json", headers=HEADERS, json=payload)
product = resp.json().get("product", {})
print(f"Updated product: {product['title']} | status: {product['status']}")
```

Only send the fields you want to change — omitted fields are not touched.

**User intent → field mapping:**
| User says | Field |
|---|---|
| "rename product to X" | `title` |
| "change vendor to X" | `vendor` |
| "update description" | `body_html` |
| "add tags X, Y" | `tags` (replace entire tag string) |
| "archive / draft / activate" | `status` |
| "change product type" | `product_type` |
| "update SEO title" | `metafields_global_title_tag` |

---

### 15b. Update Product Variant — Any Field (single variant, REST)

Every writable variant field via REST PUT `/variants/{id}`:

```python
payload = {
    "variant": {
        # Pricing
        "price":            "25.00",
        "compare_at_price": "30.00",    # strikethrough/original price (null to remove)

        # Identity
        "sku":              "NEW-SKU-001",
        "barcode":          "012345678901",   # UPC / EAN / ISBN
        "title":            "Large / Red",    # only meaningful for single-option products

        # Shipping / FedEx
        "weight":           2.5,
        "weight_unit":      "kg",            # g | kg | oz | lb
        "grams":            2500,
        "requires_shipping": True,

        # Tax
        "taxable":          True,

        # Inventory behaviour
        "inventory_management": "shopify",   # "shopify" | null (untracked)
        "inventory_policy":     "deny",      # "deny" (stop at 0) | "continue" (allow backorders)

        # Fulfillment
        "fulfillment_service": "manual",     # "manual" | carrier service handle

        # Display
        "position":         1,               # sort order among variants
        "image_id":         None,            # associate a product image
    }
}
resp = requests.put(f"{BASE_URL}/variants/{variant_id}.json", headers=HEADERS, json=payload)
variant = resp.json().get("variant", {})
print(f"Updated variant {variant_id}")
```

**Read-only fields — cannot be changed via variant update:**
`id`, `product_id`, `inventory_item_id`, `inventory_quantity`, `created_at`, `updated_at`, `admin_graphql_api_id`

**User intent → field mapping:**
| User says | Field |
|---|---|
| "change SKU to X" | `sku` |
| "change barcode to X" | `barcode` |
| "set price to X" | `price` |
| "set compare at price / original price to X" | `compare_at_price` |
| "change weight to X kg/g/oz/lb" | `weight` + `weight_unit` + `grams` |
| "allow backorders / overselling" | `inventory_policy: "continue"` |
| "stop selling when out of stock" | `inventory_policy: "deny"` |
| "mark as does not require shipping / digital" | `requires_shipping: False` |
| "stop tracking inventory" | `inventory_management: null` |
| "track inventory" | `inventory_management: "shopify"` |
| "not taxable" | `taxable: False` |

---

### 15c. Bulk Update Multiple Variants at Once (GraphQL)

Update any field on many variants in a **single API call** — no looping needed:

```python
BULK_UPDATE_QUERY = """
mutation productVariantsBulkUpdate($productId: ID!, $variants: [ProductVariantsBulkInput!]!) {
  productVariantsBulkUpdate(productId: $productId, variants: $variants) {
    userErrors { field message }
    productVariants {
      id
      title
      price
      sku
      barcode
      weight
      weightUnit
      inventoryPolicy
      taxable
      requiresShipping
    }
  }
}
"""

# Example: update price + SKU + weight on every variant of a product
resp = requests.get(f"{BASE_URL}/products/{product_id}/variants.json", headers=HEADERS)
existing = resp.json()["variants"]

variants_input = []
for v in existing:
    variants_input.append({
        "id": f"gid://shopify/ProductVariant/{v['id']}",

        # Only include fields you want to change
        "price":            "19.99",
        "sku":              f"NEW-{v['sku']}",
        "barcode":          "012345678901",
        "inventoryPolicy":  "CONTINUE",       # GraphQL uses UPPERCASE: DENY | CONTINUE
        "taxable":          True,
        "requiresShipping": True,
        "metafields": [                        # can also update/add metafields per variant
            {"namespace": "qa", "key": "test_run", "value": "sprint-42", "type": "single_line_text_field"}
        ],
    })

result = gql(BULK_UPDATE_QUERY, {
    "productId": f"gid://shopify/Product/{product_id}",
    "variants":  variants_input,
})

updated = result["productVariantsBulkUpdate"]["productVariants"]
print(f"Updated {len(updated)} variants")
for v in updated:
    print(f"  {v['title']} → sku={v['sku']}, price={v['price']}, policy={v['inventoryPolicy']}")
```

**All updatable variant fields in GraphQL `ProductVariantsBulkInput`:**

| Field | Type | Notes |
|---|---|---|
| `id` | ID! | Required to identify which variant to update |
| `price` | String | e.g. `"19.99"` |
| `compareAtPrice` | String | Strikethrough price, null to remove |
| `sku` | String | Stock keeping unit |
| `barcode` | String | UPC / EAN / ISBN |
| `weight` | Float | Numeric weight value |
| `weightUnit` | WeightUnit | `GRAMS` \| `KILOGRAMS` \| `OUNCES` \| `POUNDS` |
| `requiresShipping` | Boolean | |
| `taxable` | Boolean | |
| `inventoryPolicy` | `DENY` \| `CONTINUE` | Backorder behaviour |
| `inventoryManagement` | `SHOPIFY` \| `NOT_MANAGED` | Whether Shopify tracks stock |
| `fulfillmentService` | String | Service handle |
| `position` | Int | Sort order |
| `optionValues` | Array | Change which option values this variant represents |
| `mediaId` | ID | Associate an image/video |
| `metafields` | Array | Add or update custom metadata |

---

### 16. Archive / Draft / Activate a Product

```python
# Archive (hides from storefront, keeps all data)
resp = requests.put(f"{BASE_URL}/products/{product_id}.json", headers=HEADERS,
                    json={"product": {"status": "archived"}})

# Draft (hidden, editable)
resp = requests.put(f"{BASE_URL}/products/{product_id}.json", headers=HEADERS,
                    json={"product": {"status": "draft"}})

# Active (visible on storefront)
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

**For GraphQL order (BYPASS_STOCK):**
```
Using store: fedexapp-rest-packaging (token: automation .env)
Connected: FedEx REST Test (fedexapp-rest-packaging.myshopify.com)
Created order #1803 (gid://shopify/Order/6900000000002)
  - Customer: QA Tester <qa.test@pluginhive.com> [upserted]
  - Ship to: 123 Main St, New York, NY 10001, US
  - Inventory: BYPASS_STOCK — no stock deducted ✓
  - Tags: qa-test
```

**For GraphQL large variant product:**
```
Created product "FedEx QA Multi-Variant Product" (gid://shopify/Product/9700000000002)
Options: Size (8) × Color (8) × Fabric (4)
Creating 256 variants...
  Batch 1: 100 variants created
  Batch 2: 100 variants created
  Batch 3: 56 variants created
Done — 256 variants total
```

**For GraphQL bulk inventory:**
```
Updated 256 variants to qty=9999:
  InventoryItem/111 @ Online Store → delta=+9999, now=9999
  InventoryItem/222 @ Online Store → delta=+9999, now=9999
  ... (256 total)
```

**For REST errors:**
```
API error 422: {"errors": {"line_items": ["is too short (minimum is 1 character)"]}}
```

**For GraphQL userErrors:**
```
GraphQL userErrors:
  - field: lineItems, message: Variant does not exist
  - field: financialStatus, message: is not included in the list
```

---

## Important Notes

**Store & Auth**
- Token is read from automation `.env` automatically. If the user names a store not in any `.env`, the skill stops and asks for a token.
- Always print which store is active before running any action to prevent wrong-store mistakes.
- Cannot auto-install the app or generate a token via API — Shopify requires OAuth browser consent. Use `fedex-ai-qa-browser` skill if an install is needed.

**Orders**
- Always use `BYPASS_STOCK` (GraphQL G1) for QA test orders — never deduct real inventory.
- Tag all test orders with `qa-test` at creation time so bulk cleanup (action 13) works.
- Orders appear in the real Shopify admin → Orders list immediately and are ready for FedEx label generation.

**Products & Variants**
- REST: ~140+ variants confirmed on this store.
- GraphQL `productVariantsBulkCreate`: up to **2048 variants** per product (official Shopify limit).
- For large variant counts use GraphQL G3 (create product first, then bulk add variants in chunks of 100).
- Products created here are immediately usable for FedEx label generation in the dashboard.

**Inventory**
- Use REST action 9 (`/inventory_levels/set.json`) for single variant, single location updates.
- Use REST action 25 (`/inventory_levels/adjust.json`) for single variant relative delta.
- Use GraphQL G4 (`inventorySetQuantities`) for bulk absolute set across many variants/locations in one call.
- Use GraphQL G4 (`inventoryAdjustQuantities`) for bulk relative delta across many variants/locations.
- 6 quantity types are writable: `available`, `on_hand`, `incoming`, `safety_stock`, `damaged`, `quality_control`.
- `committed` and `reserved` are read-only — calculated from open/draft orders, cannot be set.
- `BYPASS_STOCK` on order create is separate — it just skips the deduction at order time, doesn't change stored inventory numbers.

**API choice**
- REST for simple CRUD (list, get, delete, single update).
- GraphQL for: BYPASS_STOCK orders, 100+ variant products, bulk inventory, order+fulfillment in one call.
- Both use the same `X-Shopify-Access-Token` header. Only the URL and payload format differ.

**Pagination**
- REST: max 250 per page, use `Link` header `page_info` cursor for full lists.
- GraphQL: use `first` + `after` cursor on connections for paginated queries.
- Pagination: Shopify returns max 250 records per page. For full lists use cursor-based pagination via `page_info` in the `Link` response header.
