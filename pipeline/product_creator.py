"""
Product Creator  —  AI QA Agent helper
=======================================
Creates Shopify products with many variants via REST API.
Used when AC scenarios require a product with 250+ variants
that doesn't yet exist in the test store.

Reads store credentials from the automation .env (same as order_creator.py).

Usage:
    from pipeline.product_creator import create_high_variant_product, find_high_variant_product

    # Check if a 250-variant product already exists
    product = find_high_variant_product(min_variants=250)

    # Create one if not found
    if not product:
        product = create_high_variant_product(variant_count=250)
    # → {"id": 123, "title": "Test Product 250 Variants", "variant_count": 250, "admin_url": "..."}
"""
from __future__ import annotations
import itertools
import json
import logging
import time
from pathlib import Path

import requests

import config

logger = logging.getLogger(__name__)

# ── Credentials (same .env as order_creator.py) ───────────────────────────────
_AUTOMATION_PATH = (config.AUTOMATION_CODEBASE_PATH or "").strip()
_AUTOMATION  = Path(_AUTOMATION_PATH) if _AUTOMATION_PATH else None
_ENV_FILE    = _AUTOMATION / ".env" if _AUTOMATION else None


def _read_env() -> dict[str, str]:
    env: dict[str, str] = {}
    if _ENV_FILE and _ENV_FILE.exists():
        for line in _ENV_FILE.read_text(encoding="utf-8").splitlines():
            s = line.strip()
            if s.startswith("#") or "=" not in s:
                continue
            k, _, v = s.partition("=")
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env


_ENV          = _read_env()
_STORE        = _ENV.get("STORE", "")
_ACCESS_TOKEN = _ENV.get("SHOPIFY_ACCESS_TOKEN", "")
_API_VERSION  = _ENV.get("SHOPIFY_API_VERSION", "2024-01")
_BASE_URL     = f"https://{_STORE}.myshopify.com/admin/api/{_API_VERSION}"


def _headers() -> dict:
    return {
        "X-Shopify-Access-Token": _ACCESS_TOKEN,
        "Content-Type": "application/json",
    }


def _request(method: str, url: str, payload: dict | None = None, max_retries: int = 3) -> dict | None:
    """Generic Shopify REST request with 429 retry."""
    for attempt in range(1, max_retries + 1):
        try:
            resp = requests.request(method, url, json=payload, headers=_headers(), timeout=30)
            if resp.status_code == 429:
                wait = int(resp.headers.get("Retry-After", 10)) * attempt
                logger.warning("429 rate limit — waiting %ds (attempt %d/%d)", wait, attempt, max_retries)
                time.sleep(wait)
                continue
            if not resp.ok:
                logger.error("HTTP %s: %s", resp.status_code, resp.text[:300])
                return None
            return resp.json()
        except requests.RequestException as e:
            logger.warning("Network error (attempt %d/%d): %s", attempt, max_retries, e)
            if attempt < max_retries:
                time.sleep(5)
    return None


# ── Variant generation ────────────────────────────────────────────────────────

# 5 × 10 × 5 = 250 combinations
_SIZES   = ["XS", "S", "M", "L", "XL"]
_COLORS  = ["Red", "Blue", "Green", "Black", "White", "Yellow", "Orange", "Purple", "Pink", "Brown"]
_STYLES  = ["Classic", "Modern", "Sport", "Casual", "Formal"]


def _build_variants(count: int) -> list[dict]:
    """Generate `count` variant dicts with option1/option2/option3 values."""
    combos = list(itertools.product(_SIZES, _COLORS, _STYLES))[:count]
    variants = []
    for size, color, style in combos:
        sku = f"SKU-{size}-{color[:3].upper()}-{style[:3].upper()}"
        variants.append({
            "option1": size,
            "option2": color,
            "option3": style,
            "price": "10.00",
            "weight": 0.5,
            "weight_unit": "kg",
            "sku": sku,
            "inventory_management": None,
        })
    return variants


# ── Core API calls ────────────────────────────────────────────────────────────

def _create_product_shell(title: str, variant_count: int, first_batch: list[dict]) -> dict | None:
    """Create product with first 100 variants (Shopify REST limit per create)."""
    payload = {
        "product": {
            "title": title,
            "body_html": f"Test product with {variant_count} variants for AC verification",
            "vendor": "Test",
            "product_type": "Test",
            "status": "active",
            "options": [
                {"name": "Size"},
                {"name": "Color"},
                {"name": "Style"},
            ],
            "variants": first_batch,
        }
    }
    result = _request("POST", f"{_BASE_URL}/products.json", payload)
    return result.get("product") if result else None


def _add_variant(product_id: int, variant: dict) -> bool:
    """Add a single variant to an existing product."""
    result = _request("POST", f"{_BASE_URL}/products/{product_id}/variants.json", {"variant": variant})
    return result is not None


# ── Public API ────────────────────────────────────────────────────────────────

def create_high_variant_product(variant_count: int = 250, title: str | None = None) -> dict | None:
    """
    Create a Shopify product with `variant_count` variants.

    Strategy:
      1. Create product with first 100 variants (REST API limit per create call)
      2. Add remaining variants one-by-one via POST /variants (rate-limited)

    Returns:
      {
        "id": 123456,
        "title": "Test Product 250 Variants",
        "variant_count": 250,
        "admin_url": "https://admin.shopify.com/store/{store}/products/123456"
      }
      or None on failure.
    """
    if not _STORE or not _ACCESS_TOKEN:
        logger.error("STORE or SHOPIFY_ACCESS_TOKEN not set in automation .env")
        return None

    _title = title or f"Test Product {variant_count} Variants"
    logger.info("Creating product '%s' with %d variants…", _title, variant_count)

    variants = _build_variants(variant_count)
    first_batch = variants[:100]
    remaining   = variants[100:]

    # Step 1: create product shell with first 100 variants
    product = _create_product_shell(_title, variant_count, first_batch)
    if not product:
        logger.error("Failed to create product shell")
        return None

    product_id = product["id"]
    logger.info("Product created (id=%s) — adding %d more variants…", product_id, len(remaining))

    # Step 2: add remaining variants in batches with rate limit respect
    success_count = len(first_batch)
    for i, variant in enumerate(remaining):
        ok = _add_variant(product_id, variant)
        if ok:
            success_count += 1
        else:
            logger.warning("Failed to add variant %d/%d — continuing", i + 1, len(remaining))
        # Shopify allows ~2 req/s on non-Plus — stay safe
        time.sleep(0.6)

    logger.info("Product '%s' created with %d/%d variants (id=%s)",
                _title, success_count, variant_count, product_id)

    store_slug = _STORE.split(".")[0] if "." in _STORE else _STORE
    return {
        "id":            product_id,
        "title":         _title,
        "variant_count": success_count,
        "admin_url":     f"https://admin.shopify.com/store/{store_slug}/products/{product_id}",
    }


def find_high_variant_product(min_variants: int = 250) -> dict | None:
    """
    Search existing products for one with >= min_variants variants.
    Returns product summary dict or None if not found.

    Uses GET /products.json with fields=id,title,variants — pages through
    up to 5 pages (250 products) looking for a match.
    """
    if not _STORE or not _ACCESS_TOKEN:
        return None

    page_info = None
    for page in range(5):
        url = f"{_BASE_URL}/products.json?limit=50&fields=id,title,variants"
        if page_info:
            url += f"&page_info={page_info}"

        result = _request("GET", url)
        if not result:
            break

        for p in result.get("products", []):
            v_count = len(p.get("variants", []))
            if v_count >= min_variants:
                product_id = p["id"]
                store_slug = _STORE.split(".")[0] if "." in _STORE else _STORE
                logger.info("Found existing product '%s' with %d variants (id=%s)",
                            p["title"], v_count, product_id)
                return {
                    "id":            product_id,
                    "title":         p["title"],
                    "variant_count": v_count,
                    "admin_url":     f"https://admin.shopify.com/store/{store_slug}/products/{product_id}",
                }

        # Check for next page via Link header (cursor pagination)
        # Simple approach: if fewer than 50 products returned, we've reached the end
        if len(result.get("products", [])) < 50:
            break

    return None


def get_or_create_high_variant_product(variant_count: int = 250) -> dict | None:
    """
    Check if a high-variant product already exists; create one if not.
    This is the main entry point called by the AI QA Agent.
    """
    logger.info("Looking for existing product with %d+ variants…", variant_count)
    existing = find_high_variant_product(min_variants=variant_count)
    if existing:
        logger.info("Reusing existing product: %s", existing["title"])
        return existing

    logger.info("No existing product found — creating one with %d variants…", variant_count)
    return create_high_variant_product(variant_count=variant_count)
