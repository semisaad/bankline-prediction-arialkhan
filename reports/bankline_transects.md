# Bankline and transect construction (training period)

- Reference year for fixed transects: 2023 (last pre-cutoff observation).
- Spacing along the channel: 360 m (12 pixels).
- Transects: 75.
- Bank-position rows: 5100 (4507 valid single-bank rows).

Transects are perpendicular to a pruned 2023 channel skeleton and are fixed for every historical observation. Each transect has a left (`L`) and right (`R`) bank. The normal points from the channel to the left bank when facing downstream. A bank point is the outermost intersection of the transect with the selected river polygon on that side. This preserves the outer bank of the river corridor if a side channel or island is present, and the extra crossings are flagged.

## Sign convention

Positive signed displacement means the bank moved **outward**, away from the channel and into land: **erosion**. Negative means the bank moved **inward**, toward the channel: **accretion**. The same convention is applied to left and right banks.

## Quality flags

| Flag | Rows |
|---|---:|
| border_transect | 272 |
| center_outside_river | 1654 |
| high_bank_curvature | 1 |
| missing_bank | 593 |
| multiple_crossings | 550 |
| width_below_min | 42 |

Width summary (m): min 6.7, median 255.0, max 781.7.

Missing banks, multiple crossings, centres outside the river and implausibly narrow widths are retained in the raw table and flagged. They are excluded from model labels later.
