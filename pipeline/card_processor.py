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
from __future__ import annotations
import argparse
import json
import logging
import re
import sys
import threading
from urllib.parse import urlparse
from textwrap import dedent

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage

import config
from pipeline.trello_client import TrelloClient, TrelloCard

logger = logging.getLogger(__name__)


_DEFAULT_REVIEW_STATE: dict[str, object] = {
    "needs_revision": False,
    "issues": [],
    "rewrite_instructions": [],
}
_REVIEW_STATE = threading.local()


def _set_last_ac_review(data: dict[str, object]) -> None:
    _REVIEW_STATE.last_ac_review = dict(data)


def _set_last_tc_review(data: dict[str, object]) -> None:
    _REVIEW_STATE.last_tc_review = dict(data)


def _get_last_review(attr: str) -> dict[str, object]:
    current = getattr(_REVIEW_STATE, attr, None)
    if not current:
        return dict(_DEFAULT_REVIEW_STATE)
    return dict(current)

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
    - When source code context is provided, write TCs that match the actual implementation
      (real field names, real API error codes, real validation rules from the code)
    - When dev comments are provided, incorporate any additional info or constraints mentioned
    - When past QA feedback is provided, pay special attention to gaps/issues previously
      flagged and make sure they are covered this time
    - NEVER generate test cases for mobile viewports, responsive layouts, or screen width
      breakpoints (e.g. isMobileView, ≤480px, ≤768px). We test WEB (desktop browser) ONLY.
      If the source code references mobile breakpoints, ignore them — do not write TCs for them.

    ---
    Feature Card: {card_name}

    Card Description / Acceptance Criteria:
    {card_desc}
    {dev_comments_section}
    {rag_context_section}
    {code_context_section}
    {feedback_context_section}
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

TEST_CASE_REVIEW_PROMPT = dedent("""\
    You are reviewing generated QA test cases for the FedEx Shopify App.

    Return ONLY JSON in this exact shape:
    {{
      "needs_revision": true | false,
      "issues": [
        "<short issue>"
      ],
      "rewrite_instructions": [
        "<short concrete instruction for the rewrite>"
      ]
    }}

    Review for:
    - missing Positive / Negative / Edge coverage
    - fewer than 4 test cases
    - invalid format vs the required TC template
    - vague or untestable steps / expected results
    - missing prerequisites
    - duplicate or overlapping test cases
    - missing coverage for important AC scenarios
    - mobile / responsive / viewport coverage that should not exist

    Feature Card: {card_name}

    Card Description / Acceptance Criteria:
    {card_desc}

    Generated test cases:
    {test_cases_markdown}
""")

TEST_CASE_REWRITE_PROMPT = dedent("""\
    Revise the QA test cases below using the review findings.

    Rules:
    - Keep the exact TC format:
      `### TC-{{n}}`, `**Type:**`, `**Priority:**`, `**Preconditions:**`, `**Steps:**`
    - Ensure a good mix of Positive / Negative / Edge cases
    - Keep steps testable and explicit
    - Remove duplicates
    - Do not add mobile / responsive / viewport tests

    Feature Card: {card_name}

    Card Description / Acceptance Criteria:
    {card_desc}

    Review findings:
    {review_summary}

    Current test cases:
    {test_cases_markdown}

    Return ONLY the revised test cases markdown.
""")

AC_WRITER_PROMPT = dedent("""\
    You are a senior QA engineer and product owner for the FedEx Shopify App
    built by PluginHive. Your job is to turn raw feature requests into
    well-structured Agile cards.

    Work research-first, not card-text-first.
    Before writing the final card, ground yourself in the structured brief below:
    - card type
    - linked references
    - customer issue / Zendesk signals
    - toggle / feature-flag prerequisites
    - known prerequisites and risks
    - research source priority

    Given the raw feature request below, produce:

    ## User Story
    As a [type of user], I want [goal], so that [benefit].

    ## Domain Rules / FedEx Constraints
    Summarize concrete FedEx, PluginHive, Shopify, API, carrier, or app limitations
    that developers and QA must know before implementation. Include prerequisites,
    unsupported cases, max/min limits, required fields, special service rules, and
    carrier behaviour when supported by the research context. Treat official FedEx
    docs/API findings as authoritative for carrier limits; use PluginHive findings
    for app behaviour. If a limit is unclear, explicitly mark it as an open
    question instead of inventing it.

    ## Acceptance Criteria
    List each scenario in Given / When / Then format.
    Cover: happy path, edge cases, error states, and FedEx/PluginHive limitation cases
    discovered from research.
    If this is a bug / customer issue card, include:
    - the broken behaviour the customer is facing
    - the corrected behaviour after the fix
    - at least one regression scenario to prove older working behaviour is preserved
    If a toggle / feature flag is required, include it as a prerequisite and do not
    assume it is already enabled.
    If a scenario depends on a specific order state, product setup, store state, or
    settings/toggle configuration, state that explicitly in the Given steps.

    ## Priority
    High / Medium / Low — justify in one sentence.

    ## Scenario Source Attribution
    For each AC scenario, add a short source line in this format:
    - Scenario 1 → Card request; Zendesk/wiki; Related Backlog Card; FedEx docs; PluginHive/app behaviour
    Use only the sources that actually support that scenario.
    If a scenario is mainly inferred from the raw card and not explicitly backed by research,
    say so clearly instead of pretending there is a stronger source.

    ## Test Scope
    List the app sections and automation files that will need coverage.
    Reference existing test areas: Single Label, Rate Domestic/International,
    Label Domestic/International, Orders Grid, Settings, Pickup,
    Return Labels, Notifications, Print Settings, Locations, Bulk Orders.

    ## Out of Scope
    What this story explicitly does NOT cover.
    Always include: Mobile / responsive / viewport testing (we test web/desktop only).
    Never write ACs for mobile viewports, screen-width breakpoints, or isMobileView behaviour.

    ## References
    Extract and list ALL URLs and links found anywhere in the raw feature request below
    AND any useful FedEx/PluginHive references from the research context.
    Include PR links, ticket links, BitBucket/GitLab/GitHub links, Zendesk links, changelogs, or any other URLs.
    Format each as: - [label or URL](URL)
    If no links are found, omit this section entirely.

    ## Structured Research Brief
    {generation_brief}

    ## Research Context
    {research_context}

    ---
    Raw feature request:
    {raw_request}
    ---

    Respond with clean markdown. No preamble.
""")

AC_REVIEW_PROMPT = dedent("""\
    You are reviewing generated Acceptance Criteria for the FedEx Shopify App.

    Check the draft against the structured brief and research context.

    Return ONLY JSON in this exact shape:
    {{
      "needs_revision": true | false,
      "issues": [
        "<short issue>"
      ],
      "rewrite_instructions": [
        "<short concrete instruction for the rewrite>"
      ]
    }}

    Review for:
    - duplicate or overlapping scenarios
    - vague expected results that are not testable
    - missing prerequisites or setup assumptions
    - unsupported claims not grounded in the brief or research
    - missing customer-impact/regression coverage for bug or Zendesk-driven cards
    - missing toggle prerequisites when a toggle/feature flag is involved
    - missing or weak scenario source attribution

    Structured brief:
    {generation_brief}

    Research context:
    {research_context}

    Generated AC draft:
    {ac_markdown}
""")

AC_REWRITE_PROMPT = dedent("""\
    Revise the Acceptance Criteria markdown below using the review findings.

    Rules:
    - Keep the same overall markdown structure and sections.
    - Remove duplicates and merge overlaps.
    - Make expected outcomes explicit and testable.
    - Add missing prerequisites in Given steps or Domain Rules.
    - Do not invent unsupported carrier/app rules.
    - Preserve useful references already present.
    - Keep or add the Scenario Source Attribution section and make it specific.

    Structured brief:
    {generation_brief}

    Research context:
    {research_context}

    Review findings:
    {review_summary}

    Current AC markdown:
    {ac_markdown}

    Return ONLY the revised markdown.
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


def _extract_urls(text: str) -> list[str]:
    if not text:
        return []
    seen: set[str] = set()
    urls: list[str] = []
    for match in re.finditer(r"https?://[^\s)>]+", text):
        url = match.group(0).rstrip(".,)")
        if url not in seen:
            seen.add(url)
            urls.append(url)
    return urls


def _friendly_ref(url: str) -> str:
    host = urlparse(url).netloc.lower().replace("www.", "")
    if "zendesk" in host:
        return "Zendesk"
    if "bitbucket" in host:
        return "Bitbucket"
    if "github" in host:
        return "GitHub"
    if "gitlab" in host:
        return "GitLab"
    if "pluginhive" in host:
        return "PluginHive"
    if "fedex" in host:
        return "FedEx"
    return host or "reference"


def _classify_card_type(raw_request: str, research_context: str) -> str:
    text = f"{raw_request}\n{research_context}".lower()
    if any(k in text for k in ("zendesk", "customer issue", "customer facing", "merchant facing", "bug", "fix", "regression")):
        return "bug_fix_or_customer_issue"
    if any(k in text for k in ("toggle", "feature flag", "turn on", "enable on store", "rollout")):
        return "toggle_or_rollout_change"
    if any(k in text for k in ("packaging", "fedex small box", "fedex medium box", "fedex large box", "tube", "pak", "envelope")):
        return "packaging_or_carrier_rules"
    if any(k in text for k in ("rate", "checkout", "transit", "service availability")):
        return "rates_or_checkout_behaviour"
    if any(k in text for k in ("settings", "save", "configuration", "preference")):
        return "settings_or_configuration_change"
    return "new_feature_or_general_change"


def _extract_prerequisites(raw_request: str, research_context: str, checklists: list[dict]) -> list[str]:
    text = f"{raw_request}\n{research_context}"
    prerequisites: list[str] = []

    try:
        from pipeline.slack_client import detect_toggles
        toggles = detect_toggles(raw_request, "")
    except Exception:
        toggles = []

    if toggles:
        prerequisites.append(
            "Feature toggle(s) may need store enablement before QA: " + ", ".join(toggles)
        )

    lower = text.lower()
    if "zendesk" in lower:
        prerequisites.append("Review the linked Zendesk/customer issue and preserve the real customer-facing fix path.")
    if any(k in lower for k in ("manual label", "generate label", "label generation")):
        prerequisites.append("A valid REST store and label-generation-capable order/setup are required.")
    if "return label" in lower:
        prerequisites.append("Requires an existing labeled / fulfilled order state suitable for return-label testing.")
    if "pickup" in lower:
        prerequisites.append("Requires a labeled shipment/order before pickup verification.")
    if any(k in lower for k in ("toggle", "feature flag")):
        prerequisites.append("Do not assume toggles are already enabled unless the card/research says so.")
    if any(k in lower for k in ("packing method", "packaging", "fedex box", "custom box")):
        prerequisites.append("Packaging scenarios require explicit packaging method, box selection, and product dimensions/weight.")

    for checklist in checklists[:3]:
        name = (checklist.get("name") or "").strip()
        items = [i.get("name", "").strip() for i in checklist.get("items", []) if i.get("name")]
        if name or items:
            preview = ", ".join(items[:3])
            prerequisites.append(f"Checklist context '{name}': {preview}".strip(": "))

    deduped: list[str] = []
    seen: set[str] = set()
    for item in prerequisites:
        norm = item.lower()
        if item and norm not in seen:
            seen.add(norm)
            deduped.append(item)
    return deduped[:8]


def _build_generation_brief(
    raw_request: str,
    attachments: list[dict],
    checklists: list[dict],
    research_context: str,
    feedback_context: str,
) -> str:
    urls: list[str] = []
    seen_urls: set[str] = set()
    for url in _extract_urls(raw_request + "\n" + research_context):
        if url not in seen_urls:
            seen_urls.add(url)
            urls.append(url)
    for attachment in attachments:
        url = (attachment.get("url") or "").strip()
        if url and url not in seen_urls:
            seen_urls.add(url)
            urls.append(url)

    card_type = _classify_card_type(raw_request, research_context)
    prerequisites = _extract_prerequisites(raw_request, research_context, checklists)

    try:
        from pipeline.slack_client import detect_toggles
        toggles = detect_toggles(raw_request, "")
    except Exception:
        toggles = []

    backlog_matches: list[tuple[str, str]] = []
    for match in re.finditer(
        r"- \[(?P<list_name>[^\]]+)\] (?P<card_name>.+?)\n\s+URL:\s+(?P<url>https?://\S+)",
        research_context,
        re.MULTILINE,
    ):
        list_name = (match.group("list_name") or "").strip()
        if list_name.lower() != "backlog":
            continue
        backlog_matches.append(
            (
                (match.group("card_name") or "").strip(),
                (match.group("url") or "").strip(),
            )
        )

    lines = [
        "Research priority:",
        "1. Raw card + linked references define the requested change.",
        "2. Research context provides official FedEx, PluginHive, and app behaviour facts.",
        "3. Past QA feedback highlights prior mistakes/gaps; use it only when relevant.",
        "",
        f"Card type: {card_type}",
    ]

    if toggles:
        lines.append("Detected toggles / feature flags: " + ", ".join(toggles))

    if "zendesk" in raw_request.lower() or "zendesk" in research_context.lower():
        lines.append("Customer issue signal: Zendesk/customer-support reference detected. Treat this as real broken behaviour, not only a net-new feature.")

    if backlog_matches:
        lines.append("")
        lines.append("Related Backlog Card Found:")
        for card_name, url in backlog_matches[:4]:
            lines.append(f"- Card: {card_name}")
            lines.append(f"  URL: {url}")
        lines.append(
            "- Treat this as an existing tracked issue and decide whether the current card looks like a duplicate, follow-up fix, or regression of the older issue."
        )

    if prerequisites:
        lines.append("")
        lines.append("Likely prerequisites:")
        lines.extend(f"- {item}" for item in prerequisites)

    if urls:
        lines.append("")
        lines.append("Linked references already detected:")
        lines.extend(f"- [{_friendly_ref(url)}] {url}" for url in urls[:12])

    if feedback_context.strip():
        lines.append("")
        lines.append("Past QA feedback is available and should be used to avoid repeating missed scenarios or weak expected results.")

    return "\n".join(lines)


def _review_and_rewrite_ac(
    ac_markdown: str,
    generation_brief: str,
    research_context: str,
    model: str | None = None,
) -> str:
    _set_last_ac_review(_DEFAULT_REVIEW_STATE)
    claude = _get_claude(model)
    review_prompt = AC_REVIEW_PROMPT.format(
        generation_brief=generation_brief,
        research_context=research_context or "No additional research context available.",
        ac_markdown=ac_markdown,
    )
    try:
        review_resp = claude.invoke([HumanMessage(content=review_prompt)])
        review_raw = review_resp.content.strip()
        review_data = json.loads(re.sub(r"```(?:json)?", "", review_raw).strip())
    except Exception as exc:
        logger.debug("AC review pass skipped: %s", exc)
        return ac_markdown

    _set_last_ac_review({
        "needs_revision": bool(review_data.get("needs_revision")),
        "issues": review_data.get("issues", []) or [],
        "rewrite_instructions": review_data.get("rewrite_instructions", []) or [],
    })

    if not review_data.get("needs_revision"):
        return ac_markdown

    issues = review_data.get("issues", []) or []
    rewrite_instructions = review_data.get("rewrite_instructions", []) or []
    review_summary = "\n".join(
        [f"- Issue: {item}" for item in issues[:8]] +
        [f"- Fix: {item}" for item in rewrite_instructions[:8]]
    ).strip()
    if not review_summary:
        return ac_markdown

    logger.info("AC review requested revision with %d issue(s)", len(issues))
    rewrite_prompt = AC_REWRITE_PROMPT.format(
        generation_brief=generation_brief,
        research_context=research_context or "No additional research context available.",
        review_summary=review_summary,
        ac_markdown=ac_markdown,
    )
    try:
        rewrite_resp = claude.invoke([HumanMessage(content=rewrite_prompt)])
        revised = rewrite_resp.content.strip()
        return revised or ac_markdown
    except Exception as exc:
        logger.debug("AC rewrite pass skipped: %s", exc)
        return ac_markdown


def get_last_ac_review() -> dict[str, object]:
    return _get_last_review("last_ac_review")


def _review_and_rewrite_test_cases(
    card_name: str,
    card_desc: str,
    test_cases_markdown: str,
    model: str | None = None,
) -> str:
    _set_last_tc_review(_DEFAULT_REVIEW_STATE)

    claude = _get_claude(model)
    review_prompt = TEST_CASE_REVIEW_PROMPT.format(
        card_name=card_name,
        card_desc=card_desc,
        test_cases_markdown=test_cases_markdown,
    )
    try:
        review_resp = claude.invoke([HumanMessage(content=review_prompt)])
        review_raw = review_resp.content.strip()
        review_data = json.loads(re.sub(r"```(?:json)?", "", review_raw).strip())
    except Exception as exc:
        logger.debug("TC review pass skipped: %s", exc)
        return test_cases_markdown

    _set_last_tc_review({
        "needs_revision": bool(review_data.get("needs_revision")),
        "issues": review_data.get("issues", []) or [],
        "rewrite_instructions": review_data.get("rewrite_instructions", []) or [],
    })

    if not review_data.get("needs_revision"):
        return test_cases_markdown

    issues = review_data.get("issues", []) or []
    rewrite_instructions = review_data.get("rewrite_instructions", []) or []
    review_summary = "\n".join(
        [f"- Issue: {item}" for item in issues[:8]]
        + [f"- Fix: {item}" for item in rewrite_instructions[:8]]
    ).strip()
    if not review_summary:
        return test_cases_markdown

    logger.info("TC review requested revision with %d issue(s)", len(issues))
    rewrite_prompt = TEST_CASE_REWRITE_PROMPT.format(
        card_name=card_name,
        card_desc=card_desc,
        review_summary=review_summary,
        test_cases_markdown=test_cases_markdown,
    )
    try:
        rewrite_resp = claude.invoke([HumanMessage(content=rewrite_prompt)])
        revised = rewrite_resp.content.strip()
        return revised or test_cases_markdown
    except Exception as exc:
        logger.debug("TC rewrite pass skipped: %s", exc)
        return test_cases_markdown


def get_last_tc_review() -> dict[str, object]:
    return _get_last_review("last_tc_review")


def generate_acceptance_criteria(
    raw_request: str,
    model: str | None = None,
    attachments: list[dict] | None = None,
    checklists: list[dict] | None = None,
    research_context: str | None = None,
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

    # Inject past QA feedback so AC generation learns from prior retrospectives
    try:
        from pipeline.qa_feedback import build_feedback_context
        feedback_ctx = build_feedback_context(raw_request[:400])
        if feedback_ctx:
            extra_context += feedback_ctx
            logger.info("AC generation: injecting %d chars of past QA feedback", len(feedback_ctx))
    except Exception as _fe:
        logger.debug("Feedback context fetch skipped (non-fatal): %s", _fe)

    if research_context is None:
        try:
            from pipeline.requirement_research import build_requirement_research_context
            research_context = build_requirement_research_context(raw_request)
            if research_context:
                logger.info("AC generation: injecting requirement research context")
        except Exception as _re:
            logger.debug("Requirement research context fetch skipped (non-fatal): %s", _re)
            research_context = "No additional FedEx/PluginHive research findings available."

    generation_brief = _build_generation_brief(
        raw_request=raw_request,
        attachments=attachments or [],
        checklists=checklists or [],
        research_context=research_context or "",
        feedback_context=extra_context,
    )

    claude = _get_claude(model)
    prompt = AC_WRITER_PROMPT.format(
        raw_request=raw_request.strip() + extra_context,
        research_context=research_context,
        generation_brief=generation_brief,
    )
    response = claude.invoke([HumanMessage(content=prompt)])
    ac_markdown = response.content.strip()
    return _review_and_rewrite_ac(
        ac_markdown=ac_markdown,
        generation_brief=generation_brief,
        research_context=research_context,
        model=model,
    )


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

def _build_dev_comments_section(comments: list[str]) -> str:
    """Format Trello card comments (dev notes) for the TC prompt."""
    if not comments:
        return ""
    filtered = [c.strip() for c in comments if c.strip()]
    if not filtered:
        return ""
    lines = "\n".join(f"- {c}" for c in filtered)
    return f"\nDev / QA Comments from Trello:\n{lines}\n"


def _build_rag_context_section(card_name: str, card_desc: str) -> str:
    """Query the QA knowledge base for similar past test cases."""
    try:
        from rag.vectorstore import search
        query = f"{card_name} {card_desc or ''}".strip()[:500]
        docs = search(query, k=5)
        # Prefer test_cases doc_type, then fallback to all types
        tc_docs = [d for d in docs if d.metadata.get("doc_type") == "test_cases"]
        use_docs = tc_docs if tc_docs else docs
        if not use_docs:
            return ""
        snippets = []
        for d in use_docs[:3]:
            source = d.metadata.get("card_name", "")
            snippets.append(f"[From: {source}]\n{d.page_content[:600]}")
        context = "\n\n---\n".join(snippets)
        return f"\nSimilar past test cases from QA knowledge base (use as style/coverage reference):\n{context}\n"
    except Exception as e:
        logger.debug("RAG context fetch failed (non-fatal): %s", e)
        return ""


def _build_code_context_section(card_name: str, card_desc: str) -> str:
    """
    Query source code RAG for relevant context — in priority order:
      1. Automation code  — existing spec files and POMs (shows what's already testable)
      2. Backend code     — services, validators, API controllers (real business logic)
      3. Frontend code    — UI components (if indexed)
    """
    try:
        from rag.code_indexer import search_code, get_index_stats
        stats = get_index_stats()
        if stats.get("total", 0) == 0:
            return ""   # nothing indexed yet — skip silently

        query = f"{card_name} {card_desc or ''}".strip()[:500]

        sections: list[str] = []

        # 1. Automation — existing test patterns (most useful for TC writing)
        if stats.get("automation", 0) > 0:
            auto_docs = search_code(query, k=4, source_type="automation")
            if auto_docs:
                lines = []
                seen: set[str] = set()
                for d in auto_docs:
                    fp = d.metadata.get("file_path", "")
                    if fp not in seen:
                        seen.add(fp)
                        lines.append(f"[automation/{fp}]\n```typescript\n{d.page_content[:600]}\n```")
                if lines:
                    sections.append(
                        "Existing automation test patterns (follow these — "
                        "don't duplicate what's already covered):\n"
                        + "\n\n".join(lines[:3])
                    )

        # 2. Backend — real business logic, validations, error codes
        if stats.get("backend", 0) > 0:
            be_docs = search_code(query, k=4, source_type="backend")
            if be_docs:
                lines = []
                seen: set[str] = set()
                for d in be_docs:
                    fp = d.metadata.get("file_path", "")
                    lang = d.metadata.get("language", "")
                    if fp not in seen:
                        seen.add(fp)
                        lines.append(f"[backend/{fp}]\n```{lang}\n{d.page_content[:600]}\n```")
                if lines:
                    sections.append(
                        "Backend implementation (real field names, validations, error handling):\n"
                        + "\n\n".join(lines[:3])
                    )

        # 3. Frontend — UI component names, labels, navigation
        if stats.get("frontend", 0) > 0:
            fe_docs = search_code(query, k=3, source_type="frontend")
            if fe_docs:
                lines = []
                seen: set[str] = set()
                for d in fe_docs:
                    fp = d.metadata.get("file_path", "")
                    lang = d.metadata.get("language", "")
                    if fp not in seen:
                        seen.add(fp)
                        lines.append(f"[frontend/{fp}]\n```{lang}\n{d.page_content[:500]}\n```")
                if lines:
                    sections.append(
                        "Frontend implementation (UI labels, components, navigation):\n"
                        + "\n\n".join(lines[:2])
                    )

        if not sections:
            return ""

        return "\nSource code context:\n" + "\n\n---\n".join(sections) + "\n"

    except Exception as e:
        logger.debug("Code context fetch failed (non-fatal): %s", e)
        return ""


def generate_test_cases(card: TrelloCard, model: str | None = None) -> str:
    """
    Generate QA test cases for a Trello card using all available context:
      1. Card name + description / AC
      2. Dev comments from Trello (dev notes added by the team)
      3. Similar past TCs from the QA RAG knowledge base
      4. Relevant source code from the backend/frontend code knowledge base

    Returns formatted markdown test cases.
    """
    card_desc    = card.desc.strip() if card.desc else "No description provided."
    dev_comments = _build_dev_comments_section(card.comments or [])
    rag_context  = _build_rag_context_section(card.name, card_desc)
    code_context = _build_code_context_section(card.name, card_desc)

    # Pull past QA retrospective lessons so TC generation avoids known gaps
    feedback_ctx = ""
    try:
        from pipeline.qa_feedback import build_feedback_context
        feedback_ctx = build_feedback_context(f"{card.name} {card_desc[:300]}")
    except Exception as _fe:
        logger.debug("Feedback context fetch skipped (non-fatal): %s", _fe)

    # Log what context we're using
    ctx_parts = []
    if dev_comments:  ctx_parts.append(f"{len(card.comments or [])} dev comment(s)")
    if rag_context:   ctx_parts.append("RAG past TCs")
    if code_context:  ctx_parts.append("source code")
    if feedback_ctx:  ctx_parts.append("QA feedback learnings")
    logger.info(
        "Generating TCs for '%s' — context: %s",
        card.name,
        ", ".join(ctx_parts) if ctx_parts else "card desc only",
    )

    claude = _get_claude(model)
    prompt = TEST_CASE_PROMPT.format(
        card_name=card.name,
        card_desc=card_desc,
        dev_comments_section=dev_comments,
        rag_context_section=rag_context,
        code_context_section=code_context,
        feedback_context_section=feedback_ctx,
    )
    response = claude.invoke([HumanMessage(content=prompt)])
    test_cases = response.content.strip()
    return _review_and_rewrite_test_cases(
        card_name=card.name,
        card_desc=card_desc,
        test_cases_markdown=test_cases,
        model=model,
    )


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
    test_cases = response.content.strip()
    return _review_and_rewrite_test_cases(
        card_name=card.name,
        card_desc=card.desc.strip() if card.desc else "No description provided.",
        test_cases_markdown=test_cases,
        model=model,
    )


def format_qa_comment(
    card_name: str,
    test_cases_markdown: str,
    release: str = "",
    qa_name: str = "",
) -> str:
    """
    Format a concise QA note for the Trello card comment.
    Groups all test cases (Positive + Negative + Edge) as 1-liners.
    Prefixes the comment with the QA member's name so it reads as their work.

    Example output:
        📋 QA Test Cases — Dry Ice (FedExapp 2.3.115)
        _Prepared by: Anuja B_

        ✅ Positive
        • TC-1: Enable Dry Ice — rate shows surcharge at checkout
        ...
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
    lines = [f"📋 **QA Test Cases — {card_name}{release_str}**"]

    # Credit the actual QA who prepared this — not the API token owner
    if qa_name:
        lines.append(f"_Prepared by: {qa_name}_")

    lines.append("")

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


def _get_qa_member_name(card_id: str, trello: TrelloClient) -> str:
    """
    Return the name of the QA member assigned to this card.
    Falls back to empty string if none found.
    """
    from pipeline.bug_reporter import _is_qa  # reuse QA name list
    try:
        members = trello.get_card_members(card_id)
        for m in members:
            if _is_qa(m.get("fullName", "")):
                return m["fullName"]
    except Exception:
        pass
    return ""


def write_test_cases_to_card(
    card_id: str,
    test_cases: str,
    trello: TrelloClient,
    release: str = "",
    card_name: str = "",
) -> None:
    """
    Write approved test cases to the Trello card as a comment.

    The comment is attributed to the QA member assigned to the card
    (prefixed in the comment body) rather than the API token owner.

    - Card description: unchanged (keeps User Story + Acceptance Criteria)
    - Card comment: concise QA note with 1-liner per case, grouped by type
    """
    qa_name = _get_qa_member_name(card_id, trello)
    qa_comment = format_qa_comment(
        card_name or card_id,
        test_cases,
        release,
        qa_name=qa_name,
    )
    trello.add_comment(card_id, qa_comment)
    logger.info(
        "Test cases written as comment to card %s (QA: %s)",
        card_id, qa_name or "unknown",
    )


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
