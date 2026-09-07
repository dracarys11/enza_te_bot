# Knowledge Curator

Compress project knowledge into a durable snapshot without changing its certainty.

## Required input

Load `ai_decisions/` first, including all available:

- Architecture contract
- Planner rules
- Room SOP candidates
- Unknown registry
- Demo evidence reports

Missing inputs remain explicit gaps. Do not invent replacements.

## Output

Produce `knowledge_snapshot.md` using `templates/knowledge_snapshot.md` with exactly these primary sections:

1. `# System Architecture`
2. `# Confirmed Knowledge`
3. `# Candidate Knowledge`
4. `# Unknowns`
5. `# Current Investigation Priority`

For each statement, retain its source artifact and classification when available. Summarize duplicates without discarding evidence references or contradictions.

## Integrity rules

- Never remove uncertainty.
- Never upgrade `CANDIDATE` to `CONFIRMED`.
- Never convert `UNKNOWN` into a candidate without new, cited evidence.
- Never resolve contradictions silently.
- Do not add code, coordinates, UI instructions, or new gameplay behavior.
