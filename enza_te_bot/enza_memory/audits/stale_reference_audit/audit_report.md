# Stale / Superseded Knowledge Reference Audit

- audit_id: `stale_reference_audit_20260906`
- date: 2026-09-06 (offline session, no environment contact)
- repo: `/Users/koents/Documents/ChatGPT/enza/enza_te_bot`
- mode: **OFFLINE ONLY** — no code changed, no game operated, no AGY called, no Harness/Skill modified
- outputs: `stale_references.json`, `runtime_reachable_stale_refs.json`, `test_contamination.json`, `historical_raw_safe_to_keep.json`, this report

## Method

1. Pattern sweep over all `*.py / *.json / *.jsonl / *.md` (excluding `.venv`, `__pycache__`, `.pytest_cache`, `config_backups`) for the 12 known superseded-knowledge classes: stamina→REST hard rule, S3 default-VOCAL, S4 +200k rescue, S4 stale weeks=1 / pending THE LEGEND, TE_REACHABLE, semifinal SKIP→WIN, speed badge as toggle / X3 grounded, Auto-OFF-always-click, MORNING_3CHOICE overreach, gold/blue node color = available, Visual2.5 outside-zone as target policy, active_run → closed run.
2. Every hit was verified against the current authoritative chain: `enza_memory/artifact_registry.json` (incl. `runtime_patch_20260905`), `home_policy.py` operator-policy comments + `apply_vocal_risk_guard`, `GATES.md` (SPEED_FIRST_THEN_AUTO held), migration `distilled/` + `hazard_map.json` + `zcode_review_report.md`, finalized `checkpoint.json`, and raw run traces.
3. Pollution rule applied strictly: a superseded conclusion in a **historical raw trace** is NOT pollution; only a **derived/current/runtime-path** artifact still treating it as authoritative is counted.

## Summary

| Class | Count |
|---|---|
| TOTAL_FINDINGS | 12 |
| P0_RUNTIME_REACHABLE | 1 |
| P1_TEST_OR_RESUME_CONTAMINATION | 7 |
| P2_DOC_ONLY | 4 |
| HISTORICAL_RAW_DO_NOT_TOUCH (safe-to-keep entries) | 10 |
| FALSE_POSITIVES_DISMISSED | 10 |
| RUNTIME_CHANGED | NO |

## Key findings

### P0 — runtime reachable

- **F-01 `home_policy.py:256-258`** — The S3 milestone-complete base branch still implements `stamina low → REST` (`season_3_stamina_low_rest`) directly, bypassing `apply_vocal_risk_guard`, whose own contract (and the operator policy of 2026-09-05, restated in the module header and in the registry) says low stamina is a warning that only makes the fresh failure-rate read mandatory and never forces REST by itself. Reached from `main.py:563/683/895` on any fresh S3 HOME decision. Fix is small (let the guard own the semantics) but must be paired with F-02.

### P1 — test / resume / policy contamination

- **F-02 `test_home_policy.py:52-60`** — pins the stale S3 stamina→REST rule as expected behavior; must change with F-01.
- **F-03 `config.json run_state.season3` (line 1073)** — closed-run WINGRUN_20260906_01 flags (`audition_40k/50k_completed=true`) persist in the live config that `main.py` loads; on a new run they would silently skip both required auditions. README Known Blockers #5 already warns; no code guard exists.
- **F-04 `README.md:705-724`** — Current Mainline / Active Runs still say `Active run: WINGRUN_20260905_01` (PAUSED, resumable), `S2 IN_PROGRESS`, `S3 PENDING`, `S4 BLOCKED`. Registry truth: active_run null, both runs CLOSED, S3 COMPLETE, S4 NOT REACHED, scenario concluded. This is the Resume Guide's step-1 entry point.
- **F-05 `enza_memory/policies/audition_battle_speed_handler.json`** — still marked `ACTIVE procedure`, instructing clicks on the speed control toward X3 at (1166,47); superseded by the display-only badge finding, `hazard_map` WRONG_TARGET guard, `control_regions.json:526`, and the GATES HOLD on `SPEED_FIRST_THEN_AUTO` (which `test_harness_live_invariants.py` enforces). No code loads it; risk is resume/plan-level.
- **F-06 `WINGRUN_20260905_01/distillation/control_distillation.json:117-131`** — the speed control entry (SAFE_NAVIGATION, "X3 目标, bounded toggle ≤3") is the same stale claim inside the distilled knowledge file referenced by the finalized checkpoint's `known_controls_ref`.
- **F-07 `audition_control_epoch.py:140-149` + `test_audition_control_epoch.py:51-54`** — dormant module (verified: no production importer) encodes `speed != X3 → CLICK_SPEED`; test pins X2→CLICK_SPEED. Carries the "X3 reliably togglable" rule into any future integration.
- **F-08 migration `event_occurrence/` (occurrences 018-021, `cold_start_event_policy.json`)** — LESSON_ADVICE / AUDITION_ADVICE 3-choice records labeled `MORNING_3CHOICE`; already flagged by `zcode_review_report.md:35` (LAYOUT_FAMILY vs BUSINESS_EVENT_CONTEXT must be separated). Observation-prior only; never a business input.

### P2 — doc/candidate only

- **F-09 `ai_decisions/planner_rules_candidate.json:24,27`** and **F-10 `ai_decisions/unknown_registry_candidate.json:26`** — candidate-only (executable:false, unreferenced) rules still phrasing `stamina low → REST` for S2/S3.
- **F-11 `blind_interaction_policy.py:255`** — `MORNING_3CHOICE_GREEN_V1` fingerprint name implies morning scope while the match is layout-based; behaviorally moot (operator fixed policy: all 3-choice → middle) and the module has no production importer.
- **F-12 `control_regions.json:410`** — skill-node precondition shorthand "gold/purchasable"; superseded clarification is "gold: node-type coloring, NOT availability"; the mandatory detail-panel identity check already carries the authoritative guard.

## Historical raw — safe to keep (do NOT delete)

`s4_reconciliation.json` (self-superseded TE reachability YES_CONDITIONAL / weeks=1 claim), `weekly_trace.jsonl` (raw beliefs at the time), `s4_route_policy/activation.json` (+200k inventory, run-scoped), speed evidence records, finalized `checkpoint.json` (obsolete resume state labeled as provenance), `exploration_summary.json` (1E misreads, disclaimed), both `environment_map_progress.json` copies (registry-superseded), `wing_state_graph_v2.json` (audit/benchmark only), `memory_index.json` (session log), postmortem. Details and per-entry justifications: `historical_raw_safe_to_keep.json`.

## False positives dismissed

1. `stamina < 0.50` literal hits: `home_policy.py:16` is the warning threshold constant (correct), `test_harness_live_invariants.py:29` is a **guard** asserting the string is absent from GATES, registry line 174 is the supersede record itself.
2. Semifinal SKIP→WIN: **no artifact claims it**; all record `UNKNOWN` with explicit commit guards (`result_commit_examples.json`, `hazard_map.json`).
3. `TE_REACHABLE` as a key: zero occurrences repo-wide; only the self-superseded `historical_te_reachability_assessment` in H-01.
4. `season_1_default_vocal` / `season_2_default_vocal` in `home_policy.py`: current policy, not the superseded S3 rule.
5. `wing_fast_handlers.py morning_three_choice`: fail-closed and consistent with current operator policy.
6. `GATES.md` SPEED_FIRST_THEN_AUTO: correctly **held**, not promoted.
7. `test_wing_fast_handlers.py` stamina tests: encode the current warning-only semantics.
8. `distilled/battle_runtime_distillation.json`, `hazard_map.json`, migration speed entries: corrected current knowledge (x3_handler PARTIAL, display-only).
9. `config_backups/`: timestamped backups, never authoritative.
10. `distilled/control_evidence_matrix.json:187` "speed toggle clickable region": listed under `preserved_unknowns` — honest, correct.

## Per-category coverage (of the 12 requested)

1. stamina→REST hard rule → **F-01 (P0), F-02 (P1), F-09/F-10 (P2)**
2. S3 weekly default VOCAL ignoring route objective → no current-path violation found; home_policy consumes 40k/50k flags before defaulting; only candidate artifacts (F-09/F-10) phrase an unconditional default
3. S4 +200k rescue planning → historical only (H-03); no derived/current artifact plans it
4. S4 stale weeks=1 / pending THE LEGEND → historical only (H-01, H-05); README's stale S4/S3 status captured under F-04
5. old TE_REACHABLE=YES → historical only (H-01); zero live references
6. semifinal SKIP→WIN → not found anywhere; all UNKNOWN + guarded
7. speed badge toggle / X3 grounded → **F-05, F-06, F-07**
8. Auto OFF → always click → no current artifact states it; GATES + v0.2 review frames encode interactability/phase authority; residual exposure only via dormant F-07 module pattern (noted)
9. MORNING_3CHOICE overreach → **F-08 (P1), F-11 (P2)**
10. gold/blue node color = available → **F-12 (P2)**; run record already states the correction
11. Visual2.5 outside-zone as normal target policy → not found as policy; recorded honestly as a pre-clarification deviation in the run record and memory index (raw, safe)
12. active_run → CLOSED run → **F-04 (P1, README)**; registry itself is clean (`active_run: null`); F-03 is the same class in config form

## Conclusion

One runtime-reachable superseded rule (F-01, S3 stamina→REST in `home_policy.py`) plus one dormant-but-live config residue (F-03). The remaining contamination is in tests, docs, policy/distillation references, candidate files, and dormant modules. Historical raw artifacts consistently self-mark or are registry-marked as non-authoritative and were not touched.

RUNTIME_CHANGED: NO

STALE_SUPERSEDED_REFERENCE_AUDIT_COMPLETE
