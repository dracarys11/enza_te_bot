# Evaluator

Evaluator implementation is intentionally not coupled to runtime, planner,
executor, policy, or game-control modules. v0.1 cases are evaluated by replaying
the prompt and checking the response against `expected_invariants` and
`grading_rules` in each case.

The evaluator is offline-only and must not open a browser, capture a screen,
dispatch a click, rebuild an index, or mutate evidence artifacts.
