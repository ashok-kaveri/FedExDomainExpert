"""
Test Writer — New Feature  (Step 5a)
=====================================
Generates a brand-new Playwright TypeScript spec + Page Object Model for
a feature that has no existing automation coverage.

Flow:
  1. Read acceptance criteria from the card
  2. Browse the QA app with Playwright to observe the real UI
  3. Claude generates spec file + page object following the project's POM conventions
  4. Writes files to the automation repo configured by `AUTOMATION_CODEBASE_PATH`
  5. Returns file paths for the vector updater and doc generator

Usage:
    from pipeline.test_writer.new_feature import generate_new_feature_tests
    result = generate_new_feature_tests(
        card_name="FedEx Hold at Location toggle",
        acceptance_criteria="...",
        app_url="https://your-store.myshopify.com/admin/apps/fedex",
    )
"""
from __future__ import annotations
import logging
import re
import subprocess
import sys
import tempfile
import base64
from pathlib import Path
from textwrap import dedent

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage

import config

logger = logging.getLogger(__name__)

CODEBASE_PATH = Path(config.AUTOMATION_CODEBASE_PATH) if config.AUTOMATION_CODEBASE_PATH else None


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

SPEC_GENERATOR_PROMPT = dedent("""\
    You are a senior test automation engineer for the FedEx Shopify App.
    You write Playwright + TypeScript tests following the Page Object Model (POM).

    PROJECT CONVENTIONS (follow exactly):
    - Test files live in: tests/<feature-area>/<feature-name>.spec.ts
    - Page objects live in: pages/<FeatureName>Page.ts
    - All tests use: import {{ test, expect }} from '@playwright/test';
    - Page objects extend nothing — plain TypeScript classes
    - Page object constructor takes: constructor(private page: Page) {{}}
    - Use descriptive test.describe() blocks
    - Use test.beforeEach() for navigation/setup
    - Assertions use expect() from @playwright/test
    - Test IDs follow: test-<component>-<action> pattern where possible
    - Always add: test.setTimeout(90_000); for label generation tests

    FEATURE TO TEST:
    Card: {card_name}

    Acceptance Criteria:
    {acceptance_criteria}

    OBSERVED UI (screenshot analysis):
    {ui_observations}

    EXISTING PAGE OBJECTS FOR REFERENCE:
    {existing_pom_samples}

    Generate TWO files:

    === FILE 1: tests/{test_path}.spec.ts ===
    [full spec file content]

    === FILE 2: pages/{page_name}Page.ts ===
    [full page object content]

    Use the exact === FILE N: path === delimiter format.
    Write complete, working TypeScript. No placeholders.
""")

UI_OBSERVER_PROMPT = dedent("""\
    You are examining a screenshot of the FedEx Shopify App admin panel.
    Describe what you see in detail:
    - What UI elements are visible (buttons, inputs, toggles, tables)?
    - What labels/text are shown?
    - What is the current state (enabled/disabled, selected/empty)?
    Keep it factual. 3-5 sentences.
""")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _take_screenshot(url: str, out_path: str) -> bool:
    try:
        r = subprocess.run(
            [sys.executable, "-m", "playwright", "screenshot",
             "--browser", "chromium", "--full-page", url, out_path],
            capture_output=True, text=True, timeout=30,
        )
        return r.returncode == 0
    except Exception as e:
        logger.warning("Screenshot failed: %s", e)
        return False


def _encode_image(path: str) -> str:
    with open(path, "rb") as f:
        return base64.standard_b64encode(f.read()).decode()


def _observe_ui(url: str, claude: ChatAnthropic) -> str:
    """Take a screenshot and have Claude describe the UI."""
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        tmp = f.name
    if not _take_screenshot(url, tmp) or not Path(tmp).exists():
        return "Screenshot unavailable — generating tests from AC only."

    img_b64 = _encode_image(tmp)
    msg = HumanMessage(content=[
        {"type": "text", "text": UI_OBSERVER_PROMPT},
        {"type": "image", "source": {"type": "base64",
                                      "media_type": "image/png",
                                      "data": img_b64}},
    ])
    return claude.invoke([msg]).content.strip()


def _load_pom_samples(n: int = 2) -> str:
    """Load a couple of existing page objects as style reference."""
    pages_dir = CODEBASE_PATH / "pages"
    if not pages_dir.exists():
        return "No existing page objects found."
    samples = []
    for ts_file in list(pages_dir.glob("*.ts"))[:n]:
        content = ts_file.read_text(encoding="utf-8", errors="ignore")
        samples.append(f"// {ts_file.name}\n{content[:800]}")
    return "\n\n".join(samples) or "No existing page objects found."


def _sanitise_path(card_name: str) -> tuple[str, str]:
    """Convert 'FedEx Hold at Location toggle' → ('holdAtLocation', 'HoldAtLocation')"""
    words = re.sub(r"[^a-zA-Z0-9 ]", "", card_name).split()
    camel = words[0].lower() + "".join(w.title() for w in words[1:]) if words else "feature"
    pascal = "".join(w.title() for w in words) if words else "Feature"
    # guess test area from card name
    area_map = {
        "label": "labels", "rate": "rates", "pickup": "pickup",
        "return": "returnLabels", "order": "orders", "setting": "settings",
        "notification": "notifications", "bulk": "bulkOrders",
        "location": "locations", "product": "products",
    }
    area = "general"
    for keyword, folder in area_map.items():
        if keyword in card_name.lower():
            area = folder
            break
    return f"{area}/{camel}", pascal


def _parse_generated_files(raw: str) -> dict[str, str]:
    """Parse the === FILE N: path === ... blocks from Claude's response."""
    pattern = r"=== FILE \d+: (.+?) ===\n([\s\S]*?)(?==== FILE|\Z)"
    files = {}
    for match in re.finditer(pattern, raw):
        path = match.group(1).strip()
        content = match.group(2).strip()
        # Strip markdown code fences
        content = re.sub(r"^```(?:typescript|ts)?\n?", "", content)
        content = re.sub(r"\n?```$", "", content)
        files[path] = content
    return files


# ---------------------------------------------------------------------------
# Main function
# ---------------------------------------------------------------------------

def generate_new_feature_tests(
    card_name: str,
    acceptance_criteria: str,
    app_url: str = "",
    dry_run: bool = False,
) -> dict:
    """
    Generate Playwright spec + POM for a new feature and write to the repo.

    Returns:
        {
          "spec_path": str,
          "page_object_path": str,
          "files_written": [str, ...],
          "skipped": bool,
        }
    """
    if not config.ANTHROPIC_API_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY not set in .env")
    if CODEBASE_PATH is None:
        raise RuntimeError("AUTOMATION_CODEBASE_PATH not set in .env")

    claude = ChatAnthropic(
        model=config.CLAUDE_SONNET_MODEL,
        api_key=config.ANTHROPIC_API_KEY,
        temperature=0.2,
        max_tokens=4096,
    )

    test_path, page_name = _sanitise_path(card_name)

    # Step 1: Observe the UI (if URL provided)
    ui_obs = _observe_ui(app_url, claude) if app_url else "No app URL provided."
    logger.info("UI observation: %s", ui_obs[:120])

    # Step 2: Load POM samples for style reference
    pom_samples = _load_pom_samples()

    # Step 3: Generate spec + page object
    prompt = SPEC_GENERATOR_PROMPT.format(
        card_name=card_name,
        acceptance_criteria=acceptance_criteria,
        ui_observations=ui_obs,
        existing_pom_samples=pom_samples,
        test_path=test_path,
        page_name=page_name,
    )
    logger.info("Generating tests for: %s", card_name)
    response = claude.invoke([HumanMessage(content=prompt)])
    generated = response.content.strip()

    files = _parse_generated_files(generated)
    if not files:
        logger.warning("Could not parse generated files. Raw output:\n%s", generated[:500])
        return {"spec_path": "", "page_object_path": "", "files_written": [], "skipped": True}

    written = []
    if not dry_run:
        for rel_path, content in files.items():
            abs_path = CODEBASE_PATH / rel_path
            abs_path.parent.mkdir(parents=True, exist_ok=True)
            abs_path.write_text(content, encoding="utf-8")
            written.append(str(abs_path))
            logger.info("Wrote: %s (%d chars)", abs_path, len(content))
    else:
        for rel_path, content in files.items():
            logger.info("[DRY RUN] Would write %s:\n%s", rel_path, content[:400])
            written.append(rel_path)

    spec_path = next((p for p in written if ".spec.ts" in p), "")
    page_path = next((p for p in written if "pages/" in p), "")

    return {
        "spec_path": spec_path,
        "page_object_path": page_path,
        "files_written": written,
        "skipped": False,
    }
