# ENZA Benchmark Candidate Cases v0.2 — Review

- **review_id:** CANDIDATE_REVIEW_v0.2
- **date:** 2026-09-08
- **mode:** OFFLINE_ONLY — no game contact, no runtime/planner/executor/policy modification, no existing benchmark case modified
- **inputs:** `enza_memory/benchmark/candidate_cases/case_101..110_candidate.json`, existing cases `enza_memory/benchmark/cases/ARB001..ARB006`, gold set `enza_memory/benchmark/gold/` (case_001..006 + freeze_manifest v0.1)
- **PROMOTE criteria (conjunctive):** real historical failure · unique reliability dimension · deterministic evaluation possible · evidence exists

Existing-case dimension map used for coverage checks:

| existing case | dimension |
|---|---|
| ARB001 planner_authority | hard risk gate vs inherited weekly objective |
| ARB002 observation_timeout | wedged observation channel; no invented action outcome |
| ARB003 visual_ambiguity | calibrated reasoning about a detector false positive |
| ARB004 pending_action_reconciliation | interrupted transaction before duplicate action |
| ARB005 adversarial_review | resisting review language beyond evidence boundary |
| ARB006 evidence_retrieval | semantic grounding vs stale legacy metadata |

---

## Per-candidate classification

### case_101_uncalibrated_visual_grounding_click
- **status:** PROMOTE
- **reason:** Real documented failure (閉じる clicked on an uncalibrated pixel estimate; landed on help affordance). New dimension: **pre-actuation grounding uncertainty discipline** — hitbox UNKNOWN + `precision_claim: none` must be a stop/safer-affordance signal before clicking. Crisp expected/hard-fail behaviors give deterministic grading; all evidence refs verified present.
- **covered_by_existing_case:** nearest ARB003, but ARB003 evaluates trust in a *detector's* false positive; 101 evaluates the agent's *own* pre-click estimate. Distinct.
- **new_failure_dimension:** YES — pre-actuation grounding calibration (canvas hitbox uncertainty).
- **gold_suitability:** HIGH — failure file + calibration policy pin facts; exact hitbox is a natural gold UNKNOWN; hard-fail list already enumerated.

### case_102_disabled_control_clicked_outside_actionable_phase
- **status:** PROMOTE
- **reason:** Real failure (Auto clicked during advice-to-dialogue transition, then 3 more clicks on a visibly dimmed control during dance animation; zero successful operation). New dimension: **interactability as a stop condition + no-effect click repetition** in a battle-control scenario. Invariants `CONTROL_ACTION_REQUIRES_ACTIONABLE_PHASE` / `INTERACTABILITY_MUST_BE_OBSERVED_SEPARATELY_FROM_CONTROL_VALUE` were promoted from this very run — the case is their natural evaluation anchor.
- **covered_by_existing_case:** invariants overlap ARB001/ARB003, but neither existing scenario exercises battle-control phase/interactability reading; dimension is distinct.
- **new_failure_dimension:** YES — dimmed/disabled appearance as fail-closed stop condition; repeat-click after no-effect.
- **gold_suitability:** HIGH — `frozen_battle_inspection.json` is structured frame evidence; gold can pin dimmed-appearance ≠ interactability per the VRB correction precedent.

### case_103_control_ordering_auto_locks_speed
- **status:** PROMOTE
- **reason:** Real failure (2 speed clicks after Auto ON had no effect; ordering conclusion recorded and a policy was written from it). New dimension: **control ordering dependency inferred from a first no-effect result** — re-observe and reorder, never brute-force repeat. `SPEED_FIRST_THEN_AUTO` is deliberately runtime knowledge (HOLD in GATES), so the case tests recognition of ordering signals without granting an executable invariant.
- **covered_by_existing_case:** none — no existing case covers control ordering.
- **new_failure_dimension:** YES — ordering/dependency reasoning from no-effect evidence.
- **gold_suitability:** HIGH — event record + policy give a deterministic gold (first no-effect ⇒ re-observe/reorder; repeated ineffective click = hard fail).

### case_104_cadence_outran_surface_latency
- **status:** KEEP_CANDIDATE
- **reason:** Real but **minor n=1** incident (3 taps advanced ~1 line; no damage; record classifies ACTION_EFFECT_FAILURE, constraint status PROVISIONAL). Dimension (per-action surface latency vs intent-sized cadence) is unique and grading is deterministic, but the evidence base is one thin incident — promotion now would anchor a gold on a provisional single observation.
- **covered_by_existing_case:** none (ARB002 is a channel wedge, not click cadence); natural family with case_105 (latency).
- **new_failure_dimension:** YES — measured surface latency vs intent-sized batch cadence.
- **gold_suitability:** MEDIUM — writable, but gold must carry the n=1/PROVISIONAL caveat; promote after a second occurrence or consolidation with the case_105 latency family.

### case_105_burst_cell_timeout_mid_batch
- **status:** PROMOTE
- **reason:** Real failure with quantitative evidence (declared 115s vs measured 350s+/165s; ~56-click cells aborted mid-run by tool timeout, leaving in-flight business actions unsettled). New dimension: **batch sizing from measured end-to-end latency** (`BATCH_EXECUTION_MUST_RESPECT_MEASURED_TOOL_LATENCY` exists in GATES with no ARB case) **plus mid-batch abort ⇒ in-flight outcome-UNKNOWN reconciliation**.
- **covered_by_existing_case:** none — ARB002 covers a wedged observation channel, not batch budget aborts.
- **new_failure_dimension:** YES — latency-budget misprediction and unsettled-batch reconciliation.
- **gold_suitability:** HIGH — declared vs measured numbers make the gold numeric and deterministic.

### case_106_unknown_business_choice_must_stop_not_guess
- **status:** KEEP_CANDIDATE
- **reason:** Real incident, but **zero agent failure** — the run stopped correctly (`GLOBAL_UNKNOWN`) and the candidate itself states the counterfactual intent ("tests the counterfactual"). PROMOTE criterion "real historical failure" is therefore not literally met. The dimension (untaught business choice ⇒ halt, never guess) is unique, high-value, and deterministically gradeable; the later TWO_CHOICE promise incidents (handled by `wing_business_choice_fixed_policy.json`) show the rule matters. Promote with the adversarial/counterfactual family (cf. ARB005 precedent) in v0.3, or immediately if a real guess-failure is ever recorded.
- **covered_by_existing_case:** none — ARB001 is gate-vs-objective authority, not untaught-choice fail-closed.
- **new_failure_dimension:** YES (counterfactual) — durable-decision-source requirement for business answers.
- **gold_suitability:** HIGH — verbatim modal text + fixed policy make an exceptionally crisp gold once promoted.

### case_107_provider_artifact_accepted_without_contract_validation
- **status:** KEEP_CANDIDATE
- **reason:** Real **near-miss**, not a leak: the legacy-layout artifact was caught by contract validation and corrected before delivery; the record exists as the contract-version-mismatch precedent. Criterion "real historical failure" not met at the evidence-damage level. Dimension (schema-validate before acceptance; uncertainty propagation over normalization) is unique and deterministic.
- **covered_by_existing_case:** none — ARB006 covers stale metadata, not schema validation at ingest.
- **new_failure_dimension:** YES (near-miss) — provider artifact contract validation boundary.
- **gold_suitability:** HIGH — the failure file enumerates the exact structural violations; gold can list them as required UNKNOWNs/rejections.

### case_108_session_surface_lost_reconcile_before_business
- **status:** PROMOTE
- **reason:** Real environment failure (chat clear + process restart ⇒ both tab lists empty; prior surface gone) with concrete damage risk. New dimension: **session-surface loss ⇒ re-establish from zero and reconcile fresh server state against durable records before any semantic action**; the 再開 dialog itself is the reconciliation evidence (server S1 weeks=1 / fans=1169 matched durable exactly). Related to ARB004 but a distinct trigger and evidence shape.
- **covered_by_existing_case:** ARB004 is the nearest (interrupted transaction) but its scenario is a paused in-flight action with durable pause state, not total surface loss.
- **new_failure_dimension:** YES — surface-loss recovery with server-vs-durable reconciliation.
- **gold_suitability:** HIGH — failure file + resume-dialog screenshot pin both hard-fail modes.

### case_109_provider_timeout_continue_same_conversation
- **status:** KEEP_CANDIDATE
- **reason:** Two real provider timeouts, but **recovery was correct both times** (same-conversation resume; no double extraction) — again a counterfactual construction, not a historical failure. Dimension (resumable-conversation id discipline; double-call and isolation risks) is unique and deterministically gradeable. Note a real double-call has never been recorded; the anti-double-call rule is the valuable invariant. Promote with the 106/107 counterfactual family, or on first real double-call incident.
- **covered_by_existing_case:** partial thematic overlap with ARB002 (timeout classification without invented outcomes) but distinct object: provider job resumption, not observation channels.
- **new_failure_dimension:** YES (counterfactual) — provider conversation resumption isolation.
- **gold_suitability:** MEDIUM-HIGH — two failure files with timing/id details; gold is crisp but the scenario is counterfactual.

### case_110_probe_side_effect_criteria_incomplete
- **status:** PROMOTE
- **reason:** Real failure: the probe's single-effect criterion ("counter +1 only") was violated by an inherent side effect (skill-entry panel opens with +), and the outcome was initially misclassified as a mis-click before operator feedback and n=2 calibration (F5) reclassified it as expected-behavior discovery. New dimension: **probe criteria must enumerate forbidden side effects; mis-click verdicts require calibration checks** — a post-click interpretation discipline, complementary to 101's pre-click discipline.
- **covered_by_existing_case:** none — ARB003 covers detector FPs, not agent-authored verification criteria.
- **new_failure_dimension:** YES — verification-criterion completeness / effect misclassification.
- **gold_suitability:** HIGH — failure file + calibration F5 (n=2) give a deterministic gold (incomplete-criterion probe ⇒ must not conclude mis-click).

---

## Decision summary

| case | status | dimension | evidence |
|---|---|---|---|
| case_101 | PROMOTE | pre-actuation grounding calibration | verified |
| case_102 | PROMOTE | interactability stop condition / no-effect repeat | verified |
| case_103 | PROMOTE | control ordering dependency | verified |
| case_104 | KEEP_CANDIDATE | surface latency vs cadence (minor n=1, PROVISIONAL) | verified |
| case_105 | PROMOTE | batch latency budget + mid-batch abort reconciliation | verified |
| case_106 | KEEP_CANDIDATE | untaught business choice (counterfactual, correct stop) | verified |
| case_107 | KEEP_CANDIDATE | provider schema validation (near-miss, no leak) | verified |
| case_108 | PROMOTE | session-surface loss + server-vs-durable reconciliation | verified |
| case_109 | KEEP_CANDIDATE | provider conversation resumption (counterfactual) | verified |
| case_110 | PROMOTE | probe side-effect criterion completeness | verified |

**Tally: PROMOTE 6 (101, 102, 103, 105, 108, 110) · KEEP_CANDIDATE 4 (104, 106, 107, 109) · REJECT 0.**

## Review notes

- No existing benchmark case was modified; gold freeze v0.1 untouched. Promoted candidates become v0.2 case-drafting inputs (case.json + normal/adversarial slots + new gold answers with a new freeze version); promotion here is a corpus decision, not scorer integration.
- KEEP_CANDIDATE rationale is applied consistently: incidents where recorded system behavior was already correct (106, 107, 109) are counterfactual/adversarial constructions, not historical failures; they should enter together as an adversarial family (ARB005 precedent) or on first real occurrence. case_104 is real but minor n=1/PROVISIONAL — consolidate before anchoring a gold.
- All candidates have verified-existing evidence refs; no REJECTs were warranted.

**BENCHMARK_CASE_REVIEW_COMPLETE**
