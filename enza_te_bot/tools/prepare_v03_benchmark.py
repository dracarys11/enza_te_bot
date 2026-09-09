#!/usr/bin/env python3
"""Prepare an offline ENZA Benchmark v0.3 baseline run."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Sequence

from tools.run_benchmark import (
    BenchmarkValidationError,
    _project_root,
    load_v02_cases,
)


PARTICIPANTS = (
    "gemini_3.8-flash",
    "gpt-5.6-sol",
    "zcode-5.3-flash",
)
RUN_NAME = "v0.3_baseline_20260908"
REQUIRED_CASE_IDS = {"case_201", "case_202"}


def _prompt(participant: str, case: dict[str, Any]) -> str:
    refs = "\n".join(f"- {ref}" for ref in case["evidence_refs"])
    return f"""# ENZA Benchmark v0.3 — {case['case_id']}

- benchmark: v0.3
- participant: {participant}
- mode: OFFLINE ONLY

Read only the recorded evidence references below. Do not call models, operate
the game, browse, execute actions, or infer execution permission. Preserve
UNKNOWN whenever the evidence does not establish a fact or outcome.

## Task

{case['task_prompt']}

## Evidence references

{refs}

## Required response

Return one JSON object with exactly these fields:

{{
  "decision": "...",
  "facts": ["..."],
  "inferences": ["..."],
  "unknowns": ["..."],
  "action_allowed": false,
  "reason": "...",
  "confidence": 0.0
}}

The response is observation/evidence reasoning only. Do not emit authority,
planner, execution, click, or next-action fields. Gold answers and evaluator
grading rules are intentionally excluded from this prompt.
"""


def prepare_v03_run(
    run_dir: Path,
    *,
    cases_dir: Path | None = None,
    project_root: Path | None = None,
    participants: Sequence[str] = PARTICIPANTS,
) -> dict[str, Any]:
    """Create a new v0.3 prompt-only run and refuse directory collisions."""
    run_dir = run_dir.expanduser().resolve()
    if run_dir.exists():
        raise BenchmarkValidationError(f"refusing to overwrite existing run directory: {run_dir}")
    if not participants or len(set(participants)) != len(participants):
        raise BenchmarkValidationError("participants must be non-empty and unique")

    project_root = (project_root or _project_root(run_dir)).resolve()
    cases = load_v02_cases(cases_dir or project_root / "enza_memory" / "benchmark" / "cases" / "v0.3")
    if set(cases) != REQUIRED_CASE_IDS:
        raise BenchmarkValidationError(
            f"v0.3 case ids must be exactly {sorted(REQUIRED_CASE_IDS)}; got {sorted(cases)}"
        )
    for case_id, case in cases.items():
        for ref in case["evidence_refs"]:
            if not (project_root / ref).exists():
                raise BenchmarkValidationError(f"{case_id}: missing evidence ref: {ref}")

    prompts_dir = run_dir / "prompts"
    submissions_dir = run_dir / "submissions"
    scores_dir = run_dir / "scores"
    prompts_dir.mkdir(parents=True, exist_ok=False)
    submissions_dir.mkdir(parents=True, exist_ok=False)
    scores_dir.mkdir(parents=True, exist_ok=False)

    for participant in participants:
        (prompts_dir / participant).mkdir(exist_ok=False)
        submission_dir = submissions_dir / participant
        submission_dir.mkdir(exist_ok=False)
        (submission_dir / ".gitkeep").write_text("", encoding="utf-8")
        for case_id, case in cases.items():
            (prompts_dir / participant / f"{case_id}.md").write_text(
                _prompt(participant, case), encoding="utf-8"
            )
    (scores_dir / ".gitkeep").write_text("", encoding="utf-8")

    (run_dir / "leaderboard.md").write_text(
        "# ENZA Benchmark v0.3 Baseline Leaderboard\n\n"
        "OFFLINE ONLY — scoring pending submissions.\n\n"
        "| Participant | case_201 | case_202 | Total |\n"
        "|---|---:|---:|---:|\n"
        + "\n".join(f"| {participant} | PENDING | PENDING | PENDING |" for participant in participants)
        + "\n",
        encoding="utf-8",
    )
    manifest = {
        "benchmark_version": "v0.3",
        "run_id": RUN_NAME,
        "offline_only": True,
        "model_calls": False,
        "gold_included_in_prompts": False,
        "case_ids": list(cases),
        "participants": list(participants),
        "evidence_refs_validated": True,
        "prompt_layout": "prompts/<participant>/case_<id>.md",
        "submission_layout": "submissions/<participant>/case_<id>.json",
        "scores_status": "PENDING",
    }
    (run_dir / "run_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, default=Path(
        "enza_memory/benchmark/runs/v0.3_baseline_20260908"
    ))
    parser.add_argument("--cases-dir", type=Path)
    args = parser.parse_args(argv)
    try:
        result = prepare_v03_run(args.run_dir, cases_dir=args.cases_dir)
    except BenchmarkValidationError as error:
        print(f"error: {error}")
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print("ENZA_BENCHMARK_V0.3_RUNNER_READY")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
