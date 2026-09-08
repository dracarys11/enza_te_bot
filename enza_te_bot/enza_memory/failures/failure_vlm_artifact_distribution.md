# Failure Summary

Title: VLM Full Manifest Artifact Distribution Failure

During ENZA VLM Benchmark v0.1, the full manifest contained 883 entries and
the consumer reported `FAILED: 883`. The image artifacts referenced by that
manifest had not been distributed to the inference environment. Image loading
failed before inference; these statuses do not measure VLM capability.

# Failure ID

FAIL-20260908-VLM-ARTIFACT-DISTRIBUTION-001

# Category

Category: Benchmark Infrastructure Reliability

Dimension: Artifact Completeness / Cross Environment Reproducibility

# Environment

- Producer: Mac development environment.
- Consumer: RTX5080 WSL inference environment.
- Model: Qwen2.5-VL-7B-Instruct.
- Input manifest: `enza_memory/benchmark/vlm_runs/v0.1/inputs_full.jsonl`.
- Manifest entries: 883.

# Symptoms

- The model loaded successfully and CUDA was available.
- The Qwen adapter passed a single-image smoke test.
- The full benchmark returned `FAILED: 883`.
- `Image.open()` raised `FileNotFoundError` before image inference.

Example missing artifact:

```text
enza_memory/migration/python_click_migration/recovered_frames/dialogue/rf_dl_afsoushi_rest.png
```

# Detection

The operator-reported remote validation established:

| Check | Count |
|---|---:|
| Full manifest entries | 883 |
| Available benchmark images | 52 |
| Resolvable images from the full manifest | 0 |

Timeline (reported sequence; individual timestamps were not supplied):

1. The producer prepared the full 883-entry manifest.
2. The consumer loaded the model, confirmed CUDA availability, and passed
   the adapter's single-image smoke test.
3. The full run returned 883 failures during image loading.
4. Remote artifact validation found 52 available benchmark images but zero
   resolvable references from the full manifest.
5. The incident was classified as artifact distribution failure.

This record documents the supplied execution findings; recording it did not
repeat inference or independently inspect the remote filesystem.

# Root Cause

The manifest referenced image artifacts that were absent from the consumer.
Distributing the manifest did not distribute its referenced evidence corpus.
The available 52 images did not satisfy any of the full manifest's 883
references under the reported validation.

The established cause is incomplete artifact distribution, rather than a
working-directory-only diagnosis. Explicit root resolution is still a
required reproducibility check, but cannot supply missing image bytes.

Previous tests missed this because the single-image smoke test exercised one
available image and the model/adapter path. It did not establish full-manifest
artifact completeness on the consumer before the full run.

This is not evidence of a model, GPU, adapter, or VLM reasoning failure:
model loading and the smoke test succeeded, while the full run failed at
`Image.open()` before inference. Smoke success alone does not establish
full-dataset inference quality.

# Impact

All 883 full-manifest entries failed before inference. The attempted run
cannot support a VLM capability ranking or reasoning-quality conclusion.
It demonstrates a benchmark infrastructure and cross-environment
reproducibility failure. Existing result artifacts remain the raw record of
the attempt and are not rewritten by this documentation change.

# Resolution

The failure is recorded and the required bundle/preflight contract is
documented in the [vision benchmark README](../benchmark/vlm_runs/v0.1/README.md).
Artifact distribution and a successful full rerun remain unverified.

Operational recovery requires a complete, authorized artifact bundle on the
consumer, deterministic root resolution, and successful preflight validation
before another model execution. This task performs no image distribution,
code changes, or rerun.

# Prevention

- Treat referenced image bytes, artifact metadata, and environment information
  as benchmark inputs alongside cases, gold, and the manifest.
- Declare the project/artifact root explicitly; do not assume the current
  working directory identifies it.
- Validate every manifest reference on the consumer before model execution;
  stop on missing artifacts and report their paths/counts.
- Record manifest completeness, artifact existence, deterministic resolution,
  and optional checksum validation separately from model evaluation results.
- Validate a portable bundle on the target environment; a single-image smoke
  test does not substitute for full-manifest preflight.
- Future work: bundle export, an artifact manifest with `artifact_id`,
  `relative_path`, `checksum`, and `artifact_root`, and a `benchmark doctor`
  preflight command. These are requirements only, not implemented here.
