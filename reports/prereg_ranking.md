# Pre-registration: ranking persistence of active bank stretches

- **Date:** 2026-10-21
- **Status:** fixed before any ranking metric is computed
- **Scope:** a descriptive rank-persistence test. No model is trained, no threshold is tuned, no frozen forecast or evaluation file is changed, and no UI is changed.
- **Required title:** second look at persistence, reported as it comes out.

## Question

Are the 1 km bank stretches that moved outward most strongly in an earlier 10-year period also the stretches that moved outward most strongly in the next, non-overlapping 10-year period?

The output is a ranking test, not a prediction model. A positive result would mean that the earlier ranking retained information about the later ranking on this reach. It would not prove that the same process will continue, and it would not create a forecast.

## Fixed data

This run reads only these measured bank-position files:

| File | SHA-256 |
|---|---|
| `derived/measurements/bank_positions.csv` | `12e931b90eabe499d950e29299a5d291b1ab4acc46632febc5f6a09582937957` |
| `evaluation/observed_bank_positions_2024.csv` | `1c36fa950f643b5b8decdde1a736560ada200876e6592587a3f60b05777af4d6` |
| `evaluation/observed_bank_positions_2025.csv` | `b50477a772bab1c671a4c695bae0c726cfb5d9ec1d2387caee7653d5234d9d67` |
| `evaluation/observed_bank_positions_2026.csv` | `c0771f0ff53330a8532eca0770c2e086a77d288a2135c5bf22a29a7d9ad9b626` |

The first file supplies 1989–2023 and the other three supply 2024–2026. They are concatenated into one yearly bank-position table. The transect geometry, normals, outward signs, flags, curvature and nominal observation dates come from these files.

No frozen forecast, `final_eval*` file, model artifact or evaluation metric is read for any number in this report. The 2024–2026 positions are inputs to this descriptive measurement; they do not change the frozen model or its scores.

## Prior exposure

This is a second look, not a blind test. The 2025 and 2026 observations were already examined during the origin-2024 second look, and all earlier years were used in the historical and model work. Split 5 therefore has no untouched outcome period. No split in this analysis is a prospective test, and the result is descriptive evidence about this reach, not out-of-sample proof.

## Units

- **Primary:** 1 km bank stretch = three consecutive transects on one bank side. The fixed groups are transects 1–3, 4–6, …, 73–75 on the left bank, then the same groups on the right bank. This gives 50 stretches (25 per side).
- **Secondary:** a single transect on one bank side. This gives 150 transect units.

The stretch is the unit for the pre-registered success rule. The transect-level result is secondary and cannot change the pass/fail decision.

## Clean observation rule

A yearly bank observation is usable only when all of the following hold:

1. `valid_bank` is true.
2. Its `flags` field parses to an empty list. Any flag, including `center_outside_river`, `multiple_crossings`, `border_transect`, `width_below_min`, `missing_bank` or `high_bank_curvature`, makes that observation unusable.
3. The year is not 1997. The 1997 mask is absent; no interpolation or synthetic 1997 row is allowed.

No flag is repaired, dropped selectively, or treated as zero movement. No missing year is filled. No endpoint is replaced by a nearby year.

## Fixed periods

A period is 10 calendar years counted inclusively. Its activity uses the first and last year only; the eight years between them are not used for the rate. Period B starts in the year immediately after A ends, so A and B never share a year.

| Split | Period A | Period B |
|---:|---|---|
| 1 | 1989–1998 | 1999–2008 |
| 2 | 1994–2003 | 2004–2013 |
| 3 | 1999–2008 | 2009–2018 |
| 4 | 2004–2013 | 2014–2023 |
| 5 | 2007–2016 | 2017–2026 |

The five pairs overlap heavily. For example, 1999–2008 is period B in split 1 and period A in split 3. The five results are therefore not independent evidence, and the report must say so plainly.

## Activity

For a usable transect with usable observations at both endpoints of a period:

1. Take the bank displacement vector from the first year to the last year.
2. Project it onto the first year's transect normal.
3. Multiply by the first year's outward sign. Positive means outward movement into land (erosion); negative means inward movement (accretion).
4. Divide by the elapsed years from the two stored nominal observation dates: `(end_date - start_date).days / 365.25`.

The formula is:

`activity = ((x_end - x_start) * normal_x + (y_end - y_start) * normal_y) * outward_sign / elapsed_years`

The normal and outward sign are constant for a transect in this data set, so this is also the change in outward bank distance divided by elapsed time. A period's activity is in metres per year.

For a stretch, activity is the unweighted mean of the usable transect activities in that stretch. A stretch is included when at least one of its three transects has usable endpoints. The number of contributing transects is reported. A transect or stretch with no usable endpoint pair is missing, not zero. The stretch is still identified by its full three-transect geometry; incomplete contributing transects are a limitation, not a repair.

At the transect level, the same per-transect activity is used without stretch aggregation.

## Rankers

There are three rankers for the primary stretch analysis:

1. **A activity.** Rank stretches by A activity from highest outward rate to lowest. This is the ranking examined by the map question.
2. **Random.** Permute the A activity values across the common stretches 1,000 times. Each permutation is a random ranking. This is the null band, not a scientific competitor.
3. **Curvature only.** At the last year of A, take the absolute centreline curvature `abs(curvature_1_m)` for each of the stretch's three transects. Rank stretches by the mean absolute curvature from highest to lowest. Curvature is read from the A-end year and does not use B movement.

All rankers are applied only to stretches with both A and B activity available. The number of common stretches is reported for every split. Curvature is not filtered by bank flags; it is centreline geometry. If any of a stretch's three curvature values is non-finite, the mean uses the finite values; if none is finite, the curvature ranker is missing for that stretch.

Ties in A activity or curvature are broken by one fixed random tie order generated with seed 42. The same tie order is used for both rankers. This avoids systematically favouring the left bank or the first transect.

## Metrics per split

For the primary stretch analysis:

- **Spearman rank correlation** between A activity and B activity over the common stretches. The correlation is descriptive; no p-value is used for the success rule.
- **Top-20% set size:** `k = ceil(0.20 * n)`, where `n` is the number of common stretches. For all 50 stretches this is 10.
- **Top-20% overlap:** `|A_top ∩ B_top| / k`. This is the share of the earlier top set that is also in the later top set. It is not the share of all stretches.
- **Lift:** `overlap / 0.20`. Under a random ranking the expected overlap is 0.20, so the expected lift is 1.0. The maximum lift is 5.0 because the overlap share cannot exceed 1.0. This definition is fixed so that a lift of 1.5 is possible; defining overlap as a fraction of all stretches would make a lift of 1.5 impossible.

The top set for B is always formed from B activity. For a ranker other than A activity, its top set is compared with that same B top set.

The same overlap and lift definitions are used for the curvature ranker and for the transect-level secondary result.

## Uncertainty

### Split-level rank metrics

The 90% interval for Spearman and lift uses a spatial block bootstrap over blocks of five consecutive stretches:

- The 50 stretches are ordered left-bank groups 1–3 through 73–75, then right-bank groups 1–3 through 73–75.
- Consecutive groups of five stretches form 10 fixed blocks. Blocks do not cross the left/right boundary.
- Each bootstrap replicate samples 10 blocks with replacement, concatenates their five-stretch rows, drops rows with missing A or B activity, and recomputes Spearman and lift.
- `k` is recomputed for the resampled number of common stretches.
- Replicates with fewer than four common stretches are discarded.
- The run uses 1,000 replicates, seed 42, and the 5th and 95th percentiles as the 90% interval.

This interval describes spatial block uncertainty on this reach. It does not make the overlapping split pairs independent.

### Random band

For each split, 1,000 random permutations are used. The random lift band is the 5th–95th percentile of those permutation lifts. The random Spearman band is reported the same way. A single random generator seeded at 42 is used, with splits processed in the fixed table order.

### Per-stretch interval including zero

A per-stretch 90% interval is estimated by resampling the usable transect activities within that stretch and period with replacement. Each stretch-period uses 1,000 bootstrap means when at least two transects contribute; a stretch-period with one contributing transect has no interval. The 5th and 95th percentiles form the interval. This interval is within-stretch and descriptive only; it is not the spatial block-bootstrap interval and is not used in the success rule. It is reported as `interval_includes_zero` and summarized as the share of stretches with a defined interval that includes zero in each period.

This is an assumption about the meaning of the requested “share of stretches whose interval includes zero”: with at most three transects inside a stretch, the transect replicates are the only within-stretch sample available. The split-level block bootstrap remains the required uncertainty for Spearman and lift.

## Secondary transect-level result

The transect-level result repeats A/B Spearman, top-20% overlap and lift using individual transects as units. It has no block bootstrap and no random band, because transects are not independent spatial blocks at the 1 km scale. It is reported as a sensitivity check only and cannot change the success rule.

## Fixed success rule

The result is a **pass** only when both conditions hold:

1. The primary A-activity lift is at least **1.5** in at least **4 of the 5 splits**; and
2. The primary A-activity Spearman 90% block-bootstrap interval excludes zero in at least **4 of the 5 splits**.

For this persistence test, “excludes zero” is fixed as the lower bound being greater than zero. An interval that includes zero, lies wholly below zero, or is undefined does not count; a wholly negative interval would be a reversal, not persistence. If fewer than four splits have a usable interval, the rule cannot pass.

The transect-level result, curvature ranker and random band are reported but do not alter this rule.

## Outputs

The run writes exactly these result files:

- `reports/ranking_persistence.json`: input hashes, split definitions, usable counts, all stretch-period activities and intervals, primary metrics, bootstrap draws summary, random band, curvature metrics, transect-level metrics, success decision and limitations.
- `reports/ranking_persistence.png`: five A-versus-B scatter panels, one per split, plus a lift panel showing A lift, curvature lift, the random 90% band and the 1.5 threshold.

The script must write the JSON and PNG from the same in-memory results. Every reported number must be in the JSON, including the numbers printed in the figure labels, so the figure can be checked without rerunning the calculation.

After the run, a plain-language entry is appended to `reports/DECISIONS.md`. The entry records the design, the observed result and the limits. It must not rewrite an earlier decision.

## Stop conditions

Stop and report without inventing a result if any input hash differs, a required column is missing, every split has no common stretches, or the output files cannot be written. A single split with no common stretches is reported as not evaluable and counts as a failure in the success rule; it does not block the other four splits. Do not change this pre-registration after the run. Do not modify frozen forecasts, `final_eval*` files, models, or the UI.
