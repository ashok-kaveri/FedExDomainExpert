#!/usr/bin/env python3
"""Slack operations for FedEx Codex/Claude skills."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

import requests

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import config  # noqa: F401,E402  # loads project .env from repo root
from pipeline.slack_client import list_slack_channels, search_slack_users  # noqa: E402

SLACK_API = "https://slack.com/api"


def _token() -> str:
    token = os.getenv("SLACK_BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("SLACK_BOT_TOKEN is not set in .env")
    return token


def _headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {_token()}", "Content-Type": "application/json"}


def _api_get(method: str, **params: Any) -> dict[str, Any]:
    resp = requests.get(f"{SLACK_API}/{method}", headers=_headers(), params=params, timeout=20)
    resp.raise_for_status()
    data = resp.json()
    if not data.get("ok"):
        raise RuntimeError(f"Slack {method} error: {data.get('error', 'unknown')}")
    return data


def _api_post(method: str, payload: dict[str, Any]) -> dict[str, Any]:
    resp = requests.post(f"{SLACK_API}/{method}", headers=_headers(), json=payload, timeout=20)
    resp.raise_for_status()
    data = resp.json()
    if not data.get("ok"):
        raise RuntimeError(f"Slack {method} error: {data.get('error', 'unknown')}")
    return data


def _open_dm(user_id: str) -> str:
    data = _api_post("conversations.open", {"users": user_id})
    return data["channel"]["id"]


def _resolve_channel(value: str) -> str:
    value = (value or "").strip()
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


def _compact_message(msg: dict[str, Any]) -> dict[str, Any]:
    return {
        "ts": msg.get("ts", ""),
        "thread_ts": msg.get("thread_ts", msg.get("ts", "")),
        "user": msg.get("user", msg.get("bot_id", "")),
        "text": msg.get("text", ""),
        "reply_count": msg.get("reply_count", 0),
    }


def _best_user(query: str) -> dict[str, Any]:
    users, error = search_slack_users(query)
    if error:
        raise RuntimeError(error)
    if not users:
        raise RuntimeError(f"No Slack user found for query: {query}")
    lowered = query.strip().lower()
    exact = [
        user
        for user in users
        if lowered in {
            str(user.get("name", "")).lower(),
            str(user.get("display_name", "")).lower(),
        }
    ]
    return (exact or users)[0]


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Slack operations.")
    sub = parser.add_subparsers(dest="command", required=True)

    users_p = sub.add_parser("users")
    users_p.add_argument("--query", required=True)

    sub.add_parser("channels")

    messages_p = sub.add_parser("messages")
    messages_p.add_argument("--channel", required=True, help="Channel ID or name.")
    messages_p.add_argument("--limit", type=int, default=20)

    thread_p = sub.add_parser("thread")
    thread_p.add_argument("--channel", required=True, help="Channel ID or name.")
    thread_p.add_argument("--ts", required=True, help="Parent message timestamp.")

    send_channel_p = sub.add_parser("send-channel")
    send_channel_p.add_argument("--channel", required=True, help="Channel ID or name.")
    send_channel_p.add_argument("--text", required=True)

    reply_p = sub.add_parser("reply")
    reply_p.add_argument("--channel", required=True, help="Channel ID or name.")
    reply_p.add_argument("--thread-ts", required=True)
    reply_p.add_argument("--text", required=True)

    dm_p = sub.add_parser("send-dm")
    dm_p.add_argument("--user", required=True, help="Slack user ID.")
    dm_p.add_argument("--text", required=True)

    dm_name_p = sub.add_parser("send-dm-by-name")
    dm_name_p.add_argument("--query", required=True, help="Name/display name search.")
    dm_name_p.add_argument("--text", required=True)

    args = parser.parse_args()

    if args.command == "users":
        users, error = search_slack_users(args.query)
        payload = {"users": users, "error": error}
    elif args.command == "channels":
        channels, error, note = list_slack_channels()
        payload = {"channels": channels, "error": error, "note": note}
    elif args.command == "messages":
        channel = _resolve_channel(args.channel)
        data = _api_get("conversations.history", channel=channel, limit=args.limit)
        payload = {"channel": channel, "messages": [_compact_message(m) for m in data.get("messages", [])]}
    elif args.command == "thread":
        channel = _resolve_channel(args.channel)
        data = _api_get("conversations.replies", channel=channel, ts=args.ts)
        payload = {"channel": channel, "messages": [_compact_message(m) for m in data.get("messages", [])]}
    elif args.command == "send-channel":
        channel = _resolve_channel(args.channel)
        data = _api_post("chat.postMessage", {"channel": channel, "text": args.text, "mrkdwn": True})
        payload = {"ok": True, "channel": channel, "ts": data.get("ts", "")}
    elif args.command == "reply":
        channel = _resolve_channel(args.channel)
        data = _api_post(
            "chat.postMessage",
            {"channel": channel, "thread_ts": args.thread_ts, "text": args.text, "mrkdwn": True},
        )
        payload = {"ok": True, "channel": channel, "thread_ts": args.thread_ts, "ts": data.get("ts", "")}
    elif args.command == "send-dm":
        dm_channel = _open_dm(args.user)
        data = _api_post("chat.postMessage", {"channel": dm_channel, "text": args.text, "mrkdwn": True})
        payload = {"ok": True, "user": args.user, "channel": dm_channel, "ts": data.get("ts", "")}
    elif args.command == "send-dm-by-name":
        user = _best_user(args.query)
        dm_channel = _open_dm(user["id"])
        data = _api_post("chat.postMessage", {"channel": dm_channel, "text": args.text, "mrkdwn": True})
        payload = {"ok": True, "user": user, "channel": dm_channel, "ts": data.get("ts", "")}
    else:
        raise SystemExit(f"Unsupported command: {args.command}")

    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
