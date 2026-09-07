# Event Schema Derivation Prototype v1 — Migration Report

- mode: OFFLINE_ONLY (metadata_records.jsonl read-only; runtime untouched)
- input: enza_memory/evidence_metadata/metadata_records.jsonl
- output: enza_memory/evidence_metadata/event_metadata_v1.jsonl

## Counts

| metric | count |
|---|---|
| TOTAL | 962 |
| DERIVED_COMPLETE | 0 |
| PARTIAL | 581 |
| UNKNOWN | 381 |
| LOW_CONFIDENCE (derived, confidence < 0.7) | 417 |

## Derivation sources used (authority_type)

| authority_type | records |
|---|---|
| FILENAME_CONVENTION | 417 |
| NONE | 381 |
| OBS_ARTIFACT | 12 |
| REVIEW_MANIFEST | 152 |

## Rules honored

- Only durable, provable sources promoted: review manifests (page/phase/
  recommended_action, confidence 0.75), OBS top-level screenshot
  bindings (explicit page_state label and explicit season_result PASS/FAIL,
  confidence 0.9), capture-time filename conventions (confidence
  0.6, never FACT).
- VLM fields are observations only: even when present in a future records
  version they are capped at 0.5 and can never promote a field to
  FACT.  v0.1 records are vlm_status=PENDING, so no VLM derivation fired.
- Unsupported records stay UNKNOWN with authority_type NONE — never guessed.

**EVENT_SCHEMA_DERIVATION_PROTOTYPE_READY**
