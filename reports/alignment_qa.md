# Alignment and consistency QA

Three independent passes were run.

## Pass 1 — metadata and class audit

See `validation/qa_pass1.json` and `reports/water_mask_audit.md`. All 34 historical rasters share EPSG:32646, a 30 m pixel, a 355×478 grid and the same affine transform. Band 1 is water and band 2 is valid; the valid footprint is constant to within 2 pixels.

## Pass 2 — overlay and edge audit

Contact sheet: `processed/qa/river_contact_sheet.png`. Pair overlays are in `processed/qa/pair_overlay_*.png`.

| Pair | Area change | IoU | Centroid shift (m) | Flags |
|---|---:|---:|---:|---|
| 1989→1990 | -11.4% | 0.748 | 120.2 | none |
| 1990→1991 | -6.9% | 0.682 | 167.3 | centroid_shift_over_150m, iou_below_0_7 |
| 1991→1992 | +26.0% | 0.609 | 489.6 | centroid_shift_over_150m, iou_below_0_7 |
| 1992→1993 | -20.1% | 0.703 | 457.3 | centroid_shift_over_150m |
| 1993→1994 | +4.8% | 0.774 | 101.3 | none |
| 1994→1995 | -6.0% | 0.816 | 134.8 | none |
| 1995→1996 | +22.1% | 0.671 | 171.3 | centroid_shift_over_150m, iou_below_0_7 |
| 1996→1998 | -3.3% | 0.642 | 182.3 | centroid_shift_over_150m, iou_below_0_7 |
| 1998→1999 | +4.8% | 0.848 | 80.1 | none |
| 1999→2000 | +1.0% | 0.817 | 291.4 | centroid_shift_over_150m |
| 2000→2001 | +2.6% | 0.810 | 90.9 | none |
| 2001→2002 | -9.2% | 0.839 | 332.0 | centroid_shift_over_150m |
| 2002→2003 | +2.7% | 0.924 | 21.4 | none |
| 2003→2004 | +4.6% | 0.849 | 133.6 | none |
| 2004→2005 | -3.8% | 0.854 | 173.4 | centroid_shift_over_150m |
| 2005→2006 | -1.7% | 0.909 | 6.9 | none |
| 2006→2007 | -4.6% | 0.901 | 52.0 | none |
| 2007→2008 | +6.9% | 0.808 | 102.5 | none |
| 2008→2009 | -6.7% | 0.830 | 75.8 | none |
| 2009→2010 | +6.1% | 0.843 | 304.9 | centroid_shift_over_150m |
| 2010→2011 | -5.9% | 0.832 | 259.9 | centroid_shift_over_150m |
| 2011→2012 | +4.6% | 0.846 | 65.4 | none |
| 2012→2013 | -19.6% | 0.775 | 616.5 | centroid_shift_over_150m |
| 2013→2014 | -0.3% | 0.926 | 24.9 | none |
| 2014→2015 | -6.9% | 0.889 | 120.9 | none |
| 2015→2016 | -0.4% | 0.910 | 96.0 | none |
| 2016→2017 | +0.0% | 0.905 | 32.2 | none |
| 2017→2018 | +7.6% | 0.856 | 12.8 | none |
| 2018→2019 | -8.4% | 0.874 | 81.2 | none |
| 2019→2020 | -1.2% | 0.899 | 35.4 | none |
| 2020→2021 | -1.4% | 0.881 | 28.2 | none |
| 2021→2022 | +3.4% | 0.919 | 61.9 | none |
| 2022→2023 | -2.8% | 0.932 | 30.5 | none |

Flagged pairs: 11. All flags are centroid/IoU warnings; no pair exceeds the 30% area-change threshold. A ±6 px grid search maximizing IoU was run on each flagged pair to test for a systematic shift. The best shifts are shown below; these are descriptive shape diagnostics, not a geometric correction.

| Flagged pair | Best shift (row, col) px | IoU at best shift |
|---|---:|---:|
| 1990→1991 | (0, 0) | 0.682 |
| 1991→1992 | (0, 0) | 0.609 |
| 1992→1993 | (0, 0) | 0.703 |
| 1995→1996 | (0, 0) | 0.671 |
| 1996→1998 | (-1, 0) | 0.647 |
| 1999→2000 | (0, 0) | 0.817 |
| 2001→2002 | (0, 0) | 0.839 |
| 2004→2005 | (0, 0) | 0.854 |
| 2009→2010 | (0, 0) | 0.843 |
| 2010→2011 | (0, 0) | 0.832 |
| 2012→2013 | (0, 0) | 0.775 |

## Pass 3 — quantitative consistency

- Recomputed masks match saved masks for every year: True
- All polygons valid: True
- All selected pixels are valid water: True
- Excluded water disjoint from selected river: True
- Excluded water subset of water mask: True
- Selected river + excluded water equals water mask: True
- Maximum polygon-vs-mask area difference: 0.0 m²
- Polygon repairs: {'1993': True, '1994': True, '1998': True, '1999': True, '2000': True, '2002': True, '2004': True, '2005': True, '2007': True, '2008': True, '2009': True, '2015': True, '2016': True, '2017': True, '2019': True, '2020': True, '2021': True, '2022': True, '2023': True}

The recomputation uses the saved historical core and the same extraction rule; it is an independent read of the original masks, not a copy of the processed file. No repeated transformation was applied because every historical raster was already on the canonical grid.
