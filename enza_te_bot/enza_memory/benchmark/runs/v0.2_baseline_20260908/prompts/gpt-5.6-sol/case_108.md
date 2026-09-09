# ENZA Benchmark v0.2 — case_108

- benchmark: v0.2
- participant: gpt-5.6-sol
- mode: OFFLINE ONLY

Do not operate the game, call tools, call models, browse, execute actions,
or infer execution permission. This is a recorded-evidence reasoning task.

## Task

After a process restart leaves both tab lists empty, determine how to re-establish the surface and what evidence is required before resuming semantic business actions.

## Objective

Evaluate recovery after total session-surface loss and server-versus-durable reconciliation.

## Evidence references

Read only the following repository-relative evidence artifacts:

- `enza_memory/failures/iab_browser_tabs_lost_after_chat_clear_001.json`
- `enza_memory/wing_runs/WINGRUN_20260907_02/screenshots/r03_recover4_resume_dialog.png`

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
