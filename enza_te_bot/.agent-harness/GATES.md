# Gates

- `SCOPE_GATE`: does the work advance the current milestone?
- `EVIDENCE_GATE`: is the problem demonstrated by logs, screenshots, tests, or user evidence?
- `MINIMALITY_GATE`: is there a simpler deterministic solution?
- `PRODUCTION_GATE`: is the approach validated enough for production?

If a gate fails, stop and report the failed gate.

Workflow gates:

- `SOP_GATE`: end-to-end human process is sufficiently understood.
- `DEMONSTRATION_GATE`: required real execution evidence exists.
- `MODEL_GATE`: facts, inferences, provisional claims, and unknowns are separated.
- `VERIFY_GATE`: a human reviewed critical transitions and rules.
- `AUTOMATION_GATE`: behavior is ready for deterministic replay.
- `EXCEPTION_PROMOTION_GATE`: an annotation was compiled and reviewed before activation.

Live-debug gate:

- `LIVE_DEBUG_GATE`: before a live repair loop, the exact approved CLI command, risk level, allowed click scope, terminal condition, protected states, attempt bound, and irreversible-effects declaration are recorded. A missing field fails the gate; live execution must not begin.

Perception bridge gate:

- `AGY_VISION_BRIDGE_GATE`: accepts digest-bound `GateEvidence` records, never
  caller-supplied booleans. PASS requires evidence for
  `MULTIFRAME_ISOLATION`, `FUSION_PROVIDER_PROVENANCE`,
  `NO_NATIVE_FALLBACK`, `NO_PADDLE_ONLY_FALLBACK`, `LIVE_MODEL_PINNED`,
  `ARTIFACT_HASH_BOUND`, `SCHEMA_FAIL_CLOSED`, and
  `NO_EXECUTION_DEPENDENCY`. Runner promotion additionally requires
  `REAL_AGY_RUNNER_CONTRACT`, `RUNNER_TIMEOUT_FAIL_CLOSED`,
  `RUNNER_CONVERSATION_ID_PRESERVED`, `RUNNER_ARTIFACT_STAGING_ONLY`, and
  `NO_PROVIDER_DOUBLE_CALL`. This gate validates offline perception plumbing
  only and does not authorize a real AGY command, decision, ActionBoundary
  request, or execution.

Runtime decision-boundary invariants:

- `PLANNER_DECLARES_REQUIRED_OBSERVATION_FIELDS`: policy declares the minimum
  fresh fields for the current decision; perception does not choose business
  fields.
- `DECISION_BOUNDARY_REQUIRES_FRESH_EVIDENCE`: threshold, mandatory-target, and
  season-transition branches require fresh branch evidence; cached values and
  memory hints are insufficient.
- `MINIMAL_OBSERVATION_IS_CONTEXT_DEPENDENT`: normal-week fields are a
  policy-branch optimization, not a global WING schema.

Audition control-state invariants:

- `CONTROL_STATE_MUST_BE_REOBSERVED_AFTER_RESUME`
- `TRANSIENT_OVERLAY_INVALIDATES_LOCAL_CONTROL_STATE`
- `RESULT_FLAG_COMMIT_REQUIRES_EXPLICIT_SUCCESS_EVIDENCE`
- `FAILED_ACTION_MUST_NOT_COMMIT_PROGRESS_FLAG`

Live runtime observation invariants:

- `INTERACTABILITY_MUST_BE_OBSERVED_SEPARATELY_FROM_CONTROL_VALUE`: a
  control's value (`ON`/`OFF`/`UNKNOWN`) and current interactability
  (`ENABLED`/`DISABLED`/`UNKNOWN`) are independent evidence fields; action
  authority requires both meaningful value and actionable interactability.
- `CONTROL_ACTION_REQUIRES_ACTIONABLE_PHASE`: visible control presence does
  not grant action authority for a **semantic control action** (for example
  Auto, Speed, submit, selection, purchase, or another state-changing
  control). A fresh observation must establish an actionable phase and an
  enabled control before such an action; otherwise remain fail-closed. This
  invariant does not prohibit every click during animation or transition.
- `POST_TRANSACTION_STATE_MUST_BE_RECONCILED_FROM_FRESH_STABLE_STATE`:
  pre-transaction, transient/unknown, expected, and fresh verified
  post-transaction state remain distinct; derived expectations must not be
  recorded as fresh evidence when a stable observation is required.

Promotion provenance for the live runtime observation invariants above:

- `source`: `LIVE_RUNTIME_EVIDENCE`
- `run`: `WINGRUN_20260905_01`
- scope: system-level safety/observation principle; not multi-domain or
  universal empirical validation.

Execution batching invariant:

- `BATCH_EXECUTION_MUST_RESPECT_MEASURED_TOOL_LATENCY`: size a multi-action
  execution batch using measured end-to-end latency for the actual tool path,
  not only explicit waits or the logical action count. If the estimated batch
  duration approaches the execution budget, split the batch before execution.
  Concrete tool timings, click limits, cell budgets, and provider-specific
  thresholds remain runtime/control-memory evidence and are not Harness rules.

Held system-level candidate:

- `CONTROL_ORDERING_DEPENDENCY_MUST_BE_RESPECTED`: `HOLD` pending evidence
  beyond the current WING audition control dependency. `SPEED_FIRST_THEN_AUTO`
  remains runtime/domain knowledge and is not a Harness invariant.
- `SAFE_TRANSIENT_ACTION_MAY_BE_ANTICIPATORY`: `HOLD` candidate. A
  `SAFE_TRANSIENT_ACCELERATION` (skip/dismiss/advance-only) may use learned
  anticipatory timing after transition identity and target safety are verified,
  with bounded timing and fresh post-action verification. Without timing
  evidence, use observe-first. Learning lifecycle: `OBSERVE` natural duration
  → bounded `PROBE` → repeated low-risk success before fast-path promotion.
  Concrete delays, coordinates, animation lengths, and WING-specific targets
  remain outside the Harness.
