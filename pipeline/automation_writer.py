"""
Automation Writer  —  Pipeline Step 5
======================================
Browser-assisted Playwright TypeScript code generation.

Flow:
  ① Find existing POM via registry + keyword matching (never create duplicates)
  ② Navigate to the real page with stored auth session → capture live elements
  ③a EXISTING POM → add new locators + methods (append only, no overwrite)
      Always create a SEPARATE new spec file for this card
  ③b NEW PAGE     → create POM with real locators + new spec + update fixtures.ts
  ④ Commit to automation/<branch> and push (never main)

Key rules enforced:
  - Import test/expect from '../../src/setup/fixtures' (not @playwright/test)
  - All POMs extend BasePage, locators are readonly class properties
  - this.appFrame for app iframe locators, this.page for Shopify admin
  - test.describe.configure({ mode: 'serial' }) on every describe block
  - Every test has at least one expect()
  - No page.waitForTimeout() > 3000ms, no test.only()
"""
import json
import logging
import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from textwrap import dedent

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage

import config

logger = logging.getLogger(__name__)

CODEBASE  = Path(config.AUTOMATION_CODEBASE_PATH)
SKILL_MD  = CODEBASE / "fedExSkill.md"
AUTH_JSON = CODEBASE / "auth.json"
ENV_FILE  = CODEBASE / ".env"


# ---------------------------------------------------------------------------
# POM Registry — maps feature areas to existing page objects
# ---------------------------------------------------------------------------
# Add entries here as new POMs are created.
# keywords: if any keyword appears in card_name.lower(), this POM is used.
# nav:      app navigation path for browser capture.

POM_REGISTRY: list[dict] = [
    {
        "id": "additionalServices",
        "file": "src/pages/app/settings/additionalServices.ts",
        "class": "AdditionalServices",
        "fixture": "additionalServices",
        "keywords": [
            "dry ice", "duties", "tax", "signature", "saturday delivery",
            "one rate", "alcohol", "dangerous goods", "hold at location",
            "additional service", "adult signature",
        ],
        "nav": "Settings > Additional Services",
        "app_path": "settings/additional-services",
    },
    {
        "id": "packagingSettingsPage",
        "file": "src/pages/app/settings/packagingSettingsPage.ts",
        "class": "PackagingSettingsPage",
        "fixture": "packagingSettingsPage",
        "keywords": ["packaging", "box", "weight based", "dimension", "pack items"],
        "nav": "Settings > Packaging",
        "app_path": "settings/packaging",
    },
    {
        "id": "manualLabelPage",
        "file": "src/pages/app/ManualLabelPage/ManualLabelPage.ts",
        "class": "GenerateLabelManuallyPage",
        "fixture": "manualLabelPage",
        "keywords": ["label", "generate label", "single label", "manual label", "label generation"],
        "nav": "Orders > Generate Label",
        "app_path": "orders",
    },
    {
        "id": "pickupPage",
        "file": "src/pages/app/PickupPage/PickupPage.ts",
        "class": "PickupPage",
        "fixture": "pickupPage",
        "keywords": ["pickup", "schedule pickup", "pick up"],
        "nav": "Shipping > Schedule Pickup",
        "app_path": "shipping/pickup",
    },
    {
        "id": "returnLabelPage",
        "file": "src/pages/app/returnLabelPage/returnLabelPage.ts",
        "class": "ReturnLabelPage",
        "fixture": "returnLabelPage",
        "keywords": ["return", "return label", "return setting"],
        "nav": "Orders > Return Label",
        "app_path": "return-labels",
    },
    {
        "id": "shippingPage",
        "file": "src/pages/app/ShippingPage/ShippingPage.ts",
        "class": "ShippingPage",
        "fixture": "shippingPage",
        "keywords": ["shipping rate", "rate setting", "carrier service", "rate adjustment",
                     "display name", "checkout rate"],
        "nav": "Settings > Rate Settings",
        "app_path": "settings/rate-settings",
    },
    {
        "id": "productsPage",
        "file": "src/pages/app/Products/productsPage_M.ts",
        "class": "ProductsPage_M",
        "fixture": "productsPage",
        "keywords": ["product", "shopify product"],
        "nav": "Products",
        "app_path": "products",
    },
    {
        "id": "orderSummaryPage",
        "file": "src/pages/app/OrderSummaryPage/OrderSummaryPage.ts",
        "class": "OrderSummaryPage",
        "fixture": "orderSummaryPage",
        "keywords": ["order summary", "label generated", "fulfillment", "order grid",
                     "orders page", "order list"],
        "nav": "Shipping > Orders",
        "app_path": "shipping",
    },
]

# Area → test folder mapping
AREA_FOLDER: dict[str, str] = {
    "additionalServices":    "tests/additionalServices",
    "packagingSettingsPage": "tests/packaging",
    "manualLabelPage":       "tests/label_generation",
    "pickupPage":            "tests/pickup",
    "returnLabelPage":       "tests/returnLabels",
    "shippingPage":          "tests/additionalServices",
    "productsPage":          "tests/product_Special_Service",
    "orderSummaryPage":      "tests/label_generation",
    "_new":                  "tests/additionalServices",
}


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class AutomationResult:
    kind: str                       # "existing_pom" | "new_pom"
    pom_file: str                   # relative path to POM file
    pom_class: str
    spec_file: str                  # new spec file path
    fixture_property: str           # pages.xxx name
    files_written: list[str] = field(default_factory=list)
    branch: str = ""
    pushed: bool = False
    push_error: str = ""
    error: str = ""
    skipped: bool = False
    browser_elements: str = ""      # raw captured elements from browser
    detection_reason: str = ""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _camel(text: str) -> str:
    words = re.sub(r"[^a-zA-Z0-9 ]", "", text).split()
    return (words[0].lower() + "".join(w.title() for w in words[1:])) if words else "feature"


def _pascal(text: str) -> str:
    return "".join(w.title() for w in re.sub(r"[^a-zA-Z0-9 ]", "", text).split()) or "Feature"


def _load_conventions() -> str:
    if SKILL_MD.exists():
        content = SKILL_MD.read_text(encoding="utf-8", errors="ignore")
        if content.startswith("---"):
            parts = content.split("---", 2)
            return parts[2].strip() if len(parts) >= 3 else content
        return content
    return ""


def _read_file(rel_path: str) -> str:
    for p in [CODEBASE / rel_path, Path(rel_path)]:
        if p.exists():
            return p.read_text(encoding="utf-8", errors="ignore")
    return ""


def _write_file(rel_path: str, content: str) -> str:
    abs_path = CODEBASE / rel_path
    abs_path.parent.mkdir(parents=True, exist_ok=True)
    abs_path.write_text(content, encoding="utf-8")
    return rel_path


def _get_store_url() -> str:
    """Read STORE from automation repo .env"""
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            if line.startswith("STORE="):
                val = line.split("=", 1)[1].strip().strip('"').strip("'")
                if val and not val.startswith("your-"):
                    return val
    return os.getenv("STORE", "")


# ---------------------------------------------------------------------------
# Step ①: Find existing POM
# ---------------------------------------------------------------------------

def find_pom(card_name: str) -> dict | None:
    """
    Match card name to an existing POM via keyword matching.
    Returns the registry entry or None if this is a new page.
    """
    lower = card_name.lower()
    for entry in POM_REGISTRY:
        if any(kw in lower for kw in entry["keywords"]):
            # Verify the file actually exists
            if (CODEBASE / entry["file"]).exists():
                logger.info("Matched existing POM: %s → %s", card_name, entry["file"])
                return entry
    logger.info("No existing POM matched for: %s → will create new", card_name)
    return None


# ---------------------------------------------------------------------------
# Step ②: Browser element capture
# ---------------------------------------------------------------------------

def capture_browser_elements(
    nav_description: str,
    app_path: str = "",
) -> str:
    """
    Use Python Playwright with the stored auth session to navigate to the
    relevant section and capture the accessibility tree.

    Returns a structured string describing real UI elements (buttons, inputs,
    headings, labels, checkboxes) for Claude to generate locators from.
    """
    if not AUTH_JSON.exists():
        return "auth.json not found — locators generated from test cases only."

    store_url = _get_store_url()
    if not store_url:
        return "STORE not set in .env — locators generated from test cases only."

    # Build the app URL
    app_base = f"https://{store_url}/admin/apps"
    if app_path:
        target_url = f"{app_base}/fedex-shipping/{app_path}"
    else:
        target_url = f"{app_base}/fedex-shipping"

    logger.info("Capturing browser elements from: %s", target_url)

    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(
                channel="chrome",
                headless=False,
                args=["--disable-blink-features=AutomationControlled"],
            )
            context = browser.new_context(
                storage_state=str(AUTH_JSON),
                viewport={"width": 1440, "height": 900},
            )
            page = context.new_page()

            # Navigate to the section
            page.goto(target_url, wait_until="networkidle", timeout=30000)
            page.wait_for_timeout(3000)  # let iframe load

            # Try to get accessibility tree from the app iframe
            iframe_locator = page.frame_locator('iframe[name="app-iframe"]')
            iframe_element = page.query_selector('iframe[name="app-iframe"]')

            elements: list[str] = []

            if iframe_element:
                frame = iframe_element.content_frame()
                if frame:
                    # Capture key elements from the iframe
                    ax_tree = frame.accessibility.snapshot(interesting_only=True)
                    if ax_tree:
                        elements.append(_format_ax_tree(ax_tree))

                    # Also capture visible text and roles for context
                    headings = frame.query_selector_all("h1, h2, h3, h4")
                    for h in headings[:10]:
                        txt = h.inner_text().strip()
                        if txt:
                            elements.append(f"heading: '{txt}'")

                    buttons = frame.query_selector_all("button:visible")
                    for b in buttons[:15]:
                        txt = (b.get_attribute("aria-label") or b.inner_text()).strip()
                        if txt:
                            elements.append(f"button: '{txt}'")

                    inputs = frame.query_selector_all("input:visible, select:visible, textarea:visible")
                    for inp in inputs[:20]:
                        name = inp.get_attribute("name") or ""
                        label = inp.get_attribute("aria-label") or inp.get_attribute("placeholder") or ""
                        input_type = inp.get_attribute("type") or "text"
                        elements.append(f"input[name='{name}'] type={input_type} label='{label}'")

                    checkboxes = frame.query_selector_all("input[type='checkbox']:visible")
                    for cb in checkboxes[:10]:
                        name = cb.get_attribute("name") or ""
                        elements.append(f"checkbox[name='{name}']")

            context.close()
            browser.close()

            if elements:
                result = f"=== Live UI elements from: {nav_description} ===\n"
                result += "\n".join(elements[:50])
                logger.info("Captured %d elements from browser", len(elements))
                return result
            return f"Page loaded but no elements captured for: {nav_description}"

    except Exception as e:
        logger.warning("Browser capture failed: %s", e)
        return f"Browser capture unavailable ({e}) — locators generated from test cases."


def _format_ax_tree(node: dict, depth: int = 0, lines: list | None = None) -> str:
    """Recursively flatten accessibility tree to readable lines."""
    if lines is None:
        lines = []
    if depth > 4 or len(lines) > 60:
        return "\n".join(lines)
    role = node.get("role", "")
    name = node.get("name", "")
    if role and name and role not in ("generic", "none", "presentation"):
        lines.append(f"{'  ' * depth}{role}: '{name}'")
    for child in node.get("children", []):
        _format_ax_tree(child, depth + 1, lines)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

ADD_TO_EXISTING_POM_PROMPT = dedent("""\
    You are a senior Playwright TypeScript automation engineer for the FedEx Shopify App.

    ## Project Conventions
    {conventions}

    ## Task: ADD new locators and methods to an EXISTING page object.
    DO NOT rewrite or remove existing code. ONLY append new readonly locators
    in the constructor and new action methods after the existing ones.

    Feature Card: {card_name}
    Test Cases (positive scenarios to automate):
    {test_cases}

    ## Live UI Elements Captured from Browser
    (Use these to generate accurate locators. Match names/roles exactly.)
    {browser_elements}

    ## Domain Expert: What Already Exists in the Codebase
    (From RAG — use these existing methods/locators directly instead of re-creating them)
    {rag_context}

    ## Existing POM file ({pom_file}):
    {existing_pom}

    Return the COMPLETE updated file — existing code intact + new additions appended.
    Start with: === UPDATED POM: {pom_file} ===
    Then the full TypeScript. No markdown fences.

    Rules for new locators:
    - Add as readonly properties at the END of the existing property list
    - Initialize in constructor AFTER existing initializations
    - Use this.appFrame.getByRole(...) or this.appFrame.getByLabel(...) where possible
    - Use this.appFrame.locator('[name="..."]') for inputs with known names
    - Group new locators with a comment: // --- {card_name} ---
    - Add new action methods AFTER existing methods, also with the comment group
""")

NEW_SPEC_PROMPT = dedent("""\
    You are a senior Playwright TypeScript automation engineer for the FedEx Shopify App.

    ## Project Conventions
    {conventions}

    ## Task: Create a NEW spec file for a specific feature card.
    The page object already exists — you just write the tests using it.

    Feature Card: {card_name}
    Test Cases (positive scenarios to automate):
    {test_cases}

    Page Object class: {pom_class}
    Fixture property:  pages.{fixture}  (already registered — do NOT touch fixtures.ts)

    Spec file path: {spec_path}

    ## Live UI Elements (for context on what's actually on the page)
    {browser_elements}

    ## Domain Expert Context (existing POM methods and patterns to follow)
    {rag_context}

    Generate the complete spec file.
    Start with: === SPEC FILE: {spec_path} ===

    Rules:
    - import {{ test, expect }} from '{fixtures_import}'
    - test.describe.configure({{ mode: 'serial' }})
    - Use pages.{fixture} to call methods from the page object
    - Every test must have at least one expect()
    - No test.only(), no waitForTimeout() > 3000
    - Use descriptive test names matching the test case scenarios
    - Add tag: {{ tag: '@smoke' }} to the describe block
""")

NEW_POM_PROMPT = dedent("""\
    You are a senior Playwright TypeScript automation engineer for the FedEx Shopify App.

    ## Project Conventions
    {conventions}

    ## Task: Create a BRAND NEW page object for a page that doesn't exist yet.

    Feature Card: {card_name}
    POM file path: {pom_path}
    Class name: {class_name}

    ## Live UI Elements Captured from Browser
    (Use EXACTLY these element names/roles for locators — don't invent.)
    {browser_elements}

    ## Domain Expert Context (existing POM methods and patterns to follow)
    {rag_context}

    ## Existing POM for style reference:
    {pom_sample}

    Generate the complete POM file.
    Start with: === NEW POM: {pom_path} ===

    Rules:
    - import {{ Page, Locator }} from '@playwright/test'
    - import {{ BasePage }} from '../../basePage' (adjust relative path as needed)
    - export class {class_name} extends BasePage
    - All locators as readonly properties, initialized in constructor
    - this.appFrame.getByRole / getByLabel / getByText / locator for iframe elements
    - Add action methods for each interaction the tests will need
""")

FIXTURES_UPDATE_PROMPT = dedent("""\
    Add a new page object to the fixtures.ts file.

    New class: {class_name}
    Import from: {import_path}
    Pages type property: {property_name}: {class_name}
    Instantiated as: {property_name}: new {class_name}(page)

    Current fixtures.ts:
    {fixtures_content}

    Return the COMPLETE updated file.
    Start with: === UPDATED FILE: src/setup/fixtures.ts ===
    Then full TypeScript. No markdown fences.
""")

REVIEW_PROMPT = dedent("""\
    Review this Playwright TypeScript file for the FedEx Shopify App.
    Check:
    1. Imports test/expect from fixtures path (not @playwright/test) — for spec files
    2. All locators are readonly class properties (not inside methods)
    3. Uses this.appFrame for app iframe elements (not this.page for app content)
    4. test.describe.configure({{ mode: 'serial' }}) present — for spec files
    5. Every test has at least one expect() — for spec files
    6. No waitForTimeout > 3000
    7. No test.only()

    File: {file_path}
    {content}

    Respond JSON:
    {{"passed": true/false, "issues": [], "fixed_content": "corrected content or empty"}}
""")


# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------

def _git(args: list[str]) -> tuple[bool, str]:
    r = subprocess.run(
        ["git", "-C", str(CODEBASE)] + args,
        capture_output=True, text=True, timeout=30,
    )
    return r.returncode == 0, (r.stdout + r.stderr).strip()


def _current_branch() -> str:
    ok, out = _git(["branch", "--show-current"])
    return out.strip() if ok else "main"


def _create_branch(branch: str) -> bool:
    ok, _ = _git(["checkout", "-b", branch])
    if not ok:
        ok, _ = _git(["checkout", branch])
    return ok


def _commit(files: list[str], message: str) -> bool:
    _git(["add"] + [str(CODEBASE / f) for f in files])
    ok, out = _git(["commit", "-m", message])
    if not ok:
        logger.warning("Commit issue: %s", out)
    return ok


def _push(branch: str) -> tuple[bool, str]:
    return _git(["push", "-u", "origin", branch])


# ---------------------------------------------------------------------------
# Code review
# ---------------------------------------------------------------------------

def _review(file_path: str, content: str, claude: ChatAnthropic) -> str:
    try:
        resp = claude.invoke([HumanMessage(content=REVIEW_PROMPT.format(
            file_path=file_path, content=content[:3500]
        ))])
        raw = re.sub(r"```(?:json)?", "", resp.content).strip().rstrip("`")
        data = json.loads(raw)
        if not data.get("passed") and data.get("fixed_content"):
            logger.info("Auto-fixed review issues in %s: %s", file_path, data.get("issues"))
            return data["fixed_content"]
    except Exception as e:
        logger.debug("Review step skipped: %s", e)
    return content


# ---------------------------------------------------------------------------
# Parse output blocks
# ---------------------------------------------------------------------------

def _parse_block(raw: str, marker: str) -> str:
    """Parse content after === MARKER: path === line."""
    m = re.search(rf"=== {marker}:.+?===\n([\s\S]+)", raw)
    if m:
        body = m.group(1).strip()
        body = re.sub(r"^```(?:typescript|ts)?\n?", "", body)
        return re.sub(r"\n?```$", "", body)
    return raw.strip()


# ---------------------------------------------------------------------------
# Spec path helper
# ---------------------------------------------------------------------------

def _spec_path(card_name: str, pom_id: str) -> str:
    folder = AREA_FOLDER.get(pom_id, AREA_FOLDER["_new"])
    return f"{folder}/{_camel(card_name)}.spec.ts"


def _fixtures_import(spec_path: str) -> str:
    """Calculate relative import path from spec to fixtures.ts."""
    depth = spec_path.count("/")
    return "../" * depth + "src/setup/fixtures"


def _query_domain_expert(card_name: str, test_cases: str) -> tuple[str, list[str]]:
    """
    Query the Domain Expert RAG to get existing POM content, known UI element
    texts, and nav paths for this feature area.

    Returns:
        rag_context:      Full text of relevant existing POM/test docs
        known_ui_texts:   UI element texts already in the codebase (to skip re-capturing)
    """
    try:
        from rag.vectorstore import search

        # Find existing POM + locators for this feature
        pom_docs  = search(f"page object TypeScript locators {card_name}", k=4)
        # Find navigation patterns and test files
        nav_docs  = search(f"navigation test spec {card_name} selectAppMenu appPath", k=3)

        all_docs = pom_docs + nav_docs
        if not all_docs:
            return "", []

        context_parts = ["=== Domain Expert: Existing Code Knowledge ==="]
        full_text = ""
        for doc in all_docs:
            src = doc.metadata.get("source", doc.metadata.get("source_url", ""))
            context_parts.append(f"\n--- {src} ---\n{doc.page_content}")
            full_text += doc.page_content + "\n"

        rag_context = "\n".join(context_parts)

        # Extract actual UI text strings already used as locators in the codebase
        # e.g. getByRole('button', { name: 'Save' }) → 'Save'
        #      getByLabel('Dry ice weight') → 'Dry ice weight'
        #      getByText('Signature Required') → 'Signature Required'
        ui_texts: list[str] = []
        ui_texts += re.findall(r"getByRole\([^,)]+,\s*\{\s*name:\s*['\"]([^'\"]+)['\"]", full_text)
        ui_texts += re.findall(r"getByLabel\(['\"]([^'\"]+)['\"]", full_text)
        ui_texts += re.findall(r"getByText\(['\"]([^'\"]+)['\"]", full_text)
        ui_texts += re.findall(r"getByPlaceholder\(['\"]([^'\"]+)['\"]", full_text)
        known_ui_texts = list({t.lower().strip() for t in ui_texts if t.strip()})

        logger.info(
            "Domain Expert: %d docs, %d known UI texts for '%s'",
            len(all_docs), len(known_ui_texts), card_name,
        )
        return rag_context, known_ui_texts

    except Exception as exc:
        logger.warning("Domain expert query failed: %s", exc)
        return "", []


# ---------------------------------------------------------------------------
# Main flows
# ---------------------------------------------------------------------------

def _handle_existing_pom(
    card_name: str,
    test_cases: str,
    pom_entry: dict,
    browser_elements: str,
    claude: ChatAnthropic,
    dry_run: bool,
    rag_context: str = "",
) -> AutomationResult:
    """
    Feature uses an existing POM → add new locators/methods + create new spec.
    """
    pom_file     = pom_entry["file"]
    pom_class    = pom_entry["class"]
    fixture_prop = pom_entry["fixture"]
    spec_path    = _spec_path(card_name, pom_entry["id"])
    conventions  = _load_conventions()[:3000]

    existing_pom = _read_file(pom_file)
    if not existing_pom:
        return AutomationResult(
            kind="existing_pom", pom_file=pom_file, pom_class=pom_class,
            spec_file=spec_path, fixture_property=fixture_prop,
            error=f"Could not read existing POM: {pom_file}",
        )

    files_written = []

    # ── Update POM: add new locators + methods ───────────────────────────
    pom_prompt = ADD_TO_EXISTING_POM_PROMPT.format(
        conventions=conventions,
        card_name=card_name,
        test_cases=test_cases,
        browser_elements=browser_elements,
        pom_file=pom_file,
        existing_pom=existing_pom[:4000],
        rag_context=rag_context[:2000],
    )
    pom_resp = claude.invoke([HumanMessage(content=pom_prompt)])
    updated_pom = _parse_block(pom_resp.content.strip(), "UPDATED POM")
    updated_pom = _review(pom_file, updated_pom, claude)

    if not dry_run and updated_pom and updated_pom != existing_pom:
        _write_file(pom_file, updated_pom)
        files_written.append(pom_file)
        logger.info("Updated POM: %s", pom_file)

    # ── Generate new spec ────────────────────────────────────────────────
    spec_prompt = NEW_SPEC_PROMPT.format(
        conventions=conventions,
        card_name=card_name,
        test_cases=test_cases,
        pom_class=pom_class,
        fixture=fixture_prop,
        spec_path=spec_path,
        browser_elements=browser_elements,
        fixtures_import=_fixtures_import(spec_path),
        rag_context=rag_context[:1000],
    )
    spec_resp = claude.invoke([HumanMessage(content=spec_prompt)])
    spec_content = _parse_block(spec_resp.content.strip(), "SPEC FILE")
    spec_content = _review(spec_path, spec_content, claude)

    if not dry_run and spec_content:
        _write_file(spec_path, spec_content)
        files_written.append(spec_path)
        logger.info("Created spec: %s", spec_path)

    return AutomationResult(
        kind="existing_pom",
        pom_file=pom_file,
        pom_class=pom_class,
        spec_file=spec_path,
        fixture_property=fixture_prop,
        files_written=files_written,
        browser_elements=browser_elements[:300],
        detection_reason=f"Matched existing POM via keywords → {pom_file}",
        skipped=dry_run,
    )


def _handle_new_pom(
    card_name: str,
    test_cases: str,
    browser_elements: str,
    claude: ChatAnthropic,
    dry_run: bool,
    rag_context: str = "",
) -> AutomationResult:
    """
    Brand-new page → generate POM + spec + update fixtures.ts.
    """
    class_name   = _pascal(card_name) + "Page"
    fixture_prop = _camel(card_name) + "Page"
    pom_file     = f"src/pages/app/{_pascal(card_name)}/{_pascal(card_name)}.ts"
    spec_path    = _spec_path(card_name, "_new")
    conventions  = _load_conventions()[:3000]
    pom_sample   = ""

    # Load one existing POM for style reference
    for entry in POM_REGISTRY:
        sample = _read_file(entry["file"])
        if sample:
            pom_sample = f"// {entry['file']}\n{sample[:800]}"
            break

    files_written = []

    # ── Generate new POM ─────────────────────────────────────────────────
    pom_prompt = NEW_POM_PROMPT.format(
        conventions=conventions,
        card_name=card_name,
        pom_path=pom_file,
        class_name=class_name,
        browser_elements=browser_elements,
        pom_sample=pom_sample,
        rag_context=rag_context[:2000],
    )
    pom_resp = claude.invoke([HumanMessage(content=pom_prompt)])
    pom_content = _parse_block(pom_resp.content.strip(), "NEW POM")
    pom_content = _review(pom_file, pom_content, claude)

    if not dry_run and pom_content:
        _write_file(pom_file, pom_content)
        files_written.append(pom_file)
        logger.info("Created POM: %s", pom_file)

    # ── Generate spec ────────────────────────────────────────────────────
    spec_prompt = NEW_SPEC_PROMPT.format(
        conventions=conventions,
        card_name=card_name,
        test_cases=test_cases,
        pom_class=class_name,
        fixture=fixture_prop,
        spec_path=spec_path,
        browser_elements=browser_elements,
        fixtures_import=_fixtures_import(spec_path),
        rag_context=rag_context[:1000],
    )
    spec_resp = claude.invoke([HumanMessage(content=spec_prompt)])
    spec_content = _parse_block(spec_resp.content.strip(), "SPEC FILE")
    spec_content = _review(spec_path, spec_content, claude)

    if not dry_run and spec_content:
        _write_file(spec_path, spec_content)
        files_written.append(spec_path)
        logger.info("Created spec: %s", spec_path)

    # ── Update fixtures.ts ───────────────────────────────────────────────
    if not dry_run:
        fixtures_content = _read_file("src/setup/fixtures.ts")
        if fixtures_content:
            # relative import from fixtures.ts → new POM
            import_path = f"../pages/app/{_pascal(card_name)}/{_pascal(card_name)}"
            fix_prompt = FIXTURES_UPDATE_PROMPT.format(
                class_name=class_name,
                import_path=import_path,
                property_name=fixture_prop,
                fixtures_content=fixtures_content[:4000],
            )
            fix_resp = claude.invoke([HumanMessage(content=fix_prompt)])
            updated_fix = _parse_block(fix_resp.content, "UPDATED FILE")
            if updated_fix:
                _write_file("src/setup/fixtures.ts", updated_fix)
                files_written.append("src/setup/fixtures.ts")
                logger.info("Updated fixtures.ts")

    return AutomationResult(
        kind="new_pom",
        pom_file=pom_file,
        pom_class=class_name,
        spec_file=spec_path,
        fixture_property=fixture_prop,
        files_written=files_written,
        browser_elements=browser_elements[:300],
        detection_reason="No existing POM matched — creating new page object",
        skipped=dry_run,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def write_automation(
    card_name: str,
    test_cases_markdown: str,
    acceptance_criteria: str = "",
    branch_name: str = "",
    dry_run: bool = False,
    push: bool = False,
    chrome_trace_context: str = "",
) -> dict:
    """
    Generate or update Playwright automation code for a Trello card.

    Args:
        card_name:             Feature card title
        test_cases_markdown:   Approved test cases (all types)
        acceptance_criteria:   Additional AC context
        branch_name:           Git branch (auto-generated as automation/<slug> if empty)
        dry_run:               Generate code preview without writing to disk
        push:                  Push branch to origin after commit
        chrome_trace_context:  Pre-captured UITrace context string from chrome_agent.
                               When provided, skips the internal capture_browser_elements()
                               call and uses this richer, multi-step agent trace instead.

    Returns dict suitable for display in the Streamlit dashboard.
    """
    if not config.ANTHROPIC_API_KEY:
        return {"error": "ANTHROPIC_API_KEY not set", "skipped": True}
    if not CODEBASE.exists():
        return {"error": f"Codebase not found: {CODEBASE}", "skipped": True}

    claude = ChatAnthropic(
        model=config.CLAUDE_SONNET_MODEL,
        api_key=config.ANTHROPIC_API_KEY,
        temperature=0.15,
        max_tokens=4096,
    )

    # ── ① Find existing POM ───────────────────────────────────────────────
    pom_entry = find_pom(card_name)

    # ── ①b Query Domain Expert RAG for existing code context ─────────────
    rag_context, _known_ui_texts = _query_domain_expert(card_name, test_cases_markdown)

    # ── ② Browser elements: prefer Chrome Agent trace, fall back to snapshot ─
    if chrome_trace_context:
        # Rich multi-step trace from the agentic explorer — grounded in real UI
        browser_elements = chrome_trace_context
        logger.info("Using Chrome Agent trace context for '%s' (%d chars)", card_name, len(chrome_trace_context))
    else:
        # One-shot accessibility snapshot (original behaviour)
        app_path = pom_entry["app_path"] if pom_entry else ""
        nav_desc = pom_entry["nav"] if pom_entry else card_name
        browser_elements = capture_browser_elements(nav_desc, app_path)

    # ── ③ Checkout branch ────────────────────────────────────────────────
    target_branch = branch_name or f"automation/{_slugify(card_name)[:40]}"
    if not dry_run:
        _create_branch(target_branch)

    # ── ④ Generate code ───────────────────────────────────────────────────
    if pom_entry:
        result = _handle_existing_pom(
            card_name, test_cases_markdown, pom_entry, browser_elements, claude, dry_run,
            rag_context=rag_context,
        )
    else:
        result = _handle_new_pom(
            card_name, test_cases_markdown, browser_elements, claude, dry_run,
            rag_context=rag_context,
        )

    result.branch = target_branch if not dry_run else ""

    # ── ⑤ Commit ─────────────────────────────────────────────────────────
    if not dry_run and result.files_written:
        verb = "update" if result.kind == "existing_pom" else "add"
        _commit(
            result.files_written,
            f"test(automation): {verb} Playwright tests for '{card_name}'\n\n"
            f"Kind: {result.kind} | Files: {len(result.files_written)}\n"
            f"Branch: {target_branch} — review before merging to main.",
        )

    # ── ⑥ Push (only if requested) ────────────────────────────────────────
    if not dry_run and push and result.files_written:
        ok, out = _push(target_branch)
        result.pushed = ok
        result.push_error = "" if ok else out
        if not ok:
            logger.warning("Push failed: %s", out)

    return {
        "kind": result.kind,
        "pom_file": result.pom_file,
        "spec_file": result.spec_file,
        "fixture_property": result.fixture_property,
        "files_written": result.files_written,
        "branch": result.branch,
        "pushed": result.pushed,
        "push_error": result.push_error,
        "error": result.error,
        "skipped": result.skipped,
        "browser_elements": result.browser_elements,
        "detection_reason": result.detection_reason,
    }
