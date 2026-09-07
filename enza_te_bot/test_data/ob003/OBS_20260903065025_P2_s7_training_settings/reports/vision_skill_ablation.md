# Training Settings Vision Skill Ablation

Case: `OBS_20260903065025_P2_s7_training_settings`

Integrity gate: **PASS**. Manifest, screenshot hash, artifact hashes, AGY schema, viewport binding, and provider/model/skill provenance were verified before comparison.

PaddleOCR is used only as a directional text reference/proxy. It is not ground truth. All three ablation variants use provider `AGY` and model `gemini-3.8-flash-medium`; only `skill_version` changes.

## Variant metrics

| Skill | Text regions | Exact vs Paddle | Normalized / text coverage proxy | Interactions | Grounding link coverage | Dangling links | Uncertainty count / viewport coverage | OOV bbox | Suspicious unsupported text extra | Latency ms | Timeout events |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| gemini_vision_v1 | 123 | 37 / 31.6% | 83 / 70.9% | 52 | 78.8% | 0 | 3 / 100.0% | 0 | 40 | not recorded | 0 |
| gemini_vision_v1_1 | 37 | 11 / 9.4% | 35 / 29.9% | 6 | 50.0% | 0 | 3 / 0.7% | 3 | 2 | not recorded | 1 |
| gemini_vision_v2 | 119 | 36 / 30.8% | 82 / 70.1% | 71 | 76.1% | 0 | 17 / 17.2% | 6 | 37 | not recorded | 1 |

## Pairwise skill overlap

The direction is the later skill as candidate against the earlier skill as reference. Existing comparison formulas are unchanged (interaction IoU threshold 0.5; Unicode NFKC plus whitespace removal).

| Transition | Normalized text agreement | Interaction overlap | Mean matched IoU | Grounding agreement | Unmatched candidate interactions |
|---|---:|---:|---:|---:|---:|
| v1_to_v1_1 | 32 / 26.0% | 3 / 5.8% | 0.843889 | 100.0% | 3 |
| v1_1_to_v2 | 31 / 83.8% | 3 / 50.0% | 0.781205 | 66.7% | 68 |
| v1_to_v2 | 115 / 93.5% | 9 / 17.3% | 0.618519 | 33.3% | 62 |

## Recorded timing evidence

- `gemini_vision_v1`: no timeout record found; successful total latency was not recorded.
- `gemini_vision_v1_1`: 12 min (gemini_v1_1_agy_timeout_001); continuation completed. Successful total latency was not recorded.
- `gemini_vision_v2`: 20 min (gemini_v2_agy_timeout_001); continuation completed. Successful total latency was not recorded.

## Evidence-bounded assessment

- v1 -> v1.1: **REGRESSION**. Paddle text coverage proxy 0.709402 -> 0.299145; interaction candidates 52 -> 6; out-of-viewport bboxes 0 -> 3.
- v1.1 -> v2: **RECOVERY_WITH_SIGNIFICANT_EXPANSION**. Paddle text coverage proxy 0.299145 -> 0.700855; interaction candidates 6 -> 71; unmatched candidate interactions 68; uncertainty records 3 -> 17.
- v2 vs v1: **NO_DEMONSTRATED_NET_GAIN_ON_THIS_CASE**. Paddle text coverage proxy 0.709402 -> 0.700855; normalized text agreement with v1 0.934959; interaction overlap with v1 0.173077; grounding agreement on matched interactions 0.333333; out-of-viewport bboxes 0 -> 6.
- Recommended default: **NO_PROMOTION**; retain `gemini_vision_v1` as the baseline. One-case evidence shows v1.1 regression and v2 expansion without demonstrated net gain; successful latency is also unrecorded and v2 required a recorded 20-minute timeout continuation.

## Interpretation limits

- This is one observation case and cannot establish general extraction quality.
- Unmatched candidate text is reported as a suspicious unsupported extra, not classified as a false positive.
- No successful end-to-end latency values exist in the artifacts or provenance records.
