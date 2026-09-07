# WINGRUN_20260905_01 postmortem

This is a derived audit. `enza_memory/wing_runs/WINGRUN_20260905_01/weekly_trace.jsonl`
and its referenced screenshots remain the source of truth. Missing or
conflicting facts remain `UNKNOWN`.

## Timeline

The trace sometimes records the post-action week rather than the pre-action
week. Rows below preserve that distinction and do not silently repair gaps.

### Season 1

| Trace | Observed boundary | Action and rationale | Resulting state |
|---|---|---|---|
| 1 | S1, weeks 8 before first action (result reports 8→7) | VOCAL; S1 default | HOME weeks 7; gap 999→967 |
| 2 | S1, weeks 7 before action | VOCAL; S1 default | HOME weeks 6; gap 967→935 |
| 3 | S1, weeks 6 before action | VOCAL; S1 default | HOME weeks 5; support-event interruption handled |
| 4–6 | S1, weeks 5/4 boundary; trace contains a merged/duplicate week label | VOCAL plus operator-resolved business choice | HOME weeks 4; gap 872→809 |
| 7 | S1, next normal week | VOCAL; S1 default | HOME weeks 3; three-choice advice handled |
| 8 | S1, next normal week | VOCAL; S1 default | HOME weeks 2; communication event handled |
| 9–10 | S1 final boundary, weeks 1 | AUDITION; gap 416 > 300 | PASS, weeks 0, target reached |
| 11 | S2 transition | no weekly action | S2 HOME weeks 8 |

### Season 2

| Trace | Observed boundary | Action and rationale | Resulting state |
|---|---|---|---|
| 12 | S2 W1 in progress | no new policy action; screenshot channel failed | current page/week `UNKNOWN` |
| 13 | Fresh recovery | no action; reconcile from a new HOME | S2 HOME weeks 4; intervening WINGVAL chain referenced but not reconstructed here |
| 14 | S2 weeks 4 before action | VOCAL; non-final S2 default | HOME weeks 3 |
| 15 | S2 weeks 3 before action | VOCAL; non-final S2 default | HOME weeks 2 |
| 16–17 | S2 final boundary, weeks 1 | AUDITION; positive fan gap | PASS, weeks 0, S2 CLEAR |
| 18 | S3 transition | no weekly action | S3 HOME weeks 8 |

### Season 3

| Trace | Observed boundary | Action and rationale | Resulting state |
|---|---|---|---|
| 19 | S3 first route attempt | 40k audition; milestone pending | FAIL; weeks 7; flag remains false |
| 20 | S3 retry boundary | retry 40k; flag still false | result evidence lost; weeks 6; flag remains false |
| 21–22 | S3 next retry | retry 40k | explicit PASS; HOME weeks 5; 40k flag committed |
| 23 | S3 weeks 5 | 50k audition; unlocked and pending | PASS; +50000 explicit; 50k flag committed |
| 24 | S3 weeks 4 | REST; fresh 27% VOCAL failure rate | HOME weeks 3; stamina recovered |
| 25 | S3 weeks 3 | VOCAL; fresh failure rate 0% | completed with advice interruption |
| 26 | S3 final normal boundary | VOCAL; milestones complete | weeks 1/season end progression; fans 111150 |
| 27–28 | S3 end → S4 | no weekly action | S4 HOME weeks 8 |

### Season 4 and finals

| Trace | Observed boundary | Action and rationale | Resulting state |
|---|---|---|---|
| 29–30 | S4 HOME weeks 8; fans 111150; gap 388850 | plan 4 × 100k wins plus one-week margin; choose preparation VOCAL | route deadline model omits a complete remaining-route-step budget |
| 31 | S4 weeks 8 before action | VOCAL; 8 > 5 | HOME weeks 7 |
| 32 | S4 weeks 7 before action | VOCAL; 7 > 5 | HOME weeks 6 |
| 33 | S4 weeks 6 before action | VOCAL; 6 > 5 | HOME weeks 5, then select THE LEGEND |
| 34–36 | First battle transient | early Auto clicks during non-actionable phase; later reconciliation records conflict | current week transiently `UNKNOWN`; no separate week consumed by control attempts |
| 37 | THE LEGEND #1/#2 chain | #1 PASS followed by #2 retry | #1: weeks 5→4, fans 114414→214414; #2: FAIL, weeks 4→3, fans unchanged |
| 38 | S4 weeks 3 | THE LEGEND #3; route target still unmet | PASS; weeks 2; fans become 314414 at next fresh boundary |
| 39 | S4 weeks 2 | THE LEGEND #4 | PASS; weeks 1; fans become 414414 at next fresh boundary |
| 40 | S4 weeks 1 | THE LEGEND #5 | FAIL; weeks 0; fans remain 414414 |
| 41 | S4 end | presentation/semifinal entry was advanced with SKIP | S4 ended; semifinal result `UNKNOWN` |
| 42 | closed run | operator long-press abandon | final evaluation 419414; +5000 source `UNKNOWN`; run `COMPLETED_ABANDONED` |

## Failure classification

| Class | Finding | Causal role |
|---|---|---|
| Execution failure | THE LEGEND #2 and #5 failed | Directly reduced successful 100k auditions to three, but failure must be budgeted by planning |
| Perception failure | Some HOME fan totals were obscured; early Auto `OFF` was confused with enabled interactability | Operational friction, not the earliest TE planning cause |
| State reconciliation failure | The transient `weeks=1` record and later forced `weeks=5` reconciliation lacked matching provenance at that time | Contaminated reporting, but occurred after the critical S4 training decision |
| Policy/planning failure | S4 planning used required wins plus one margin, not a fresh `remaining_weeks` versus complete `remaining_required_route_steps` deadline | Primary preventable cause |
| Missing invariant | No execution-boundary rule rejected low-priority training at or after the route's latest safe start | Allowed the third S4 VOCAL to consume the last additional attempt budget |

## Preventable point

- Deadline risk first became visible at S4 entry (trace 30): gap 388850,
  maximum confirmed reward 100000, and only eight weeks remained.
- The last postmortem-safe route start was the fresh S4 HOME boundary at
  weeks 6. Starting there would have retained a sixth audition opportunity;
  the observed five-attempt sequence contained two failures and only three
  wins.
- The first irreversible preventable decision was the third S4 VOCAL at the
  weeks-6 boundary (trace 33), which consumed that sixth opportunity and left
  only five attempts.

The number `6` is a run-specific postmortem result, not a global WING constant.
Runtime policy now computes the boundary from explicit, fresh
`remaining_required_route_steps`. If that value is unknown, policy remains
`NEED_MORE_OBSERVATION`; it is never inferred from this run.

## Minimal correction

1. Route-plan evidence is bound to exact season and HOME week.
2. Policy compares `remaining_weeks` with `remaining_required_route_steps`.
3. Before the boundary, an explicitly declared pre-deadline action may run.
4. At or after the boundary, the next route action replaces low-priority
   training.
5. A failed route step requires a fresh week-bound replan; stale plans and
   previous-season plans fail closed.
6. Goal execution independently rejects a forged low-priority action that
   conflicts with an attached deadline.
