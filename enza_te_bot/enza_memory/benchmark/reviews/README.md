# ENZA Local Qwen Adversarial Review

This workflow uses a local llama.cpp OpenAI-compatible server to perform an
independent infrastructure review of benchmark design documents. It does not
call external APIs, operate the game, or modify benchmark cases, gold data,
evaluator logic, or runtime code.

Requirements:

- llama.cpp `llama-server` running locally;
- default endpoint: `http://localhost:8080/v1`;
- a locally loaded Qwen3.8-27B-GGUF model;
- the server model ID passed with `--model` when it differs from the default.

Run from the repository root:

```bash
python tools/run_local_review.py
```

Optional overrides:

```bash
python tools/run_local_review.py \
  --endpoint http://localhost:8080/v1 \
  --model Qwen3.8-27B-GGUF \
  --project-root /path/to/enza_te_bot
```

The review context is built from the frozen v0.3 release and review material,
the benchmark README, the VLM harness README, and the artifact distribution
failure report. The generated Markdown is written to:

```text
enza_memory/benchmark/reviews/qwen_v0.4_attack_review.md
```

The reviewer identity is `Qwen3.8-27B-GGUF` served by local llama.cpp. Tests
use a mocked OpenAI-compatible API and never require an actual model server.
