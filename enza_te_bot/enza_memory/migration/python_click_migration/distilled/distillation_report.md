# Python Runtime Live-Evidence Distillation

Generated: 2026-09-06T06:22:51Z

This directory contains normalized evidence for a future local Python executor. It does not change runtime, policy, Harness, Skill, historical traces, or game state. Every proposed control remains a shadow-test candidate until its missing geometry and detector evidence is collected.

## Evidence reviewed

Priority order was live screenshot/tool evidence, raw trace, recovered crash transcript, then derived summaries.

- `WINGRUN_20260905_01`: 42 raw `weekly_trace.jsonl` events, screenshots, unexpected events, battle inspection, timeout report, final outcome, and existing control/transition distillation.
- `WINGVAL_20260905_01`: two independent normal-week validation loops, four guarded core controls, and latency evidence.
- `WINGRUN_20260906_01`: seven original timing records through S1W6, the separately classified crash-recovery chain through fresh S3 start, and one later operator-reconciled S3W1 completion record.
- `python_click_migration`: 10 seeded click samples, seven transient-timing records, viewport profile, and current migration blockers.
- Crash transcript `sess_dc58a91a` was used only where durable evidence stopped; its recovered facts remain separately classified in `crash_recovery_backfill.json`.

No historical artifact was edited by this distillation. During final validation, `timings.jsonl` was concurrently appended from seven to eight lines with `S3W1_COMMIT_OPERATOR_RECONCILED` (recorded timestamp `2026-09-06T07:05:00Z`). The new line supports a week-level VOCAL completion to S3 weeks=7 but explicitly says it is not autonomous-detector replication, so no individual control was promoted from it.

## Distilled inventory

- 20 requested controls are present in `control_evidence_matrix.json`.
- 10 repeated transition chains are normalized in `stable_transition_chains.json`.
- 13 negative/hazard patterns are normalized in `hazard_map.json`.
- Timing is split into nine game-transition records and six tool-latency records.
- Battle inventory contains 11 instances: S1 final (1), S2 final (1), S3 40k (3), S3 50k (1), and THE LEGEND (5).

## Geometry versus authority

The strongest controls have proven viewport-relative points at 1280×720, but no core control has a captured normalized visual box or proven click box. A stable point therefore does not authorize a click.

`SCHEDULE:VOCAL` is the clearest example: its taught point and visual anchor replicate, but action authority additionally requires a fresh, current failure-rate observation of 2% or less. `AUDITION_BATTLE:AUTO` similarly requires current-epoch `INPUT_READY + OFF + ENABLED`; its visible value alone is insufficient.

No control is marked production-ready. The readiness scores only prioritize shadow testing.

## Stable execution material

The best-supported chains are:

1. Fresh WING HOME → SCHEDULE → loaded SCHEDULE.
2. Fresh eligible VOCAL selection → DECIDE → lesson/result → fresh HOME with weeks decremented.
3. Fresh known dialogue → bounded textbox progression, stopping on choice or HOME.
4. Fresh three-choice context → middle option → verified progression.
5. Fresh `INPUT_READY + AUTO_OFF + ENABLED` → one click → fresh `AUTO_ON`.
6. THE LEGEND selection → battle → explicit PASS/FAIL → fresh HOME weeks decrement, scoped only to THE LEGEND.

The risk-gated `SCHEDULE -> BACK -> HOME -> REST` chain passed once and is suitable for shadow instrumentation, not promotion.

## Negative evidence that must become test fixtures

- `(985,663)` on SCHEDULE opens Support Skill and is not a safe dialogue-advance point.
- `(205,655)` after dialogue termination can open FURIKAERI.
- DECIDE during schedule loading produces no effect.
- AUTO during dialogue/animation is disabled even if `OFF` is readable.
- The X2 badge is a display, not a grounded speed toggle.
- Advancing result presentation before capture loses commit evidence.
- Multi-click browser-tool batches were under-budgeted because each click cost about five seconds.
- Screenshot capture can time out at 30 seconds during animation/dialogue.
- WINGRUN_20260906_01 proves a week/season persistence gap can outlive the process.

## Timing interpretation

Browser CUA timing is not Python injection timing. The measured click median was 5,047 ms and p90 5,095 ms for four samples; this explains historical tool-cell timeouts but must not be used as a native executor estimate. Stable screenshots had a 339 ms median across the three explicit comparable samples, while animation/dialogue screenshots may hit 30 seconds.

The validated normal-week loop was about 39 seconds, but compute was about 1.3 seconds for HOME observation plus 4.5 seconds for guards; execution and game presentation dominated. This migration should optimize evidence ownership and local control latency without treating game animation as compute cost.

## Battle boundary

AUTO value and interactability stay separate. Only a fresh current-epoch `OFF + ENABLED` observation at `INPUT_READY` can authorize one toggle, followed by a fresh `ON` verification. Pause/resume starts a new epoch and invalidates AUTO, SPEED, turn, and selected-card observations.

Speed-state recognition is supported, but the toggle control remains HOLD and the X3 handler remains PARTIAL. Manual Vocal-card fallback remains a run-local emergency observation and is excluded.

Result flags require explicit evidence. THE LEGEND failures, the first 40k failure, and the 40k evidence-loss attempt did not commit success. The S3 40k and 50k successes had explicit evidence. Semifinal result and the final +5,000 fan source remain UNKNOWN.

## First shadow-test bundle

The proposed v0.1 bundle contains nine controls: HOME:SCHEDULE, SCHEDULE:VOCAL, SCHEDULE:DECIDE, RESULT:ADVANCE, DIALOGUE:SAFE_TEXTBOX, DIALOGUE:3_CHOICE_MIDDLE, SCHEDULE:BACK, HOME:REST, and AUDITION_BATTLE:AUTO.

Before any click-capable migration, the bundle must verify viewport origin/size, device pixel ratio, browser zoom, normalized visual boxes, state anchors, and postconditions. Other resolutions require re-teaching rather than coordinate scaling.

## Required new live evidence

- Fresh normalized visual/proven click boxes for every bundle control.
- Verified game-viewport origin, DPR, zoom, and browser-to-game coordinate mapping.
- A second independent BACK→HOME→REST replication.
- Cross-session AUTO epoch replication, including pause/resume.
- A separately grounded speed toggle if X3 automation remains desired.
- More pause/resume samples.
- Long-press automation remains PARTIAL and should not enter the first bundle.

Harness change is not required. Skill change is not required.
