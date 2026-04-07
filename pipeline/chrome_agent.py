"""
Chrome Agent  —  Step 5a: Agentic Live App Explorer
====================================================
Multi-step agentic loop: Claude sees the current accessibility tree,
decides what action to take next (click, fill, navigate, observe),
executes it via Playwright, captures new state, and repeats.

Unlike capture_browser_elements() (one-shot snapshot), this agent:
  • Explores multi-step flows  (Settings → enable toggle → Save → verify toast)
  • Captures element state at every step of the journey
  • Produces a UITrace used by automation_writer for grounded code generation
  • Means zero hallucinated locators — every locator comes from real UI

Usage:
    from pipeline.chrome_agent import explore_with_agent, UITrace
    trace = explore_with_agent(
        card_name="FedEx Hold at Location",
        acceptance_criteria="## AC\\n- User can enable Hold at Location...",
        app_path="settings/additional-services",
        max_steps=12,
    )
    # trace.final_elements       → rich context for automation_writer
    # trace.navigation_path      → human-readable what the agent did
    # trace.to_context_string()  → full block passed to code gen prompt
"""
import json
import logging
import os
import re
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from textwrap import dedent

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage

import config

logger = logging.getLogger(__name__)

CODEBASE  = Path(config.AUTOMATION_CODEBASE_PATH)
AUTH_JSON = CODEBASE / "auth.json"
ENV_FILE  = CODEBASE / ".env"


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class ExplorationStep:
    step_num: int
    action_type: str          # "navigate" | "click" | "fill" | "observe" | "scroll" | "done"
    description: str          # what Claude decided to do and why
    target: str = ""          # element text/label targeted
    value: str = ""           # fill value (only for fill actions)
    elements_captured: list[str] = field(default_factory=list)  # key UI elements at this state
    success: bool = True


@dataclass
class UITrace:
    card_name: str
    app_url: str
    steps: list[ExplorationStep] = field(default_factory=list)
    error: str = ""

    @property
    def final_elements(self) -> str:
        """All unique elements captured across every step — rich context for code gen."""
        seen: list[str] = []
        seen_set: set[str] = set()
        for step in self.steps:
            for el in step.elements_captured:
                key = el.lower().strip()
                if key and key not in seen_set:
                    seen.append(el)
                    seen_set.add(key)
        return "\n".join(seen)

    @property
    def navigation_path(self) -> str:
        """Concise human-readable summary of the agent's journey."""
        icon_map = {
            "click": "🖱", "fill": "✍️", "navigate": "🌐",
            "observe": "👁", "scroll": "↕️", "done": "✅",
        }
        lines = []
        for s in self.steps:
            icon = icon_map.get(s.action_type, "→")
            ok = "" if s.success else " ❌"
            target = f" → '{s.target}'" if s.target else ""
            lines.append(f"  {s.step_num}. {icon} {s.description}{target}{ok}")
        return "\n".join(lines)

    def to_context_string(self) -> str:
        """Full context block passed to the automation writer prompt."""
        lines = [
            f"=== Chrome Agent Live Exploration: {self.card_name} ===",
            f"URL: {self.app_url}",
            f"Steps taken: {len(self.steps)}",
            "",
            "Navigation path:",
            self.navigation_path or "  (no steps recorded)",
            "",
            "All UI elements captured (grounded locators):",
            self.final_elements or "  (none captured)",
        ]
        return "\n".join(lines)

    def to_report(self) -> str:
        """Formatted report for the dashboard."""
        if self.error:
            return f"❌ Agent error: {self.error}"
        lines = [
            f"**{self.card_name}** — {len(self.steps)} steps",
            self.navigation_path,
            "",
            "**Elements captured:**",
        ]
        elements = self.final_elements.splitlines()
        lines += [f"• {e}" for e in elements[:20]]
        if len(elements) > 20:
            lines.append(f"…and {len(elements) - 20} more")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

AGENT_STEP_PROMPT = dedent("""\
    You are a QA engineer navigating the FedEx Shopify App to explore a feature
    for automation test generation. The app runs inside a Shopify iframe.

    FEATURE BEING EXPLORED: {card_name}

    ACCEPTANCE CRITERIA:
    {ac}

    CURRENT PAGE URL: {url}

    CURRENT ACCESSIBILITY TREE (what is visible right now):
    {ax_tree}

    STEPS TAKEN SO FAR ({step_num} of max {max_steps}):
    {trace_so_far}

    UI ELEMENTS CAPTURED SO FAR (for test generation):
    {elements_so_far}

    Decide your NEXT action. Respond ONLY in this JSON format (no extra text):
    {{
      "action": "click" | "fill" | "observe" | "scroll" | "done",
      "target": "<exact element name/label visible in the accessibility tree above>",
      "value": "<text to type — only needed for fill action>",
      "description": "<one sentence: what you are doing and why>",
      "elements_captured": [
        "<key UI element for test generation, e.g. 'button: Save'>",
        "<toggle: FedEx One Rate [checked=false]>",
        "<input: Default Box Length>"
      ]
    }}

    Rules:
    - ONLY reference targets that literally appear in the CURRENT accessibility tree
    - action = "done" when you have covered all main scenarios from the AC
    - action = "observe" to record elements without interacting (first step is usually observe)
    - For "click": target = exact button/link/checkbox name as shown in the tree
    - For "fill": target = input label, value = example text to enter
    - elements_captured: list EVERY button, toggle, input, checkbox visible — tests will need these
    - Stop when you have: seen the feature's main UI, one enable/disable cycle, one save flow
    - Do NOT explore unrelated sections (orders, products, etc.)
""")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_store_url() -> str:
    """Read STORE variable from automation repo .env file."""
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith("#") or "=" not in stripped:
                continue
            key, _, val = stripped.partition("=")
            if key.strip() == "STORE":
                val = val.strip().strip('"').strip("'")
                if val and not val.startswith("your-"):
                    return val
    return ""


def _ax_tree_to_text(node: dict, depth: int = 0, lines: list | None = None) -> str:
    """Recursively flatten accessibility tree into readable text for Claude."""
    if lines is None:
        lines = []
    if depth > 5 or len(lines) > 80:
        return "\n".join(lines)

    role  = node.get("role", "")
    name  = node.get("name", "")
    checked = node.get("checked")
    value = node.get("value", "")

    skip_roles = {"generic", "none", "presentation", "document", "group", "list"}
    if role and name and role not in skip_roles:
        line = f"{'  ' * depth}{role}: '{name}'"
        if checked is not None:
            line += f" [checked={checked}]"
        if value and role in ("textbox", "combobox", "spinbutton"):
            line += f" [value='{value}']"
        lines.append(line)

    for child in node.get("children", []):
        _ax_tree_to_text(child, depth + 1, lines)
    return "\n".join(lines)


def _get_frame_snapshot(frame) -> str:
    """Capture accessibility tree text from the app iframe."""
    try:
        ax = frame.accessibility.snapshot(interesting_only=True)
        if ax:
            return _ax_tree_to_text(ax)
    except Exception as exc:
        logger.warning("Accessibility snapshot failed: %s", exc)
    return "(accessibility tree unavailable)"


def _execute_action(frame, action: dict) -> bool:
    """
    Execute a Claude-decided action on the iframe.
    Returns True on success, False if the target wasn't found.
    """
    action_type = action.get("action", "observe")
    target      = action.get("target", "").strip()
    value       = action.get("value", "")

    if action_type in ("done", "observe", "scroll"):
        if action_type == "scroll":
            try:
                frame.evaluate("window.scrollBy(0, 400)")
            except Exception:
                pass
        return True

    if not target:
        return False

    try:
        if action_type == "click":
            # Try locator strategies in priority order
            strategies = [
                lambda: frame.get_by_role("button",   name=target, exact=False),
                lambda: frame.get_by_role("link",     name=target, exact=False),
                lambda: frame.get_by_role("checkbox", name=target, exact=False),
                lambda: frame.get_by_role("tab",      name=target, exact=False),
                lambda: frame.get_by_text(target, exact=False),
                lambda: frame.get_by_label(target, exact=False),
            ]
            for strategy in strategies:
                try:
                    el = strategy()
                    if el.count() > 0:
                        el.first.click(timeout=5000)
                        logger.debug("Clicked: '%s'", target)
                        return True
                except Exception:
                    continue
            logger.warning("Click target not found: '%s'", target)
            return False

        elif action_type == "fill":
            strategies = [
                lambda: frame.get_by_label(target, exact=False),
                lambda: frame.get_by_placeholder(target, exact=False),
                lambda: frame.get_by_role("textbox", name=target, exact=False),
            ]
            for strategy in strategies:
                try:
                    el = strategy()
                    if el.count() > 0:
                        el.first.clear()
                        el.first.fill(value, timeout=5000)
                        logger.debug("Filled '%s' with '%s'", target, value)
                        return True
                except Exception:
                    continue
            logger.warning("Fill target not found: '%s'", target)
            return False

    except Exception as exc:
        logger.warning("Action failed [%s '%s']: %s", action_type, target, exc)
        return False

    return True


def _ask_claude(
    claude: ChatAnthropic,
    card_name: str,
    ac: str,
    url: str,
    ax_tree: str,
    step_num: int,
    max_steps: int,
    trace: UITrace,
    all_elements: list[str],
) -> dict:
    """Ask Claude to decide the next action. Returns parsed action dict."""
    trace_lines = [
        f"Step {s.step_num}: [{s.action_type}] {s.description}"
        for s in trace.steps
    ]
    prompt = AGENT_STEP_PROMPT.format(
        card_name=card_name,
        ac=ac[:1500],
        url=url,
        ax_tree=ax_tree[:3000],
        step_num=step_num,
        max_steps=max_steps,
        trace_so_far="\n".join(trace_lines) if trace_lines else "(starting now)",
        elements_so_far="\n".join(all_elements[:30]) if all_elements else "(none yet)",
    )

    resp = claude.invoke([HumanMessage(content=prompt)])

    # Handle both plain string and list-of-blocks content formats
    content = resp.content
    if isinstance(content, list):
        raw = " ".join(
            block.get("text", "") if isinstance(block, dict) else str(block)
            for block in content
        ).strip()
    else:
        raw = str(content).strip()

    if not raw:
        logger.warning("Claude returned empty response")
        return {"action": "stop", "reasoning": "Claude returned empty response", "elements": []}

    json_text = re.sub(r"```(?:json)?\n?", "", raw).strip().rstrip("`")

    try:
        return json.loads(json_text)
    except json.JSONDecodeError:
        logger.warning("Claude returned non-JSON response: %s", raw[:300])
        return {"action": "stop", "reasoning": f"Claude response was not valid JSON: {raw[:100]}", "elements": []}


# ---------------------------------------------------------------------------
# Public function
# ---------------------------------------------------------------------------

def explore_with_agent(
    card_name: str,
    acceptance_criteria: str,
    app_path: str = "",
    max_steps: int = 12,
) -> UITrace:
    """
    Run the Chrome agent to explore the FedEx Shopify app for a feature.

    The agent navigates to the relevant section, walks through the feature
    UI using the AC as a guide, captures real elements at each step, and
    returns a UITrace for grounded Playwright spec generation.

    Args:
        card_name:          Feature name, e.g. "FedEx Hold at Location"
        acceptance_criteria: Full AC text from the Trello card
        app_path:           URL sub-path in the app, e.g. "settings/additional-services"
        max_steps:          Max exploration steps (default 12, capped at 20)

    Returns:
        UITrace — navigation path + all elements captured
    """
    max_steps = min(max_steps, 20)

    # Guard: auth.json must exist and contain valid JSON — auto-run setup if not
    def _auth_valid() -> bool:
        try:
            content = AUTH_JSON.read_text(encoding="utf-8").strip()
            if not content:
                return False
            json.loads(content)
            return True
        except Exception:
            return False

    if not _auth_valid():
        logger.info("auth.json missing or invalid — running Playwright setup to generate it…")
        try:
            result = subprocess.run(
                ["npx", "playwright", "test", "--project=setup"],
                cwd=str(CODEBASE),
                timeout=180,
                capture_output=True,
                text=True,
            )
            if not _auth_valid():
                return UITrace(
                    card_name=card_name,
                    app_url="",
                    error=(
                        "Playwright setup ran but auth.json is still missing or invalid.\n"
                        f"Setup output:\n{result.stdout[-500:] if result.stdout else ''}\n"
                        f"{result.stderr[-300:] if result.stderr else ''}"
                    ),
                )
            logger.info("auth.json generated successfully via setup")
        except subprocess.TimeoutExpired:
            return UITrace(
                card_name=card_name,
                app_url="",
                error="Playwright setup timed out after 3 minutes. Run it manually: `npx playwright test --project=setup`",
            )
        except FileNotFoundError:
            return UITrace(
                card_name=card_name,
                app_url="",
                error="npx not found — ensure Node.js is installed and `npm install` has been run in the automation repo.",
            )

    # app_url will be read from the TypeScript output (it builds it from its own .env)
    trace = UITrace(card_name=card_name, app_url="")

    # ── Call the TypeScript explorer (uses existing fixtures/auth infra) ──
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
        output_path = tmp.name

    try:
        logger.info("Running TS explorer: '%s' (path=%s)", card_name, app_path)
        env = {**os.environ, "EXPLORE_APP_PATH": app_path, "EXPLORE_OUTPUT": output_path}
        result = subprocess.run(
            ["npx", "playwright", "test", "src/setup/exploreApp.ts",
             "--project=explore", "--reporter=line"],
            cwd=str(CODEBASE),
            timeout=120,
            capture_output=True,
            text=True,
            env=env,
        )
        logger.info("TS explorer exit=%d stdout=%s stderr=%s",
                    result.returncode, result.stdout[-300:], result.stderr[-300:])

        if not os.path.exists(output_path):
            trace.error = f"Explorer produced no output.\n{result.stderr[-500:]}"
            return trace

        data = json.loads(Path(output_path).read_text(encoding="utf-8"))

        # Use the URL that TypeScript actually navigated to (built from its own .env)
        if data.get("app_url"):
            trace.app_url = data["app_url"]

        if data.get("error"):
            trace.error = data["error"]
            return trace

        elements: list[str] = data.get("elements", [])
        steps_log: list[str] = data.get("steps", [])

        # Build trace from results
        for i, s in enumerate(steps_log, 1):
            trace.steps.append(ExplorationStep(
                step_num=i,
                action_type="observe",
                description=s,
                elements_captured=[],
            ))

        trace.steps.append(ExplorationStep(
            step_num=len(steps_log) + 1,
            action_type="done",
            description=f"Captured {len(elements)} elements",
            elements_captured=elements,
        ))

        logger.info("Chrome agent complete — %d elements captured", len(elements))

    except subprocess.TimeoutExpired:
        trace.error = "Explorer timed out after 2 minutes"
    except FileNotFoundError:
        trace.error = "npx/ts-node not found — run `npm install` in the automation repo"
    except Exception as exc:
        import traceback
        tb = traceback.format_exc()
        logger.error("Chrome agent error: %s\n%s", exc, tb)
        trace.error = f"{exc}\n\nTraceback:\n{tb}"
    finally:
        try:
            os.unlink(output_path)
        except Exception:
            pass

    return trace
