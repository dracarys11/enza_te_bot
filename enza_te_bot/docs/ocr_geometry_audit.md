# OB-001 OCR geometry calibration experiment

## Scope

This experiment compares raw geometry from:

- `test_data/ob001/paddle_raw.json`
- `test_data/ob001/gemini_raw.json`
- `ai_decisions/observations/screenshots/OBS_20260903052210_calibration_produce_selection.png`

The stored Paddle artifact contains the axis-aligned boxes derived from
`rec_boxes`. Because it does not contain polygons, `rec_polys` and `dt_polys`
were collected by rerunning PaddleOCR 3.7.0 on the same screenshot with the
pre-fix baseline configuration:

```python
PaddleOCR(use_textline_orientation=True, lang="japan")
```

The rerun produced the same 25 recognized strings in the same order, and all
25 rerun `rec_boxes` matched the boxes represented in `paddle_raw.json`.
No runtime code was modified.

## Method

Paddle and Gemini regions were paired only when both their exact text and that
text's occurrence number matched. No fuzzy text matching was used. This gave
17 paired regions from 25 Paddle text regions and 21 Gemini text regions.

Gemini boxes use `[x, y, width, height]`. Paddle `rec_boxes` use
`[x1, y1, x2, y2]`. All measurements below convert them to a common geometry.

For each pair, the experiment measured:

- rectangle IoU between `rec_boxes` and the Gemini bbox;
- convex-polygon IoU between `rec_polys` or `dt_polys` and the Gemini bbox;
- Euclidean distance between region centers in pixels;
- center offset `(Paddle center - Gemini center)`;
- Paddle/Gemini width and height ratios using each Paddle field's envelope.

A global scale-and-offset calibration was also fitted independently per axis:

```text
Paddle center x = scale_x * Gemini center x + offset_x
Paddle center y = scale_y * Gemini center y + offset_y
```

Gemini bboxes are an independent visual estimate, not pixel-level ground
truth. IoU differences smaller than the uncertainty of those boxes should not
be interpreted as detector quality rankings. The original screenshot and the
Paddle preprocessing arrays provide the coordinate-space evidence.

## Input dimensions and coordinate spaces

| Item | Observed shape |
|---|---:|
| Original screenshot | 1280 × 720 |
| Original decoded array | `(720, 1280, 3)` |
| Paddle `input_img` | `(720, 1280, 3)` |
| Paddle preprocessor `output_img` | `(720, 1280, 3)` |

Although the dimensions are unchanged, the default preprocessor output is not
the original image. Direct array comparison found:

- `input_img` equals the original decoded screenshot exactly;
- the reported orientation angle is `0`;
- `output_img` does not equal the original screenshot;
- mean absolute channel difference is `32.499`, with a maximum of `254`.

Therefore, the default OCR geometry is measured on a same-size spatially
warped image. Equal dimensions and coordinates within `[0,1280] × [0,720]` do
not establish original-image coordinates.

## Aggregate comparison with Gemini bboxes

| Paddle field | Mean IoU | Median IoU | IoU range | Mean center distance | Median center distance | Maximum center distance |
|---|---:|---:|---:|---:|---:|---:|
| `rec_boxes` | 0.305 | 0.242 | 0.052–0.697 | 33.35 px | 26.17 px | 80.51 px |
| `rec_polys` | 0.301 | 0.224 | 0.052–0.692 | 33.34 px | 26.00 px | 80.65 px |
| `dt_polys` | 0.301 | 0.224 | 0.052–0.692 | 33.34 px | 26.00 px | 80.65 px |

The nearly identical polygon metrics are expected: all 25 `rec_polys` were
array-equal to their corresponding `dt_polys` in this run.

Every `rec_box` was also exactly the axis-aligned envelope of its corresponding
`rec_poly`:

```text
[min(poly.x), min(poly.y), max(poly.x), max(poly.y)]
```

The small IoU difference between `rec_boxes` and polygons is caused by the
rectangle including pixels outside a slanted quadrilateral. It does not
indicate a different coordinate system.

## Offset and scale measurements

Across the 17 exact-text pairs, using `rec_boxes` centers and envelopes:

| Measurement | Result |
|---|---:|
| Mean x offset | +12.85 px |
| x offset range | -77.0 to +56.0 px |
| Mean y offset | -4.15 px |
| y offset range | -24.5 to +27.0 px |
| Mean width ratio | 1.014 |
| Mean height ratio | 1.111 |

The wide offset ranges and sign changes rule out a constant x/y correction.
Mean ratios close to one also hide location-dependent deformation and do not
support a single uniform scale correction.

The best independent linear center fit was:

| Axis | Scale | Offset | Fit RMSE |
|---|---:|---:|---:|
| x | 1.0973 | -63.80 px | 16.53 px |
| y | 1.0818 | -26.40 px | 2.40 px |

The non-unit fitted scales and residual error show that a global
scale-and-offset approximation cannot recover the original geometry exactly.
In particular, the x residual remains material after fitting.

## Representative pairs

Boxes below use `[x1, y1, x2, y2]` after normalization.

| OCR text occurrence | Paddle `rec_box` | Gemini bbox | IoU | Center distance |
|---|---|---|---:|---:|
| `プロデュース選択` #1 | `[0, 0, 231, 33]` | `[52, 24, 333, 56]` | 0.107 | 80.51 px |
| `プロデュース選択` #2 | `[476, 0, 656, 31]` | `[488, 27, 665, 52]` | 0.072 | 26.20 px |
| `W.I.N.G.` | `[801, 208, 1092, 298]` | `[738, 224, 1111, 290]` | 0.608 | 22.36 px |
| `W.I.N.G.編` | `[201, 375, 347, 407]` | `[225, 371, 366, 402]` | 0.573 | 21.97 px |
| `283プロダクション` | `[897, 479, 1093, 508]` | `[868, 468, 1046, 492]` | 0.242 | 40.33 px |
| `研修設定` | `[974, 668, 1109, 706]` | `[923, 643, 1049, 677]` | 0.077 | 61.72 px |

The displacement changes with image position. Upper regions are displaced
upward and may move left, while lower regions are displaced downward and to
the right. This pattern is consistent with the observed preprocessor warp, not
with a simple resize or translation.

## Which Paddle field matches original-image space?

None of the three fields from the pre-fix default run can be treated as
original-image coordinates:

- `rec_boxes` are axis-aligned envelopes in preprocessor-output space.
- `rec_polys` retain more precise quadrilateral geometry, but in the same
  preprocessor-output space.
- `dt_polys` are identical to `rec_polys` for all 25 OB-001 detections and use
  the same space.

`rec_polys` are the most precise field for the shape of a non-axis-aligned
region, but they are not more correct with respect to the original screenshot
coordinate system.

The related preprocessing-disabled control documented in
`docs/paddleocr_coordinate_audit.md` produced an `output_img` byte-identical to
the original and geometry aligned with the original image. The present
experiment confirms that choosing among `rec_boxes`, `rec_polys`, and
`dt_polys` cannot by itself correct the default preprocessor's coordinate
transform.

## Conclusion

For the pre-fix default OB-001 PaddleOCR 3.7.0 run:

1. no Paddle coordinate field directly matches original-image space;
2. no uniform scaling is required or sufficient;
3. no fixed offset is valid;
4. `rec_polys` preserve shape better than `rec_boxes`, but share the same
   transformed coordinate space;
5. original-image geometry requires either an inverse preprocessor transform
   or OCR inference without the document-warping stage.

This experiment records the geometry evidence only and makes no runtime
change.

## Resolution

The Paddle adapter now disables document orientation classification and
document unwarping. The regenerated OB-001 `paddle_raw.json` contains geometry
in original-screenshot space; no bbox scaling, fixed offset, or Gemini-based
coordinate correction was introduced.
