# ENZA Vision Benchmark v0.1

Offline observation-only benchmark for the RTX5080 WSL node. The runner is
`tools/run_vlm_benchmark.py`; use `--model-path` to specify an existing local
model path. No model is downloaded, moved, or loaded unless an explicit model
path is supplied. The default run uses UNKNOWN records and does not infer.

Cases:

- VLB001: state recognition
- VLB002: visible control observation; visible is not clickable and clickable
  is not authorized
- VLB003: evidence retrieval from existing local image evidence

Output records contain only image, sha256, observation, confidence, and
vlm_status. Authority, planner, execution, permission, and next-action fields
are forbidden. The runner never connects to ENZA runtime or operates the game.

## Long-running inference reliability (runner v0.4)

Predictions are appended as individual JSONL records, flushed and synced after
each image. The existing prediction schema is unchanged. `run_progress.json`
in the output directory is atomically updated at startup and after every
record, including failures. `completed` counts non-FAILED records, `failed`
counts FAILED records, and `remaining = total - completed - failed`.
`started_at` and `updated_at` are UTC timestamps; `started_at` is preserved
across resume invocations. Scores and the leaderboard are generated
when the invocation finishes; the JSONL file is the resume checkpoint.

Use an explicit project root and a new output directory for each run:

```sh
python tools/run_vlm_benchmark.py \
  --input /path/to/inputs_full.jsonl \
  --project-root /path/to/project \
  --model-path /path/to/local/Qwen2.5-VL-7B-Instruct \
  --output /path/to/run-output \
  --max-new-tokens 128 --limit 100
```

Repeat with `--resume` to process the remaining images. `--limit` caps new
attempts per invocation; omitting it processes all remaining images.
`--max-new-tokens` defaults to 128. Model loading, prompting, placement, and
response normalization otherwise retain their existing behavior.

Recommended runtime profiles:

- Fast iteration: Qwen2.5-VL-3B with `--max-new-tokens 128`.
- Quality baseline: Qwen2.5-VL-7B with `--max-new-tokens 128`; confirm that
  available VRAM avoids unacceptable CPU offload before a long run.

Resume identifies records by their existing `image` field and verifies their
SHA-256 against the current artifact. All saved terminal statuses, including
FAILED and UNKNOWN, are skipped. Use a separate output for intentional retries
or changed model/settings. Foreign IDs, duplicate IDs, changed artifacts, and
malformed checkpoint lines are rejected without rewriting the checkpoint;
an interrupted partial JSON line requires explicit operator repair. Existing
output requires `--resume`, preventing accidental replacement. Use one writer
per output directory; a JSONL output path shares its parent's progress file.

Preflight validates the entire manifest and every image before model loading,
even when `--limit` is set. It also checks the local model directory when
supplied and probes output-directory writability. Relative image paths resolve
against `--project-root`, independent of the current working directory. Any
preflight infrastructure failure exits before inference with
`ARTIFACT_VALIDATION_FAILED`. Validation and regression tests use local fixtures;
real RTX5080 inference remains a separate execution check.

## Benchmark Artifact Bundle Contract

A reproducible benchmark run includes cases, gold, and the input manifest,
as well as all referenced artifacts, artifact metadata, and environment
information. Shipping a manifest alone does not establish that its image
references are available on another machine.

Before inference, the harness should validate:

1. Manifest completeness: the manifest exists, parses, and contains the
   expected number of valid entries for the declared run.
2. Artifact existence: every referenced image resolves to an available file
   on the consumer environment.
3. Deterministic path resolution: use an explicit project root and declared
   artifact root, independent of the current working directory. The same
   reference must resolve to the same artifact within the declared bundle.
4. Optional checksum validation: compare available artifact bytes with the
   declared checksum and report mismatches when this validation is enabled.

Missing artifacts must fail preflight before model execution. Report missing
paths and counts as infrastructure failures; they do not measure model or
adapter capability. Validate the full manifest on the consumer even when a
single-image smoke test has passed.

The Mac producer and RTX5080 WSL consumer must share the same bundle contract;
machine-specific absolute roots may differ, but relative references and
artifact identities must remain consistent. Record producer/consumer
environment information and the model identifier with the run.

See the [full manifest artifact distribution failure](../../../failures/failure_vlm_artifact_distribution.md)
for the incident in which 883 entries had zero resolvable image references.

## Future Harness Improvements

These are documentation-only requirements; no export or preflight command is
implemented by this change.

- Portable benchmark bundle export containing the referenced artifacts and
  the metadata required to validate them on another machine.
- An artifact manifest declaring `artifact_id`, `relative_path`, `checksum`,
  and `artifact_root`. The consumer explicitly binds the declared root to its
  local bundle location.
- A proposed `benchmark doctor` preflight command reporting manifest count,
  artifact count, missing files, and invalid references, with deterministic
  resolution and optional checksum checks. An incomplete bundle must produce
  a failed preflight result before model execution.
