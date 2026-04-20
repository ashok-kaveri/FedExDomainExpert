"""
QA Explorer  —  Step 4b of the Delivery Pipeline
=================================================
Uses Claude (vision) + Playwright to walk through the deployed QA
environment and verify it against the card's acceptance criteria.

For each AC scenario:
  • Navigates to the relevant part of the app
  • Takes a screenshot
  • Claude analyses the screenshot against the AC
  • Reports: ✅ Pass | ❌ Fail | ⚠️ Unexpected behaviour

Output: a structured exploration report dict ready for Trello comment
or the sign-off dashboard.

Usage:
    from pipeline.qa_explorer import explore_feature
    report = explore_feature(
        app_url="https://your-shopify-store.myshopify.com/admin/apps/fedex",
        acceptance_criteria="## Acceptance Criteria\n...",
        card_name="FedEx Hold at Location toggle",
    )
"""
from __future__ import annotations
import base64
import json
import logging
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from textwrap import dedent
from typing import Any

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage

import config

# ---------------------------------------------------------------------------
# Auth / codebase paths (same as chrome_agent.py)
# ---------------------------------------------------------------------------
_CODEBASE  = Path(config.AUTOMATION_CODEBASE_PATH) if config.AUTOMATION_CODEBASE_PATH else None
_AUTH_JSON = _CODEBASE / "auth.json" if _CODEBASE else None

# Phrases that indicate Shopify/Cloudflare challenge page (not the real app)
_CHALLENGE_PHRASES = [
    "connection needs to be verified",
    "let us know you",
    "verify you are human",
    "access to this page has been denied",
    "just a moment...",
    "checking your browser",
    "please wait while we verify",
    "needs to be verified before you can proceed",
]

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class ScenarioResult:
    scenario: str          # AC scenario title
    status: str            # "pass" | "fail" | "unexpected" | "skipped"
    finding: str           # Claude's analysis
    screenshot_path: str = ""


@dataclass
class ExplorationReport:
    card_name: str
    app_url: str
    scenarios: list[ScenarioResult] = field(default_factory=list)
    summary: str = ""

    @property
    def passed(self) -> int:
        return sum(1 for s in self.scenarios if s.status == "pass")

    @property
    def failed(self) -> int:
        return sum(1 for s in self.scenarios if s.status == "fail")

    def to_trello_comment(self) -> str:
        lines = [
            f"## 🔍 QA Explorer Report — {self.card_name}",
            f"App: {self.app_url}",
            f"Result: {self.passed} ✅ passed, {self.failed} ❌ failed\n",
        ]
        for s in self.scenarios:
            icon = {"pass": "✅", "fail": "❌", "unexpected": "⚠️", "skipped": "⏭️"}.get(s.status, "?")
            lines.append(f"{icon} **{s.scenario}**")
            lines.append(f"   {s.finding}")
        if self.summary:
            lines.append(f"\n**Summary:** {self.summary}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

SCENARIO_EXTRACTOR_PROMPT = dedent("""\
    Extract each Given/When/Then scenario from the acceptance criteria below.
    Return ONLY a JSON array of scenario title strings, nothing else.
    Example: ["User can enable Hold at Location", "User sees error on invalid address"]

    Acceptance Criteria:
    {ac}
""")

VISION_ANALYSER_PROMPT = dedent("""\
    You are a QA engineer testing the FedEx Shopify App.

    Acceptance Criteria scenario being tested:
    {scenario}

    Look at the screenshot of the app and determine:
    1. Does the UI match what the scenario expects? (pass / fail / unexpected)
    2. What exactly do you see that leads to that conclusion?

    Respond in JSON:
    {{
      "status": "pass" | "fail" | "unexpected",
      "finding": "one or two sentence observation"
    }}
""")

EXPLORATION_SUMMARY_PROMPT = dedent("""\
    You are a QA lead reviewing an exploration session for the FedEx Shopify App.

    Feature: {card_name}
    Scenario results:
    {results}

    Write a concise 2-3 sentence executive summary of the QA findings.
    Highlight any blockers for sign-off.
""")


# ---------------------------------------------------------------------------
# Screenshot helper (uses Playwright Python API with auth session)
# ---------------------------------------------------------------------------

def _load_auth_kwargs() -> dict:
    """Return browser context kwargs that load the saved Shopify session."""
    kwargs: dict = {"viewport": {"width": 1400, "height": 1000}}
    if _AUTH_JSON.exists():
        try:
            json.loads(_AUTH_JSON.read_text(encoding="utf-8"))
            kwargs["storage_state"] = str(_AUTH_JSON)
            logger.debug("QA Explorer: using auth.json session state")
        except Exception:
            logger.warning("QA Explorer: auth.json is invalid — screenshot will be unauthenticated")
    else:
        logger.warning(
            "QA Explorer: auth.json not found at %s — "
            "screenshots may show Shopify login/challenge page. "
            "Run: npx playwright test --project=setup  in the automation repo.",
            _AUTH_JSON,
        )
    return kwargs


def _is_challenge_page(page) -> bool:  # noqa: ANN001
    """Return True when the page is a Shopify/Cloudflare bot-challenge screen."""
    try:
        text = (page.inner_text("body") or "").lower()
        return any(phrase in text for phrase in _CHALLENGE_PHRASES)
    except Exception:
        return False


def _take_screenshot(url: str, output_path: str) -> bool:
    """
    Screenshot a URL using the stored Shopify auth session.

    Uses real Chrome (channel='chrome') in headed mode with auth.json cookies
    to avoid Shopify's bot-detection / connection-verification interstitial.
    Falls back to headless Chromium when Chrome binary is not available
    (less reliable against bot detection but still captures *something*).

    Returns True when a useful screenshot was captured, False on error or
    when a challenge/verification page was detected instead of the real app.
    """
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

    anti_bot_args = [
        "--disable-blink-features=AutomationControlled",
        "--no-sandbox",
        "--disable-setuid-sandbox",
    ]
    ctx_kwargs = _load_auth_kwargs()

    try:
        with sync_playwright() as p:
            # Prefer real Chrome — avoids most bot-detection fingerprinting
            try:
                browser = p.chromium.launch(
                    channel="chrome",
                    headless=False,
                    args=anti_bot_args,
                )
                logger.debug("QA Explorer: launched real Chrome (headless=False)")
            except Exception as chrome_err:
                logger.warning(
                    "QA Explorer: Chrome not available (%s) — falling back to headless Chromium. "
                    "Shopify bot detection may trigger.", chrome_err
                )
                browser = p.chromium.launch(headless=True, args=anti_bot_args)

            context = browser.new_context(**ctx_kwargs)
            page = context.new_page()

            try:
                page.goto(url, wait_until="domcontentloaded", timeout=30_000)
                page.wait_for_timeout(2_500)
            except PWTimeout:
                logger.warning("QA Explorer: page load timed out for %s", url)

            # Guard: detect challenge / verification overlay
            if _is_challenge_page(page):
                logger.warning(
                    "QA Explorer: Shopify connection-verification challenge detected at %s.\n"
                    "The auth.json session may have expired or be unrecognised by this browser.\n"
                    "Fix: run  npx playwright test --project=setup  in the automation repo "
                    "to refresh auth.json, then retry.",
                    url,
                )
                context.close()
                browser.close()
                return False

            page.screenshot(path=output_path, full_page=True)
            context.close()
            browser.close()
            return True

    except Exception as exc:
        logger.warning("QA Explorer: screenshot error for %s — %s", url, exc)
        return False


def _encode_image(path: str) -> str:
    """Base64-encode an image file for Claude vision."""
    with open(path, "rb") as f:
        return base64.standard_b64encode(f.read()).decode("utf-8")


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------

def _extract_scenarios(ac: str, claude: ChatAnthropic) -> list[str]:
    """Ask Claude to pull out individual scenario titles from AC markdown."""
    import json, re
    prompt = SCENARIO_EXTRACTOR_PROMPT.format(ac=ac)
    response = claude.invoke([HumanMessage(content=prompt)])
    raw = response.content.strip()
    try:
        json_text = re.sub(r"```(?:json)?\n?", "", raw).strip().rstrip("`")
        return json.loads(json_text)
    except Exception:
        # Fallback: split on newlines that look like scenario headings
        return [line.strip("- ").strip() for line in ac.splitlines()
                if line.strip().startswith(("Given", "When", "Scenario", "-"))][:10]


def _analyse_screenshot(
    scenario: str,
    screenshot_path: str,
    claude: ChatAnthropic,
) -> tuple[str, str]:
    """Send screenshot + scenario to Claude vision. Returns (status, finding)."""
    import json, re

    if not Path(screenshot_path).exists():
        return "skipped", "Screenshot not available"

    img_b64 = _encode_image(screenshot_path)
    prompt = VISION_ANALYSER_PROMPT.format(scenario=scenario)

    message = HumanMessage(content=[
        {"type": "text", "text": prompt},
        {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/png",
                "data": img_b64,
            },
        },
    ])
    response = claude.invoke([message])
    raw = response.content.strip()

    try:
        json_text = re.sub(r"```(?:json)?\n?", "", raw).strip().rstrip("`")
        data = json.loads(json_text)
        return data.get("status", "unexpected"), data.get("finding", raw)
    except Exception:
        return "unexpected", raw[:300]


def explore_feature(
    app_url: str,
    acceptance_criteria: str,
    card_name: str = "Feature",
) -> ExplorationReport:
    """
    Walk through the app and validate each AC scenario with Claude vision.

    Args:
        app_url:             Base URL of the deployed QA environment
        acceptance_criteria: Full AC markdown from the card processor
        card_name:           Feature name for the report

    Returns:
        ExplorationReport with per-scenario status and overall summary
    """
    if not config.ANTHROPIC_API_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY not set in .env")
    if _AUTH_JSON is None:
        raise RuntimeError("AUTOMATION_CODEBASE_PATH is not set in .env")

    claude = ChatAnthropic(
        model=config.CLAUDE_SONNET_MODEL,   # sonnet — vision capable
        api_key=config.ANTHROPIC_API_KEY,
        temperature=0.1,
        max_tokens=1024,
    )

    report = ExplorationReport(card_name=card_name, app_url=app_url)

    # Step 1: Extract scenarios from AC
    scenarios = _extract_scenarios(acceptance_criteria, claude)
    logger.info("Extracted %d scenarios from AC", len(scenarios))

    # Step 2: For each scenario — screenshot + analyse
    with tempfile.TemporaryDirectory() as tmpdir:
        # Take a single screenshot of the app (same URL for every scenario)
        # and reuse it — avoids re-launching Chrome for every scenario.
        shared_screenshot = str(Path(tmpdir) / "app_state.png")
        screenshot_ok = _take_screenshot(app_url, shared_screenshot)

        if not screenshot_ok:
            # Challenge page was detected — skip all scenarios with a clear error
            challenge_msg = (
                "⚠️ Shopify connection-verification challenge detected. "
                "The QA Explorer could not load the app UI. "
                "To fix: open a terminal, run  `npx playwright test --project=setup`  "
                "in the automation repo to refresh auth.json, then retry."
            )
            for scenario in scenarios:
                report.scenarios.append(ScenarioResult(
                    scenario=scenario,
                    status="skipped",
                    finding=challenge_msg,
                ))
            report.summary = challenge_msg
            logger.warning("QA Explorer blocked by challenge page — all scenarios skipped")
            return report

        for i, scenario in enumerate(scenarios):
            logger.info("[%d/%d] Testing: %s", i + 1, len(scenarios), scenario)

            status, finding = _analyse_screenshot(scenario, shared_screenshot, claude)
            report.scenarios.append(ScenarioResult(
                scenario=scenario,
                status=status,
                finding=finding,
                screenshot_path=shared_screenshot,
            ))

        # Step 3: Generate executive summary
        results_text = "\n".join(
            f"- [{s.status.upper()}] {s.scenario}: {s.finding}"
            for s in report.scenarios
        )
        summary_prompt = EXPLORATION_SUMMARY_PROMPT.format(
            card_name=card_name,
            results=results_text,
        )
        summary_resp = claude.invoke([HumanMessage(content=summary_prompt)])
        report.summary = summary_resp.content.strip()

    logger.info(
        "Exploration done: %d passed, %d failed",
        report.passed, report.failed,
    )
    return report
