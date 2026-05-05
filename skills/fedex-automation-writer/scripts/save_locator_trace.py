#!/usr/bin/env python3
"""Save a locator trace JSON for handoff from AI QA browser to automation writer."""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path


def _slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "unknown-card"


def main() -> int:
    parser = argparse.ArgumentParser(description="Save a FedEx AI QA locator trace.")
    parser.add_argument("--card-name", required=True)
    parser.add_argument("--card-id", default="")
    parser.add_argument("--tc-id", action="append", default=[])
    parser.add_argument("--route", default="")
    parser.add_argument("--source", default="fedex-ai-qa-browser")
    parser.add_argument("--input-json", default="", help="Optional existing trace JSON file to normalize/save.")
    parser.add_argument("--elements", default="", help="Newline-separated element notes if no input JSON is provided.")
    parser.add_argument("--evidence", default="", help="Newline-separated evidence notes.")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[3]
    out_dir = repo_root / "data" / "ai_qa_locator_traces"
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.input_json:
        data = json.loads(Path(args.input_json).read_text(encoding="utf-8"))
    else:
        elements = [line.strip() for line in args.elements.splitlines() if line.strip()]
        evidence = [line.strip() for line in args.evidence.splitlines() if line.strip()]
        data = {
            "card_id": args.card_id,
            "card_name": args.card_name,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "source": args.source,
            "tc_ids": args.tc_id,
            "route": args.route,
            "page_context": {
                "shopify_admin": True,
                "app_iframe": True,
                "url": "",
            },
            "steps": [
                {
                    "step": 1,
                    "action": "observe",
                    "target": "",
                    "url": "",
                    "elements": elements,
                    "notes": "Saved from AI QA browser trace handoff.",
                }
            ],
            "recommended_locators": [],
            "evidence": evidence,
        }

    data.setdefault("card_name", args.card_name)
    data.setdefault("card_id", args.card_id)
    data.setdefault("created_at", datetime.now(timezone.utc).isoformat())
    data.setdefault("source", args.source)
    data.setdefault("tc_ids", args.tc_id)
    data.setdefault("route", args.route)

    file_stem = args.card_id.strip() or _slugify(args.card_name)
    out_path = out_dir / f"{file_stem}.json"
    out_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(str(out_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

