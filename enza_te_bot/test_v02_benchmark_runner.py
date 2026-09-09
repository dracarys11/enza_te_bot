from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.run_benchmark import BenchmarkValidationError, prepare_v02_run


def _case(case_dir: Path, case_id: str = "case_101") -> None:
    case_dir.mkdir(parents=True)
    (case_dir / f"{case_id}.json").write_text(json.dumps({
        "case_id": case_id,
        "failure_source": "evidence.json",
        "objective": "offline objective",
        "task_prompt": "offline task",
        "evidence_refs": ["evidence.json"],
        "expected_behavior": "preserve unknown",
        "hard_fail_conditions": ["invented action"],
        "grading_rules": ["PASS: preserves unknown"],
    }), encoding="utf-8")
    (case_dir.parent / "evidence.json").write_text("{}", encoding="utf-8")


def test_prepare_v02_creates_isolated_participant_layout(tmp_path: Path) -> None:
    cases = tmp_path / "project" / "enza_memory" / "benchmark" / "cases" / "v0.2"
    _case(cases)
    run = tmp_path / "project" / "enza_memory" / "benchmark" / "runs" / "v0.2_run"

    prepare_v02_run(run, cases_dir=cases)

    manifest = json.loads((run / "run_manifest.json").read_text(encoding="utf-8"))
    assert manifest["case_ids"] == ["case_101"]
    for participant in ("gemini_3.8-flash", "gpt-5.6-sol", "zcode-5.3-flash"):
        assert (run / "prompts" / participant / "case_101.md").is_file()
        assert (run / "submissions" / participant).is_dir()
    assert "grading_rules" not in (run / "prompts" / "gemini_3.8-flash" / "case_101.md").read_text()


def test_prepare_v02_refuses_directory_collision(tmp_path: Path) -> None:
    cases = tmp_path / "cases"
    _case(cases)
    run = tmp_path / "run"
    prepare_v02_run(run, cases_dir=cases)

    with pytest.raises(BenchmarkValidationError, match="overwrite"):
        prepare_v02_run(run, cases_dir=cases)


def test_prepare_v02_rejects_duplicate_participants(tmp_path: Path) -> None:
    cases = tmp_path / "cases"
    _case(cases)
    with pytest.raises(BenchmarkValidationError, match="unique"):
        prepare_v02_run(tmp_path / "run", cases_dir=cases, participants=("same", "same"))
