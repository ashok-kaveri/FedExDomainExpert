"""Refresh Shopify auth.json by logging in with Playwright."""
import os, sys, time
from pathlib import Path
from dotenv import dotenv_values

sys.path.insert(0, os.path.dirname(__file__))
import config

_CODEBASE = Path(config.AUTOMATION_CODEBASE_PATH)
_AUTH_JSON = _CODEBASE / "auth.json"
_AUTO_ENV  = _CODEBASE / ".env"

creds = dotenv_values(_AUTO_ENV)
EMAIL    = creds.get("USER_EMAIL", "").strip()
PASSWORD = creds.get("USER_PASSWORD", "").strip()

if not EMAIL or not PASSWORD:
    print("ERROR: USER_EMAIL or USER_PASSWORD missing in automation .env")
    sys.exit(1)

from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome", headless=False)
    ctx = browser.new_context(viewport={"width": 1400, "height": 900})
    page = ctx.new_page()

    print("Navigating to Shopify admin login…")
    page.goto("https://accounts.shopify.com/lookup?rid=243d17d6-92e0-4abb-82c7-5ac3c12bee24")
    page.wait_for_load_state("domcontentloaded")
    page.wait_for_timeout(2000)
    print(f"URL: {page.url}")

    # Step 1: fill email and click Continue
    email_input = page.locator('input[type="email"], input[name="email"]').first
    email_input.wait_for(state="visible", timeout=10_000)
    print(f"Filling email: {EMAIL}")
    email_input.fill(EMAIL)
    page.wait_for_timeout(500)

    continue_btn = page.get_by_role("button", name="Continue with email")
    if continue_btn.count() > 0:
        continue_btn.click()
    else:
        page.keyboard.press("Enter")
    page.wait_for_timeout(3000)
    print(f"After email submit URL: {page.url}")

    # Step 2: fill password
    password_input = page.locator('input[type="password"]').first
    if password_input.is_visible(timeout=8_000):
        print("Filling password…")
        password_input.fill(PASSWORD)
        page.wait_for_timeout(500)
        login_btn = page.get_by_role("button", name="Log in")
        if login_btn.count() > 0 and login_btn.is_visible():
            login_btn.click()
        else:
            page.keyboard.press("Enter")
        page.wait_for_timeout(5000)
        print(f"After password submit URL: {page.url}")

    # Step 3: account selector if present
    if "accounts.shopify.com/select" in page.url:
        print("Selecting account…")
        acc = page.get_by_text(EMAIL, exact=False).first
        if acc.count() > 0:
            acc.click()
            page.wait_for_timeout(3000)

    # Step 4: wait up to 60s for admin
    print(f"Waiting for Shopify admin… current: {page.url}")
    for _ in range(12):
        if "admin.shopify.com" in page.url:
            break
        page.wait_for_timeout(5000)
        print(f"  still at: {page.url}")
    print(f"Final URL: {page.url}")

    # Save auth state
    ctx.storage_state(path=str(_AUTH_JSON))
    print(f"Saved auth.json → {_AUTH_JSON}")
    browser.close()

print("Done — auth.json refreshed.")
