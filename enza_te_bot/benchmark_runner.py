"""Offline benchmark runner for benchmark_cases/ (evaluation framework v0.1).

Loads every ``benchmark_cases/case_*.json``, validates it against the case
contract, and generates per-case evaluation templates plus a run manifest
under ``benchmark_results/``.  This module is the normative offline evaluation
boundary for the regression corpus mined from enza_memory failures:

1. every ``case_*.json`` must parse and satisfy the case schema (required
   fields, artifact_type BENCHMARK_CASE, schema_version 1, case_id bound to
   the filename);
2. every referenced input evidence must exist at its recorded path (resolved
   against the repository root) and every recorded sha256 digest must match
   the bytes on disk -- stale or re-encoded evidence fails validation;
3. a run directory is written ONLY when every case validates (fail-closed:
   one broken case blocks template generation and exits non-zero);
4. the runner performs no observation and no action: it reads case/evidence
   files and writes evaluation records, and nothing else.  It imports no
   execution, network, or automation surface;
5. templates are executor-agnostic.  ``--executor {vlm,agent,human}`` tags
   who fills ``actual_behavior`` / ``pass/fail``; the expected_behavior and
   grading sections are marked as evaluator reference and must not be shown
   to a system under test before its answer is recorded.

Validation verdict, case listing, and the sentinel line are printed to
stdout so a session transcript is itself the run report.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parent
DEFAULT_CASES_DIR = REPOSITORY_ROOT / "benchmark_cases"
DEFAULT_RESULTS_DIR = REPOSITORY_ROOT / "benchmark_results"

ARTIFACT_TYPE = "BENCHMARK_CASE"
SCHEMA_VERSION = 1
EXECUTORS = ("vlm", "agent", "human")

SENTINEL_CREATED = "ENZA_BENCHMARK_RUNNER_CREATED"

REQUIRED_TOP_LEVEL = {
    "schema_version": int,
    "artifact_type": str,
    "case_id": str,
    "title": str,
    "status": str,
    "failure_class": str,
    "failure_provenance": dict,
    "scenario": dict,
    "inputs": list,
    "expected_behavior": dict,
    "grading": dict,
    "invariants_tested": list,
    "provenance": dict,
}

REQUIRED_INPUT_FIELDS = {
    "evidence_id": str,
    "kind": str,
    "path": str,
    "classification": str,
}


class BenchmarkValidationError(Exception):
    """A case file violates the case contract or its evidence is unbound."""


@dataclass
class CaseValidation:
    """Validation outcome for one case file; ``errors`` empty means valid."""

    path: Path
    case_id: str
    failure_class: str
    input_count: int
    digests_verified: int
    data: dict[str, Any] | None
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def _type_name(expected: type) -> str:
    return {dict: "object", list: "array", str: "string", int: "integer"}.get(expected, expected.__name__)  # type: ignore[dict-item]


def _check_fields(where: str, obj: Any, required: dict[str, type], errors: list[str]) -> None:
    if not isinstance(obj, dict):
        errors.append(f"{where}: expected object, got {type(obj).__name__}")
        return
    for name, expected in required.items():
        if name not in obj:
            errors.append(f"{where}: missing required field '{name}'")
        elif not isinstance(obj[name], expected) or (
            expected is int and isinstance(obj[name], bool)
        ):
            errors.append(
                f"{where}: field '{name}' must be {_type_name(expected)}, "
                f"got {type(obj[name]).__name__}"
            )


def validate_case_data(path: Path, data: Any, repo_root: Path) -> CaseValidation:
    """Validate one parsed case document against the case contract."""

    case_id = path.stem
    errors: list[str] = []
    failure_class = ""
    input_count = 0
    digests_verified = 0

    _check_fields(f"{path.name}", data, REQUIRED_TOP_LEVEL, errors)
    if errors:
        return CaseValidation(path, case_id, failure_class, input_count,
                              digests_verified, None, errors)

    assert data is not None
    if data["schema_version"] != SCHEMA_VERSION:
        errors.append(f"{path.name}: unsupported schema_version {data['schema_version']!r}")
    if data["artifact_type"] != ARTIFACT_TYPE:
        errors.append(f"{path.name}: artifact_type must be {ARTIFACT_TYPE!r}")
    if data["case_id"] != case_id:
        errors.append(f"{path.name}: case_id {data['case_id']!r} does not match filename")
    failure_class = data["failure_class"]

    source_failures = data["failure_provenance"].get("source_failures")
    if not isinstance(source_failures, list) or not source_failures:
        errors.append(f"{path.name}: failure_provenance.source_failures must be a non-empty list")

    scenario = data["scenario"]
    _check_fields(f"{path.name}.scenario", scenario,
                  {"role_of_system_under_test": str, "situation": str, "question": str}, errors)

    inputs = data["inputs"]
    if not inputs:
        errors.append(f"{path.name}: inputs must be a non-empty list")
    for index, inp in enumerate(inputs):
        where = f"{path.name}.inputs[{index}]"
        _check_fields(where, inp, REQUIRED_INPUT_FIELDS, errors)
        if not isinstance(inp, dict) or "path" not in inp:
            continue
        input_count += 1
        raw_path = Path(inp["path"])
        evidence = raw_path if raw_path.is_absolute() else repo_root / raw_path
        if not evidence.is_file():
            errors.append(f"{where}: evidence not found: {inp['path']}")
            continue
        integrity = inp.get("integrity") or {}
        if integrity.get("algorithm") == "sha256" and integrity.get("digest"):
            digest = hashlib.sha256(evidence.read_bytes()).hexdigest()
            digests_verified += 1
            if digest != integrity["digest"]:
                errors.append(
                    f"{where}: sha256 mismatch for {inp['path']} "
                    f"(recorded {integrity['digest']}, actual {digest})"
                )

    expected = data["expected_behavior"]
    _check_fields(f"{path.name}.expected_behavior", expected,
                  {"FACT": list, "required_decision": str, "UNKNOWN": list}, errors)
    if isinstance(expected, dict) and not expected.get("FACT"):
        errors.append(f"{path.name}: expected_behavior.FACT must be a non-empty list")

    grading = data["grading"]
    _check_fields(f"{path.name}.grading", grading,
                  {"pass": list, "hard_fail": list}, errors)
    if isinstance(grading, dict):
        if not grading.get("pass"):
            errors.append(f"{path.name}: grading.pass must be a non-empty list")
        if not grading.get("hard_fail"):
            errors.append(f"{path.name}: grading.hard_fail must be a non-empty list")

    if not data["invariants_tested"]:
        errors.append(f"{path.name}: invariants_tested must be a non-empty list")
    if data["provenance"].get("no_environment_contact") is not True:
        errors.append(
            f"{path.name}: provenance.no_environment_contact must be true "
            "(benchmark cases are offline-derived records)"
        )

    return CaseValidation(path, case_id, failure_class, input_count,
                          digests_verified, data, errors)


def load_cases(cases_dir: Path, repo_root: Path) -> list[CaseValidation]:
    """Load and validate every case_*.json in ``cases_dir`` (sorted by name).

    A file that fails to parse becomes an invalid CaseValidation carrying the
    decode error; a missing cases directory yields no cases at all, which the
    caller treats as a validation failure (nothing to benchmark).
    """

    results: list[CaseValidation] = []
    for path in sorted(cases_dir.glob("case_*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            results.append(CaseValidation(path, path.stem, "", 0, 0, None,
                                          [f"{path.name}: not valid JSON: {exc}"]))
            continue
        results.append(validate_case_data(path, data, repo_root))
    return results


def render_report(validations: list[CaseValidation]) -> str:
    """Render the BENCHMARK_CASES / VALIDATION stdout report blocks."""

    lines = ["BENCHMARK_CASES:"]
    for v in validations:
        status = "OK" if v.ok else "INVALID"
        lines.append(
            f"  [{status}] {v.case_id} ({v.failure_class or '?'}, "
            f"inputs={v.input_count}, digests={v.digests_verified})"
        )
        for error in v.errors:
            lines.append(f"         - {error}")
    if not validations:
        lines.append("  (no case_*.json found)")

    total_inputs = sum(v.input_count for v in validations)
    total_digests = sum(v.digests_verified for v in validations)
    valid_cases = sum(1 for v in validations if v.ok)
    verdict = "ALL_PASS" if validations and valid_cases == len(validations) else "FAIL"
    lines.extend([
        "VALIDATION:",
        f"  cases_loaded: {len(validations)}",
        f"  schema_valid: {valid_cases}/{len(validations)}",
        f"  evidence_exists: "
        f"{total_inputs - sum(1 for v in validations for e in v.errors if 'not found' in e)}"
        f"/{total_inputs}",
        f"  sha256_verified: {total_digests}",
        f"  verdict: {verdict}",
    ])
    return "\n".join(lines)


def _bullet_list(items: list[str]) -> str:
    return "\n".join(f"- {item}" for item in items)


def render_template(validation: CaseValidation, run_id: str, executor: str,
                    generated_at: str) -> str:
    """Render one evaluator-facing markdown template for a validated case."""

    data = validation.data
    assert data is not None  # templates are only generated for valid cases
    scenario = data["scenario"]
    expected = data["expected_behavior"]
    grading = data["grading"]
    input_rows = "\n".join(
        f"| {inp['evidence_id']} | {inp['kind']} | `{inp['path']}` | "
        f"{'yes' if (inp.get('integrity') or {}).get('digest') else 'n/a'} |"
        for inp in data["inputs"]
    )
    return f"""# Benchmark evaluation — {validation.case_id}

- run_id: {run_id}
- executor: {executor}
- generated_at: {generated_at}
- offline_only: YES — this record authorizes no observation and no action.

## case_id

{validation.case_id}

## scenario

**Role of system under test:** {scenario['role_of_system_under_test']}

**Situation:** {scenario['situation']}

**Question:** {scenario['question']}

## inputs

| evidence_id | kind | path | sha256 bound |
|---|---|---|---|
{input_rows}

## expected_behavior (evaluator reference — do not disclose before the answer is recorded)

**FACT:**

{_bullet_list(expected['FACT'])}

**required_decision:** {expected['required_decision']}

**INFERENCE:** {_bullet_list(expected.get('INFERENCE', [])) or '- (none recorded)'}

**UNKNOWN:**

{_bullet_list(expected['UNKNOWN'])}

## grading reference (evaluator only)

**pass:**

{_bullet_list(grading['pass'])}

**hard_fail (automatic fail):**

{_bullet_list(grading['hard_fail'])}

## actual_behavior

PENDING — to be filled by executor: {executor}

## pass/fail

PENDING
"""


def write_run(cases_dir: Path, validations: list[CaseValidation], results_dir: Path,
              executor: str, repo_root: Path) -> Path:
    """Write the run directory (templates + manifest) and return its path.

    Caller must have confirmed every validation is OK; this function does not
    re-check and never mixes results from a failed validation into a run.
    """

    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    run_id = f"run_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}_{executor}"
    run_dir = results_dir / run_id
    suffix = 1
    while run_dir.exists():
        run_dir = results_dir / f"{run_id}-{suffix}"
        suffix += 1
    run_dir.mkdir(parents=True)

    for validation in validations:
        assert validation.data is not None
        template = render_template(validation, run_dir.name, executor, generated_at)
        (run_dir / f"eval_{validation.case_id}.md").write_text(template, encoding="utf-8")

    manifest = {
        "run_id": run_dir.name,
        "executor": executor,
        "generated_at": generated_at,
        "offline_only": True,
        "execution_performed": False,
        "cases_dir": str(cases_dir.relative_to(repo_root)),
        "verdict": "ALL_PASS",
        "results": [
            {
                "case_id": v.case_id,
                "failure_class": v.failure_class,
                "inputs": v.input_count,
                "sha256_verified": v.digests_verified,
                "validation": "PASS",
                "actual_behavior": "PENDING",
                "pass_fail": "PENDING",
            }
            for v in validations
        ],
    }
    (run_dir / "run_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return run_dir


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Offline benchmark runner: validate benchmark_cases and "
                    "generate evaluation templates. Performs no observation "
                    "and no action."
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("validate", help="load and validate every case; write nothing")
    gen = sub.add_parser("generate", help="validate, then write a benchmark_results run")
    gen.add_argument("--executor", required=True, choices=EXECUTORS,
                     help="who fills actual_behavior / pass-fail in the templates")
    gen.add_argument("--results-dir", type=Path, default=DEFAULT_RESULTS_DIR)
    args = parser.parse_args(argv)

    cases_dir = DEFAULT_CASES_DIR
    validations = load_cases(cases_dir, REPOSITORY_ROOT)
    report = render_report(validations)
    print(report)

    all_ok = bool(validations) and all(v.ok for v in validations)
    if args.command == "validate":
        return 0 if all_ok else 1

    if not all_ok:
        print("generate: refused — validation FAIL is fail-closed, nothing written",
              file=sys.stderr)
        return 1
    run_dir = write_run(cases_dir, validations, args.results_dir, args.executor,
                        REPOSITORY_ROOT)
    print(f"RUN_WRITTEN: {run_dir.relative_to(REPOSITORY_ROOT)}")
    print(SENTINEL_CREATED)
    return 0


if __name__ == "__main__":
    sys.exit(main())
