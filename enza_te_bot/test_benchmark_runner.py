"""Regression tests for the offline benchmark runner.

- TEST_VALID_CASE_PASSES_VALIDATION
- TEST_MISSING_EVIDENCE_DETECTED
- TEST_DIGEST_MISMATCH_DETECTED
- TEST_SCHEMA_VIOLATION_DETECTED
- TEST_GENERATE_WRITES_TEMPLATES_AND_MANIFEST
- TEST_GENERATE_FAILS_CLOSED_ON_INVALID_CASE
- TEST_RUNNER_HAS_NO_EXECUTION_SURFACE

All tests are offline: cases and evidence are fakes under tmp_path; no
browser, no game, no network, no subprocess.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import benchmark_runner
from benchmark_runner import (
    ARTIFACT_TYPE,
    SCHEMA_VERSION,
    SENTINEL_CREATED,
    load_cases,
    main,
    write_run,
)


def _write_case(cases_dir: Path, evidence: Path, **overrides) -> Path:
    """Write a minimal valid case with one digest-bound fake evidence file."""

    digest = hashlib.sha256(evidence.read_bytes()).hexdigest()
    case = {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": ARTIFACT_TYPE,
        "case_id": "case_001_example",
        "title": "example case",
        "status": "CANDIDATE",
        "failure_class": "EXAMPLE_CLASS",
        "failure_provenance": {"source_failures": ["enza_memory/failures/some_001.json"]},
        "scenario": {
            "role_of_system_under_test": "decision agent",
            "situation": "a situation",
            "question": "a question?",
        },
        "inputs": [
            {
                "evidence_id": "fake.png",
                "kind": "SCREENSHOT",
                "path": str(evidence),
                "classification": "FACT",
                "integrity": {"algorithm": "sha256", "digest": digest},
            }
        ],
        "expected_behavior": {
            "FACT": ["some fact"],
            "required_decision": "refuse",
            "UNKNOWN": ["some unknown"],
        },
        "grading": {"pass": ["declines"], "hard_fail": ["executes anyway"]},
        "invariants_tested": ["SOME_INVARIANT"],
        "provenance": {
            "classification": "derived_from_durable_records",
            "no_environment_contact": True,
        },
    }
    case.update(overrides)
    path = cases_dir / f"{case['case_id']}.json"
    path.write_text(json.dumps(case), encoding="utf-8")
    return path


@pytest.fixture()
def env(tmp_path: Path) -> tuple[Path, Path, Path]:
    cases_dir = tmp_path / "benchmark_cases"
    cases_dir.mkdir()
    evidence = tmp_path / "evidence.png"
    evidence.write_bytes(b"pixels")
    return cases_dir, tmp_path, evidence


def test_valid_case_passes_validation(env) -> None:
    cases_dir, root, evidence = env
    _write_case(cases_dir, evidence)

    validations = load_cases(cases_dir, root)

    assert len(validations) == 1
    assert validations[0].ok, validations[0].errors
    assert validations[0].digests_verified == 1


def test_missing_evidence_detected(env) -> None:
    cases_dir, root, evidence = env
    path = _write_case(cases_dir, evidence)
    evidence.unlink()

    validations = load_cases(cases_dir, root)

    assert not validations[0].ok
    assert any("not found" in e for e in validations[0].errors)
    assert path.exists()  # the runner never deletes case files


def test_digest_mismatch_detected(env) -> None:
    cases_dir, root, evidence = env
    path = _write_case(cases_dir, evidence)
    evidence.write_bytes(b"re-encoded pixels")  # same path, different bytes

    case = json.loads(path.read_text(encoding="utf-8"))
    validations = load_cases(cases_dir, root)
    assert not validations[0].ok
    assert any("sha256 mismatch" in e for e in validations[0].errors)
    assert case["inputs"][0]["integrity"]["algorithm"] == "sha256"


def test_schema_violation_detected(env) -> None:
    cases_dir, root, evidence = env
    path = _write_case(cases_dir, evidence)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["artifact_type"] = "SOMETHING_ELSE"
    data["case_id"] = "case_999_mismatched"  # content no longer binds to filename
    path.write_text(json.dumps(data), encoding="utf-8")

    validations = load_cases(cases_dir, root)

    assert len(validations) == 1
    errors = " | ".join(validations[0].errors)
    assert "artifact_type" in errors
    assert "does not match filename" in errors


def test_generate_writes_templates_and_manifest(env, tmp_path: Path) -> None:
    cases_dir, root, evidence = env
    _write_case(cases_dir, evidence)
    results_dir = tmp_path / "benchmark_results"

    validations = load_cases(cases_dir, root)
    assert all(v.ok for v in validations)
    run_dir = write_run(cases_dir, validations, results_dir, "human", root)

    manifest = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
    assert manifest["executor"] == "human"
    assert manifest["offline_only"] is True
    assert manifest["execution_performed"] is False
    assert manifest["verdict"] == "ALL_PASS"
    assert manifest["results"][0]["pass_fail"] == "PENDING"

    template = (run_dir / "eval_case_001_example.md").read_text(encoding="utf-8")
    for section in ("## case_id", "## scenario", "## expected_behavior",
                    "## actual_behavior", "## pass/fail"):
        assert section in template
    assert "PENDING — to be filled by executor: human" in template


def test_generate_fails_closed_on_invalid_case(env, tmp_path: Path,
                                               capsys: pytest.CaptureFixture[str]) -> None:
    cases_dir, root, evidence = env
    good = _write_case(cases_dir, evidence)
    broken = _write_case(cases_dir, evidence, case_id="case_002_broken")
    data = json.loads(broken.read_text(encoding="utf-8"))
    data["grading"]["hard_fail"] = []
    broken.write_text(json.dumps(data), encoding="utf-8")
    results_dir = tmp_path / "benchmark_results"

    exit_code = main(["generate", "--executor", "vlm",
                      "--results-dir", str(results_dir)])

    assert exit_code == 1
    assert "verdict: FAIL" in capsys.readouterr().out
    assert not results_dir.exists()  # fail-closed: nothing written
    assert good.exists() and broken.exists()


def test_runner_has_no_execution_surface() -> None:
    """The runner must stay observation/action free: no automation, network,
    or process imports anywhere in its source."""

    source = Path(benchmark_runner.__file__).read_text(encoding="utf-8")
    for forbidden in ("subprocess", "socket", "urllib", "requests",
                      "pyautogui", "os.system", "eval(", "exec("):
        assert forbidden not in source, f"forbidden surface: {forbidden}"
    assert SENTINEL_CREATED == "ENZA_BENCHMARK_RUNNER_CREATED"
