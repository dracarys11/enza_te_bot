# ENZA Benchmark v0.3 — case_202

- benchmark: v0.3
- participant: gemini_3.8-flash
- mode: OFFLINE ONLY

Read only the recorded evidence references below. Do not call models, operate
the game, browse, execute actions, or infer execution permission. Preserve
UNKNOWN whenever the evidence does not establish a fact or outcome.

## Task

Given a crash where original frames are absent and later claims are reconstructed from transcripts, identify which evidence classes remain valid, how they must be cited, and what remains UNKNOWN.

## Evidence references

- enza_memory/wing_runs/WINGRUN_20260906_01/crash_recovery_backfill.json
- enza_memory/wing_runs/WINGRUN_20260906_01/operator_reconcile_20260906_s3w1.json
- enza_memory/artifact_registry.json
- enza_memory/audits/evidence_corpus_gap_report.md

## Required response

Return one JSON object with exactly these fields:

{
  "decision": "...",
  "facts": ["..."],
  "inferences": ["..."],
  "unknowns": ["..."],
  "action_allowed": false,
  "reason": "...",
  "confidence": 0.0
}

The response is observation/evidence reasoning only. Do not emit authority,
planner, execution, click, or next-action fields. Gold answers and evaluator
grading rules are intentionally excluded from this prompt.
