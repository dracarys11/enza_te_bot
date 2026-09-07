# Demo Evidence Extractor

Extract room-execution knowledge from existing human demos. This is not strategy learning and must not modify source data or code.

## Required preparation

Load `ai_decisions/` before examining the demo. Respect existing confirmed, candidate, and unknown classifications. Analyze screenshots only when the invoking task explicitly authorizes it.

## Extraction boundary

For one of `VOCAL`, `REST`, `SKILL`, or `AUDITION`, extract only:

- Entry: HOME verification and starting state
- Room entry
- Intermediate state categories
- Shared handlers: dialogue, continue, speed, and choice
- Result
- Return to fresh, verified HOME

Do not infer why the human chose the action, seasonal strategy, optimal policy, or hidden gameplay behavior.

## Classification

Classify every extracted claim as:

- `CONFIRMED`: directly supported by sufficient existing evidence
- `CANDIDATE`: plausible but not established
- `UNKNOWN`: unsupported or contradicted

Never promote a candidate merely because it appears in a prior candidate artifact.

## Output

Use `templates/demo_evidence_report.json`. Include:

```json
{
  "room": "VOCAL | REST | SKILL | AUDITION",
  "evidence": [],
  "confidence": 0.0,
  "missing_information": [],
  "required_followup_demo": []
}
```

Include evidence locations and keep strategy inference explicitly false.
