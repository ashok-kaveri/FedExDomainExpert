#!/usr/bin/env python3
"""Trello operations for FedEx Codex/Claude skills."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import config  # noqa: F401,E402  # loads project .env from repo root
from pipeline.bug_reporter import get_card_devs  # noqa: E402
from pipeline.trello_client import TrelloCard, TrelloClient  # noqa: E402


def _card_ref(value: str) -> str:
    value = (value or "").strip()
    match = re.search(r"trello\.com/c/([^/?#\s]+)", value)
    if match:
        return match.group(1)
    return value.rstrip("/").split("/")[-1] if value.startswith("http") else value


def _card_json(card: TrelloCard) -> dict[str, Any]:
    return {
        "id": card.id,
        "name": card.name,
        "desc": card.desc,
        "list_id": card.list_id,
        "list_name": card.list_name,
        "labels": card.labels,
        "url": card.url,
        "attachments": card.attachments,
        "checklists": card.checklists,
        "comments": card.comments,
    }


def _client(args: argparse.Namespace) -> TrelloClient:
    return TrelloClient(board_id=getattr(args, "board_id", "") or None)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Trello operations.")
    parser.add_argument("--board-id", default="", help="Optional Trello board id override.")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("boards")
    sub.add_parser("lists")

    cards_list = sub.add_parser("cards-in-list")
    cards_list.add_argument("--list", required=True, help="List name, e.g. Backlog or Dev Done.")

    card_p = sub.add_parser("card")
    card_p.add_argument("--card", required=True, help="Card id, shortlink, or URL.")

    comments_p = sub.add_parser("comments")
    comments_p.add_argument("--card", required=True)
    comments_p.add_argument("--limit", type=int, default=20)

    members_p = sub.add_parser("members")
    members_p.add_argument("--card", required=True)

    devs_p = sub.add_parser("devs")
    devs_p.add_argument("--card", required=True)

    search_p = sub.add_parser("search")
    search_p.add_argument("--query", required=True)

    add_comment_p = sub.add_parser("add-comment")
    add_comment_p.add_argument("--card", required=True)
    add_comment_p.add_argument("--text", required=True)

    move_p = sub.add_parser("move")
    move_p.add_argument("--card", required=True)
    move_p.add_argument("--list", required=True)

    create_p = sub.add_parser("create-card")
    create_p.add_argument("--list", required=True)
    create_p.add_argument("--name", required=True)
    create_p.add_argument("--desc", default="")
    create_p.add_argument("--labels", default="", help="Comma-separated label names.")

    args = parser.parse_args()
    trello = _client(args)

    if args.command == "boards":
        payload = [{"id": b.id, "name": b.name} for b in trello.get_boards()]
    elif args.command == "lists":
        payload = [{"id": l.id, "name": l.name} for l in trello.get_lists()]
    elif args.command == "cards-in-list":
        lst = trello.get_list_by_name(args.list)
        if not lst:
            raise SystemExit(f"List not found: {args.list}")
        payload = [_card_json(card) for card in trello.get_cards_in_list(lst.id)]
    elif args.command == "card":
        payload = _card_json(trello.get_card(_card_ref(args.card)))
    elif args.command == "comments":
        card = trello.get_card(_card_ref(args.card))
        payload = {
            "card": {"id": card.id, "name": card.name, "url": card.url},
            "comments": list(reversed(card.comments))[: args.limit],
        }
    elif args.command == "members":
        payload = trello.get_card_members(_card_ref(args.card))
    elif args.command == "devs":
        payload = get_card_devs(_card_ref(args.card))
    elif args.command == "search":
        payload = [_card_json(card) for card in trello.search_cards_on_board(args.query)]
    elif args.command == "add-comment":
        card_id = _card_ref(args.card)
        trello.add_comment(card_id, args.text)
        card = trello.get_card(card_id)
        payload = {"ok": True, "card": {"id": card.id, "name": card.name, "url": card.url}}
    elif args.command == "move":
        card_id = _card_ref(args.card)
        trello.move_card_to_list(card_id, args.list)
        card = trello.get_card(card_id)
        payload = {"ok": True, "target_list": args.list, "card": _card_json(card)}
    elif args.command == "create-card":
        labels = [label.strip() for label in args.labels.split(",") if label.strip()]
        card = trello.create_card(args.list, args.name, desc=args.desc, label_names=labels or None)
        payload = {"ok": True, "card": _card_json(card)}
    else:
        raise SystemExit(f"Unsupported command: {args.command}")

    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
