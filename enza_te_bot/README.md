# enza Environment Agent Harness

## Project purpose

This repository is an experimental, governance-first computer-use agent harness
for the enza environment. Its purpose is to make evidence, authorization,
verification, and memory boundaries reviewable. It is not an autonomous
gameplay system and does not treat screenshots, demonstrations, or prior agent
claims as self-authorizing instructions.

The target lifecycle is:

```text
Observation
    ↓
Evidence classification
    ↓
Action authorization
    ↓
Bounded execution
    ↓
Independent verification
    ↓
Memory update
```

The repository also contains a legacy state-driven automation prototype. That
runtime remains separate from the Environment Agent design until the permission
and verification boundaries have been independently reviewed.

## Current capabilities

Implemented as artifacts, prototypes, or offline governance checks:

- Observation artifact collection
- Screenshot-based perception
- `FACT` / `INFERENCE` / `UNKNOWN` separation
- Failure memory
- Policy memory
- A mandatory memory update protocol
- An ActionGate design and side-effect-free prototype
- Offline governance testing

Not implemented as a safe Environment Agent runtime:

- Live autonomous execution
- Runtime ZCode integration
- Reliable canvas hitbox grounding
- Gameplay strategy
- Production automation
- Mandatory permission-token enforcement across every execution path

## Architecture

```text
ZCode
  |
Observation Collector
  |
Observation Artifact
  |
Memory Layer
  |
ActionIntent
  |
ActionGate
  |
ExecutionPermission
  |
EnvironmentProvider
  |
Verification
  |
Canonical Result
```

This diagram is the target governance boundary. `ExecutionPermission` and the
mandatory provider enforcement needed for live integration are still design
work. ZCode may contribute evidence artifacts, but it must not become the
planner, bypass authorization, declare completion, or directly control the
legacy runtime.

### Computer Use Harness data flow

The current Computer Use Harness separates screenshot capture, visual fact
extraction, semantic interpretation, policy, authorization, and execution:

```text
Capture Provider
  |
  v
Perception Layer
  |
  v
VisionObservation Contract v0.1
  |
  v
Observation Interpreter
  |
  v
Harness Policy
  |
  v
Human Approval / Action Boundary
  |
  v
Execution
```

The capture provider may be ZCode or another screenshot source. It supplies
pixels to the perception layer; it does not collapse capture, interpretation,
and action into one trusted step. The `VisionObservation` schema is the
boundary between visual perception and the evidence-based components
downstream.

The perception layer has one screenshot input and complementary raw-fact
sensors:

- PaddleOCR for primary text grounding
- Gemini Vision for visual grounding
- Tesseract as the text fallback when PaddleOCR returns no text regions

Its only output is `VisionObservation Contract v0.1`. Sensor fusion preserves
provenance per region: text regions identify the OCR source, while visual and
interaction candidates identify the visual-grounding source. Fusion does not
assign screen identity, infer progress, or authorize an action.

### Observation-first artifact isolation

Offline extraction artifacts are isolated observation-first. The comparison
unit is one screenshot case; provider, model, and skill are independent
provenance dimensions rather than interchangeable directory names:

```text
test_data/ob003/<case_id>/
  source_screenshot.png
  manifest.json
  providers/
    paddle/vision_output.json
    agy/
      gemini_vision_v1/vision_output.json
      gemini_vision_v1_1/vision_output.json
      gemini_vision_v2/vision_output.json
    zcode/vision_output.json
    gemini/
      v1/vision_output.json
      v1_1/vision_output.json
      v2/vision_output.json
  reports/
    comparison_report.json
```

The observation case is the first isolation boundary. All compared outputs sit
beside the same local screenshot and repeat its SHA-256. The first directory
below `providers/` names who generated the artifact: for example, an AGY result
using a Gemini model and `gemini_vision_v2` belongs under `providers/agy/`, not
under `providers/gemini/v2/`. A ZCode result using GLM belongs under
`providers/zcode/`. Paddle remains an OCR sensor artifact under
`providers/paddle/` and does not become a visual-provider artifact.

For a provider that intentionally stores several skill variants, such as a
direct Gemini provider, the skill directory is a second-level version
dimension. Benchmarks receive explicit artifact paths from the case manifest;
they do not infer provenance from filenames or scan a provider-first root.

Every new JSON artifact in this convention includes a top-level `metadata`
object:

```json
{
  "metadata": {
    "provider": "AGY",
    "model": "gemini-3.8-flash-medium",
    "skill_version": "gemini_vision_v2",
    "case_id": "OBS_example",
    "source_image": "source_screenshot.png",
    "screenshot_sha256": "sha256-without-prefix",
    "created_at": "2026-09-04T00:00:00Z"
  }
}
```

All seven values are required non-empty strings. Use `not_applicable` only when a
field genuinely does not apply; do not infer missing provenance from a filename
or use `skill_version` to choose a provider. This metadata is artifact
provenance, not a change to `VisionObservation v0.1`.

An observation directory also carries a manifest and a hash-bound local source
copy:

```text
OBS_<case_id>/
  manifest.json
  source_screenshot.png
  providers/<provider>/<artifact>.json
  reports/<report>.json
```

`manifest.json` records the `case_id`, the relative screenshot filename and
SHA-256 digest, and every provider name/artifact path available for that case.
Each listed artifact repeats the same digest as
`metadata.screenshot_sha256`. The artifact-isolation regression rejects a case
when the manifest digest, source file digest, and provider metadata digest do
not agree. Benchmarks still receive explicit artifact paths and do not assume
that files in one directory came from the same image. The manifest is discovery
and provenance metadata only and does not change benchmark comparison logic.
Artifacts whose provider/model/skill cannot be established from recorded
evidence remain in their historical location and are listed under
`unresolved_artifacts`; they are not silently classified. Earlier
provider-first directories are retained as historical inputs so migration does
not delete or overwrite benchmark evidence, but new artifacts must use the
observation-first convention.

The offline `VisionArtifactHarness` is the single persistence boundary for new
Vision Agent outputs. It derives the destination from `case_id` first, always
uses the filename `vision_output.json`, places AGY skill variants below
`providers/agy/<skill_version>/`, injects provenance and screenshot hash
metadata, updates the case manifest, and refuses to overwrite an existing
provider/skill result. A Gemini model name does not change the provider path.

### AGY Vision Bridge v0.2

`AgyVisionBridge` is the bounded perception-only connection from a caller's
screenshot through local PaddleOCR and an injected AGY extraction runner to the
existing fusion function. `vision_request(...)` returns a structured
`VisionRequestResult`; `AgyVisionBridge.observe(...)` exposes only the validated
fused VisionObservation for direct use by `ObserverMode`. Provider failures,
invalid or semantic output, provenance/hash/staleness failures, and artifact
conflicts return `UNKNOWN` without native-vision or execution fallback.

Case identity is supplied per request (`request(screenshot_path, case_id)`) or
by an injected `case_id_factory` for `ObserverMode`; a bridge no longer binds one
immutable case ID across frames. The provider boundary is explicitly
`AgyRunnerRequest -> AgyRunnerResult`. Offline fixtures implement that protocol;
future live-like configuration must pin an approved `expected_model`.

`AGY_VISION_BRIDGE_GATE` consumes digest-bound `GateEvidence` with a concrete
source and test identifier. A dictionary of caller-provided booleans cannot
promote the bridge.

The real AGY CLI command remains deliberately unconfigured (`agy_command=None`)
inside the bridge configuration. The separate `vision_agent.agy_cli_runner`
adapter implements the locally available `agy 1.1.26` print dispatch using an
argv list, `--model gemini-3.8-flash-medium`, bounded `--print-timeout`, and an
optional exact `--conversation` continuation. It writes only the staging path
from `AgyRunnerRequest`; bridge validation and canonical publication remain
downstream. The runner has only been exercised with fake executables in tests;
no live extraction was run in this milestone.

### Computer Use Agent Loop

The model-agnostic evaluation path separates visual perception, grounded
reasoning, and execution responsibility:

```text
Screenshot
  |--------------------|
  v                    v
Vision Agent       OCR/Text Sensor
  |                    |
  |--------------------|
           v
   Perception Fusion
           |
           v
   VisionObservation
           |
           v
   GroundedElement list
           |
           v
 Grounded Decision Agent
           |
           v
    ActionCandidate
```

The layers answer different questions:

- **Vision Agent — “What exists?”** It converts a screenshot into raw visual
  evidence governed by `VisionObservation v0.1`. The Gemini adapter reuses the
  existing `skills/gemini_vision/SKILL.md` contract and does not own a second
  prompt definition.
- **Decision Agent — “What should happen?”** It reasons only over supplied
  GroundedElements and the user goal. A candidate must reference an existing
  element ID; absent or ambiguous evidence produces `UNKNOWN`.
- **Executor — “How to perform it?”** This remains a separate downstream
  responsibility. The evaluation pipeline does not call it and an
  `ActionCandidate` is neither authorization nor execution.

The OB-001 replay harness reads the frozen fused observation, generates
GroundedElements, evaluates the configured goal, and writes an inert
`test_data/ob001/action_candidate.json` artifact. It sends no mouse or keyboard
input.

### Vision Boundary

The vision provider reports visual facts only. Its allowed output includes:

- OCR text
- Text bounding boxes
- Element candidates
- Numeric regions
- Overlays
- Unreadable regions
- Explicit uncertainty reporting

The vision provider must not emit or decide:

- `semantic_state`
- The current screen name
- The next action
- Strategy
- Execution permission
- Game-progress inference

Those restrictions keep screenshot recognition separate from state grounding,
policy evaluation, authorization, and execution.

### Grounding Principle

The system must not infer semantic state directly from screenshot appearance.
The required grounding flow is:

```text
VisionObservation
  -> ObservationInterpreter
  -> Grounded state candidate
```

State identity requires admissible evidence. Text position matters because a
label's role depends on where and how it appears. In particular, a button label
is not a screen title and therefore does not prove the current state. Shape or
coordinate evidence alone cannot establish identity; coordinate-only
observations remain `UNKNOWN`.

The same rules cover earlier failure modes: a visible button label does not
prove current state identity, file names are not evidence, coordinates are not
semantic states, and unknown observations must remain `UNKNOWN`.

### Human-in-the-loop Replay Harness

The MVP replay path is offline and human-controlled:

```text
Observation JSON
  -> Interpreter
  -> Policy evaluation
  -> HumanDecisionRecord
  -> Next observation
  -> Verification
```

The harness interprets supplied observation artifacts, evaluates the bounded
policy, records the proposed decision and human approval or rejection, and
compares the next observation with the expected verification rule. This mode
exists to validate grounding before autonomous execution; it does not itself
authorize autonomous gameplay.

### Current Computer Use MVP scope

The current validation target is the bounded sequence:

```text
HOME
  -> WING_SELECTION
  -> TRAINING_SETTINGS
  -> VOCAL counter verification
```

Within that target, the current OB-001 phase validates only:

```text
Screenshot
  -> VisionObservation
  -> Interpreter correctness
```

OB-001 does not validate autonomous gameplay execution. Execution remains
behind human approval or a separately bounded execution layer.

## Evidence model

`FACT` is evidence directly measured by the stated source, such as captured
pixels or a recorded browser value. A fact is local to its evidence and is not
automatically confirmed project knowledge.

`INFERENCE` is an interpretation derived from evidence, such as assigning a
page-state label from visible text.

`UNKNOWN` is missing, ambiguous, contradictory, stale, or otherwise unverified
information. It must remain visible and fail closed.

The non-promotion rules are absolute:

- `UNKNOWN` cannot become `FACT` without new evidence.
- Screenshot evidence cannot become DOM or accessibility evidence.
- `VISIBLE_ONLY` cannot become `CLICKABLE`, an exact hitbox, or verified game
  state.
- Confidence does not change evidence class.
- Evidence does not become executable policy without independent review.

## Memory model

Environment-agent memory is stored under `enza_memory/`:

```text
observations/   captured evidence packages
trajectories/   ordered observation, intent, execution, and verification records
failures/       anomalies, competing hypotheses, and recovery evidence
policies/       candidate constraints with provenance and review status
```

Memory is workflow evidence, not automatically training data or runtime policy.
Current permitted uses are:

| Use | Status | Limitation |
|---|---|---|
| Ground-truth training | No | Mixed provenance and inference must not become labels. |
| Evaluation benchmark | Yes | Candidate-only and limited to claims supported by cited evidence. |
| Failure analysis | Yes | Causes and hypotheses must retain their uncertainty. |
| Executable policy | No | Requires independent evidence, review, and explicit promotion. |

See [HARNESS.md](HARNESS.md), [MEMORY_SCHEMA.md](MEMORY_SCHEMA.md), and
[enza_memory/MEMORY_PROTOCOL.md](enza_memory/MEMORY_PROTOCOL.md) for the
normative session and memory requirements.

## Current phase status

| Phase | Status |
|---|---|
| Observation baseline | Completed |
| Memory protocol | Completed |
| AGY audit | Completed |
| OB-001 Perception MVP | Completed |
| GroundedElement v0.1 | Completed |
| Perception Stack v0.1 | Frozen |
| Decision Layer / ActionCandidate | Completed (offline evaluation) |
| Model-agnostic evaluation replay | Completed (OB-001) |
| ZCode integration | Not started |
| Live execution | Blocked |

## Perception Stack v0.1 Frozen

The screenshot perception boundary is frozen as a stable v0.1 baseline. This
freeze is a regression-protected reference point; later phases build on it and
must not silently change its behavior.

Frozen components and their contracts:

- **Gemini Vision Skill** (`skills/gemini_vision/SKILL.md` v0.1): JSON-only raw
  visual-facts extraction; semantic output fields are forbidden.
- **VisionObservation v0.1** (`vision_observation_schema.py`): strict schema +
  validation boundary between perception and downstream evidence components.
  Forbidden semantic fields are rejected at load; low-confidence regions must
  carry an explicit uncertainty entry.
- **PaddleOCR raw sensor** (`paddleocr_baseline.py`): raw text regions only,
  deterministic empty result on dependency failure. The coordinate audit
  (`docs/paddleocr_coordinate_audit.md`) established that document preprocessing
  must stay disabled for viewport-space geometry. The sensor now uses
  `use_doc_orientation_classify=False, use_doc_unwarping=False`, and the frozen
  OB-001 artifact has been regenerated with that configuration.
- **Perception Fusion** (`perception_fusion.py`): deterministic fusion with
  per-region provenance (`paddle` / `gemini` / `tesseract`); Tesseract is used
  only when Paddle returns no text regions.
- **GroundedElement v0.1** (`grounded_element.py`): visual region + text
  evidence + explicit `geometry_space: "original_viewport"` + provenance +
  two-layer confidence (`visual_confidence`, deterministic
  `grounding_confidence = min(visual, all text evidence)`). Textless regions
  stay `UNKNOWN` and are never guessed. No action, intent, or strategy fields.

Freeze regression coverage (`test_grounded_element.py`,
`test_perception_fusion.py`, `test_paddleocr_baseline.py`,
`test_vision_observation_schema.py`) protects:

- GroundedElements cannot contain action/semantic fields (rejected at build).
- `geometry_space` is always explicit and equals `original_viewport`.
- Provenance is preserved on every element and text-evidence record.
- UNKNOWN elements remain UNKNOWN.
- The frozen artifact `test_data/ob001/grounded_elements.json` must stay
  identical to what the current pipeline produces from
  `test_data/ob001/fused_observation.json`.
- The fused observation remains valid under `VisionObservation.validate`.

## Decision evaluation layer

The offline decision boundary is implemented by:

- `vision_agent/base.py` and `vision_agent/gemini_adapter.py` for the
  screenshot-to-visual-evidence interface;
- `decision_agent/base.py` and `decision_agent/grounded_decision.py` for
  validated `CLICK` or `UNKNOWN` candidates;
- `evaluation/run_ob001_decision_test.py` for replay from frozen OB-001
  evidence.

This layer may propose only an inert candidate. It contains no executor,
authorization token, mouse operation, keyboard operation, or ActionBoundary
mutation.

## Legacy deterministic runtime reference

The sections below describe the existing state-driven prototype. Their presence
does not authorize live Environment Agent execution. The prototype starts in
dry-run mode, uses configured visual templates rather than fixed waits, and
stops without clicking when the screen is unknown. It does not bypass
authentication, CAPTCHA, anti-bot, or game protections.

## Setup

```bash
cd /Users/koents/Documents/ChatGPT/enza/enza_te_bot
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python main.py --dry-run
```

## Browser target guard

The prototype refuses to take a game screenshot or click until it has connected to Chrome's DevTools Protocol (CDP) and found **exactly one** tab whose hostname is `shinycolors.enza.fun`. It brings only that tab to the foreground before capture. Set `browser.cdp_url` in `config.json` to your CDP endpoint, normally `http://127.0.0.1:9222`.

Launch the Chrome instance you use for the game with remote debugging enabled, then open the game in that instance. For example on macOS:

```bash
open -na "Google Chrome" --args --remote-debugging-port=9222 --user-data-dir=/tmp/enza-chrome-cdp
```

This launches a separate Chrome profile. Do not run the automation while there are zero or multiple matching game tabs: it will stop safely.

`game_window` is resolved before every screenshot from the unique visible game canvas or iframe in the CDP-targeted tab. All `roi` and action `box` values are normalized `[left, top, right, bottom]` coordinates within that dynamic window. `roi: null` searches the whole window. If DOM detection is ambiguous, `calibrate.py` offers an interactive fallback and records a viewport signature; that fallback is rejected automatically after a resize. Put captured PNGs in `templates/`, then list their filenames under the appropriate state. A state matches only when a template exceeds its confidence threshold. A full-desktop debug overlay is saved as `logs/current_game_window_debug.png`.

## First calibration

1. Capture a screenshot and inspect cursor coordinates:

   ```bash
   python calibrate.py
   ```

2. Create a template from a stable visual element (drag in the preview, then press Enter or Space):

   ```bash
   python capture_template.py home_marker
   ```

3. Capture templates and action boxes interactively. The tools persist only normalized game-window coordinates and create a backup before mutating `config.json`.

4. Test detection and the proposed click without interaction:

   ```bash
   python main.py --dry-run
   ```

5. The legacy runtime exposes a live command, but the Environment Agent harness
   does not currently authorize its use. Run it only under the repository's
   explicit live-debug authorization and gates for a separately approved,
   bounded command:

   ```bash
   python main.py --live
   ```

This command is documentation of the legacy interface, not approval for live
execution. Move the pointer to a screen corner to trigger PyAutoGUI's failsafe,
or press Ctrl+C for clean shutdown. Logs and UNKNOWN/transition-failure
screenshots are saved in `logs/`.

## Interactive teaching console

Run the single guided teaching session with:

```bash
.venv/bin/python main.py --teach
```

It never clicks an UNKNOWN screen. A configured click is only performed after
you press Enter at its prompt. Unknown screenshots and every console decision
are recorded in `logs/teach_<timestamp>.jsonl`; template/action updates create
a verified backup in `config_backups/` before changing `config.json`.

For a new label, choose `NEW_STATE` first, then enter the label. Entering an
unlisted label directly is intentionally rejected.

## Current architecture and scope

The project is a deterministic, fixed-SOP prototype. Its optimization target is
time-to-first-complete True End run for the known deck, without an LLM at
runtime. It is not a generic WING optimizer and does not currently implement
OCR, audition policy, skill-tree policy, rest policy, or continuous farming.

The intended control flow is room-oriented:

```text
HOME
→ policy decision
→ bounded room handler
→ interruption boundary when needed
→ verified room exit
→ HOME
```

Strict verification is retained at room entry, action preconditions, meaningful
known transitions, interruption boundaries, and room exit. Animation frames are
not promoted to global business states merely to satisfy a fixed-timing macro.
Unknown, ambiguous, unexpected, or timed-out UI always stops safely with
evidence.

### Current room: `VOCAL_ROOM`

`VOCAL_ROOM` is a single bounded attempt, not a loop:

```text
HOME
→ produce_start
→ PRODUCE_MENU
→ vocal_lesson
→ asynchronous post-Vocal observation
→ HOME exit, interruption boundary, UNKNOWN, or timeout
```

Its historical click evidence remains in `states.<STATE>.allowed_actions` as a
single source of truth. Inspect it without clicking:

```bash
.venv/bin/python main.py --show-transitions
.venv/bin/python main.py --show-rooms
```

The bounded room commands are:

```bash
.venv/bin/python main.py --run-room VOCAL_ROOM --dry-run
.venv/bin/python main.py --run-room VOCAL_ROOM --live
```

Use `--live` only after reviewing the current transition table and while the
dedicated CDP Chrome window contains exactly one game tab.

### Transition and UNKNOWN semantics

Actions follow this lifecycle:

```text
ACTION SENT → PENDING TRANSITION → COMMITTED DESTINATION
```

For `vocal_lesson`, the short verifier is only a fast path. An unresolved or
visually changing frame enters a bounded no-click post-Vocal observer instead
of being treated as an immediate click failure. Its deadlines are local:

- `post_vocal_transition_timeout_seconds` is a 20-second soft milestone.
- `loading_timeout_seconds` applies only after a taught `LOADING` anchor.
- `post_vocal_overall_timeout_seconds` is the 60-second hard ceiling.

The stable-UNKNOWN classifier samples several frames without clicking. A known
state cancels the candidate; a stable unmatched tail becomes
`CONFIRMED_UNKNOWN`; continued motion is `TRANSITION_IN_PROGRESS` and remains
the responsibility of the outer observer until its hard deadline.

### Generic dialogue control, not support-event identity

`DIALOGUE_FAST_FORWARD_OFF` means only that the shared lower-right
`早送り×4 OFF` dialogue control is visible. It is not evidence of a support-card
event. The preserved `templates/support_event_marker.png` is intentionally
registered under this generic control state.

Its one captured action is `dialogue_fast_forward_on`: it clicks the toggle
once, then performs bounded no-click observation. It must never click again to
toggle fast-forward back off. Its currently taught destinations are:

```text
HOME
CHOICE_REQUIRED
SEASON_CLEAR
SEASON_RESULT
```

`SUPPORT_EVENT` remains an inert future business label with no active template
or action until support-specific visual evidence is captured. The shared
dialogue control must not be promoted into a business-state label.

`CHOICE_REQUIRED` is also intentionally inert: it is the generic three-choice
boundary and always stops safely until a specific event rule is taught.

### Evidence and safety

- Dynamic macOS Retina conversion is central: game geometry is logical for
  click planning, screenshots are physical pixels, and all stored boxes/ROIs
  stay normalized to the dynamic game window.
- Every configuration mutation creates a timestamped backup and uses an atomic
  write. Existing screenshots, JSONL traces, templates, and backups are kept.
- `PyAutoGUI.FAILSAFE`, Ctrl+C shutdown, unique-CDP-target checks, URL
  revalidation, bounded clicks, and UNKNOWN evidence capture remain mandatory.
- Offline regressions cover room-step lookup, long post-Vocal motion, stable
  UNKNOWN confirmation, generic dialogue boundaries, and one-click dialogue
  behavior. Run them with `python -m unittest -v test_room_registry.py`.

---

# Runtime / Learning Artifact Index

> 导航索引，不是事实源。事实以各目录内 raw JSON/trace/screenshot 为准。
> 机器可读入口：`enza_memory/artifact_registry.json`。长期任务启动前先读 registry + 下面 Current Mainline。

## 1. Current Mainline

- Scenario: **W.I.N.G.**
- Evidence baseline: `enza_memory/self_exploration/SELFEXP_20260905_04`（WING entry 主证据）
- `ACTIVE_RUN = NONE`
- Resume authority: resolve `current_mainline.active_run` in `enza_memory/artifact_registry.json`, then load only that run's registry-listed checkpoint/run-local state. Never resume from hardcoded historical run text.
- Runtime status:
  - S1: CLEAR
  - S2: CLEAR
  - S3: COMPLETE
  - S4: NOT REACHED（S3 fan target missed; scenario concluded normally）
- Current blockers: BUSINESS_CHOICE detection promotion evidence / controls production promotion 未完成

## 2. Active Runs

| Run ID | Type | Scope | Status | Resume Point | Primary Path |
|--------|------|-------|--------|--------------|--------------|
| WINGRUN_20260905_01 | WING_RUN | WING | COMPLETED_ABANDONED / CLOSED | —（不可续跑） | `weekly_trace.jsonl` |
| WINGRUN_20260906_01 | WING_RUN | WING | COMPLETED_TARGET_NOT_MET / CLOSED | —（不可续跑） | `run_completion_record.json` |
| WINGVAL_20260905_01 | PROMOTION_EVIDENCE | WING | COMPLETED | —（无续跑） | `final_summary.json` |
| SELFEXP_20260905_04 | SELF_EXPLORATION | WING | COMPLETED | — | `summary.json` + `screenshots/` |
| LIVE_20260905_BOOTVIS | BOOTSTRAP_VISUAL | NONE | COMPLETED | — | `bootstrap_summary.json` |

## 3. WING Memory Map

### Strategy / Policy（可执行策略）
- `home_policy.py` — S1–S3 确定性决策（S4 返回 ROUTE_STATE_REQUIRED）
- `season3_audition.py` — S3 40k/50k 顺序与 unlock 阈值、flag commit 规则
- `ai_decisions/planner_rules_candidate.json` — CANDIDATE_ONLY，多被 unknown registry blocked
- `ai_decisions/unknown_registry_candidate.json` — 全部未决业务 unknown 及置信度
- `ai_decisions/room_sop_candidates.json` — 四种 room 的 SOP 候选（exit=FRESH_VERIFIED_HOME）
- `enza_memory/policies/wing_dialogue_fastforward_rule.json` — 早送り自动推进规则（CANDIDATE，已 1 次 run 验证）

### Run State / Trajectory
- `enza_memory/wing_runs/WINGRUN_20260905_01/`
  - `weekly_trace.jsonl` / `season_summary.json`（S1 CLEAR + S2 过渡）
  - `checkpoint.json`（恢复程序；注意其后 WINGVAL 已推进至 weeks=4，恢复必须 fresh screenshot 对账）
  - `loaded_strategy.json` / `unexpected_events.jsonl`

### Distilled Runtime Knowledge
`enza_memory/wing_runs/WINGRUN_20260905_01/distillation/`
- `decision_distillation.json` / `page_identity_distillation.json` / `control_distillation.json` / `transition_distillation.json` / `interruption_distillation.json` / `visual_budget_distillation.json` / `distilled_fast_runtime.json` / `over_analysis_findings.json`

### Promotion Audit
`enza_memory/wing_runs/WINGRUN_20260905_01/distillation/promotion_audit/`
- PROMOTE: interruption dual-channel detection；stable WING_HOME entry identity；weeks_remaining-1 = ROOM_COMPLETION_EVIDENCE（S1 scope）
- HOLD: VOCAL normal-week loop（WINGVAL 已给出 PROMOTION_EVIDENCE_READY，待重审）；BUSINESS_CHOICE dual-check detection（第 2 实例已在 WINGRUN resume 中检出，待重审）
- `CONTROLS_PRODUCTION_EXECUTABLE = NO`

### Cross-session Control Validation
`enza_memory/wing_runs/WINGVAL_20260905_01/` — control_validation / normal_week_validation / business_choice_validation / latency_validation / final_summary

## 4. Self-Exploration Evidence

| Session | Scope | Status | 用途 |
|---|---|---|---|
| SELFEXP_20260905_01 | GENERIC | COMPLETED | 通用导航/页面/控件记忆（historical supporting） |
| SELFEXP_20260905_02 | GENERIC_PRODUCE | FAIL_CLOSED | 发现 wizard tab 锁定（superseded by 03） |
| SELFEXP_20260905_03 | GENERIC_PRODUCE | COMPLETED | produce wizard 4-stage 模型；KNOWHOW 路径（OUT_OF_SCOPE_FOR_WING） |
| SELFEXP_20260905_04 | WING | COMPLETED | **PRIMARY WING ENTRY EVIDENCE** |

跨 session 审计：`enza_memory/self_exploration/cross_session_audit.json`

## 5. Visual / AGY Evidence

- AGY dispatch 记录：`logs/agy_bridge/<case_id>/`、`test_data/ob003/LIVE2F_*`
- 状态：全部 FAIL_CLOSED 或 result unavailable（OAuth 超时 / 外部终止 / 通道 wedge）
- **AGY_DISPATCHED != AGY_RESULT_AVAILABLE**；失败 dispatch 不得当视觉证据；对失败 case retry 被禁止
- 历史 6 图审计与 Paddle 坐标审计：`docs/paddleocr_coordinate_audit.md`、`docs/ocr_geometry_audit.md`
- agy CLI 认证已修复：需 `HTTPS_PROXY=http://127.0.0.1:7897`，令牌已持久化（`AUTH_OK` 验证过）

## 6. Runtime Benchmarks

| Benchmark | Status | Evidence |
|---|---|---|
| Normal-week no-AGY loop | PASS（2 独立周） | `enza_memory/wing_runs/WINGVAL_20260905_01/latency_validation.json` |
| Control geometry stability | STABLE（1280x720） | 同上 `control_validation.json` |
| 单周延迟基线 | ~39s（HOME 1.3s/guard 4.5s/执行 8.1s/推进 26s） | 同上 |
| Fast HOME cheap benchmark（旧） | 旧帧结果 UNKNOWN（season OCR 失败） | `enza_memory/wing_state_graph_v2.json` 引用 |
| production validated | NO — 全部为 candidate evidence | — |

## 7. Harness Invariants（runtime invariants 索引）

| Invariant | Status |
|---|---|
| FRESH_VISUAL_VERIFICATION_REQUIRED_BEFORE_ACTION | ACTIVE |
| URL_REACHABLE != STATE_VERIFIED | ACTIVE |
| AGY_DISPATCHED != AGY_RESULT_AVAILABLE | ACTIVE |
| weeks_remaining-1 = ROOM_COMPLETION_EVIDENCE（非 EFFECT_TRUTH，S1 scope） | ACTIVE（guarded） |
| DECISION_BOUNDARY_REQUIRES_FRESH_EVIDENCE | CANDIDATE |
| MINIMAL_OBSERVATION_IS_CONTEXT_DEPENDENT | CANDIDATE（distillation 已给证据） |
| IDENTITY_REQUIRES_VISUAL_PROVENANCE | CANDIDATE |
| AGY_FILESYSTEM_WRITE_BOUNDARY（staging-only） | ACTIVE（代码强制） |
| LIVE_RUN_EVIDENCE_DURABILITY | CANDIDATE |

## 8. Skill Status

- `gemini_vision_v1`（`skills/gemini_vision/SKILL.md`）：frozen，唯一 approved live skill
- v1.1 / v2（`test_data/gemini_v1_1`、`gemini_v2`）：research/historical，runtime 禁用
- AGY/Gemini vision **不属于** WING fast runtime 主路径；正常路径 = memory + cheap observation + native coarse vision；AGY 仅 escalation/audit/calibration

## 9. Known Blockers / Unknowns（active）

1. S4 route state 未定义（进入 S4 即 fail-closed）
2. BUSINESS_CHOICE 已拆分（operator fixed policy 已生效，见 `enza_memory/policies/wing_business_choice_fixed_policy.json`）：
   - 业务答案：不再是 blocker（2选1含「ごめん」→固定ごめん；3选1→固定中间项；其他→fail-closed）
   - 仍是 blocker 的部分：BUSINESS_CHOICE_DETECTION——2-card detector promotion evidence 积累中；未支持的选项形态/遮挡/数量不确定仍 fail-closed
3. 截图通道偶发 wedge（恢复程序见 checkpoint；3 次 bounded retry 后 STOP）
4. Controls production promotion 未完成（需更多跨 session/viewport 证据）
5. S3 audition flag 需显式 result evidence commit；旧 `config.json run_state.season3` 为遗留值不得污染新 run

## 10. Resume Guide

**标准启动纪律（所有长 run prompt 默认引用此节，无需重复列举文件）**

Before execution:

1. Read `README.md` → Runtime / Learning Artifact Index
2. Read `enza_memory/artifact_registry.json`
3. Resolve `current_mainline` and `active_run`
4. Read the registry-listed checkpoint / strategy / trace / distillation
5. Do not discover runtime truth from historical sessions unless referenced by the registry

然后：fresh screenshot 定态 → 与 checkpoint/最新 trace 对账 → 恢复 runtime。

## 自动更新规则

发生以下事件必须更新本索引与 `enza_memory/artifact_registry.json`：新建 SELFEXP/WING run、checkpoint、season clear、fail-closed、run completed、distillation 完成、Codex/promotion audit 完成、benchmark 完成、invariant promotion、skill 状态变化、blocker 增解。
