# ENZA VLM Observation Annotation Protocol v0.1

```text
OFFLINE_ONLY: YES
RUNTIME_CHANGES: NO
EXECUTION_AUTHORITY_CREATED: NONE
```

## 0. Status and inputs

- **Version:** v0.1 (candidate protocol; not executable policy)
- **Scope:** the observation layer between an evidence image and an event
  record — the contract for filling the `vlm` block defined in
  `enza_memory/evidence_metadata/metadata_schema.json`.
- **Inputs this protocol is derived from:**
  - `enza_memory/evidence_metadata/metadata_schema.json` (the `vlm` pending
    block, forbidden-field list, determinism guarantees)
  - event schema derivation rules
    (`enza_memory/evidence_metadata/derive_event_metadata_v1.py`:
    VLM fields are consumed as `VLM_APPEARANCE_ONLY` with confidence capped
    at `CONF_VLM_CAP = 0.5` and can never promote a field to FACT)
  - vocabulary corpora: OBS `page_state` labels, review-batch manifest
    `page`/`phase` values, `FILENAME_RULES`/`DIR_STATE_RULES` tokens
  - failure corpus: `detect_state_winghome_false_positive_001.json`
    (overconfident visual classification),
    `s1w6_vocal_executed_above_risk_gate_001.json` (visible control ≠
    authority), `iab_screenshot_pipeline_stall_001.json` (absence of pixels)
  - boundaries: `CURRENT_MILESTONE.md`, `.agent-harness/GATES.md`
    runtime decision-boundary invariants, `enza_memory/MEMORY_PROTOCOL.md`

## 1. Position in the pipeline

```text
image (read-only) ──> VLM annotation pass ──> vlm block (state, phase,
                          |                    event_type, visible_text,
                          |                    visible_controls,
                          |                    layout_family, vlm_status)
                          |                          |
             deterministic joins (OBS / review manifest /      |
             filename) remain the FACT-grade sources           v
                          └────────> event = {action, phase, result, state}
                                     (derive_event_metadata_v1)
```

The VLM pass annotates **what the pixels show**. Everything the project
already derives deterministically (OBS joins, review manifests, filename
conventions) outranks VLM output downstream. The VLM layer exists to cover
images those joins cannot classify, and to make visual appearance auditable —
never to replace session-observed claims.

## 2. Output contract

Exactly the `vlm` block fields from `metadata_schema.json`, plus `vlm_status`:

| field | content | vocabulary |
|---|---|---|
| `layout_family` | surface/geometry class of the image | §3.4 (annotate FIRST) |
| `state` | which screen identity the pixels show | §3.1 |
| `phase` | temporal position within that screen | §3.2 |
| `visible_controls` | affordances seen, each `SEEN` only | §3.3 |
| `visible_text` | readable text/numeric transcription | verbatim, appearance-only |
| `event_type` | optional appearance-level event hint | §3.5 |
| `vlm_status` | `PENDING` → `ANNOTATED` / `FAILED`; `OPERATOR_REVIEWED` after human review | closed set |

Rules:

1. One annotation per image, keyed by `record_id` (= image sha256). Original
   images are opened read-only and never modified; annotations are written
   only inside `enza_memory/evidence_metadata/`.
2. Every vocabulary field accepts `UNKNOWN`. **UNKNOWN is preferred over
   guessing.** A confident wrong label is strictly worse than UNKNOWN
   (regression: `detect_state` emitted AUDITION_BATTLE at confidence 1.0 on a
   WING_HOME frame — see §4, rule D2).
3. Each non-UNKNOWN field carries `confidence` in [0, 1] and a short
   `evidence_note` naming the visual discriminators used.
4. The forbidden properties of `metadata_schema.json` remain forbidden in
   every annotation: `authority_type`, `failure_category`,
   `planner_decision`, `execution_permission`, `action_permission`. They are
   process/authorization metadata and are not pixel-derivable.
5. An annotation never overwrites a durable claim. If the VLM label conflicts
   with an OBS-joined or review-manifest-joined value, both are kept: the
   durable value stays FACT-grade, the VLM value stays an appearance-only
   disagreement recorded in `evidence_note`.

## 3. Taxonomies (closed; extension requires a reviewed protocol version bump)

### 3.1 State taxonomy — screen identity

Bounded to states with corpus evidence (OBS labels, review manifests,
filename rules, failure records):

| value | corpus basis |
|---|---|
| `MAIN_LOBBY` | OBS_008, ngvg_17/18, r02_00 |
| `PRODUCE_SELECTION` | produceReady / プロデュース選択 (canvas_misclick_001 expected state) |
| `WING_HOME` | OBS_005–010, r02_08, winghome filenames |
| `SCHEDULE` | OBS_011, schedule filenames, s1w6 evidence |
| `TRAINING_SETTINGS` | canvas_misclick_002 state |
| `DIALOGUE` | dialog/dlg frames, POST_LESSON_EVENT_DIALOGUE family |
| `CHOICE` | choice frames, TWO_CHOICE / MORNING_3CHOICE / PROMISE_STORY |
| `AUDITION_SELECT` | audition_selection frames |
| `AUDITION_BATTLE` | battle frames, input_ready/stuck_frame/auto_toggle tokens |
| `SKILL_BOARD` | skill_board frames, recovered_frames/skill_board |
| `SKILL_REPLACEMENT` | recovered_frames/replacement |
| `COMMUNICATION` | comm frames, COMMUNICATION_SPLASH |
| `RESULT` | result frames, AUDITION_RESULT, RESULT_DIALOGUE family |
| `SEASON_RESULT` | rank_screen frames, OBS_012 |
| `SEASON_TRANSITION` | season tokens |
| `HELP_OVERLAY` | canvas_misclick_001 observed result |
| `UNKNOWN` | default when discriminators are absent or rival states tie |

Disambiguation rules:

- **S1 state-vs-phase rule:** `WING_HOME` vs `AUDITION_BATTLE` is the corpus'
  known confusable pair. A `WING_HOME` claim requires a top status bar with
  weeks/CLEAR markers, or corroboration from URL/durable context; top-right
  button brightness/layout-presence is a **non-discriminator** (recorded
  measurement: WING_HOME top-right satisfies the AUDITION_BATTLE
  page_layout_presence thresholds).
- Rival states must not be resolved by elimination of a single weak
  heuristic. If two state values remain plausible, output `UNKNOWN` plus both
  rivals in `evidence_note`.

### 3.2 Phase taxonomy — temporal position within a state

Canonical values (recognized corpus aliases in parentheses):

| value | meaning | aliases |
|---|---|---|
| `LOADING` | splash/transition in progress | LOADING_SPLASH, COMMUNICATION_SPLASH, TRANSITION, RESULT_STAGE_TRANSITION |
| `ANIMATION` | animated sequence playing; input semantics unknown | ANIMATION_DISABLED (alias kept), birth/lesson animations |
| `IDLE_ACTIONABLE` | screen settled and (apparently) interactive | ACTIONABLE_HOME, LOADED_ACTIONABLE, LOW_STAMINA_HOME |
| `INPUT_READY` | battle/interaction input explicitly expected | INPUT_READY, INPUT_READY_AUTO_ON, INPUT_READY_CANDIDATE, BATTLE_ACTIVE |
| `AWAITING_CHOICE` | choice overlay presented | CHOICE_PRESENT, TWO_CHOICE_PRESENT, PRE_BATTLE_CHOICE |
| `DIALOGUE_ADVANCING` | dialogue chain mid-flight | PLAIN_DIALOGUE, POST_BATTLE_DIALOGUE, PRE_RESULT_DIALOGUE, POST_RESULT_DIALOGUE, RESULT_ANNOUNCEMENT_DIALOGUE, RESULT_CONFIRMATION_DIALOGUE, SEASON_ENTRY_DIALOGUE, POST_LESSON_EVENT_DIALOGUE |
| `POST_ACTION_WAIT` | a click was reportedly sent and the outcome is not yet settled | kettei_sent naming convention |
| `RESULT_PRESENTED` | explicit result/reward surface visible | RESULT_REWARD_LIST, EXPLICIT_PASS, EXPLICIT_FAIL |
| `STUCK_UNKNOWN` | frame static but phase unverifiable | stuck_frame, STUCK_VISUAL_STATE |
| `UNKNOWN` | default | — |

Rules:

- Phase may be `UNKNOWN` while state is known, and vice versa; they are
  annotated independently.
- `POST_ACTION_WAIT` may be annotated only from image + provided context
  (e.g. a companion timing record); pixels alone cannot establish that a
  click happened.
- Result **values** (PASS/FAIL) are not phase output; §5 rule A3.

### 3.3 Visible-control taxonomy — seen affordances, `SEEN` only

Each entry records: control class, verbatim label text (or `UNREADABLE`),
and appearance attributes (e.g. `selected=true` on a lesson card is a visual
fact). Controls are annotated **as seen** — never as enabled, clickable, or
permitted (GATES: `INTERACTABILITY_MUST_BE_OBSERVED_SEPARATELY_FROM_CONTROL_VALUE`,
`CONTROL_ACTION_REQUIRES_ACTIONABLE_PHASE`).

| class | corpus examples |
|---|---|
| `CONFIRM` | 決定, OK |
| `NAVIGATION` | 戻る/back arrow, ホームに戻る, help back-arrow |
| `MENU_ENTRY` | スケジュール, オプション, プロデュース再開 / 再開, 再読み込み |
| `LESSON_CARD` | VOCAL / DANCE / VISUAL cards (+`selected` attribute) |
| `REST_CARD` | REST selection card |
| `GIVE_UP` | 諦める |
| `AUTO_TOGGLE` | Auto control (state observed as appearance only) |
| `SPEED_CONTROL` | Speed control |
| `SKIP_CONTROL` | SKIP / 選択肢まで |
| `TEXTBOX_ADVANCE` | dialogue textbox region |
| `CHOICE_OPTION` | two/three-choice buttons |
| `CLOSE` | 閉じる |
| `SKILL_ICON` | skill board icons (state rings are detector business, not VLM authority) |
| `SYSTEM_DIALOG` | browser/news-page chrome |
| `UNKNOWN_CONTROL` | visible affordance that fits no class |

Rules:

- No hitbox, precision, or coordinate claims (regression:
  `canvas_misclick_001` — uncalibrated visual-estimate clicking). Locations
  may be recorded as rough regions only, explicitly marked unverified.
- A `CONFIRM` button being visible is never a statement that pressing it is
  allowed, safe, or owned by the current objective (regression:
  `s1w6_vocal_executed_above_risk_gate_001` — 決定 was visible and grounded
  while execution was forbidden).
- Numeric text such as トラブル率 92% or 残り週 is transcribed under
  `visible_text` verbatim. Threshold interpretation (e.g. ">2% unsafe") is
  downstream policy work and must not appear in the annotation.

### 3.4 Layout-family taxonomy — surface/geometry class

| value | meaning |
|---|---|
| `IAB_CANVAS_1280X720` | current ZCode IAB canvas surface (DOM/accessibility unavailable) — the corpus' primary family |
| `IAB_CANVAS_OTHER_GEOMETRY` | IAB canvas at a different size/orientation (e.g. Retina-derived crops) |
| `HISTORICAL_RECOVERED_GEOMETRY` | recovered historical frames; surface never re-established (the `home_marker.png` taught-on-another-surface lesson: it scored 0.1948 vs its 0.85 threshold on IAB) |
| `ANNOTATED_OVERLAY` | derived/annotated visual (`REVIEW_BATCH_ANNOTATED`, `image_role=ANNOTATED_OVERLAY`) — never raw evidence |
| `NON_GAME_SURFACE` | news pages, browser chrome, error pages |
| `UNKNOWN_LAYOUT` | default |

Rules:

- `layout_family` is annotated **before** `state` and gates state matching:
  a template, heuristic, or expectation taught on one family must not be
  applied to another as if transferable.
- `ANNOTATED_OVERLAY` images are excluded from state/phase annotation
  entirely (they are derived pictures of evidence, not evidence pixels).

### 3.5 Event-type hints (appearance-level, optional)

Only these corpus-derived hints may be emitted, and only when the pixels
show the event mid-flight or its immediate visual trace; otherwise omit the
field:

`SKIP_VISIBLE`, `AUTO_TOGGLE_INDICATOR_VISIBLE`, `SPEED_INDICATOR_VISIBLE`,
`DECIDE_BUTTON_PRESSED_VISUAL_TRACE`, `RANK_SCREEN_PRESENT`,
`UNKNOWN_EVENT_HINT`.

This field is a hint for event derivation ordering only. It is never the
recorded action; a dispatched action lives in trajectory/durable records
(action-sent vs committed stays a runtime distinction).

## 4. Annotation rules (fail-closed)

- **A1 — Observation only.** Output describes pixels. No authority, no
  planner decision, no execution permission, ever.
- **A2 — UNKNOWN over guessing.** Missing discriminators → `UNKNOWN` + named
  missing evidence. UNKNOWN is a valid, expected, first-class output.
- **A3 — No semantic verdicts.** No PASS/FAIL, no risk-gate evaluation, no
  "this action failed/succeeded", no objective ownership. These require
  policy + fresh-evidence context that pixels do not carry.
- **A4 — No authority escalation.** An annotation must never be cited as
  permission to act, as a planner decision, or as ground truth over a
  durable record. Downstream, VLM-derived fields are capped at
  APPEARANCE_ONLY / confidence ≤ 0.5 and never FACT
  (`derive_event_metadata_v1`).
- **A5 — Discriminative evidence required for state claims.** A state claim
  must cite a discriminator that actually separates the claim from its
  nearest rival (§3.1 confusable pair). Single weak heuristics (brightness
  regions, template on unverified family) justify `UNKNOWN`, not a claim.
- **A6 — Absence of pixels is annotated, never interpreted.** If no image is
  obtainable (capture timeout/stall), there is nothing to annotate: the
  record stays `PENDING`/`FAILED` with the tool receipt in the note, and no
  game/action verdict is derived from the absence
  (`iab_screenshot_pipeline_stall_001`).
- **A7 — Read-only corpus.** Original images are never modified or moved;
  annotations live only in `enza_memory/evidence_metadata/`.
- **A8 — Conflicts are preserved, not resolved.** VLM vs durable disagreement
  is recorded as a disagreement (§2 rule 5). Silent repair is forbidden
  (MEMORY_PROTOCOL honesty rules).

## 5. Authority boundary (normative restatement)

1. **No authority.** An annotation grants nothing: not interactability, not
   safety, not objective ownership.
2. **No planner decision.** Weekly objectives, gate evaluations
   (e.g. `VOCAL_RISK_ALLOWED`/`VOCAL_RISK_BLOCKED`), and business choices
   are planner/policy layers. The VLM must not emit their vocabulary.
3. **No execution permission.** No annotation may be consumed as an
   ActionCandidate authorization; `CURRENT_MILESTONE.md`: candidates are not
   execution permission, and annotations are strictly upstream of candidates.
4. **Unknown is preferred over guessing** — in every field, every time.

## 6. Regression hooks

- `benchmark_cases/case_003_visual_ambiguity.json` — the canonical test that
  an annotator obeys §3.1/A5 (no overconfident misclassification on the
  recorded WING_HOME frame).
- `benchmark_cases/case_001_planner_authority.json` — the canonical test that
  a visible control is not treated as authority (§3.3/§5).
- `benchmark_cases/case_002_observation_timeout.json` — the canonical test
  for A6 (no annotation from absent pixels; no action verdict derived).
- `test_vision_observation_schema.py` — the VisionObservation contract that
  rejects forbidden semantic fields; this protocol keeps the annotation layer
  inside that boundary.

Final: VLM_OBSERVATION_PROTOCOL_CREATED
