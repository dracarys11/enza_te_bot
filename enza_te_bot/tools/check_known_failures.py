#!/usr/bin/env python3
"""Classify pytest failures against an explicit known-failure baseline."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASELINE = ROOT / "test_baselines" / "known_failures_20260906.json"
FAILED_LINE = re.compile(r"^FAILED\s+(\S+?)(?:\s+-\s+.*)?$", re.MULTILINE)


def load_baseline(path: Path = DEFAULT_BASELINE) -> set[str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    failures = payload.get("failures")
    if not isinstance(failures, list) or not all(isinstance(item, str) for item in failures):
        raise ValueError("known failure baseline must contain a string failures list")
    if payload.get("expected_failure_count") != len(failures) or len(set(failures)) != len(failures):
        raise ValueError("known failure baseline count/uniqueness mismatch")
    return set(failures)


def extract_failure_nodeids(pytest_output: str) -> set[str]:
    return set(FAILED_LINE.findall(pytest_output))


def classify_failures(current: Iterable[str], baseline: Iterable[str]) -> dict[str, list[str]]:
    current_set = set(current)
    baseline_set = set(baseline)
    return {
        "same_known_failures": sorted(current_set & baseline_set),
        "new_failures": sorted(current_set - baseline_set),
        "resolved_failures": sorted(baseline_set - current_set),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("pytest_output", type=Path)
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    args = parser.parse_args()
    report = classify_failures(
        extract_failure_nodeids(args.pytest_output.read_text(encoding="utf-8")),
        load_baseline(args.baseline),
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if report["new_failures"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
