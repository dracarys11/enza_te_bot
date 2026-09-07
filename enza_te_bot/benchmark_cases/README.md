# benchmark_cases — Regression Corpus Mining v0.1

Offline benchmark cases mined from the recorded failure corpus
(`enza_memory/failures/`, `enza_memory/CASE_STUDY_WING_AGENT_RELIABILITY.md`).
Each case turns one recurring failure class into a replayable scenario that a
VLM or decision agent under test can be evaluated against — offline, with no
game contact and no execution authority.

Mined: 2026-09-07, from durable memory records only (offline mining session;
no environment observation or action).

## Case index

| case_id | failure class | source failures |
|---|---|---|
| `case_001_planner_authority` | Executor acts above a hard risk gate / planner authority separation | `s1w6_vocal_executed_above_risk_gate_001.json` |
| `case_002_observation_timeout` | Observation channel failure misread as action failure | `iab_screenshot_pipeline_stall_001.json` |
| `case_003_visual_ambiguity` | Overconfident automatic visual state classification | `detect_state_winghome_false_positive_001.json` (+ `skill_board_detector_color_fp_001.json` scenario B) |
| `case_004_pending_action_reconciliation` | Pending-action outcome UNKNOWN after interruption | `operator_cancel_pending_action_001.json` |

These four classes correspond to the four engineering lessons in
`enza_memory/CASE_STUDY_WING_AGENT_RELIABILITY.md`:

1. Planner is not executor (case_001).
2. Observation failure is not action failure (case_002).
3. Visual evidence is not action authority (case_003).
4. Recovery must reconcile, not retry (case_004).

## Case file contract

Each `case_*.json`:

- `schema_version: 1`, `artifact_type: "BENCHMARK_CASE"`, `status: "CANDIDATE"`.
- `inputs` reference real evidence **in place** (paths relative to the
  repository root) with SHA-256 digests where the pixels are load-bearing.
  Evidence is never copied or regenerated.
- `task` is the prompt given to the system under test.
- `expected_behavior` separates `FACT` (established by recorded evidence),
  `INFERENCE`, and `UNKNOWN` per `enza_memory/MEMORY_PROTOCOL.md` honesty
  rules.
- `grading` lists `pass` conditions and `hard_fail` conditions. A hard-fail
  condition mirrors the original incident: reproducing the recorded failure
  behavior is an automatic fail regardless of other outputs.
- `invariants_tested` references the runtime decision-boundary invariants in
  `.agent-harness/GATES.md`.

## Usage rules

- **Offline replay only.** Running a case never authorizes environment
  contact, clicks, or live automation. Cases evaluate the
  `VisionObservation -> GroundedElement -> ActionCandidate` boundary described
  in `CURRENT_MILESTONE.md`; an `ActionCandidate` is never execution
  permission.
- **Ground truth is bounded.** Expected behavior is derived from what the
  recorded evidence actually established (single-run, single-frame in most
  cases). It is candidate ground truth for regression comparison, not
  universal policy.
- **Adding cases.** Next free id: `case_005`. Candidate extensions recorded in
  the corpus but not yet mined: `tap_cadence_outran_text_typing_001.json`
  (action cadence vs surface latency), `gemini_v1_1_agy_timeout_001.json` /
  `gemini_v2_agy_timeout_001.json` (provider timeout continuation),
  `gemini_v1_schema_mismatch_001.json` (provider contract normalization),
  `canvas_misclick_001.json` (uncalibrated coordinate grounding).
