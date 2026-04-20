"""
Domain Validator  —  Pipeline Step 1.5
=======================================
Uses the RAG knowledge base (ChromaDB + nomic-embed-text) to validate
a Trello card's description and acceptance criteria BEFORE test cases
are generated.

Checks:
  1. Requirement gaps   — known behaviors missing from the card description
  2. AC gaps            — acceptance criteria scenarios not covered
  3. Accuracy issues    — anything contradicting actual FedEx app behaviour
  4. FedEx-specific     — API constraints, edge cases, app quirks
  5. Suggestions        — improvements to the card wording or scope

Returns a ValidationReport dataclass shown in the dashboard UI.
"""
from __future__ import annotations
import json
import logging
import re
from dataclasses import dataclass, field
from textwrap import dedent

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage

import config
from rag.vectorstore import search

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

VALIDATION_PROMPT = dedent("""\
    You are a senior domain expert and QA lead for the FedEx Shopify App built by PluginHive.

    A new Trello card has come in. Your job is to validate the card's requirements and
    acceptance criteria against the knowledge base before test cases are generated.

    Knowledge base context (retrieved for this feature):
    {context}

    Requirement research context:
    {research_context}

    ---
    Card Name: {card_name}

    Card Description / Requirements:
    {card_desc}

    Acceptance Criteria (if already written):
    {acceptance_criteria}
    ---

    Analyse carefully and respond in this EXACT JSON format (no extra text, no markdown fences):
    {{
      "overall_status": "PASS" | "NEEDS_REVIEW" | "FAIL",
      "summary": "<one sentence — what this card is about and your overall verdict>",
      "requirement_gaps": [
        "<requirement or behaviour known from the KB that is missing from the card>"
      ],
      "ac_gaps": [
        "<acceptance criteria scenario not covered — e.g. error state, edge case, boundary>"
      ],
      "accuracy_issues": [
        "<anything in the description that contradicts how the FedEx app actually works>"
      ],
      "suggestions": [
        "<improvement to wording, scope, or test coverage>"
      ],
      "rewrite_instructions": [
        "<direct instruction for how to fix the AC>"
      ],
      "kb_insights": "<what the knowledge base tells us about this feature — key facts, constraints, known behaviours>"
    }}

    Rules:
    - overall_status = PASS if no significant gaps or issues
    - overall_status = NEEDS_REVIEW if minor gaps or suggestions only
    - overall_status = FAIL if accuracy issues or critical missing requirements
    - Keep each item concise (1–2 sentences max)
    - If a list has nothing to report, return an empty array []
    - Explicitly check for missing prerequisites, missing regression/customer-impact scenarios,
      missing toggle/setup dependencies, duplicate scenarios, and weak source attribution
    - Only reference what is in the knowledge base or research context above — do not invent
""")

VALIDATION_REWRITE_PROMPT = dedent("""\
    You are fixing Acceptance Criteria for the FedEx Shopify App based on domain validation feedback.

    Keep the existing markdown structure where possible, but improve the AC so it is:
    - accurate
    - testable
    - explicit about prerequisites
    - aligned with the research context

    Card Name:
    {card_name}

    Research context:
    {research_context}

    Existing AC markdown:
    {acceptance_criteria}

    Validation findings:
    Summary: {summary}

    Requirement gaps:
    {requirement_gaps}

    AC gaps:
    {ac_gaps}

    Accuracy issues:
    {accuracy_issues}

    Suggestions:
    {suggestions}

    Rewrite instructions:
    {rewrite_instructions}

    Return ONLY the revised AC markdown.
""")


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class ValidationReport:
    overall_status: str                  # "PASS" | "NEEDS_REVIEW" | "FAIL"
    summary: str
    requirement_gaps: list[str] = field(default_factory=list)
    ac_gaps: list[str] = field(default_factory=list)
    accuracy_issues: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    rewrite_instructions: list[str] = field(default_factory=list)
    kb_insights: str = ""
    sources: list[str] = field(default_factory=list)
    error: str = ""                      # set if validation itself failed


# ---------------------------------------------------------------------------
# Validator
# ---------------------------------------------------------------------------

def validate_card(
    card_name: str,
    card_desc: str,
    acceptance_criteria: str = "",
    research_context: str = "",
) -> ValidationReport:
    """
    Validate a Trello card against the knowledge base.

    Args:
        card_name:           Title of the Trello card
        card_desc:           Full description / requirements on the card
        acceptance_criteria: AC already written (may be empty for new cards)

    Returns:
        ValidationReport dataclass
    """
    if not config.ANTHROPIC_API_KEY:
        return ValidationReport(
            overall_status="NEEDS_REVIEW",
            summary="Validation skipped — ANTHROPIC_API_KEY not set.",
            error="ANTHROPIC_API_KEY not set",
        )

    # ── Step 1: Retrieve relevant context from RAG knowledge base ────────────
    query = f"{card_name} {card_desc[:300]}"
    try:
        docs = search(query, k=config.TOP_K_RESULTS)
        context = "\n\n".join(
            f"[Source: {doc.metadata.get('source_url', doc.metadata.get('source', 'KB'))}]\n{doc.page_content}"
            for doc in docs
        )
        sources = list({
            doc.metadata.get("source_url", doc.metadata.get("source", "Unknown"))
            for doc in docs
        })
    except Exception as e:
        logger.warning("RAG search failed during validation: %s", e)
        context = "No context retrieved — knowledge base may not be indexed yet."
        sources = []

    # ── Step 2: Build prompt ─────────────────────────────────────────────────
    prompt = VALIDATION_PROMPT.format(
        context=context or "No relevant context found in knowledge base.",
        research_context=research_context.strip() or "No additional requirement research available.",
        card_name=card_name,
        card_desc=card_desc.strip() or "(No description provided)",
        acceptance_criteria=acceptance_criteria.strip() or "(Not yet written)",
    )

    # ── Step 3: Call Claude ──────────────────────────────────────────────────
    try:
        llm = ChatAnthropic(
            model=config.CLAUDE_HAIKU_MODEL,   # fast + cheap for validation
            api_key=config.ANTHROPIC_API_KEY,
            temperature=0.1,
            max_tokens=1500,
        )
        response = llm.invoke([HumanMessage(content=prompt)])
        raw = response.content.strip()
    except Exception as e:
        logger.error("Claude validation call failed: %s", e)
        return ValidationReport(
            overall_status="NEEDS_REVIEW",
            summary="Validation could not complete due to an API error.",
            error=str(e),
        )

    # ── Step 4: Parse JSON response ──────────────────────────────────────────
    try:
        # Strip any accidental markdown fences
        json_text = re.sub(r"```(?:json)?", "", raw).strip()
        data = json.loads(json_text)

        return ValidationReport(
            overall_status=data.get("overall_status", "NEEDS_REVIEW"),
            summary=data.get("summary", ""),
            requirement_gaps=data.get("requirement_gaps", []),
            ac_gaps=data.get("ac_gaps", []),
            accuracy_issues=data.get("accuracy_issues", []),
            suggestions=data.get("suggestions", []),
            rewrite_instructions=data.get("rewrite_instructions", []),
            kb_insights=data.get("kb_insights", ""),
            sources=sources,
        )

    except (json.JSONDecodeError, KeyError) as e:
        logger.warning("Failed to parse validation JSON: %s\nRaw: %s", e, raw[:300])
        # Graceful fallback — return raw summary
        return ValidationReport(
            overall_status="NEEDS_REVIEW",
            summary=raw[:300],
            error=f"JSON parse error: {e}",
        )


def apply_validation_fixes(
    card_name: str,
    acceptance_criteria: str,
    report: ValidationReport,
    research_context: str = "",
) -> str:
    if not acceptance_criteria.strip():
        return acceptance_criteria
    if not config.ANTHROPIC_API_KEY:
        return acceptance_criteria

    llm = ChatAnthropic(
        model=config.CLAUDE_HAIKU_MODEL,
        api_key=config.ANTHROPIC_API_KEY,
        temperature=0.1,
        max_tokens=2200,
    )
    prompt = VALIDATION_REWRITE_PROMPT.format(
        card_name=card_name,
        research_context=research_context.strip() or "No additional requirement research available.",
        acceptance_criteria=acceptance_criteria.strip(),
        summary=report.summary or "",
        requirement_gaps="\n".join(f"- {x}" for x in report.requirement_gaps) or "- None",
        ac_gaps="\n".join(f"- {x}" for x in report.ac_gaps) or "- None",
        accuracy_issues="\n".join(f"- {x}" for x in report.accuracy_issues) or "- None",
        suggestions="\n".join(f"- {x}" for x in report.suggestions) or "- None",
        rewrite_instructions="\n".join(f"- {x}" for x in report.rewrite_instructions) or "- None",
    )
    try:
        response = llm.invoke([HumanMessage(content=prompt)])
        revised = response.content.strip()
        return revised or acceptance_criteria
    except Exception as exc:
        logger.warning("Validation rewrite failed: %s", exc)
        return acceptance_criteria
