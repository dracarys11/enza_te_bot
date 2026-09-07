# WING scope supersession audit

## Verdict

`SELFEXP_20260905_04` supersedes the old `WING_SCOPE_NOT_YET_GROUNDED` conclusion. The decision is evidence-based: `trace.jsonl` w1 records the selected `育成プロデュース` category and the same-screen labels `W.I.N.G.`, `Wonder.Idol.Nova.Grandprix.`, and `W.I.N.G.編`; `w1_ikusei_tab.png` also lists `ファン感謝祭` and `G.R.A.D.` as other scenario cards.

## Entry path

The raw w1–w6 records each contain before screenshot, selected action, after screenshot, and `transition_result: MATCHED`. The reconstructed WING path is:

`PRODUCE_SELECTION → UNIT_FORMATION → ITEM_SELECTION → 使用確認 → プロデュース開始 → WING_INTRO_DIALOGUE → WING_HOME`.

The WING preparation trace bypasses `KNOWHOW_SELECTION`; therefore `KNOWHOW_SELECTION_FOR_WING = NOT_APPLICABLE`. SELFEXP_03's KNOWHOW evidence is retained as `NON_WING/OTHER_SCENARIO_EVIDENCE`, not as a missing WING stage.

`w5_after_produce_start.png` is an intro presentation and `w6_after_skip.png` is a matched stable landing. This is a transient interruption, not a separate business state.

## HOME grounding

`w6_after_skip.png` supports WING HOME, season 1, 8 weeks remaining, `あと999人(Eランク)`, stamina 270/300, the main WING controls, and no dialogue/overlay. It is ready as a coarse fast-home benchmark input.

## Reconciliation

The prior “no confirmed WING evidence” and “continue through KNOWHOW” findings are superseded. The old six-screenshot AGY review is historical and remains non-blocking (`AGY_REVIEW_INCOMPLETE`, `RESULT_NOT_RECOVERABLE`, `promotion=NONE`); AGY is not called. SELFEXP_02's explanation for two no-op tab clicks remains unresolved and is not promoted.

No runtime, planner, skill, harness, fusion, or original exploration memory was modified. No production promotion was performed.
