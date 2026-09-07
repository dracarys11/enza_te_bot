# Pre-change Architecture Check

Perform a read-only architecture safety check before implementation. Do not
modify runtime code, planner rules, room logic, vision, configuration, or
automation behavior.

## Required preparation

Load the relevant `ai_decisions/` artifacts before forming a conclusion:

- `architecture_contract.json`
- `unknown_registry_candidate.json`
- relevant planner, room, and evidence artifacts

Treat missing artifacts as missing information. Preserve `CONFIRMED`,
`CANDIDATE`, `PROVISIONAL`, and `UNKNOWN` distinctions.

## Checks

### HOME boundary impact

Determine whether the requested change affects any of these invariants:

- `HOME` is the only strategic decision point.
- Planner invocation requires fresh, verified `HOME`.
- A room executes exactly one supplied objective.
- Completion commits require objective evidence and fresh verified `HOME`.

### Responsibility leakage

Flag any change that would give the planner:

- click logic or coordinates
- UI-state handling
- room execution or transition control

Flag any change that would give a room:

- strategy selection
- seasonal policy
- hidden planning

Flag any change that would give vision:

- action selection
- strategy inference
- completion commits

### Knowledge dependency

Identify every requested behavior that depends on an `UNKNOWN`, unresolved
evidence gap, or candidate-only claim. Do not silently promote candidate
knowledge.

## Decision

Return exactly one top-level decision:

- `CHANGE_SAFE`: the requested change respects the contract and has sufficient
  evidence, with a concise scope note.
- `ARCHITECTURE_REVIEW_REQUIRED`: cite the violated boundary or missing
  evidence, the affected artifact/claim, and the minimum review needed.

Include a short evidence ledger with artifact paths and classifications. This
check is a gate, not implementation approval.
