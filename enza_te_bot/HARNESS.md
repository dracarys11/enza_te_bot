# enza Environment Agent Harness Specification

## Scope

This document defines how an Environment Agent session records evidence,
requests authorization, verifies effects, and updates memory. It does not grant
live execution authority or define gameplay strategy.

The harness preserves the repository invariant that evidence, inference,
permission, execution, verification, and completion are separate concerns.
Current live Environment Agent execution is blocked until a mandatory,
single-use permission boundary is implemented and audited.

## Session roles

- The observation collector captures environment evidence and creates an
  observation artifact. It does not choose an objective.
- The evidence classifier records `FACT`, `INFERENCE`, `PROVISIONAL`, and
  `UNKNOWN` without automatic promotion.
- The intent producer describes one already-authorized bounded action. It does
  not execute it.
- ActionGate evaluates evidence, freshness, target ambiguity, confidence, and
  scope. It does not click or declare success.
- The environment provider may execute only an exact intent carrying a valid,
  unexpired, single-use permission.
- The verifier obtains independent post-action evidence. It does not commit
  completion.
- The canonical result boundary maps verified evidence to the permitted result
  vocabulary. `UNKNOWN` and `FAILED` never become success.
- The memory curator records the session without turning evidence into policy or
  training truth.

## Session lifecycle

```text
START
  ↓
Read AGENTS.md
  ↓
Read enza_memory/memory_index.json
  ↓
Read current milestone and applicable governance contracts
  ↓
Observe environment
  ↓
Generate OBS artifact
  ↓
Classify evidence and preserve unknowns
  ↓
Perform only an explicitly authorized action, or record NO_ACTION
  ↓
Generate independent verification
  ↓
Update trajectory
  ↓
Update failures and candidate policies if needed
  ↓
Update memory index
  ↓
Validate artifacts and END
```

An observation-only session follows the same lifecycle but records `NO_ACTION`
and does not create execution permission or execution records.

## Start requirements

Before environment contact, the agent must:

1. Read `AGENTS.md`.
2. Read `CURRENT_MILESTONE.md` and the applicable files under
   `.agent-harness/`.
3. Read `enza_memory/memory_index.json` and
   `enza_memory/MEMORY_PROTOCOL.md`.
4. Read the relevant contracts under `ai_decisions/`.
5. Declare whether the session is observation-only, offline replay, or an
   explicitly authorized bounded live session.
6. Treat missing authority or missing evidence as a stop condition.

No historical trajectory, screenshot, candidate constraint, or prior successful
action supplies live authority.

## Required artifacts

Every session with environment contact requires:

- At least one versioned Observation artifact.
- Evidence references containing stable identities, timestamps, sources, and
  integrity digests when available.
- A trajectory step for every observation and action decision, including
  `NO_ACTION` decisions.
- Provenance classification for every material claim:
  `session_observed`, `user_reported`, or `inference`.
- Evidence classification for every material claim:
  `FACT`, `INFERENCE`, `PROVISIONAL`, or `UNKNOWN`.
- Independent post-action verification for every performed action.
- A Failure artifact for every anomaly, unexpected state, mis-click, error, or
  unresolved result.
- A memory-index update linking the session and all artifacts.

An action-capable session additionally requires:

- One immutable ActionIntent.
- One recorded ActionGate decision.
- One permission bound to the exact observation, intent, target, scope, and
  provider session.
- One execution record showing permission consumption.
- Explicit proof that no retry or additional action occurred unless separately
  authorized.

These action-capable requirements describe the target contract. They do not
indicate that the current repository is ready for live use.

## Authorization boundary

The only valid action path is:

```text
Observation
→ ActionIntent
→ ActionGate
→ single-use ExecutionPermission
→ EnvironmentProvider
→ independent Verification
→ Canonical Result
```

The session must stop without action when:

- Provenance is missing, invalid, stale, replayed, or from another session.
- Observation or target evidence is unknown, contradictory, or below its
  reviewed confidence threshold.
- The target is ambiguous.
- A canvas target is only `SCREENSHOT` / `VISIBLE_ONLY` and lacks separate,
  reviewed target calibration.
- Scope or intent differs from the authorized values.
- Permission is missing, expired, altered, consumed, or revoked.
- Live execution was not explicitly authorized.

Permission authorizes one bounded actuation only. It does not authorize retry,
strategy, objective selection, completion, persistent-state commit, or another
planner invocation.

## Verification boundary

Verification must use a fresh post-action observation acquired independently of
the execution response. It records what changed, what did not change, and what
remains unknown.

A verification record must not:

- Trust an expected state merely because the intent named it.
- Treat an unchanged URL as proof of unchanged UI state.
- Treat visual similarity as authoritative game state.
- Convert `UNKNOWN` or `FAILED` into success.
- Commit room, planner, or persistent completion flags.

## End-of-session update

Before ending any session covered by the memory protocol, the agent must:

1. Store or alias each new Observation artifact under
   `enza_memory/observations/`.
2. Append or create the relevant trajectory with observation, intent, gate,
   permission, execution, and verification references.
3. Create a Failure artifact for every anomaly, even when recovery appeared
   successful.
4. Add reusable lessons only as candidate constraints with cited evidence and
   explicit uncertainty.
5. Update `enza_memory/memory_index.json` with the session identity, artifact
   paths, interaction count, verification coverage, gate outcomes, anomalies,
   and terminal observation.
6. Validate every changed JSON artifact.
7. Report files changed, validation results, interaction count, and whether live
   execution occurred.

A session that contacts the environment but omits the required memory update is
incomplete.

## Promotion rules

- Memory is candidate evidence by default.
- `session_observed` does not mean ground truth.
- `FACT` does not mean confirmed project knowledge.
- `user_reported` evidence remains distinct from first-hand evidence.
- An inference cannot be promoted by raising its confidence value.
- A policy constraint requires independent review before executable use.
- Conflicts are retained; they are not averaged away.
- Unknowns remain unknown until new, cited evidence resolves them.
