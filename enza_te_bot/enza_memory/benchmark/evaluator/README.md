# Evaluator

Evaluator implementation is intentionally not coupled to runtime, planner,
executor, policy, or game-control modules. v0.1 cases are evaluated by replaying
the prompt and checking the response against `expected_invariants` and
`grading_rules` in each case.

The evaluator is offline-only and must not open a browser, capture a screen,
dispatch a click, rebuild an index, or mutate evidence artifacts.

## Grading rule schema

The current case schema stores grading rules as strings. The evaluator accepts
the legacy v0.1/v0.2 forms `PASS:` and `FAIL:` and the v0.3 forms
`PASS only if` and `FAIL if`, with an optional colon after `if`. Matching is
case-insensitive and anchored at the beginning of the complete rule; unsupported
forms are ignored rather than guessed.

Use `--rule-audit` with `evaluator/runner.py` to include
`parsed_rules_count`, `ignored_rules_count`, and warnings for unsupported rule
syntax in the evaluation JSON. This audit metadata does not alter dimension or
total score fields.
