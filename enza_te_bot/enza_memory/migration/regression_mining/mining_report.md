# Regression Mining Report — Enza Python Migration

- Mining session: `OFFLINE_REGRESSION_MINING_20260906` (offline forensic / regression miner role)
- Date: 2026-09-06
- Mode: AUDIT/RESEARCH — no game operation, no AGY call, no runtime / business-policy / Harness / Skill change, no raw evidence rewritten.
- Output dir: `enza_memory/migration/regression_mining/`

## 1. Sources reviewed (priority order respected)

Live screenshot/tool evidence inventory > raw jsonl trace > durable recovery artifact > session transcript > derived summary.

| Source class | Items |
|---|---|
| Governance (read first, per AGENTS.md) | CURRENT_MILESTONE.md, .agent-harness CORE/MODES/GATES/LIVE_DEBUG, profiles/enza.md, MEMORY_PROTOCOL |
| wing_runs | WINGRUN_20260905_01 (weekly_trace.jsonl 42 rows, unexpected_events.jsonl, timeout_debug_report, final/season summary, frozen_battle_inspection, s4_* ×3, distillation ×10, promotion-audit reports), WINGRUN_20260906_01 (timings.jsonl 13 rows, checkpoint, crash_recovery_backfill, operator_reconcile, run_completion_record, s3_start_prep_record, skill_board_session_2_record), WINGVAL_20260905_01 (6 JSONs) |
| migration corpus | python_click_migration: README, migration_status, viewport_profiles, distilled ×8, event_occurrence ×5, review_batches (shadow_v0_1 + v0_2 zcode_audit), recovered_frames manifests + skill_board/replacement visual sequences |
| enza_memory | failures ×5, policies ×8, wing_state_graph_v2, state_hierarchy_review_001, exploration_summary, self_exploration ×4 + cross_session_audit, live_decisions ×2, decision_traces index, memory_index.json (18 sessions) |
| ai_decisions | room_sop_candidates, aidecision_candidates, planner_rules_candidate, unknown_registry_candidate (+ observation inventory 71 files) |
| docs | KNOWN_ISSUES.md (KI-001..013), wingrun_20260905_01_postmortem.md, ocr/paddleocr coordinate audits |
| logs | 439 files inventoried by incident pattern (147 non-PNG jsonl: teach/home_tick/room_vocal_room/audition_battle_handler/season_3_trial/discovery) |
| tests | 76 test_*.py enumerated for coverage mapping |
| rollout | Not opened: crash evidence already durably backfilled into `crash_recovery_backfill.json` with transcript SHA-256, so no rollout re-read was required (raw transcript left untouched per task rules) |

**TOTAL_SOURCE_ARTIFACTS_REVIEWED: 96** (read in full or in relevant part) plus inventories of 439 log files, 76 tests, 71 observation artifacts, 18 memory-index sessions.

## 2. Canonical states

**CANONICAL_STATES: 13** (canonical vocabulary exactly as requested) **+ 3 extensions added by mining** (PRODUCE_PREP, MAIN_MENU_OUTSIDE_PRODUCE, OVERLAY_TUTORIAL) for states that genuinely occurred but were absent from the vocabulary. 8 historical-label reclassifications recorded with `reason_for_reclassification` (tutorial-modal misreads, state-merge downgrades, layout/context split, trace week-label error, banner occlusion) — no historical artifact was modified.

Key reclassification: the "WING_CONFIRMATION_DIALOG" of the 1E phase was superseded by AGY reinspection as the UNIT_FORMATION_TUTORIAL_MODAL; WING confirmation dialog has **0 verified first-hand observations**.

## 3. Canonical transitions

**CANONICAL_TRANSITIONS: 26** (T01–T26) with replication_count, independent runs/sessions, positive/negative samples, failure modes, confidence. Highlights:

- Cross-session replicated (≥2 sessions): HOME→SCHEDULE (7), SCHEDULE→VOCAL (6), DECIDE (6+1 negative), RESULT advance cycle (6), VOCAL week loop (≥20 weeks, 3 runs), dialogue textbox (35 taps), 3-choice middle (8), 2-choice ごめん (4), audition selection→battle (10), battle result commit (11 instances), season transition (5 stable + 1 crash), produce entry (2), ending flow (2).
- Single-session (replication-limited): skill board (17 acquisitions, 1 session), replacement (4, 1 session), pause/resume (1), REST (1), BACK→REST (1), fast-forward rule (1).
- Negative-only transitions kept as guard evidence: (985,663)→サポートスキル ×2, over-tap→振り返り ×1, Auto-in-animation ×4, speed-after-Auto ×2.

## 4. Negative regressions

**NEGATIVE_REGRESSION_CASES: 27** (NRG-001..027) — each with precondition, bad_action, observed_consequence, required_guard, evidence_refs, severity, coverage status. Class coverage: WRONG_TARGET ×8, NO_EFFECT ×4, DISABLED_CONTROL ×3, STALE_GEOMETRY ×2, PERSISTENCE_GAP ×2, UNKNOWN_STATE ×2, OVER_TAP, OVERLAY_OWNERSHIP, SCREENSHOT_TIMEOUT, SESSION_RELEASE, FAILED_ACTION_NO_COMMIT, RESULT_EVIDENCE_LOSS, TOOL_LATENCY_BUDGET_EXCEEDED ×1 each.

## 5. Planner failures (focus: WINGRUN_20260905_01)

**PLR-001..010** in `planner_regressions.json`. The central distinction is pinned as PLR-007: *VOCAL failure_rate=0 (fresh, replicated) proves the action's local risk is permitted — it never proves the planner should spend the week on VOCAL.* In S4, all three preparation VOCALs cited fresh 0% reads as decision support while the route deadline (min 4 THE LEGEND wins within 8 weeks, 2 failures actually occurred) was being consumed. Primary preventable causes per postmortem: deadline model omitted complete remaining-route-step budget (PLR-001) and no execution-boundary invariant rejected low-priority training at/after the route's latest safe start (PLR-002). Business policy itself was **not** modified.

## 6. Domain corpora

- **Skill board**: AVAILABLE / LOCKED / ACQUIRED / INSUFFICIENT_SP / PROGRESSIVE_UNLOCK / OUTSIDE_ALLOWED_ZONE / REPLACEMENT_REQUIRED / REPLACEMENT_SLOT_SELECT / REPLACEMENT_CONFIRM with frame refs and 6 regression cases; CENTER_SKIP has zero evidence (preserved UNKNOWN). All 4 locked-node hazard regions are **MISSING_FRAME** (live_csm_020..023 sources never durably persisted) — coordinates were never used to fabricate image evidence.
- **Choice layouts**: LAYOUT_FAMILY (THREE_CHOICE_LAYOUT_V1, TWO_CHOICE_LAYOUT_V1, UNKNOWN_CARD_LAYOUT) separated from EVENT_CONTEXT (MORNING, LESSON_ADVICE, AUDITION_ADVICE, PROMISE, REQUEST_DECLINE, OTHER); 6 regression cases; empirical rates marked RAW_EMPIRICAL / eligibility UNKNOWN.
- **Battle**: 9 paired cases exactly per the requested contract (AUTO OFF+DISABLED+ANIMATION→no click; AUTO OFF+ENABLED+INPUT_READY→click once; AUTO ON→no action; SPEED DISPLAY→not clickable; PASS→commit; FAIL→commit fail; UNKNOWN→no commit; plus pause/resume epoch and manual-card HOLD), grounded in 11 battle instances.
- **Result commit**: 10 cases including evidence-loss, scene-skip week consumption, POST_TIMEOUT reconciliation, SP forfeit, and the two preserved unknowns (semifinal result, +5000 fan delta).

## 7. Missing visual evidence

**MVE-001..023** (`missing_visual_evidence.json`): 9 skill-board/support missing source frames, all-core-control box gap, viewport DPR/zoom unknowns, speed toggle region, 2-choice box, semifinal result, +5000 source, replacement commit frames T3/T4, crash-recovered week frame identity, shadow-pipeline geometry completeness (10/38).

## 8. Priority

**regression_priority.json** rolls up 68 cases: **P0 ×24, P1 ×19, P2 ×19, P3 ×6**; ~60 are new test candidates (others pinned already-tested guards, e.g. UNKNOWN-business-choice stop, no-retry-without-reobserve).

**NEW_P0_TEST_CANDIDATES: 20** (listed in `regression_priority.json.new_test_candidates.P0`)
**NEW_P1_TEST_CANDIDATES: 15**

TOP_20_NEXT_REGRESSION_CASES and TOP_10_NEXT_LIVE_EVIDENCE_TARGETS are ranked in `regression_priority.json` (top live targets: speed-toggle grounding, skill-board durable frames, AUTO cross-session replication, control visual-boxes, 2-choice box, flush fail-closed drill, pause/resume epoch sample 2, viewport separation, season-transition flush boundary, fresh-season prep gate — each with a proposed LIVE_DEBUG risk level, none executed in this session).

## 9. Honesty limits

- Skill-board corpus is single-session; no cross-session replication exists.
- Battle counts are battle instances, not independent sessions; THE LEGEND repeatability is scoped to THE LEGEND.
- Event probabilities are raw empirical rates over 34 eligible weeks (crashed/operator-reconciled weeks excluded) with ELIGIBILITY_MODEL=UNKNOWN.
- Historical labels were reclassified only in this corpus; raw artifacts untouched.

## Final declarations

- RUNTIME_CHANGED: NO
- HARNESS_CHANGED: NO
- SKILL_CHANGED: NO
- Raw evidence rewritten: NO (memory_index.json gained one session entry per MEMORY_PROTOCOL; no existing entries modified)

**ENZA_HISTORICAL_REGRESSION_MINING_COMPLETE**
