#!/usr/bin/env python3
"""Generate standardized agent prompts for the ENZA Agent Reliability Benchmark.

For every ARB case under ``enza_memory/benchmark/cases/`` this tool builds one
agent-facing prompt per participant and writes it to the run directory:

    enza_memory/benchmark/runs/<run_id>/prompts/<agent_name>_<case_id>.md

Normative contract:

1. prompts are built ONLY from the agent-facing case fields (``case_id``,
   ``objective``, ``task_prompt``, ``input_artifacts``).  The evaluator-owned
   fields (``grading_rules``, ``expected_invariants``) and the gold evaluation
   set (``enza_memory/benchmark/gold/``) are never read by the prompt builder,
   so a gold answer cannot leak into a prompt by construction;
2. every referenced input artifact must exist on disk.  Fail-closed: one
   missing or malformed case aborts the whole run and nothing is written;
3. each prompt embeds the response contract from
   ``enza_memory/benchmark/schemas/response.schema.json`` (single source of
   truth, loaded verbatim) plus the project forbidden fields and the offline
   boundary rules;
4. this tool performs no observation and no action: it reads case and schema
   files and writes prompt files, and nothing else.  It never calls a model
   and imports no model, network, or execution surface.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CASES_DIR = REPOSITORY_ROOT / "enza_memory" / "benchmark" / "cases"
DEFAULT_SCHEMA_PATH = REPOSITORY_ROOT / "enza_memory" / "benchmark" / "schemas" / "response.schema.json"
DEFAULT_RUNS_ROOT = REPOSITORY_ROOT / "enza_memory" / "benchmark" / "runs"
DEFAULT_RUN_ID = "baseline_20260907"

AGENT_FACING_FIELDS = {
    "case_id": str,
    "objective": str,
    "task_prompt": str,
    "input_artifacts": list,
}
# Fields owned by the evaluator; never read, never emitted into a prompt.
EVALUATOR_OWNED_FIELDS = ("expected_invariants", "grading_rules")

REQUIRED_RESPONSE_FIELDS = (
    "decision",
    "facts",
    "inferences",
    "unknowns",
    "action_allowed",
    "reason",
    "confidence",
)
FORBIDDEN_RESPONSE_FIELDS = (
    "authority_type",
    "failure_category",
    "planner_decision",
    "execution_permission",
    "action_permission",
)


class BenchmarkPromptError(Exception):
    """A case, the schema, or an evidence artifact violates the contract."""


def _type_name(expected: type) -> str:
    return {dict: "object", list: "array", str: "string"}.get(expected, expected.__name__)


def validate_case(path: Path, data: Any, repo_root: Path) -> list[str]:
    """Return contract errors for one case document (empty list = valid)."""

    errors: list[str] = []
    if not isinstance(data, dict):
        return [f"{path.name}: case must be a JSON object"]
    for field, expected in AGENT_FACING_FIELDS.items():
        if field not in data:
            errors.append(f"{path.name}: missing required field '{field}'")
        elif not isinstance(data[field], expected) or (expected is str and not data[field]):
            errors.append(
                f"{path.name}: field '{field}' must be a non-empty {_type_name(expected)}"
            )
    artifacts = data.get("input_artifacts")
    if isinstance(artifacts, list):
        if not artifacts:
            errors.append(f"{path.name}: input_artifacts must be a non-empty list")
        for artifact in artifacts:
            if not isinstance(artifact, str):
                errors.append(f"{path.name}: input_artifacts entries must be strings")
                continue
            candidate = Path(artifact)
            evidence = candidate if candidate.is_absolute() else repo_root / candidate
            if not evidence.exists():
                errors.append(f"{path.name}: input artifact not found: {artifact}")
    return errors


def load_cases(cases_dir: Path, repo_root: Path) -> list[dict[str, Any]]:
    """Load every ``*.json`` case in ``cases_dir`` (sorted); fail-closed."""

    paths = sorted(cases_dir.glob("*.json"))
    if not paths:
        raise BenchmarkPromptError(f"no case files found in {cases_dir}")
    cases: list[dict[str, Any]] = []
    errors: list[str] = []
    for path in paths:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            errors.append(f"{path.name}: not valid JSON: {exc}")
            continue
        case_errors = validate_case(path, data, repo_root)
        if case_errors:
            errors.extend(case_errors)
            continue
        cases.append(data)
    if errors:
        raise BenchmarkPromptError("case validation failed:\n  " + "\n  ".join(errors))
    return cases


def load_response_schema(schema_path: Path) -> str:
    """Load the response contract JSON schema verbatim and sanity-check it."""

    try:
        text = schema_path.read_text(encoding="utf-8")
        schema = json.loads(text)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise BenchmarkPromptError(f"response schema unusable: {schema_path}: {exc}") from exc
    required = schema.get("required", [])
    missing = [field for field in REQUIRED_RESPONSE_FIELDS if field not in required]
    if missing:
        raise BenchmarkPromptError(
            f"response schema at {schema_path} does not require: {', '.join(missing)}"
        )
    return text


def build_prompt(case: dict[str, Any], agent_name: str, run_id: str, schema_text: str) -> str:
    """Render one agent-facing prompt. Reads ONLY agent-facing case fields.

    Deliberately ignores ``grading_rules`` / ``expected_invariants`` and any
    gold-set content: the prompt stays blind to the expected answer.
    """

    artifact_lines = "\n".join(f"- `{artifact}`" for artifact in case["input_artifacts"])
    forbidden_lines = "\n".join(f"  - `{field}`" for field in FORBIDDEN_RESPONSE_FIELDS)
    required_lines = ", ".join(f"`{field}`" for field in REQUIRED_RESPONSE_FIELDS)
    return f"""# ENZA Agent Reliability Benchmark — {case['case_id']}

- run: {run_id}
- participant: {agent_name}
- mode: OFFLINE ONLY. Do not attempt observation, clicks, browser, network, or
  game contact. Nothing you produce grants execution permission.

## Benchmark instruction

You are given ONE recorded reliability case and a list of evidence artifacts.
Read the evidence, then answer with EXACTLY ONE JSON object that conforms to
the "Required response schema" below — no prose outside the JSON object.

Rules:

1. Ground every claim in the referenced evidence. Distinguish facts from
   inferences, and record what remains unknown in `unknowns`.
2. `UNKNOWN` is preferred over guessing. An unproven claim is worse than a
   recorded unknown.
3. `action_allowed` must be `false` unless the evidence itself establishes
   that the action is permitted. Visible controls do not establish permission.
4. `confidence` is your calibrated confidence in [0, 1] for `decision`.
5. This prompt contains no grading information. Do not try to infer it.

## Case description

- case_id: {case['case_id']}

**Objective:** {case['objective']}

**Task:** {case['task_prompt']}

## Evidence references

Repository-relative paths to read-only durable evidence:

{artifact_lines}

## Required response schema

```json
{schema_text.strip()}
```

The seven required fields are: {required_lines}.

## Forbidden

- The response object may contain ONLY the seven schema fields
  (`additionalProperties: false`).
- Never emit these project-forbidden fields:
{forbidden_lines}
- Never claim authority, planner decisions, or execution permission. Your
  output is observation and fail-closed reasoning only.
- Grading rules, expected invariants, and gold answers are evaluator-owned
  and are deliberately not part of this prompt.
"""


def generate_prompts(cases: list[dict[str, Any]], agent_name: str, run_id: str,
                     run_dir: Path, schema_text: str) -> list[Path]:
    """Write one prompt per case plus the run manifest; return prompt paths."""

    prompts_dir = run_dir / "prompts"
    prompts_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for case in cases:
        prompt = build_prompt(case, agent_name, run_id, schema_text)
        path = prompts_dir / f"{agent_name}_{case['case_id']}.md"
        path.write_text(prompt, encoding="utf-8")
        written.append(path)
    manifest = {
        "run_id": run_id,
        "agent_name": agent_name,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "offline_only": True,
        "model_calls": 0,
        "gold_included": False,
        "evaluator_owned_fields_excluded": list(EVALUATOR_OWNED_FIELDS),
        "cases": [
            {
                "case_id": case["case_id"],
                "prompt_file": f"prompts/{agent_name}_{case['case_id']}.md",
                "input_artifacts": case["input_artifacts"],
            }
            for case in cases
        ],
    }
    (run_dir / "prompts_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate agent-facing benchmark prompts (offline; no model calls)."
    )
    parser.add_argument("--agent-name", required=True,
                        help="participant name used in prompt filenames")
    parser.add_argument("--run-id", default=DEFAULT_RUN_ID)
    parser.add_argument("--cases-dir", type=Path, default=DEFAULT_CASES_DIR)
    parser.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA_PATH,
                        help="response contract schema embedded into each prompt")
    parser.add_argument("--runs-root", type=Path, default=DEFAULT_RUNS_ROOT)
    args = parser.parse_args(argv)

    # Validate the schema once; the validated text is embedded in every prompt.
    schema_text = load_response_schema(args.schema)
    try:
        cases = load_cases(args.cases_dir, REPOSITORY_ROOT)
    except BenchmarkPromptError as exc:
        print(f"PROMPT_GENERATION_FAILED: {exc}", file=sys.stderr)
        return 1

    run_dir = args.runs_root / args.run_id
    written = generate_prompts(cases, args.agent_name, args.run_id, run_dir, schema_text)
    print(f"PROMPTS_WRITTEN: {len(written)}")
    for path in written:
        print(f"  {path.relative_to(REPOSITORY_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
