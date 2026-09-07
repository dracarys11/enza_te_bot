# WING runtime candidate re-audit

WINGVAL_20260905_01 supplies an independent session with two complete S2 normal weeks. Both loops used fresh WING_HOME/anchor guards, stable 1280x720 geometry, expected transitions, post-action HOME verification, and zero AGY/Paddle/OCR calls.

The VOCAL normal-week loop is promoted only for the known WING normal-week branch at 1280x720. The four core controls are `PROMOTE_WITH_GUARDS`; fixed coordinates remain invalid on unvalidated viewports. Required guards are fresh state, matching viewport signature, local anchor, bounds, and post-action transition verification.

The BUSINESS_CHOICE detector remains HOLD. The new run proves that three-card advice is distinct from the prior two-card choice, but contains no new independent two-card instance. The detector must require `card_count == 2` plus the dual-check/selectable-card structure, and its default remains STOP/taught-choice lookup.

`NORMAL_WEEK_NO_AGY` is VALIDATED only for known WING normal weeks. It does not cover audition, business choices, new pages, season transitions, or unknown rooms.

Measured ~39s/week is dominated by game/presentation time: HOME observation ~1.3s, decision 0ms, guard ~4.5s, execution ~8.1s, progression/dialogue ~26s. Compute path is not the bottleneck.

No runtime, Planner, Skill, bridge, or game was modified.
