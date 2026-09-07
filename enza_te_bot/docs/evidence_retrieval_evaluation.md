# Evidence retrieval evaluation

- Model: `/home/administrator/models/siglip-base-patch16-224`
- Total indexed images: 655
- Evaluated queries: 100
- Top-k neighbors: 5
- Sampling seed: 0

Association metrics exclude the query image itself. Exact self retrieval is measured at rank 1.
Average similarity and score distribution cover non-self top-k neighbors.

| Metric | Value | Eligible queries |
| --- | ---: | ---: |
| Exact self retrieval rate | 86.0% | 100 |
| Same-content rank-1 retrieval rate | 100.0% | 100 |
| Same run hit rate | 87.3% | 63 |
| Same phase/state hit rate | 0.0% | 1 |
| Failure association hit rate | 100.0% | 2 |
| Average similarity | 0.951430493235588 | — |

## Metadata coverage

| Field | Images | Total |
| --- | ---: | ---: |
| run_id | 403 | 655 |
| trajectory | 13 | 655 |
| failure | 7 | 655 |
| observation | 12 | 655 |
| phase | 10 | 655 |
| state | 10 | 655 |

## Score distribution

```json
{
  "min": 0.7514548301696777,
  "p10": 0.8613432049751282,
  "p25": 0.9301941990852356,
  "median": 0.9759199619293213,
  "p75": 0.9919002652168274,
  "p90": 0.9979116320610046,
  "max": 1.0
}
```

## Interpretation

Exact path self retrieval can be lower than same-content retrieval when duplicate image bytes share a score and FAISS resolves the tie to another vector ID.
Association rates with small eligible-query counts are diagnostic only; they are not broad quality estimates until metadata coverage increases.

## Representative good cases

| Query | Same content rank 1 | Best non-self neighbor | Similarity | Same run | Same state | Same failure |
| --- | --- | --- | ---: | --- | --- | --- |
| dataset/evidence/result/20260905_234057_dc58a91a_result_flow.png | True | wing_runs/WINGRUN_20260905_01/screenshots/s3_audition_pass.png | 0.9970146417617798 | None | None | None |
| dataset/evidence/result/20260906_002133_dc58a91a_reward.png | True | wing_runs/WINGRUN_20260907_01/screenshots/ngvg_15_final_boundary.png | 0.9977179765701294 | None | None | None |
| dataset/evidence/review_batches/v0_3/annotated/VRB02_006.png | True | wing_runs/WINGRUN_20260905_01/screenshots/s2_home_first.png | 0.7583984732627869 | None | None | None |
| dataset/evidence/review_batches/v0_3/annotated/VRB02_015.png | True | dataset/evidence/review_batches/v0_3/annotated/VRB02_016.png | 0.9821398854255676 | None | None | None |
| dataset/evidence/review_batches/v0_3/annotated/VRB02_017.png | True | dataset/evidence/review_batches/v0_3/annotated/VRB02_001.png | 0.9665330052375793 | None | None | None |

## Representative bad cases

| Query | Same content rank 1 | Best non-self neighbor | Similarity | Same run | Same state | Same failure |
| --- | --- | --- | ---: | --- | --- | --- |
| dataset/evidence/audition_selection/20260905_143649_38712583_list.png | True | wing_runs/WINGRUN_20260905_01/screenshots/wk9_audition_intro.png | 1.0 | None | None | None |
| dataset/evidence/audition_selection/20260905_231421_38712583_the_legend.png | True | wing_runs/WINGRUN_20260905_01/screenshots/s4_leg1_home_after.png | 1.0 | None | None | None |
| dataset/evidence/choice/20260905_142730_38712583_two_option.png | True | wing_runs/WINGRUN_20260905_01/screenshots/wk5_after_choice.png | 0.9999998807907104 | None | None | None |
| dataset/evidence/choice/20260905_162603_38712583_middle_pick.png | True | wing_runs/WINGRUN_20260905_01/screenshots/s3_50k_battle_entry.png | 0.9999999403953552 | None | None | None |
| dataset/evidence/choice/20260905_170306_38712583_middle_pick.png | True | wing_runs/WINGRUN_20260905_01/screenshots/s4_w3_home.png | 1.0 | None | None | None |
