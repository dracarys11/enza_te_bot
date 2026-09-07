---
name: gemini-vision-v1-1
description: Draft bounded visual-facts extraction for screenshots, adding counter duplication, visible clipped fragments, per-control geometry, and limited ROI rechecks without semantic interpretation.
---

# Gemini Vision Extraction Skill v1.1 (draft)

## Purpose

Extract machine-consumable visual facts from one screenshot. Return visual
evidence only. Do not identify the current screen, infer game progress, choose
an action, or grant execution permission.

This draft preserves the `VisionObservation Contract v0.1` boundary. It does
not change the schema and does not replace `gemini-vision` v1.

## Forbidden output

Never emit these fields or equivalent claims:

- `semantic_state`, `page_name`, `screen_name`, `current_state`
- `next_action`, `recommendation`, `button_purpose`, `intent`, `strategy`
- `game_progress`, execution commands, or permission claims

Coordinates describe visible geometry only. They are not click instructions.

## Output contract

Return exactly one JSON object and no prose or Markdown fences:

```json
{
  "observation_id": "",
  "capture": {
    "timestamp": "",
    "frame_id": "",
    "screenshot_digest": ""
  },
  "viewport": {"width": 0, "height": 0},
  "text_regions": [],
  "interaction_candidates": [],
  "numeric_regions": [],
  "overlay_regions": [],
  "uncertainties": [],
  "detection_failures": []
}
```

Use supplied capture metadata. Do not invent timestamps, frame identifiers, or
digests. When the caller omits metadata, omit the unavailable values for the
adapter to populate and record the gap in `detection_failures`; do not invent a
spatial bbox for a metadata failure.

## Initial extraction

Perform one ordinary v1 visual-facts extraction over the screenshot:

- record readable text with `[x, y, width, height]` bbox and confidence;
- record visible interaction candidates without naming their function;
- record parseable counters, visible overlays, and material uncertainty;
- leave unsupported facts out instead of guessing.

Do not perform a mandatory second full-screen scan and do not attempt complete
enumeration of every decorative mark or possible control.

## Text regions and clipped fragments

Record only characters supported by visible pixels:

```json
{
  "id": "t20",
  "text": "次へ",
  "bbox": [1139, 638, 72, 43],
  "confidence": 0.99
}
```

When text is clipped by a viewport edge or visible obstruction:

- preserve the readable fragment rather than silently dropping the region;
- never complete characters or words outside the visible pixels;
- reduce confidence when the fragment is ambiguous;
- add an overlapping uncertainty with reason
  `text_clipped_by_viewport_edge` or `occluded_by_overlay`.

If no characters can be read reliably, emit no text region and record the
unreadable area as an uncertainty.

## Numeric dual recording

Every emitted `numeric_regions` entry must have a corresponding
`text_regions` entry containing the same visible `raw_text` and covering the
same visual region.

Emit a numeric region only when both the value and maximum are explicitly
visible and parse cleanly, for example `1/7` or `2/20`:

```json
{
  "id": "n1",
  "raw_text": "2/20",
  "value": 2,
  "max_value": 20,
  "bbox": [73, 160, 58, 28],
  "confidence": 0.99
}
```

Do not invent a maximum for standalone values such as `283`, `Lv.80`, or
`SP:40`. Keep those strings in `text_regions` only unless the complete
value/maximum pair is visible.

## One control, one candidate

For every interaction candidate that is emitted:

- represent one visually distinct control with one candidate;
- represent repeated controls as separate candidates when their individual
  boundaries are visible;
- do not group a row of distinct tabs or buttons into one large candidate;
- do not split one button into separate background, icon, and label
  candidates;
- link only text that visually belongs to that control.

This is a granularity rule, not a completeness requirement. Do not label every
panel, banner, card, or decorative region as interactive. A candidate requires
visible affordance evidence such as a bounded button surface, tab boundary,
control glyph, or repeated control geometry.

Use the existing interaction shape:

```json
{
  "id": "e20",
  "bbox": [1092, 623, 166, 78],
  "appearance": {"shape": "rounded_rect", "color_hint": "pink"},
  "linked_text_ids": ["t20"],
  "interaction_confidence": 0.99
}
```

## Bounded ROI recheck

After the initial extraction, optionally recheck only a specific region of
interest when the first pass already recorded one of these conditions:

- a clipped text fragment;
- low-contrast text that may change the emitted reading;
- an ambiguous boundary between adjacent visible controls;
- a low-confidence visible text-to-control association.

The recheck is bounded:

- recheck at most four ROIs;
- inspect each selected ROI once;
- do not rescan the full screenshot;
- do not create additional recheck ROIs during the recheck;
- after the recheck, either update the visual fact with supported evidence or
  preserve the uncertainty and stop.

Do not use an ROI recheck merely because a region might contain something.

## Occlusion boundary

A partially occluded element may be emitted only when enough of its own pixels
remain visible to support its bbox and appearance. Mark the visible limitation
in `uncertainties` and, where already supported by the contract, in its
appearance metadata.

Never reconstruct or emit a fully occluded element from layout expectations,
prior screenshots, filenames, or inferred page structure.

## Final check

Before returning:

1. Remove semantic state, action, intent, strategy, and execution claims.
2. Ensure every emitted region has contract-compatible geometry and
   confidence fields.
3. Ensure every numeric region has a matching visible text region.
4. Ensure emitted controls are neither grouped nor split.
5. Ensure clipped text contains visible fragments only.
6. Ensure no fully occluded element was inferred.
7. Ensure the ROI limit was respected, then return JSON only.

