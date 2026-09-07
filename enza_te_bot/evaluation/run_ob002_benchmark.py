"""Run the OB002 decision benchmark without authorization or execution."""
from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from decision_agent.base import ActionCandidateError, validate_action_candidate
from decision_agent.grounded_decision import GroundedDecisionAgent
from grounded_element import build_grounded_elements


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CASES = Path(__file__).resolve().parent / "decision_cases"


class BenchmarkCaseError(ValueError):
    """Raised when an OB002 case definition is malformed."""


def _load(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise BenchmarkCaseError(f"case must be a JSON object: {path}")
    return payload


def _elements(case: dict[str, Any]) -> list[dict[str, Any]]:
    relative = case.get("observation")
    if not isinstance(relative, str) or not relative:
        raise BenchmarkCaseError("case observation must be a repository-relative path")
    observation = _load(ROOT / relative)
    return build_grounded_elements(observation)


def evaluate_case(case: dict[str, Any]) -> dict[str, Any]:
    elements = _elements(case)
    mode = case.get("mode")
    expected = case.get("expected")
    if not isinstance(expected, dict):
        raise BenchmarkCaseError("case expected must be an object")

    if mode == "decision":
        goal = case.get("user_goal")
        options = case.get("target_text_options")
        if not isinstance(goal, str) or not isinstance(options, list):
            raise BenchmarkCaseError("decision case requires user_goal and target_text_options")
        actual = GroundedDecisionAgent({goal: options}).decide(elements, goal)
        passed = actual == expected
    elif mode == "candidate_validation":
        candidate = case.get("candidate")
        if not isinstance(candidate, dict):
            raise BenchmarkCaseError("candidate_validation case requires candidate")
        try:
            validate_action_candidate(candidate, elements)
        except ActionCandidateError as error:
            actual = {"outcome": "REJECTED", "reason": str(error)}
        else:
            actual = {"outcome": "ACCEPTED"}
        passed = actual.get("outcome") == expected.get("outcome")
    else:
        raise BenchmarkCaseError(f"unsupported case mode: {mode!r}")

    return {
        "case_name": case.get("case_name"),
        "expected": expected,
        "actual": actual,
        "result": "PASS" if passed else "FAIL",
    }


def run_benchmark(cases_dir: str | Path = DEFAULT_CASES) -> dict[str, Any]:
    paths = sorted(Path(cases_dir).glob("*.json"))
    if not paths:
        raise BenchmarkCaseError("no OB002 decision cases found")
    results = [evaluate_case(_load(path)) for path in paths]
    passed = sum(result["result"] == "PASS" for result in results)
    return {
        "benchmark": "OB002 Decision Benchmark Suite",
        "cases": results,
        "summary": {"passed": passed, "failed": len(results) - passed},
    }


def main() -> int:
    report = run_benchmark()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["summary"]["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
