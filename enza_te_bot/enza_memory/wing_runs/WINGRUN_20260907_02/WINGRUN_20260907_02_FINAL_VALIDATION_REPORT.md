# WINGRUN_20260907_02 Final Validation Report

## 1. Run Summary

- **Run ID:** `WINGRUN_20260907_02`
- **Game mode:** `W.I.N.G.編 ミドル`
- **Character/unit:** `【ちゃカワ】園田智代子`
- **Final season state:** Season 1 completed; the explicit result screen records Season target rank E achieved. The produce remains active and the post-pass presentation position is unknown; S2 continuation was expected but not freshly observed after the final screenshot stall.
- **Final fan count:** `1,453` fans. The durable run timing records `1,169 -> 1,453 (+284)` at the S1W8 commit.
- **Final result evidence:** `r07_s1w8_exec_rank_screen_final_1453.png` and the related `r07_s1w8_exec_*.png` evidence set show the rank screen with `シーズン目標ランク E`, the 1,000-fan threshold highlighted, `1,453人`, and `一次審査突破`. The durable timing record marks S1W8 as committed with one `決定` click after fresh `0%` trouble-rate verification.

Primary run records: `enza_memory/trajectories/TRAJ_WINGRUN_20260907_02.json` and `enza_memory/wing_runs/WINGRUN_20260907_02/timings.jsonl`.

## 2. Architecture Validation

Verified pipeline:

```text
Planner
↓
Explicit Objective
↓
Executor Mapping
↓
Risk Gate
↓
Fresh Evidence
↓
Action Dispatch
↓
Pending Action Reconciliation
↓
Result Commit
```

| Layer | Status | Evidence source |
|---|---|---|
| Planner | PASS | `timings.jsonl` records planner authority and seven prior planner calls; the S1W8 planner-only step records `home_policy.decide_home` returning `VOCAL` with reason `season_1_final_week_fan_gap_met`. |
| Explicit Objective | PASS | `TRAJ_WINGRUN_20260907_02.json` step `r02_s1w8_planner_decision_only` records the objective and the required fresh-risk read before execution. |
| Executor Mapping | PASS | `timings.jsonl` records `objective=VOCAL` followed by the single S1W8 VOCAL commit; `test_home_tick.py` contains focused objective-to-executor and non-VOCAL blocking cases. |
| Risk Gate | PARTIAL | S1W8 has fresh `トラブル率 0%`, `gate=ALLOW`, and no click before re-verification. Block/fail-closed behavior is covered by regression tests, but this run does not provide a live blocked VOCAL execution path. |
| Fresh Evidence | PASS | `r05_s1w8_gate_schedule.png`, `r05_s1w8_gate_badge_zoom.png`, and `OBS_011.json` record fresh card selection and `0%`; the final commit timing says the precondition was re-verified at click time. |
| Action Dispatch | PASS | `timings.jsonl` records exactly one S1W8 `決定` click after the fresh gate; no duplicate click or retry was recorded. |
| Pending Action Reconciliation | PARTIAL | The run records screenshot stalls and a pre-click interrupted attempt with no business action pending, followed by a no-retry handoff. The broader action-sent/timeout reconciliation invariant is covered offline, but no post-send timeout occurred in this final S1W8 commit. |
| Result Commit | PASS | The explicit rank screen and `一次審査突破` evidence establish S1 completion; the durable record commits the fan total at `1,453` and weeks `1->0`. |

## 3. Major Incidents and Fixes

### S1W6 VOCAL Risk Violation

- Fresh S1W6 evidence showed `trouble_rate ≈92%` while a VOCAL decision was emitted.
- Classification: confirmed policy violation, with separate planner-objective authority and risk-gate authority violations. The incident record states that the executor continued a baseline-VOCAL objective without an attached planner objective and executed despite the authoritative `>2%` hard-gate condition.
- Later fixes recorded in the durable reconciliation and regression artifacts:
  - planner objective required;
  - risk gate given authority over VOCAL dispatch;
  - executor blocking / fail-closed behavior when the objective or fresh risk evidence is absent or unsafe.
- The later state progression does not retroactively validate the emitted action; reconciliation preserved the violation and did not retry it.

Evidence: `enza_memory/failures/s1w6_vocal_executed_above_risk_gate_001.json`, `operator_cancel_pending_action_001.json`, and the offline S1W6 reconciliation under `WINGRUN_20260907_01/offline_reconciliation/`.

### Screenshot Pipeline Stall

- The host screenshot path stalled repeatedly: the tab remained live for title/URL reads, but screenshot capture timed out and the per-tab pending-screenshot latch remained wedged.
- This is a host screenshot limitation and an observation stall, not proof that the game action failed or that game state was damaged.
- The observation boundary fix records `OBSERVATION_UNAVAILABLE`, separates capture failure from game/action failure, and requires fresh observation before recovery or retry. The run’s fourth occurrence was pre-click and therefore had no pending business action.

Evidence: `enza_memory/failures/iab_screenshot_pipeline_stall_001.json`, `test_observation_failure_boundary.py`, and `test_screenshot_pipeline.py`.

### Action Timeout Boundary

- The incident model records the `ACTION_SENT` condition separately from a later observation timeout.
- A timeout after dispatch does not prove action failure and must not trigger a duplicate retry.
- Reconciliation from a fresh stable observation is required before any subsequent action. This boundary is represented in `test_evidence_reconciliation.py` and the pending-action failure records.

## 4. Tests Added

The durable regression inventory records the following focused coverage:

- **Observation failure boundary tests:** 3 tests in `test_observation_failure_boundary.py`.
- **Action reconciliation tests:** 12 tests in `test_evidence_reconciliation.py`, including timeout-without-retry, transition-after-timeout, fresh-observation retry authorization, stale-target rejection, and fail-closed session release.
- **Planner/risk wiring tests:** 6 focused HomeTick cases covering `92%` VOCAL blocking, non-VOCAL objective blocking, unknown trouble-rate fail-closed behavior, objective-to-risk interaction, and recovery routing.
- **Executor mapping tests:** 3 focused HomeTick cases covering `NEEDS_VOCAL_FAN_GAIN` mapping, high-risk REST recovery, and unknown-risk fail-closed mapping; weekly-tool boundary coverage adds 3 tests for fresh-home commit and failure/no-commit behavior.

These are offline regression tests and do not constitute a claim that the host screenshot mechanism was repaired.

## 5. Confirmed Invariants

| Invariant | Status |
|---|---|
| Executor cannot invent VOCAL objective | PASS |
| VOCAL requires fresh risk evidence | PASS |
| Observation timeout cannot prove action failure | PASS |
| Pending action cannot retry without fresh observation | PASS |
| A risk gate passing does not by itself establish the weekly objective | PASS |
| Result commit requires explicit success evidence or a fresh stable reconciliation boundary | PASS |
| A pre-click observation stall does not create a pending business action | PASS |

## 6. Remaining Limitations

- The ZCode host screenshot latch is external to this project.
- This project cannot patch the host screenshot implementation.
- Screenshot reliability remains an external dependency; a live tab can remain responsive while capture is unavailable.
- The final post-pass presentation position is unknown because the last capture stall occurred after the confirmed S1 result and with no business action pending.
- The next S2 opening and any S2 planner objective were not tested in this recovery/validation boundary.

## 7. Benchmark Value

This run is a Computer Use reliability benchmark for:

- **Decision authority:** planner output is represented explicitly and separated from executor dispatch; the S1W6 incident provides a durable negative case for executor self-selection.
- **Evidence grounding:** VOCAL execution required a fresh schedule frame and fresh `0%` trouble-rate evidence at the final commit boundary.
- **Failure recovery:** screenshot stalls were classified as observation failures, recovered or handed off without asserting game failure, and reconciled from durable/fresh state.
- **Action safety:** the final S1W8 action was dispatched once after re-verification; timeout boundaries prohibit blind duplicate retry; explicit result evidence was required before commit.

```text
REPORT_CREATED: YES
FILE: enza_memory/wing_runs/WINGRUN_20260907_02/WINGRUN_20260907_02_FINAL_VALIDATION_REPORT.md
RUNTIME_CHANGED: NO
BUSINESS_POLICY_CHANGED: NO
GAME_CONTACT: NO
```

Final: WINGRUN_VALIDATION_REPORT_COMPLETE
