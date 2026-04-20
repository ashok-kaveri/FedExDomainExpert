from __future__ import annotations

import datetime as _dt
import io
import logging
import re
from dataclasses import dataclass, field

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage

import config
from pipeline.bug_reporter import _is_qa
from pipeline.slack_client import detect_toggles

logger = logging.getLogger(__name__)


@dataclass
class HandoffDocContext:
    card_id: str
    card_name: str
    card_url: str = ""
    release_name: str = ""
    approved_at: str = ""
    card_description: str = ""
    acceptance_criteria: str = ""
    test_cases: str = ""
    ai_qa_summary: str = ""
    ai_qa_evidence: str = ""
    signoff_summary: str = ""
    developer_names: list[str] = field(default_factory=list)
    tester_names: list[str] = field(default_factory=list)
    toggle_names: list[str] = field(default_factory=list)
    generated_on: str = field(default_factory=lambda: _dt.datetime.now().strftime("%Y-%m-%d %H:%M"))


def split_card_members(members: list[dict]) -> tuple[list[str], list[str]]:
    testers: list[str] = []
    developers: list[str] = []
    for member in members or []:
        full_name = (member.get("fullName") or member.get("username") or "").strip()
        if not full_name:
            continue
        if _is_qa(full_name):
            if full_name not in testers:
                testers.append(full_name)
        else:
            if full_name not in developers:
                developers.append(full_name)
    return developers, testers


def build_handoff_context(
    *,
    card,
    release_name: str = "",
    approved_at: str = "",
    acceptance_criteria: str = "",
    test_cases: str = "",
    ai_qa_summary: str = "",
    ai_qa_evidence: str = "",
    signoff_summary: str = "",
    members: list[dict] | None = None,
) -> HandoffDocContext:
    devs, testers = split_card_members(members or [])
    desc = getattr(card, "desc", "") or ""
    toggles = detect_toggles(desc, getattr(card, "name", "") or "")
    return HandoffDocContext(
        card_id=getattr(card, "id", ""),
        card_name=getattr(card, "name", ""),
        card_url=getattr(card, "url", "") or "",
        release_name=release_name,
        approved_at=approved_at,
        card_description=desc,
        acceptance_criteria=acceptance_criteria or desc,
        test_cases=test_cases,
        ai_qa_summary=ai_qa_summary,
        ai_qa_evidence=ai_qa_evidence,
        signoff_summary=signoff_summary,
        developer_names=devs,
        tester_names=testers,
        toggle_names=toggles,
    )


_SUPPORT_PROMPT = """You are writing a polished internal Support Guide for a Shopify shipping-app feature handoff.

Write a practical, support/demo-friendly document in markdown.

Requirements:
- Clear title
- Short feature summary
- Developed by
- Tested by
- Toggle / prerequisite section
- Where to find the feature in the app
- Step-by-step walkthrough for support/demo team
- Expected behaviour / what support should observe
- Business-safe explanations (support-friendly, not code jargon heavy)
- Common questions / troubleshooting
- Known limitations / rollout notes
- References section with Trello link when available

Use facts from the context only. Do not invent unsupported details.
Keep it concise but useful.

CONTEXT:
{context}
"""


_BUSINESS_PROMPT = """You are writing a polished internal Business Brief for a Shopify shipping-app feature.

Write a clear stakeholder-facing markdown document.

Requirements:
- Strong title
- One-line value statement
- Problem statement
- What changed
- Real merchant/business scenarios
- Key benefits
- Operational/support impact
- Rollout / toggle notes
- References

Use facts from the context only. Avoid shallow marketing filler.
Keep it concise, concrete, and presentation-ready.

CONTEXT:
{context}
"""


def _context_text(ctx: HandoffDocContext) -> str:
    parts = [
        f"Card: {ctx.card_name}",
        f"Card URL: {ctx.card_url or '(none)'}",
        f"Release: {ctx.release_name or '(unknown)'}",
        f"Approved at: {ctx.approved_at or '(unknown)'}",
        f"Developed by: {', '.join(ctx.developer_names) if ctx.developer_names else 'Unknown'}",
        f"Tested by: {', '.join(ctx.tester_names) if ctx.tester_names else 'QA Team'}",
        f"Toggles: {', '.join(ctx.toggle_names) if ctx.toggle_names else 'None detected'}",
        "",
        "CARD DESCRIPTION / CURRENT AC:",
        (ctx.acceptance_criteria or ctx.card_description or "").strip()[:7000],
        "",
        "TEST CASES:",
        (ctx.test_cases or "").strip()[:6000],
        "",
        "AI QA SUMMARY:",
        (ctx.ai_qa_summary or "").strip()[:3000],
        "",
        "AI QA EVIDENCE:",
        (ctx.ai_qa_evidence or "").strip()[:5000],
        "",
        "SIGN-OFF / NOTES:",
        (ctx.signoff_summary or "").strip()[:2000],
    ]
    return "\n".join(parts).strip()


def _invoke_doc_prompt(prompt: str, ctx: HandoffDocContext) -> str:
    if not config.ANTHROPIC_API_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY not set")
    claude = ChatAnthropic(
        model=config.CLAUDE_SONNET_MODEL,
        api_key=config.ANTHROPIC_API_KEY,
        temperature=0.1,
        max_tokens=2400,
    )
    resp = claude.invoke([HumanMessage(content=prompt.format(context=_context_text(ctx)))])
    content = resp.content if isinstance(resp.content, str) else str(resp.content)
    return content.strip()


def _fallback_support_doc(ctx: HandoffDocContext) -> str:
    toggles = ", ".join(ctx.toggle_names) if ctx.toggle_names else "None detected"
    devs = ", ".join(ctx.developer_names) if ctx.developer_names else "Unknown"
    testers = ", ".join(ctx.tester_names) if ctx.tester_names else "QA Team"
    return f"""# Support Guide — {ctx.card_name}

## Summary
This document helps the support/demo team understand and explain the feature.

## Ownership
- Developed by: {devs}
- Tested by: {testers}

## Toggle / Prerequisites
- {toggles}

## Where to Find It
- FedEx app path: derive from AC / card context

## What Changed
{(ctx.acceptance_criteria or ctx.card_description or 'No description available').strip()[:2500]}

## Test Coverage Summary
{(ctx.ai_qa_summary or 'No AI QA summary recorded').strip()[:1200]}

## Support Notes
- Review the Trello card and approved test cases before demoing.
- If toggles are required, confirm store enablement first.

## References
- Trello: {ctx.card_url or 'N/A'}
"""


def _fallback_business_doc(ctx: HandoffDocContext) -> str:
    toggles = ", ".join(ctx.toggle_names) if ctx.toggle_names else "None detected"
    return f"""# Business Brief — {ctx.card_name}

## Value Statement
This change improves merchant workflow and support readiness for the feature.

## Problem
{(ctx.card_description or ctx.acceptance_criteria or 'Problem statement not available').strip()[:1800]}

## What Changed
{(ctx.acceptance_criteria or 'No acceptance criteria available').strip()[:2200]}

## Operational Notes
- Release: {ctx.release_name or 'Unknown'}
- Toggles: {toggles}

## Support / Rollout Impact
- Support team should use the support guide for demo and troubleshooting.
- Confirm toggle or rollout prerequisites before enabling for merchants.

## References
- Trello: {ctx.card_url or 'N/A'}
"""


def generate_support_guide(ctx: HandoffDocContext) -> str:
    try:
        return _invoke_doc_prompt(_SUPPORT_PROMPT, ctx)
    except Exception as exc:
        logger.warning("Support guide generation fell back to template: %s", exc)
        return _fallback_support_doc(ctx)


def generate_business_brief(ctx: HandoffDocContext) -> str:
    try:
        return _invoke_doc_prompt(_BUSINESS_PROMPT, ctx)
    except Exception as exc:
        logger.warning("Business brief generation fell back to template: %s", exc)
        return _fallback_business_doc(ctx)


def render_pdf_bytes(title: str, markdown_text: str) -> bytes:
    try:
        from reportlab.lib.colors import HexColor
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import inch
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "PDF export requires the optional 'reportlab' dependency."
        ) from exc

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        rightMargin=0.7 * inch,
        leftMargin=0.7 * inch,
        topMargin=0.7 * inch,
        bottomMargin=0.7 * inch,
        title=title,
    )
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(
        name="DocTitle",
        parent=styles["Title"],
        fontName="Helvetica-Bold",
        fontSize=20,
        leading=24,
        textColor=HexColor("#1f3a5f"),
        spaceAfter=12,
    ))
    styles.add(ParagraphStyle(
        name="H2Doc",
        parent=styles["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=14,
        leading=18,
        textColor=HexColor("#243b53"),
        spaceBefore=10,
        spaceAfter=6,
    ))
    styles.add(ParagraphStyle(
        name="H3Doc",
        parent=styles["Heading3"],
        fontName="Helvetica-Bold",
        fontSize=12,
        leading=15,
        textColor=HexColor("#334e68"),
        spaceBefore=8,
        spaceAfter=4,
    ))
    styles.add(ParagraphStyle(
        name="BodyDoc",
        parent=styles["BodyText"],
        fontName="Helvetica",
        fontSize=10.5,
        leading=14,
        spaceAfter=5,
    ))

    story = [Paragraph(title, styles["DocTitle"]), Spacer(1, 6)]
    lines = markdown_text.splitlines()
    for raw in lines:
        line = raw.strip()
        if not line:
            story.append(Spacer(1, 6))
            continue
        if line.startswith("# "):
            story.append(Paragraph(_escape(line[2:].strip()), styles["DocTitle"]))
        elif line.startswith("## "):
            story.append(Paragraph(_escape(line[3:].strip()), styles["H2Doc"]))
        elif line.startswith("### "):
            story.append(Paragraph(_escape(line[4:].strip()), styles["H3Doc"]))
        elif re.match(r"^[-*]\s+", line):
            story.append(Paragraph(_escape(line[2:].strip()), styles["BodyDoc"], bulletText="•"))
        else:
            story.append(Paragraph(_format_inline_md(line), styles["BodyDoc"]))
    doc.build(story)
    return buf.getvalue()


def _escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _format_inline_md(text: str) -> str:
    escaped = _escape(text)
    escaped = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", escaped)
    escaped = re.sub(r"`(.+?)`", r"<font name='Courier'>\1</font>", escaped)
    return escaped
