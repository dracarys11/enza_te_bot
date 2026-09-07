# ZCode Self-Exploration Audit

Session: `SELFEXP_20260905_01` (read-only audit)

## Session integrity

`SESSION_INTEGRITY = WARN`. The 13 trace steps are unique, contiguous and time ordered; every executed action has an existing after screenshot. All screenshot references resolve. Raw trace contains 12 `MATCHED` transitions and one `MISMATCH` (`step9`), while `summary.json` reports 11 valid transitions. The summary also reports 15 screenshots although 16 files are referenced/present, and its `new_pages=3`/`new_controls=8` do not match the six page records/nine control records.

## Evidence findings

HOME, IDOL_PORTAL and MENU_OVERLAY have repeated visual support. PRODUCE_MENU and IDOL_LIST are single-example or overlay-adjacent and remain held. WORK_ACTIVITY is supported as a base page, but `step9` demonstrates a delayed `営業について 1/6` interruption. No control has a calibrated `normalized_bbox`; all coordinates are approximate trace coordinates. The wildcard `back_arrow` combines multiple pages and has one failed attempt at `step9`, so it is not execution-ready.

The correct minimal interruption interpretation for the work branch is:

```text
WORK_ACTIVITY → (back) → INTERRUPTION_OVERLAY
→ dismiss → WORK_ACTIVITY → (back) → HOME
```

The trace supports this: `step9` is `MISMATCH`, `step10` closes the overlay, and `step11` reaches HOME. A direct unconditional `WORK_ACTIVITY → HOME` transition is therefore over-specified.

## Cross-file drift

See `cross_file_drift.json`. The main drift is summary counters and the page-like encoding of tutorial overlays. `step9` itself is consistently retained as a failed transition and should not be promoted as success.

## Promotion classification

Promotion means entry to a validated candidate pool only; no production configuration was changed. Repeated page identity candidates are suitable for next validation, but controls and transitions remain held until geometry and repeated runs are available. `work_complete_buttons` is rejected because it was recorded but never clicked or transition-verified.

## Minimal AGY review

`agy_review_manifest.json` selects six review items over six distinct screenshot groups (within the requested 4–8 screenshot budget): HOME, PRODUCE_MENU vs IDOL_PORTAL, IDOL_LIST/tutorial separation, delayed WORK_ACTIVITY overlay, shared back arrow, and MENU_OVERLAY parentage. No AGY call was made.

## Runtime readiness

`NOT_READY`. Current memory is useful as candidate knowledge, not as autonomous execution policy. The three most dangerous direct-consumption errors are: treating wildcard `back_arrow` as page-independent, treating `WORK_ACTIVITY → HOME` as unconditional despite the delayed overlay, and treating approximate single-frame controls as stable clickable geometry. The audit also identifies a self-confirmation risk: page/control/transition memory is authored from the same ZCode trace; it is not independent visual validation.

NO_PRODUCTION_PROMOTION_PERFORMED.
