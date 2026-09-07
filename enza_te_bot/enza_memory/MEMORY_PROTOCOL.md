# enza_memory Update Protocol (MANDATORY)

Every test / benchmark / live interaction session MUST end with a memory update.
A session that produced game interactions or observations but no memory update is INCOMPLETE.

The required artifact contracts are defined in `../MEMORY_SCHEMA.md`. Existing
memory files that predate that schema remain candidate evidence; their presence
or JSON validity does not make them schema-compliant, ground truth, or
executable policy.

## Scope

Applies to any ZCode (or other agent) session that:

- observes the enza environment (any screenshot / OBS artifact), or
- executes any action in the game (even one click), or
- produces an offline benchmark result (proposal, gate, replay).

Pure code-editing sessions with no environment contact are exempt.

## Required updates per session

1. **Observations**
   - Copy each new `ai_decisions/observations/OBS_<id>.json` into `enza_memory/observations/`
     with sequential alias `OBS###.json` (next free number).
   - Screenshot stays in `ai_decisions/observations/screenshots/`; reference by path.

2. **Trajectory**
   - Same mission continuation: append steps to the existing trajectory file.
   - New mission/phase: create `enza_memory/trajectories/<trajectory_id>.json`
     following the Trajectory contract in `../MEMORY_SCHEMA.md`.
   - A legacy trajectory may be referenced for comparison, but its unsupported
     claims must not be copied into a new artifact as facts.

3. **Failures**
   - Any unexpected state, mis-click, error code, or UNKNOWN outcome →
     new file in `enza_memory/failures/` (see `canvas_misclick_001.json` for format).
   - Never downgrade a failure to "recovered, no record". Recovery is part of the record.

4. **Policies**
   - If a failure or anomaly yields a new reusable constraint, add it to
     `enza_memory/policies/learned_constraints.json` (E#/C#/V# numbering, with evidence).
   - New constraints remain non-executable candidates until independently
     reviewed. One failure does not establish a universal rule.

5. **Index**
   - Update `enza_memory/memory_index.json`: session entry, files touched,
     interaction count, verification coverage, gate outcomes.

## Honesty rules (inherited from Phase 1 rules)

- `provenance: session_observed` only for first-hand evidence (screenshot/URL/tool read in that session).
- `provenance: user_reported` for anything from planner summaries or other sessions; confidence ≤ 0.5.
- Every material claim also records `FACT`, `INFERENCE`, `PROVISIONAL`, or
  `UNKNOWN` separately from provenance.
- `session_observed` is not synonymous with ground truth, and `FACT` is not
  synonymous with confirmed project knowledge.
- Evidence references should include stable identities, timestamps, sources,
  and integrity digests when available.
- UNKNOWN stays UNKNOWN. No visual similarity → confirmed state. No silent repairs.

## Session close checklist

- [ ] All new JSON artifacts parse (`python3 -m json.tool`)
- [ ] Trajectory steps have provenance + verification result
- [ ] Failures: every anomaly has a failure file
- [ ] memory_index.json updated with this session
- [ ] Report paths + validation result in the final answer

## Purpose

These records are candidate evidence for audit, failure analysis, and bounded
offline benchmark comparison. They are not automatically ground-truth training
data and do not authorize executable policy. Screenshots, tool records, and
other primary evidence remain necessary to audit the memory claims that refer
to them.
