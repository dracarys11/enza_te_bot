# Implementation Plan — READY_TO_IMPLEMENT Regression Cases

- Planning session: `IMPLEMENTATION_PLANNING_20260907` (offline planner; no code implemented, no runtime/business-policy/Harness/Skill change, no game operation, no AGY)
- Inputs: regression corpus + reconciliation + implementation queue + live-target list + stale_reference_audit + runtime_contracts + code inspection of tests/, goal_execution.py, home_policy.py, audition_control_epoch.py, shadow_executor/, main.py

## 1. READY enumeration (16 cases → scored in implementation_priority.json)

From the current queue (not copied blindly — verified against code):

NRG-013 (durable flush), NRG-026 (evidence-in-flush), NRG-010 (post-timeout reconcile), NRG-009 (capture-before-advance), RCR-006 (scene-skip guard), PLR-011 (risk-gate ≠ objective + futility), PLR-007 (trace separation), PLR-001/PLR-002 (deadline model — **verify-only**: already implemented), NRG-004/NRG-008 (Auto authority + epoch invalidation), NRG-015 (layout/context separation), NRG-012 (session fail-closed), NRG-021/SBR-002 (replacement validation, merged), VNC-001/002/003 (board probe guards).

Key code-recon facts that shaped the plan:
- `goal_execution.validate_goal_deadline` + `route_capacity_from_state` + 10 deadline tests **already exist** → PLR-001/002 downgraded to verify-only.
- `home_policy.py` S3 branch already fixed (F-01) and `test_planner_objective_is_not_replaced_by_vocal_risk_authorization` already pins the selection-vs-permission distinction → PLR-011 residual is only the **futility projection** (no code exists: grep ENDGAME/futility = 0).
- `audition_control_epoch.py` is **still stale per F-07** (`speed_action` defaults X3 → `CLICK_SPEED` contradicts display-only badge) though its lifecycle/epoch tests are correct.
- `main.py` has **zero** checkpoint/durable-flush code today; no post-timeout reconcile; no session fail-closed — these are genuinely new, small surfaces.

## 2. Scoring

Each case scored on runtime reachability × severity × likelihood × blast radius × implementation/test complexity (composite in `implementation_priority.json`). Top of order: NRG-010 (11), NRG-013 / PLR-011 / NRG-009 / RCR-006 / NRG-026 (10/9), then the rest. Blast-radius classes: RUN_LOSS (timeout, persistence), BUSINESS_COMMIT_CORRUPTION (planner futility, result loss, replacement), STALL (session), MISCLICK (Auto, choice, board), OBSERVATION_ONLY (trace fields).

## 3. Batches (8, in `implementation_batches.json`)

| batch | goal | cases | est. |
|---|---|---|---|
| CODEX_BATCH_1 | planner objective vs risk gate + ENDGAME_FUTILE surfacing + trace field split | PLR-011, PLR-007 | 25min |
| CODEX_BATCH_2 | deadline model verification vs 0905 multi-failure postmortem (verify-only) | PLR-001, PLR-002 | 10–15min |
| CODEX_BATCH_3 | durability: 4-boundary flush + evidence-in-flush + session fail-closed + F-03 config guard | NRG-013, NRG-026, NRG-012, F-03 | 25–30min |
| CODEX_BATCH_4 | post-timeout reconcile-before-retry state machine | NRG-010 | 15–20min |
| CODEX_BATCH_5 | result commit guard: evidence→commit→advance ordering; scene-skip cannot consume uncommitted week | NRG-009, RCR-006 | 20–25min |
| CODEX_BATCH_6 | F-07 cleanup: speed toggle → HOLD until separately grounded; Auto authority pin | NRG-004, NRG-008 | 15min |
| CODEX_BATCH_7 | layout_family + event_context as separate required detector fields | NRG-015 | 25–30min |
| CODEX_BATCH_8 | board probe guards (no side effect ≠ safe-target) + replacement validation on recovered-frame fixtures | VNC-001/002/003, NRG-021/SBR-002 | 25–30min |

Ordering rationale: planner logic first (pure, partly verify-only), then durability (largest new surface), then executor-loop contracts, then dormant-module cleanup before battle integration, then additive shadow-detection fields. Each batch = one contract/call-path; every batch has its own `pytest` verification command and stays inside a bounded FIX/FEATURE mode.

## 4. Pre-live blockers

- **MUST_FIX_BEFORE_NEXT_LIVE (4)**: NRG-010, NRG-013, NRG-009, PLR-011(+PLR-007) — each maps to an already-observed run-loss or season-waste incident.
- **SHOULD_FIX (5)**: RCR-006, NRG-026, NRG-012, NRG-021/SBR-002 (MUST only if the next run does skill prep), F-03.
- **CAN_WAIT (5)**: PLR-001/002 (implemented), NRG-004/008 (battle executor not integrated), NRG-015 (shadow-level), VNC (shadow-level), CLR-004 (blocked on 45-frame review).

## 5. Redundancy found (redundant_cases.json)

- PLR-001/002 and part of PLR-011 were already implemented+tested → queue's READY was stale; downgraded/merged (no new logic).
- NRG-021 ≡ SBR-002 (one replacement guard); NRG-009 ≡ RCR-006 (one ordering contract); NRG-013 ≡ NRG-026 ≡ NRG-012 (one durability family).
- 7 ALREADY_COVERED cases re-listed to prevent test re-creation.
- Artifact duplicates already merged earlier (PLR-005→PLR-011; NRG-020→VNC cross-refs).

Net: 16 READY entries → **8 batches** (2 verify-only), 3 merged test sets replace 6 duplicates.

## 6. Code area mapping

See `code_area_mapping.json` for per-batch files/functions/tests (read-only located): home_policy.py (~255 S3 branch, ~158 risk guard), decision_trace_schema.py, goal_execution.py:56/102, a **new** run_checkpoint.py (no existing flush site), evidence_reconciliation.py, wing_fast_handlers.py, audition_control_epoch.py:140 (speed_action), shadow_executor/detectors.py+authority.py+executor.py, fixtures under recovered_frames/. Policy files are consumed as specs only — never loaded as executable logic by new code.

## 7. Codex execution order

CODEX_BATCH_1 → 2 → 3 → 4 → 5 → 6 → 7 → 8 (B3 may swap with B1/B2 if durability is urgent; B6 must precede any future battle-executor integration; B7/B8 are independent and can run anytime after B1).

## Final

- READY_CASES_TOTAL: 16 (14 implementation + 2 verify-only)
- MUST_FIX_BEFORE_NEXT_LIVE: 4
- SHOULD_FIX: 5
- CAN_WAIT: 5
- IMPLEMENTATION_BATCHES: 8
- REDUNDANT_CASES: 8 findings (2 already-implemented downgrades, 3 same-guard merges, 1 test-exists list, 2 artifact duplicates)
- RECOMMENDED_CODEX_ORDER: 1→2→3→4→5→6→7→8
- RUNTIME_CHANGED: NO
- BUSINESS_POLICY_CHANGED: NO
- HARNESS_CHANGED: NO

**REGRESSION_IMPLEMENTATION_PLAN_READY**
