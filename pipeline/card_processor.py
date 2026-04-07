"""
Card Processor  —  Step 2 of the Delivery Pipeline
====================================================
Takes a raw feature one-liner from the Trello backlog and uses Claude
to produce a proper Agile card with:
  • User Story  (As a … I want … So that …)
  • Acceptance Criteria  (Given / When / Then scenarios)
  • Priority  (High / Medium / Low)
  • Test scope  (what areas need automation coverage)

The formatted output is written back to the Trello card description
and the card is moved from "Iteration Backlog" → "Ready for Dev".

Usage (CLI):
    python -m pipeline.card_processor --card <TRELLO_CARD_ID>
    python -m pipeline.card_processor --list "Iteration Backlog"   # process all
"""
import argparse
import logging
import sys
from textwrap import dedent

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage

import config
from pipeline.trello_client import TrelloClient, TrelloCard

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

TEST_CASE_PROMPT = dedent("""\
    You are a senior QA engineer for the FedEx Shopify App built by PluginHive.

    Generate detailed test cases for the feature described below.

    IMPORTANT: Use EXACTLY this format for each test case:

    ### TC-{{n}}: <short title>
    **Type:** Positive | Negative | Edge
    **Priority:** High / Medium / Low
    **Preconditions:** <what must be true before testing>

    **Steps:**
    Given <the initial state or precondition, e.g. "I am logged in to the PH FedEx app">
    When <the first user action, e.g. "I navigate to Settings > Additional Services">
    And <additional action if needed>
    Then <the expected result>
    And <additional expected result if needed>

    Type definitions:
    - Positive  = happy path, feature works as expected
    - Negative  = invalid input, error states, wrong data
    - Edge      = boundary values, limits, unusual but valid scenarios

    Rules:
    - Every TC must have exactly one Type line
    - Start each step line with Given / When / And / Then (no numbers or dashes)
    - Use "PH FedEx app" to refer to the PluginHive FedEx Shopify App
    - Navigation paths like: Settings > Rate Settings > Carrier Services
    - Generate a mix: at least 2 Positive, 1–2 Negative, 1 Edge case

    ---
    Feature Card: {card_name}

    Card Description:
    {card_desc}
    ---

    Generate at least 4 test cases covering all three types.
""")

REGENERATE_PROMPT = dedent("""\
    You previously generated these test cases for the feature below.
    The reviewer has provided feedback. Update the test cases accordingly.

    Feature: {card_name}
    Card Description: {card_desc}

    Previous test cases:
    {previous_test_cases}

    Reviewer feedback:
    {feedback}

    Generate the updated test cases in the SAME format (Given/When/And/Then steps).
    Address ALL feedback points. Keep test cases not affected by the feedback unchanged.
""")

AC_WRITER_PROMPT = dedent("""\
    You are a senior QA engineer and product owner for the FedEx Shopify App
    built by PluginHive. Your job is to turn raw feature requests into
    well-structured Agile cards.

    Given the raw feature request below, produce:

    ## User Story
    As a [type of user], I want [goal], so that [benefit].

    ## Acceptance Criteria
    List each scenario in Given / When / Then format.
    Cover: happy path, edge cases, error states.

    ## Priority
    High / Medium / Low — justify in one sentence.

    ## Test Scope
    List the app sections and automation files that will need coverage.
    Reference existing test areas: Single Label, Rate Domestic/International,
    Label Domestic/International, Orders Grid, Settings, Pickup,
    Return Labels, Notifications, Print Settings, Locations, Bulk Orders.

    ## Out of Scope
    What this story explicitly does NOT cover.

    ## References
    Extract and list ALL URLs and links found anywhere in the raw feature request below.
    Include PR links, ticket links, BitBucket/GitLab/GitHub links, Zendesk links, changelogs, or any other URLs.
    Format each as: - [label or URL](URL)
    If no links are found, omit this section entirely.

    ---
    Raw feature request:
    {raw_request}
    ---

    Respond with clean markdown. No preamble.
""")


# ---------------------------------------------------------------------------
# Claude helper
# ---------------------------------------------------------------------------

def _get_claude(model: str | None = None) -> ChatAnthropic:
    if not config.ANTHROPIC_API_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY not set in .env")
    return ChatAnthropic(
        model=model or config.CLAUDE_HAIKU_MODEL,   # haiku — fast + cheap
        api_key=config.ANTHROPIC_API_KEY,
        temperature=0.2,
        max_tokens=2048,
    )


def generate_acceptance_criteria(
    raw_request: str,
    model: str | None = None,
    attachments: list[dict] | None = None,
    checklists: list[dict] | None = None,
) -> str:
    """
    Send a raw feature description to Claude and return the formatted
    User Story + Acceptance Criteria markdown.
    Includes links and checklists from the Trello card as extra context.
    """
    extra_context = ""

    if attachments:
        links = "\n".join(
            f"- {a['name']}: {a['url']}" if a.get("name") else f"- {a['url']}"
            for a in attachments if a.get("url")
        )
        if links:
            extra_context += f"\n\n## Linked References\n{links}"

    if checklists:
        for cl in checklists:
            items = "\n".join(
                f"  - [{'x' if i['state'] == 'complete' else ' '}] {i['name']}"
                for i in cl.get("items", [])
            )
            extra_context += f"\n\n## Checklist: {cl['name']}\n{items}"

    claude = _get_claude(model)
    prompt = AC_WRITER_PROMPT.format(raw_request=raw_request.strip() + extra_context)
    response = claude.invoke([HumanMessage(content=prompt)])
    return response.content.strip()


# ---------------------------------------------------------------------------
# Pipeline step
# ---------------------------------------------------------------------------

def process_card(
    card: TrelloCard,
    trello: TrelloClient,
    move_to: str = "Ready for Dev",
    dry_run: bool = False,
) -> str:
    """
    Process a single Trello card:
    1. Generate AC from card name + existing description
    2. Write AC back to the card description
    3. Add '✅ AC Written' comment
    4. Move card to `move_to` list

    Returns the generated AC markdown.
    """
    raw = f"{card.name}\n\n{card.desc}".strip()
    logger.info("Processing card: %s", card.name)

    ac_markdown = generate_acceptance_criteria(raw)
    logger.info("AC generated (%d chars)", len(ac_markdown))

    if dry_run:
        logger.info("[DRY RUN] Would update card %s", card.id)
        return ac_markdown

    # Write back to card
    trello.update_card_description(card.id, ac_markdown)
    trello.add_comment(
        card.id,
        "🤖 **Card Processor** — Acceptance criteria generated by Claude. "
        "Please review before moving to development."
    )

    # Move to next list
    try:
        trello.move_card_to_list(card.id, move_to)
        logger.info("Moved card to '%s'", move_to)
    except ValueError as e:
        logger.warning("Could not move card: %s", e)

    return ac_markdown


def process_backlog(
    list_name: str = "Iteration Backlog",
    move_to: str = "Ready for Dev",
    dry_run: bool = False,
) -> list[dict]:
    """
    Process all cards in the backlog list.
    Returns list of {card_id, card_name, ac} dicts.
    """
    trello = TrelloClient()
    cards = trello.get_backlog_cards(list_name)
    if not cards:
        logger.warning("No cards found in '%s'", list_name)
        return []

    results = []
    for card in cards:
        try:
            ac = process_card(card, trello, move_to=move_to, dry_run=dry_run)
            results.append({"card_id": card.id, "card_name": card.name, "ac": ac})
        except Exception:
            logger.exception("Failed to process card %s", card.id)

    logger.info("Processed %d / %d cards", len(results), len(cards))
    return results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def generate_test_cases(card: TrelloCard, model: str | None = None) -> str:
    """
    Generate QA test cases for a Trello card.
    Returns formatted markdown test cases.
    """
    claude = _get_claude(model)
    prompt = TEST_CASE_PROMPT.format(
        card_name=card.name,
        card_desc=card.desc.strip() if card.desc else "No description provided.",
    )
    response = claude.invoke([HumanMessage(content=prompt)])
    return response.content.strip()


def regenerate_with_feedback(
    card: TrelloCard,
    previous_test_cases: str,
    feedback: str,
    model: str | None = None,
) -> str:
    """
    Regenerate test cases based on reviewer feedback.
    Returns updated markdown test cases.
    """
    claude = _get_claude(model)
    prompt = REGENERATE_PROMPT.format(
        card_name=card.name,
        card_desc=card.desc.strip() if card.desc else "No description provided.",
        previous_test_cases=previous_test_cases,
        feedback=feedback,
    )
    response = claude.invoke([HumanMessage(content=prompt)])
    return response.content.strip()


def format_qa_comment(card_name: str, test_cases_markdown: str, release: str = "") -> str:
    """
    Format a concise QA note for the Trello card comment.
    Groups all test cases (Positive + Negative + Edge) as 1-liners.

    Example output:
        📋 QA Test Cases — Dry Ice (FedExapp 2.3.115)

        ✅ Positive
        • TC-1: Enable Dry Ice — rate shows surcharge at checkout
        • TC-2: Valid dry ice weight (2 kg) — accepted and saved

        ❌ Negative
        • TC-3: Dry ice weight = 0 — error message displayed
        • TC-4: Dry ice on FedEx Ground — not supported warning shown

        ⚠️ Edge
        • TC-5: Dry ice weight at max 2500 lbs — accepted at boundary
    """
    import re as _re

    blocks = _re.split(r"(?=###\s+TC-\d+)", test_cases_markdown)
    groups: dict[str, list[str]] = {"Positive": [], "Negative": [], "Edge": []}

    for block in blocks:
        block = block.strip()
        if not block or not _re.match(r"###\s+TC-\d+", block):
            continue

        # Extract TC number + title
        title_match = _re.match(r"###\s+(TC-\d+):\s*(.+)", block)
        tc_num = title_match.group(1) if title_match else "TC-?"
        tc_title = title_match.group(2).strip() if title_match else "Unknown"

        # Extract type
        type_match = _re.search(r"\*\*Type:\*\*\s*(Positive|Negative|Edge)", block, _re.IGNORECASE)
        tc_type = type_match.group(1).capitalize() if type_match else "Positive"

        # Extract first Then line as the short expected result
        then_match = _re.search(r"^Then (.+)$", block, _re.MULTILINE | _re.IGNORECASE)
        result = then_match.group(1).strip() if then_match else ""

        one_liner = f"• {tc_num}: {tc_title}"
        if result:
            one_liner += f" — {result}"

        if tc_type in groups:
            groups[tc_type].append(one_liner)
        else:
            groups["Positive"].append(one_liner)

    release_str = f" ({release})" if release else ""
    lines = [f"📋 **QA Test Cases — {card_name}{release_str}**\n"]

    icons = {"Positive": "✅ Positive", "Negative": "❌ Negative", "Edge": "⚠️ Edge"}
    for tc_type, icon_label in icons.items():
        if groups[tc_type]:
            lines.append(f"**{icon_label}**")
            lines.extend(groups[tc_type])
            lines.append("")

    total = sum(len(v) for v in groups.values())
    lines.append(f"_Total: {total} cases — "
                 f"{len(groups['Positive'])} positive · "
                 f"{len(groups['Negative'])} negative · "
                 f"{len(groups['Edge'])} edge_")

    return "\n".join(lines)


def write_test_cases_to_card(
    card_id: str,
    test_cases: str,
    trello: TrelloClient,
    release: str = "",
    card_name: str = "",
) -> None:
    """
    Write approved test cases to the Trello card.

    - Card description: unchanged (keeps User Story + Acceptance Criteria)
    - Card comment: concise QA note with 1-liner per case, grouped by type
    """
    # Concise QA note → card comment only; description keeps User Story + AC
    qa_comment = format_qa_comment(card_name or card_id, test_cases, release)
    trello.add_comment(card_id, qa_comment)

    logger.info("Test cases written as comment to card %s", card_id)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    parser = argparse.ArgumentParser(description="Generate acceptance criteria for Trello cards")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--card", metavar="CARD_ID", help="Process a single card by ID")
    group.add_argument("--list", metavar="LIST_NAME", default="Iteration Backlog",
                       help="Process all cards in a list (default: 'Iteration Backlog')")
    parser.add_argument("--move-to", default="Ready for Dev",
                        help="Move processed cards to this list (default: 'Ready for Dev')")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print AC without writing to Trello")
    args = parser.parse_args()

    if args.card:
        trello = TrelloClient()
        card = trello.get_card(args.card)
        ac = process_card(card, trello, move_to=args.move_to, dry_run=args.dry_run)
        print("\n" + "=" * 60)
        print(ac)
    else:
        results = process_backlog(
            list_name=args.list,
            move_to=args.move_to,
            dry_run=args.dry_run,
        )
        for r in results:
            print(f"\n{'=' * 60}")
            print(f"Card: {r['card_name']}")
            print(r["ac"])
