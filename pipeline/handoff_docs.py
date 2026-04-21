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


_BUSINESS_PROMPT = """You are a product marketing writer. Write a concise, visually clean Business Brief for a Shopify shipping-app feature that will be read by non-technical stakeholders — marketing, sales, and account managers.

━━━ STRICT RULES ━━━
• MAXIMUM 400 words total. Brevity is required.
• Plain business English only — absolutely no technical terms (no "client-side", "API", "GraphQL", "REST", "backend", "frontend", "regex", "substring", "UTC", "DST", etc.)
• Short paragraphs — 2 sentences max per paragraph
• NO developer or QA attribution (no "Developed by", "Tested by")
• NO QA notes, test counts, or sign-off details
• NO internal Trello links or support ticket numbers in the main body
• NO toggle/flag details unless the merchant must do something to enable the feature
• Tables allowed only if they have ≤ 4 rows and add genuine clarity

━━━ DOCUMENT STRUCTURE (use exactly in this order) ━━━

## [Feature Name in Plain English]
*One punchy sentence — the headline value for merchants.*

---

### 🔍 The Problem
2–3 sentences. What frustration or inefficiency did merchants face before this? Make it relatable and concrete — describe the pain, not the technical gap.

---

### ✅ What's New
3–5 bullet points. Each bullet = one new thing a merchant can now do.
Start each bullet with an action verb. No jargon.

---

### 👥 Who Benefits
2–3 short named scenarios (1–2 sentences each). Use merchant archetypes:
e.g. "High-volume store owners can now..." / "Support agents can now..."
Focus on the outcome, not the mechanism.

---

### 💡 Why It Matters
2–3 sentences. The single most important business outcome. Think: time saved, tickets avoided, merchant satisfaction, or competitive edge.

---

### 📌 Availability
One line: Is this on by default? Does the merchant need to do anything?
If no toggle is needed, write: "Available automatically for all merchants — no setup required."

━━━ TONE ━━━
Confident, warm, clear. Write as if briefing a smart businessperson who has never opened the app.

━━━ CONTEXT ━━━
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


def _invoke_doc_prompt(prompt: str, ctx: HandoffDocContext, max_tokens: int = 2400) -> str:
    if not config.ANTHROPIC_API_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY not set")
    claude = ChatAnthropic(
        model=config.CLAUDE_SONNET_MODEL,
        api_key=config.ANTHROPIC_API_KEY,
        temperature=0.3,
        max_tokens=max_tokens,
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
        return _invoke_doc_prompt(_BUSINESS_PROMPT, ctx, max_tokens=900)
    except Exception as exc:
        logger.warning("Business brief generation fell back to template: %s", exc)
        return _fallback_business_doc(ctx)


def render_pdf_bytes(title: str, markdown_text: str) -> bytes:
    """
    Render a markdown string to a polished, branded PDF.
    Handles **bold**, *italic*, `code`, bullet lists, headings,
    --- dividers, and emoji section headers.
    """
    try:
        from reportlab.lib import colors as _rl_colors
        from reportlab.lib.colors import HexColor, white
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import inch, mm
        from reportlab.platypus import (
            HRFlowable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
        )
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "PDF export requires the optional 'reportlab' dependency."
        ) from exc

    # ── Brand palette ────────────────────────────────────────────
    NAVY      = HexColor("#1B2D4F")   # deep navy – header banner
    ACCENT    = HexColor("#2563A8")   # medium blue – section headers & accents
    LIGHT_BG  = HexColor("#EEF3FA")   # pale blue – tagline box
    RULE      = HexColor("#C8D6EA")   # subtle divider line
    BODY_COL  = HexColor("#2C3E50")   # body text
    MUTED     = HexColor("#6B7E99")   # footer / meta text
    BULLET_BG = HexColor("#D9E5F5")   # bullet left-bar background

    # ── Page geometry ────────────────────────────────────────────
    PAGE_W, PAGE_H = A4
    LM = RM = 0.65 * inch
    CONTENT_W = PAGE_W - LM - RM

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=LM, rightMargin=RM,
        topMargin=0.35 * inch, bottomMargin=0.55 * inch,
        title=title,
    )

    # ── Styles ───────────────────────────────────────────────────
    base = getSampleStyleSheet()

    def _ps(name, **kw):
        parent = kw.pop("parent", base["Normal"])
        return ParagraphStyle(name, parent=parent, **kw)

    BANNER_DOC   = _ps("BannerDoc",   fontName="Helvetica", fontSize=8,
                        textColor=HexColor("#A8BFD8"), leading=10)
    BANNER_TITLE = _ps("BannerTitle", fontName="Helvetica-Bold", fontSize=15,
                        textColor=white, leading=19)
    TAGLINE      = _ps("Tagline",     fontName="Helvetica-Oblique", fontSize=10.5,
                        textColor=NAVY, leading=15, leftIndent=4, rightIndent=4)
    H2           = _ps("H2",          fontName="Helvetica-Bold", fontSize=11.5,
                        textColor=ACCENT, leading=15, spaceBefore=10, spaceAfter=3)
    H3           = _ps("H3",          fontName="Helvetica-Bold", fontSize=10.5,
                        textColor=NAVY, leading=14, spaceBefore=8, spaceAfter=2)
    BODY         = _ps("Body",        fontName="Helvetica", fontSize=10,
                        textColor=BODY_COL, leading=14.5, spaceAfter=4)
    BULLET       = _ps("Bullet",      parent=BODY, leftIndent=18, firstLineIndent=0,
                        spaceBefore=2, spaceAfter=3,
                        bulletColor=ACCENT, bulletFontSize=11)
    FOOTER       = _ps("Footer",      fontName="Helvetica", fontSize=7.5,
                        textColor=MUTED, alignment=1, leading=10)

    # ── Helpers ──────────────────────────────────────────────────
    _EMOJI_RE = re.compile(
        "[\U0001F300-\U0001FFFF"   # misc symbols & pictographs
        "\U00002600-\U000027BF"    # misc symbols
        "\U0000FE00-\U0000FE0F"    # variation selectors
        "]+",
        flags=re.UNICODE,
    )

    def _strip_emoji(text: str) -> str:
        return _EMOJI_RE.sub("", text).strip()

    def _esc(t: str) -> str:
        return t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    def _inline(text: str) -> str:
        """Convert markdown inline markup → ReportLab XML tags."""
        t = _esc(_strip_emoji(text))
        t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
        t = re.sub(r"\*(.+?)\*",     r"<i>\1</i>",  t)
        t = re.sub(r"`(.+?)`",       r"<font name='Courier'>\1</font>", t)
        return t.strip()

    def _section_bar(heading_text: str) -> Table:
        """Return a table that looks like:  [blue bar] [bold heading text]"""
        return Table(
            [[Paragraph("", BODY), Paragraph(_inline(heading_text), H2)]],
            colWidths=[4 * mm, CONTENT_W - 4 * mm],
            hAlign="LEFT",
        )

    def _tagline_box(text: str) -> Table:
        return Table(
            [[Paragraph(_inline(text), TAGLINE)]],
            colWidths=[CONTENT_W],
        )

    def _rule(thickness=0.5, color=RULE, space_before=4, space_after=4):
        return HRFlowable(
            width="100%", thickness=thickness, color=color,
            spaceBefore=space_before, spaceAfter=space_after,
        )

    # ── Header banner ────────────────────────────────────────────
    story = []

    parts = title.split("—", 1)
    doc_type     = parts[0].strip() if len(parts) > 1 else "Document"
    feature_name = parts[1].strip() if len(parts) > 1 else title

    banner = Table(
        [[
            Paragraph(_esc(doc_type).upper(), BANNER_DOC),
            Paragraph(_esc(feature_name),     BANNER_TITLE),
        ]],
        colWidths=[1.05 * inch, CONTENT_W - 1.05 * inch],
    )
    banner.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (0, 0), ACCENT),
        ("BACKGROUND",    (1, 0), (1, 0), NAVY),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN",         (0, 0), (0, 0), "CENTER"),
        ("LEFTPADDING",   (0, 0), (-1, -1), 10),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 10),
        ("TOPPADDING",    (0, 0), (-1, -1), 14),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 14),
    ]))
    story.append(banner)
    story.append(Spacer(1, 8))

    # ── Parse markdown ───────────────────────────────────────────
    lines = markdown_text.splitlines()
    idx = 0
    while idx < len(lines):
        raw  = lines[idx]
        line = raw.strip()
        idx += 1

        # Skip blank / title line that duplicates the banner
        if not line:
            story.append(Spacer(1, 3))
            continue

        # Hard rules → thin visual spacer only
        if re.fullmatch(r"[-*_]{3,}", line):
            story.append(_rule(space_before=2, space_after=2))
            continue

        # H1 (# …) → skip; already in banner
        if line.startswith("# "):
            continue

        # H2 (## …) or H3 (### …) → coloured section header
        if line.startswith("### "):
            text = line[4:].strip()
            bar = _section_bar(text)
            bar.setStyle(TableStyle([
                ("BACKGROUND",    (0, 0), (0, 0), ACCENT),
                ("VALIGN",        (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING",   (0, 0), (-1, -1), 0),
                ("RIGHTPADDING",  (0, 0), (-1, -1), 0),
                ("TOPPADDING",    (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]))
            story.append(bar)
            continue

        if line.startswith("## "):
            text = line[3:].strip()
            bar = _section_bar(text)
            bar.setStyle(TableStyle([
                ("BACKGROUND",    (0, 0), (0, 0), ACCENT),
                ("VALIGN",        (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING",   (0, 0), (-1, -1), 0),
                ("RIGHTPADDING",  (0, 0), (-1, -1), 0),
                ("TOPPADDING",    (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]))
            story.append(bar)
            continue

        # Italic tagline  *text* (standalone line)
        tagline_match = re.fullmatch(r"\*([^*].+?[^*])\*", line)
        if tagline_match:
            box = _tagline_box(tagline_match.group(1))
            box.setStyle(TableStyle([
                ("BACKGROUND",    (0, 0), (-1, -1), LIGHT_BG),
                ("LEFTPADDING",   (0, 0), (-1, -1), 12),
                ("RIGHTPADDING",  (0, 0), (-1, -1), 12),
                ("TOPPADDING",    (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                ("LINEBELOW",     (0, 0), (-1, -1), 1.5, ACCENT),
            ]))
            story.append(box)
            story.append(Spacer(1, 6))
            continue

        # Bullet  (•, -, *)
        if re.match(r"^[•\-\*]\s+", line):
            bullet_text = re.sub(r"^[•\-\*]\s+", "", line)
            story.append(Paragraph(
                _inline(bullet_text),
                BULLET,
                bulletText="•",
            ))
            continue

        # Table row  | … | … | — skip (not supported in business brief)
        if line.startswith("|") and line.endswith("|"):
            continue

        # Default: body paragraph
        story.append(Paragraph(_inline(line), BODY))

    # ── Footer ───────────────────────────────────────────────────
    story.append(Spacer(1, 14))
    story.append(_rule(thickness=0.8, color=ACCENT))
    story.append(Paragraph(
        f"PluginHive · Shopify FedEx Shipping App · "
        f"{_dt.date.today().strftime('%B %d, %Y')}",
        FOOTER,
    ))

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
    escaped = re.sub(r"\*(.+?)\*",     r"<i>\1</i>",  escaped)
    escaped = re.sub(r"`(.+?)`",       r"<font name='Courier'>\1</font>", escaped)
    return escaped
