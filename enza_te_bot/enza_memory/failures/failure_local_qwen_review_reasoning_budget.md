# Failure Summary

Title: Local Qwen Reviewer Reasoning Budget Exhaustion

The ENZA local adversarial reviewer reached the end of its chat-completion
budget while generating private reasoning and returned no final Markdown.
The llama.cpp server and Qwen3.8-27B model were healthy; the failure was caused
by the review harness allowing the model's default thinking mode for a task
whose persisted artifact requires only final answer content.

# Failure ID

FAIL-20260909-LOCAL-QWEN-REVIEW-BUDGET-001

# Category

Category: Local Model Harness Reliability

Dimension: Generation Mode / Completion Budget

# Environment

- Producer and controller: Mac development environment.
- Consumer: RTX5080 WSL inference environment.
- Serving layer: local llama.cpp OpenAI-compatible API.
- Model: Qwen3.8-27B GGUF.
- Harness: `tools/run_local_review.py`.
- Persisted output: `enza_memory/benchmark/reviews/qwen_v0.4_attack_review.md`.
- Network requirement: none for inference; the model endpoint is local to the
  runtime node.

# Symptoms

The initial real review run reported approximately:

```text
reasoning tokens: ~4056
answer tokens: 0
local reviewer returned empty Markdown
```

Increasing the completion budget to 8192 did not make the workflow reliable.
A later run still consumed the available generation in reasoning mode and
reported approximately:

```text
reasoning tokens: ~8309
answer tokens: 0
local reviewer returned empty Markdown
```

No review file was accepted because the harness correctly treats empty final
content as an error.

# Debug Timeline

1. The llama.cpp model endpoint was confirmed available and streaming worked.
2. Progress instrumentation showed generated chunks in
   `reasoning_content`, but zero tokens in final `content`.
3. The answer-extraction boundary was inspected. It intentionally ignored
   `reasoning_content` and wrote only `message.content` or streamed
   `delta.content`; therefore the missing file content was not a parser loss.
4. The original completion budget was identified as too small for Qwen's
   default reasoning behavior. The harness gained configurable `max_tokens`,
   initially defaulting to 8192, plus a prompt instruction requiring a final
   Markdown answer.
5. A real run showed that a larger budget and prompt instruction alone were
   insufficient: thinking could still consume the full generation allowance.
6. A manual llama.cpp API request with
   `chat_template_kwargs.enable_thinking=false` returned normal final content
   in `message.content`.
7. The harness was changed to send that template option, its default
   `max_tokens` was reduced to 4096, and progress was made consistent with the
   configured mode.
8. The resulting non-thinking review run completed and wrote the Markdown
   artifact successfully.

# Root Cause

Qwen thinking mode was enabled by the model's chat template unless explicitly
disabled. The completion budget covers all generated completion tokens,
including private reasoning. On this review prompt, the model spent the budget
on `reasoning_content` before emitting final `content`.

This was not:

- a model-load or CUDA failure;
- an SSE framing or streaming interruption;
- a timeout failure;
- loss of final content caused by the Markdown writer;
- a reason to persist private reasoning as the review result.

The client-side reasoning-token figure is an approximation based on generated
text, not authoritative tokenizer usage. It can differ from the server's token
accounting, so values such as `~8309` diagnose the generation pattern but do
not prove an exact server-side token count.

# Why Earlier Checks Missed It

- Health checks verified model availability, not completion behavior for a
  long adversarial review prompt.
- Streaming and SSE tests proved transport correctness but did not constrain
  the model's chat-template reasoning mode.
- Increasing `max_tokens` addressed the symptom temporarily, not the mode that
  consumed the budget.
- Prompt text asking for a final answer is advisory; it does not reliably
  override a model-specific chat-template setting.

# Impact

- Review inference consumed runtime without producing the required Markdown.
- The failed attempts could have been mistaken for model, GPU, transport, or
  parser failures without separate reasoning and answer metrics.
- No private reasoning was written, and no partial or empty review was treated
  as a valid benchmark review.

# Resolution

The chat-completion payload now includes:

```json
{
  "max_tokens": 4096,
  "chat_template_kwargs": {
    "enable_thinking": false
  },
  "stream": true
}
```

The CLI retains `--max-tokens` for explicit overrides, with a default of 4096.
The SSE parser and reasoning compatibility path remain in place for servers or
models that still return `reasoning_content`.

Output authority remains strict:

- `reasoning_content` contributes only to progress and speed metrics;
- `message.content` and streamed `delta.content` are the only Markdown sources;
- a reasoning-only or otherwise empty final answer fails clearly and does not
  create a review artifact;
- mixed reasoning/content responses persist only content.

Because thinking is disabled for this workflow, live generation progress uses
`phase: ANSWERING` and does not display a misleading `THINKING` phase.

# Validation

The regression suite verifies:

- the payload contains `chat_template_kwargs.enable_thinking=false`;
- the default completion budget is 4096 and remains configurable;
- a content-only stream writes Markdown;
- a reasoning-only stream fails with `local reviewer returned empty Markdown`;
- a mixed stream succeeds while excluding reasoning from the file;
- streaming, SSE parsing, progress metrics, timeout handling, and the existing
  output path continue to work.

The final operational validation was a successful real local Qwen review run
that produced final Markdown on the RTX5080 runtime.

# Prevention

- Treat model generation mode as an explicit harness parameter, not an
  undocumented server default.
- Test the exact production chat-template settings with the full review prompt,
  not only endpoint health or short prompts.
- Keep reasoning-token and answer-token metrics separate.
- Never use private reasoning as a fallback answer or write it into benchmark
  review artifacts.
- Fail closed when final content is empty.
- When changing model families or server templates, regression-test
  content-only, reasoning-only, and mixed streaming responses.
- Use larger token budgets only when the required final artifact needs them;
  do not use budget growth as the primary fix for uncontrolled thinking.

# Related Changes

- `09ee32e` — `ENZA_LOCAL_QWEN_GENERATION_BUDGET_FIX`
- `1d89e07` — `ENZA_LOCAL_QWEN_REVIEW_NON_THINKING_MODE`
