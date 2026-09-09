# ENZA Local Qwen Runtime Guide

## Purpose

Qwen3.8-27B is used as an independent adversarial reviewer for ENZA
benchmark infrastructure. It is not a planner, executor, or benchmark
participant. Its job is to attack benchmark design and identify risks that
could make a release or result invalid.

## Environment

The target runtime is:

- RTX5080 WSL
- CUDA-enabled GPU
- llama.cpp server
- OpenAI-compatible API on `localhost:8080`

This reviewer runs offline against the local server. It does not connect to
the game runtime or authorize benchmark actions.

## Model Location

Expected model layout:

```text
~/models/Qwen3.8-27B-GGUF/
```

Example model file:

```text
Qwen3.8-27B-UD-IQ3_S.gguf
```

Confirm the actual filename before starting the server. Model files are not
downloaded or moved by the ENZA review workflow.

## llama.cpp Location

The expected llama.cpp server binary is:

```text
~/projects/llama.cpp/build/bin/llama-server
```

`llama-server` may not be in `PATH`. Check both the command lookup and the
filesystem when diagnosing a setup:

```bash
which llama-server
find ~ -name "llama-server"
```

## Startup Command

Run this from the RTX5080 WSL environment, after verifying the model path:

```bash
~/projects/llama.cpp/build/bin/llama-server \
  -m ~/models/Qwen3.8-27B-GGUF/Qwen3.8-27B-UD-IQ3_S.gguf \
  --ctx-size 32768 \
  --n-gpu-layers 999 \
  --port 8080
```

Parameters:

- `--ctx-size 32768` sets the maximum request context window. A smaller
  value can reduce memory pressure.
- `--n-gpu-layers 999` asks llama.cpp to place as many layers as possible on
  the GPU. The effective placement still depends on available VRAM.
- `--port 8080` exposes the OpenAI-compatible HTTP server on local port 8080.

If the RTX5080 cannot fit the selected model and context, llama.cpp may
offload layers to CPU or fail with an out-of-memory error.

## Health Check

With the server running, execute:

```bash
curl http://localhost:8080/v1/models
```

Expected behavior is an HTTP success response containing a JSON model list,
normally with an object such as `"object": "list"` and at least one model
entry. An unavailable connection means the server is not listening at the
configured endpoint yet.

## Running ENZA Review

From the repository root, run:

```bash
python3 tools/run_local_review.py
```

The review reads the frozen benchmark context and writes:

```text
enza_memory/benchmark/reviews/qwen_v0.4_attack_review.md
```

The review tool expects the local llama.cpp server to be healthy before it is
started. On the RTX5080 checkout, use the project virtual-environment Python
instead of `python3` if the system interpreter does not contain the review
tool dependencies.

## Remote synchronization

The RTX5080 WSL runtime machine is accessed through Tailscale SSH. Do not
assume or use a local SSH alias such as `enza-wsl`; aliases depend on one
Mac's SSH configuration and do not identify the Tailscale node contract.

Discover the runtime node before synchronization. On the RTX5080 WSL host,
the operator can obtain its address and peer name with:

```bash
tailscale ip -4
tailscale status
```

On the Mac, run `tailscale status` and select the RTX5080 WSL node by its
Tailscale hostname or `100.x.x.x` address. Connect explicitly as the WSL
administrator:

```bash
ssh administrator@<tailscale-hostname-or-IP>
```

Before pulling, inspect the remote checkout. Do not pull over uncommitted
remote changes:

```bash
ssh administrator@<tailscale-hostname-or-IP> \
  "git -C ~/projects/enza_te_bot/enza_te_bot status --porcelain=v1"
```

If the result is empty, synchronize with a fast-forward-only pull and verify
the commit:

```bash
ssh administrator@<tailscale-hostname-or-IP> \
  "git -C ~/projects/enza_te_bot/enza_te_bot pull --ff-only origin main && \
   git -C ~/projects/enza_te_bot/enza_te_bot rev-parse HEAD"
```

The verified remote commit must equal the commit pushed to `origin/main`.
Report `REMOTE_SYNC_STATUS`, `REMOTE_HOST`, and `REMOTE_COMMIT`. If Tailscale
node discovery, SSH authentication, the clean-check check, pull, or commit
verification fails, stop without changing remote state and report the failed
stage.

```text
Code distribution:  MacBook -> GitHub -> RTX5080 WSL
Management path:    MacBook -> Tailscale SSH -> RTX5080 WSL
```

## Troubleshooting

### Reasoning tokens increase but answer tokens remain zero

This indicates that the model is generating `reasoning_content` without final
Markdown in `content`. The ENZA reviewer explicitly sends
`chat_template_kwargs.enable_thinking=false`; do not remove that setting or
write reasoning into the review as a fallback. Confirm the runtime checkout
contains the non-thinking-mode change and rerun the harness.

The full diagnosis and resolution are recorded in
`enza_memory/failures/failure_local_qwen_review_reasoning_budget.md`.

### `llama-server` command not found

Use the full binary path shown above, or add its containing directory to
`PATH` for the current shell. Re-run `which llama-server` to verify the
lookup.

### `No such file or directory`

`~` expands to `/home/administrator` in the RTX5080 WSL environment. It does
not mean `/home/administrator/projects`. The project checkout and the model
directory are separate paths; verify both explicitly.

### CUDA out of memory

Reduce `--ctx-size`, then restart the server. A smaller context lowers memory
use. Layer offloading or a smaller compatible quantization may also be
required, but do not change model files as part of a benchmark review run.

### Port occupied

Check which process owns port 8080:

```bash
lsof -i :8080
```

Stop or reconfigure the conflicting local service before starting the ENZA
server.

## Agent Instruction

Before running local Qwen review, agents must read this document.
