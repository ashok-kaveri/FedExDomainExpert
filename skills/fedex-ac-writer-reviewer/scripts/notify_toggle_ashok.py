#!/usr/bin/env python3
"""Send the dashboard-style toggle enablement DM to Ashok Kumar N.

Usage:
    PYTHONPATH=. .venv/bin/python skills/fedex-ac-writer-reviewer/scripts/notify_toggle_ashok.py \
      --card-name "Card title" \
      --toggle "toggle.one" \
      --store "qa-store"
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def _load_dotenv_file(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _resolve_store(cli_store: str) -> str:
    if cli_store.strip():
        return cli_store.strip()
    store = os.getenv("STORE", "").strip()
    if store:
        return store
    try:
        import config  # type: ignore

        auto_path = getattr(config, "AUTOMATION_CODEBASE_PATH", "") or ""
        if auto_path:
            auto_env = Path(auto_path) / ".env"
            _load_dotenv_file(auto_env)
            return os.getenv("STORE", "").strip()
    except Exception:
        return ""
    return ""


def main() -> int:
    parser = argparse.ArgumentParser(description="Notify Ashok Kumar N to enable feature toggles for QA.")
    parser.add_argument("--card-name", required=True)
    parser.add_argument("--toggle", action="append", default=[], help="Toggle name. Repeat for multiple toggles.")
    parser.add_argument("--store", default="", help="Shopify store name, for example kee-fedex-qa.")
    parser.add_argument("--store-url", default="")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[3]
    os.chdir(repo_root)
    sys.path.insert(0, str(repo_root))
    _load_dotenv_file(repo_root / ".env")

    toggles = [t.strip() for t in args.toggle if t.strip()]
    if not toggles:
        print(json.dumps({"ok": False, "error": "At least one --toggle is required"}))
        return 2

    store = _resolve_store(args.store)
    if not store:
        print(json.dumps({"ok": False, "error": "Store is not set. Pass --store or configure STORE."}))
        return 2

    store_url = args.store_url.strip() or f"https://admin.shopify.com/store/{store}"

    try:
        from pipeline.slack_client import notify_toggle_enablement, search_slack_users
    except Exception as exc:
        print(json.dumps({"ok": False, "error": f"Could not import Slack helpers: {exc}"}))
        return 1

    users, err = search_slack_users("Ashok Kumar")
    if not users:
        print(json.dumps({"ok": False, "error": err or "Could not find Ashok Kumar in Slack"}))
        return 1

    ashok = users[0]
    result = notify_toggle_enablement(
        user_id=ashok["id"],
        card_name=args.card_name,
        toggles=toggles,
        store_name=store,
        store_url=store_url,
    )
    result = {
        **result,
        "recipient": ashok.get("display_name") or ashok.get("real_name") or "Ashok Kumar",
        "recipient_id": ashok["id"],
        "toggles": toggles,
        "store": store,
        "store_url": store_url,
    }
    print(json.dumps(result, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())

