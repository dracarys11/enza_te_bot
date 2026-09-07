# Current milestone: Model-agnostic Computer Use Evaluation v0.1

## Status: IMPLEMENTED — OFFLINE REPLAY ONLY

The screenshot perception boundary remains frozen as a stable v0.1 baseline.
The current layer evaluates `VisionObservation -> GroundedElement ->
ActionCandidate` without execution or authorization.

## Frozen baseline

- **VisionObservation v0.1** (`vision_observation_schema.py`): strict contract
  between perception and downstream evidence components. Forbidden semantic
  fields rejected at load; low-confidence regions require explicit uncertainty.
- **Gemini Vision Skill v0.1** (`skills/gemini_vision/SKILL.md`): JSON-only raw
  visual-facts extraction, no semantic output.
- **PaddleOCR raw sensor** (`paddleocr_baseline.py`): raw text regions only.
  Geometry note (`docs/paddleocr_coordinate_audit.md`): document preprocessing
  is disabled with `use_doc_orientation_classify=False` and
  `use_doc_unwarping=False`; the OB-001 artifact has been regenerated in
  viewport-space geometry.
- **OCR Fusion pipeline** (`perception_fusion.py`): deterministic fusion with
  per-region provenance (`paddle` / visual artifact `metadata.provider` /
  `tesseract`); Tesseract only as fallback when Paddle returns no text regions.
- **Observation-first artifact isolation**
  (`test_data/ob003/<case_id>/providers/`): each screenshot case owns its local
  source, manifest, provider outputs, and reports. Provider is the first output
  directory; model and skill remain independent metadata dimensions (with an
  optional skill subdirectory when one provider has variants). Every listed
  artifact repeats the local source SHA-256 so stale JSON cannot silently bind
  to replaced pixels. Unresolved historical provenance remains explicitly
  unclassified instead of being guessed from filenames. New writes use the
  offline `VisionArtifactHarness`, which fixes the filename as
  `vision_output.json`, keeps AGY skill variants under
  `providers/agy/<skill_version>/`, and refuses exact provider/skill
  overwrites.
- **AGY Vision Bridge v0.2** (`vision_agent/agy_vision_bridge.py`): offline,
  fail-closed Paddle + injected AGY extraction + existing fusion orchestration.
  Each request has an explicit case ID or injected per-frame ID factory;
  `ObserverMode` receives only validated fused VisionObservation data. The
  runner boundary is structured as `AgyRunnerRequest -> AgyRunnerResult`, while
  `vision_agent/agy_cli_runner.py` implements the real `agy 1.1.26` dispatch
  boundary with argv-only subprocesses, bounded timeout, staging-only output,
  and optional explicit conversation continuation. Live-like configuration must
  pin the approved model. The promotion gate requires digest-bound evidence and
  creates no execution authority; no live run has been authorized here.
- **GroundedElement v0.1** (`grounded_element.py`): visual region + text
  evidence + `geometry_space: "original_viewport"` + provenance +
  deterministic confidence (`grounding_confidence = min(visual, all text)`).
  Textless regions stay `UNKNOWN`; no action/intent/strategy fields.

## Regression coverage

- `test_vision_observation_schema.py` — contract validation, forbidden fields.
- `test_paddleocr_baseline.py` — raw OCR contract, coordinate-safe init.
- `test_perception_fusion.py` — provider-derived provenance separation and
  fallback behavior.
- `test_grounded_element.py` — GroundedElement schema, OB-001 regression, and
  PerceptionStackFreezeTests guarding the frozen artifact
  `test_data/ob001/grounded_elements.json` against drift.
- `test_vision_provider_artifact_isolation.py` — observation-first directories,
  provider/model/skill independence, v1/v2 coexistence, manifest/source hash
  binding, provider contamination guards, and explicit benchmark input paths.
- `test_vision_artifact_harness.py` — case-first output routing, AGY
  v1/v1.1/v2 coexistence, metadata/hash/manifest binding, overwrite rejection,
  and path traversal rejection.
- `test_agy_vision_bridge.py` — structured fake runner, multi-frame isolation,
  timeout/command/JSON/schema/hash/provenance/staleness/conflict failures,
  malformed geometry/confidence/uncertainty cases, live-model pinning,
  evidence-backed gate, Paddle failure and empty OCR, ObserverMode consumption,
  fused-only exposure, and absence of native vision or execution dependencies.

## History

- OB-001 Perception MVP: completed (raw perception, fusion, contract
  validation, no semantic leakage).
- GroundedElement Layer v0.1 (Phase 2): completed (`次へ` / `研修設定` grounded,
  textless Gemini regions preserved as UNKNOWN).
- Model-agnostic Computer Use Evaluation v0.1: implemented with Vision Agent
  and Decision Agent interfaces plus the OB-001 replay artifact.

## Current evaluation boundary

```text
Screenshot -> Vision Agent + OCR sensor -> Perception Fusion
           -> VisionObservation -> GroundedElement
           -> Grounded Decision Agent -> ActionCandidate
```

An `ActionCandidate` must reference an existing GroundedElement ID. Missing or
ambiguous evidence returns `UNKNOWN`; invalid IDs are rejected. Candidates are
not execution permission.

## Still deferred

- Autonomous gameplay execution.
- Executor and ActionBoundary authorization changes.
- Runner and live ZCode behavior changes.
- Strategy and game-progress inference in the perception layer.
