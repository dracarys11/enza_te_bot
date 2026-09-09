# ENZA Benchmark Coverage Audit & Gap Analysis v0.3

- **audit_id:** BENCHMARK_GAP_ANALYSIS_v0.3
- **date:** 2026-09-08
- **mode:** OFFLINE_ONLY — no game contact, no browser, no AGY/model calls, no runtime/planner/executor/policy modification, no existing benchmark case or gold modified
- **inputs:** benchmark `cases/` (ARB001–006 v0.1), `cases/v0.2/` (ARB101/102/103/105/108/110), `gold/` (v0.1 freeze + v0.2), `reviews/candidate_review_v0.2.md`; historical evidence `enza_memory/failures/` (12 files), `enza_memory/wing_runs/` (5 runs, timings/traces/records), `enza_memory/observations/` (OBS001–012), `enza_memory/audits/` (corpus gap report, stale reference audit); architecture `decision_agent/`, `action_gate.py`, `action_boundary.py`, `zcode_observation_loop.py`; protocols (VLM observation, event schema derivation `derive_event_metadata_v1.py`, evidence metadata `metadata_schema.json`/`bootstrap_metadata.py`)

---

## 1. Current benchmark coverage map

| dimension | case | scenario (evidence anchor) |
|---|---|---|
| risk gate vs inherited objective (planner authority) | ARB001 | S1W6 VOCAL at 92% trouble (`s1w6_vocal_executed_above_risk_gate_001`) |
| wedged observation channel; no invented action outcome | ARB002 | screenshot pipeline stall (`iab_screenshot_pipeline_stall_001`) |
| calibrated reasoning about detector false positive | ARB003 | detect_state WING_HOME FP + skill-board color FP |
| interrupted transaction; no duplicate business action | ARB004 | operator cancel of post-click wait |
| resisting review language beyond evidence boundary | ARB005 | v0_3 review batch + stale reference audit |
| semantic grounding vs stale legacy metadata (retrieval) | ARB006 | weekly_trace vs regression candidates |
| pre-actuation grounding calibration (hitbox UNKNOWN) | ARB101 | canvas_misclick_001 |
| interactability stop condition; no-effect repeat (battle) | ARB102 | frozen_battle_inspection |
| control ordering dependency (speed before Auto) | ARB103 | AUTO_LOCKS_SPEED_ORDERING |
| measured-latency batch budget; mid-batch abort UNKNOWN | ARB105 | timeout_debug_report |
| session-surface loss; server-vs-durable reconciliation | ARB108 | tabs lost after chat clear |
| probe side-effect criterion completeness | ARB110 | canvas_misclick_002 |

Held outside the benchmark (v0.2 KEEP family): case_104 (cadence, minor n=1/PROVISIONAL), case_106 (untaught business choice, counterfactual), case_107 (provider schema near-miss), case_109 (provider conversation resumption, counterfactual).

## 2. Covered dimensions (12)

planner/authority gating · observation-channel failure decoupling · detector false-positive calibration · pending-action reconciliation · adversarial evidence-boundary discipline · evidence retrieval grounding · pre-click grounding calibration · control interactability/phase discipline · control ordering · batch latency budgeting · session-loss reconciliation · probe verification completeness.

## 3. Missing dimensions (found by regression mining; all backed by real records)

1. **Recovery-scope conflation** — observation failure used as license for business-touching recovery (new tab + game reload + produce resume) without page-death proof. Real: pipeline-stall occurrences 1–3 recovered through game resume; occurrence #4 started a resume during an authorized execution attempt; the audit finding "recovery path unnecessarily opened new browser tab" records it, and the hardened `screenshot_pipeline.py` contract now forbids it.
2. **Evidence durability downgrade** — crash lost every frame of WINGRUN_20260906_01; evidence reconstructed from transcripts carries an explicit "NOT ORIGINAL REAL-TIME RAW TRACE" notice, and the registry scope_note excludes call-id-only frames from durable status. No case tests whether an agent keeps reconstructed evidence downgraded.
3. **No-effect commit-submit retry boundary** — twice recorded (`S1W5_COMMIT`, `S1W7_COMMIT`: "retry after one no-op 決定") with real double-commit risk; benign outcomes, no operator ruling on the retry boundary.
4. **Stale authority registry** — the registry designated as startup authority omits the two newest runs (one ACTIVE); documented in the corpus gap report, no runtime failure yet.
5. **Operator-evidence provenance classification** — user_reported frames must stay user_reported and stay out of autonomous detector replication counts (explicit note in `operator_reconcile_20260906_s3w1.json`).
6. **Assumed state default vs persisted state** — speed persisted across battles, overturning the per-battle reset assumption (hypothesis-grade, n=1).

Architecture scan (`decision_agent/`, `action_gate.py`, `action_boundary.py`, `zcode_observation_loop.py`): these boundaries (candidate grounding validation, gate APPROVED/REJECTED, observation freshness expiry, UNKNOWN-stops-loop) are implemented but have **no recorded live failure**; per the reject rules no candidates are proposed from them.

## 4. Recommended v0.3 cases (written to `candidate_cases/v0.3/`)

| case_id | dimension | evidence refs verified | gold | recommendation |
|---|---|---|---|---|
| case_201_observation_failure_must_not_trigger_business_recovery | recovery-scope conflation | 4/4 present | HIGH | **PROMOTE** |
| case_202_crash_backfill_evidence_durability_downgrade | evidence durability downgrade | 4/4 present | HIGH | **PROMOTE** |
| case_203_noop_kettei_single_retry_boundary | no-effect submit retry boundary | 3/3 present | MEDIUM | KEEP |
| case_204_registry_staleness_active_run_resolution | stale authority registry | 4/4 present | MEDIUM | KEEP |
| case_205_operator_evidence_provenance_classification | operator-evidence provenance | 3/3 present | HIGH | KEEP |
| case_206_cross_battle_speed_persistence_assumption | assumed default vs persisted state | 2/2 present | MEDIUM | KEEP |

## 5. Priority ranking

- **P0 (promote into v0.3):**
  - case_201 — recurrence count 5, directly caused wasted business-touching recoveries; hardened contract exists to grade against.
  - case_202 — only fully documented evidence-loss event; deterministic downgrade discipline; guards retrieval v0.2 correctness.
- **P1 (keep, promote on trigger):**
  - case_203 — real double-commit risk pattern, 2 benign occurrences; needs an operator retry-policy ruling to anchor gold.
  - case_205 — crisp provenance discipline; natural fit for the next adversarial batch together with case_106/107/109.
- **P2 (keep, evidence too thin):**
  - case_204 — documented latent trap, no failure event yet.
  - case_206 — n=1, explicitly hypothesis-grade (疑似).

Still open from v0.2 (unchanged, not re-filed): case_104 (cadence), case_106 (untaught choice), case_107 (schema near-miss), case_109 (provider conversation resumption) — counterfactual/minor family awaiting either a real occurrence or a deliberate adversarial-batch decision.

## 6. Boundaries

No runtime, planner, executor, policy, harness, existing benchmark case, or gold answer was modified. Candidates are corpus proposals only; they grant no execution permission and make no live claims.

**BENCHMARK_V0.3_AUDIT_COMPLETE**
