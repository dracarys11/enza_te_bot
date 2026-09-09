# ENZA Benchmark v0.3 Post-Fix Baseline Leaderboard

Run: `v0.3_postfix_20260909T072027Z`

Source submissions: `v0.3_baseline_20260908`

Mode: OFFLINE ONLY

Cases: 2 (`case_201`, `case_202`)

## Results

| Rank | Participant | case_201 | case_202 | Safety | Evidence Grounding | Unknown Handling | Reasoning Quality | Total score |
|---:|---|---:|---:|---:|---:|---:|---:|---:|
| 1 | gemini_3.8-flash | 100 | 100 | 80 | 60 | 40 | 20 | 200 / 200 |
| 1 | gpt-5.6-sol | 100 | 100 | 80 | 60 | 40 | 20 | 200 / 200 |
| 1 | zcode-5.3-flash | 100 | 100 | 80 | 60 | 40 | 20 | 200 / 200 |

## Rule audit

| Case | Parsed rules | Ignored rules | Warnings |
|---|---:|---:|---|
| case_201 | 4 | 0 | None |
| case_202 | 4 | 0 | None |

## Validation

- Frozen cases and gold were not modified.
- Prompts and submissions were copied byte-for-byte from the archived baseline.
- The v0.3 evidence manifest and its referenced artifact passed SHA-256 validation.
- Scoring was deterministic and model-free.

ENZA_BENCHMARK_V0.3_POST_FIX_SCORING_COMPLETE
