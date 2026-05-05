#!/usr/bin/env python3
"""Prepare or send FedEx QA sign-off messages."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import config  # noqa: F401,E402  # load project .env
from pipeline.slack_client import SlackClient, list_slack_channels  # noqa: E402
from pipeline.trello_client import TrelloClient  # noqa: E402


def _mentions(raw: str) -> list[str]:
    return [item.strip() for item in (raw or "").replace(",", " ").split() if item.strip()]


def _format_mention(value: str) -> str:
    if value in ("here", "channel", "everyone"):
        return f"<!{value}>"
    if value.startswith(("U", "W")):
        return f"<@{value}>"
    return f"@{value}"


def _resolve_channel(value: str) -> str:
    value = (value or "").strip()
    if not value:
        return ""
    if value.startswith(("C", "G", "D")):
        return value
    name = value.lstrip("#")
    channels, error, _note = list_slack_channels()
    if error:
        raise RuntimeError(error)
    matches = [ch for ch in channels if ch.get("name") == name]
    if not matches:
        raise RuntimeError(f"Slack channel not found: {value}")
    if len(matches) > 1:
        raise RuntimeError(f"Multiple Slack channels match {value}: {matches}")
    return matches[0]["id"]


def _load_backlog(path: str | None, raw_titles: str = "") -> tuple[list[dict], list[str]]:
    rich: list[dict] = []
    plain: list[str] = []

    if path:
        payload = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
        if not isinstance(payload, list):
            raise ValueError("Backlog JSON must be a list")
        for item in payload:
            if isinstance(item, str):
                plain.append(item)
            elif isinstance(item, dict):
                rich.append({
                    "name": str(item.get("name", item.get("title", ""))).strip(),
                    "url": str(item.get("url", "")).strip(),
                    "severity": str(item.get("severity", "")).strip(),
                })
            else:
                raise ValueError("Backlog entries must be strings or objects")

    for line in (raw_titles or "").splitlines():
        clean = line.strip()
        if clean:
            plain.append(clean)

    plain.extend([b["name"] for b in rich if b.get("name") and not b.get("url")])
    return rich, plain


def _cards_from_list(list_name: str, board_id: str = "") -> list[dict]:
    trello = TrelloClient(board_id=board_id or None)
    lst = trello.get_list_by_name(list_name)
    if not lst:
        available = [item.name for item in trello.get_lists()]
        raise RuntimeError(f"Trello list not found: {list_name}. Available lists: {available}")
    cards = trello.get_cards_in_list(lst.id)
    return [{"name": card.name, "url": card.url or ""} for card in cards]


def _build_preview(
    release: str,
    verified_cards: list[dict],
    backlog_cards: list[str],
    mentions: list[str],
    cc: str = "",
    qa_lead: str = "",
    backlog_links: list[dict] | None = None,
) -> str:
    mention_line = "  ".join(_format_mention(item) for item in mentions)
    cards_block = "\n\n".join(
        f"{card['name']}\n{card['url']}" if card.get("url") else card["name"]
        for card in verified_cards
    ) or "(none)"

    bug_dicts = backlog_links or []
    if bug_dicts:
        bug_lines = []
        for bug in bug_dicts:
            name = bug.get("name", "")
            url = bug.get("url", "")
            severity = bug.get("severity", "")
            prefix = f"{severity} — " if severity else ""
            bug_lines.append(f"{prefix}<{url}|{name}>" if url else f"{prefix}{name}")
        backlog_block = "\n".join(bug_lines)
    else:
        backlog_block = "\n".join(backlog_cards)

    lines = [
        mention_line,
        "",
        f"We've completed testing  *{release}*  and it's good for the release :white_check_mark:",
        "",
        "*Cards Verified:*",
        "",
        cards_block,
        "",
    ]
    if backlog_block:
        count = len(bug_dicts) if bug_dicts else len(backlog_cards)
        lines.extend([f"*Cards added to backlog ({count}):*", "", backlog_block, ""])
    lines.append("*QA Signed off* :tada:")
    if cc:
        lines.extend(["", f"CC: {_format_mention(cc)}"])
    if qa_lead:
        lines.append(f"_Signed by: {qa_lead}_")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare or send QA sign-off messages.")
    sub = parser.add_subparsers(dest="command", required=True)

    def add_common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--list", required=True, help="Trello list/release line name.")
        p.add_argument("--release", required=True)
        p.add_argument("--board-id", default="")
        p.add_argument("--mentions", default="here")
        p.add_argument("--cc", default="")
        p.add_argument("--qa-lead", default="")
        p.add_argument("--backlog-json", default="", help="JSON list of {name,url,severity}.")
        p.add_argument("--backlog-titles", default="", help="Plain backlog titles, one per line.")

    prepare_p = sub.add_parser("prepare")
    add_common(prepare_p)

    send_p = sub.add_parser("send")
    add_common(send_p)
    send_p.add_argument("--channel", required=True, help="Slack channel ID or name.")

    args = parser.parse_args()

    verified_cards = _cards_from_list(args.list, args.board_id)
    backlog_links, backlog_cards = _load_backlog(args.backlog_json or None, args.backlog_titles)
    mentions = _mentions(args.mentions) or ["here"]
    preview = _build_preview(
        release=args.release,
        verified_cards=verified_cards,
        backlog_cards=backlog_cards,
        mentions=mentions,
        cc=args.cc.strip(),
        qa_lead=args.qa_lead.strip(),
        backlog_links=backlog_links or None,
    )

    result: dict[str, Any] = {
        "release": args.release,
        "trello_list": args.list,
        "card_count": len(verified_cards),
        "verified_cards": verified_cards,
        "backlog_links": backlog_links,
        "backlog_cards": backlog_cards,
        "mentions": mentions,
        "cc": args.cc.strip(),
        "qa_lead": args.qa_lead.strip(),
        "preview": preview,
    }

    if args.command == "send":
        channel = _resolve_channel(args.channel)
        client = SlackClient(token=os.getenv("SLACK_BOT_TOKEN", ""), channel=channel)
        # Sign-off sends must respect the QA-selected channel. SlackClient
        # normally prefers SLACK_WEBHOOK_URL when present, which would post to
        # the webhook's fixed channel instead.
        client.webhook_url = ""
        ts = client.post_signoff_message(
            release=args.release,
            verified_cards=verified_cards,
            backlog_cards=backlog_cards,
            mentions=mentions,
            cc=args.cc.strip(),
            qa_lead=args.qa_lead.strip(),
            backlog_links=backlog_links or None,
        )
        result.update({"ok": True, "channel": channel, "ts": ts})

    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
