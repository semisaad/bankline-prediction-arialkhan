# Main-river extraction (training period)

The masks contain the river plus detached ponds and small wet slivers. The extraction is an explicit two-stage rule based only on 1989–2023 observations:

1. Build a persistent-water **core** from the fraction of historical years in which each valid pixel is water (threshold 0.20). Keep the largest 8-connected core component (the river network).
2. In each year, label all 8-connected water components. Select the component with the largest overlap with the core (the anchor). Also select a detached component only if it overlaps the core substantially (at least 20 px and 10% of its own area) or is within 2 px of the anchor and is elongated. All other components are excluded and retained in the diagnostic layer.

The largest-component rule is not used by itself. It is only a fallback if no component overlaps the historical core, and that fallback is flagged.

- Historical years used: 1989–2023 (34 observations)
- Core pixels: 22723
- Main core component: 13170 px
- Median selected river area: 8156 px (7.341 km²)

## Per-year selection

| Year | Selected px | Excluded px | Components selected | Anchor fallback | Flags |
|---:|---:|---:|---:|---|---|
| 1989 | 8896 | 8327 | 3 | False | multiple_selected_components |
| 1990 | 7879 | 8193 | 2 | False | multiple_selected_components |
| 1991 | 7332 | 5403 | 2 | False | multiple_selected_components |
| 1992 | 9236 | 6989 | 3 | False | multiple_selected_components |
| 1993 | 7382 | 5952 | 1 | False | none |
| 1994 | 7734 | 3324 | 1 | False | none |
| 1995 | 7268 | 2345 | 2 | False | multiple_selected_components |
| 1996 | 8876 | 6014 | 3 | False | multiple_selected_components |
| 1998 | 8581 | 2583 | 1 | False | none |
| 1999 | 8989 | 3294 | 1 | False | none |
| 2000 | 9078 | 8442 | 1 | False | none |
| 2001 | 9310 | 14288 | 2 | False | multiple_selected_components |
| 2002 | 8451 | 5764 | 1 | False | none |
| 2003 | 8676 | 3262 | 1 | False | none |
| 2004 | 9074 | 12374 | 1 | False | none |
| 2005 | 8729 | 2192 | 1 | False | none |
| 2006 | 8580 | 5023 | 1 | False | none |
| 2007 | 8182 | 3631 | 1 | False | none |
| 2008 | 8747 | 9896 | 1 | False | none |
| 2009 | 8165 | 2893 | 1 | False | none |
| 2010 | 8661 | 14747 | 2 | False | multiple_selected_components |
| 2011 | 8148 | 7524 | 3 | False | multiple_selected_components |
| 2012 | 8523 | 10530 | 2 | False | multiple_selected_components |
| 2013 | 6854 | 5327 | 2 | False | multiple_selected_components |
| 2014 | 6831 | 4087 | 2 | False | multiple_selected_components |
| 2015 | 6359 | 4053 | 1 | False | none |
| 2016 | 6332 | 2422 | 1 | False | none |
| 2017 | 6335 | 2497 | 1 | False | none |
| 2018 | 6816 | 2342 | 2 | False | multiple_selected_components |
| 2019 | 6241 | 2878 | 1 | False | none |
| 2020 | 6167 | 4346 | 1 | False | none |
| 2021 | 6079 | 2511 | 1 | False | none |
| 2022 | 6285 | 3208 | 1 | False | none |
| 2023 | 6110 | 1333 | 1 | False | none |

## Interpretation and limits

- Connected side channels and braided water are kept because they are part of the anchor component. Detached oxbows/channel fragments that retain a strong overlap with the historical core are kept as separate selected components; this is recorded per year.
- Detached ponds are excluded even when they are large. The excluded layer is saved for every year so a reviewer can inspect what was removed.
- If two water systems are joined by flooding in one year, the 8-connected anchor can include the joined water. Such a year is flagged by an area jump; the joined water is not silently relabelled as a separate pond.
- The extraction configuration is fixed before any 2024–2026 raster is opened.
