from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.prepare_v03_benchmark import prepare_v03_run
from tools.run_benchmark import BenchmarkValidationError


def _fixture(tmp_path: Path) -> tuple[Path, Path]:
    project = tmp_path / "project"
    cases = project / "enza_memory" / "benchmark" / "cases" / "v0.3"
    evidence = project / "evidence.json"
    evidence.parent.mkdir(parents=True)
    evidence.write_text("{}", encoding="utf-8")
    cases.mkdir(parents=True)
    for case_id in ("case_201", "case_202"):
        (cases / f"{case_id}.json").write_text(json.dumps({
            "case_id": case_id,
            "failure_source": "evidence.json",
            "objective": "objective",
            "task_prompt": "task",
            "evidence_refs": ["evidence.json"],
            "expected_behavior": "expected",
            "hard_fail_conditions": ["hard fail"],
            "grading_rules": ["PASS: deterministic"],
        }), encoding="utf-8")
    return project, cases


def test_prompts_generated_without_gold_and_participants_isolated(tmp_path: Path) -> None:
    project, cases = _fixture(tmp_path)
    run = project / "enza_memory" / "benchmark" / "runs" / "v0.3_baseline_20260908"
    prepare_v03_run(run, cases_dir=cases, project_root=project)

    for participant in ("gemini_3.8-flash", "gpt-5.6-sol", "zcode-5.3-flash"):
        prompt = run / "prompts" / participant / "case_201.md"
        assert prompt.is_file()
        text = prompt.read_text(encoding="utf-8")
        assert "expected_behavior" not in text
        assert "hard_fail_conditions" not in text
        assert "grading_rules" not in text
        assert (run / "submissions" / participant / ".gitkeep").is_file()
    manifest = json.loads((run / "run_manifest.json").read_text(encoding="utf-8"))
    assert manifest["case_ids"] == ["case_201", "case_202"]
    assert manifest["gold_included_in_prompts"] is False


def test_directory_collision_is_rejected(tmp_path: Path) -> None:
    project, cases = _fixture(tmp_path)
    run = project / "run"
    run.mkdir()
    with pytest.raises(BenchmarkValidationError, match="overwrite"):
        prepare_v03_run(run, cases_dir=cases, project_root=project)


def test_missing_evidence_ref_is_rejected(tmp_path: Path) -> None:
    project, cases = _fixture(tmp_path)
    data = json.loads((cases / "case_201.json").read_text(encoding="utf-8"))
    data["evidence_refs"] = ["missing.json"]
    (cases / "case_201.json").write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(BenchmarkValidationError, match="missing evidence ref"):
        prepare_v03_run(project / "run", cases_dir=cases, project_root=project)
