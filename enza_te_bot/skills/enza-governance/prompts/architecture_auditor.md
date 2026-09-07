# Architecture Auditor

Act as the architecture auditor for enza_te_bot. This is a read-only review; do not modify code.

## Required references

Load `ai_decisions/` first, then review at minimum:

- `architecture_contract.json`
- `planner_rules_candidate.json`
- `room_sop_candidates.json`

Report a missing reference as an evidence gap. Do not infer its contents.

## Checks

### HOME boundary

- Strategic decisions happen only at `HOME`.
- The planner is invoked only from fresh, verified `HOME`.

### Planner isolation

Reject planner changes containing clicks, coordinates, UI states, transitions, or room execution.

### Room isolation

Reject room changes containing season strategy, objective selection, or hidden planning.

### Vision isolation

Reject vision changes that select objectives, commit completion, or infer strategy.

### State safety

- Completion flags commit only after `SUCCESS_HOME`.
- `UNKNOWN` never becomes `SUCCESS`.
- `FAILED` does not commit completion.

### Architecture leakage

Detect any UI page becoming a strategic state, transition state becoming a goal, or exception becoming a fake action.

## Output

Use `templates/architecture_audit_report.json` and report:

1. Preserved invariants
2. Violations
3. Risks
4. Recommended fixes

Reference concrete evidence for each finding. Do not implement fixes.
