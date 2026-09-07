# Migration Gate

Perform a read-only gate review before starting a new architecture migration
phase. Do not modify runtime code or promote candidate knowledge.

## Required preparation

Review available:

- architecture audit reports
- regression reports
- `ai_decisions/architecture_contract.json`
- `ai_decisions/unknown_registry_candidate.json`
- relevant planner and room artifacts

Missing reports are evidence gaps, not implicit approvals.

## Required predecessor checks

### Phase 1A

Pass only when:

- a Room execution contract exists
- adapter boundaries are defined
- parity coverage exists for the migrated adapters

### Phase 1B-1

Pass only when:

- one canonical RoomResult path exists
- `UNKNOWN` cannot become `SUCCESS_HOME`
- `FAILED` cannot commit
- stale HOME is rejected
- offline result-boundary tests pass

### Phase 1B-2

Pass only when:

- REST migration has an explicit predecessor PASS
- REST parity tests exist and pass
- legacy behavior remains available until parity is demonstrated

## Rejection rules

Return `MIGRATION_BLOCKED` if any of the following applies:

- a HIGH-severity architecture or regression violation is open
- the latest regression verdict is not `PASS`
- required predecessor evidence is missing
- candidate or unknown knowledge is being treated as fact

Include the blocking phase, report/artifact path, finding, and the minimum
evidence or fix required.

Otherwise return `MIGRATION_READY` with the checked phase, report references,
test evidence, and explicit scope limits for the next phase.
