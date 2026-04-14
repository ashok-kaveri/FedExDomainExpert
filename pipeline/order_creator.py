"""
Order Creator  —  Smart AC Verifier helper
==========================================
Creates Shopify orders via REST API for the Smart AC Verifier.
Reads the same productsconfig.json + addressconfig.json that the
TypeScript ShopifyOrderUploader uses — no duplication.

Used when the verifier judges that a suitable existing order
does not exist in the store and needs to create one.

Supports:
  product_type: "simple" | "variable" | "digital" | "dangerous"
  address_type: "default" (US domestic) | "UK" | "CA" (Canada)
"""
from __future__ import annotations
import json
import logging
import time
from pathlib import Path

import requests

import config

logger = logging.getLogger(__name__)

# ── Paths (same files the TypeScript helper reads) ────────────────────────────
_AUTOMATION   = Path(config.AUTOMATION_CODEBASE_PATH)
_PRODUCTS_CFG = _AUTOMATION / "testData" / "products" / "productsconfig.json"
_ADDRESS_CFG  = _AUTOMATION / "testData" / "products" / "addressconfig.json"
_ENV_FILE     = _AUTOMATION / ".env"

# ── Read store credentials from automation .env ───────────────────────────────
def _read_env() -> dict[str, str]:
    env: dict[str, str] = {}
    if _ENV_FILE.exists():
        for line in _ENV_FILE.read_text(encoding="utf-8").splitlines():
            s = line.strip()
            if s.startswith("#") or "=" not in s:
                continue
            k, _, v = s.partition("=")
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env

_ENV = _read_env()
_STORE        = _ENV.get("STORE", "")
_ACCESS_TOKEN = _ENV.get("SHOPIFY_ACCESS_TOKEN", "")
_API_VERSION  = _ENV.get("SHOPIFY_API_VERSION", "2024-01")
_BASE_URL     = f"https://{_STORE}.myshopify.com/admin/api/{_API_VERSION}"

# ── Load config files ─────────────────────────────────────────────────────────
def _load_products() -> dict:
    if _PRODUCTS_CFG.exists():
        return json.loads(_PRODUCTS_CFG.read_text(encoding="utf-8"))
    logger.warning("productsconfig.json not found at %s", _PRODUCTS_CFG)
    return {}

def _load_addresses() -> dict:
    if _ADDRESS_CFG.exists():
        return json.loads(_ADDRESS_CFG.read_text(encoding="utf-8"))
    return {}

_PRODUCTS  = _load_products()
_ADDRESSES = _load_addresses()

# ── Shopify order creation ────────────────────────────────────────────────────
def _post_order(payload: dict, label: str, max_retries: int = 4) -> dict | None:
    """POST to Shopify orders API with 429 retry. Returns order dict or None."""
    url     = f"{_BASE_URL}/orders.json"
    headers = {
        "X-Shopify-Access-Token": _ACCESS_TOKEN,
        "Content-Type": "application/json",
    }
    for attempt in range(1, max_retries + 1):
        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=30)

            if resp.status_code == 429:
                retry_after = int(resp.headers.get("Retry-After", 10))
                wait = retry_after * attempt
                logger.warning("%s — 429 rate limit, waiting %ds (attempt %d/%d)",
                               label, wait, attempt, max_retries)
                time.sleep(wait)
                continue

            if not resp.ok:
                logger.error("%s — HTTP %s: %s", label, resp.status_code, resp.text[:300])
                return None

            return resp.json().get("order")

        except requests.RequestException as e:
            logger.warning("%s — network error (attempt %d/%d): %s", label, attempt, max_retries, e)
            if attempt < max_retries:
                time.sleep(5)

    logger.error("%s — gave up after %d retries", label, max_retries)
    return None


def create_order(
    product_type: str = "simple",
    address_type: str = "default",
    product_index: int = 0,
    quantity: int = 1,
) -> dict | None:
    """
    Create one Shopify order via the Admin REST API.

    Args:
        product_type:  "simple" | "variable" | "digital" | "dangerous"
        address_type:  "default" (US) | "UK" | "CA"
        product_index: which product from the list to use (default 0 = first)
        quantity:      line item quantity

    Returns:
        Shopify order dict {"id": ..., "name": "#1234", ...} or None on failure.
    """
    if not _STORE or not _ACCESS_TOKEN:
        logger.error("STORE or SHOPIFY_ACCESS_TOKEN not set in automation .env")
        return None

    # ── Pick product ──────────────────────────────────────────────────────────
    store_products = _PRODUCTS.get(_STORE, {})
    product_list   = store_products.get(product_type, [])

    if not product_list:
        # Fallback: try simple products
        product_list = store_products.get("simple", [])
        if not product_list:
            logger.error("No products configured for store '%s' type '%s'", _STORE, product_type)
            return None
        logger.warning("No '%s' products for store '%s' — falling back to simple", product_type, _STORE)

    product = product_list[min(product_index, len(product_list) - 1)]

    # ── Pick address ──────────────────────────────────────────────────────────
    addr = _ADDRESSES.get(address_type, _ADDRESSES.get("default", {}))
    if not addr:
        logger.error("No address config found for '%s'", address_type)
        return None

    shipping_address = {
        "first_name": "Test",
        "last_name":  "User",
        "phone":      "1234567890",
        "address1":   addr.get("street", "123 Main St"),
        "city":       addr.get("city", "Los Angeles"),
        "province":   addr.get("state", "CA"),
        "country":    addr.get("countryCode", "US"),
        "zip":        addr.get("zip", "90001"),
    }

    payload = {
        "order": {
            "email": "test.user@example.com",
            "line_items": [{
                "product_id": product["product_id"],
                "variant_id": product["variant_id"],
                "quantity":   quantity,
            }],
            "customer":         {"first_name": "Test", "last_name": "User", "email": "test.user@example.com"},
            "billing_address":  shipping_address,
            "shipping_address": shipping_address,
        }
    }

    label = f"order({product_type}/{address_type})"
    logger.info("Creating %s order via Shopify API…", label)
    order = _post_order(payload, label)

    if order:
        logger.info("Created order %s (id: %s)", order.get("name"), order.get("id"))
    return order


# ── Bulk order creation ───────────────────────────────────────────────────────

# For AC verification we don't need 50 orders — 5 is enough to prove bulk works.
# The full 50/100-order test lives in bulkAutoLabelGeneration.spec.ts.
_BULK_AC_COUNT = 5

# How many seconds to wait between bulk order creations (respect Shopify rate limit)
_BULK_DELAY_S = 2


def create_bulk_orders(
    count: int = _BULK_AC_COUNT,
    product_type: str = "simple",
    address_type: str = "default",
) -> list[dict]:
    """
    Create multiple Shopify orders for bulk AC verification.

    Strategy:
      1. Create 1 template order
      2. Clone it (count - 1) more times using the same payload
      This mirrors what TypeScript uploadBulkOrdersFromExisting() does.

    For AC verification, default count = 5 (not 50 — that's the Playwright suite's job).

    Returns list of created order dicts (name + id). Empty list on total failure.
    """
    if not _STORE or not _ACCESS_TOKEN:
        logger.error("STORE or SHOPIFY_ACCESS_TOKEN not set in automation .env")
        return []

    store_products = _PRODUCTS.get(_STORE, {})
    product_list   = store_products.get(product_type, []) or store_products.get("simple", [])
    if not product_list:
        logger.error("No products found for store '%s'", _STORE)
        return []

    product = product_list[0]
    addr    = _ADDRESSES.get(address_type, _ADDRESSES.get("default", {}))

    shipping_address = {
        "first_name": "Test",
        "last_name":  "User",
        "phone":      "1234567890",
        "address1":   addr.get("street", "123 Main St"),
        "city":       addr.get("city", "Los Angeles"),
        "province":   addr.get("state", "CA"),
        "country":    addr.get("countryCode", "US"),
        "zip":        addr.get("zip", "90001"),
    }

    payload = {
        "order": {
            "email": "test.user@example.com",
            "line_items": [{
                "product_id": product["product_id"],
                "variant_id": product["variant_id"],
                "quantity":   1,
            }],
            "customer":         {"first_name": "Test", "last_name": "User", "email": "test.user@example.com"},
            "billing_address":  shipping_address,
            "shipping_address": shipping_address,
        }
    }

    created: list[dict] = []
    logger.info("Creating %d bulk orders for AC verification…", count)

    for i in range(count):
        order = _post_order(payload, f"bulk-order-{i+1}/{count}")
        if order:
            created.append({"name": order.get("name"), "id": str(order.get("id"))})
            logger.info("  [%d/%d] Created %s", i + 1, count, order.get("name"))
        else:
            logger.warning("  [%d/%d] Failed — continuing", i + 1, count)

        if i < count - 1:
            time.sleep(_BULK_DELAY_S)

    logger.info("Bulk creation done: %d/%d orders created → %s",
                len(created), count, [o["name"] for o in created])
    return created


# ── Smart order resolver ──────────────────────────────────────────────────────

# What each scenario keyword maps to
_PRODUCT_TYPE_MAP = {
    "dangerous": "dangerous",
    "hazmat":    "dangerous",
    "dg ":       "dangerous",
    "variable":  "variable",
    "digital":   "digital",
    "virtual":   "digital",
    # everything else → simple
}

_ADDRESS_TYPE_MAP = {
    "canada":        "CA",
    " ca ":          "CA",
    "canadian":      "CA",
    "uk":            "UK",
    "united kingdom":"UK",
    "britain":       "UK",
    "london":        "UK",
    "international": "UK",   # default international → UK
    "cross-border":  "UK",
    "overseas":      "UK",
}

_BULK_KEYWORDS = [
    "bulk", "multiple orders", "50 orders", "100 orders",
    "all orders", "batch label", "bulk label", "bulk generate",
    "bulk auto", "auto-generate labels", "select all orders",
    "bulk actions", "bulk print", "bulk packing slip",
    "bulk download", "bulk pickup",
]

_NO_ORDER_KEYWORDS = [
    "settings", "configuration", "configure",
    "navigation", "next order", "previous order", "prev order",
    "next/previous", "pagination", "order grid", "orders grid",
    "filter", "tab shows", "status display", "app shows",
    "rate log", "rates log", "sidebar",
    "pickup scheduling", "schedule pickup",
]

_EXISTING_FULFILLED_KEYWORDS = [
    "return label", "generate return",
    "existing label", "download document", "label request",
    "label shows", "print document", "view label",
    "label generated", "already generated",
    "order summary navigation", "next/previous order",
    # Address update scenarios need an order WITH a label so the agent can cancel it first
    "address update", "edit address", "update address",
    "cancel label", "cancel the label", "after cancellation",
    "regenerate", "re-generate", "updated address", "new address",
]

_EXISTING_UNFULFILLED_KEYWORDS = [
    "shipping address change without label",  # only if explicitly no label yet
]


def resolve_order(scenario: str, order_decision: str) -> dict | list | None:
    """
    Called by the verifier when the plan says order_action = "create_new" or "create_bulk".
    Infers product type, address type, and quantity from scenario text.

    Returns:
      - Single order dict  for "create_new"
      - List of order dicts for "create_bulk"
      - None if no creation needed or creation failed
    """
    if order_decision not in ("create_new", "create_bulk"):
        return None

    s = scenario.lower()

    # Infer product type
    product_type = "simple"
    for keyword, ptype in _PRODUCT_TYPE_MAP.items():
        if keyword in s:
            product_type = ptype
            break

    # Infer address type
    address_type = "default"
    for keyword, atype in _ADDRESS_TYPE_MAP.items():
        if keyword in s:
            address_type = atype
            break

    if order_decision == "create_bulk":
        # Infer count from scenario text (e.g. "50 orders" → 50, but cap at 10 for AC verification)
        import re
        nums = re.findall(r"\b(\d+)\s+orders?\b", s)
        requested = int(nums[0]) if nums else _BULK_AC_COUNT
        # Cap at 10 for AC verification — full load test is in the Playwright suite
        count = min(requested, 10) if requested > 0 else _BULK_AC_COUNT
        logger.info(
            "resolve_order BULK: scenario='%s' → count=%d product=%s address=%s",
            scenario[:80], count, product_type, address_type,
        )
        return create_bulk_orders(count=count, product_type=product_type, address_type=address_type)

    logger.info(
        "resolve_order SINGLE: scenario='%s' → product=%s address=%s",
        scenario[:80], product_type, address_type,
    )
    return create_order(product_type=product_type, address_type=address_type)


def infer_order_decision(scenario: str) -> str:
    """
    Fallback: infer the order_action from the scenario text alone,
    in case Claude's plan JSON doesn't include order_action.

    Returns one of:
      "none"                 — no order needed
      "existing_fulfilled"   — need an order that already has a label
      "existing_unfulfilled" — need an existing unfulfilled order
      "create_new"           — need a fresh single order
      "create_bulk"          — need multiple fresh orders (bulk scenarios)
    """
    s = scenario.lower()

    # Bulk check FIRST — before any other check
    if any(kw in s for kw in _BULK_KEYWORDS):
        return "create_bulk"

    if any(kw in s for kw in _NO_ORDER_KEYWORDS):
        return "none"

    if any(kw in s for kw in _EXISTING_FULFILLED_KEYWORDS):
        return "existing_fulfilled"

    if any(kw in s for kw in _EXISTING_UNFULFILLED_KEYWORDS):
        return "existing_unfulfilled"

    # Any label generation scenario → fresh single order
    label_keywords = [
        "generate label", "auto-generate", "auto generate",
        "create label", "label generation",
        "dry ice", "alcohol", "battery", "signature",
        "hold at location", "hal ", "cod ", "insurance",
        "one rate", "fedex one rate",
        "domestic label", "international label",
        "manual label", "label request",
    ]
    if any(kw in s for kw in label_keywords):
        return "create_new"

    # Default: try existing unfulfilled
    return "existing_unfulfilled"
