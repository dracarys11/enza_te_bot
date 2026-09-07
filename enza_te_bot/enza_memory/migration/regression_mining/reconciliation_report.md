# Regression Reconciliation Report

- Reconciliation: `REGRESSION_RECONCILIATION_20260906`
- Date: 2026-09-07 (offline session — no game operation, no AGY call, no Harness/Skill/business-policy change, no raw evidence rewritten)
- Inputs: mining corpus (`OFFLINE_REGRESSION_MINING_20260906`), `recovered_frame_manifest.jsonl` (45 frames), review batch v0.3, `enza_memory/audits/stale_reference_audit/`

## 1. Skill-board missing evidence reconciled (RC-001)

The mining pass marked live_csm_020..023 as `MISSING_FRAME`. The recovered-frame manifest now binds each click sample to a real original frame recovered from session `sess_a87f3588-8212-4de7-b9ad-319825b4509e`:

| click sample | recovered frame | click (raw) | observed result | probe class |
|---|---|---|---|---|
| live_csm_020 | rf_sb_g1_misclick_590_145 | (590,145) | ring moved to adjacent LOCKED node, no purchase | WRONG_NODE_PROBE |
| live_csm_021 | rf_sb_g2_misclick_585_200 | (585,200/205) | Vocal100%UP 未解放 panel, NO_EFFECT | LOCKED_NODE_PROBE |
| live_csm_022 | rf_sb_g3_misclick_465_115 | (465,115) | Vocal240%UP locked at the time, NO_EFFECT | LOCKED_NODE_PROBE |
| live_csm_023 | rf_sb_g4_misclick_645_205 | (645,205) | off-board empty space, panel closed | DEAD_ZONE_NO_PURCHASE |

Derived artifacts updated **in place with reconciliation overlays** (`missing_visual_evidence.json`, `skill_board_regressions.json`, `negative_regressions.json`): the historical MISSING_FRAME designations are preserved verbatim and marked superseded; current status is `RECOVERED_VISUAL_EVIDENCE` / `RECOVERED_REVIEW_PENDING`. Note: review batches v0.2/v0.3 still list M02..M05 as missing — a v0.4 rebuild is queued (offline). MVE-001/006/007 (live_csm_015..019 positive-path frames) are only partially recovered and stay open as a narrow residual.

## 2. Visual negative corpus promoted (RC-002)

Three cases added to `skill_board_regressions.json#visual_negative_cases`: **VNC-001** LOCKED_NODE_PROBE, **VNC-002** WRONG_NODE_PROBE, **VNC-003** DEAD_ZONE_NO_PURCHASE. Pinned guard: **a click with no side effect (ring move / panel open / panel close) is never available-target evidence** — availability requires positive purchase evidence (confirm dialog → SP deduction → owned node). live_csm_022 additionally demonstrates why per-frame identity beats coordinate memory: the same locked node later became purchasable after chain unlock.

## 3. Planner regression strengthened (RC-004)

**PLR-011 (P0) added**; PLR-005 merged into it with a preserved merge marker. The strongest durable negative example is now WINGRUN_20260906_01 S3: fresh vocal failure_rate=0 on every remaining week (`risk_gate_allows(VOCAL)` true at every decision), yet repeated VOCAL selection finished S3 at **22,672/50,000 fans (rank D)** and **S4 was never reached**. Required regression pinned in `planner_regressions.json`: `risk_gate_allows(VOCAL)` must **not** imply `planner_selects(VOCAL)`; planner objective selection must separately satisfy route/fan-target logic (projected max gain vs remaining gap → ENDGAME_FUTILE escalation; route prerequisites before default selection). Business policy itself was not modified — the test pins the distinction, the policy stays operator-owned. Together with the 0905 deadline variant (PLR-001/002) this gives two independent runs for the same root distinction.

## 4. Persistence regression preserved (RC-005)

**NRG-013 unchanged and still required**: raw trace stopped at S1W6 while the game progressed to the S3 start, forcing a 12-event recovery backfill. Required regression: durable flush at **completed week / audition result / season transition / handoff** boundary, refusing the next transaction until the flush succeeds. Stale-audit F-03 (closed-run S3 flags surviving in live `config.json`) is the same durability class on the config path and is queued as an implementation dependency.

## 5. TOP20 triage (no blind test creation)

| triage | count | ids |
|---|---|---|
| READY_TO_IMPLEMENT | 13 | NRG-010, NRG-013, NRG-009, NRG-004, NRG-015, PLR-001, PLR-002, PLR-011, NRG-021, RCR-006, PLR-007, NRG-008, NRG-012 |
| ALREADY_COVERED | 7 | NRG-016, NRG-006, NRG-007, NRG-001, NRG-002, NRG-024, NRG-023 — verified against `test_python_shadow_executor.py`, `test_blind_interaction_policy.py`, `test_season3_audition.py`, `test_goal_execution.py`, `test_audition_battle_identity.py`, `test_harness_live_invariants.py` |
| WAITING_FOR_VISUAL_REVIEW | 1 | CLR-004 (timed-choice detection needs the 45-frame review completed) |
| WAITING_FOR_BUSINESS_POLICY | 0 (within TOP20; PLR-006 sits outside the TOP20 and is WAITING_FOR_BUSINESS_POLICY — prep-node selection is operator-owned) | — |
| SUPERSEDED | 0 | — |

Dependencies recorded: F-07 (dormant `audition_control_epoch.py` carries the stale X2→CLICK_SPEED rule) blocks NRG-004/008 implementation; F-05/F-06 stale speed-policy files block safe reuse of speed handling; F-08/F-11 confirm the choice-label drift NRG-015 targets.

## 6. TOP10 live evidence targets reduced

Cross-checked against the 45 recovered frames and v0.3:

- **Removed**: original target #2 (skill-board source frames) — satisfied in part by the recovery; residual narrowed to the csm_015..019 positive-path frames, folded into any future skill session rather than a dedicated run.
- **Narrowed**: original #4 — DIALOGUE:SAFE_TEXTBOX now covered by recovered frames + live_csm_029 box.
- **ACTUAL_NEXT_LIVE_EVIDENCE_TARGETS: 9** (LVT-01..09 in `remaining_live_evidence_targets.json`): speed-toggle grounding, AUTO cross-session replication, remaining control boxes (RESULT:ADVANCE / SCHEDULE:AUDITION / season SKIP/NEXT), TWO_CHOICE box, flush fail-closed drill, pause/resume epoch sample 2, viewport/DPR/zoom separation, season-transition flush boundary, fresh-season prep gate. Offline next steps (frame review, v0.4 rebuild, implementation queue) are listed separately and are not live work.

## Declarations

- RAW_EVIDENCE_CHANGED: NO (manifests, transcripts, run traces, recovered PNGs untouched; mining artifacts updated only via reconciliation overlays with history preserved)
- HARNESS_CHANGED: NO
- RUNTIME / BUSINESS_POLICY / SKILL_CHANGED: NO
- memory_index.json: one reconciliation session entry appended

**REGRESSION_MINING_RECONCILED_WITH_CURRENT_EVIDENCE**
