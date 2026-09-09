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

The v0.3 post-fix deterministic, model-free evaluator is the evaluator for
this release. It parses the supported `PASS:`, `PASS only if`, and `FAIL if`
grading-rule forms. The post-fix rule audit reports:

| Case | parsed_rules_count | ignored_rules_count |
|---|---:|---:|
| `case_201` | 4 | 0 |
| `case_202` | 4 | 0 |

The evaluator fix is recorded in commit
`37c6cf3a6a4959b7ea0944b4085d659f41718470`.

## Baseline status

The previous baseline is retained as historical evidence but is superseded
for release scoring:

- Previous baseline: `v0.3_baseline_20260908`
- Status: `SUPERSEDED`
- Reason: it used the evaluator before the v0.3 grading-rule schema fix.

The current valid baseline is:

- Current baseline: `v0.3_postfix_20260909T072027Z`
- Status: `CURRENT VALID BASELINE`

Using the unchanged submissions, the score changed from `170/200` to
`200/200` for every participant. The entire change came from UNKNOWN
handling, which changed from `10` to `40` across the two-case run. No
submissions changed and no model calls were rerun.

## Specification and generated results

Release specifications and review provenance are kept under:

- `cases/v0.2/` and `cases/v0.3/`
- `gold/`
- `reviews/`

Generated, immutable baseline material is kept separately under:

- `runs/v0.2_baseline_20260908/`
- `runs/v0.3_baseline_20260908/`
- `runs/v0.3_postfix_20260909T072027Z/`

Each run directory contains its run manifest, prompts, raw submissions,
per-participant scores, and leaderboard. Generated run artifacts are retained
as recorded and are not benchmark specifications or gold inputs.

## Reproducibility

The current v0.3 post-fix baseline manifest declares two case IDs and three
participants. It records offline operation, excludes gold from prompts,
validates evidence references, binds the evidence manifest, and marks scoring
complete. The current leaderboard reports all three participants at
`200 / 200` using the post-fix evaluator. The earlier `170 / 200` leaderboard
is retained only as the superseded historical baseline.

### Evidence dependency policy

v0.3 uses Option B: an immutable external evidence bundle. Case specifications
retain repository-relative references to evidence owned outside the benchmark
directory. Every evidence artifact that was not already part of the committed
repository baseline is a committed bundle member bound by
`evidence/v0.3/manifest.json`.

The manifest declares the repository root as the deterministic artifact root
and records each bundle member's path, SHA-256 digest, source, and
version/revision. For v0.3, the bundle contains
`enza_memory/observations/OBS_012.json`, which is required by `case_201`.
The manifest and artifact must be checked out from the same release commit;
substitution, regeneration, or retrieval from mutable workspace state is not
permitted during reproduction.

To validate a checkout without modifying artifacts:

1. Check out the release source commit
   `bc35a25f949508a908d014dd4274014bf42eeff6` or the final metadata-update
   commit recorded by the release process.
2. Verify all JSON files in the release paths parse successfully.
3. Run the offline evidence-bundle validation from the repository root:

   ```bash
   python -c 'from pathlib import Path; from enza_memory.benchmark.evidence_bundle import validate_evidence_bundle; errors = validate_evidence_bundle(Path.cwd(), Path("enza_memory/benchmark/evidence/v0.3/manifest.json")); print("\n".join(errors)); raise SystemExit(bool(errors))'
   ```

4. Recalculate SHA-256 for the two v0.3 case files and two v0.3 gold files and
   compare them with this document.
5. Confirm `runs/v0.3_postfix_20260909T072027Z/run_manifest.json` lists
   exactly `case_201` and `case_202`, the three archived participants, the
   evidence manifest, and the post-fix execution commit.
6. Re-score copies of the current baseline submissions with the post-fix
   evaluator if independent score reproduction is required. Do not overwrite
   either baseline archive.

## Known limitations

- v0.3 is a two-case release delta; it is not a cumulative rerun of v0.1 and
  v0.2.
- v0.3 does not have a standalone `gold/v0.3/freeze_manifest.json`; this
  release document provides direct case/gold hashes only.
- The v0.2 archive contains six promoted ARB packages and six gold answers,
  while its normalized baseline run contains five cases and omits `case_103`.
  This historical structure is preserved rather than normalized during the
  v0.3 freeze.
- `runs/v0.3_baseline_20260908/` remains an archived superseded result and is
  not deleted.
- Baseline submissions and scores are archived outputs. Their inclusion does
  not imply independent reruns or model calls during release preparation.

ENZA_BENCHMARK_V0.3_FREEZE
