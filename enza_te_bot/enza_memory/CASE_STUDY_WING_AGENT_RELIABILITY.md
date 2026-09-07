# Case Study: WING Agent Reliability

## 1. Initial Failure

During S1W6, the agent executed a VOCAL action while the fresh schedule evidence showed a `trouble_rate` of approximately `92%`. This violated the authoritative VOCAL risk condition.

The underlying reliability failure was authority separation: the executor continued a baseline VOCAL objective without an explicitly attached planner objective and was able to emit the semantic action itself. The action was sent, and later reconciliation preserved the violation rather than reinterpreting it as valid because the game progressed.

Evidence: `enza_memory/failures/s1w6_vocal_executed_above_risk_gate_001.json` and the WINGRUN S1W6 offline reconciliation artifacts.

## 2. Fixes

The durable engineering fixes and regression constraints established after the incident were:

- **Planner objective enforcement:** weekly objectives must be explicit and planner-owned; the executor cannot invent or replace the objective.
- **VOCAL risk gate:** VOCAL dispatch requires fresh risk evidence. An unsafe or unknown trouble rate fails closed; the recorded hard threshold is `2%`.
- **Observation boundary:** screenshot timeout, capture error, or stale observation is recorded as `OBSERVATION_UNAVAILABLE`. It is not converted into a claim that the game or action failed.
- **Pending action reconciliation:** after an action may have been sent, recovery must obtain fresh stable evidence and reconcile the resulting state before any further semantic action. A timeout does not authorize a duplicate retry.

Evidence: `enza_memory/failures/iab_screenshot_pipeline_stall_001.json`, `enza_memory/failures/operator_cancel_pending_action_001.json`, `test_observation_failure_boundary.py`, and `test_evidence_reconciliation.py`.

## 3. Validation

`WINGRUN_20260907_02` validated the guarded final-week path:

- W8 VOCAL was selected only after fresh schedule re-verification.
- Fresh `trouble_rate` was `0%`; the risk gate recorded `ALLOW`.
- Exactly one `決定` click was recorded for the W8 commit.
- The explicit result screen recorded Season 1 rank **E** target clear.
- Final fans were **1,453**, increasing from `1,169` by `284`.

The final post-pass presentation later encountered a screenshot pipeline stall, but no business action was pending at that boundary. The result itself was already established by explicit rank-screen evidence.

Evidence: `enza_memory/wing_runs/WINGRUN_20260907_02/timings.jsonl`, `enza_memory/trajectories/TRAJ_WINGRUN_20260907_02.json`, and the `r07_s1w8_exec_*` screenshots.

## 4. Engineering Lessons

- **Observation failure is not action failure.** A host screenshot timeout describes the evidence channel, not the game transaction.
- **Visual evidence is not action authority.** Seeing a control does not authorize clicking it; objective ownership, risk permission, and a valid action boundary are separate requirements.
- **Planner is not executor.** The planner selects the objective; the executor maps and dispatches only an approved objective.
- **Recovery must reconcile, not retry.** When action outcome is uncertain, obtain fresh stable state, reconcile what happened, and only then consider a new action.

```text
OFFLINE_ONLY: YES
CODE_CHANGES: NO
RUNTIME_CHANGED: NO
```

Final: CASE_STUDY_CREATED
