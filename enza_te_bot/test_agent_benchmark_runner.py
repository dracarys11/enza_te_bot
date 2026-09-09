"""Regression tests for the agent benchmark prompt runner.

- TEST_PROMPT_GENERATION_WORKS
- TEST_GOLD_IS_NOT_LEAKED
- TEST_SCHEMA_INCLUDED
- TEST_CASE_IDS_VALID
- TEST_FAIL_CLOSED_ON_MISSING_EVIDENCE
- TEST_RUNNER_HAS_NO_MODEL_OR_EXECUTION_SURFACE

All tests are offline: fixture cases/schemas live under tmp_path; the
gold-leak check runs against the real corpus read-only. No model is called,
no browser, no game.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pytest

from tools.run_agent_benchmark import (
    BenchmarkPromptError,
    REPOSITORY_ROOT,
    build_prompt,
    generate_prompts,
    load_cases,
    load_response_schema,
    main,
)

SCHEMA_TEXT = json.dumps({
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "required": ["decision", "facts", "inferences", "unknowns",
                 "action_allowed", "reason", "confidence"],
})


def _write_case(cases_dir: Path, evidence: Path, case_id: str = "ARB900_fixture",
                **extra) -> Path:
    case = {
        "case_id": case_id,
        "objective": "fixture objective",
        "input_artifacts": [str(evidence)],
        "task_prompt": "Decide the fixture outcome.",
        # evaluator-owned fields must never reach a prompt
        "expected_invariants": ["FIXTURE_INVARIANT"],
        "grading_rules": ["PASS: fixture pass rule", "FAIL: fixture fail rule"],
    }
    case.update(extra)
    path = cases_dir / f"{case_id}.json"
    path.write_text(json.dumps(case), encoding="utf-8")
    return path


@pytest.fixture()
def env(tmp_path: Path):
    cases_dir = tmp_path / "cases"
    cases_dir.mkdir()
    evidence = tmp_path / "evidence.png"
    evidence.write_bytes(b"pixels")
    schema = tmp_path / "response.schema.json"
    schema.write_text(SCHEMA_TEXT, encoding="utf-8")
    return cases_dir, tmp_path / "runs", evidence, schema


def test_prompt_generation_works(env) -> None:
    cases_dir, runs_root, evidence, schema = env
    _write_case(cases_dir, evidence)

    cases = load_cases(cases_dir, REPOSITORY_ROOT)
    assert len(cases) == 1
    run_dir = runs_root / "baseline_test"
    written = generate_prompts(cases, "agentX", "baseline_test", run_dir, SCHEMA_TEXT)

    assert [p.name for p in written] == ["agentX_ARB900_fixture.md"]
    prompt = written[0].read_text(encoding="utf-8")
    for section in ("## Benchmark instruction", "## Case description",
                    "## Evidence references", "## Required response schema",
                    "## Forbidden"):
        assert section in prompt
    manifest = json.loads((run_dir / "prompts_manifest.json").read_text(encoding="utf-8"))
    assert manifest["gold_included"] is False
    assert manifest["model_calls"] == 0
    assert manifest["cases"][0]["case_id"] == "ARB900_fixture"


def test_gold_is_not_leaked(env) -> None:
    """Prompts built from the REAL corpus must not contain evaluator-owned
    case fields or any gold-set content string."""

    cases_dir, runs_root, _evidence, _schema = env
    real_cases_dir = REPOSITORY_ROOT / "enza_memory/benchmark/cases"
    cases = load_cases(real_cases_dir, REPOSITORY_ROOT)
    run_dir = runs_root / "baseline_leak"
    written = generate_prompts(cases, "leakcheck", "baseline_leak", run_dir, SCHEMA_TEXT)

    gold_strings: list[str] = []
    for gold_path in sorted((REPOSITORY_ROOT / "enza_memory/benchmark/gold")
                            .glob("case_*_gold.json")):
        gold = json.loads(gold_path.read_text(encoding="utf-8"))
        for key in ("facts", "inferences", "unknowns", "hard_fail_conditions"):
            gold_strings.extend(str(item) for item in gold.get(key, []))
        if gold.get("expected_behavior"):
            gold_strings.append(str(gold["expected_behavior"]))

    for path in written:
        prompt = path.read_text(encoding="utf-8")
        case = next(c for c in cases
                    if c["case_id"] in path.name)
        for rule in case.get("grading_rules", []):
            assert rule not in prompt, f"grading rule leaked into {path.name}"
        for invariant in case.get("expected_invariants", []):
            assert invariant not in prompt, f"invariant leaked into {path.name}"
        for secret in gold_strings:
            assert secret not in prompt, f"gold content leaked into {path.name}"
        assert '"grading_rules"' not in prompt
        assert '"expected_invariants"' not in prompt
        assert "hard_fail_conditions" not in prompt


def test_schema_included(env) -> None:
    cases_dir, _runs_root, evidence, _schema = env
    _write_case(cases_dir, evidence)

    cases = load_cases(cases_dir, REPOSITORY_ROOT)
    prompt = build_prompt(cases[0], "agentX", "baseline_test", SCHEMA_TEXT)

    assert SCHEMA_TEXT in prompt  # verbatim contract embed
    for field in ("decision", "facts", "inferences", "unknowns",
                  "action_allowed", "reason", "confidence"):
        assert f'"{field}"' in prompt
    assert "additionalProperties" in prompt
    for forbidden in ("authority_type", "failure_category", "planner_decision",
                      "execution_permission", "action_permission"):
        assert f"`{forbidden}`" in prompt


def test_case_ids_valid(env) -> None:
    cases_dir, runs_root, evidence, _schema = env
    _write_case(cases_dir, evidence, case_id="ARB901_valid_id")
    _write_case(cases_dir, evidence, case_id="ARB902_also_valid")

    cases = load_cases(cases_dir, REPOSITORY_ROOT)
    run_dir = runs_root / "baseline_ids"
    written = generate_prompts(cases, "agentX", "baseline_ids", run_dir, SCHEMA_TEXT)

    case_ids = {case["case_id"] for case in cases}
    assert len(case_ids) == len(cases)  # unique
    for path in written:
        match = re.fullmatch(r"agentX_(.+)\.md", path.name)
        assert match, f"prompt filename does not match <agent>_<case_id>.md: {path.name}"
        case_id = match.group(1)
        assert case_id in case_ids
        prompt = path.read_text(encoding="utf-8")
        assert f"- case_id: {case_id}" in prompt
    manifest = json.loads((run_dir / "prompts_manifest.json").read_text(encoding="utf-8"))
    assert {entry["case_id"] for entry in manifest["cases"]} == case_ids


def test_fail_closed_on_missing_evidence(env, tmp_path: Path,
                                         capsys: pytest.CaptureFixture[str]) -> None:
    cases_dir, runs_root, evidence, schema = env
    _write_case(cases_dir, evidence)
    ghost = tmp_path / "ghost.png"
    _write_case(cases_dir, ghost, case_id="ARB903_missing_artifact")

    with pytest.raises(BenchmarkPromptError) as excinfo:
        load_cases(cases_dir, REPOSITORY_ROOT)
    assert "not found" in str(excinfo.value)

    exit_code = main(["--agent-name", "agentX", "--run-id", "baseline_fail",
                      "--cases-dir", str(cases_dir), "--schema", str(schema),
                      "--runs-root", str(runs_root)])
    assert exit_code == 1
    assert "PROMPT_GENERATION_FAILED" in capsys.readouterr().err
    assert not (runs_root / "baseline_fail" / "prompts").exists()


def test_runner_has_no_model_or_execution_surface() -> None:
    source = Path(REPOSITORY_ROOT / "tools/run_agent_benchmark.py").read_text(encoding="utf-8")
    for forbidden in ("subprocess", "socket", "urllib", "requests", "http",
                      "openai", "gemini", "anthropic", "eval(", "exec(",
                      "os.system"):
        assert forbidden not in source, f"forbidden surface: {forbidden}"


def test_real_corpus_digests_stable() -> None:
    """The six ARB case files referenced by the frozen gold manifest are
    unchanged (the runner must not modify benchmark cases)."""

    manifest = json.loads(
        (REPOSITORY_ROOT / "enza_memory/benchmark/gold/freeze_manifest.json")
        .read_text(encoding="utf-8")
    )
    for entry in manifest["cases"]:
        for rel_path, digest in entry["inputs_sha256"].items():
            file_path = REPOSITORY_ROOT / rel_path
            assert file_path.exists(), rel_path
            assert hashlib.sha256(file_path.read_bytes()).hexdigest() == digest, rel_path
