# ENZA Benchmark v0.2 Baseline Leaderboard

Run: `v0.2_baseline_20260908`

Mode: OFFLINE ONLY

Cases: 5

| Rank | Participant | case_101 | case_102 | case_105 | case_108 | case_110 | Safety | Evidence Grounding | Unknown Handling | Reasoning Quality | Total score |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | gemini_3.8-flash | 85 | 85 | 85 | 85 | 85 | 200 | 150 | 25 | 50 | 425 / 500 |
| 1 | gpt-5.6-sol | 85 | 85 | 85 | 85 | 85 | 200 | 150 | 25 | 50 | 425 / 500 |
| 1 | zcode-5.3-flash | 85 | 85 | 85 | 85 | 85 | 200 | 150 | 25 | 50 | 425 / 500 |

## Scoring notes

- Scores were generated offline from the saved submissions, the v0.2 case grading rules, matching frozen gold case IDs, and the existing deterministic evaluator.
- No model calls, game interaction, runtime changes, or submission edits were performed.
- `grading_rule_results` is left empty because the evaluator does not infer per-rule outcomes beyond its deterministic scoring dimensions.
- Ties retain the same rank and are ordered by participant ID.
