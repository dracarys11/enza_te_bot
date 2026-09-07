# Known Issues

Last updated: 2026-09-05

## Scope and status model

This register consolidates the recent architecture audits of the offline
Computer Use path:

```text
Screenshot -> VisionObservation -> GroundedElement
           -> Decision Agent -> ActionCandidate
```

It does not authorize live execution or change the current milestone. The
classifications are used as follows:

- **BLOCKER** — must be resolved before an `ActionCandidate` may be promoted
  into an automatically authorizable `ActionBoundary` request.
- **ACTIVE** — confirmed issue in the current offline evaluation path that
  should be addressed in the current or next bounded evaluation phase.
- **DEFERRED** — intentionally outside the current offline-replay milestone.
- **OBSERVATION** — verified fact, resolved issue, or constraint retained for
  regression and architectural context.

## BLOCKER

### KI-001 — Decision Agent evidence binding is structural but not semantic

- **问题**：`validate_action_candidate()` verifies that a `CLICK` target ID
  exists and that `evidence` is a non-empty list of strings, but it does not
  prove that those strings describe evidence belonging to the selected
  `GroundedElement`. It also does not require `text_evidence_status=MATCHED`,
  bind cited text-region IDs, compare candidate confidence with the element's
  confidence, or reject duplicate element IDs. A caller can therefore construct
  a formally valid candidate with an existing target ID and unrelated evidence.
- **发现来源**：Computer Use architecture audit, 2026-09-04;
  `decision_agent/base.py:29-69`; `decision_agent/grounded_decision.py:62-78`;
  current regression coverage in `test_decision_agent.py:66-81` checks a missing
  ID and forbidden coordinate fields but not forged evidence binding.
- **影响范围**：Decision Agent output validation, hallucinated-target defense,
  downstream candidate consumers, and any future Candidate-to-ActionBoundary
  adapter.
- **当前状态**：**OPEN / BLOCKING ACTIONBOUNDARY PROMOTION**. The concrete
  `GroundedDecisionAgent` selects exact text matches and fails closed on zero or
  multiple matches, but the shared `ActionCandidate` contract does not enforce
  the same evidence relationship.
- **建议修复阶段**：Decision Layer hardening, before ActionBoundary integration.
  Prefer a small deterministic validation extension using element and
  text-region identities rather than a new planning framework.

### KI-002 — Observation uncertainty is not propagated to the Decision Agent

- **问题**：`VisionObservation.uncertainties` and `overlay_regions` do not flow
  into `GroundedElement` or the `DecisionAgent.decide()` input. A uniquely
  text-matched element may therefore produce `CLICK` even when its bbox or
  intended hit point overlaps a declared uncertain or occluded region. Merely
  recording low confidence upstream does not currently make the decision fail
  closed.
- **发现来源**：Computer Use architecture audit, 2026-09-04;
  `vision_observation_schema.py:209-242`; `grounded_element.py:116-148`;
  `decision_agent/base.py:19-25`. Concrete OB-001 evidence:
  `test_data/ob001/fused_observation.json:567-606` places `e14` and its center
  inside a region marked
  `content_partially_clipped_by_bottom_viewport_edge`, while
  `test_data/ob001/action_candidate.json:2-9` records `CLICK e14` at confidence
  `0.99`.
- **影响范围**：missing-uncertainty handling, overconfident-click prevention,
  overlay/modal safety, clipped controls, and confidence interpretation.
- **当前状态**：**OPEN / BLOCKING ACTIONBOUNDARY PROMOTION**. Upstream honesty
  reporting exists, but the blocking signal is lost before selection.
- **建议修复阶段**：GroundedElement/Decision contract v0.2, before any execution
  adapter. Propagate only the minimum blocking uncertainty/occlusion facts
  needed to return deterministic `UNKNOWN`.

### KI-003 — ActionCandidate is not end-to-end bound to ActionBoundary freshness evidence

- **问题**：`ActionCandidate` contains no `source_observation_id`, `frame_id`,
  screenshot digest, expiry, scope, or typed evidence references. Grounded
  elements carry `source_observation_id`, but the candidate does not bind itself
  to it. The existing `ActionBoundary` correctly validates freshness and request
  binding once it receives an `ActionRequest`; the missing part is the trusted,
  deterministic bridge from the candidate and its source evidence into that
  request.
- **发现来源**：Computer Use architecture audit, 2026-09-04;
  `decision_agent/base.py:14-16`; `grounded_element.py:116-129`;
  `action_boundary.py:18-56` and `action_boundary.py:59-71` show the stronger
  freshness/request requirements that are absent from `ActionCandidate`.
- **影响范围**：stale-candidate prevention, cross-frame and cross-observation
  mixing, permission identity, action scope, replay safety, and auditability.
- **当前状态**：**OPEN / BLOCKING ACTIONBOUNDARY PROMOTION**. This is not a flaw
  in `ActionBoundary`'s internal freshness checks; it is a missing binding
  between the new Decision path and the existing boundary contract.
- **建议修复阶段**：bounded Candidate-to-ActionRequest adapter phase, after
  KI-001 and KI-002 and before enabling authorization. Preserve the existing
  ActionBoundary freshness, TTL, scope, and single-use semantics.

### KI-004 — Adversarial Decision benchmarks are insufficient

- **问题**：current Decision Agent tests cover one successful exact-text
  selection, textless `UNKNOWN`, multiple configured matches, invalid IDs, and
  forbidden execution fields. OB-002 contains five cases derived from the same
  frozen observation. It does not exercise similar labels, low-confidence exact
  text, overlays, target absence on a misleading page, mixed/stale observations,
  unsafe geometry, or forged evidence. OB-002's separate target-selection helper
  also raises `ReasoningBenchmarkError` on ambiguity instead of returning a
  structured fail-closed result.
- **发现来源**：Computer Use architecture audit, 2026-09-04;
  `test_decision_agent.py:34-100`;
  `test_ob002_reasoning_benchmark.py:21-30`;
  `ob002_reasoning_benchmark.py:98-117`.
- **影响范围**：hallucinated targets, overconfident clicks, semantic leaps,
  uncertainty behavior, model-agnostic compatibility, and regression confidence.
- **当前状态**：**OPEN / BLOCKING ACTIONBOUNDARY PROMOTION**. Happy-path replay
  is implemented, but readiness under adversarial input is not demonstrated.
- **建议修复阶段**：next offline benchmark increment, before ActionBoundary
  integration. Add at least the ten cases defined by the 2026-09-04 audit:
  duplicate exact labels; similar/OCR-confusable labels; textless icon; low
  confidence with uncertainty; overlay/uncertainty intersection; absent target;
  same label on the wrong page; mixed or stale observations; unsafe/out-of-bounds
  geometry; and forged candidate evidence or duplicate IDs.

## ACTIVE

### KI-005 — Goal-to-text mapping can make an unverified semantic leap

- **问题**：the agent converts a user goal through `target_text_by_goal` and then
  treats one exact text match as sufficient for a `CLICK`. For example, the
  OB-001 replay maps `Enter W.I.N.G. mode` to `次へ` without a verified page/room
  precondition or transition contract. The observation proves that text exists;
  it does not by itself prove that clicking it fulfills the goal.
- **发现来源**：Computer Use architecture audit, 2026-09-04;
  `evaluation/run_ob001_decision_test.py:19-28`;
  `decision_agent/grounded_decision.py:29-78`.
- **影响范围**：semantic-leap prevention, wrong-page same-label controls,
  confirmation dialogs, and route correctness.
- **当前状态**：**OPEN / OFFLINE-SAFE ONLY**. Risk is contained today because
  the candidate is inert and execution remains deferred.
- **建议修复阶段**：Decision Policy verification phase, before KI-003 is allowed
  to issue executable requests. Bind each mapping to a reviewed bounded context
  and expected post-action verification rather than introducing generic page
  understanding.

### KI-006 — The replay path does not enforce the full VisionObservation contract at its entry

- **问题**：the OB-001 replay reads JSON and passes it directly to
  `build_grounded_elements()` instead of first constructing or validating a
  `VisionObservation`. The GroundedElement builder validates selected fields but
  does not enforce the entire upstream contract, including capture metadata,
  viewport, and low-confidence uncertainty coverage.
- **发现来源**：Computer Use architecture audit, 2026-09-04;
  `evaluation/run_ob001_decision_test.py:22-28`;
  `grounded_element.py:132-148`;
  full validation exists separately in `vision_observation_schema.py:100-115`.
- **影响范围**：model-agnostic replay inputs, malformed or adversarial fixtures,
  and confidence that all downstream evidence passed the frozen observation
  boundary.
- **当前状态**：**OPEN**. The frozen OB-001 fixture is separately covered by a
  regression validation, but arbitrary replay input is not protected at this
  call boundary.
- **建议修复阶段**：offline replay hardening alongside KI-004; keep the frozen
  perception output unchanged.

### KI-007 — CLICK eligibility lacks an explicit confidence and obstruction policy

- **问题**：a unique exact-text match produces `CLICK` regardless of how low its
  `grounding_confidence` is. The Decision Agent has no explicit threshold or
  policy for uncertainty overlap, overlay blocking, viewport containment, or a
  safe hit point. Confidence is copied into the candidate but does not govern
  the decision.
- **发现来源**：Computer Use architecture audit, 2026-09-04;
  `decision_agent/grounded_decision.py:62-78`;
  `grounded_element.py:50-60` validates positive bbox dimensions but not viewport
  containment; `action_gate.py:120-133` demonstrates the existing distinction
  between visible and independently calibrated targets.
- **影响范围**：overconfident-click prevention, clipped controls, coordinate
  safety, Retina/window mapping, and future executor integration.
- **当前状态**：**OPEN**. The current ActionGate provides a downstream defense
  for screenshot-visible-only targets, but the new Decision path does not yet
  carry enough information to use that defense end to end.
- **建议修复阶段**：Decision benchmark and Candidate-to-ActionRequest adapter
  phases. Keep click authorization in ActionBoundary/ActionGate rather than
  moving execution policy into perception.

## DEFERRED

### KI-008 — Screenshot isolation is implementation-level, not capability-enforced for every DecisionAgent

- **问题**：the concrete `GroundedDecisionAgent` receives only grounded elements
  and a goal and has no screenshot dependency. However, the abstract Python
  interface cannot prevent a future implementation from reading a global path,
  file, or external source. The OB-002 statement “no screenshot access” is a
  harness arrangement rather than a general capability sandbox.
- **发现来源**：Computer Use architecture audit, 2026-09-04;
  `decision_agent/base.py:19-25`;
  `decision_agent/grounded_decision.py:1-8`;
  `ob002_reasoning_benchmark.py:1-15`.
- **影响范围**：future pluggable/model-backed Decision Agents and claims that all
  implementations are screenshot-free by construction.
- **当前状态**：**DEFERRED / NO CURRENT LEAK FOUND**. The present concrete agent
  and replay path do not read the screenshot, so this does not block offline
  v0.1.
- **建议修复阶段**：future external-model or plugin integration, only if such an
  implementation is introduced. Do not build a capability framework solely for
  the current deterministic agent.

### KI-009 — Autonomous ActionBoundary integration and execution remain out of milestone scope

- **问题**：the repository contains an existing `ActionBoundary`, `ActionGate`,
  and execution-permission model, but the new GroundedElement/Decision path is
  intentionally not connected to them. Screenshot-derived visibility is also
  not independent proof of clickability or calibration.
- **发现来源**：`CURRENT_MILESTONE.md:57-64`; `README.md:363-376`;
  `action_gate.py:129-133` and `action_gate.py:200-208` explicitly prevent
  screenshot-visible-only evidence from creating permission.
- **影响范围**：executor integration, live ZCode behavior, autonomous gameplay,
  and post-action verification.
- **当前状态**：**DEFERRED BY MILESTONE**. Live execution remains blocked; this
  is intentional and must not be treated as permission to weaken existing
  gates.
- **建议修复阶段**：a separately accepted ActionBoundary integration milestone,
  after KI-001 through KI-007 are closed and the workflow gates pass.

### KI-013 — Real AGY live invocation remains unpromoted

- **问题**：the local `agy 1.1.26` CLI exposes a verified print/conversation/model/
  timeout argument surface, and `agy_cli_runner.py` now maps it to the frozen
  runner DTO. However, no real extraction has been run in this milestone, so
  provider response timing, cancellation behavior, and final artifact
  provenance still require a separately approved live validation.
- **发现来源**：AGY Vision Bridge v0.1 implementation audit, 2026-09-05; no
  callable command contract was found in the requested Vision Agent, observer,
  fusion, skill, or harness sources.
- **影响范围**：live AGY invocation only. Offline fixture injection, schema and
  provenance validation, fusion, artifact routing, and ObserverMode consumption
  are regression-covered.
- **当前状态**：**DEFERRED / OFFLINE-CONTRACT-VERIFIED**. Bridge v0.2 freezes
  the pluggable data boundary as `AgyRunnerRequest -> AgyRunnerResult`; the real
  runner uses `shell=False`, one dispatch per request, bounded timeout,
  exact-conversation continuation when explicitly configured, and staging-only
  output. With no injected runner the bridge returns
  `UNKNOWN / AGY_COMMAND_UNCONFIGURED`; it never substitutes ZCode native
  vision or Paddle-only decision input.
- **建议修复阶段**：a separately approved live Phase A dry-run after a human
  reviews the command risk, timeout/cancellation policy, model identity, and
  artifact output behavior.

## OBSERVATION

### KI-010 — PaddleOCR document-preprocessing geometry mismatch is resolved

- **问题**：the pre-fix PaddleOCR configuration returned `rec_boxes`,
  `rec_polys`, and `dt_polys` in the document preprocessor's spatially warped
  output coordinate space. Equal 1280×720 dimensions did not make those
  coordinates valid in the original screenshot; neither uniform scaling nor a
  constant offset could correct the position-dependent displacement.
- **发现来源**：`docs/paddleocr_coordinate_audit.md:17-35` and
  `docs/ocr_geometry_audit.md:164-177`.
- **影响范围**：OCR-to-interaction text binding, overlays, original-viewport
  geometry, and any click target derived from OCR boxes.
- **当前状态**：**RESOLVED / REGRESSION-GUARDED**. The adapter disables
  `use_doc_orientation_classify` and `use_doc_unwarping` in
  `paddleocr_baseline.py:104-105`; the resolution is documented in
  `docs/paddleocr_coordinate_audit.md:157-161`, and
  `test_paddleocr_baseline.py:58-59` guards both settings. The OB-001 artifact
  was regenerated in original-screenshot coordinates.
- **建议修复阶段**：none. Retain the existing regression and re-audit only when
  upgrading PaddleOCR, changing preprocessing options, or changing coordinate
  extraction fields.

### KI-011 — Current concrete Decision Agent is screenshot-free and non-executing

- **问题**：this is a retained positive control rather than an open defect. The
  audit checked whether the concrete Decision Agent secretly consumes screenshot
  data or emits direct execution details.
- **发现来源**：Computer Use architecture audit, 2026-09-04;
  `decision_agent/base.py:19-25`;
  `decision_agent/grounded_decision.py:29-79`;
  `test_decision_agent.py:77-91`.
- **影响范围**：separation between perception, decision, authorization, and
  execution.
- **当前状态**：**VERIFIED FOR THE CURRENT IMPLEMENTATION**. It consumes supplied
  GroundedElements plus the user goal, emits only `CLICK` or `UNKNOWN`
  candidates, and does not emit coordinates or authorization. This does not
  resolve KI-001 through KI-008.
- **建议修复阶段**：none; preserve as a regression invariant during all later
  hardening work.

### KI-012 — Provider-first artifact classification was conceptually incorrect

- **问题**：legacy benchmark artifacts use generic names such as
  `gemini_output.json` or `agent_vision_output.json`. The first isolation fix
  then used `test_data/<provider-or-skill>/<case_id>/`, which mixed three
  independent concepts: provider, model, and skill. This could classify an AGY
  output under `gemini_v1` merely because it used a Gemini model or skill.
- **发现来源**：Vision Provider artifact-isolation maintenance, 2026-09-04;
  legacy layouts under `test_data/ob001`, `test_data/ob002`, and
  `test_data/ob003`.
- **影响范围**：v1/v2 comparison reproducibility, provider provenance, frozen
  benchmark evidence, and auditability.
- **当前状态**：**RESOLVED FOR NEW ARTIFACTS / REGRESSION-GUARDED**. OB-003 now
  uses `test_data/ob003/<case_id>/providers/<provider>/...`; each case owns the
  local screenshot, manifest, outputs, and reports. Metadata independently
  records provider/model/skill/source/hash/time. The audit found an artifact
  stored under the historical `gemini_v1` root whose own metadata identified
  AGY as the provider; its observation-first copy is correctly placed under
  `providers/agy/`. Tests prove that the same model and skill can belong to
  different providers, AGY/ZCode cannot be routed to Gemini directories,
  Paddle cannot contaminate visual-provider directories, hashes agree, and the
  unchanged benchmark accepts explicit observation-local paths.
- **建议修复阶段**：none. Preserve historical files in place. If provenance
  cannot be established from recorded content, list it as unresolved rather
  than guessing from its filename or directory.

## Promotion condition

No open BLOCKER in this register may be bypassed by high model confidence or by
the fact that a target is visible in a screenshot. Automatic ActionBoundary
promotion requires evidence binding, uncertainty propagation, fresh
observation/request binding, adversarial benchmark coverage, reviewed scope,
and the existing ActionGate calibration and permission checks. Until then,
`ActionCandidate` remains an inert offline evaluation artifact.
