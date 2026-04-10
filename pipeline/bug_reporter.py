"""
Bug Reporter  —  QA → Developer notification pipeline
=======================================================
When QA finds a bug (manually via Ask Domain Expert, or automatically
via Smart AC Verifier), this module:

  1. Looks at the bug description + code RAG → locates the likely file/function
  2. Gets card members from Trello → filters out QA team → finds developer(s)
  3. Searches Slack for the dev's name → gets their user ID
  4. Sends a DM to the dev with full bug context

QA team list (anyone in this list is NOT a developer):
  Anuja B, Arshiya Sayed, Ashok Kumar N, Basavaraj,
  Inderbir Singh, Keerthanaa Elangovan, Madan Kumar AS,
  Preethi K K, Shahitha S
"""
from __future__ import annotations
import logging
import os
import re
from textwrap import dedent

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage

import config

logger = logging.getLogger(__name__)

# ── QA team — these are NOT developers ───────────────────────────────────────
# Full names (lowercase for matching)
_QA_NAMES: set[str] = {
    "anuja b",
    "arshiya sayed",
    "ashok kumar n",
    "basavaraj",
    "inderbir singh",
    "keerthanaa elangovan",
    "madan kumar as",
    "preethi k k",
    "shahitha s",
}


def _is_qa(full_name: str) -> bool:
    """Return True if the full name matches a known QA team member."""
    name = full_name.strip().lower()
    # exact match or starts-with (handles "Madan Kumar AS (you)")
    return any(
        name == qa or name.startswith(qa) or qa.startswith(name)
        for qa in _QA_NAMES
    )


# ── Code RAG bug localiser ────────────────────────────────────────────────────

_LOCATE_PROMPT = dedent("""\
    You are a senior engineer analysing a bug report from the FedEx Shopify App.

    BUG DESCRIPTION:
    {bug_description}

    CARD: {card_name}

    CODE CONTEXT (backend + frontend + automation):
    {code_context}

    Based on the bug description and code context above, identify:
    1. Which type of code is likely affected: "backend" | "frontend" | "config" | "unknown"
    2. The most likely file path or module name (if visible in context)
    3. The specific function/component/endpoint (if identifiable)
    4. A concise technical explanation of what is wrong in the code

    Respond ONLY in JSON:
    {{
      "code_layer":   "backend" | "frontend" | "config" | "unknown",
      "file_hint":    "path/to/file.ts  or  empty string if unknown",
      "function_hint":"functionName  or  empty string if unknown",
      "technical_explanation": "one or two sentences — what exactly is wrong in the code"
    }}
""")


def locate_bug_in_code(bug_description: str, card_name: str) -> dict:
    """
    Query code RAG to identify which layer/file/function the bug lives in.

    Returns dict with keys:
      code_layer, file_hint, function_hint, technical_explanation
    """
    ctx_parts: list[str] = []
    query = f"{card_name} {bug_description}"

    try:
        from rag.code_indexer import search_code
        for stype, label in [("backend", "Backend"), ("frontend", "Frontend"),
                              ("automation", "Automation")]:
            docs = search_code(query, k=3, source_type=stype)
            if docs:
                snippets = "\n---\n".join(
                    f"[{d.metadata.get('file_path','?')}]\n{d.page_content[:400]}"
                    for d in docs
                )
                ctx_parts.append(f"=== {label} ===\n{snippets}")
    except Exception as e:
        logger.debug("Code RAG query failed: %s", e)

    code_context = "\n\n".join(ctx_parts) if ctx_parts else "(no code indexed)"

    try:
        claude = ChatAnthropic(
            model=config.CLAUDE_HAIKU_MODEL,
            api_key=config.ANTHROPIC_API_KEY,
            temperature=0,
            max_tokens=512,
        )
        resp = claude.invoke([HumanMessage(content=_LOCATE_PROMPT.format(
            bug_description=bug_description[:800],
            card_name=card_name,
            code_context=code_context[:3000],
        ))])
        raw = resp.content.strip()
        clean = re.sub(r"```(?:json)?\n?", "", raw).strip().rstrip("`")
        import json
        return json.loads(clean)
    except Exception as e:
        logger.warning("Bug location analysis failed: %s", e)
        return {
            "code_layer": "unknown",
            "file_hint": "",
            "function_hint": "",
            "technical_explanation": bug_description,
        }


# ── Dev detector from Trello card ────────────────────────────────────────────

def get_card_devs(card_id: str) -> list[dict]:
    """
    Get Trello card members, filter out QA, return developer(s).
    Each dict: {"fullName": str, "username": str, "id": str}
    """
    try:
        from pipeline.trello_client import TrelloClient
        client = TrelloClient()
        members = client.get_card_members(card_id)
        devs = [m for m in members if not _is_qa(m.get("fullName", ""))]
        logger.info(
            "Card %s members: %d total, %d devs after QA filter",
            card_id, len(members), len(devs),
        )
        return devs
    except Exception as e:
        logger.warning("Could not get card devs: %s", e)
        return []


# ── Slack DM to developer ─────────────────────────────────────────────────────

def _format_bug_dm(
    card_name: str,
    card_url: str,
    bug_description: str,
    location: dict,
    scenario: str,
    qa_name: str,
    verification_steps: list[str],
) -> str:
    """Build the DM text to send to the developer."""
    layer_emoji = {
        "backend": "🖥️ Backend",
        "frontend": "🌐 Frontend",
        "config": "⚙️ Config",
        "unknown": "❓ Unknown layer",
    }.get(location.get("code_layer", "unknown"), "❓")

    file_hint    = location.get("file_hint", "")
    fn_hint      = location.get("function_hint", "")
    tech_explain = location.get("technical_explanation", bug_description)

    lines = [
        f"🐛 *Bug Found During QA — {card_name}*",
        f"Card: {card_url}" if card_url else "",
        "",
        f"*Scenario being tested:*\n> {scenario}",
        "",
        f"*What QA observed:*\n{bug_description}",
        "",
        f"*Code analysis:*",
        f"  Layer: {layer_emoji}",
    ]
    if file_hint:
        lines.append(f"  File: `{file_hint}`")
    if fn_hint:
        lines.append(f"  Function/Component: `{fn_hint}`")
    lines.append(f"  Issue: {tech_explain}")

    if verification_steps:
        lines.append("")
        lines.append("*Steps to reproduce:*")
        for step in verification_steps[:5]:
            lines.append(f"  • {step}")

    lines += [
        "",
        f"_Reported by QA: {qa_name}_",
        "_Please review and fix before release sign-off._",
    ]
    return "\n".join(l for l in lines if l is not None)


def notify_devs_of_bug(
    card_id: str,
    card_name: str,
    card_url: str,
    bug_description: str,
    scenario: str = "",
    qa_name: str = "QA Team",
    verification_steps: list[str] | None = None,
    location: dict | None = None,
) -> dict:
    """
    Full bug notification pipeline:
      1. Locate bug in code (if location not already provided)
      2. Get devs from Trello card members
      3. Search Slack for each dev
      4. Send DM

    Returns:
      {"ok": bool, "sent_to": [dev_names], "failed": [dev_names], "error": str,
       "location": dict, "devs_found": int}
    """
    from pipeline.slack_client import SlackClient, search_slack_users

    # Step 1 — locate bug
    if location is None:
        location = locate_bug_in_code(bug_description, card_name)
    logger.info("Bug location: %s", location)

    # Step 2 — get devs from Trello
    devs = get_card_devs(card_id)
    if not devs:
        logger.warning("No developers found on card %s — no DMs sent", card_id)
        return {
            "ok": False,
            "sent_to": [],
            "failed": [],
            "error": (
                "No developers found on this card. "
                "Make sure developers are assigned as card members in Trello."
            ),
            "location": location,
            "devs_found": 0,
        }

    # Step 3 & 4 — find Slack user + send DM
    dm_text = _format_bug_dm(
        card_name=card_name,
        card_url=card_url,
        bug_description=bug_description,
        location=location,
        scenario=scenario,
        qa_name=qa_name,
        verification_steps=verification_steps or [],
    )

    token = os.getenv("SLACK_BOT_TOKEN", "").strip()
    if not token:
        return {
            "ok": False,
            "sent_to": [],
            "failed": [d["fullName"] for d in devs],
            "error": "SLACK_BOT_TOKEN not set — cannot send DMs",
            "location": location,
            "devs_found": len(devs),
        }

    slack = SlackClient(token=token, channel="dm-only")
    sent_to: list[str] = []
    failed:  list[str] = []

    for dev in devs:
        dev_name = dev.get("fullName") or dev.get("username", "Unknown")
        # Search Slack by first name for best match
        first_name = dev_name.split()[0] if dev_name.split() else dev_name
        try:
            users, err = search_slack_users(first_name)
            if err or not users:
                # Try full name
                users, err = search_slack_users(dev_name)
            if not users:
                logger.warning("Could not find Slack user for dev: %s", dev_name)
                failed.append(dev_name)
                continue

            # Take best match — first result
            slack_user = users[0]
            slack.send_dm(user_id=slack_user["id"], text=dm_text)
            sent_to.append(f"{dev_name} (@{slack_user['display_name']})")
            logger.info("Bug DM sent to dev %s (Slack: %s)", dev_name, slack_user["id"])

        except Exception as e:
            logger.warning("DM to dev %s failed: %s", dev_name, e)
            failed.append(dev_name)

    return {
        "ok": len(sent_to) > 0,
        "sent_to": sent_to,
        "failed": failed,
        "error": f"Failed to reach: {', '.join(failed)}" if failed else "",
        "location": location,
        "devs_found": len(devs),
    }


# ── Domain Expert Q&A with web fallback ──────────────────────────────────────

_DOMAIN_EXPERT_PROMPT = dedent("""\
    You are a domain expert for the FedEx Shopify App (PluginHive).
    A QA engineer is testing a feature and has a question.

    CARD BEING TESTED: {card_name}
    CARD DESCRIPTION / AC:
    {card_desc}

    KNOWLEDGE BASE CONTEXT:
    {rag_context}

    CODE CONTEXT (backend + frontend):
    {code_context}

    QA QUESTION: {question}

    Answer clearly and specifically. If the answer involves code behaviour,
    reference the actual API endpoint or component from the context.
    If you are not confident, say so explicitly — do NOT guess.

    Also at the end, on a new line, output one of:
      VERDICT: answered
      VERDICT: unsure — needs web research
      VERDICT: bug_possible — this sounds like a code issue
""")

_WEB_RESEARCH_PROMPT = dedent("""\
    You are a FedEx Shopify App expert. A QA engineer asked:
    "{question}"

    Web search results:
    {web_results}

    Based on the web results, answer the QA engineer's question clearly and concisely.
    Focus on FedEx shipping + Shopify app behaviour.
""")


def ask_domain_expert(
    question: str,
    card_name: str,
    card_desc: str = "",
    history: "list[dict] | None" = None,
) -> dict:
    """
    Answer a QA question using:
      1. QA knowledge RAG (FedEx docs)
      2. Code RAG (backend + frontend)
      3. Web search fallback if unsure

    Returns:
      {"answer": str, "verdict": str, "sources": list[str],
       "web_searched": bool, "bug_possible": bool}
    """
    # Build RAG context
    rag_ctx = ""
    try:
        from rag.vectorstore import search
        docs = search(question + " " + card_name, k=5)
        if docs:
            rag_ctx = "\n---\n".join(d.page_content[:400] for d in docs)
    except Exception as e:
        logger.debug("QA RAG error: %s", e)

    code_ctx = ""
    try:
        from rag.code_indexer import search_code
        parts = []
        for stype in ("backend", "frontend"):
            docs = search_code(question + " " + card_name, k=3, source_type=stype)
            if docs:
                parts.append(
                    "\n---\n".join(
                        f"[{d.metadata.get('file_path','?')}]\n{d.page_content[:350]}"
                        for d in docs
                    )
                )
        code_ctx = "\n\n".join(parts)
    except Exception as e:
        logger.debug("Code RAG error: %s", e)

    # First pass — answer from knowledge
    claude = ChatAnthropic(
        model=config.CLAUDE_SONNET_MODEL,
        api_key=config.ANTHROPIC_API_KEY,
        temperature=0.1,
        max_tokens=1024,
    )

    prompt = _DOMAIN_EXPERT_PROMPT.format(
        card_name=card_name,
        card_desc=(card_desc or "")[:800],
        rag_context=rag_ctx[:2000] or "(not indexed yet)",
        code_context=code_ctx[:2000] or "(not indexed yet)",
        question=question,
    )
    resp = claude.invoke([HumanMessage(content=prompt)])
    raw_answer = resp.content.strip()

    # Parse verdict from end of answer
    verdict = "answered"
    bug_possible = False
    answer_lines = raw_answer.splitlines()
    clean_lines = []
    for line in answer_lines:
        stripped = line.strip()
        if stripped.startswith("VERDICT:"):
            v = stripped.replace("VERDICT:", "").strip().lower()
            if "bug_possible" in v:
                verdict = "bug_possible"
                bug_possible = True
            elif "unsure" in v or "web" in v:
                verdict = "unsure"
        else:
            clean_lines.append(line)
    answer = "\n".join(clean_lines).strip()

    web_searched = False

    # Web fallback when unsure
    if verdict == "unsure":
        try:
            import subprocess, sys
            search_query = f"FedEx Shopify App {question}"
            # Use Python's urllib for simple DuckDuckGo instant-answer fetch
            import urllib.request, urllib.parse, json as _json
            encoded = urllib.parse.quote(search_query)
            url = f"https://api.duckduckgo.com/?q={encoded}&format=json&no_redirect=1"
            with urllib.request.urlopen(url, timeout=8) as r:
                data = _json.loads(r.read().decode())
            web_text = data.get("AbstractText") or data.get("Answer") or ""
            related = [t.get("Text", "") for t in data.get("RelatedTopics", [])[:3]]
            web_results = web_text + "\n" + "\n".join(related)
            web_results = web_results.strip()

            if web_results:
                web_resp = claude.invoke([HumanMessage(content=_WEB_RESEARCH_PROMPT.format(
                    question=question,
                    web_results=web_results[:2000],
                ))])
                answer = web_resp.content.strip()
                web_searched = True
                verdict = "answered"
        except Exception as e:
            logger.debug("Web search fallback failed: %s", e)

    return {
        "answer": answer,
        "verdict": verdict,
        "web_searched": web_searched,
        "bug_possible": bug_possible,
        "rag_used": bool(rag_ctx),
        "code_used": bool(code_ctx),
    }
