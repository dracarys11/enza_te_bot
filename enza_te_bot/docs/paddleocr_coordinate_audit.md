# PaddleOCR 3.7.0 coordinate audit

## Scope

This audit uses the OB-001 PNG at
`ai_decisions/observations/screenshots/OBS_20260903052210_calibration_produce_selection.png`.
It examines raw OCR geometry only. No state or action interpretation is used.

The audited baseline initialization is:

```python
PaddleOCR(use_textline_orientation=True, lang="japan")
```

No runtime code was changed during the audit.

## Result

With the pre-fix baseline initialization, `rec_boxes`, `rec_polys`, and
`dt_polys` are expressed in the coordinate space of
`doc_preprocessor_res.output_img`, not the original PNG. The preprocessor keeps
the same width and height but applies a spatial warp, so matching dimensions do
not imply matching coordinates.

- A uniform scale correction is not required and would not solve the mismatch.
- A single x/y offset correction would not solve the mismatch.
- Mapping these coordinates onto the original PNG would require the inverse of
  the document-unwarping transform. That transform is not present in the
  inspected `OCRResult` fields.
- When document orientation classification and unwarping are disabled for the
  audit run, the OCR input image is byte-identical to the original and the
  returned geometry aligns with original-image coordinates.
- `rec_polys` retain quadrilateral geometry and are therefore more precise than
  axis-aligned `rec_boxes` for skewed regions. They do not, however, correct the
  coordinate-space mismatch caused by document unwarping.

## Image and pipeline dimensions

| Item | Observed value |
|---|---:|
| Original PNG dimensions | 1280 × 720 |
| Original decoded array | `(720, 1280, 3)` |
| `doc_preprocessor_res.input_img` | `(720, 1280, 3)` |
| `doc_preprocessor_res.rot_img` | `(720, 1280, 3)` |
| `doc_preprocessor_res.output_img` | `(720, 1280, 3)` |
| `rec_boxes` | `(25, 4)` NumPy array |
| `rec_polys` | 25 NumPy arrays of shape `(4, 2)` |
| `dt_polys` | 25 NumPy arrays of shape `(4, 2)` |

The original decoded image, `input_img`, and `rot_img` were byte-identical.
The reported orientation angle was `0`. The same-size `output_img` was not
byte-identical to the original:

| Comparison | Exact equality | Mean absolute channel difference | Maximum difference |
|---|---:|---:|---:|
| Default `input_img` vs original | yes | 0.000 | 0 |
| Default `rot_img` vs original | yes | 0.000 | 0 |
| Default `output_img` vs original | no | 32.499 | 254 |
| Preprocessing-disabled `output_img` vs original | yes | 0.000 | 0 |

This rules out image-size scaling as the explanation. The changed pixels and
position-dependent coordinate differences identify the document-unwarping
stage as the coordinate-space boundary.

## Coordinate comparison

For comparison, a second audit-only inference disabled document preprocessing:

```python
PaddleOCR(
    use_doc_orientation_classify=False,
    use_doc_unwarping=False,
    use_textline_orientation=True,
    lang="japan",
)
```

The table compares `[x1, y1, x2, y2]` boxes for OCR strings found in both runs.
The second column is the pre-fix default output; the third is the
original-space, preprocessing-disabled output.

| OCR text occurrence | Default `rec_boxes` | Preprocessing disabled | Default minus disabled |
|---|---|---|---|
| `プロデュース選択` #1 | `[0, 0, 231, 33]` | `[51, 21, 252, 50]` | `[-51, -21, -21, -17]` |
| `プロデュース選択` #2 | `[476, 0, 656, 31]` | `[487, 25, 651, 49]` | `[-11, -25, 5, -18]` |
| `W.I.N.G.` | `[801, 208, 1092, 298]` | `[795, 215, 1062, 298]` | `[6, -7, 30, 0]` |
| `~Thanks Flapping Day!!~` | `[845, 571, 1137, 603]` | `[811, 551, 1067, 575]` | `[34, 20, 70, 28]` |
| `G.R` | `[832, 662, 953, 720]` | `[799, 632, 910, 704]` | `[33, 30, 43, 16]` |
| `研修設定` | `[974, 668, 1109, 706]` | `[922, 643, 1041, 676]` | `[52, 25, 68, 30]` |

The displacement changes direction and magnitude across the image. For
example, the first top region moves left/up in the default output, while lower
regions move right/down. This is incompatible with a constant offset. Because
both images have identical dimensions, multiplying by a width or height scale
factor would also leave the mismatch unresolved.

The default geometry spans the full processed-image bounds: its observed
minimum coordinates are `(0, 0)` and its maximum coordinates are `(1280, 720)`.
Those extrema are valid in the processed image but are not evidence that the
same points describe the original PNG.

## `rec_boxes`, `rec_polys`, and `dt_polys`

For all 25 default-run detections:

- Each `rec_box` exactly equals
  `[min(poly.x), min(poly.y), max(poly.x), max(poly.y)]` for its corresponding
  `rec_poly`.
- `rec_polys` and `dt_polys` were array-equal in 25 of 25 positions.
- 10 of 25 `rec_polys` were not identical to an axis-aligned rectangle made
  from the corresponding `rec_box` corners.

Therefore:

- `rec_boxes` are convenient axis-aligned envelopes.
- `rec_polys` are more geometrically accurate when a region is slanted or
  warped because they preserve four individual corners.
- In this sample, `dt_polys` provide no additional geometric precision over
  `rec_polys`; the arrays are identical. In general, `rec_polys` are the
  recognition-aligned collection, while `dt_polys` are the detector output.
- All three collections shared the processed-output coordinate space under the
  pre-fix default initialization.

## Answer to the audit questions

### Do `rec_boxes` need scaling?

No uniform scaling is indicated. The original and processed images are both
1280 × 720. The mismatch is caused by a same-size spatial warp, not by a width
or height scale factor.

### Do `rec_boxes` need offset correction?

No single offset is valid. Differences vary by location and change sign. If
document unwarping remains enabled, an inverse spatial transform is needed to
return geometry to original-image space.

### Are `rec_polys` more accurate?

Yes, for the shape of non-axis-aligned text regions: they retain quadrilateral
corners instead of only an axis-aligned envelope. No, as a remedy for the
coordinate-space issue: the polygons are still relative to the preprocessor's
warped `output_img`.

## Practical implication

For geometry that must overlay the original screenshot, the evidence from
OB-001 supports either:

1. running OCR without document orientation classification and document
   unwarping, or
2. retaining preprocessing and applying its inverse warp before emitting
   original-image coordinates.

This audit does not select or implement either runtime change.

## Resolution

The adapter now disables document orientation classification and document
unwarping. Newly generated Paddle geometry is therefore measured against the
original screenshot pixels; no scale or offset correction was added.
