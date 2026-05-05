#!/usr/bin/env python3
"""Maintain FedEx card-cycle knowledge.

This helper wraps the project's existing RAG and QA feedback APIs so Codex or
Claude can update knowledge after a card cycle without re-implementing the
dashboard logic.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipeline.qa_feedback import QAFeedback, ScenarioLearning, save_feedback  # noqa: E402
from pipeline.rag_updater import update_rag_from_card  # noqa: E402


def _read_text(path: str | None) -> str:
    if not path:
        return ""
    file_path = Path(path).expanduser()
    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")
    return file_path.read_text(encoding="utf-8")


def _read_scenario_learnings(path: str | None) -> list[ScenarioLearning]:
    if not path:
        return []
    payload = json.loads(_read_text(path))
    if not isinstance(payload, list):
        raise ValueError("Scenario learnings JSON must be a list")

    learnings: list[ScenarioLearning] = []
    for item in payload:
        if not isinstance(item, dict):
            raise ValueError("Each scenario learning must be an object")
        learnings.append(
            ScenarioLearning(
                scenario=str(item.get("scenario", "")).strip(),
                root_cause=str(item.get("root_cause", "")).strip(),
                correct_navigation=str(item.get("correct_navigation", "")).strip(),
                correct_order_action=str(item.get("correct_order_action", "")).strip(),
                verification_signal=str(item.get("verification_signal", "")).strip(),
                notes=str(item.get("notes", "")).strip(),
            )
        )
    return [learning for learning in learnings if learning.scenario]


def _split_notes(value: str | None) -> list[str]:
    if not value:
        return []
    return [line.strip(" -\t") for line in value.splitlines() if line.strip(" -\t")]


def main() -> int:
    parser = argparse.ArgumentParser(description="Update FedEx card-cycle knowledge.")
    parser.add_argument("--card-id", required=True)
    parser.add_argument("--card-name", required=True)
    parser.add_argument("--release", default="")
    parser.add_argument("--description-file")
    parser.add_argument("--ac-file")
    parser.add_argument("--test-cases-file")
    parser.add_argument("--skip-rag", action="store_true")

    parser.add_argument("--ac-misses", default="")
    parser.add_argument("--tc-issues", default="")
    parser.add_argument("--automation-issues", default="")
    parser.add_argument("--what-went-well", default="")
    parser.add_argument("--overall-notes", default="")
    parser.add_argument(
        "--scenario-learnings-json",
        help="Path to a JSON list with scenario, root_cause, correct_navigation, correct_order_action, verification_signal, notes.",
    )
    parser.add_argument("--skip-feedback", action="store_true")

    args = parser.parse_args()

    description = _read_text(args.description_file)
    acceptance_criteria = _read_text(args.ac_file)
    test_cases = _read_text(args.test_cases_file)

    result: dict[str, Any] = {
        "card_id": args.card_id,
        "card_name": args.card_name,
        "rag_updated": False,
        "feedback_saved": False,
    }

    if not args.skip_rag:
        update_rag_from_card(
            card_id=args.card_id,
            card_name=args.card_name,
            description=description,
            acceptance_criteria=acceptance_criteria,
            test_cases=test_cases,
            release=args.release,
        )
        result["rag_updated"] = True

    scenario_learnings = _read_scenario_learnings(args.scenario_learnings_json)
    feedback_has_content = any(
        [
            args.ac_misses.strip(),
            args.tc_issues.strip(),
            args.automation_issues.strip(),
            args.what_went_well.strip(),
            args.overall_notes.strip(),
            scenario_learnings,
        ]
    )

    if not args.skip_feedback and feedback_has_content:
        feedback = QAFeedback(
            card_id=args.card_id,
            card_name=args.card_name,
            date=datetime.now().strftime("%Y-%m-%d"),
            ac_misses=_split_notes(args.ac_misses),
            tc_issues=_split_notes(args.tc_issues),
            automation_issues=_split_notes(args.automation_issues),
            what_went_well=_split_notes(args.what_went_well),
            overall_notes=args.overall_notes.strip(),
            scenario_learnings=scenario_learnings,
        )
        save_feedback(feedback)
        result["feedback_saved"] = True
        result["scenario_learning_count"] = len(scenario_learnings)

    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
