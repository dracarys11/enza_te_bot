# Qwen2.5-VL Smoke Validation

## Model information

- Model: `Qwen2.5-VL-7B-Instruct`
- Adapter: ENZA local Qwen2.5-VL benchmark adapter
- Adapter commit: `688bc22`

## Hardware environment

- GPU: NVIDIA RTX 5080
- CUDA available: yes
- Transformers: `5.16.1`
- PyTorch: version not captured in the validated environment report
- Connection context: real RTX 5080 Tailscale smoke environment

## Smoke test input

- Images supplied: 1
- Execution mode: local model validation
- Model download: none
- Game execution: none

## Result

- `OBSERVED`: 1
- Status: `SMOKE_TEST_PASS`

The validated one-image summary is frozen in `qwen_smoke_test_result.jsonl`.
The environment record is frozen in `qwen_environment.json`.

## Known fixes validated

- Qwen multimodal message format
- Observation schema normalization

## Readiness status

The Qwen2.5-VL adapter is ready for the ENZA offline VLM benchmark smoke path.
This validation does not change or authorize runtime, planner, executor,
policy, benchmark-case, gold-dataset, or evaluator behavior.
