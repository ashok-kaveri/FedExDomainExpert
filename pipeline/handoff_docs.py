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


REQUEST_LOG_CALLOUT_RE = re.compile(
    r"^[-*]\s*(?:Request node|Request nodes|Request/response nodes|Request/log fields) to verify:",
    flags=re.IGNORECASE,
)


def is_request_log_callout(markdown_line: str) -> bool:
    """Return true when a markdown bullet should render as a request/log callout."""
    return bool(REQUEST_LOG_CALLOUT_RE.match((markdown_line or "").strip()))


# An H2 that opens a card section in a combined release package:
# "ZI-651 - WSS order updates not syncing" or "941 - Add DAP Incoterm option".
CARD_SECTION_HEADING_RE = re.compile(r"^(?:[A-Z]{1,4}-\d{1,5}|\d{1,6})\s+-\s+\S")

# H2s that belong to the package itself rather than to a story card.
PACKAGE_LEVEL_HEADINGS = frozenset({
    "included story cards",
    "included updates",
    "release overview",
    "availability",
    "how support should use this package",
})


def is_card_section_heading(heading_text: str, combined_package: bool = False) -> bool:
    """Return true when a heading starts a new story-card section.

    Inside a combined package every H2 except the package-level ones is a card,
    because each card's own sections were demoted to H3. That matters for cards
    whose title carries no story id (for example "[F-DIM] Bulk Edit ..."), which
    an id pattern alone would miss and leave sharing a page with the card above.
    """
    text = (heading_text or "").strip()
    if not text or text.lower().rstrip(":") in PACKAGE_LEVEL_HEADINGS:
        return False
    if CARD_SECTION_HEADING_RE.match(text):
        return True
    return combined_package


def is_combined_package(markdown_lines: list[str]) -> bool:
    """True when the document is a release package with an index page."""
    return any(
        line.strip().lower() in ("## included story cards", "## included updates")
        for line in markdown_lines or []
    )


@dataclass
class HandoffDocContext:
    card_id: str
    card_name: str
    card_url: str = ""
    release_name: str = ""
    approved_at: str = ""
    card_description: str = ""
    card_comments: list[str] = field(default_factory=list)
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
    comments = [c for c in (getattr(card, "comments", []) or []) if c]
    comments_text = "\n".join(comments)
    toggles = detect_toggles(desc, getattr(card, "name", "") or "", comments_text,
                             acceptance_criteria, test_cases)
    return HandoffDocContext(
        card_id=getattr(card, "id", ""),
        card_name=getattr(card, "name", ""),
        card_url=getattr(card, "url", "") or "",
        release_name=release_name,
        approved_at=approved_at,
        card_description=desc,
        card_comments=comments,
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
- `## Brief Description` — a short, crisp summary of what changed and why it matters
- Toggle / prerequisite section
- Where to find the feature in the app (use exact paths from APP NAVIGATION STRUCTURE or code context)
- Step-by-step walkthrough for support/demo team (use exact button/link names from code or AI QA evidence)
- Expected behaviour / what support should observe

The document ends after the expected-behaviour section.

DO NOT include any of the following sections:
- Developed by
- Tested by
- Feature Summary (use `## Brief Description` instead)
- Business-Safe Explanation / Merchant-Safe Explanation (any merchant-facing wording section)
- Common Questions / Troubleshooting (or any Q&A section)
- Support Escalation Packet
- Known Limitations / Rollout Notes
- References

Length: keep the whole document under 400 words. Support reads this during a call — every
sentence must tell them something they would otherwise have to ask engineering. Specifically:
- Brief Description: 2-4 sentences, one paragraph, no preamble.
- Toggle / Prerequisites: at most 4 rows or bullets.
- Walkthrough: at most 8 numbered steps in total, at most 2 scenarios, one line per step.
- Expected Behaviour: at most 4 distinct signals; do not restate the walkthrough.

Accuracy rules:
- Name a specific field, value, or setting ONLY if the card evidence names it. Never round out a
  list with plausible-sounding extras: if the card says dimensions are editable, write dimensions,
  not "weight, dimensions, and other fields".
- When a card's human QA Notes conflict with generated test-case scenarios in the comments, trust
  the QA Notes — generated scenarios can contain invented specifics.
- When the affected fields are not enumerable from the evidence, say "the fields the card makes
  editable" rather than guessing which ones.
- No filler: no "this section describes", no restating the card title, no closing summary.

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

### 🔍 Brief Description
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
        "LIVE TRELLO COMMENTS / QA NOTES:",
        ("\n\n".join(ctx.card_comments or []) or "None").strip()[:7000],
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

## Brief Description
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
"""


def _fallback_business_doc(ctx: HandoffDocContext) -> str:
    toggles = ", ".join(ctx.toggle_names) if ctx.toggle_names else "None detected"
    return f"""# Business Brief — {ctx.card_name}

## Value Statement
This change improves merchant workflow and support readiness for the feature.

## Brief Description
{(ctx.card_description or ctx.acceptance_criteria or 'Problem statement not available').strip()[:1800]}

## What Changed
{(ctx.acceptance_criteria or 'No acceptance criteria available').strip()[:2200]}

## Operational Notes
- Release: {ctx.release_name or 'Unknown'}
- Toggles: {toggles}

## Support / Rollout Impact
- Support team should use the support guide for demo and troubleshooting.
- Confirm toggle or rollout prerequisites before enabling for merchants.
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


def _register_fonts() -> tuple[str, str]:
    """Register Arial + Georgia TTF fonts. Returns (sans_family, serif_family)."""
    try:
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        from reportlab.pdfbase.pdfmetrics import registerFontFamily

        _SF = "/System/Library/Fonts/Supplemental/"
        pdfmetrics.registerFont(TTFont("Arial",           _SF + "Arial.ttf"))
        pdfmetrics.registerFont(TTFont("Arial-Bold",      _SF + "Arial Bold.ttf"))
        pdfmetrics.registerFont(TTFont("Arial-Italic",    _SF + "Arial Italic.ttf"))
        pdfmetrics.registerFont(TTFont("Arial-BoldItalic",_SF + "Arial Bold Italic.ttf"))
        registerFontFamily("Arial", normal="Arial", bold="Arial-Bold",
                           italic="Arial-Italic", boldItalic="Arial-BoldItalic")

        pdfmetrics.registerFont(TTFont("Georgia",           _SF + "Georgia.ttf"))
        pdfmetrics.registerFont(TTFont("Georgia-Bold",      _SF + "Georgia Bold.ttf"))
        pdfmetrics.registerFont(TTFont("Georgia-Italic",    _SF + "Georgia Italic.ttf"))
        pdfmetrics.registerFont(TTFont("Georgia-BoldItalic",_SF + "Georgia Bold Italic.ttf"))
        registerFontFamily("Georgia", normal="Georgia", bold="Georgia-Bold",
                           italic="Georgia-Italic", boldItalic="Georgia-BoldItalic")
        return "Arial", "Georgia"
    except Exception:
        return "Helvetica", "Times-Roman"


_EMOJI_RE = re.compile(
    "[\U0001F300-\U0001FFFF\U00002600-\U000027BF\U0000FE00-\U0000FE0F]+",
    flags=re.UNICODE,
)


def _strip_emoji(text: str) -> str:
    """Drop emoji — the embedded PDF fonts render them as blank boxes."""
    return _EMOJI_RE.sub("", text or "").strip()


def _md_to_rl(text: str, sans: str = "Arial") -> str:
    """Convert basic markdown inline formatting to ReportLab XML tags."""
    text = _strip_emoji(text)
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    # Markdown links [label](url) → clickable ReportLab anchors. Do this first so the
    # label/url (which never contain markdown emphasis) survive the asterisk handling.
    def _link(m):
        label, url = m.group(1), m.group(2)
        return f'<a href="{url}" color="#1155CC">{label}</a>'
    text = re.sub(r'\[([^\]]+)\]\(([^)\s]+)\)', _link, text)
    # Stash `code` spans before emphasis handling. A literal asterisk inside a
    # code span (for example `*.enabled`) must not be read as an italic marker —
    # otherwise emphasis pairs across two code spans and emits interleaved tags
    # that ReportLab rejects.
    code_spans: list[str] = []

    def _stash(m):
        code_spans.append(m.group(1))
        return f"\x00{len(code_spans) - 1}\x00"

    text = re.sub(r'`([^`]+)`', _stash, text)
    text = re.sub(r'\*\*\*(.+?)\*\*\*', r'<b><i>\1</i></b>', text)
    text = re.sub(r'\*\*(.+?)\*\*',     r'<b>\1</b>', text)
    text = re.sub(r'\*([^*\n]+?)\*',    r'<i>\1</i>', text)
    # Strip any unmatched asterisks left over (e.g. from BDD steps bleeding in)
    text = re.sub(r'\*+', '', text)
    for index, span in enumerate(code_spans):
        text = text.replace(f"\x00{index}\x00",
                            f'<font name="Courier" fontSize="9">{span}</font>')
    return text


# Brand line shown under the PDF title. Keep the handoff PDF styling identical
# across the MCSL / FedEx / AU Post repos — only this brand string differs.
PDF_BRAND = "PluginHive FedEx"


def _pdf_subtitle(title: str, markdown_text: str) -> str:
    """Brand + platform scope line for the PDF header panel."""
    return "  ·  ".join([PDF_BRAND, "Shopify"])


def _demote_markdown(markdown_text: str) -> str:
    """Nest a single-card document under a release-level package heading."""
    lines: list[str] = []
    for raw in (markdown_text or "").splitlines():
        line = raw.rstrip()
        if line.startswith("### "):
            lines.append("#### " + line[4:].strip())
        elif line.startswith("## "):
            lines.append("### " + line[3:].strip())
        elif line.startswith("# "):
            lines.append("## " + line[2:].strip())
        else:
            lines.append(line)
    return "\n".join(lines).strip()


def _story_id(ctx: HandoffDocContext) -> str:
    """Story/card number only, for the index page `Story ID` column."""
    name = ctx.card_name or ""
    story_id_match = re.search(r"\b([A-Z]{1,4}-\d{1,5})\b", name)
    if story_id_match:
        return story_id_match.group(1)
    leading_number = re.match(r"\s*#?(\d{1,6})\b", name)
    if leading_number:
        return leading_number.group(1)
    return ""


def _story_title(ctx: HandoffDocContext) -> str:
    """Card title for the `Story Title` column.

    Strips the StoryLab card-name boilerplate ("From SL: ZI-629 — ") so the
    column holds the title only; the id already has its own column.
    """
    title = (ctx.card_name or "").strip()
    title = re.sub(r"^from\s+sl\s*:\s*", "", title, flags=re.IGNORECASE).strip()
    story_id = _story_id(ctx)
    if story_id and title.startswith(story_id):
        title = title[len(story_id):].lstrip(" -–—:#")
    return title or "(untitled card)"


def _strip_leading_h1(markdown_text: str) -> str:
    """Drop a per-card document's own H1 title.

    Inside a combined release package the wrapper already prints
    "<Story ID> - <Story Title>", so the card's own "# Support Guide: ..."
    line would render as a duplicate heading.
    """
    lines = (markdown_text or "").lstrip().splitlines()
    if lines and lines[0].startswith("# "):
        lines = lines[1:]
    return "\n".join(lines).strip()


def _table_cell(value: str) -> str:
    return (value or "").replace("|", "\\|").replace("\n", " ").strip()


def _trello_link_cell(ctx: HandoffDocContext) -> str:
    """Markdown link for the index page `Trello card link` column."""
    url = (ctx.card_url or "").strip()
    if not url:
        return "-"
    label = _story_id(ctx) or "Card"
    return f"[{label}]({url})"


def _release_summary_table(contexts: list[HandoffDocContext]) -> str:
    rows = [
        "| Story ID | Story Title | Toggle Name | Trello card link |",
        "|---|---|---|---|",
    ]
    for ctx in contexts:
        toggles = ", ".join(ctx.toggle_names) if ctx.toggle_names else "None"
        rows.append(
            f"| {_table_cell(_story_id(ctx)) or '-'} | {_table_cell(_story_title(ctx))} "
            f"| {_table_cell(toggles)} | {_trello_link_cell(ctx)} |"
        )
    return "\n".join(rows)


def _card_section_heading(ctx: HandoffDocContext) -> str:
    """`<Story ID> - <Story Title>` heading, without repeating the id inside the title."""
    story_id = _story_id(ctx)
    story_title = _story_title(ctx)
    return f"{story_id} - {story_title}" if story_id else story_title


def generate_combined_support_guide(contexts: list[HandoffDocContext], release_name: str = "") -> str:
    """Generate one release-level Support Guide containing all selected cards."""
    contexts = [ctx for ctx in contexts if ctx]
    release = release_name or (contexts[0].release_name if contexts else "") or "FedEx Release"
    parts = [
        f"# {release} Support Guide",
        "",
        "## Included Story Cards",
        _release_summary_table(contexts),
    ]
    for ctx in contexts:
        parts.extend([
            "",
            f"## {_card_section_heading(ctx)}",
            _demote_markdown(_strip_leading_h1(generate_support_guide(ctx))),
        ])
    return "\n".join(part for part in parts if part is not None).strip()


def render_pdf_bytes(title: str, markdown_text: str) -> bytes:
    try:
        from reportlab.lib.colors import HexColor
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.lib.units import inch
        from reportlab.platypus import (
            HRFlowable, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
        )
    except ModuleNotFoundError as exc:
        raise RuntimeError("PDF rendering requires reportlab to be installed") from exc

    SANS, SERIF = _register_fonts()

    PAGE_W, PAGE_H = A4
    LM = RM = 0.7 * inch
    CW = PAGE_W - LM - RM

    # ── Professional navy / gold colour palette ──────────────────────────────
    C_NAVY      = HexColor("#0d1b3e")   # header background — deep navy
    C_NAVY_MID  = HexColor("#162447")   # header body rows
    C_NAVY_META = HexColor("#1a2f5e")   # metadata strip
    C_GOLD      = HexColor("#c9922a")   # badge label & subtitle — warm gold
    C_BLUE      = HexColor("#1d4ed8")   # section headings — royal blue
    C_ACCENT    = HexColor("#2563eb")   # left accent bar
    C_WHITE     = HexColor("#ffffff")
    C_HDR_DESC  = HexColor("#cbd5e1")   # header description text
    C_META_TXT  = HexColor("#94a3b8")   # metadata strip text
    C_TEXT      = HexColor("#1e293b")   # body text — rich charcoal
    C_GRAY      = HexColor("#475569")   # secondary / quote text
    C_BORDER    = HexColor("#e2e8f0")   # dividers & table borders

    def _ps(name, **kw):
        return ParagraphStyle(name, **kw)

    # Fonts: Georgia for the big title impact, Arial everywhere else
    hdr_badge  = _ps("HBadge", fontName=f"{SANS}-Bold",   fontSize=8.5, leading=11, textColor=C_GOLD,
                               spaceAfter=2, tracking=60)
    hdr_title  = _ps("HTitle", fontName=f"{SERIF}-Bold",  fontSize=26,  leading=32, textColor=C_WHITE,
                               spaceAfter=4)
    hdr_sub    = _ps("HSub",   fontName=f"{SANS}-Bold",   fontSize=10.5,leading=14, textColor=C_GOLD,
                               spaceAfter=0)
    hdr_desc   = _ps("HDesc",  fontName=f"{SANS}-Italic", fontSize=10,  leading=14, textColor=C_HDR_DESC)
    hdr_meta   = _ps("HMeta",  fontName=SANS,             fontSize=8.5, leading=12, textColor=C_META_TXT)
    h2_style   = _ps("H2",     fontName=f"{SANS}-Bold",   fontSize=12,  leading=16, textColor=C_BLUE,
                               spaceBefore=12, spaceAfter=2)
    h2_box_style = _ps("H2Box", fontName=f"{SANS}-Bold",  fontSize=12,  leading=16, textColor=C_BLUE,
                               spaceBefore=0, spaceAfter=0)
    h3_style   = _ps("H3",     fontName=f"{SANS}-BoldItalic", fontSize=11, leading=14, textColor=C_BLUE,
                               spaceBefore=8, spaceAfter=3)
    body_style = _ps("Body",   fontName=SANS,             fontSize=10.5, leading=16, textColor=C_TEXT,
                               spaceAfter=6)
    bullet_sty = _ps("Bullet", fontName=SANS,             fontSize=10.5, leading=16, textColor=C_TEXT,
                               spaceAfter=4, leftIndent=16)
    num_style  = _ps("Num",    fontName=SANS,             fontSize=10.5, leading=16, textColor=C_TEXT,
                               spaceAfter=4, leftIndent=18)
    quote_sty  = _ps("Quote",  fontName=f"{SERIF}-Italic",fontSize=10.5, leading=16, textColor=C_GRAY,
                               leftIndent=20, rightIndent=20, spaceAfter=8,
                               borderPadding=(6, 10, 6, 14),
                               borderColor=C_GOLD, borderWidth=0)

    # ── H2 rendered as a full-width heading box ─────────────────────────────
    C_BOX_BG     = HexColor("#f7f9ff")   # heading box fill — very light blue
    C_BOX_BORDER = HexColor("#dbe4f7")   # heading box border

    def _h2_row(text: str):
        p = Paragraph(_md_to_rl(text), h2_box_style)
        row = Table([[p]], colWidths=[CW])
        row.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (-1, -1), C_BOX_BG),
            ("BOX",           (0, 0), (-1, -1), 0.8, C_BOX_BORDER),
            ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING",    (0, 0), (-1, -1), 11),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 11),
            ("LEFTPADDING",   (0, 0), (-1, -1), 16),
            ("RIGHTPADDING",  (0, 0), (-1, -1), 16),
        ]))
        return [Spacer(1, 0.10 * inch), row, Spacer(1, 0.09 * inch)]

    # ── Badge / subtitle detection ───────────────────────────────────────────
    tl = title.lower()
    if any(w in tl for w in ["delay", "fix", "bug", "error", "performance", "slow", "issue"]):
        badge_txt = "PERFORMANCE FIX"
    elif any(w in tl for w in ["new", "feature", "add", "introduc", "launch"]):
        badge_txt = "NEW FEATURE"
    else:
        badge_txt = "UPDATE"

    clean_title = re.sub(r'\[#\d+\]', '', title).strip()
    clean_title = re.sub(r'From SL:\s*[A-Z]+-\d+\s*[—–-]\s*', '', clean_title).strip()

    subtitle = _pdf_subtitle(title, markdown_text)

    # ── Parse markdown ───────────────────────────────────────────────────────
    lines = (markdown_text or "").splitlines()
    content_lines: list[str] = []
    desc_text = ""
    skip_h1 = True
    for line in lines:
        if skip_h1 and line.startswith("# "):
            skip_h1 = False
            continue
        content_lines.append(line)
        if not desc_text:
            s = line.strip()
            if s and not s.startswith("#") and not s.startswith("-"):
                desc_text = s[:170] + ("…" if len(s) > 170 else "")

    # ── Canvas footer ────────────────────────────────────────────────────────
    buf = io.BytesIO()

    def _draw_footer(canvas_obj, doc):
        canvas_obj.saveState()
        # Thin gold rule above footer
        canvas_obj.setStrokeColor(C_GOLD)
        canvas_obj.setLineWidth(0.5)
        canvas_obj.line(LM, 26, PAGE_W - RM, 26)
        canvas_obj.setFillColor(C_GRAY)
        canvas_obj.setFont(SANS, 7.5)
        canvas_obj.drawString(LM, 12, f"Generated {_dt.datetime.now().strftime('%B %d, %Y')}  ·  Confidential — PluginHive")
        canvas_obj.drawCentredString(PAGE_W / 2, 12, f"Page {doc.page}")
        canvas_obj.drawRightString(PAGE_W - RM, 12, "pluginhive.com")
        canvas_obj.restoreState()

    doc_obj = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=LM, rightMargin=RM,
        topMargin=0.4 * inch, bottomMargin=0.5 * inch,
        title=title,
    )

    story: list = []

    # ── Header panel (deep navy) ─────────────────────────────────────────────
    badge_p = Paragraph(badge_txt, hdr_badge)
    title_p = Paragraph(clean_title, hdr_title)
    sub_p   = Paragraph(subtitle, hdr_sub)
    desc_p  = Paragraph(_md_to_rl(desc_text), hdr_desc) if desc_text else Spacer(1, 2)

    hdr_tbl = Table([[badge_p], [title_p], [sub_p], [desc_p]], colWidths=[CW])
    hdr_tbl.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), C_NAVY_MID),
        ("BACKGROUND",    (0, 0), (0, 0),   C_NAVY),
        ("TOPPADDING",    (0, 0), (0, 0), 18),
        ("BOTTOMPADDING", (0, 0), (0, 0),  4),
        ("TOPPADDING",    (0, 1), (0, 1),  4),
        ("BOTTOMPADDING", (0, 1), (0, 1),  6),
        ("TOPPADDING",    (0, 2), (0, 2),  2),
        ("BOTTOMPADDING", (0, 2), (0, 2),  8),
        ("TOPPADDING",    (0, 3), (0, 3),  2),
        ("BOTTOMPADDING", (0, 3), (0, 3), 18),
        ("LEFTPADDING",   (0, 0), (-1, -1), 22),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 22),
    ]))

    # Gold top-border accent line on header
    hdr_border = Table([[""]], colWidths=[CW], rowHeights=[3])
    hdr_border.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), C_GOLD),
        ("TOPPADDING",    (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ("LEFTPADDING",   (0, 0), (-1, -1), 0),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 0),
    ]))

    meta_txt = (
        f"Generated {_dt.datetime.now().strftime('%B %Y')}     ·     "
        f"PluginHive QA Team"
    )
    meta_tbl = Table([[Paragraph(meta_txt, hdr_meta)]], colWidths=[CW])
    meta_tbl.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), C_NAVY_META),
        ("TOPPADDING",    (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("LEFTPADDING",   (0, 0), (-1, -1), 22),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 22),
    ]))

    story += [hdr_border, hdr_tbl, meta_tbl, Spacer(1, 0.25 * inch)]

    # ── Styles for tables and checkboxes ────────────────────────────────────
    tbl_hdr  = _ps("TblHdr",  fontName=f"{SANS}-Bold", fontSize=9,   leading=12,
                               textColor=C_WHITE)
    tbl_cell = _ps("TblCell", fontName=SANS,            fontSize=9,   leading=13,
                               textColor=C_TEXT)
    tbl_cell_sm = _ps("TblSm", fontName=SANS,           fontSize=8.5, leading=12,
                               textColor=C_TEXT)
    chk_sty  = _ps("Chk",     fontName=SANS,            fontSize=10.5, leading=16,
                               textColor=C_TEXT, spaceAfter=3, leftIndent=16)
    node_sty = _ps("NodeCallout", fontName=f"{SANS}-Bold", fontSize=10, leading=14,
                               textColor=HexColor("#1e3a8a"), spaceAfter=0)
    code_sty = _ps("Code",    fontName="Courier",        fontSize=8.5, leading=12,
                               textColor=C_TEXT)
    note_sty = _ps("Note",    fontName=SANS,             fontSize=10,  leading=14,
                               textColor=C_TEXT)

    def _code_block(code_lines: list[str]):
        """Fenced ``` block → monospace box."""
        body = "<br/>".join(
            (ln.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
               .replace(" ", "&nbsp;")) or "&nbsp;"
            for ln in code_lines
        )
        tbl = Table([[Paragraph(body, code_sty)]], colWidths=[CW])
        tbl.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (-1, -1), HexColor("#f1f5f9")),
            ("BOX",           (0, 0), (-1, -1), 0.5, C_BORDER),
            ("LEFTPADDING",   (0, 0), (-1, -1), 10),
            ("RIGHTPADDING",  (0, 0), (-1, -1), 10),
            ("TOPPADDING",    (0, 0), (-1, -1), 8),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ]))
        return tbl

    def _callout(quote_lines: list[str]):
        """Blockquote → note box; gold tint when it reads as a warning/QA note."""
        joined = " ".join(quote_lines).lower()
        warn = any(kw in joined for kw in ("warning", "caution", "qa note", "confirm"))
        body = "<br/>".join(_md_to_rl(ln) if ln.strip() else "&nbsp;" for ln in quote_lines)
        tbl = Table([[Paragraph(body, note_sty)]], colWidths=[CW])
        tbl.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (-1, -1), HexColor("#fefce8") if warn else HexColor("#f1f5f9")),
            ("LINEBEFORE",    (0, 0), (0, -1),  3, C_GOLD if warn else C_ACCENT),
            ("LEFTPADDING",   (0, 0), (-1, -1), 12),
            ("RIGHTPADDING",  (0, 0), (-1, -1), 12),
            ("TOPPADDING",    (0, 0), (-1, -1), 9),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
        ]))
        return tbl

    def _flush_table(raw_rows: list[str]) -> None:
        """Parse buffered markdown table lines and append a styled ReportLab Table."""
        parsed: list[list[str]] = []
        for r in raw_rows:
            if re.match(r"^\|[-| :]+\|$", r.strip()):
                continue  # separator row
            cells = [c.strip() for c in r.strip().strip("|").split("|")]
            parsed.append(cells)
        if not parsed:
            return
        n_cols = max(len(r) for r in parsed)
        # Normalise column count
        parsed = [r + [""] * (n_cols - len(r)) for r in parsed]
        # Auto column widths: first col narrower, last col narrower for status cols
        header_cells = [c.lower() for c in parsed[0]]
        story_id_first = "story id" in header_cells[0]
        if n_cols == 4 and story_id_first:
            # Release index page: Story ID | Story Title | Toggle Name | Trello card link
            col_ws = [0.14 * CW, 0.39 * CW, 0.27 * CW, 0.20 * CW]
        elif n_cols == 3 and story_id_first:
            # Release index page without a toggle column
            col_ws = [0.14 * CW, 0.51 * CW, 0.35 * CW]
        elif n_cols == 3:
            col_ws = [0.06 * CW, 0.56 * CW, 0.38 * CW]
        elif n_cols == 2:
            col_ws = [0.32 * CW, 0.68 * CW]
        else:
            unit = CW / n_cols
            col_ws = [unit] * n_cols
        # Build cell paragraphs
        tbl_data: list[list] = []
        for ri, row in enumerate(parsed):
            style = tbl_hdr if ri == 0 else tbl_cell_sm
            tbl_data.append([Paragraph(_md_to_rl(cell), style) for cell in row])
        rl_tbl = Table(tbl_data, colWidths=col_ws, repeatRows=1)
        ts = TableStyle([
            ("BACKGROUND",    (0, 0), (-1, 0),   C_NAVY),
            ("TEXTCOLOR",     (0, 0), (-1, 0),   C_WHITE),
            ("FONTNAME",      (0, 0), (-1, 0),   f"{SANS}-Bold"),
            ("ROWBACKGROUNDS",(0, 1), (-1, -1),  [C_WHITE, HexColor("#f1f5f9")]),
            ("GRID",          (0, 0), (-1, -1),  0.4, C_BORDER),
            ("TOPPADDING",    (0, 0), (-1, -1),  5),
            ("BOTTOMPADDING", (0, 0), (-1, -1),  5),
            ("LEFTPADDING",   (0, 0), (-1, -1),  7),
            ("RIGHTPADDING",  (0, 0), (-1, -1),  7),
            ("VALIGN",        (0, 0), (-1, -1),  "TOP"),
        ])
        rl_tbl.setStyle(ts)
        story.append(rl_tbl)
        story.append(Spacer(1, 0.1 * inch))

    # ── Render content (with table buffering) ────────────────────────────────
    table_buf: list[str] = []
    seen_card_marker = False
    seen_page_h1 = False
    seen_card_section = False
    combined_package = is_combined_package(content_lines)

    def _maybe_flush():
        if table_buf:
            _flush_table(list(table_buf))
            table_buf.clear()

    idx = 0
    while idx < len(content_lines):
        line = content_lines[idx]
        idx += 1
        clean = line.strip()

        # Fenced code block
        if clean.startswith("```"):
            _maybe_flush()
            code_lines: list[str] = []
            while idx < len(content_lines) and not content_lines[idx].strip().startswith("```"):
                code_lines.append(content_lines[idx])
                idx += 1
            idx += 1  # closing fence
            if code_lines:
                story.append(_code_block(code_lines))
                story.append(Spacer(1, 0.08 * inch))
            continue

        # Blockquote / callout block
        if clean.startswith(">"):
            _maybe_flush()
            quote_lines = [re.sub(r"^>\s?", "", clean)]
            while idx < len(content_lines) and content_lines[idx].strip().startswith(">"):
                quote_lines.append(re.sub(r"^>\s?", "", content_lines[idx].strip()))
                idx += 1
            story.append(_callout(quote_lines))
            story.append(Spacer(1, 0.08 * inch))
            continue

        # Table row detection
        if clean.startswith("|"):
            table_buf.append(clean)
            continue
        else:
            _maybe_flush()

        if not clean:
            story.append(Spacer(1, 0.05 * inch))
            continue
        if re.fullmatch(r"(-{3,}|\*{3,}|_{3,})", clean):
            story.append(HRFlowable(width=CW, thickness=0.5, color=C_BORDER,
                                    spaceBefore=4, spaceAfter=6))
            continue
        if re.match(r"^CARD\s+\d+/\d+$", clean, flags=re.IGNORECASE):
            if seen_card_marker:
                story.append(PageBreak())
            seen_card_marker = True
            story.append(Paragraph(_md_to_rl(clean), body_style))
            continue
        if clean.startswith("# ") and not clean.startswith("## "):
            # A later H1 starts a new document section — give it its own page.
            if seen_page_h1:
                story.append(PageBreak())
            seen_page_h1 = True
            story.extend(_h2_row(clean[2:].strip()))
        elif clean.startswith("## "):
            heading = clean[3:].strip()
            # Every story card starts on its own page — including the first, so the
            # index page stands alone and no card begins halfway down another page.
            if is_card_section_heading(heading, combined_package):
                story.append(PageBreak())
                seen_card_section = True
            story.extend(_h2_row(heading))
        elif clean.startswith("### "):
            story.append(Paragraph(_md_to_rl(clean[4:].strip()), h3_style))
        elif re.match(r"^- \[[ xX]\]", clean):
            # Checkbox bullet: - [ ] or - [x]
            checked = bool(re.match(r"^- \[[xX]\]", clean))
            raw_text = re.sub(r"^- \[[ xX]\]\s*", "", clean)
            # Strip any leftover ** / * that _md_to_rl couldn't pair-match
            raw_text = re.sub(r"\*+", "", raw_text)
            text = _md_to_rl(raw_text)
            if checked:
                icon = f'<font color="#16a34a" fontName="{SANS}-Bold" fontSize="13">✓</font>'
            else:
                icon = f'<font color="#1d4ed8" fontName="{SANS}-Bold" fontSize="11">✦</font>'
            story.append(Paragraph(f"{icon}  {text}", chk_sty))
        elif is_request_log_callout(clean):
            text = re.sub(r"^[-*]\s*", "", clean).strip()
            node_tbl = Table([[Paragraph(_md_to_rl(text), node_sty)]], colWidths=[CW])
            node_tbl.setStyle(TableStyle([
                ("BACKGROUND",    (0, 0), (-1, -1), HexColor("#dbeafe")),
                ("BOX",           (0, 0), (-1, -1), 0.7, HexColor("#2563eb")),
                ("LEFTPADDING",   (0, 0), (-1, -1), 10),
                ("RIGHTPADDING",  (0, 0), (-1, -1), 10),
                ("TOPPADDING",    (0, 0), (-1, -1), 7),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ]))
            story.append(node_tbl)
            story.append(Spacer(1, 0.08 * inch))
        elif clean.startswith("- ") or clean.startswith("* "):
            text = _md_to_rl(clean[2:].strip())
            story.append(Paragraph(
                f'<font color="#c9922a" fontName="{SANS}-Bold">›</font>  {text}', bullet_sty,
            ))
        elif re.match(r"^\d+\.\s+", clean):
            m = re.match(r"^(\d+)\.\s+(.*)", clean)
            if m:
                n, cnt = m.group(1), _md_to_rl(m.group(2))
                story.append(Paragraph(
                    f'<font color="#1d4ed8" fontName="{SANS}-Bold">{n}.</font>  {cnt}', num_style,
                ))
        elif clean.startswith('"') or clean.startswith('\u201c'):
            q_tbl = Table([[Paragraph(_md_to_rl(clean), quote_sty)]], colWidths=[CW])
            q_tbl.setStyle(TableStyle([
                ("BACKGROUND",   (0, 0), (-1, -1), HexColor("#fefce8")),
                ("LINEAFTER",    (0, 0), (0, -1),  3, C_GOLD),
                ("LINEBEFORE",   (0, 0), (0, -1),  3, C_GOLD),
                ("TOPPADDING",   (0, 0), (-1, -1), 10),
                ("BOTTOMPADDING",(0, 0), (-1, -1), 10),
                ("LEFTPADDING",  (0, 0), (-1, -1), 14),
                ("RIGHTPADDING", (0, 0), (-1, -1), 14),
            ]))
            story.append(q_tbl)
            story.append(Spacer(1, 0.06 * inch))
        else:
            story.append(Paragraph(_md_to_rl(clean), body_style))

    _maybe_flush()
    story.append(Spacer(1, 0.3 * inch))
    doc_obj.build(story, onFirstPage=_draw_footer, onLaterPages=_draw_footer)
    return buf.getvalue()
