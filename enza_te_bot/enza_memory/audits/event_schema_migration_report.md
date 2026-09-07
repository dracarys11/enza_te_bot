# Event Schema Migration Readiness Audit

**Mode:** OFFLINE ONLY

**Scope:** read-only audit of existing evidence metadata, benchmark cases,
reconciliation reports, and artifact registry

**Generated:** 2026-09-07

## Summary

| Metric | Count |
|---|---:|
| TOTAL_RECORDS | 962 |
| NESTED_EVENT_COMPLETE | 0 |
| LEGACY_ONLY | 0 |
| CONFLICTS | 0 |
| MISSING_FIELDS | 3,848 field occurrences |

## Missing fields

All 962 metadata records are missing each required nested field:

| Required field | Missing records |
|---|---:|
| `event.action` | 962 |
| `event.phase` | 962 |
| `event.result` | 962 |
| `event.state` | 962 |

`MISSING_FIELDS` is reported as field occurrences (962 × 4), with the
per-field breakdown above.

## Findings

The audited metadata source is:

`enza_memory/evidence_metadata/metadata_records.jsonl`

Its records conform to the bootstrap metadata schema and contain a `vlm`
pending block (`state`, `phase`, `event_type`, and related visual fields), not
the migrated `event` block. No record contains a complete nested event, and no
record contains any of the four legacy top-level fields, so there are no
legacy-only records and no nested-versus-legacy conflicts to report.

The artifact registry, existing `benchmark_cases/`, and reconciliation/report
artifacts were checked for metadata sources and migration evidence. They
provide references and event-shaped durable records, but do not provide a
second query metadata record set that supersedes `metadata_records.jsonl`.

## Readiness assessment

**NOT READY for complete event-schema migration.** The query-layer precedence
logic can consume nested events when present, but the audited evidence metadata
corpus has not yet been populated with `event.action`, `event.phase`,
`event.result`, or `event.state`. This report does not modify metadata or
promote `vlm` pending values into event claims.

No runtime, planner, executor, policy, index, or image files were modified.
