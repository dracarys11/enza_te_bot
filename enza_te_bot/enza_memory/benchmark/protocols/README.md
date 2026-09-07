# ENZA Benchmark Execution Protocol v0.1

This protocol evaluates multiple participants against an identical set of
offline ARB cases. It consumes responses that have already been captured; it
does not call models, open browsers, inspect a game, or import runtime code.

## Manifest

```json
{
  "protocol_version": 1,
  "run_id": "comparison_001",
  "participants": [
    {
      "participant_id": "codex_sol",
      "kind": "AGENT",
      "adapter": "openai",
      "responses": {
        "ARB001_planner_authority": "responses/codex/ARB001.json"
      }
    }
  ]
}
```

`kind` is one of `VLM`, `AGENT`, or `HUMAN`. `adapter` is one of `openai`,
`gemini`, `zcode`, `local_vlm`, or `canonical`. Every participant must provide
exactly one response for every selected case. Relative response paths resolve
from the protocol manifest directory.

## Run

```bash
python enza_memory/benchmark/protocols/benchmark_runner_v2.py \
  --manifest protocol.json
```

Results are written only after the entire manifest, common case set, adapters,
and response files validate. The default destination is
`benchmark_results/<run_id>/`.
