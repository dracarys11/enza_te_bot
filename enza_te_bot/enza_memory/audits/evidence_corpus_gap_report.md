# Evidence Corpus Gap Report — Vision Evidence Retrieval v0.2 readiness

- **audit_id:** EVIDENCE_CORPUS_GAP_AUDIT_20260907
- **mode:** OFFLINE_ONLY — no game contact, no browser, no AGY, no artifact modification
- **generated_at:** 2026-09-07
- **inputs read:** `enza_memory/artifact_registry.json`, `enza_memory/memory_index.json`, `enza_memory/wing_runs/*`, `enza_memory/migration/python_click_migration/*`, `enza_memory/runtime_contracts/*` (battle + room contracts), `enza_memory/observations/`, `enza_memory/failures/`, `enza_memory/trajectories/`, reconciliation reports (run-level, migration-level, contract-level)
- **required fields evaluated:** `image`, `run_id`, `trajectory`, `phase`, `state`, `event_type`, `action`, `failure_category`, `authority_type`, `confidence`

Legend: **YES** = present as structured field · **PART** = partially present / prose or adjacent field · **DER** = derivable only by convention (e.g. directory name) · **NO** = absent · n/a = field not meaningful for the category.

---

## 1. CURRENT_COVERAGE

Corpus inventory (counts verified on disk):

| category | volume | primary metadata home |
|---|---|---|
| A. Run screenshot corpora (`wing_runs/*/screenshots/`) | 165 + 0 + 121 + 142 + 6 ≈ **434 png** (WINGRUN_20260906_01 has **0** — frames lost in crash; `crash_recovery_backfill.json` cites non-durable call ids) | none (filename prefixes only: `r02_*`, `r07_s1w8_*`, `ngvg_*`) |
| B. Click samples (`click_samples.jsonl`) | 29 entries | self (rich control-level schema) |
| C. Evidence coverage matrix (`evidence_coverage_matrix.json`) | 40 scored rows | self (7-dimension 0–3 scoring) |
| D. Review batch manifests (`review_batches/v0_3/review_manifest.jsonl` + v0_2/shadow/skill_board batches) | 38 entries (+38 annotated +38 original png) | self (closest to target schema) |
| E. Battle frames + reconciliation (`recovered_historical_frames/battle/` 17 png, `integration/battle_reconciliation.json`, `audition_battle.json` contract, `AUTO_VISUAL_AUTHORITY_CORRECTION`) | 17 png + verdict blocks | reconciliation overlays |
| F. Runtime room contracts (`runtime_contracts/*.json`) | 11 contracts | self (phases/authority/failure modes, no per-image binding) |
| G. Reconciliation reports (run/migration/contract level) | ~10 documents | self (verdict/prose) |
| H. Observations (`observations/OBS001..OBS_012`) | 12 schema-compliant OBS | self (screenshot+sha256+page_state+provenance) |
| I. Failures (`failures/*.json`) | 12 files | self (classification + evidence refs) |
| J. Trajectories (`trajectories/*`, run trajectory files) | 10 files | self (steps with provenance/confidence) |

### Coverage matrix (per category × required field)

| category | image | run_id | trajectory | phase | state | event_type | action | failure_category | authority_type | confidence |
|---|---|---|---|---|---|---|---|---|---|---|
| A. run screenshots | YES (file) | DER (dir) | NO | NO (filename hint) | NO (hint) | NO | NO | NO | NO | NO |
| B. click samples | NO | NO | NO | NO | YES | NO | PART (result/postcondition) | NO | NO | NO |
| C. coverage matrix | NO | NO | NO | NO | YES (room/state/control) | NO | YES (control) | NO | PART (AUTHORITY score, not type) | PART (scores, not calibrated) |
| D. review manifests | YES (+sha256 ×2) | YES (`source_run`) | NO | YES | YES (`page`/`room_identity`) | PART (`event_context`/`source_event`, often null) | PART (`recommended_action`) | NO | NO | NO (`priority`/`human_review_required` only) |
| E. battle frames + reconciliation | YES | PART (session id in filename) | NO | PART (filename tags + verdict blocks) | PART | NO | NO | NO | PART (corrected UNKNOWN/anti-overclaim blocks, not per-frame field) | NO |
| F. runtime contracts | n/a | n/a | n/a | YES | YES | PART | YES (`ALLOWED_ACTIONS`) | YES (`FAILURE_MODES`) | YES (`ACTION_AUTHORITY`) | NO |
| G. reconciliation reports | PART | YES | PART | PART | PART | NO | PART | YES (prose/verdicts, no vocabulary) | PART | NO |
| H. observations (OBS) | YES (+sha256) | PART (`run_id` on run-tagged OBS) | PART (`source_artifact_ids`) | YES | YES (`page_state`) | NO | NO | NO | NO | YES (`page_state.confidence`) |
| I. failures | YES (evidence refs) | YES | YES | PART | PART | NO | PART | YES (`classification`) | NO | PART (per hypothesis) |
| J. trajectories | PART (evidence_ids) | YES | YES (self) | NO | NO | NO | YES (`intent_id`/`execution`) | NO (lives in failures) | PART (`gate_decision_id`) | YES (per claim) |

### Corpus-wide field verdicts

- **image:** YES (files + sha256 binding exist; but only OBS/review-manifest items carry the binding — plain run screenshots have no sidecar)
- **run_id:** PART — durable for D/H/I/J; derivable from directory for A; absent for B/C/E
- **trajectory:** **NO corpus-wide** (only self-referential in J/I); no evidence item outside trajectories links back to a trajectory step
- **phase:** PART (strong in D/F; absent in A/B/E as structured field)
- **state:** PART (strong in B/C/D/F/H; filename hints only in A)
- **event_type:** **NO corpus-wide** (nearest: `event_context`/`source_event`, frequently null)
- **action:** PART (normalized only in C/F via `control_key`/`ALLOWED_ACTIONS`; no per-image action)
- **failure_category:** NO as controlled vocabulary — exists as `classification` strings inside I and prose inside G
- **authority_type:** **NO as per-item field** — exists as contract blocks (`ACTION_AUTHORITY`), scoring dimension (C), corrected anti-overclaim blocks (E); the S1W6 authority incident and the VRB interactability overclaim corrections demonstrate why this field must be explicit
- **confidence:** PART — calibrated only inside H (`page_state.confidence`) and J (per-claim); absent everywhere else

### Known corpus integrity risks found during audit (read-only observations)

1. **Registry freshness gap:** `artifact_registry.json` (updated 2026-09-06T11:00Z) does not list `WINGRUN_20260907_01` / `WINGRUN_20260907_02`; run_id resolution for those corpora currently relies on directory/timings conventions.
2. **Durability loss:** all WINGRUN_20260906_01 frames are non-durable (crash); backfill cites session call ids — retrieval v0.2 must either exclude or downgrade these rows.
3. **Provenance-by-filename:** category A (the largest corpus, 434 png) has no sidecar; any indexing must re-derive phase/state, which the `detect_state` false-positive finding (`detect_state_winghome_false_positive_001`) shows is not reliable unaided.

---

## 2. HIGH_VALUE_MISSING_METADATA

### P0 — needed for agent reliability evaluation

1. **`run_id` + `trajectory` step link on every evidence item** (categories A, B, C, E). Without them, no frame can be tied to the decision/gate that produced it; reliability evaluation cannot reconstruct the action→evidence chain.
2. **`authority_type` per evidence item** with a controlled vocabulary, e.g. `SESSION_OBSERVED / OPERATOR_AUTHORIZED / PLANNER_GATE / DERIVED_INFERENCE / APPEARANCE_ONLY`. Motivated by recorded incidents: S1W6 VOCAL executed above risk gate; VRB02 battle frames corrected for interactability/phase/causality overclaims (`AUTO_VISUAL_AUTHORITY_CORRECTION`). Appearance-derived claims must be structurally distinguishable from gate-authorized ones.
3. **`failure_category` controlled vocabulary** (e.g. `ENVIRONMENT_TOOL_FAILURE`, `OBSERVATION_UNAVAILABLE`, `POLICY_VIOLATION`, `ACTION_NO_EFFECT`, `UNKNOWN_OUTCOME`, `STATE_TRANSITION_ANOMALY`) applied across I and G, and retroactively indexable for A/E. Currently locked in prose; the screenshot-pipeline stall series (5 occurrences) and the authority violation are the highest-value reliability series and cannot be queried today.
4. **`image` + sha256 sidecar for category A** (largest corpus, zero metadata). Even a minimal sidecar (`{image, sha256, run_id, captured_at, phase_hint}`) converts 434 orphan frames into retrievable evidence.

### P1 — needed for retrieval quality

5. **`state` + `phase` as controlled enums aligned with the runtime contract substates** (`WING_HOME`, `SCHEDULE`, `AUDITION_BATTLE`, `RESULT`, `DIALOGUE`, `CHOICE`, `SEASON_RESULT`, … × `ACTIONABLE_HOME`, `INPUT_READY`, `ANIMATION`, `TRANSIENT`, …). Current values are free-text (`page`, `state` strings differ across categories).
6. **`event_type`** (e.g. `SUPPORT_EVENT`, `MORNING_THREE_CHOICE`, `PROMISE_CHOICE`, `PIPELINE_STALL`, `SEASON_RESULT`, `FES_IDOL_BIRTH`). Required to answer "show me all choice-shaped frames" or "all tool-failure windows" — today only partially inferable from prose.
7. **`confidence` calibration**: numeric confidence + evidence classification (FACT/INFERENCE/UNKNOWN) per item, per the MEMORY_SCHEMA honesty rules; `priority`/scores (C/D) are not confidence and must not be conflated.
8. **`action` normalized to `control_key` vocabulary** (`HOME:SCHEDULE`, `AUDITION_BATTLE:AUTO_ON`, …) so frames join with click samples and the coverage matrix.

### P2 — nice to have

9. `viewport_profile` on all image-bearing items (exists only in B).
10. `layout_family` / `overlay` annotations (fields exist in D but mostly null).
11. Cross-session replication count and negative-evidence flags (matrix dimension, not per item).
12. `annotated_image`/`original_copy` dual-file pattern generalized beyond D.

---

## 3. 5080_NEXT_PIPELINE_INPUT

Fields recommended for VLM generation in the next pipeline stage (vision-derivable only):

| field | VLM role | caveat |
|---|---|---|
| `state` (page identity) | primary VLM target: classify page/state from full frame (WING_HOME / SCHEDULE / AUDITION_BATTLE / RESULT / DIALOGUE / CHOICE / SEASON_RESULT …) | must supersede the unreliable template path (see `detect_state_winghome_false_positive_001`); emit `UNKNOWN` fail-closed on low confidence |
| `phase` | classify from control layout + overlays (INPUT_READY / ANIMATION / RESULT / TRANSIENT) | static frames under-determine phase; emit appearance-only claims |
| `event_type` markers | detect SKIP button, choice panels, rank screens, birth animations, 評価 screens | enumerable checklist; high precision expected |
| `visible_controls` + control appearance | list visible controls and apparent ON/OFF state | **must** emit `authority_type=APPEARANCE_ONLY` — appearance ≠ interactability (VRB02 correction) |
| OCR payloads | トラブル率 badge, fan counters, week digits, stat rows | cross-check against taught detectors; disagreement ⇒ UNKNOWN, not overwrite |
| frame hygiene | blur/black/white/duplicate detection → STALE_FRAME flag | feeds the screenshot-pipeline OBSERVATION_UNAVAILABLE boundary |
| embedding/vector + caption | retrieval index for free-form queries | caption must be grounded; no gameplay-strategy inference |

**Must NOT be VLM-generated (process metadata, not pixel-derivable):** `run_id`, `trajectory`, `authority_type` (authorization provenance), `failure_category` (process outcome), `confidence` for authorization decisions (may only be calibrated from VLM↔taught-detector agreement, never asserted). These stay pipeline/operator-side fields attached at ingest.

Recommended join key: `image sha256` as primary identity (already minted in D/H; missing for A), with `run_id`+`trajectory_step_id` attached from the durable session records at ingest time.

---

## 4. DO NOT CHANGE

No runtime, planner, executor, policy, Harness, or existing artifact was modified in this audit. `detect_state` misclassification, registry staleness, and crash-lost frames are recorded here as findings only; remediation is out of scope for this audit.

---

**Final: EVIDENCE_CORPUS_GAP_AUDIT_COMPLETE**
