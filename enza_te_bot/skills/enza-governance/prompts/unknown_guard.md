# Unknown Guard

Perform a read-only knowledge-dependency check before answering an uncertain
architecture or gameplay question. Do not modify source, policy, configuration,
or evidence artifacts.

## Required preparation

Load `ai_decisions/unknown_registry_candidate.json` and any directly relevant
artifacts under `ai_decisions/`. Treat candidate knowledge as non-authoritative.

## Check

Determine whether the requested conclusion, recommendation, or implementation
advice depends on one or more entries classified as `UNKNOWN`, unresolved, or
candidate-only.

If it does, do not fill the gap by inference. Return:

```text
UNKNOWN_DEPENDENCY
```

and include for each blocking entry:

- `unknown_id`
- why it blocks the requested conclusion
- required evidence
- a bounded follow-up demonstration or observation

If no unknown dependency blocks the answer, return:

```text
NO_UNKNOWN_BLOCKER
```

with the cited confirmed evidence and any remaining caveats.

## Integrity rules

- Never promote candidate knowledge to confirmed.
- Never infer strategy from one demonstration.
- Never invent missing coordinates, states, thresholds, rewards, or success
  evidence.
- Keep contradictions and provisional claims visible.
