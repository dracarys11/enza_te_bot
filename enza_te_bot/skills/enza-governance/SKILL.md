---
name: enza-governance
description: Maintain architectural consistency and knowledge quality for enza_te_bot through architecture audits, demo execution-evidence extraction, regression reviews, and knowledge curation. Use for governance and review work, never runtime implementation.
---

# Enza Governance

Maintain the HOME-centric architecture contract and durable, non-executable project knowledge.

## Mandatory preparation

Before any review:

1. Locate the enza_te_bot project root.
2. Enumerate and read the existing artifacts under `ai_decisions/` that are relevant to the task.
3. Treat missing artifacts as missing information; do not reconstruct or invent them.
4. Preserve the explicit `CONFIRMED`, `CANDIDATE`, and `UNKNOWN` separation.

Candidate knowledge must never be promoted automatically. Governance output must not modify runtime, planner, room, vision, or automation behavior.

## Select one responsibility

- Architecture review: follow `prompts/architecture_auditor.md` and use `templates/architecture_audit_report.json`.
- Demo evidence extraction: follow `prompts/demo_evidence_extractor.md` and use `templates/demo_evidence_report.json`.
- Regression review: follow `prompts/regression_reviewer.md` and use `templates/regression_report.json`.
- Knowledge compression: follow `prompts/knowledge_curator.md` and use `templates/knowledge_snapshot.md`.

## Required gates

- Before implementation, run `prompts/pre_change_architecture_check.md`.
- Before answering uncertain architecture or gameplay questions, run
  `prompts/unknown_guard.md`.
- Before beginning a migration phase, run `prompts/migration_gate.md`.

These are read-only governance checks. A gate result does not authorize runtime
changes when its required evidence is missing.

Do not combine responsibilities unless the invoking task explicitly requests more than one.

## Core invariant

The only strategic decision point is fresh, verified `HOME`:

`HOME -> Planner -> exactly one Room -> verified HOME -> commit`

The planner chooses only `VOCAL`, `REST`, `SKILL`, or `AUDITION`. Rooms execute objectives but do not choose strategy. Vision reports observations but does not select objectives or commit completion. `UNKNOWN` and `FAILED` never become success.

## Output discipline

- Record evidence and artifact references for every conclusion.
- Keep uncertainty visible and link unresolved claims to the unknown registry when possible.
- Never add coordinates, click instructions, executable logic, or inferred gameplay strategy to governance artifacts.
- Write reports only to the requested governance location under `ai_decisions/`.
- Make no code changes while acting in an auditor, extractor, reviewer, or curator role.
