"""CLI and library entry point for offline case evaluation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

try:  # Supports both ``python -m evaluator.runner`` and direct script use.
    from .scorer import classify_response, parse_grading_rules, score_response
except ImportError:  # pragma: no cover - exercised by the direct CLI form
    from scorer import classify_response, parse_grading_rules, score_response


REQUIRED = {"decision", "facts", "inferences", "unknowns", "action_allowed", "reason", "confidence"}


def validate_response(response: dict[str, Any]) -> list[str]:
    errors = []
    errors.extend(f"missing required field: {field}" for field in sorted(REQUIRED - response.keys()))
    if not isinstance(response.get("decision"), str): errors.append("decision must be a string")
    for field in ("facts", "inferences", "unknowns"):
        if not isinstance(response.get(field), list) or not all(isinstance(item, str) for item in response.get(field, [])):
            errors.append(f"{field} must be an array of strings")
    if not isinstance(response.get("action_allowed"), bool): errors.append("action_allowed must be boolean")
    if not isinstance(response.get("confidence"), (int, float)) or not 0 <= response.get("confidence", -1) <= 1:
        errors.append("confidence must be between 0 and 1")
    return errors


def evaluate(case: dict[str, Any], response: dict[str, Any], *, include_rule_audit: bool = False) -> dict[str, Any]:
    errors = validate_response(response)
    scores = score_response(case, response) if not errors else {"dimensions": {}, "total": 0, "max_total": 100}
    result = {"case_id": case.get("case_id"), "status": "UNKNOWN" if errors else classify_response(case, response), "validation_errors": errors, "score": scores}
    if include_rule_audit:
        audit = parse_grading_rules(case)
        result["rule_audit"] = {
            key: audit[key]
            for key in ("parsed_rules_count", "ignored_rules_count", "warnings")
        }
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", required=True, type=Path)
    parser.add_argument("--response", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--rule-audit", action="store_true", help="include grading-rule parse counts and warnings")
    args = parser.parse_args()
    case = json.loads(args.case.read_text())
    response = json.loads(args.response.read_text())
    args.output.write_text(json.dumps(evaluate(case, response, include_rule_audit=args.rule_audit), indent=2) + "\n")


if __name__ == "__main__":
    main()
