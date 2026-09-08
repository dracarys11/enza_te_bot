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
