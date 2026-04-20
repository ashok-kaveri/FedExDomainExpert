"""
Test Writer — Existing Feature  (Step 5b)
==========================================
When the feature detector finds existing test coverage, this module:
  1. Reads the related spec files from the automation repo
  2. Compares the old acceptance criteria (from ChromaDB) with the new AC
  3. Claude generates a minimal diff / updated test code
  4. Writes the updated files and creates a git branch for manual review

Manual review is intentional — modifying existing tests is higher risk
than generating new ones.

Usage:
    from pipeline.test_writer.old_feature import update_existing_tests
    result = update_existing_tests(
        card_name="FedEx Saturday Delivery toggle",
        new_ac="...",
        related_files=["tests/labels/labelDomestic.spec.ts"],
    )
"""
from __future__ import annotations
import logging
import re
import subprocess
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

DIFF_GENERATOR_PROMPT = dedent("""\
    You are a senior test automation engineer for the FedEx Shopify App.

    An existing feature has been updated. Your job is to update the existing
    Playwright TypeScript tests to match the new acceptance criteria.

    FEATURE: {card_name}

    NEW ACCEPTANCE CRITERIA:
    {new_ac}

    EXISTING TEST FILE ({file_path}):
    {existing_content}

    Instructions:
    1. Identify which existing tests are affected by the new AC
    2. Update ONLY what needs to change — do not rewrite unaffected tests
    3. Add new test cases for any scenarios not yet covered
    4. Keep all existing passing tests intact

    Return the COMPLETE updated file content.
    Start your response with: === UPDATED FILE: {file_path} ===
    Then the full file content. No markdown fences.
""")

REVIEW_SUMMARY_PROMPT = dedent("""\
    Summarise the changes made to the test file in 3-5 bullet points.
    Be specific about which test cases were added, modified, or removed.

    Original file snippet:
    {original}

    Updated file snippet:
    {updated}
""")


# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------

def _create_branch(branch_name: str) -> bool:
    """Create and checkout a new git branch in the automation repo."""
    try:
        subprocess.run(
            ["git", "-C", str(CODEBASE_PATH), "checkout", "-b", branch_name],
            check=True, capture_output=True, text=True,
        )
        logger.info("Created branch: %s", branch_name)
        return True
    except subprocess.CalledProcessError as e:
        logger.warning("Could not create branch '%s': %s", branch_name, e.stderr)
        return False


def _stage_and_commit(files: list[str], message: str) -> bool:
    """Stage specified files and commit in the automation repo."""
    try:
        subprocess.run(
            ["git", "-C", str(CODEBASE_PATH), "add"] + files,
            check=True, capture_output=True,
        )
        subprocess.run(
            ["git", "-C", str(CODEBASE_PATH), "commit", "-m", message],
            check=True, capture_output=True,
        )
        logger.info("Committed: %s", message)
        return True
    except subprocess.CalledProcessError as e:
        logger.warning("Git commit failed: %s", e)
        return False


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------

def _update_single_file(
    file_path: str,
    card_name: str,
    new_ac: str,
    claude: ChatAnthropic,
) -> tuple[str, str]:
    """
    Read one spec file, ask Claude to update it, return (original, updated).
    """
    abs_path = CODEBASE_PATH / file_path
    if not abs_path.exists():
        # Try treating file_path as absolute
        abs_path = Path(file_path)
    if not abs_path.exists():
        logger.warning("File not found: %s", file_path)
        return "", ""

    original = abs_path.read_text(encoding="utf-8", errors="ignore")

    prompt = DIFF_GENERATOR_PROMPT.format(
        card_name=card_name,
        new_ac=new_ac,
        file_path=file_path,
        existing_content=original[:6000],  # Claude context window safe limit
    )

    response = claude.invoke([HumanMessage(content=prompt)])
    raw = response.content.strip()

    # Parse === UPDATED FILE: ... === block
    match = re.search(r"=== UPDATED FILE:.+?===\n([\s\S]+)", raw)
    if match:
        updated = match.group(1).strip()
    else:
        # Fallback: assume entire response is the file
        updated = raw

    return original, updated


def update_existing_tests(
    card_name: str,
    new_ac: str,
    related_files: list[str],
    dry_run: bool = False,
    create_pr_branch: bool = True,
) -> dict:
    """
    Update existing test files to cover new/changed acceptance criteria.

    Args:
        card_name:      Feature name from the Trello card
        new_ac:         New acceptance criteria markdown
        related_files:  Spec file paths from feature_detector
        dry_run:        If True, print diffs but don't write files
        create_pr_branch: If True, commit changes to a new git branch for PR

    Returns:
        {
          "files_updated": [str, ...],
          "branch": str,          # git branch name (empty if dry_run)
          "change_summaries": {file: summary},
          "skipped": bool,
        }
    """
    if not config.ANTHROPIC_API_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY not set in .env")
    if CODEBASE_PATH is None:
        raise RuntimeError("AUTOMATION_CODEBASE_PATH not set in .env")
    if not related_files:
        logger.warning("No related files provided — nothing to update")
        return {"files_updated": [], "branch": "", "change_summaries": {}, "skipped": True}

    claude = ChatAnthropic(
        model=config.CLAUDE_SONNET_MODEL,
        api_key=config.ANTHROPIC_API_KEY,
        temperature=0.1,
        max_tokens=4096,
    )

    # Create a feature branch for the changes
    safe_name = re.sub(r"[^a-z0-9]+", "-", card_name.lower()).strip("-")
    branch_name = f"test-update/{safe_name}"
    if not dry_run and create_pr_branch:
        _create_branch(branch_name)

    updated_files = []
    summaries = {}

    for file_path in related_files:
        logger.info("Updating: %s", file_path)
        original, updated = _update_single_file(file_path, card_name, new_ac, claude)

        if not updated:
            logger.warning("Skipping %s — no update generated", file_path)
            continue

        if dry_run:
            logger.info("[DRY RUN] Would update %s", file_path)
            # Show first 500 chars of update
            print(f"\n--- Updated: {file_path} ---\n{updated[:500]}\n")
        else:
            abs_path = CODEBASE_PATH / file_path
            if not abs_path.exists():
                abs_path = Path(file_path)
            abs_path.write_text(updated, encoding="utf-8")
            updated_files.append(str(abs_path))
            logger.info("Written: %s", abs_path)

        # Generate change summary
        summary_prompt = REVIEW_SUMMARY_PROMPT.format(
            original=original[:800],
            updated=updated[:800],
        )
        summary_resp = claude.invoke([HumanMessage(content=summary_prompt)])
        summaries[file_path] = summary_resp.content.strip()

    # Commit all updated files
    if not dry_run and updated_files and create_pr_branch:
        _stage_and_commit(
            [str(CODEBASE_PATH / f) for f in related_files],
            f"test(automation): update tests for '{card_name}'\n\nAuto-generated by FedEx Pipeline — requires manual review.",
        )

    return {
        "files_updated": updated_files,
        "branch": branch_name if not dry_run else "",
        "change_summaries": summaries,
        "skipped": False,
    }
