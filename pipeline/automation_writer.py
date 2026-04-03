"""
Automation Writer  —  Pipeline Step 5
======================================
After test cases are approved, this module generates Playwright + TypeScript
automation code following the exact conventions of the fedex-test-automation repo.

Flow:
  1. Feature Detector classifies card as NEW or EXISTING feature
  2a. NEW feature  → generate POM + spec + update fixtures.ts
  2b. EXISTING     → read related spec files + update with new test cases
  3. Create git branch in automation repo: automation/<card-slug>
  4. Commit all changes + push to origin (NOT main)
  5. Return branch name + file paths for dashboard display

Conventions enforced (from fedExSkill.md):
  - Import test/expect from '../../src/setup/fixtures' (NOT @playwright/test)
  - Page objects extend BasePage, locators use this.appFrame (app iframe)
  - Locators are readonly class properties, NOT created inside methods
  - test.describe.configure({ mode: 'serial' }) on every describe block
  - No page.waitForTimeout() — use expect() with timeout instead
  - New pages must be registered in src/setup/fixtures.ts
"""
import json
import logging
import re
import subprocess
from pathlib import Path
from textwrap import dedent

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage

import config
from pipeline.feature_detector import detect_feature, DetectionResult

logger = logging.getLogger(__name__)

CODEBASE = Path(config.AUTOMATION_CODEBASE_PATH)
SKILL_MD  = CODEBASE / "fedExSkill.md"


# ---------------------------------------------------------------------------
# Load project conventions from fedExSkill.md
# ---------------------------------------------------------------------------

def _load_conventions() -> str:
    """Load the project conventions guide from fedExSkill.md."""
    if SKILL_MD.exists():
        content = SKILL_MD.read_text(encoding="utf-8", errors="ignore")
        # Skip the YAML frontmatter
        if content.startswith("---"):
            parts = content.split("---", 2)
            return parts[2].strip() if len(parts) >= 3 else content
        return content
    return "fedExSkill.md not found — use standard Playwright POM conventions."


# ---------------------------------------------------------------------------
# Load existing files for reference
# ---------------------------------------------------------------------------

def _load_pom_samples(n: int = 2) -> str:
    """Load existing page objects as style reference."""
    pages_dir = CODEBASE / "src" / "pages" / "app"
    if not pages_dir.exists():
        return ""
    samples = []
    for ts_file in list(pages_dir.rglob("*.ts"))[:n]:
        rel = ts_file.relative_to(CODEBASE)
        content = ts_file.read_text(encoding="utf-8", errors="ignore")
        samples.append(f"// {rel}\n{content[:1000]}")
    return "\n\n---\n\n".join(samples)


def _load_spec_sample() -> str:
    """Load one existing spec for reference."""
    tests_dir = CODEBASE / "tests"
    if not tests_dir.exists():
        return ""
    for ts_file in tests_dir.rglob("*.spec.ts"):
        rel = ts_file.relative_to(CODEBASE)
        content = ts_file.read_text(encoding="utf-8", errors="ignore")
        return f"// {rel}\n{content[:1200]}"
    return ""


def _read_file(rel_path: str) -> str:
    """Read a file from the automation repo."""
    abs_path = CODEBASE / rel_path
    if not abs_path.exists():
        abs_path = Path(rel_path)
    if not abs_path.exists():
        return ""
    return abs_path.read_text(encoding="utf-8", errors="ignore")


# ---------------------------------------------------------------------------
# Slug / path helpers
# ---------------------------------------------------------------------------

_AREA_MAP = {
    "label": "label_generation",
    "return": "returnLabels",
    "pickup": "pickup",
    "packaging": "packaging",
    "product": "product_Special_Service",
    "signature": "product_Special_Service",
    "dry ice": "additionalServices",
    "additional": "additionalServices",
    "duties": "additionalServices",
    "tax": "additionalServices",
    "onboard": "onboarding",
    "install": "onboarding",
    "setting": "additionalServices",
}


def _slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _camel(text: str) -> str:
    words = re.sub(r"[^a-zA-Z0-9 ]", "", text).split()
    if not words:
        return "newFeature"
    return words[0].lower() + "".join(w.title() for w in words[1:])


def _pascal(text: str) -> str:
    words = re.sub(r"[^a-zA-Z0-9 ]", "", text).split()
    return "".join(w.title() for w in words) if words else "NewFeature"


def _detect_area(card_name: str) -> str:
    lower = card_name.lower()
    for kw, folder in _AREA_MAP.items():
        if kw in lower:
            return folder
    return "additionalServices"


def _spec_path(card_name: str) -> str:
    return f"tests/{_detect_area(card_name)}/{_camel(card_name)}.spec.ts"


def _pom_dir(card_name: str) -> str:
    return f"src/pages/app/{_pascal(card_name)}"


def _pom_path(card_name: str) -> str:
    return f"{_pom_dir(card_name)}/{_pascal(card_name)}.ts"


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

NEW_FEATURE_PROMPT = dedent("""\
    You are a senior Playwright + TypeScript automation engineer for the FedEx Shopify App.

    ## Project Conventions (FOLLOW EXACTLY)
    {conventions}

    ## Existing POM Reference
    {pom_samples}

    ## Existing Spec Reference
    {spec_sample}

    ---
    ## Task: Generate automation for a NEW feature

    Feature Card: {card_name}
    Test Cases (positive scenarios to automate):
    {test_cases}

    Generate TWO files:

    === FILE 1: {spec_path} ===
    [complete spec file — import from fixtures, test.describe.configure serial,
     use pages fixture, every test has expect(), no waitForTimeout > 3s]

    === FILE 2: {pom_path} ===
    [complete POM — extends BasePage, readonly locators in constructor,
     this.appFrame for app iframe locators, this.page for Shopify admin locators,
     action methods that use the locators]

    Use exactly the === FILE N: path === delimiter.
    Write complete working TypeScript. No placeholder comments.
    Locators should reflect the actual FedEx app UI described in the test cases.
""")

EXISTING_FEATURE_PROMPT = dedent("""\
    You are a senior Playwright + TypeScript automation engineer for the FedEx Shopify App.

    ## Project Conventions (FOLLOW EXACTLY)
    {conventions}

    ---
    ## Task: Update existing automation for a changed feature

    Feature Card: {card_name}
    New test cases to add:
    {test_cases}

    ## Existing file to update ({file_path}):
    {existing_content}

    Instructions:
    1. Add new test cases for scenarios not yet covered
    2. Update any tests affected by the new acceptance criteria
    3. Keep all existing unaffected tests unchanged
    4. Every new test must have at least one expect() assertion
    5. No test.only(), no waitForTimeout() > 3s

    Return the COMPLETE updated file content.
    Start with: === UPDATED FILE: {file_path} ===
    Then the full TypeScript content. No markdown fences.
""")

FIXTURES_UPDATE_PROMPT = dedent("""\
    The following new page object class needs to be registered in src/setup/fixtures.ts.

    New class name: {class_name}
    Import path (relative to fixtures.ts): {import_path}
    Property name in Pages type: {property_name}

    Current fixtures.ts content:
    {fixtures_content}

    Return the COMPLETE updated fixtures.ts.
    Start with: === UPDATED FILE: src/setup/fixtures.ts ===
    Then the full content. No markdown fences.
""")

REVIEW_PROMPT = dedent("""\
    Review this Playwright + TypeScript code for the FedEx Shopify App.

    Check for:
    1. Imports from '../../src/setup/fixtures' (not @playwright/test directly)
    2. All locators are readonly class properties (not inside methods)
    3. Uses this.appFrame for app iframe locators (not this.page for app elements)
    4. test.describe.configure({{ mode: 'serial' }}) present
    5. Every test has at least one expect() assertion
    6. No page.waitForTimeout() calls > 3000ms
    7. No test.only() calls

    File path: {file_path}
    Content:
    {content}

    Respond in JSON:
    {{
      "passed": true | false,
      "issues": ["issue 1", "issue 2"],
      "fixed_content": "corrected file content if issues found, else empty string"
    }}
""")


# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------

def _git(args: list[str], cwd: Path = CODEBASE) -> tuple[bool, str]:
    """Run a git command in the automation repo."""
    try:
        r = subprocess.run(
            ["git", "-C", str(cwd)] + args,
            capture_output=True, text=True, timeout=30,
        )
        return r.returncode == 0, (r.stdout + r.stderr).strip()
    except Exception as e:
        return False, str(e)


def _current_branch() -> str:
    ok, out = _git(["branch", "--show-current"])
    return out.strip() if ok else "main"


def _branch_exists(branch: str) -> bool:
    ok, out = _git(["branch", "--list", branch])
    return bool(out.strip())


def _create_and_checkout(branch: str) -> bool:
    if _branch_exists(branch):
        ok, _ = _git(["checkout", branch])
    else:
        ok, _ = _git(["checkout", "-b", branch])
    return ok


def _write_file(rel_path: str, content: str) -> Path:
    abs_path = CODEBASE / rel_path
    abs_path.parent.mkdir(parents=True, exist_ok=True)
    abs_path.write_text(content, encoding="utf-8")
    return abs_path


def _stage_and_commit(files: list[str], message: str) -> bool:
    _git(["add"] + files)
    ok, out = _git(["commit", "-m", message])
    if not ok:
        logger.warning("Git commit issue: %s", out)
    return ok


def _push_branch(branch: str) -> tuple[bool, str]:
    return _git(["push", "-u", "origin", branch])


# ---------------------------------------------------------------------------
# Code reviewer
# ---------------------------------------------------------------------------

def _review_and_fix(file_path: str, content: str, claude: ChatAnthropic) -> str:
    """Review generated code and auto-fix common issues."""
    prompt = REVIEW_PROMPT.format(file_path=file_path, content=content[:4000])
    try:
        resp = claude.invoke([HumanMessage(content=prompt)])
        raw = re.sub(r"```(?:json)?", "", resp.content).strip().rstrip("`")
        data = json.loads(raw)
        if not data.get("passed") and data.get("fixed_content"):
            logger.info("Auto-fixed issues in %s: %s", file_path, data.get("issues"))
            return data["fixed_content"]
    except Exception as e:
        logger.warning("Review step failed for %s: %s", file_path, e)
    return content


# ---------------------------------------------------------------------------
# Parse === FILE === blocks
# ---------------------------------------------------------------------------

def _parse_files(raw: str) -> dict[str, str]:
    pattern = r"=== FILE \d+: (.+?) ===\n([\s\S]*?)(?==== FILE|\Z)"
    files = {}
    for m in re.finditer(pattern, raw):
        path = m.group(1).strip()
        body = m.group(2).strip()
        body = re.sub(r"^```(?:typescript|ts)?\n?", "", body)
        body = re.sub(r"\n?```$", "", body)
        files[path] = body
    return files


def _parse_updated_file(raw: str, file_path: str) -> str:
    m = re.search(r"=== UPDATED FILE:.+?===\n([\s\S]+)", raw)
    if m:
        content = m.group(1).strip()
        content = re.sub(r"^```(?:typescript|ts)?\n?", "", content)
        return re.sub(r"\n?```$", "", content)
    return raw.strip()


# ---------------------------------------------------------------------------
# Main entry points
# ---------------------------------------------------------------------------

def _handle_new_feature(
    card_name: str,
    test_cases: str,
    claude: ChatAnthropic,
    dry_run: bool,
) -> dict:
    """Generate POM + spec + update fixtures for a brand-new feature."""
    conventions = _load_conventions()
    pom_samples = _load_pom_samples()
    spec_sample = _load_spec_sample()
    spec_path = _spec_path(card_name)
    pom_path  = _pom_path(card_name)
    class_name = _pascal(card_name) + "Page"
    property_name = _camel(card_name) + "Page"

    prompt = NEW_FEATURE_PROMPT.format(
        conventions=conventions[:3000],
        pom_samples=pom_samples[:2000],
        spec_sample=spec_sample[:1000],
        card_name=card_name,
        test_cases=test_cases,
        spec_path=spec_path,
        pom_path=pom_path,
    )

    logger.info("Generating new feature automation for: %s", card_name)
    resp = claude.invoke([HumanMessage(content=prompt)])
    files = _parse_files(resp.content.strip())

    if not files:
        return {"error": "Could not parse generated files", "files_written": [], "skipped": True}

    # Review + auto-fix each file
    for path, content in list(files.items()):
        files[path] = _review_and_fix(path, content, claude)

    written = []
    if not dry_run:
        for rel_path, content in files.items():
            _write_file(rel_path, content)
            written.append(rel_path)
            logger.info("Wrote: %s", rel_path)

        # Update fixtures.ts
        fixtures_content = _read_file("src/setup/fixtures.ts")
        if fixtures_content:
            # Relative import: from POM dir to fixtures.ts
            import_rel = f"../pages/app/{_pascal(card_name)}/{_pascal(card_name)}"
            fix_prompt = FIXTURES_UPDATE_PROMPT.format(
                class_name=class_name,
                import_path=import_rel,
                property_name=property_name,
                fixtures_content=fixtures_content[:4000],
            )
            fix_resp = claude.invoke([HumanMessage(content=fix_prompt)])
            updated_fixtures = _parse_updated_file(fix_resp.content, "src/setup/fixtures.ts")
            if updated_fixtures:
                _write_file("src/setup/fixtures.ts", updated_fixtures)
                written.append("src/setup/fixtures.ts")
                logger.info("Updated fixtures.ts with %s", class_name)

    return {
        "kind": "new",
        "spec_path": spec_path,
        "pom_path": pom_path,
        "files_written": written,
        "skipped": dry_run,
    }


def _handle_existing_feature(
    card_name: str,
    test_cases: str,
    related_files: list[str],
    claude: ChatAnthropic,
    dry_run: bool,
) -> dict:
    """Update existing spec files with new test cases."""
    conventions = _load_conventions()
    updated_files = []

    for file_path in related_files[:2]:   # limit to 2 files to avoid context overflow
        existing = _read_file(file_path)
        if not existing:
            logger.warning("Could not read: %s", file_path)
            continue

        prompt = EXISTING_FEATURE_PROMPT.format(
            conventions=conventions[:2000],
            card_name=card_name,
            test_cases=test_cases,
            file_path=file_path,
            existing_content=existing[:5000],
        )

        logger.info("Updating existing spec: %s", file_path)
        resp = claude.invoke([HumanMessage(content=prompt)])
        updated = _parse_updated_file(resp.content.strip(), file_path)
        updated = _review_and_fix(file_path, updated, claude)

        if not dry_run and updated:
            _write_file(file_path, updated)
            updated_files.append(file_path)
            logger.info("Updated: %s", file_path)

    return {
        "kind": "existing",
        "files_written": updated_files,
        "related_files": related_files,
        "skipped": dry_run,
    }


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
) -> dict:
    """
    Generate or update Playwright automation for a Trello card.

    Args:
        card_name:             Feature card title
        test_cases_markdown:   Approved test cases (all types — we filter to positive)
        acceptance_criteria:   AC for feature detection query
        branch_name:           Git branch to commit to (auto-generated if empty)
        dry_run:               If True, generate code but don't write/commit
        push:                  If True, push branch to origin after commit

    Returns dict with:
        kind, files_written, branch, pushed, spec_path, pom_path, error
    """
    if not config.ANTHROPIC_API_KEY:
        return {"error": "ANTHROPIC_API_KEY not set", "skipped": True}

    if not CODEBASE.exists():
        return {"error": f"Automation codebase not found at {CODEBASE}", "skipped": True}

    claude = ChatAnthropic(
        model=config.CLAUDE_SONNET_MODEL,
        api_key=config.ANTHROPIC_API_KEY,
        temperature=0.15,
        max_tokens=4096,
    )

    # Step 1: Detect new vs existing
    query = acceptance_criteria or test_cases_markdown[:500]
    detection: DetectionResult = detect_feature(card_name, query)
    logger.info("Feature detection: %s (%.0f%%) — %s",
                detection.kind, detection.confidence * 100, detection.reasoning[:80])

    # Step 2: Prepare branch
    auto_branch = f"automation/{_slugify(card_name)}"
    target_branch = branch_name or auto_branch

    original_branch = _current_branch()
    if not dry_run:
        if not _create_and_checkout(target_branch):
            logger.warning("Could not create branch '%s' — staying on '%s'",
                           target_branch, original_branch)

    # Step 3: Generate/update code
    if detection.kind == "existing" and detection.related_files:
        result = _handle_existing_feature(
            card_name, test_cases_markdown, detection.related_files, claude, dry_run
        )
    else:
        result = _handle_new_feature(card_name, test_cases_markdown, claude, dry_run)

    result["detection"] = {
        "kind": detection.kind,
        "confidence": detection.confidence,
        "reasoning": detection.reasoning,
        "related_files": detection.related_files,
    }
    result["branch"] = target_branch if not dry_run else ""

    if result.get("error") or result.get("skipped"):
        return result

    # Step 4: Commit
    if not dry_run and result.get("files_written"):
        commit_msg = (
            f"test(automation): {'add' if detection.kind == 'new' else 'update'} "
            f"tests for '{card_name}'\n\n"
            f"Generated by FedEx Pipeline — review before merging to main.\n"
            f"Detection: {detection.kind} ({detection.confidence:.0%} confidence)"
        )
        _stage_and_commit(result["files_written"], commit_msg)

    # Step 5: Push (only if explicitly requested)
    pushed = False
    push_error = ""
    if not dry_run and push and result.get("files_written"):
        ok, out = _push_branch(target_branch)
        pushed = ok
        if not ok:
            push_error = out
            logger.warning("Push failed: %s", out)

    result["pushed"] = pushed
    result["push_error"] = push_error

    return result
