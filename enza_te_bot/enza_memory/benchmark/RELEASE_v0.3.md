# ENZA Benchmark v0.3 Freeze Package

- Benchmark version: `v0.3`
- Freeze date: `2026-09-09`
- Mode: `OFFLINE_ONLY`
- Release commit: the Git commit containing this file

## Release scope

The v0.3 evaluation set contains the two cases promoted by the committee
review:

| Case | Reliability dimension | Case specification | Gold answer |
|---|---|---|---|
| `case_201` | Observation failure must not trigger business recovery | `cases/v0.3/case_201.json` | `gold/v0.3/case_201_gold.json` |
| `case_202` | Crash backfill evidence durability downgrade | `cases/v0.3/case_202.json` | `gold/v0.3/case_202_gold.json` |

The v0.2 cases, gold, review records, and baseline run are included as a
compatibility archive. They are not additional cases in the v0.3 baseline.
The v0.3 promotion decision and held candidates are documented in
`reviews/v0.3_committee_review.md`.

## Gold status

The v0.3 gold set contains one answer for each included case. These answers
are frozen as written and were not rewritten for this release.

| Gold file | SHA-256 |
|---|---|
| `gold/v0.3/case_201_gold.json` | `c7204b38ab6e2433364f8bcf345d67d52fde86d1bc6bcf19c25d3a430c07105d` |
| `gold/v0.3/case_202_gold.json` | `78525507e2bbf776fdec7589aefeb3b7451ec34e05974ecb5ce4f0aa72f2f7b4` |

The corresponding case bindings are:

| Case file | SHA-256 |
|---|---|
| `cases/v0.3/case_201.json` | `766338d40bdb18d86b2d6ce2473637aecdba6f4c075acf30e3a15a6254eba1a8` |
| `cases/v0.3/case_202.json` | `87fe9139fb7a4c46674e324bf28c89d11615369d5e337ae84f11ea4d75207a17` |

The v0.1 and v0.2 gold archives retain their existing
`freeze_manifest.json` files. v0.3 has no separate gold freeze manifest; the
four hashes above are the release-level bindings for its cases and gold.

## Evaluator status

The existing deterministic, model-free evaluator is the evaluator for this
release. Evaluator source and scoring behavior are outside this freeze commit
and remain unchanged. The archived v0.3 baseline reports the current scoring
behavior explicitly, including the rule-prefix limitation that assigns five
unknown-handling points for these case contracts.

## Specification and generated results

Release specifications and review provenance are kept under:

- `cases/v0.2/` and `cases/v0.3/`
- `gold/`
- `reviews/`

Generated, immutable baseline material is kept separately under:

- `runs/v0.2_baseline_20260908/`
- `runs/v0.3_baseline_20260908/`

Each run directory contains its run manifest, prompts, raw submissions,
per-participant scores, and leaderboard. Generated run artifacts are retained
as recorded and are not benchmark specifications or gold inputs.

## Reproducibility

The v0.3 baseline manifest declares two case IDs and three participants. It
records offline operation, excludes gold from prompts, validates evidence
references, and marks scoring complete. The archived leaderboard reports all
three participants at `170 / 200` using the unchanged evaluator.

To validate a checkout without modifying artifacts:

1. Check out the release commit containing this file.
2. Verify all JSON files in the release paths parse successfully.
3. Recalculate SHA-256 for the two v0.3 case files and two v0.3 gold files and
   compare them with this document.
4. Confirm `runs/v0.3_baseline_20260908/run_manifest.json` lists exactly
   `case_201` and `case_202` and the three archived participants.
5. Re-score copies of the archived submissions with the existing evaluator if
   independent score reproduction is required. Do not overwrite the archive.

## Known limitations

- v0.3 is a two-case release delta; it is not a cumulative rerun of v0.1 and
  v0.2.
- v0.3 does not have a standalone `gold/v0.3/freeze_manifest.json`; this
  release document provides direct case/gold hashes only.
- `case_201` references `enza_memory/observations/OBS_012.json`. That evidence
  record exists in the release workspace but is not part of this benchmark
  package or its committed baseline, so a clean-checkout evidence-availability
  check will report that external dependency missing.
- The v0.2 archive contains six promoted ARB packages and six gold answers,
  while its normalized baseline run contains five cases and omits `case_103`.
  This historical structure is preserved rather than normalized during the
  v0.3 freeze.
- Baseline submissions and scores are archived outputs. Their inclusion does
  not imply independent reruns or model calls during release preparation.

ENZA_BENCHMARK_V0.3_FREEZE
