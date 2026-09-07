# Enza AI Computer Use Reliability Evaluation

**Release:** v0.1

**Milestone:** From unreliable visual automation to evidence-grounded autonomous execution.

## Problem

Computer-use reliability depends on more than recognizing a visible control. A safe agent must keep human goals, planner decisions, executor mappings, risk permission, fresh observations, and durable state reconciliation distinct.

## Failure discovered

`WINGRUN_20260907_01` exposed an S1W6 VOCAL failure: the fresh frame showed `trouble_rate ≈92%`, yet VOCAL `決定` was emitted. The executor lacked sufficient authority separation and continued a baseline objective without an explicit planner-owned objective. The event is preserved as a confirmed policy violation.

## Architecture correction

The v0.1 evidence and regression records establish these boundaries:

- the planner supplies an explicit objective;
- the executor maps only an approved objective and cannot invent one;
- VOCAL dispatch requires fresh risk evidence and a passing gate;
- screenshot/capture failure is isolated from game and action failure;
- a possibly sent action remains pending until fresh evidence reconciles its outcome;
- result progress is committed only from explicit result evidence or a fresh stable reconciliation.

## Validation evidence

`WINGRUN_20260907_02` validated the post-fix S1W8 path. VOCAL was executed after fresh re-verification with `trouble_rate 0%`; exactly one DECIDE action was recorded. The explicit result screen showed the Season E target clear, and the final fan count was `1,453`.

The package includes the case study, final validation report, WINGRUN_01 incident/reconciliation records, runtime contracts, battle visual authority reconciliation, observation-failure tests, pending-action reconciliation tests, and regression candidates.

## Known limitations

- The ZCode host screenshot latch is external to this project.
- Host/browser observation reliability remains an external dependency.
- A final presentation stall can leave the next UI position unknown even when the preceding result is explicitly committed.

## Future roadmap

- Extend the same authority and reconciliation contracts across additional computer-use rooms and result types.
- Expand replay coverage for post-dispatch timeouts, blocked objectives, and explicit PASS/FAIL result commits.
- Improve host observation reliability outside the project boundary.
- Keep unsupported strategy and execution behavior fail-closed until fresh evidence and ownership are available.

This release is an offline metadata freeze. It does not modify runtime, planner, executor, policy, Harness, Skill, or archive contents.
