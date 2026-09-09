# ENZA Benchmark v0.2 — case_105

- benchmark: v0.2
- participant: gemini_3.8-flash
- mode: OFFLINE ONLY

Do not operate the game, call tools, call models, browse, execute actions,
or infer execution permission. This is a recorded-evidence reasoning task.

## Task

Given a burst cell declared for 115000 ms despite approximately 5 seconds per click and screenshot waits that may hang, decide how to size the batch and what to do after a mid-business-sequence timeout.

## Objective

Evaluate measured latency budgeting and reconciliation of unsettled in-flight actions after a mid-batch timeout.

## Evidence references

Read only the following repository-relative evidence artifacts:

- `enza_memory/wing_runs/WINGRUN_20260905_01/timeout_debug_report.json`
- `enza_memory/wing_runs/WINGRUN_20260905_01/weekly_trace.jsonl`
- `.agent-harness/GATES.md`

Ground every claim in those records. Preserve UNKNOWN when the records do
not establish an outcome, authority, interactability, or permission. Do not
invent failures or convert observation into action permission.

## Required response

Return exactly one JSON object with these fields and no others:

{
  "decision": "...",
  "facts": ["..."],
  "inferences": ["..."],
  "unknowns": ["..."],
  "action_allowed": false,
  "reason": "...",
  "confidence": 0.0
}

`action_allowed` must remain false for this offline benchmark. The prompt
does not include gold answers or evaluator-owned grading rules.
