# Runtime Contracts Distillation Report

- **Generated**: 2026-09-06 (offline; zero environment contact — no clicks, no observations, no live automation)
- **Output**: `enza_memory/runtime_contracts/` — 11 room contracts + `room_contract_index.json` + this report
- **Task mode**: RESEARCH/AUDIT distillation. No Harness change, no Skill change, no business-policy change, no production code change.

## What was distilled

Live knowledge was converged per room into Python-executor-consumable contracts
(`ROOM_IDENTITY`, `ENTRY_CONDITIONS`, `OBSERVATION_SCHEMA`, `SUBSTATES`,
`VISIBLE_CONTROLS`, `ACTION_AUTHORITY`, `ALLOWED_ACTIONS`, `FORBIDDEN_ACTIONS`,
`POSTCONDITIONS`, `EXIT_CONDITIONS`, `FAILURE_MODES`, `RECOVERY`,
`PERSISTENCE_BOUNDARY`, `MIGRATION_STATUS`) from these primary memory sources:

- `enza_memory/migration/python_click_migration/distilled/*` (control evidence matrix, stable transition chains, hazard map, battle runtime, result commits, recovery requirements, timing, migration bundle/readiness)
- `enza_memory/migration/python_click_migration/event_occurrence/*` and `recovered_frames/*`
- `enza_memory/wing_runs/WINGRUN_20260905_01`, `WINGRUN_20260906_01`, `WINGVAL_20260905_01` (run records, validation, crash backfill)
- `enza_memory/policies/*` (referenced as BUSINESS POLICY boundaries, never embedded)
- `.agent-harness/GATES.md` runtime invariants

## Strict separation enforced

Every contract keeps four evidence classes distinct, mirroring the harness
invariants (`INTERACTABILITY_MUST_BE_OBSERVED_SEPARATELY_FROM_CONTROL_VALUE`,
`CONTROL_ACTION_REQUIRES_ACTIONABLE_PHASE`,
`RESULT_FLAG_COMMIT_REQUIRES_EXPLICIT_SUCCESS_EVIDENCE`):

| Visible | != | Authorized/available/committed |
|---|---|---|
| VOCAL card visible | != | VOCAL authorized (needs fresh failure_rate<=2 gate) |
| Auto OFF visible | != | Auto actionable (needs INPUT_READY + ENABLED + current epoch) |
| Speed badge (X2) visible | != | Speed toggle grounded (HOLD — display-only) |
| node visible on skill board | != | node available (color model; gold != available) |
| result scene visible | != | result committed (explicit PASS/FAIL evidence only) |
| candidate visible | != | candidate eligible/selectable |
| SKIP visible | != | SKIP authorized for unknown transition type |

Business policy (which option, which route, which node, when to REST) is only
referenced by path (`enza_memory/policies/wing_business_choice_fixed_policy.json`,
`audition_battle_speed_handler.json`, `s4_route_operator_hints.json`, etc.); the
contracts own perception and control authority only.

## ROOMS_DISTILLED

HOME, SCHEDULE, DIALOGUE, CHOICE, AUDITION_SELECTION, AUDITION_BATTLE, RESULT,
SKILL_BOARD, SKILL_REPLACEMENT, SEASON_TRANSITION, ENDING — all 11 contracts
written with all 14 required fields plus sources, and indexed in
`room_contract_index.json`.

## PYTHON_READY (shadow-test candidates per evidence matrix readiness scores)

`HOME:SCHEDULE` (16/17), `SCHEDULE:VOCAL` (16/17), `SCHEDULE:DECIDE` (16/17,
REPLICATED), `RESULT:ADVANCE_CYCLE` (15/17, REPLICATED) are the strongest
candidates; `AUDITION_SELECTION:DECIDE` (14/17), `AUDITION_BATTLE:AUTO`
(14/17), `DIALOGUE:SAFE_TEXTBOX` (13/17), `DIALOGUE:3_CHOICE_MIDDLE` (13/17),
`SEASON_TRANSITION:SKIP/NEXT` (13/17), `SCHEDULE:BACK` (12/17) follow.
"Python-ready" here means shadow-test ready (detect/predict without clicking)
exactly as scoped in `python_migration_bundle_v0_1.json` — `production_ready_controls` remains **empty**.

## PARTIAL (evidence exists, gaps documented per contract)

- All 11 rooms carry `status: PARTIAL`; canonical normalized boxes exist only
  for `HOME:SCHEDULE` and `SCHEDULE:VOCAL` (fresh 2026-09-06 captures).
- AUDITION_BATTLE: AUTO has 4/4 phase-guarded successes vs 4 negative samples
  but lacks cross-session epoch replication; PAUSE_RESUME is n=1.
- CHOICE: 3-choice geometry is single-frame (staggered layout, middle = green
  border + ✓ badge); 2-choice boxes never captured; event probabilities are
  LOW_SAMPLE observation priors (n=34 eligible weeks), eligibility UNKNOWN.
- RESULT: commit semantics fully exampled (7 cases incl. evidence-loss and
  FAIL-no-commit), but per-phase boxes and terminal detector unbuilt.
- SEASON_TRANSITION: 3 completions; S3_START_PREP sequencing rule (check at
  fresh weeks=8 HOME) recorded after a late-recovery miss.
- SKILL_BOARD / SKILL_REPLACEMENT: 2 live sessions, 4/4 replacements verified
  by SP deltas, full board color model + visual replacement sequence
  documented — but zero normalized geometry (coordinate probing only).
- ENDING: single n=1 run observation (rank screen → ending dialogue →
  プロデュース評価 → fes idol birth → MAIN_LOBBY_IDLE).

## BLOCKED / HOLD (per task-critical items)

- **speed toggle**: HOLD — display badge is read-only (X2 clicks never reached
  X3); toggle body coordinate (1166,47) exists in the ACTIVE operator handler
  but x3_zero_clicks / x1_two_clicks / unknown_stop paths are
  `NOT_YET_OBSERVED`; `SPEED_FIRST_THEN_AUTO` ordering is live-confirmed (Auto
  ON locks speed) yet remains a held Harness candidate.
- **semifinal/final**: UNKNOWN — no separate contract; S1/S2 finals observed
  once each; the S3 semifinal scene SKIP advanced without explicit WIN
  evidence (preserved as RESULT_EVIDENCE_LOSS, no commit).
- **long-press abandon**: BLOCKED — irreversible, operator-gated
  (`ABANDON:*` excluded from the migration bundle; automated long-press
  semantics UNKNOWN).
- **real event eligibility**: UNKNOWN for all event/audition types — the
  empirical rates in `event_probability_summary.json` are observation priors
  only and are explicitly barred from business use.
- Also grounded-blocked: `AUDITION_SELECTION:CANDIDATE`,
  `HOME:FURIKAERI` (intentional use), `AUDITION_BATTLE:SPEED_DISPLAY` as a
  control, `DIALOGUE:2_CHOICE_GOMEN` (business-policy blocked),
  skill-board/replacement controls (no normalized geometry).

## Cross-cutting invariants carried into every contract

Control epoch invalidation on resume, actionable-phase requirement, fresh
post-transaction reconciliation, fail-closed UNKNOWN handling, measured-latency
batch budgeting (~5.0s/click CUA cost, 30s screenshot hazard reserve, ≤8
clicks/cell), and durable flush boundaries (week / season / burst / handoff).

## Honesty notes

- Counts are conservative minimums from cited artifacts; nothing was invented
  or upgraded. The whole distillation is offline; no environment contact
  occurred, so per `enza_memory/MEMORY_PROTOCOL.md` this session is
  environment-contact-exempt — `memory_index.json` is nonetheless updated for
  traceability of the created artifacts.
- These contracts are candidate executor input, not executable policy and not
  ground truth; execution authority still lives in the ActionGate/permission
  stack.
