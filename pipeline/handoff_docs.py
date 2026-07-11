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
    # Conflict warnings injected before doc generation
    qa_code_conflicts: str = ""
    # RAG-fetched navigation context (auto-populated by generate_support_guide)
    rag_nav_context: str = ""
    # Code-search context — frontend + backend snippets for new features
    # not yet covered by the known navigation map (auto-populated)
    code_context: str = ""
    # Code index status message injected when index is empty/stale
    code_index_status: str = ""


# ── FedEx app navigation structure ──────────────────────────────────────────
# Injected into every support guide so Claude can write accurate "Where to find"
# and "Step-by-step walkthrough" sections even for brand-new features.
_FEDEX_APP_NAV = """
APP NAVIGATION STRUCTURE (FedEx Shopify App):
─────────────────────────────────────────────
The FedEx app is embedded inside Shopify admin as an iframe (iframe[name="app-iframe"]).

App sidebar sections (INSIDE iframe):
  • Shipping   — All Orders grid; tabs: All | Label Created | Awaiting Shipment | Shipped | Cancelled | Delivery Exception
  • Settings   — Account, Packaging, Carrier Services, Additional Settings, International Shipping, Pickup Settings, etc.
  • Products   — Map Shopify products to special services (Signature, Insurance, Dangerous Goods, etc.)
  • PickUp     — Schedule FedEx pickup
  • Rates Log  — Historical rate request / response JSON logs
  • FAQ        — Help articles

Shopify admin sidebar (OUTSIDE iframe):
  • Orders  — Shopify orders list (click order → More Actions to reach the app)
  • Products — Shopify product catalog

Manual Label Generation flow:
  Shopify Orders → click order row → More Actions (button) → "Generate Label" (link)
  → App label page opens in iframe:
    LEFT panel  : Generate Packages → Get Rates → select rate radio button
    RIGHT panel : SideDock (always visible — configure BEFORE clicking Generate Label):
                  1. Address Classification (Residential / Commercial)
                  2. Signature Options (Adult / Direct / Indirect / No Signature / Service Default)
                  3. Hold at Location (HAL) — button → modal → select FedEx location
                  4. Insurance — checkbox → pencil icon → modal → enter declared value
                  5. COD — checkbox → COD Amount, TIN Type, contact/address
                  6. Duties & Taxes (international) — Purpose, Terms of Sale, Duties Payment Type
  → "Generate Label" button → redirects to Order Summary page

Auto Label Generation:
  Shopify Orders → click order row → More Actions → "Auto-Generate Label"
  → Label generated automatically → Order Summary page

Bulk Label Generation:
  Shopify admin Orders list → select orders (header checkbox) → Actions → "Auto-Generate Labels"

Order Summary page buttons:
  Print Documents | Upload Documents | Download Documents | Track Order | More Actions ▾
  More Actions items: Cancel Label | Return Label | How To
  Tabs on page: Packages | Return packages

Return Label:
  Way A: Order Summary → "Return packages" tab → "Return Packages" button → Refresh Rates → select → Generate Return Label
  Way B: Shopify Orders → More Actions → "Generate Return Label"
"""


def _fetch_nav_context(card_name: str, ac_text: str = "") -> str:
    """Search the domain vectorstore for navigation / UI docs relevant to this feature.

    Returns a formatted string to inject into the support guide context,
    or empty string if the vectorstore is unavailable or returns nothing.
    """
    try:
        from rag.vectorstore import search
        query = f"{card_name} navigation steps where to find feature app UI settings"
        if ac_text:
            query += " " + ac_text[:200]
        docs = search(query, k=4)
        if not docs:
            return ""
        parts = ["RELEVANT APP KNOWLEDGE (from knowledge base):"]
        for doc in docs:
            src = doc.metadata.get("source", doc.metadata.get("source_type", ""))
            snippet = doc.page_content.strip()[:450]
            parts.append(f"[{src}]: {snippet}")
        return "\n\n".join(parts)
    except Exception as exc:
        logger.debug("Nav context RAG search failed: %s", exc)
        return ""


def _check_code_index() -> dict:
    """Return code index stats: frontend/backend chunk counts + last-sync commit.

    Used to decide whether to suggest a re-index before searching for
    new-feature navigation. Returns dict with keys:
      frontend, backend, total — int chunk counts
      indexed — bool (True if at least one source has chunks)
      stale_sources — list[str] sources with 0 chunks
    """
    try:
        from rag.code_indexer import get_index_stats
        stats = get_index_stats()
        stale: list[str] = []
        if stats.get("frontend", 0) == 0:
            stale.append("frontend")
        if stats.get("backend", 0) == 0:
            stale.append("backend")
        stats["indexed"] = stats.get("total", 0) > 0
        stats["stale_sources"] = stale
        return stats
    except Exception as exc:
        logger.debug("Code index check failed: %s", exc)
        return {"frontend": 0, "backend": 0, "total": 0, "indexed": False,
                "stale_sources": ["frontend", "backend"], "error": str(exc)}


def _fetch_code_context(card_name: str, ac_text: str = "") -> str:
    """Search the code vectorstore (frontend + backend) for UI components,
    button labels, routes, and business logic related to this feature.

    This is the fallback for NEW features where the navigation map may not
    yet have an entry. The frontend code contains exact button text, route
    paths, and component structure. The backend contains API endpoints and
    feature flags.

    Returns a formatted string to inject into the support guide context,
    or empty string if the code collection is unavailable.
    """
    try:
        from rag.code_indexer import search_code
        query = f"{card_name} button label route component UI screen"
        if ac_text:
            query += " " + ac_text[:200]

        parts: list[str] = []

        # Frontend first — has button labels, route paths, React/TS components
        frontend_docs = search_code(query, k=4, source_type="frontend")
        if frontend_docs:
            parts.append("FRONTEND CODE (button labels, routes, components):")
            for doc in frontend_docs:
                file_path = doc.metadata.get("file_path", doc.metadata.get("source", ""))
                snippet = doc.page_content.strip()[:500]
                parts.append(f"[{file_path}]:\n{snippet}")

        # Backend — has API endpoints, feature logic, service names
        backend_docs = search_code(query, k=3, source_type="backend")
        if backend_docs:
            parts.append("BACKEND CODE (API endpoints, business logic):")
            for doc in backend_docs:
                file_path = doc.metadata.get("file_path", doc.metadata.get("source", ""))
                snippet = doc.page_content.strip()[:400]
                parts.append(f"[{file_path}]:\n{snippet}")

        if not parts:
            return ""
        return "\n\n".join(parts)
    except Exception as exc:
        logger.debug("Code context search failed: %s", exc)
        return ""


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


_CONFLICT_DETECT_PROMPT = """You are a technical reviewer checking for conflicts between QA comments and code-level implementation evidence inside a Trello card.

Your job: read the card context below and identify every place where a QA comment, QA note, or acceptance-criteria statement describes behavior that is BROADER, DIFFERENT, or CONTRADICTED by what the actual code implementation (code snippets, suggested approach, test coverage list, or implementation checklist) does.

Focus especially on:
- Scope differences: QA says "X and Y are affected" but code only handles X
- Day/date/range differences: QA says "Saturday or Sunday" but code checks only Saturday (isoWeekday === 6)
- Field differences: QA mentions a field but code ignores it
- Condition differences: QA says "always" but code says "only when flag is set"
- Test case contradictions: a test case says "unchanged" but QA note implies it changes

For EACH conflict found, output:
CONFLICT: <short label>
QA SAYS: <exact quote or close paraphrase of what the QA comment/AC states>
CODE DOES: <what the code implementation/checklist/test cases actually do>
IMPACT: <which sentence in a support guide would be wrong if QA wording is used>

If no conflicts are found, output exactly: NO CONFLICTS DETECTED

Be concise. Only report genuine conflicts — not vague wording or minor phrasing differences.

CARD CONTEXT:
{context}
"""

_SUPPORT_PROMPT = """You are writing a polished internal Support Guide for a Shopify shipping-app feature handoff.

Write a practical, support/demo-friendly document in markdown.

Requirements:
- Clear title
- Trello card link prominently at the top (immediately after the title, formatted as: **Trello:** [Card Title or URL](url))
- Short feature summary
- Toggle / prerequisite section
- Where to find the feature in the app (use exact paths from APP NAVIGATION STRUCTURE or code context)
- Step-by-step walkthrough for support/demo team (use exact button/link names from code or AI QA evidence)
- Expected behaviour / what support should observe

DO NOT include any of the following sections:
- Developed by
- Tested by
- Business-Safe Explanation (For Merchant-Facing Communication)
- Common Questions / Troubleshooting (or any Q&A section)
- Known Limitations / Rollout Notes

NAVIGATION RULE (CRITICAL):
Use this priority order to write "Where to Find" and "Walkthrough" sections:
1. AI QA Evidence in context → extract actual navigate/click/fill steps (ground truth for live app)
2. FRONTEND CODE / BACKEND CODE snippets in context → extract exact button text, route paths
3. APP NAVIGATION STRUCTURE block in context → use known flows for existing features
4. AC / test case text → use only if none of the above apply

UNKNOWN NAVIGATION RULE (CRITICAL):
If you cannot determine exact navigation steps for a section from ANY source in the context:
- Do NOT guess or invent steps
- Do NOT add "QA NOTE" blocks, "Navigation Confirmation Needed" callouts, or any
  "requires QA confirmation / see QA NOTE above" inline notes anywhere in the document
- Instead, write the section using the best available navigation information (known app
  structure, code context, or AC text), describing the flow at the level of detail you can
  support, without flagging uncertainty in the output

CONFLICT RESOLUTION RULE (CRITICAL):
If CONFLICT WARNINGS appear in the context below, treat the code-level implementation as the ground truth — not the QA comment wording. The support guide must reflect what the code actually does, not what was initially requested.

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
    ]
    # Always inject the app navigation structure so Claude can write accurate
    # "Where to find" and "Step-by-step walkthrough" sections.
    parts += [_FEDEX_APP_NAV.strip(), ""]
    # Inject RAG-fetched navigation context when available
    if ctx.rag_nav_context:
        parts += [ctx.rag_nav_context.strip(), ""]
    # Inject code-search context (frontend + backend) for new features
    if ctx.code_context:
        parts += [ctx.code_context.strip(), ""]
    # Inject code index status (empty/stale warning) when code search found nothing
    if ctx.code_index_status:
        parts += [ctx.code_index_status.strip(), ""]
    # Inject conflict warnings at the top so Claude sees them before card prose
    if ctx.qa_code_conflicts and "NO CONFLICTS DETECTED" not in ctx.qa_code_conflicts:
        parts += [
            "⚠️  CONFLICT WARNINGS — QA COMMENT vs CODE IMPLEMENTATION:",
            "The following conflicts were detected. Use CODE DOES as ground truth when writing this guide.",
            ctx.qa_code_conflicts.strip(),
            "",
        ]
    parts += [
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


def detect_qa_code_conflicts(ctx: HandoffDocContext) -> str:
    """
    Run a conflict-detection pass over the card context.

    Looks for places where QA comments/AC describe behavior that is broader
    or different from what the actual code implementation does (code snippets,
    suggested approach, test coverage items, implementation checklist).

    Returns a formatted conflict report string, or "NO CONFLICTS DETECTED".
    The result should be stored in ctx.qa_code_conflicts before calling
    generate_support_guide() so the support guide prompt can resolve conflicts
    in favour of the code implementation.
    """
    try:
        if not config.ANTHROPIC_API_KEY:
            return "NO CONFLICTS DETECTED"
        claude = ChatAnthropic(
            model=config.CLAUDE_SONNET_MODEL,
            api_key=config.ANTHROPIC_API_KEY,
            temperature=0.1,
            max_tokens=1200,
        )
        prompt = _CONFLICT_DETECT_PROMPT.format(context=_context_text(ctx))
        resp = claude.invoke([HumanMessage(content=prompt)])
        result = resp.content if isinstance(resp.content, str) else str(resp.content)
        return result.strip()
    except Exception as exc:
        logger.warning("Conflict detection failed: %s", exc)
        return "NO CONFLICTS DETECTED"


def generate_support_guide(ctx: HandoffDocContext) -> str:
    try:
        ac_text = ctx.acceptance_criteria or ctx.card_description

        # Step 1 — domain RAG: navigation docs, existing feature knowledge
        if not ctx.rag_nav_context:
            ctx.rag_nav_context = _fetch_nav_context(ctx.card_name, ac_text)

        # Step 2 — code RAG: frontend + backend source for NEW features.
        # When AI QA evidence is absent, code is the best source of exact
        # button labels, route paths, and component structure.
        if not ctx.code_context and not ctx.ai_qa_evidence:
            # Check index health before searching — surface stale/empty index early
            index = _check_code_index()
            if not index.get("indexed"):
                ctx.code_index_status = (
                    "⚠️  CODE INDEX STATUS: The frontend + backend code collection is empty "
                    "(0 chunks indexed). Navigation steps for new features cannot be looked up "
                    "from source code.\n"
                    "TO FIX: Run the following to index the codebase, then regenerate:\n"
                    "  cd /Users/madan/Documents/Fed-Ex-automation/FedexDomainExpert\n"
                    "  .venv/bin/python -m ingest.run_ingest --sources codebase\n"
                    "Until then, use QA NOTE blocks for any navigation that cannot be confirmed."
                )
            else:
                stale = index.get("stale_sources", [])
                ctx.code_context = _fetch_code_context(ctx.card_name, ac_text)
                if not ctx.code_context and stale:
                    ctx.code_index_status = (
                        f"⚠️  CODE INDEX STATUS: Sources {stale} have 0 chunks. "
                        f"Frontend: {index.get('frontend', 0)} chunks, "
                        f"Backend: {index.get('backend', 0)} chunks. "
                        "Navigation for new features in these sources cannot be confirmed from code. "
                        "Use QA NOTE blocks for any navigation that cannot be determined."
                    )

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

    Handles: headings H1–H3, **bold**, *italic*, `code`, bullet lists,
    numbered lists, blockquotes (QA NOTE / warning boxes), fenced code blocks,
    Markdown tables (with zebra striping), checkbox items (- [ ] / - [x]),
    inline links [text](url), horizontal rules, and italic tagline lines.
    H1 sections each get a new page with a branded banner.
    """
    try:
        from reportlab.lib.colors import HexColor, white
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import inch
        from reportlab.platypus import (
            HRFlowable, KeepTogether, PageBreak, Paragraph,
            SimpleDocTemplate, Spacer, Table, TableStyle,
        )
    except ModuleNotFoundError as exc:
        raise RuntimeError("PDF export requires the optional 'reportlab' dependency.") from exc

    # ── Palette ──────────────────────────────────────────────────
    NAVY        = HexColor("#1B2D4F")
    ACCENT      = HexColor("#2563A8")
    ACCENT_DARK = HexColor("#1A4D8F")
    LIGHT_BG    = HexColor("#EEF3FA")
    WARN_BG     = HexColor("#FFF8E6")
    WARN_BORDER = HexColor("#E8A820")
    NOTE_BG     = HexColor("#EEF3FA")
    NOTE_BORDER = HexColor("#2563A8")
    CODE_BG     = HexColor("#F3F4F6")
    RULE_COL    = HexColor("#C8D6EA")
    BODY_COL    = HexColor("#2C3E50")
    MUTED       = HexColor("#6B7E99")
    TBL_HDR     = HexColor("#1B2D4F")
    TBL_ALT     = HexColor("#F0F4FA")
    TBL_GRID    = HexColor("#D0DCF0")

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

    BANNER_LABEL = _ps("BannerLabel", fontName="Helvetica", fontSize=7.5,
                        textColor=HexColor("#A8BFD8"), leading=10)
    BANNER_TITLE = _ps("BannerTitle", fontName="Helvetica-Bold", fontSize=14,
                        textColor=white, leading=18)
    TAGLINE_ST   = _ps("Tagline",     fontName="Helvetica-Oblique", fontSize=10,
                        textColor=NAVY, leading=14, leftIndent=4, rightIndent=4)
    H2_ST        = _ps("H2",          fontName="Helvetica-Bold", fontSize=11.5,
                        textColor=ACCENT, leading=15, spaceBefore=10, spaceAfter=3)
    H3_ST        = _ps("H3",          fontName="Helvetica-Bold", fontSize=10.5,
                        textColor=NAVY, leading=14, spaceBefore=8, spaceAfter=2)
    BODY_ST      = _ps("Body",        fontName="Helvetica", fontSize=9.5,
                        textColor=BODY_COL, leading=14, spaceAfter=4)
    BULLET_ST    = _ps("Bullet",      parent=BODY_ST, leftIndent=16, firstLineIndent=0,
                        spaceBefore=2, spaceAfter=2)
    NUM_ST       = _ps("Num",         parent=BODY_ST, leftIndent=22, firstLineIndent=0,
                        spaceBefore=2, spaceAfter=2)
    QUOTE_ST     = _ps("Quote",       fontName="Helvetica", fontSize=9,
                        textColor=HexColor("#3A4A5C"), leading=13, leftIndent=8, rightIndent=4)
    CODE_ST      = _ps("Code",        fontName="Courier", fontSize=8,
                        textColor=HexColor("#1E293B"), leading=12, leftIndent=6)
    META_ST      = _ps("Meta",        fontName="Helvetica", fontSize=9,
                        textColor=BODY_COL, leading=12, spaceAfter=1)
    TBL_HDR_ST   = _ps("TblHdr",      fontName="Helvetica-Bold", fontSize=8.5,
                        textColor=white, leading=12)
    TBL_CELL_ST  = _ps("TblCell",     fontName="Helvetica", fontSize=8.5,
                        textColor=BODY_COL, leading=12)

    # ── Emoji strip ──────────────────────────────────────────────
    _EMOJI_RE = re.compile(
        "[\U0001F300-\U0001FFFF\U00002600-\U000027BF\U0000FE00-\U0000FE0F]+",
        flags=re.UNICODE,
    )

    def _strip_emoji(t: str) -> str:
        return _EMOJI_RE.sub("", t).strip()

    def _esc(t: str) -> str:
        return t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    def _inline(text: str, linkify: bool = True) -> str:
        """Markdown inline → ReportLab XML. Handles bold, italic, code, links."""
        t = _esc(_strip_emoji(text))
        # Links [label](url) — render label as underlined, drop URL (RL free fonts don't support URI action well)
        t = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"<u>\1</u>", t)
        t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
        t = re.sub(r"\*([^*\n]+?)\*", r"<i>\1</i>", t)
        t = re.sub(r"`([^`]+)`", r"<font name='Courier'>\1</font>", t)
        return t.strip()

    # ── Layout helpers ───────────────────────────────────────────
    def _banner(label: str, feat_title: str) -> Table:
        tbl = Table(
            [[Paragraph(_esc(label).upper(), BANNER_LABEL),
              Paragraph(_esc(feat_title), BANNER_TITLE)]],
            colWidths=[0.95 * inch, CONTENT_W - 0.95 * inch],
        )
        tbl.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (0, 0), ACCENT),
            ("BACKGROUND",    (1, 0), (1, 0), NAVY),
            ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
            ("ALIGN",         (0, 0), (0, 0), "CENTER"),
            ("LEFTPADDING",   (0, 0), (-1, -1), 10),
            ("RIGHTPADDING",  (0, 0), (-1, -1), 10),
            ("TOPPADDING",    (0, 0), (-1, -1), 13),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 13),
        ]))
        return tbl

    def _rule(thickness=0.5, color=RULE_COL, sb=4, sa=4):
        return HRFlowable(width="100%", thickness=thickness, color=color,
                          spaceBefore=sb, spaceAfter=sa)

    def _callout(lines_text: list, is_warning: bool = False) -> Table:
        """Render a blockquote block as a styled callout box."""
        bg     = WARN_BG     if is_warning else NOTE_BG
        border = WARN_BORDER if is_warning else NOTE_BORDER
        combined = " ".join(l.strip() for l in lines_text if l.strip())
        tbl = Table(
            [[Paragraph(_inline(combined), QUOTE_ST)]],
            colWidths=[CONTENT_W - 0.18 * inch],
        )
        tbl.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (-1, -1), bg),
            ("LINEBEFORE",    (0, 0), (0, -1), 3.5, border),
            ("LEFTPADDING",   (0, 0), (-1, -1), 10),
            ("RIGHTPADDING",  (0, 0), (-1, -1), 8),
            ("TOPPADDING",    (0, 0), (-1, -1), 7),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ]))
        return tbl

    def _code_block(code_lines: list) -> Table:
        """Render a fenced code block."""
        content = "\n".join(code_lines)
        paras = [Paragraph(_esc(ln) or " ", CODE_ST) for ln in code_lines]
        tbl = Table([[p] for p in paras], colWidths=[CONTENT_W])
        tbl.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (-1, -1), CODE_BG),
            ("LEFTPADDING",   (0, 0), (-1, -1), 10),
            ("RIGHTPADDING",  (0, 0), (-1, -1), 8),
            ("TOPPADDING",    (0, 0), (-1, -1), 2),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ("ROWBACKGROUNDS",(0, 0), (-1, -1), [CODE_BG]),
            ("BOX",           (0, 0), (-1, -1), 0.5, RULE_COL),
        ]))
        return tbl

    def _md_table(header_row: list, data_rows: list) -> Table:
        """Render a Markdown table with header + zebra-striped rows."""
        n_cols = max(len(header_row), max((len(r) for r in data_rows), default=1))
        # Pad short rows
        def _pad(row, n):
            return row + [""] * (n - len(row))

        hdr = [Paragraph(_inline(c), TBL_HDR_ST) for c in _pad(header_row, n_cols)]
        rows = [[Paragraph(_inline(c), TBL_CELL_ST) for c in _pad(r, n_cols)]
                for r in data_rows]
        all_rows = [hdr] + rows

        col_w = CONTENT_W / n_cols
        col_widths = [col_w] * n_cols

        tbl = Table(all_rows, colWidths=col_widths, repeatRows=1)
        style_cmds = [
            ("BACKGROUND",    (0, 0), (-1, 0), TBL_HDR),
            ("TEXTCOLOR",     (0, 0), (-1, 0), white),
            ("FONTNAME",      (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE",      (0, 0), (-1, -1), 8.5),
            ("LEADING",       (0, 0), (-1, -1), 12),
            ("GRID",          (0, 0), (-1, -1), 0.4, TBL_GRID),
            ("LEFTPADDING",   (0, 0), (-1, -1), 7),
            ("RIGHTPADDING",  (0, 0), (-1, -1), 7),
            ("TOPPADDING",    (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("VALIGN",        (0, 0), (-1, -1), "TOP"),
        ]
        for i, _ in enumerate(rows):
            if i % 2 == 0:
                style_cmds.append(("ROWBACKGROUNDS", (0, i + 1), (-1, i + 1), [TBL_ALT]))
        tbl.setStyle(TableStyle(style_cmds))
        return tbl

    def _parse_table_row(line: str) -> list:
        """Parse a Markdown table row into a list of cell strings."""
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        return cells

    def _is_table_sep(line: str) -> bool:
        """True if line is a table separator row (|---|---|)."""
        return bool(re.fullmatch(r"[\|\-\:\s]+", line))

    # ── First pass: extract H1 titles for cover page TOC ────────
    h1_titles = []
    for raw_line in markdown_text.splitlines():
        stripped = raw_line.strip()
        if stripped.startswith("# ") and not stripped.startswith("## "):
            h1_titles.append(stripped[2:].strip())

    # ── Build cover page ─────────────────────────────────────────
    story = []

    title_parts = re.split(r"\s+[—\-]\s+", title, maxsplit=1)
    if len(title_parts) > 1:
        title_label, title_name = title_parts[0].strip(), title_parts[1].strip()
    elif "support guide" in title.lower():
        title_label, title_name = "Support Guide", title
    else:
        title_label, title_name = "Document", title

    story.append(_banner(title_label, title_name))
    story.append(Spacer(1, 16))

    if len(h1_titles) > 1:
        # TOC header
        TOC_LABEL = _ps("TOCLabel", fontName="Helvetica-Bold", fontSize=8,
                         textColor=MUTED, leading=12, spaceBefore=0, spaceAfter=6,
                         letterSpacing=1.0)
        story.append(Paragraph("CONTENTS", TOC_LABEL))
        TOC_ITEM = _ps("TOCItem", fontName="Helvetica", fontSize=9.5,
                        textColor=BODY_COL, leading=15, leftIndent=0)
        for i, t in enumerate(h1_titles[1:], 1):   # skip the release header H1
            story.append(Paragraph(
                f"<b>{i}.</b>  {_inline(t)}",
                TOC_ITEM,
            ))
        story.append(Spacer(1, 12))
        story.append(_rule(thickness=1, color=ACCENT, sb=0, sa=0))

    # ── Parse body ───────────────────────────────────────────────
    lines = markdown_text.splitlines()
    idx = 0
    in_release_details = False
    first_h1_seen = False
    current_label = title_label

    while idx < len(lines):
        raw = lines[idx]
        line = raw.strip()
        idx += 1

        # ── Fenced code block ────────────────────────────────────
        if line.startswith("```"):
            code_lines = []
            while idx < len(lines):
                cl = lines[idx]
                idx += 1
                if cl.strip().startswith("```"):
                    break
                code_lines.append(cl)
            if code_lines:
                story.append(Spacer(1, 4))
                story.append(_code_block(code_lines))
                story.append(Spacer(1, 4))
            continue

        # ── Blank line ───────────────────────────────────────────
        if not line:
            story.append(Spacer(1, 3))
            continue

        # ── Horizontal rule ──────────────────────────────────────
        if re.fullmatch(r"[-*_]{3,}", line):
            story.append(_rule(sb=3, sa=3))
            continue

        # ── H1 ───────────────────────────────────────────────────
        if line.startswith("# ") and not line.startswith("## "):
            h1_text = line[2:].strip()
            if not first_h1_seen:
                first_h1_seen = True
                # First H1 is the release title — already in cover banner; skip
                continue
            # Subsequent H1s → new page + banner
            parts = re.split(r"\s+[—\-]\s+", h1_text, maxsplit=1)
            if len(parts) > 1:
                current_label, banner_feat = parts[0].strip(), parts[1].strip()
            else:
                current_label = title_label
                banner_feat = h1_text
            story.append(PageBreak())
            story.append(_banner(current_label, banner_feat))
            story.append(Spacer(1, 10))
            in_release_details = False
            continue

        # ── H2 ───────────────────────────────────────────────────
        if line.startswith("## ") and not line.startswith("### "):
            text = line[3:].strip()
            in_release_details = text.lower() in ("release details", "details")
            if not in_release_details:
                story.append(_rule(sb=6, sa=0))
                story.append(Paragraph(_inline(text), H2_ST))
            continue

        # ── H3 ───────────────────────────────────────────────────
        if line.startswith("### "):
            text = line[4:].strip()
            story.append(Paragraph(_inline(text), H3_ST))
            continue

        # ── Markdown table ───────────────────────────────────────
        if line.startswith("|") and "|" in line[1:]:
            # Collect full table
            tbl_lines = [line]
            while idx < len(lines) and lines[idx].strip().startswith("|"):
                tbl_lines.append(lines[idx].strip())
                idx += 1
            if len(tbl_lines) < 2:
                story.append(Paragraph(_inline(line), BODY_ST))
                continue
            # Row 0: header, Row 1: separator, Rows 2+: data
            header = _parse_table_row(tbl_lines[0])
            data = []
            for tl in tbl_lines[2:]:
                if not _is_table_sep(tl):
                    data.append(_parse_table_row(tl))
            if header and (data or len(tbl_lines) >= 2):
                story.append(Spacer(1, 5))
                story.append(_md_table(header, data))
                story.append(Spacer(1, 6))
            continue

        # ── Blockquote ───────────────────────────────────────────
        if line.startswith("> ") or line == ">":
            bq_lines = [line[2:] if line.startswith("> ") else ""]
            while idx < len(lines):
                nxt = lines[idx].strip()
                if nxt.startswith("> ") or nxt == ">":
                    bq_lines.append(nxt[2:] if nxt.startswith("> ") else "")
                    idx += 1
                else:
                    break
            text_joined = " ".join(l for l in bq_lines if l.strip())
            is_warn = any(kw in text_joined.lower() for kw in ("warning", "note", "caution", "confirm", "qa note"))
            story.append(Spacer(1, 4))
            story.append(_callout(bq_lines, is_warning=is_warn))
            story.append(Spacer(1, 6))
            continue

        # ── Italic tagline (standalone *text*) ───────────────────
        tagline_m = re.fullmatch(r"\*([^*].+?[^*])\*", line)
        if tagline_m:
            tbl = Table([[Paragraph(_inline(tagline_m.group(1)), TAGLINE_ST)]],
                        colWidths=[CONTENT_W])
            tbl.setStyle(TableStyle([
                ("BACKGROUND",    (0, 0), (-1, -1), LIGHT_BG),
                ("LEFTPADDING",   (0, 0), (-1, -1), 12),
                ("RIGHTPADDING",  (0, 0), (-1, -1), 12),
                ("TOPPADDING",    (0, 0), (-1, -1), 7),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
                ("LINEBELOW",     (0, 0), (-1, -1), 1.5, ACCENT),
            ]))
            story.append(tbl)
            story.append(Spacer(1, 6))
            continue

        # ── Checkbox bullet  - [ ] / - [x] ──────────────────────
        chk_m = re.match(r"^[-*]\s+\[([ xX])\]\s+(.*)", line)
        if chk_m:
            checked = chk_m.group(1).lower() == "x"
            mark = "[x]" if checked else "[ ]"
            text = chk_m.group(2)
            story.append(Paragraph(
                f"<font name='Courier'>{mark}</font>  {_inline(text)}",
                BULLET_ST,
            ))
            continue

        # ── Bullet ───────────────────────────────────────────────
        if re.match(r"^[•\-\*]\s+", line) and not re.match(r"^[-*]{3,}$", line):
            bullet_text = re.sub(r"^[•\-\*]\s+", "", line)
            if in_release_details:
                story.append(Paragraph(_inline(bullet_text), META_ST))
            else:
                story.append(Paragraph(_inline(bullet_text), BULLET_ST, bulletText="•"))
            continue

        # ── Numbered list ────────────────────────────────────────
        num_m = re.match(r"^(\d+)\.\s+(.*)", line)
        if num_m:
            num = num_m.group(1)
            text = num_m.group(2)
            story.append(Paragraph(
                f"<b>{_esc(num)}.</b>  {_inline(text)}",
                NUM_ST,
            ))
            continue

        # ── Bold standalone step header (e.g. **Step 1 — ...**) ──
        if re.fullmatch(r"\*\*.+\*\*", line):
            story.append(Paragraph(_inline(line), H3_ST))
            continue

        # ── Default body paragraph ───────────────────────────────
        story.append(Paragraph(_inline(line), BODY_ST))

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
