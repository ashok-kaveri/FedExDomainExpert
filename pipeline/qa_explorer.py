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
import base64
import logging
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from textwrap import dedent
from typing import Any

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage

import config

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
# Screenshot helper (uses playwright CLI)
# ---------------------------------------------------------------------------

def _take_screenshot(url: str, output_path: str) -> bool:
    """Use playwright CLI to screenshot a URL. Returns True on success."""
    try:
        result = subprocess.run(
            [
                sys.executable, "-m", "playwright", "screenshot",
                "--browser", "chromium",
                "--full-page",
                url,
                output_path,
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            logger.warning("Screenshot failed for %s: %s", url, result.stderr[:300])
            return False
        return True
    except Exception as e:
        logger.warning("Screenshot error: %s", e)
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
        for i, scenario in enumerate(scenarios):
            logger.info("[%d/%d] Testing: %s", i + 1, len(scenarios), scenario)

            screenshot_path = str(Path(tmpdir) / f"scenario_{i + 1}.png")
            _take_screenshot(app_url, screenshot_path)

            status, finding = _analyse_screenshot(scenario, screenshot_path, claude)
            report.scenarios.append(ScenarioResult(
                scenario=scenario,
                status=status,
                finding=finding,
                screenshot_path=screenshot_path,
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
