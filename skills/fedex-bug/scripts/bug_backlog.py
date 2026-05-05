#!/usr/bin/env python3
"""Draft/check/create a Trello Backlog bug using the dashboard bug tracker flow."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Check/draft/create a FedEx QA bug in Trello Backlog.")
    parser.add_argument("--issue", required=True, help="Plain-English QA bug description.")
    parser.add_argument("--feature", default="", help="Feature/page context.")
    parser.add_argument("--release", default="", help="Release label.")
    parser.add_argument("--backlog-list", default="Backlog")
    parser.add_argument("--raise", dest="do_raise", action="store_true", help="Create the Trello Backlog card if no duplicate is found.")
    parser.add_argument("--raise-anyway", action="store_true", help="Create even if duplicate check finds a match.")
    parser.add_argument("--linked-card-id", default="")
    parser.add_argument("--linked-card-name", default="")
    parser.add_argument("--linked-card-url", default="")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[3]
    os.chdir(repo_root)
    sys.path.insert(0, str(repo_root))
    _load_dotenv(repo_root / ".env")

    issue = args.issue.strip()
    if args.linked_card_name:
        suffix = f"\n\n---\nFound while testing card: {args.linked_card_name}"
        if args.linked_card_url:
            suffix += f"\n{args.linked_card_url}"
        issue += suffix

    from pipeline.bug_tracker import check_and_draft_bug, raise_bug

    result = check_and_draft_bug(
        issue_description=issue,
        feature_context=args.feature.strip(),
        release=args.release.strip(),
        backlog_list_name=args.backlog_list,
    )

    payload: dict = {
        "ok": not bool(result.error),
        "error": result.error,
        "is_duplicate": result.is_duplicate,
        "duplicate_reason": result.duplicate_reason,
        "duplicate_card": None,
        "draft": None,
        "created_card": None,
        "linked_comment": None,
    }

    if result.duplicate_card:
        payload["duplicate_card"] = {
            "id": result.duplicate_card.id,
            "name": result.duplicate_card.name,
            "url": result.duplicate_card.url,
        }

    if result.draft:
        payload["draft"] = {
            "title": result.draft.title,
            "severity": result.draft.severity,
            "feature_area": result.draft.feature_area,
            "steps_to_reproduce": result.draft.steps_to_reproduce,
            "expected_behavior": result.draft.expected_behavior,
            "actual_behavior": result.draft.actual_behavior,
            "labels": result.draft.labels,
            "release": result.draft.release,
            "trello_desc": result.draft.to_trello_desc(),
        }

    should_create = args.do_raise and result.draft and (not result.is_duplicate or args.raise_anyway)
    if should_create:
        created = raise_bug(result.draft, backlog_list_name=args.backlog_list)
        payload["created_card"] = {
            "id": created.id,
            "name": created.name,
            "url": created.url,
        }

        if args.linked_card_id:
            try:
                from pipeline.trello_client import TrelloClient

                trello = TrelloClient()
                comment = (
                    f"Bug raised to Backlog: [{created.name}]({created.url})\n"
                    f"Severity: {result.draft.severity} · Release: {result.draft.release}"
                )
                trello.add_comment(args.linked_card_id, comment)
                payload["linked_comment"] = {"ok": True}
            except Exception as exc:
                payload["linked_comment"] = {"ok": False, "error": str(exc)}

    print(json.dumps(payload, indent=2))
    if result.error:
        return 1
    if args.do_raise and result.is_duplicate and not args.raise_anyway:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

