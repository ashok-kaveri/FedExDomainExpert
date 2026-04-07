"""
Doc Generator  —  Step 7 of the Delivery Pipeline
===================================================
After sign-off and test run, generates:

  1. A feature documentation file saved to the automation repo:
       docs/features/{card-slug}.md

  2. A CHANGELOG.md entry appended to:
       docs/CHANGELOG.md

The doc is grounded in:
  • The card's acceptance criteria
  • The generated test cases
  • KB context retrieved from the RAG vector store
  • The spec + POM file paths

Usage:
    from pipeline.doc_generator import generate_feature_doc
    result = generate_feature_doc(
        card_name="FedEx Hold at Location",
        acceptance_criteria="...",
        test_cases="...",
        spec_file="tests/holdAtLocation/holdAtLocation.spec.ts",
        release="FedExapp 2.3.115",
    )
    # result["doc_path"]     → "docs/features/fedex-hold-at-location.md"
    # result["doc_content"]  → full markdown
    # result["changelog_entry"] → the line added to CHANGELOG.md
"""
import logging
import re
from datetime import date
from pathlib import Path
from textwrap import dedent

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage

import config
from rag.vectorstore import search

logger = logging.getLogger(__name__)

CODEBASE  = Path(config.AUTOMATION_CODEBASE_PATH)
DOCS_DIR  = CODEBASE / "docs" / "features"
CHANGELOG = CODEBASE / "docs" / "CHANGELOG.md"


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

DOC_PROMPT = dedent("""\
    You are a senior QA engineer writing technical feature documentation for
    the FedEx Shopify App Playwright automation suite.

    Write a concise feature document in Markdown using EXACTLY this structure
    (no extra sections, no omissions):

    # {card_name}

    **Release:** {release}
    **Date:** {today}
    **Spec:** `{spec_file}`
    **POM:** `{pom_file}`

    ## Overview
    (2–3 sentences: what the feature does, why QA cares about it)

    ## Test Coverage
    (Bullet list of what is automated — positive scenarios, negative scenarios, edge cases)

    ## Key UI Elements
    (Exact element names used in locators — button labels, toggle names, input labels)

    ## Known Constraints
    (API limits, FedEx account requirements, Shopify restrictions — from KB context below)

    ## QA Notes
    (Manual steps needed, known automation limitations, or watch-out points)

    ---
    Source data:

    Card: {card_name}
    Release: {release}

    Acceptance Criteria:
    {ac}

    Test Cases:
    {test_cases}

    KB Context (constraints & behaviour):
    {kb_context}

    Rules:
    - Each section: 3–5 bullet points maximum
    - Write for a QA engineer who has never seen this feature before
    - Keep the tone direct and factual — no marketing language
    - Do NOT add sections not listed above
""")


# ---------------------------------------------------------------------------
# Public function
# ---------------------------------------------------------------------------

def generate_feature_doc(
    card_name: str,
    acceptance_criteria: str,
    test_cases: str = "",
    spec_file: str = "",
    pom_file: str = "",
    release: str = "",
) -> dict:
    """
    Generate a markdown feature document and append a CHANGELOG entry.

    Args:
        card_name:           Feature name from the Trello card
        acceptance_criteria: Full AC markdown
        test_cases:          Generated test cases markdown
        spec_file:           Relative path to spec file (e.g. "tests/foo/foo.spec.ts")
        pom_file:            Relative path to POM file (e.g. "src/pages/app/foo.ts")
        release:             Release label (e.g. "FedExapp 2.3.115")

    Returns:
        {
            "doc_path":         str   — relative path to saved doc file
            "doc_content":      str   — full markdown content
            "changelog_entry":  str   — the CHANGELOG line added
            "error":            str   — non-empty if something failed
        }
    """
    result: dict = {
        "doc_path": "",
        "doc_content": "",
        "changelog_entry": "",
        "error": "",
    }

    if not config.ANTHROPIC_API_KEY:
        result["error"] = "ANTHROPIC_API_KEY not set"
        return result

    today = date.today().isoformat()

    # ── RAG context ────────────────────────────────────────────────────────
    try:
        rag_query = f"{card_name} {acceptance_criteria[:300]}"
        docs = search(rag_query, k=4)
        kb_context = "\n\n".join(
            f"[{d.metadata.get('source', 'KB')}]\n{d.page_content}"
            for d in docs
        )
    except Exception as exc:
        logger.warning("RAG search failed in doc_generator: %s", exc)
        kb_context = "No KB context available."

    # ── Ask Claude to write the doc ────────────────────────────────────────
    prompt = DOC_PROMPT.format(
        card_name=card_name,
        release=release or "Unknown",
        today=today,
        spec_file=spec_file or "(not generated yet)",
        pom_file=pom_file or "(not generated yet)",
        ac=acceptance_criteria[:2000],
        test_cases=test_cases[:1500],
        kb_context=kb_context[:1200],
    )

    try:
        llm = ChatAnthropic(
            model=config.CLAUDE_SONNET_MODEL,
            api_key=config.ANTHROPIC_API_KEY,
            temperature=0.2,
            max_tokens=1800,
        )
        resp = llm.invoke([HumanMessage(content=prompt)])
        doc_content = resp.content.strip()
        result["doc_content"] = doc_content
    except Exception as exc:
        logger.error("Claude doc generation failed: %s", exc)
        result["error"] = f"Claude error: {exc}"
        return result

    # ── Save to docs/features/{slug}.md ───────────────────────────────────
    slug = re.sub(r"[^a-z0-9]+", "-", card_name.lower()).strip("-")
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    doc_path = DOCS_DIR / f"{slug}.md"

    try:
        doc_path.write_text(doc_content, encoding="utf-8")
        result["doc_path"] = str(doc_path.relative_to(CODEBASE))
        logger.info("Feature doc saved: %s", result["doc_path"])
    except Exception as exc:
        logger.error("Failed to write doc file: %s", exc)
        result["error"] = f"File write error: {exc}"
        return result

    # ── Append CHANGELOG entry ─────────────────────────────────────────────
    changelog_entry = (
        f"\n### [{release or 'Unreleased'}] — {today}\n"
        f"- **{card_name}**\n"
        f"  - Spec: `{spec_file}`\n"
        f"  - Docs: [docs/features/{slug}.md](docs/features/{slug}.md)\n"
    )
    result["changelog_entry"] = changelog_entry.strip()

    try:
        CHANGELOG.parent.mkdir(parents=True, exist_ok=True)

        if CHANGELOG.exists():
            existing = CHANGELOG.read_text(encoding="utf-8")
            # Insert new entry after the first line (title)
            lines = existing.splitlines()
            insert_idx = 1
            for i, line in enumerate(lines):
                if line.startswith("### [") or line.startswith("## ["):
                    insert_idx = i
                    break
            lines.insert(insert_idx, changelog_entry)
            CHANGELOG.write_text("\n".join(lines), encoding="utf-8")
        else:
            CHANGELOG.write_text(
                f"# FedEx Automation — Changelog\n{changelog_entry}",
                encoding="utf-8",
            )
        logger.info("CHANGELOG updated for: %s", card_name)
    except Exception as exc:
        logger.warning("CHANGELOG update failed (doc still saved): %s", exc)
        # Don't fail — doc is already written

    return result


# ---------------------------------------------------------------------------
# Bulk helper — generate docs for all cards in a release
# ---------------------------------------------------------------------------

def generate_release_docs(
    release: str,
    cards_data: list[dict],
) -> list[dict]:
    """
    Generate docs for every card in a release.

    Args:
        release:     Release label
        cards_data:  List of dicts with keys:
                       card_name, acceptance_criteria, test_cases,
                       spec_file, pom_file

    Returns:
        List of result dicts (one per card), same shape as generate_feature_doc()
    """
    results = []
    for card in cards_data:
        logger.info("Generating doc for: %s", card.get("card_name", "?"))
        result = generate_feature_doc(
            card_name=card.get("card_name", "Unknown"),
            acceptance_criteria=card.get("acceptance_criteria", ""),
            test_cases=card.get("test_cases", ""),
            spec_file=card.get("spec_file", ""),
            pom_file=card.get("pom_file", ""),
            release=release,
        )
        results.append(result)
    return results
