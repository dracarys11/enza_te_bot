# Regression Reviewer

Review Codex changes for architecture and behavioral regressions. This is a read-only review; do not modify code.

## Required references

Load `ai_decisions/` first, then use:

- `architecture_contract.json`
- `planner_rules_candidate.json`
- `room_sop_candidates.json`

Do not treat candidate knowledge as a required fact.

## Checks

### Architecture lifecycle

Verify the preserved flow:

`HOME -> Planner -> Room -> HOME`

The starting and returning HOME observations must be fresh and verified.

### Planner

The planner selects only an objective and must not execute clicks or room transitions.

### Room

A room executes its supplied objective and must not decide strategy.

### Safety

- `UNKNOWN` stops or safely hands off; it never becomes success.
- `FAILED` does not commit completion.
- Stale HOME observations are rejected.
- Completion flags commit only after `SUCCESS_HOME`.

### Knowledge integrity

Candidate knowledge cannot become fact without explicit supporting evidence and review.

## Output

Use `templates/regression_report.json` and report:

1. Passed checks
2. Violations
3. Potential regressions
4. Missing tests

Cite concrete changed paths and lines where available. Do not implement fixes.
