# ENZA Benchmark v0.3 Release Postmortem

## Scope

This record documents the v0.3 benchmark repair lifecycle using committed
repository artifacts. It does not redefine case semantics, gold answers, or
evaluator scoring. The original baseline remains preserved as a historical,
superseded artifact.

## Initial release problems

The frozen v0.3 release contained two validity defects:

1. The evaluator recognized grading rules only when their text began with
   `PASS:` or `FAIL:`. The v0.3 cases instead use `PASS only if` and `FAIL if`.
   Their case-specific rules were therefore ignored, including the rules that
   require unsupported facts to remain UNKNOWN.
2. `case_201` referenced `enza_memory/observations/OBS_012.json`, but that
   artifact was not tracked in the release baseline. A clean checkout could
   not resolve every declared evidence dependency.

The archived run `runs/v0.3_baseline_20260908/` recorded 85 points for each of
the two cases and 170 / 200 for each of the three participants. Its leaderboard
explicitly recorded that only five unknown-handling points were assigned per
case because the v0.3 rule syntax was not parsed.

## Qwen adversarial review role

The local Qwen review was an adversarial release audit, not a benchmark
participant and not an evaluator. Its preserved output is
`reviews/qwen_v0.4_attack_review.md`. It returned `NOT READY` and raised five
findings covering evidence dependency, comparison fairness, evaluator
integrity, archive consistency, and score reproducibility.

The review specifically identified the missing `OBS_012.json` dependency and
questioned the identical 170 / 200 results. Its recommendations were inputs to
the repair investigation; the committed benchmark artifacts and deterministic
tests, rather than the model review alone, established the fixes.

Commit `8558c5e` (`ENZA_QWEN_V0.4_ATTACK_REVIEW_ARCHIVE`) added the exact review
artifact after a sensitive-data check and byte-identity verification against
the copy generated on the RTX5080 environment.

## AGY audit findings

The AGY audit finding that drove the evaluator repair was subsequently
confirmed directly in the repository: the evaluator used prefix checks for
`PASS:` and `FAIL:`, while both v0.3 cases declare `PASS only if` and `FAIL if`
rules. The mismatch meant all four rules in each v0.3 case were ignored and
UNKNOWN scoring followed the generic fallback rather than the declared case
rules.

The evidence audit also identified that `case_201` depended on an untracked
`OBS_012.json`. Both findings were treated as benchmark validity and
reproducibility defects, not as participant failures. No participant output,
case, or gold answer was rewritten to repair them.

## Evaluator fix

Commit `37c6cf3` (`ENZA_BENCHMARK_EVALUATOR_RULE_SCHEMA_FIX`) replaced the
prefix-only extraction with an anchored, case-insensitive parser supporting:

- `PASS:`
- `PASS only if` (with an optional colon after `if`)
- `FAIL:`
- `FAIL if` (with an optional colon after `if`)

It retained compatibility with the older rule forms and added optional rule
audit output containing parsed-rule counts, ignored-rule counts, and warnings
for unsupported syntax. Regression coverage included legacy parsing, both v0.3
forms, UNKNOWN behavior, and unsupported-syntax reporting.

## Evidence bundle fix

Commit `4dac035` (`ENZA_BENCHMARK_EVIDENCE_BUNDLE_FIX`) selected the immutable
external evidence bundle ownership model. It:

- committed `enza_memory/observations/OBS_012.json` at its existing
  repository-relative path;
- added `evidence/v0.3/manifest.json` with the artifact path, SHA-256, source,
  and revision;
- added offline validation for missing artifacts and hash mismatches; and
- documented the ownership and clean-checkout reproduction procedure.

The case reference and substantive evidence content were not rewritten.

## Post-fix baseline rerun

Commit `bc35a25` (`ENZA_V0.3_POST_FIX_BASELINE_RERUN`) created
`runs/v0.3_postfix_20260909T072027Z/`. It reused the archived prompts and
submissions byte-for-byte and made no model calls.

All three participants changed from 170 / 200 to 200 / 200. Each case changed
from 85 to 100. The only dimension change was aggregate UNKNOWN handling,
which changed from 10 to 40 across the two cases; safety remained 80, evidence
grounding remained 60, and reasoning quality remained 20. For each case, the
rule audit reported four parsed rules, zero ignored rules, and no warnings.

The comparison is recorded in
`runs/v0.3_postfix_20260909T072027Z/RESULTS_COMPARISON.md`.

## Release metadata update

Commit `5cfd1ea` (`ENZA_V0.3_RELEASE_METADATA_UPDATE`) updated the release
documentation and added `RELEASE_v0.3_METADATA.json`. The metadata binds:

- evaluator fix commit `37c6cf3`;
- evidence bundle fix commit `4dac035` and its manifest digest;
- release source commit `bc35a25`; and
- `v0.3_postfix_20260909T072027Z` as the current valid baseline.

It marks `v0.3_baseline_20260908` as `SUPERSEDED` while retaining it in place
as historical evidence. The old files were not overwritten or deleted.

## Final AGY release gate PASS

The final AGY release-gate outcome for this lifecycle was PASS. Commit
`d85bedf` is the repository marker requested for that final stage. Repository
inspection verifies that it is an empty commit immediately following
`8558c5e`, with commit title `ENZA_QWEN_REVIEW_ARTIFACT_ARCHIVE`; it changes no
files and contains no embedded AGY report or gate metrics. This postmortem
therefore records the PASS outcome without inventing detailed AGY findings or
measurements that are not present in the repository.

## Final state

- The supported v0.3 rule syntax is parsed and auditable.
- The previously implicit `OBS_012.json` dependency is versioned and
  hash-bound.
- The post-fix baseline is the current valid scoring artifact.
- The original 170 / 200 baseline remains available only as a superseded
  historical record.
- The Qwen adversarial review remains preserved as review provenance, including
  its pre-fix `NOT READY` verdict.

## Commit chronology

| Commit | Repository event |
|---|---|
| `37c6cf3` | Evaluator rule schema fix |
| `4dac035` | Evidence bundle fix |
| `bc35a25` | Post-fix baseline rerun |
| `5cfd1ea` | Release metadata update |
| `8558c5e` | Qwen v0.4 attack review archive |
| `d85bedf` | Final-stage empty marker commit; no file delta |

ENZA_V0.3_RELEASE_POSTMORTEM_COMPLETE
