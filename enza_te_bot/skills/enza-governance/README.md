# enza-governance

`enza-governance` is the non-executable governance skill for enza_te_bot. It keeps architecture review, demo evidence, regression review, and knowledge compression separate from runtime implementation.

Before every workflow, load the relevant artifacts under `ai_decisions/` and preserve `CONFIRMED`, `CANDIDATE`, and `UNKNOWN` classifications.

## Workflow

Before implementation, use `prompts/pre_change_architecture_check.md` to check
HOME boundaries, responsibility ownership, and evidence dependencies.

Before answering an uncertain architecture or gameplay question, use
`prompts/unknown_guard.md`. It returns `UNKNOWN_DEPENDENCY` instead of filling
an evidence gap by inference.

Before starting a migration phase, use `prompts/migration_gate.md` to verify
predecessor contracts, regression verdicts, and candidate-knowledge hygiene.

1. After an architecture discussion, run the knowledge curator with `prompts/knowledge_curator.md`. Save the resulting snapshot under `ai_decisions/knowledge_snapshot/`.
2. After demo analysis, run the demo evidence extractor with `prompts/demo_evidence_extractor.md`. Save reports under `ai_decisions/audit_reports/demo_evidence/`.
3. Before and after major code changes, run the architecture auditor with `prompts/architecture_auditor.md`. Save reports under `ai_decisions/audit_reports/architecture/`.
4. After Codex implementation, run the regression reviewer with `prompts/regression_reviewer.md`. Save reports under `ai_decisions/audit_reports/regression/`.

Use the matching file under `templates/` for each output. AGY performs architecture, review, and governance work; Codex remains the implementation agent; the repository harness and `ai_decisions/` retain workflow memory.

## Guardrails

- Reviews are read-only unless a separate task explicitly authorizes a knowledge-artifact update.
- Do not modify runtime, planner, room, vision, or automation behavior.
- Do not promote candidate knowledge automatically.
- Do not use demo evidence to infer strategy.
- Do not run live automation as part of governance.

The three gates are structural/read-only prompts, not a workflow runtime. They
complement the existing architecture auditor, demo extractor, regression
reviewer, and knowledge curator.
