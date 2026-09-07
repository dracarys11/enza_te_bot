import json
from pathlib import Path

from tools.check_known_failures import (classify_failures,
                                        extract_failure_nodeids,
                                        load_baseline)


ROOT = Path(__file__).resolve().parent
BASELINE = ROOT / "test_baselines" / "known_failures_20260906.json"


def test_known_failure_baseline_is_unique_and_fixed_at_eight():
    payload = json.loads(BASELINE.read_text(encoding="utf-8"))
    baseline = load_baseline(BASELINE)
    assert payload["expected_failure_count"] == 8
    assert len(baseline) == 8


def test_known_baseline_does_not_hide_a_new_regression():
    baseline = load_baseline(BASELINE)
    known = sorted(baseline)[0]
    report = classify_failures(
        {known, "test_route_deadline_policy.py::test_new_regression"},
        baseline,
    )
    assert report["same_known_failures"] == [known]
    assert report["new_failures"] == [
        "test_route_deadline_policy.py::test_new_regression"
    ]
    assert len(report["resolved_failures"]) == 7


def test_pytest_output_classifies_same_new_and_resolved():
    baseline = load_baseline(BASELINE)
    known = sorted(baseline)[0]
    output = (
        f"FAILED {known} - AssertionError\n"
        "FAILED test_example.py::test_new - RuntimeError\n"
    )
    report = classify_failures(extract_failure_nodeids(output), baseline)
    assert report["same_known_failures"] == [known]
    assert report["new_failures"] == ["test_example.py::test_new"]
    assert len(report["resolved_failures"]) == 7
