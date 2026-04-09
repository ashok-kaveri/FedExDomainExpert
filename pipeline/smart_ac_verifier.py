"""
Smart AC Verifier  —  Step 2b (Agentic Upgrade)
=================================================
Replaces the old screenshot-only QA Explorer with a true agentic loop:

  AC text
    │
    ▼
  1. Claude extracts each scenario
    │
    ▼  (per scenario)
  2. Query code RAG  →  automation POM + backend API + QA knowledge
     Claude knows what locators exist, what API endpoints to watch
    │
    ▼
  3. Claude plans: which app path to navigate, what to interact with
    │
    ▼  (agentic loop — up to 10 steps)
  4. Browser action  →  navigate / click / fill / scroll / observe
  5. Capture: page accessibility tree + screenshot + network calls
  6. Claude decides next action  OR  gives verdict  OR  asks QA
    │
    ▼
  ✅ pass / ❌ fail / ⚠️ partial  per scenario
    │
    ▼
  Final report  →  feeds directly into Write Automation Code

If Claude can't find a feature:
  → status = "qa_needed"
  → Dashboard shows Claude's question + QA text input
  → QA answers → re-run that scenario with the guidance injected
"""

import base64
import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from textwrap import dedent
from typing import Callable

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage

import config

logger = logging.getLogger(__name__)

_CODEBASE       = Path(config.AUTOMATION_CODEBASE_PATH)
_AUTH_JSON      = _CODEBASE / "auth.json"
_ENV_FILE       = _CODEBASE / ".env"
MAX_STEPS       = 10
_ANTI_BOT_ARGS  = [
    "--disable-blink-features=AutomationControlled",
    "--no-sandbox",
    "--disable-setuid-sandbox",
]
_CHALLENGE_PHRASES = [
    "connection needs to be verified",
    "let us know you",
    "verify you are human",
    "just a moment",
    "checking your browser",
]


# ── Data models ───────────────────────────────────────────────────────────────

@dataclass
class VerificationStep:
    action: str
    description: str
    target: str = ""
    success: bool = True
    screenshot_b64: str = ""        # base64 PNG of page at this step
    network_calls: list[str] = field(default_factory=list)


@dataclass
class ScenarioResult:
    scenario: str
    status: str = "pending"         # pass | fail | partial | skipped | qa_needed
    verdict: str = ""               # Claude's finding
    steps: list[VerificationStep] = field(default_factory=list)
    qa_question: str = ""           # what Claude asks QA when stuck
    bug_report: dict = field(default_factory=dict)  # result from bug_reporter.notify_devs_of_bug


@dataclass
class VerificationReport:
    card_name: str
    app_url: str
    scenarios: list[ScenarioResult] = field(default_factory=list)
    summary: str = ""

    @property
    def passed(self) -> int:
        return sum(1 for s in self.scenarios if s.status == "pass")

    @property
    def failed(self) -> int:
        return sum(1 for s in self.scenarios if s.status in ("fail", "partial"))

    @property
    def qa_needed(self) -> "list[ScenarioResult]":
        return [s for s in self.scenarios if s.status == "qa_needed"]

    def to_automation_context(self) -> str:
        """Convert verified flows into context string for automation writer."""
        lines = [f"=== Smart AC Verification: {self.card_name} ===", f"App: {self.app_url}", ""]
        for sv in self.scenarios:
            icon = {"pass": "✅", "fail": "❌", "partial": "⚠️"}.get(sv.status, "⏭️")
            lines.append(f"{icon} {sv.scenario}")
            for step in sv.steps:
                if step.action in ("click", "fill", "navigate") and step.target:
                    lines.append(f"   [{step.action}] '{step.target}' — {step.description}")
                if step.network_calls:
                    for nc in step.network_calls[:3]:
                        lines.append(f"   [api] {nc}")
            if sv.verdict:
                lines.append(f"   Result: {sv.verdict}")
            lines.append("")
        return "\n".join(lines)


# ── Prompts ───────────────────────────────────────────────────────────────────

_EXTRACT_PROMPT = dedent("""\
    Extract each testable scenario from the acceptance criteria below.
    Return ONLY a JSON array of concise scenario title strings. No explanation.
    Example: ["User can enable Hold at Location", "Success toast shown after Save"]

    Acceptance Criteria:
    {ac}
""")

_PLAN_PROMPT = dedent("""\
    You are a QA engineer verifying a feature in the FedEx Shopify App.

    SCENARIO: {scenario}
    APP URL:  {app_url}

    CODE KNOWLEDGE (automation POM patterns + backend API):
    {code_context}

    Plan how to verify this. Which app section to open, what to interact with,
    which API endpoint to watch in the network tab.

    Respond ONLY in JSON:
    {{
      "app_path": "sub-path to navigate after the base URL (e.g. 'settings/additional-services') — empty string for home",
      "look_for": ["UI element or behaviour that proves this scenario is implemented"],
      "api_to_watch": ["API endpoint path fragment to watch in network calls"],
      "plan": "one sentence: how you will verify this scenario"
    }}
""")

_STEP_PROMPT = dedent("""\
    You are verifying this AC scenario in the FedEx Shopify App.

    SCENARIO: {scenario}

    CURRENT PAGE: {url}
    ACCESSIBILITY TREE (what is visible):
    {ax_tree}

    NETWORK CALLS SEEN SO FAR:
    {network_calls}

    STEPS TAKEN SO FAR ({step_num}/{max_steps}):
    {steps_taken}

    CODE KNOWLEDGE:
    {code_context}

    Decide your NEXT action. Respond ONLY in JSON — no extra text:
    {{
      "action":      "navigate" | "click" | "fill" | "scroll" | "observe" | "verify" | "qa_needed",
      "target":      "<exact element name from accessibility tree — required for click/fill>",
      "value":       "<text to type — only for fill>",
      "path":        "<app sub-path — only for navigate>",
      "description": "one sentence: what you are doing and why",
      "verdict":     "pass | fail | partial  — ONLY when action=verify",
      "finding":     "what you observed      — ONLY when action=verify",
      "question":    "your question for QA   — ONLY when action=qa_needed"
    }}

    Rules:
    - action=verify  → you have clear evidence to give a verdict
    - action=qa_needed → you genuinely cannot locate the feature after looking carefully
    - ONLY reference targets that literally appear in the accessibility tree above
    - Do NOT explore unrelated sections of the app
    - action=observe on first step to capture visible elements before interacting
""")

_SUMMARY_PROMPT = dedent("""\
    QA lead summary for feature: {card_name}

    Scenario results:
    {results}

    Write 2-3 sentences. Call out any failures or blockers for sign-off.
""")


# ── Browser helpers ───────────────────────────────────────────────────────────

def get_auto_app_url() -> str:
    """Auto-detect app URL from automation repo .env STORE value."""
    if _ENV_FILE.exists():
        for line in _ENV_FILE.read_text(encoding="utf-8").splitlines():
            s = line.strip()
            if s.startswith("#") or "=" not in s:
                continue
            k, _, v = s.partition("=")
            if k.strip() == "STORE":
                v = v.strip().strip('"').strip("'")
                if v and not v.startswith("your-"):
                    store = v.replace(".myshopify.com", "")
                    return f"https://admin.shopify.com/store/{store}/apps/testing-553"
    return ""


def _auth_ctx_kwargs() -> dict:
    kw: dict = {"viewport": {"width": 1400, "height": 1000}}
    if _AUTH_JSON.exists():
        try:
            json.loads(_AUTH_JSON.read_text(encoding="utf-8"))
            kw["storage_state"] = str(_AUTH_JSON)
        except Exception:
            pass
    return kw


def _ax_tree(page) -> str:
    """Accessibility tree as readable text."""
    try:
        ax = page.accessibility.snapshot(interesting_only=True)
        if not ax:
            return "(empty tree)"
        lines: list[str] = []

        def _walk(n: dict, d: int = 0) -> None:
            if d > 4 or len(lines) > 70:
                return
            role, name = n.get("role", ""), n.get("name", "")
            skip = {"generic", "none", "presentation", "document", "group", "list", "region"}
            if role and name and role not in skip:
                ln = f"{'  ' * d}{role}: '{name}'"
                c = n.get("checked")
                if c is not None:
                    ln += f" [checked={c}]"
                v = n.get("value", "")
                if v and role in ("textbox", "combobox"):
                    ln += f" [value='{v[:30]}']"
                lines.append(ln)
            for ch in n.get("children", []):
                _walk(ch, d + 1)

        _walk(ax)
        return "\n".join(lines) or "(no interactive elements)"
    except Exception as e:
        return f"(snapshot error: {e})"


def _screenshot(page) -> str:
    """Base64 PNG of current page."""
    try:
        return base64.standard_b64encode(page.screenshot()).decode()
    except Exception:
        return ""


def _network(page, endpoints: list[str]) -> list[str]:
    """Recent API/XHR calls matching endpoint paths."""
    try:
        entries = page.evaluate("""() =>
            performance.getEntriesByType('resource')
              .filter(e => ['xmlhttprequest','fetch'].includes(e.initiatorType))
              .slice(-30).map(e => e.name)
        """)
        hits = entries or []
        if endpoints:
            return [e for e in hits if any(ep in e for ep in endpoints)]
        return [e for e in hits if "/api/" in e]
    except Exception:
        return []


def _app_frame(page):
    return page.frame_locator('iframe[name="app-iframe"]')


def _do_action(page, action: dict, app_base: str) -> bool:
    """Execute a Claude-decided browser action. Returns True on success."""
    atype  = action.get("action", "observe")
    target = action.get("target", "").strip()
    value  = action.get("value", "")
    path   = action.get("path", "").strip("/")

    if atype == "navigate":
        url = f"{app_base}/{path}" if path else app_base
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            page.wait_for_timeout(2_000)
            return True
        except Exception:
            return False

    if atype in ("observe", "verify", "qa_needed"):
        return True

    if atype == "scroll":
        try:
            page.evaluate("window.scrollBy(0, 400)")
        except Exception:
            pass
        return True

    if not target:
        return False

    frame = _app_frame(page)

    if atype == "click":
        for fn in [
            lambda: frame.get_by_role("button",   name=target, exact=False),
            lambda: frame.get_by_role("checkbox", name=target, exact=False),
            lambda: frame.get_by_role("switch",   name=target, exact=False),
            lambda: frame.get_by_role("link",     name=target, exact=False),
            lambda: frame.get_by_role("tab",      name=target, exact=False),
            lambda: frame.get_by_text(target, exact=False),
            lambda: page.get_by_role("button", name=target, exact=False),
            lambda: page.get_by_text(target, exact=False),
        ]:
            try:
                el = fn()
                if el.count() > 0:
                    el.first.click(timeout=5_000)
                    page.wait_for_timeout(800)
                    return True
            except Exception:
                continue
        logger.debug("Click target not found: '%s'", target)
        return False

    if atype == "fill":
        for fn in [
            lambda: frame.get_by_label(target, exact=False),
            lambda: frame.get_by_placeholder(target, exact=False),
            lambda: frame.get_by_role("textbox", name=target, exact=False),
        ]:
            try:
                el = fn()
                if el.count() > 0:
                    el.first.clear()
                    el.first.fill(value, timeout=5_000)
                    return True
            except Exception:
                continue
        return False

    return True


# ── Code RAG ─────────────────────────────────────────────────────────────────

def _code_context(scenario: str, card_name: str) -> str:
    """Query automation POM + backend API + QA knowledge for context."""
    parts: list[str] = []
    query = f"{card_name} {scenario}"

    try:
        from rag.code_indexer import search_code
        for stype, label in [("automation", "Automation POM"), ("backend", "Backend API")]:
            docs = search_code(query, k=3, source_type=stype)
            if docs:
                snippets = "\n---\n".join(d.page_content[:350] for d in docs)
                parts.append(f"=== {label} ===\n{snippets}")
    except Exception as e:
        logger.debug("Code RAG error: %s", e)

    try:
        from rag.vectorstore import search as qs
        docs = qs(query, k=3)
        if docs:
            snippets = "\n---\n".join(d.page_content[:300] for d in docs)
            parts.append(f"=== QA knowledge ===\n{snippets}")
    except Exception as e:
        logger.debug("QA knowledge RAG error: %s", e)

    return "\n\n".join(parts) if parts else "(no code context indexed yet)"


# ── Claude helpers ────────────────────────────────────────────────────────────

def _parse_json(raw: str) -> dict:
    clean = re.sub(r"```(?:json)?\n?", "", raw.strip()).strip().rstrip("`")
    try:
        return json.loads(clean)
    except Exception:
        return {}


def _extract_scenarios(ac: str, claude: ChatAnthropic) -> list[str]:
    resp = claude.invoke([HumanMessage(content=_EXTRACT_PROMPT.format(ac=ac))])
    raw  = resp.content.strip()
    data = _parse_json(raw)
    if isinstance(data, list):
        return data
    # fallback: parse line by line
    return [
        ln.strip("- ").strip()
        for ln in ac.splitlines()
        if ln.strip().startswith(("Given", "When", "Scenario", "Then", "-"))
    ][:12]


def _plan_scenario(scenario: str, app_url: str, ctx: str, claude: ChatAnthropic) -> dict:
    resp = claude.invoke([HumanMessage(content=_PLAN_PROMPT.format(
        scenario=scenario, app_url=app_url, code_context=ctx[:2000]))])
    return _parse_json(resp.content) or {}


def _decide_next(
    claude: ChatAnthropic,
    scenario: str,
    url: str,
    ax: str,
    net: list[str],
    steps: list[VerificationStep],
    ctx: str,
    step_num: int,
) -> dict:
    steps_text = "\n".join(
        f"  {i+1}. [{s.action}] {s.description} ({'✓' if s.success else '✗'})"
        for i, s in enumerate(steps)
    )
    content = claude.invoke([HumanMessage(content=_STEP_PROMPT.format(
        scenario=scenario,
        url=url,
        ax_tree=ax[:3000],
        network_calls="\n".join(net[-10:]) if net else "(none)",
        steps_taken=steps_text or "(just starting)",
        code_context=ctx[:1500],
        step_num=step_num,
        max_steps=MAX_STEPS,
    ))]).content
    raw = content if isinstance(content, str) else \
        " ".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in content)
    return _parse_json(raw) or {"action": "verify", "verdict": "partial", "finding": raw[:200]}


# ── Core: verify one scenario ─────────────────────────────────────────────────

def _verify_scenario(
    page,
    scenario: str,
    card_name: str,
    app_base: str,
    plan_data: dict,
    ctx: str,
    claude: ChatAnthropic,
    progress_cb: Callable | None = None,
    qa_answer: str = "",
) -> ScenarioResult:
    result       = ScenarioResult(scenario=scenario)
    net_seen: list[str] = []
    api_endpoints = plan_data.get("api_to_watch", [])

    # Inject QA guidance when resuming a stuck scenario
    if qa_answer:
        ctx = f"QA GUIDANCE: {qa_answer}\n\n{ctx}"

    # Navigate to initial path from plan
    path = plan_data.get("app_path", "").strip("/")
    url  = f"{app_base}/{path}" if path else app_base
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        page.wait_for_timeout(2_500)
    except Exception as e:
        result.status  = "fail"
        result.verdict = f"Could not navigate to app: {e}"
        return result

    # Detect bot-challenge page
    try:
        body = page.inner_text("body").lower()
        if any(p in body for p in _CHALLENGE_PHRASES):
            result.status  = "skipped"
            result.verdict = "⚠️ Shopify bot-detection challenge. Refresh auth.json and retry."
            return result
    except Exception:
        pass

    # Agentic loop ────────────────────────────────────────────────────────────
    for step_num in range(1, MAX_STEPS + 1):
        ax  = _ax_tree(page)
        scr = _screenshot(page)
        net = _network(page, api_endpoints)
        net_seen.extend(n for n in net if n not in net_seen)

        if progress_cb:
            progress_cb(step_num, f"Step {step_num}/{MAX_STEPS}")

        action = _decide_next(claude, scenario, page.url, ax, net_seen,
                              result.steps, ctx, step_num)

        atype = action.get("action", "observe")
        step  = VerificationStep(
            action=atype,
            description=action.get("description", atype),
            target=action.get("target", ""),
            screenshot_b64=scr,
            network_calls=list(net),
        )
        result.steps.append(step)

        if atype == "verify":
            result.status  = action.get("verdict", "partial")
            result.verdict = action.get("finding", "")
            step.screenshot_b64 = _screenshot(page)   # final state screenshot
            break

        if atype == "qa_needed":
            result.status      = "qa_needed"
            result.qa_question = action.get("question", "I need more guidance to find this feature.")
            break

        step.success = _do_action(page, action, app_base)

    else:
        result.status  = "partial"
        result.verdict = "Reached max steps without a conclusive verdict"

    return result


# ── Public entry point ────────────────────────────────────────────────────────

def verify_ac(
    app_url: str,
    ac_text: str,
    card_name: str,
    card_id: str = "",
    card_url: str = "",
    qa_name: str = "QA Team",
    progress_cb: "Callable[[int, str, int, str], None] | None" = None,
    qa_answers: "dict[str, str] | None" = None,
    auto_report_bugs: bool = True,
) -> VerificationReport:
    """
    Verify all AC scenarios for a card against the live Shopify app.

    Args:
        app_url:           Full FedEx app URL in Shopify admin
        ac_text:           Full AC markdown from the Trello card
        card_name:         Card title
        card_id:           Trello card ID — used to get dev members for bug DMs
        card_url:          Trello card URL — included in bug DM
        qa_name:           Name of QA running the verification (shown in DM)
        progress_cb:       callback(scenario_idx, scenario_title, step_num, step_desc)
        qa_answers:        {scenario_text: qa_answer} for stuck scenarios
        auto_report_bugs:  If True, automatically DM developers when a bug is found

    Returns:
        VerificationReport with per-scenario results + bug_report on failures
    """
    from playwright.sync_api import sync_playwright

    if not app_url:
        app_url = get_auto_app_url()
    if not app_url:
        raise ValueError(
            "App URL required. Set STORE in the automation repo .env, "
            "or enter the URL manually."
        )
    if not config.ANTHROPIC_API_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY not set in .env")

    claude = ChatAnthropic(
        model=config.CLAUDE_SONNET_MODEL,
        api_key=config.ANTHROPIC_API_KEY,
        temperature=0.1,
        max_tokens=2048,
    )

    report    = VerificationReport(card_name=card_name, app_url=app_url)
    scenarios = _extract_scenarios(ac_text, claude)
    logger.info("SmartVerifier: %d scenarios for '%s'", len(scenarios), card_name)

    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(channel="chrome", headless=False, args=_ANTI_BOT_ARGS)
            logger.debug("SmartVerifier: launched real Chrome")
        except Exception as e:
            logger.warning("Chrome not found (%s) — falling back to headless Chromium", e)
            browser = p.chromium.launch(headless=True, args=_ANTI_BOT_ARGS)

        ctx  = browser.new_context(**_auth_ctx_kwargs())
        page = ctx.new_page()

        for idx, scenario in enumerate(scenarios):
            logger.info("[%d/%d] Verifying: %s", idx + 1, len(scenarios), scenario[:70])

            code_ctx  = _code_context(scenario, card_name)
            plan_data = _plan_scenario(scenario, app_url, code_ctx, claude)

            def _cb(step_num: int, desc: str, _i: int = idx, _sc: str = scenario) -> None:
                if progress_cb:
                    progress_cb(_i + 1, _sc, step_num, desc)

            qa_ans = (qa_answers or {}).get(scenario, "")

            sv = _verify_scenario(
                page=page,
                scenario=scenario,
                card_name=card_name,
                app_base=app_url,
                plan_data=plan_data,
                ctx=code_ctx,
                claude=claude,
                progress_cb=_cb,
                qa_answer=qa_ans,
            )

            # Auto bug report — DM developer when fail/partial detected
            if auto_report_bugs and sv.status in ("fail", "partial") and card_id:
                if progress_cb:
                    progress_cb(idx + 1, scenario, MAX_STEPS, "🐛 Bug detected — notifying developer…")
                try:
                    from pipeline.bug_reporter import notify_devs_of_bug
                    steps_taken = [
                        f"{s.action}: {s.description}" for s in sv.steps
                        if s.action in ("click", "fill", "navigate", "observe")
                    ]
                    bug_result = notify_devs_of_bug(
                        card_id=card_id,
                        card_name=card_name,
                        card_url=card_url,
                        bug_description=sv.verdict,
                        scenario=scenario,
                        qa_name=qa_name,
                        verification_steps=steps_taken,
                    )
                    sv.bug_report = bug_result
                    logger.info(
                        "Bug report for '%s': sent=%s failed=%s",
                        scenario[:50], bug_result.get("sent_to"), bug_result.get("failed"),
                    )
                except Exception as e:
                    logger.warning("Bug auto-report failed: %s", e)
                    sv.bug_report = {"ok": False, "error": str(e)}

            report.scenarios.append(sv)

        ctx.close()
        browser.close()

    # Generate summary
    results_txt = "\n".join(
        f"- [{sv.status.upper()}] {sv.scenario}: {sv.verdict}"
        for sv in report.scenarios
    )
    resp = claude.invoke([HumanMessage(content=_SUMMARY_PROMPT.format(
        card_name=card_name, results=results_txt,
    ))])
    report.summary = resp.content.strip()

    return report


def reverify_failed(
    report: VerificationReport,
    app_url: str = "",
    card_id: str = "",
    card_url: str = "",
    qa_name: str = "QA Team",
    progress_cb: "Callable | None" = None,
    qa_answers: "dict[str, str] | None" = None,
    auto_report_bugs: bool = True,
) -> VerificationReport:
    """
    Re-run only the failed/partial/qa_needed scenarios from an existing report.

    Args:
        report:            Existing VerificationReport from a previous verify_ac() call
        app_url:           Full FedEx app URL (defaults to report.app_url if blank)
        card_id:           Trello card ID — used for bug DMs
        card_url:          Trello card URL — included in bug DM
        qa_name:           Name of QA running the re-verification
        progress_cb:       callback(scenario_idx, scenario_title, step_num, step_desc)
        qa_answers:        {scenario_text: qa_answer} for stuck scenarios
        auto_report_bugs:  If True, automatically DM developers when a bug is found

    Returns:
        Updated VerificationReport — previously-passing scenarios kept as-is,
        re-run results merged in, and summary regenerated.
    """
    from playwright.sync_api import sync_playwright

    # Filter to only failed scenarios
    failed_scenarios = [
        sv for sv in report.scenarios
        if sv.status in ("fail", "partial", "qa_needed")
    ]

    # Nothing to re-verify — return report unchanged
    if not failed_scenarios:
        return report

    # Resolve app URL
    _app_url = (app_url or report.app_url or "").strip()
    if not _app_url:
        _app_url = get_auto_app_url()
    if not _app_url:
        raise ValueError(
            "App URL required. Set STORE in the automation repo .env, "
            "or enter the URL manually."
        )
    if not config.ANTHROPIC_API_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY not set in .env")

    claude = ChatAnthropic(
        model=config.CLAUDE_SONNET_MODEL,
        api_key=config.ANTHROPIC_API_KEY,
        temperature=0.1,
        max_tokens=2048,
    )

    card_name = report.card_name
    failed_count = len(failed_scenarios)
    logger.info(
        "reverify_failed: re-running %d scenario(s) for '%s'",
        failed_count, card_name,
    )

    # Build a lookup for in-place replacement
    # Maps scenario text → index in report.scenarios
    scenario_index: dict[str, int] = {
        sv.scenario: i for i, sv in enumerate(report.scenarios)
    }

    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(channel="chrome", headless=False, args=_ANTI_BOT_ARGS)
            logger.debug("reverify_failed: launched real Chrome")
        except Exception as e:
            logger.warning("Chrome not found (%s) — falling back to headless Chromium", e)
            browser = p.chromium.launch(headless=True, args=_ANTI_BOT_ARGS)

        ctx  = browser.new_context(**_auth_ctx_kwargs())
        page = ctx.new_page()

        for idx, old_sv in enumerate(failed_scenarios):
            scenario = old_sv.scenario
            logger.info(
                "[%d/%d] Re-verifying: %s", idx + 1, failed_count, scenario[:70]
            )

            code_ctx  = _code_context(scenario, card_name)
            plan_data = _plan_scenario(scenario, _app_url, code_ctx, claude)

            def _cb(step_num: int, desc: str, _i: int = idx, _sc: str = scenario) -> None:
                if progress_cb:
                    progress_cb(_i + 1, _sc, step_num, desc)

            qa_ans = (qa_answers or {}).get(scenario, "")

            new_sv = _verify_scenario(
                page=page,
                scenario=scenario,
                card_name=card_name,
                app_base=_app_url,
                plan_data=plan_data,
                ctx=code_ctx,
                claude=claude,
                progress_cb=_cb,
                qa_answer=qa_ans,
            )

            # Auto bug report on fail/partial
            if auto_report_bugs and new_sv.status in ("fail", "partial") and card_id:
                if progress_cb:
                    progress_cb(idx + 1, scenario, MAX_STEPS, "🐛 Bug detected — notifying developer…")
                try:
                    from pipeline.bug_reporter import notify_devs_of_bug
                    steps_taken = [
                        f"{s.action}: {s.description}" for s in new_sv.steps
                        if s.action in ("click", "fill", "navigate", "observe")
                    ]
                    bug_result = notify_devs_of_bug(
                        card_id=card_id,
                        card_name=card_name,
                        card_url=card_url,
                        bug_description=new_sv.verdict,
                        scenario=scenario,
                        qa_name=qa_name,
                        verification_steps=steps_taken,
                    )
                    new_sv.bug_report = bug_result
                    logger.info(
                        "Bug report for '%s': sent=%s failed=%s",
                        scenario[:50], bug_result.get("sent_to"), bug_result.get("failed"),
                    )
                except Exception as e:
                    logger.warning("Bug auto-report failed: %s", e)
                    new_sv.bug_report = {"ok": False, "error": str(e)}

            # Replace the old result in-place
            orig_idx = scenario_index.get(scenario)
            if orig_idx is not None:
                report.scenarios[orig_idx] = new_sv
            else:
                # Scenario not found by exact match (shouldn't happen) — append
                report.scenarios.append(new_sv)

        ctx.close()
        browser.close()

    # Re-generate summary with Claude
    results_txt = "\n".join(
        f"- [{sv.status.upper()}] {sv.scenario}: {sv.verdict}"
        for sv in report.scenarios
    )
    resp = claude.invoke([HumanMessage(content=_SUMMARY_PROMPT.format(
        card_name=card_name, results=results_txt,
    ))])
    report.summary = resp.content.strip()

    return report
