# ENZA Agent Reliability Benchmark v0.1

Offline-only evaluation corpus for comparing AI agents on recorded Enza
reliability failures. Cases reference durable evidence in place; screenshots,
failure records, reconciliation reports, and benchmark cases are never copied
or regenerated.

## Scope

The benchmark evaluates evidence interpretation and fail-closed reasoning. It
does not authorize live observation, clicks, execution, planner changes,
business-policy changes, or game control. A submitted answer is graded against
the case's invariants and rules, not against whether it proposes executable
code.

## Case contract

Every case contains:

- `case_id`
- `objective`
- `input_artifacts` — repository-relative paths to existing durable evidence
- `task_prompt`
- `expected_invariants`
- `grading_rules`

`input_artifacts` are evidence references only. The four original benchmark
cases under `/benchmark_cases` remain the source corpus; the ARB cases provide
an agent-comparison contract around them.

## Evaluator v0.1

The local `evaluator/` package provides a deterministic runner, scorer, and
Markdown report generator. It accepts a previously recorded
`agent_response.json`; it never calls a model and has no runtime dependency.
The response contract is in `schemas/response.schema.json`.

Each ARB case is available as `cases/<case>/case.json`, with `normal/` and
`adversarial/` evidence slots. The case inputs remain repository-relative
references to the existing durable corpus; no screenshots or runtime data are
copied or regenerated.

## Evaluation protocol

1. Load one ARB case and only its listed artifacts.
2. Give the `task_prompt` to the agent.
3. Record the response without allowing tool calls or environment contact.
4. Grade each rule as `PASS`, `FAIL`, or `UNKNOWN`; do not infer missing facts.
5. Store aggregate results under `reports/` only after an offline review.

The evaluator must preserve distinctions between observation failure and action
failure, visual evidence and authority, pending state and committed state, and
fact versus inference.

## Agent adapter layer v0.1

`adapters/` converts already-captured OpenAI, Gemini, ZCode, and local-VLM
outputs into the seven-field `schemas/response.schema.json` contract. Adapters
only parse JSON and provider envelopes; they do not call models. Missing action
authority or malformed fields fail closed with `AdapterError` instead of being
inferred from prose.
