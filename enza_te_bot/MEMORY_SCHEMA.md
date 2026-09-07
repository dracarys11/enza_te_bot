# enza Environment Agent Memory Schema

## Purpose

This document defines the governance contracts for Environment Agent memory.
The contracts are descriptive and non-executable. Existing memory artifacts may
predate this schema and must not be treated as compliant merely because they are
valid JSON.

## Common types

Every artifact must include:

```json
{
  "schema_version": 1,
  "artifact_id": "stable unique identity",
  "artifact_type": "OBSERVATION|TRAJECTORY|FAILURE|POLICY|DECISION_REVIEW",
  "created_at": "ISO-8601 timestamp",
  "status": "CANDIDATE|REVIEWED|REJECTED",
  "provenance": {},
  "evidence_references": [],
  "unknowns": []
}
```

### Evidence classification

- `FACT`: directly measured by the cited evidence source.
- `INFERENCE`: interpretation derived from cited evidence.
- `PROVISIONAL`: a reviewable hypothesis that is not yet accepted.
- `UNKNOWN`: missing, ambiguous, stale, contradictory, or unverified.

Confidence is a numeric estimate in `[0, 1]`. It never changes classification.
In particular, high-confidence `INFERENCE` remains `INFERENCE`.

### Provenance classification

- `session_observed`: captured first-hand in the named provider session.
- `user_reported`: supplied by a human or a summary from another session.
- `inference`: derived by an agent from other records.

Every provenance object contains:

```json
{
  "classification": "session_observed|user_reported|inference",
  "producer": "agent or provider identity",
  "provider_session_id": "session identity or null",
  "captured_at": "ISO-8601 timestamp or null",
  "source_artifact_ids": [],
  "integrity": {
    "algorithm": "digest algorithm or null",
    "digest": "digest or null"
  }
}
```

Missing session identity, timestamp, or integrity data must be represented as an
unknown. It must not be silently generated during ingestion.

### Evidence reference

```json
{
  "evidence_id": "stable evidence identity",
  "kind": "SCREENSHOT|URL_READ|TITLE_READ|DOM_SNAPSHOT|ACCESSIBILITY_SNAPSHOT|TRACE|HUMAN_REPORT|OTHER",
  "path": "repository-relative path or null",
  "captured_at": "ISO-8601 timestamp or null",
  "source": "capture source",
  "classification": "FACT|INFERENCE|PROVISIONAL|UNKNOWN",
  "integrity": {
    "algorithm": "digest algorithm or null",
    "digest": "digest or null"
  }
}
```

An evidence reference proves only the claim supported by that source.
Screenshot evidence cannot be relabeled as DOM or accessibility evidence.

## Observation contract

An Observation records one environment sample without selecting an action.

```json
{
  "schema_version": 1,
  "artifact_id": "OBS...",
  "artifact_type": "OBSERVATION",
  "created_at": "ISO-8601 timestamp",
  "status": "CANDIDATE",
  "environment": {
    "provider": "provider identity",
    "provider_session_id": "session identity",
    "frame_id": "frame identity",
    "viewport": {"width": 0, "height": 0},
    "url": {"value": null, "classification": "UNKNOWN", "evidence_ids": []},
    "title": {"value": null, "classification": "UNKNOWN", "evidence_ids": []},
    "canvas": {"value": null, "classification": "UNKNOWN", "evidence_ids": []},
    "dom_available": {"value": null, "classification": "UNKNOWN", "evidence_ids": []},
    "accessibility_available": {"value": null, "classification": "UNKNOWN", "evidence_ids": []}
  },
  "page_state": {
    "label": "UNKNOWN",
    "classification": "UNKNOWN",
    "confidence": 0.0,
    "evidence_ids": []
  },
  "visible_elements": [],
  "numeric_observations": [],
  "provenance": {},
  "evidence_references": [],
  "unknowns": []
}
```

Each visible element contains:

```json
{
  "element_id": "observation-local identity",
  "name": "descriptive label",
  "visual_evidence": "directly visible basis",
  "source": "SCREENSHOT|DOM|ACCESSIBILITY|OTHER",
  "verification_level": "VISIBLE_ONLY|SOURCE_VERIFIED|UNKNOWN",
  "role": {
    "value": "descriptive role or UNKNOWN",
    "classification": "FACT|INFERENCE|PROVISIONAL|UNKNOWN"
  },
  "geometry": {
    "bounds": null,
    "coordinate_space": "NORMALIZED_VIEWPORT|PIXEL_VIEWPORT|UNKNOWN",
    "classification": "APPROXIMATE|SOURCE_VERIFIED|UNKNOWN"
  },
  "confidence": 0.0,
  "evidence_ids": [],
  "unknowns": []
}
```

For an opaque canvas, a visually identified control remains
`source=SCREENSHOT` and `verification_level=VISIBLE_ONLY`. This does not prove
clickability, an exact hitbox, DOM identity, accessibility identity, or gameplay
meaning.

## Trajectory contract

A Trajectory records ordered evidence. It is not a policy demonstration by
default.

```json
{
  "schema_version": 1,
  "artifact_id": "TRAJ...",
  "artifact_type": "TRAJECTORY",
  "created_at": "ISO-8601 timestamp",
  "status": "CANDIDATE",
  "mission": {
    "description": "bounded mission",
    "authority_reference": null,
    "allowed_scope": [],
    "forbidden_scope": []
  },
  "steps": [
    {
      "step_id": "stable step identity",
      "timestamp": "ISO-8601 timestamp",
      "provenance": {},
      "before_observation_id": "OBS...",
      "intent_id": null,
      "gate_decision_id": null,
      "permission_id": null,
      "execution": {
        "performed": false,
        "provider_session_id": null,
        "permission_consumed": false,
        "result": "NO_ACTION|ISSUED|REJECTED|UNKNOWN",
        "evidence_ids": []
      },
      "after_observation_id": null,
      "verification": {
        "result": "VERIFIED|FAILED|UNKNOWN|NOT_APPLICABLE",
        "independent": false,
        "evidence_ids": []
      },
      "claims": [],
      "unknowns": []
    }
  ],
  "provenance": {},
  "evidence_references": [],
  "unknowns": []
}
```

Each claim inside a trajectory must carry classification, confidence, and
evidence IDs. A user-reported step must not be merged into a session-observed
step. A successful visible transition does not establish strategy quality,
hidden state integrity, or room completion.

## Failure contract

A Failure preserves an anomaly and competing explanations without selecting an
unsupported cause.

```json
{
  "schema_version": 1,
  "artifact_id": "FAIL...",
  "artifact_type": "FAILURE",
  "created_at": "ISO-8601 timestamp",
  "status": "CANDIDATE",
  "trajectory_id": "TRAJ...",
  "step_id": "step identity",
  "before_observation_id": "OBS...",
  "intent_id": null,
  "execution_evidence_ids": [],
  "after_observation_id": "OBS...",
  "description": {
    "value": "observed mismatch",
    "classification": "FACT|INFERENCE|PROVISIONAL|UNKNOWN",
    "confidence": 0.0,
    "evidence_ids": []
  },
  "cause": {
    "value": "UNKNOWN",
    "classification": "UNKNOWN",
    "confidence": 0.0,
    "evidence_ids": []
  },
  "hypotheses": [],
  "recovery": {
    "performed": false,
    "trajectory_step_ids": [],
    "observed_result": "UNKNOWN",
    "hidden_state_integrity": "UNKNOWN"
  },
  "candidate_constraint_ids": [],
  "provenance": {},
  "evidence_references": [],
  "unknowns": []
}
```

Each hypothesis requires its own classification, confidence, evidence IDs, and
contradicting evidence. Recovery never erases the failure and does not prove
that hidden state was unchanged.

## Policy contract

A Policy artifact stores reviewed constraints separately from gameplay
strategy. New constraints are non-executable candidates by default.

```json
{
  "schema_version": 1,
  "artifact_id": "POLICY...",
  "artifact_type": "POLICY",
  "created_at": "ISO-8601 timestamp",
  "status": "CANDIDATE",
  "constraints": [
    {
      "constraint_id": "stable identity",
      "statement": "bounded constraint",
      "scope": "explicit applicability boundary",
      "classification": "INFERENCE|PROVISIONAL|UNKNOWN",
      "confidence": 0.0,
      "evidence_ids": [],
      "source_failure_ids": [],
      "contradicting_evidence_ids": [],
      "review_status": "UNREVIEWED|PASS|WARN|FAIL",
      "executable": false,
      "overgeneralization_risk": "description or UNKNOWN",
      "unknowns": []
    }
  ],
  "provenance": {},
  "evidence_references": [],
  "unknowns": []
}
```

A constraint cannot become executable merely because it appeared repeatedly or
has high confidence. Promotion requires independent evidence, explicit review,
bounded scope, contradiction analysis, and separate implementation authority.

## Decision Review contract

A Decision Review records a governance judgment. It does not execute or select
a gameplay objective.

```json
{
  "schema_version": 1,
  "artifact_id": "REVIEW...",
  "artifact_type": "DECISION_REVIEW",
  "created_at": "ISO-8601 timestamp",
  "status": "REVIEWED",
  "subject": {
    "artifact_ids": [],
    "decision_id": null
  },
  "reviewer": {
    "identity": "reviewer identity",
    "independent_of_producer": null
  },
  "result": "PASS|PASS_WITH_WARNINGS|FAIL|UNKNOWN",
  "findings": [
    {
      "finding_id": "stable identity",
      "severity": "INFO|WARN|ERROR|CRITICAL",
      "classification": "FACT|INFERENCE|PROVISIONAL|UNKNOWN",
      "confidence": 0.0,
      "statement": "review finding",
      "evidence_ids": [],
      "unknowns": []
    }
  ],
  "allowed_usage": [],
  "forbidden_usage": [],
  "promotion": {
    "requested": false,
    "approved": false,
    "authority_reference": null
  },
  "provenance": {},
  "evidence_references": [],
  "unknowns": []
}
```

A review may approve an artifact for a bounded evaluation purpose while still
forbidding ground-truth training or executable-policy use.

## Validation requirements

- JSON must parse and match the declared schema version.
- Artifact IDs and referenced IDs must resolve uniquely.
- Evidence paths must exist when a path is claimed.
- Available evidence should have an integrity digest.
- Timestamps must include a timezone.
- Confidence must be within `[0, 1]`.
- Required classifications cannot be omitted.
- `UNKNOWN` fields cannot contain inferred replacement values.
- Screenshot-only elements cannot claim DOM, accessibility, exact-hitbox, or
  clickable verification.
- A trajectory action without independent verification cannot be marked
  verified.
- Candidate policy cannot be marked executable.
- Validation success proves structural conformance only; it does not confirm
  gameplay state or knowledge.
