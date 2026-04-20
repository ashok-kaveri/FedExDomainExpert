"""
Requirement research helper for User Story / AC generation.

Combines local RAG with best-effort public web research so product requests
include official FedEx constraints first, then PluginHive/app behaviour.
"""
from __future__ import annotations

import logging
import re
import urllib.parse
from html import unescape

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

_FEDEX_OFFICIAL_DOMAINS = (
    "developer.fedex.com",
    "fedex.com",
)

_PLUGINHIVE_DOMAINS = ("pluginhive.com",)
_BACKLOG_LIST_NAME = "backlog"


def _clean_text(text: str, limit: int = 500) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    return text[:limit]


def _local_research(query: str) -> str:
    """Prefer official FedEx RAG, then PluginHive/app implementation knowledge."""
    try:
        from rag.vectorstore import search_filtered

        fedex_sections: list[str] = []
        pluginhive_sections: list[str] = []

        for source_type, bucket in (
            ("fedex_rest", fedex_sections),
            ("pluginhive_seeds", pluginhive_sections),
            ("pluginhive_docs", pluginhive_sections),
        ):
            docs = search_filtered(query, k=3, source_type=source_type)
            for doc in docs[:2]:
                url = (
                    doc.metadata.get("source_url")
                    or doc.metadata.get("source")
                    or source_type
                )
                bucket.append(
                    f"- [{source_type}] {url}\n  {_clean_text(doc.page_content, 600)}"
                )

        sections: list[str] = []
        if fedex_sections:
            sections.append("Official FedEx findings from local RAG:\n" + "\n".join(fedex_sections[:3]))
        if pluginhive_sections:
            sections.append("PluginHive / app behaviour findings from local RAG:\n" + "\n".join(pluginhive_sections[:4]))
        return "\n\n".join(sections)
    except Exception as exc:
        logger.debug("Local requirement research skipped: %s", exc)
    return ""


def _extract_issue_queries(feature_request: str) -> list[str]:
    text = feature_request or ""
    queries: list[str] = []
    seen: set[str] = set()

    for match in re.finditer(r"(?:zendesk[^0-9]{0,20})?#?(\d{5,12})", text, re.IGNORECASE):
        ticket_id = match.group(1)
        if ticket_id not in seen:
            seen.add(ticket_id)
            queries.append(ticket_id)

    for match in re.finditer(r"https?://[^\s]*zendesk[^\s]*/tickets/(\d+)", text, re.IGNORECASE):
        ticket_id = match.group(1)
        if ticket_id not in seen:
            seen.add(ticket_id)
            queries.append(ticket_id)

    cleaned = _clean_text(re.sub(r"https?://\S+", " ", text), 180)
    if cleaned and cleaned.lower() not in seen:
        seen.add(cleaned.lower())
        queries.append(cleaned)

    return queries[:4]


def _trello_backlog_research(feature_request: str) -> str:
    try:
        from pipeline.trello_client import TrelloClient

        trello = TrelloClient()
        queries = _extract_issue_queries(feature_request)
        if not queries:
            return ""

        matches: list[str] = []
        seen_ids: set[str] = set()
        for query in queries:
            for card in trello.search_cards_on_board(query):
                if card.id in seen_ids:
                    continue
                list_name = (card.list_name or "").strip()
                if list_name and list_name.lower() != _BACKLOG_LIST_NAME:
                    continue
                seen_ids.add(card.id)
                matches.append(
                    f"- [{list_name or 'Backlog'}] {card.name}\n"
                    f"  URL: {card.url}\n"
                    f"  Desc: {_clean_text(card.desc, 220)}"
                )
                if len(matches) >= 6:
                    break
            if len(matches) >= 6:
                break

        if not matches:
            return ""
        return "Related open Trello backlog / planning cards:\n" + "\n".join(matches)
    except Exception as exc:
        logger.debug("Trello backlog research skipped: %s", exc)
        return ""


def _wiki_customer_issue_summary(feature_request: str) -> str:
    text = feature_request or ""
    lower = text.lower()
    if not any(k in lower for k in ("zendesk", "customer", "merchant", "support", "ticket", "issue", "bug", "fix")):
        return ""

    try:
        from rag.vectorstore import search_filtered

        queries = _extract_issue_queries(feature_request)
        if not queries:
            return ""

        findings: list[str] = []
        seen_sources: set[str] = set()
        for query in queries:
            docs = search_filtered(
                query,
                k=4,
                source_type="wiki",
                category="Customer Issues & Support",
            )
            for doc in docs:
                source = doc.metadata.get("source", "wiki")
                if source in seen_sources:
                    continue
                seen_sources.add(source)
                findings.append(
                    f"- Source: {source}\n"
                    f"  {_clean_text(doc.page_content, 420)}"
                )
                if len(findings) >= 4:
                    break
            if len(findings) >= 4:
                break

        if not findings:
            return ""

        return (
            "Customer issue summary from internal wiki:\n"
            "Use this to understand the real customer-facing problem, likely root cause, "
            "and the expected fixed behaviour before writing AC.\n"
            + "\n".join(findings)
        )
    except Exception as exc:
        logger.debug("Wiki customer issue summary skipped: %s", exc)
        return ""


def _ddg_result_url(href: str) -> str:
    if not href:
        return ""
    if href.startswith("//duckduckgo.com/l/?"):
        href = "https:" + href
    parsed = urllib.parse.urlparse(href)
    qs = urllib.parse.parse_qs(parsed.query)
    if "uddg" in qs and qs["uddg"]:
        return qs["uddg"][0]
    return href


def _web_search(
    query: str,
    domains: tuple[str, ...],
    heading: str,
    max_results: int = 5,
) -> str:
    """Best-effort public web search. Safe to fail; generation still works."""
    site_filter = " OR ".join(f"site:{domain}" for domain in domains)
    search_query = (
        f"FedEx {query} limits requirements API rules carrier restrictions "
        f"{site_filter}"
    )
    url = "https://duckduckgo.com/html/?" + urllib.parse.urlencode({"q": search_query})
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"
        )
    }
    try:
        resp = requests.get(url, headers=headers, timeout=8)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
    except Exception as exc:
        logger.debug("Requirement web search failed: %s", exc)
        return ""

    results: list[str] = []
    seen: set[str] = set()
    for row in soup.select(".result"):
        link = row.select_one(".result__a")
        if not link:
            continue
        result_url = _ddg_result_url(link.get("href", ""))
        host = urllib.parse.urlparse(result_url).netloc.lower().replace("www.", "")
        if not any(host.endswith(domain) for domain in domains):
            continue
        if result_url in seen:
            continue
        seen.add(result_url)
        title = _clean_text(unescape(link.get_text(" ")), 140)
        snippet_el = row.select_one(".result__snippet")
        snippet = _clean_text(
            unescape(snippet_el.get_text(" ")) if snippet_el else "",
            280,
        )
        results.append(f"- {title}\n  URL: {result_url}\n  {snippet}".strip())
        if len(results) >= max_results:
            break

    if not results:
        return ""
    return f"{heading}:\n" + "\n".join(results)


def build_requirement_research_context(feature_request: str) -> str:
    """
    Return a compact research block for story/AC generation.

    The output is intentionally plain text so it can be embedded directly in
    Claude prompts. It includes official FedEx evidence first, then PluginHive.
    """
    query = _clean_text(feature_request, 500)
    if not query:
        return ""

    parts = [
        p for p in [
            _local_research(query),
            _wiki_customer_issue_summary(feature_request),
            _trello_backlog_research(feature_request),
            _web_search(
                query,
                _FEDEX_OFFICIAL_DOMAINS,
                "Official FedEx public web findings",
                max_results=5,
            ),
            _web_search(
                query,
                _PLUGINHIVE_DOMAINS,
                "PluginHive public web findings",
                max_results=3,
            ),
        ] if p
    ]
    if not parts:
        return (
            "No additional official FedEx or PluginHive research findings were available. "
            "Use existing product/code context and flag unknown limits as open questions."
        )

    return (
        "Requirement research for User Story / AC:\n"
        "Priority order for facts:\n"
        "1. Official FedEx docs/API/carrier rules are authoritative for carrier limits.\n"
        "2. PluginHive docs explain how the app exposes or implements those rules.\n"
        "3. Local code/RAG explains current product behaviour.\n"
        "Use this to add constraints, limitations, edge cases, and references for "
        "developers and QA. Do not invent limits not supported by this context.\n\n"
        + "\n\n".join(parts)
    )
