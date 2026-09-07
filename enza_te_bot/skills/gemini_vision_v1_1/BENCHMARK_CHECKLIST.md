# Gemini Vision v1.1 vs v1 Benchmark Checklist

Use this checklist for an offline, same-input comparison before considering
promotion of the v1.1 draft. It does not authorize live extraction or runtime
integration.

## Test controls

- [ ] Use byte-identical screenshots for v1 and v1.1.
- [ ] Hold provider, model, image resolution, temperature, token limit, and
      capture metadata constant.
- [ ] Run each version independently; do not show either output to the other.
- [ ] Preserve raw JSON and validation errors without manual repair.
- [ ] Record wall-clock provider latency and timeout status separately from
      parsing or benchmark time.
- [ ] Define the latency budget and promotion threshold before running.
- [ ] Use Paddle only as an independent text reference, never as hidden prompt
      context for either vision run.

Suggested existing screenshot groups:

- [ ] OB-001 produce-selection screenshot: text, bottom clipping, and ordinary
      interaction geometry.
- [ ] OB-003 dialog screenshot: numeric counter and partial occlusion.
- [ ] OB-003 unit-formation screenshot: repeated tabs, small labels, and dense
      controls.
- [ ] OB-003 after-back screenshot: clipped and low-contrast banner text.

## Contract and boundary

- [ ] Both outputs parse as JSON.
- [ ] Both outputs pass the unchanged `VisionObservation v0.1` validator after
      normal adapter metadata handling.
- [ ] No semantic-state, action, intent, strategy, progress, or execution
      fields appear.
- [ ] Filenames and prior screenshots are not used as visual evidence.
- [ ] UNKNOWN and unreadable facts remain represented as uncertainty rather
      than inferred content.

## Text comparison

- [ ] Record exact and NFKC-normalized text recall against Paddle.
- [ ] Report missed and extra strings; do not treat either provider as correct
      without adjudication.
- [ ] Manually review every v1.1-only clipped fragment against visible pixels.
- [ ] Record clipped-fragment precision: supported fragments / reviewed
      fragments.
- [ ] Confirm that v1.1 never completes text beyond the viewport or occluder.
- [ ] Separate meaningful UI-label recall from decorative glyphs and isolated
      low-confidence OCR tokens.

## Numeric dual recording

- [ ] Every v1.1 numeric region has an equal `raw_text` in `text_regions` with
      overlapping geometry.
- [ ] `1/7` and `2/20` appear in both collections when visible.
- [ ] Standalone strings such as `283`, `Lv.80`, and `SP:40` do not acquire an
      invented `max_value`.
- [ ] Compare duplicate, missed, malformed, and unsupported numeric entries.

## Interaction granularity and geometry

- [ ] Build an adjudicated list of visible controls for each screenshot.
- [ ] Measure interaction recall and false-positive count against that list.
- [ ] Report matched bbox IoU and center distance.
- [ ] Count grouped-control errors, especially the ten unit tabs.
- [ ] Count split-control errors where one button becomes multiple candidates.
- [ ] Count decorative panels, banners, cards, or overlay containers incorrectly
      emitted as controls.
- [ ] Measure text-to-control grounding agreement.
- [ ] Preserve icon-only controls as textless/UNKNOWN candidates when visually
      supported.

## ROI recheck behavior

- [ ] Record every selected ROI and its trigger.
- [ ] Confirm no more than four ROIs were rechecked.
- [ ] Confirm each ROI was rechecked at most once.
- [ ] Confirm no second full-screen sweep occurred.
- [ ] Confirm rechecks did not recursively create new recheck regions.
- [ ] For each ROI, record whether it recovered a supported fact, corrected a
      fact, or retained uncertainty.
- [ ] Compare recall gain, false-positive delta, output-token delta, and latency
      delta with v1.

## Uncertainty and occlusion

- [ ] Every low-confidence fact required by the existing validator overlaps an
      uncertainty bbox.
- [ ] Uncertainty reasons distinguish clipping, low contrast, ambiguous
      boundaries, and partial occlusion.
- [ ] Partially occluded candidates have visible pixel evidence.
- [ ] No fully occluded control is reconstructed from expected layout or prior
      knowledge.
- [ ] Missing capture metadata is reported without fabricating spatial
      geometry.

## Promotion decision record

- [ ] Schema-valid rate: v1 `____` / v1.1 `____`.
- [ ] Meaningful text recall: v1 `____` / v1.1 `____`.
- [ ] Clipped-fragment precision: v1 `____` / v1.1 `____`.
- [ ] Interaction recall: v1 `____` / v1.1 `____`.
- [ ] Interaction false positives: v1 `____` / v1.1 `____`.
- [ ] Mean matched IoU: v1 `____` / v1.1 `____`.
- [ ] Grounding agreement: v1 `____` / v1.1 `____`.
- [ ] Median and maximum latency: v1 `____` / v1.1 `____`.
- [ ] Timeout count: v1 `____` / v1.1 `____`.
- [ ] All predeclared promotion thresholds passed.
- [ ] Human reviewer decision: keep experimental / revise / promote.

