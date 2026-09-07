# Architecture Overview v0.1

```text
Human Goal
↓
Planner
↓
Executor
↓
Risk Gate
↓
Observation Layer
↓
Evidence/Reconciliation
```

## Authority boundaries

### Human Goal

The goal defines the requested outcome and authorizes the operating scope. It is not itself a click instruction.

### Planner

The planner converts fresh state and the human goal into an explicit objective. Weekly objective authority belongs here. A passing local risk gate does not, by itself, justify selecting an objective.

### Executor

The executor maps an explicit planner objective to a supported action path. It cannot invent a VOCAL objective, substitute a different weekly objective, or treat visual presence as execution permission.

### Risk Gate

The risk gate authorizes or blocks an action using fresh risk evidence. VOCAL requires fresh trouble-rate evidence; unknown or unsafe evidence fails closed.

### Observation Layer

The observation layer supplies fresh state and control evidence. Screenshot timeout, capture error, or stale frame is an observation failure. It is not evidence that the game action failed.

### Evidence/Reconciliation

After dispatch, the system must distinguish `ACTION_SENT` from observed outcome. A pending action cannot be retried until fresh stable evidence reconciles the transaction. Result progress is committed only from explicit result evidence or a fresh stable state; recovery reconciles state and does not blindly retry.

## Validated reliability properties

- Planner authority is explicit.
- Executor cannot invent objectives.
- Observation timeout is isolated from action failure.
- Pending actions require fresh reconciliation before retry.
- Evidence-grounded results are committed at a durable boundary.
