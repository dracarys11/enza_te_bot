# Bounded live debugging

`LIVE_DEBUG` is a governed repair loop, not unrestricted autonomous control:

approved live command → inspect evidence → classify outcome → minimal scoped repair → focused offline tests → retry the same command.

## Authorization contract

Before any live run, record all of:

- the exact approved CLI command;
- risk level;
- allowed click scope;
- terminal condition;
- protected states;
- maximum repair/live-run attempts (default: 3);
- irreversible effects declaration.

Only the exact approved command may be retried. Run one live command at a time. Do not chain into the next business milestone.

## Risk levels

- `LEVEL_0_OBSERVE_ONLY`: no input injection. Autonomous live debugging is allowed when the command is explicitly approved.
- `LEVEL_1_BOUNDED_SAFE_UI`: a known bounded transaction with constrained click capability, protected-state precedence, timeout, maximum-click, and no-effect bounds. Explicit command approval is required.
- `LEVEL_2_BUSINESS_ACTION`: changes business progress or chooses a business branch. Explicit approval is required for that exact command and transaction.
- `LEVEL_3_COST_OR_IRREVERSIBLE`: consumes resources, purchases, retries with consumables, or performs destructive/irreversible actions. Never escalate automatically; require explicit human approval.

Risk permission never overrides project safety invariants or the approved task scope.

## Outcome classification

Classify each run as exactly one of:

- `OBSERVATION_FAILURE`
- `ENTRY_GUARD_FAILURE`
- `DETECTOR_FAILURE`
- `ACTION_EFFECT_FAILURE`
- `KNOWN_PROTECTED_STATE`
- `UNKNOWN_STATE`
- `POLICY_REQUIRED`
- `ENVIRONMENT_NETWORK_FAILURE`
- `SUCCESS`

For the first four failure classes, a minimal evidence-backed repair may be made, followed by focused offline tests before another live attempt. For protected, unknown, or policy-required outcomes, stop unless an existing explicitly approved handler applies. For environment/network failure, do not rewrite business logic; retry only when safe and within the bound. On success, stop.

## Stop conditions

Stop immediately when:

- the approved terminal condition is reached;
- a protected state, unsupported `UNKNOWN`, or new policy decision appears;
- the next action would exceed the approved command, click scope, transaction, or risk authorization;
- an irreversible effect lacks explicit approval;
- FAILSAFE, window validation, or another safety invariant blocks execution;
- the attempt bound is exhausted.

After three unsuccessful attempts, emit an exception report containing stdout, classification, last state, trace and evidence paths, attempted changes, and remaining hypothesis.

## Repair discipline

- Preserve the distinction between action sent, effect verified, and committed.
- Do not weaken global `UNKNOWN` fail-closed behavior.
- Do not broaden click regions or bypass protected states to make a retry pass.
- Do not invent business policy or cross into a different transaction.
- Keep each repair minimal and within the current milestone.
- Run the full offline suite when the repair's blast radius warrants it; focused tests are mandatory before every retry.

