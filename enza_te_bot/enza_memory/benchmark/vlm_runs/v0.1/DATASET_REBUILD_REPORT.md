# ENZA VLM Benchmark v0.1 Dataset Rebuild Report

## Source and counts

- Original full dataset count: 883 records, as recorded by the existing VLM annotation and prediction reports.
- Recovered image count: 883 records.
- Source manifest: `enza_memory/evidence_metadata/vlm_annotations/observations.jsonl`.
- Cross-check manifest: `enza_memory/evidence_metadata/vlm_annotations/vlm_predictions.jsonl` (883 records).
- Existing `inputs.jsonl`: 3 records, a smoke-test subset containing `VLB001`, `VLB002`, and `VLB003`.

## Overwrite assessment

The previous `inputs.jsonl` was overwritten or replaced by the smoke-test subset: its only tracked introduction is the benchmark commit that added three lines, while the full 883-record source manifests and 883-record prediction outputs predate that subset. No prior tracked full `inputs.jsonl` was found in Git history. The smoke-test file is preserved unchanged; the complete manifest is restored as `inputs_full.jsonl`.

## Rebuild contract

Each recovered line contains the existing runner input fields `image` and
`sha256`, copied from the observation manifest. Images are not invented,
renamed, or deduplicated: duplicate content hashes remain separate image
references because the source manifest contains separate records.

## Validation

- JSONL schema: passed for 883/883 records.
- Image paths: 883/883 exist relative to the project root.
- SHA-256 values: 883/883 match the referenced image bytes.
- Source record count: 883.
- Recovered manifest count: 883.
- Model calls: none.
- Runtime/planner/executor/policy changes: none.
