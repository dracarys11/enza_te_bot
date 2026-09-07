"""Infer named actions from recorded demo transitions without changing source data."""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any, Iterable


UNKNOWN_STATE = "UNKNOWN"


def _interaction_parts(record: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    before = record.get("observation") or record.get("pre") or {}
    after = record.get("after_observation") or record.get("post") or {}
    action = record.get("human_action") or record.get("action") or {}
    return before, after, action


def _available_actions(record: dict[str, Any], before: dict[str, Any]) -> tuple[bool, list[dict[str, Any]]]:
    if "available_actions" in before:
        return True, before.get("available_actions") or []
    if "available_actions" in record:
        return True, record.get("available_actions") or []
    if "controls" in record:
        return True, record.get("controls") or []
    return False, []


def classify_unknown_click(record: dict[str, Any]) -> dict[str, Any] | None:
    """Classify one recorded UNKNOWN_CLICK using declared transition contracts."""
    if record.get("kind") not in {"demo_step", "normalized_interaction"} and record.get("record_type") != "demo_step":
        return None

    before, after, recorded_action = _interaction_parts(record)
    if recorded_action.get("classification") != "UNKNOWN_CLICK":
        return None

    before_state = before.get("state")
    after_state = after.get("state")
    actions_known, actions = _available_actions(record, before)
    matches = [
        action["name"]
        for action in actions
        if action.get("name")
        and after_state in (action.get("expected_next_states") or [])
    ]

    known_states = (
        before_state not in {None, UNKNOWN_STATE}
        and after_state not in {None, UNKNOWN_STATE}
    )
    base = {
        "step_id": record.get("step"),
        "before_state": before_state,
        "after_state": after_state,
        "recorded_action": "UNKNOWN_CLICK",
    }
    if known_states and actions_known and len(matches) == 1:
        return {
            **base,
            "status": "INFERRED",
            "inferred_action": matches[0],
            "confidence": 1.0,
            "inference_reason": (
                f"Exactly one available action declares {after_state} as an expected next state."
            ),
        }
    if known_states and actions_known and len(matches) > 1:
        return {
            **base,
            "status": "AMBIGUOUS",
            "matching_actions": matches,
        }
    return {**base, "status": "UNRESOLVED"}


def analyze_records(records: Iterable[dict[str, Any]]) -> dict[str, Any]:
    classifications = [
        result
        for record in records
        if (result := classify_unknown_click(record)) is not None
    ]
    inferred = [item for item in classifications if item["status"] == "INFERRED"]
    transition_counts = Counter(
        (item["before_state"], item["after_state"], item["inferred_action"])
        for item in inferred
    )
    top_transitions = [
        {
            "before_state": before,
            "after_state": after,
            "inferred_action": action,
            "count": count,
        }
        for (before, after, action), count in sorted(
            transition_counts.items(),
            key=lambda entry: (-entry[1], entry[0]),
        )
    ]
    return {
        "inferred_actions": inferred,
        "summary": {
            "total_unknown_click": len(classifications),
            "deterministic_recoverable_count": len(inferred),
            "ambiguous_count": sum(item["status"] == "AMBIGUOUS" for item in classifications),
            "unresolved_count": sum(item["status"] == "UNRESOLVED" for item in classifications),
            "top_recoverable_transitions": top_transitions,
        },
    }


def analyze_episode(path: Path) -> dict[str, Any]:
    records = []
    with path.open(encoding="utf-8") as episode:
        for line_number, line in enumerate(episode, start=1):
            if not line.strip():
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as error:
                raise ValueError(f"Invalid JSON on line {line_number}: {error.msg}") from error
    return analyze_records(records)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("episode", type=Path, help="Existing episode.jsonl to analyze")
    args = parser.parse_args()
    print(json.dumps(analyze_episode(args.episode), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
