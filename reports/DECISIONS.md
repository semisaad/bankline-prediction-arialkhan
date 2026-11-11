# Decision Log

Append-only. Each entry records a choice that affects the numbers, method, or claims. If a choice changes, add a new superseding entry; do not rewrite the old one.

## 1. Keep the new application separate from RiverGuard

- **Date:** 2026-10-20
- **Decision:** Build the database, API, and user interface inside `/media/saad/HDD/rivererosionaccretion` and do not modify `/media/saad/HDD/riverguard`.
- **Reason:** RiverGuard is an existing working project. Reusing its code or processed outputs could change its results and would mix two different data contracts.
- **Rejected:** Adding pages to RiverGuard or importing its outputs into the new application.
- **Impact:** The new app is self-contained. It uses only the frozen forecast and evaluation files from this project.

## 2. Lock the 2024-2026 test years until the forecast is frozen

- **Date:** 2026-10-20
- **Decision:** Do not open the 2024, 2025, or 2026 rasters for training, tuning, or method selection. Access them only after `forecasts/frozen/manifest.json` and `READY` exist.
- **Reason:** A test period is only useful if it cannot influence the model. Opening it early would make the reported test numbers optimistic.
- **Rejected:** Using the test years in cross-validation or checking them repeatedly while tuning.
- **Impact:** The frozen forecast was created from data through 2023. The test years were opened only for the post-freeze evaluation. The forecast must not be regenerated now.

## 3. Use the source raster grid without reprojection

- **Date:** 2026-10-20
- **Decision:** Keep the supplied EPSG:32646 grid, 30 m pixels, 355 x 478 cells, and transform `[30, 0, 209970, 0, -30, 2575320]`.
- **Reason:** All 37 source masks already share this grid. Reprojecting would resample the water masks and create artificial boundary movement.
- **Rejected:** Reprojecting to another CRS, resampling to a round extent, or clipping to a vector boundary.
- **Impact:** Pixel areas are 900 m². Transect distances are measured in metres on this grid. Off-grid rasters would fail the input check rather than being silently warped.

## 4. Treat band 1 as water and band 2 as valid

- **Date:** 2026-10-20
- **Decision:** Water is stored in band 1; valid pixels are stored in band 2; value 255 means true. The source files have no nodata tag.
- **Reason:** This is the actual encoding in the supplied GeoTIFFs. Guessing from filenames or assuming a single-band mask would invert or delete data.
- **Rejected:** Treating 0 as water, treating 255 as nodata, or inferring valid area from band 1 alone.
- **Impact:** Every extraction and QA check uses this encoding. A mismatch is treated as a hard error.

## 5. Assume a nominal 25 March date

- **Date:** 2026-10-20
- **Decision:** Use `YYYY-03-25` as the nominal observation date and calculate elapsed days from those dates.
- **Reason:** Filenames contain only a year. The export description says a dry-season composite from 1 January to 25 March, but individual scene dates are not stored.
- **Rejected:** Pretending the date is 1 January, treating each year as exactly 365 days, or inventing mid-season dates.
- **Impact:** Rates use nominal elapsed time. The 1997 gap creates a genuine 730-day interval. This is an assumption and must be stated in reports.

## 6. Extract the main river from a persistent-water core

- **Date:** 2026-10-20
- **Decision:** Build a 1989-2023 water-occurrence core at a 0.20 threshold, keep the largest connected core component, and select the river component in each year by overlap with that core.
- **Reason:** The mask includes ponds, canals, and other water. A fixed spatial core separates the main river from most false positives.
- **Rejected:** Taking all water pixels, using the largest water component alone, or hand-drawing a river polygon.
- **Impact:** Historical selected area has a median of 8,156.5 pixels (7.34 km²). The 2023 area is 6,110 pixels. Border clipping can still cut the river at the image edge.

## 7. Use 75 fixed transects at 360 m spacing

- **Date:** 2026-10-20
- **Decision:** Use a 2023 skeleton centerline with 12-pixel (360 m) spacing, a minimum width of 60 m, and bank search up to 400 m. This supersedes the earlier draft spacing of 18 pixels (540 m).
- **Reason:** The 540 m spacing produced 45 transects and missed bends and short transition zones. The 360 m spacing gives 75 transects while keeping the bank points separated enough to limit overlap.
- **Rejected:** 540 m spacing, a 30 m minimum width, or spacing based on a single year's water polygon.
- **Impact:** The geometry stage produced 75 transects, 150 bank sides, and 5,100 bank rows. Measurements, dataset features, validation, and forecasts all use this geometry.

## 8. Use the outermost valid bank crossings

- **Date:** 2026-10-20
- **Decision:** For each transect, take the first water-to-land crossing on each side from the centerline. If the center is outside the selected polygon, choose the nearest valid bank pair. Use border transects as-is with a flag.
- **Reason:** On a wide or braided channel, taking every crossing would mix in islands. The outermost bank is the stable definition of the channel edge.
- **Rejected:** Averaging all crossings, taking the innermost crossing, or dropping every transect that touches the border.
- **Impact:** Bank positions carry `border_transect`, `center_outside`, `multiple_crossings`, `high_curvature`, `missing_bank`, or `width_below_min` flags. Flagged origins are not used for training; flagged test banks are excluded from metrics.

## 9. Define positive displacement as erosion

- **Date:** 2026-10-20
- **Decision:** Positive bank displacement means outward movement from the centerline (erosion). Negative means inward movement (accretion). Values within 15 m are low movement.
- **Reason:** The sign must match the application's labels and the map colours. A mixed convention would invert the meaning of erosion and accretion.
- **Rejected:** Positive-inward, using absolute displacement only, or treating low movement as a zero target.
- **Impact:** Forecast classes use the same rule. The 15 m tolerance is half a 30 m pixel and is recorded in the frozen summary.

## 10. Bound plausible movement and change patches

- **Date:** 2026-10-20
- **Decision:** Mark measured displacement above 150 m as implausible and exclude it from training and evaluation. Remove change-map patches smaller than 2 pixels. Do not allow intervals longer than 5 years.
- **Reason:** A 150 m move is five pixels in one interval and is often a false bank match. Tiny patches are usually mask noise. The 5-year limit prevents long gaps from dominating rates.
- **Rejected:** Keeping every raw difference, smoothing the masks, or filling the 1997 gap with an interpolation.
- **Impact:** The measurement table has 4,950 interval rows; 3,163 are good, 1,013 flagged, 646 invalid, and 128 implausible. The 1997 gap remains a two-year interval.

## 11. Train only on features known at the forecast origin

- **Date:** 2026-10-20
- **Decision:** Use 20 origin-only features from the current and previous bank positions. Exclude transect ID, reach, along-channel distance, coordinates, forecast-year values, and target labels.
- **Reason:** Using future bank positions or a target-derived feature would leak the answer into training and make backtest scores invalid.
- **Rejected:** Including future widths, future centerline positions, or using transect identity as a numeric feature.
- **Impact:** The dataset has 13,950 rows, 8,425 usable rows, and 450 forecast rows. Leakage checks pass. Forecast features have no label-quality or training-only columns.

## 12. Require both low-movement and directional skill

- **Date:** 2026-10-20
- **Decision:** A model is eligible only if directional accuracy on movement beyond 15 m is at least 0.55 and low-movement F1 is at least 0.70. Rank eligible models by mean rank over MAE, RMSE, low-movement F1, and directional accuracy. Break ties on higher directional accuracy, then lower RMSE, then lower MAE.
- **Reason:** A model that predicts "no movement" everywhere can have good MAE and low-movement F1 but has no directional skill. The gates prevent choosing that kind of model.
- **Rejected:** Selecting on MAE alone, selecting on a single fold, or using the test years to choose a model.
- **Impact:** Ridge and RandomForest passed the gates with mean rank 1.5 each. RandomForest won the directional tie-break (0.648 vs 0.589) and was frozen for all three horizons.

## 13. Freeze the forecast with hashes before evaluation

- **Date:** 2026-10-20
- **Decision:** Write 15 frozen files, a manifest with a SHA-256 for every file, and a `READY` file containing the manifest hash. The model, config, dataset, forecast features, and metadata hashes are recorded in the manifest.
- **Reason:** A forecast without provenance can be changed after seeing test results. The hashes make that visible.
- **Rejected:** Saving only the latest CSV, storing the forecast in a database without a file hash, or relying on file modification times.
- **Impact:** `READY` is `d113c99da9fed2270dd2dd4892c6812d5aa5b907f0f4b5e4ff42274886f72f98`. The API verifies all frozen files and key inputs on `/api/health/`.

## 14. Do not retune after opening the test years

- **Date:** 2026-10-20
- **Decision:** Keep the frozen RandomForest unchanged even though the zero-change baseline has lower test MAE. Report the weaker result and the event-capture failure plainly.
- **Reason:** Changing the model after seeing 2024-2026 would turn the test period into training data and invalidate the evaluation.
- **Rejected:** Switching to the zero baseline for the interface, retraining on test years, changing the 15 m tolerance, or hiding the baseline result.
- **Impact:** On 398 good pairs, the frozen model has MAE 9.15 m versus 5.82 m for zero change. It captures 3 of 22 erosion events and 2 of 42 accretion events. The UI shows this trade-off and does not claim the model is more accurate than the baseline.

## 15. Correct the evaluation flag parser and rerun

- **Date:** 2026-10-20
- **Decision:** Make `_parse_flags()` accept in-memory lists, tuples, and sets as well as JSON strings, then rerun the evaluation.
- **Reason:** The first evaluation counted flagged bank rows as good because flags loaded from memory were not parsed. That inflated the good-pair count and hid exclusion problems.
- **Rejected:** Leaving the first evaluation numbers, or manually deleting flagged rows without fixing the parser.
- **Impact:** The corrected evaluation has 398 good pairs and 52 flagged or invalid pairs. The frozen forecast was not changed. The overlay IoU shift audit and the geometry QA were also completed before this rerun.

## 16. Serve only local frozen artifacts through a small API

- **Date:** 2026-10-20
- **Decision:** Build a Django API that reads frozen GeoJSON/CSV-derived JSON and evaluation JSON from disk. Do not read Landsat rasters at request time. Use a React map for the forecast and observed banks.
- **Reason:** The UI should show exactly the frozen forecast and the post-freeze evaluation, not a live recomputation that could drift. The API also stays fast and does not depend on raster libraries.
- **Rejected:** A GIS server that renders rasters per request, a database copy of the forecast, or a frontend that reads local files directly.
- **Impact:** The five API endpoints are `/api/health/`, `/api/forecast/summary/`, `/api/forecast/maps/?year=YYYY`, `/api/forecast/metrics/`, and `/api/forecast/data-quality/`. Observed test banks are served from `evaluation/observed_banklines_YYYY.geojson`.

## 17. Do not promote the v2 model without a leak-free win

- **Date:** 2026-10-21
- **Decision:** Keep the frozen v1 RandomForest as the only forecast model. Do not replace it with the v2 neighbour/history/two-stage models, because no v2 variant beat the zero/median baseline under a leak-free selection rule.
- **Reason:** V2 added 19 neighbour/reach features, 15 long-history features, and 10 river-area features. The best classifier reached AUC 0.672. A post-hoc gate at probability 0.70 reached MAE 17.292 m versus 17.320 m for zero, but it used only 2.7% of moving banks, had directional accuracy 0.038, and the 0.028 m gain is too small to be meaningful. When the threshold was chosen only from earlier out-of-sample folds, MAE was 17.364 m, worse than zero. A two-stage HGB model at threshold 0.80 had MAE 17.77 m; an L1 model on all rows had MAE 18.32 m. No variant passed both the MAE and directional tests.
- **Rejected:** Reporting the post-hoc 0.028 m gain as a win, selecting a threshold on the same folds used to report the score, using 2024-2026 to choose v2, or swapping the interface to a model that only ties the baseline.
- **Impact:** V1 remains frozen and the app still shows its weaker test MAE honestly. A credible v2 needs new information not present at the origin, such as flow, rainfall, dam releases, or a held-out reach; it also needs nested threshold selection and a pre-registered scorecard. V2 experiments used only rolling validation origins 2000-2020 and never read 2024-2026.

## 18. External flow and rainfall did not produce a v2 win

- **Date:** 2026-10-21
- **Decision:** Do not wire the external flow/rainfall model into the app or replace v1. Keep `derived/external/` and `scripts/fetch_external_flow.py` as a reusable data source, but leave the frozen forecast and API unchanged.
- **Reason:** The reach is the Arial Khan distributary near Madaripur. Open-Meteo GloFAS daily discharge at the reach and at the upstream Padma main channel was downloaded for 1997-2026; ERA5-Land rainfall, ET0, and soil moisture were downloaded for 1989-2026. I added 28 external features, signed curvature, along-channel position, and neighbour five-year history, giving 100 candidate features. The best RandomForest classifier reached AUC 0.668, no better than the 0.672 without external data. A threshold chosen only from earlier out-of-sample folds gave MAE 17.286 m versus 17.320 m for zero; it won 17 of 63 folds and a paired test gave p=0.659, so the gain is noise. Directional accuracy was 0.059 and recall was about 3.5%. A post-hoc threshold 0.65 gave MAE 17.264 m, but that threshold was not selected online.
- **Rejected:** Reporting the 0.034-0.056 m post-hoc gains as a win, using 2024-2026 to tune the external model, or forcing a v2 into the app because the data cost effort.
- **Impact:** V1 remains the only forecast and the app is unchanged. The external data is available for a future experiment with a new reach, a longer flow record, seasonal flow forecasts, or better movement labels. The current zero/median baseline is still the honest MAE winner.

## 19. Record the pre-registered zone-tier result before any change

- **Date:** 2026-10-21
- **Decision:** Keep the pre-registered zone rules fixed: 90% block-bootstrap interval with 3-year blocks, Theil-Sen slope times elapsed years, 3-transect stretches, STRONG lower bound >= 150 m, MODERATE interval excludes zero and lower bound >= 30 m, LAND GAINED upper bound <= -30 m, and NO CLEAR MOVEMENT otherwise. Run the rules once on 1989-2026 usable bank positions, skipping 1997 and every flagged row, before changing any threshold or method.
- **Reason:** The user required the tier counts to be seen and recorded before deciding whether the design is usable. The result is 0 STRONG, 0 MODERATE, 11 LAND GAINED, and 39 NO CLEAR MOVEMENT out of 50 stretches. Two stretches had only one usable transect (the border groups at each end); their intervals are undefined and they fall to NO CLEAR MOVEMENT. The empty STRONG and MODERATE tiers and the 78% NO CLEAR share trigger the agreed stop rule.
- **Rejected:** Lowering the 150 m or 30 m cutoffs, changing the interval confidence, switching to overlapping stretches, or dropping missing stretches until a preferred mix appeared. Those would be post-hoc method changes.
- **Impact:** The fixed-rule outcome is preserved as evidence. It is not evidence that the banks are stable; it shows that the long-term record does not separate a clear outward class at this confidence and sampling density. The app will not claim an erosion-risk class from these tiers.

## 20. Publish the zone diagnostics and omit the relative layer

- **Date:** 2026-10-21
- **Decision:** Store the fixed-rule diagnostic checks in `reports/zone_diagnostics.json` and in `derived/zones/summary.json`, and keep the tier result unchanged. Do not show the “Most movement among stretches here” layer because the early/late rank score is below the pre-registered 0.30 minimum.
- **Reason:** The user required the diagnostics before accepting the zone design. The transect half-length is effectively 400 m for all 75 transects. Net movement has median 0.0 m, Q1 -144.532 m, Q3 30.156 m, min -347.894 m, and max 158.562 m. Interval width (46 defined intervals) has median 135.252 m and maximum 534.743 m. Four stretches have undefined intervals. The rank score is 0.146260 across 39 stretches (p=0.374289); including the two one-transect border groups would give 0.161528 across 43, which does not change the conclusion. Nine of the 11 land-gained stretches had the opposite bank moving outward; none had both banks moving inward.
- **Rejected:** Lowering the tier cutoffs, presenting the rank result as useful, using raw widths that include flagged rows, or dropping stretches until the map looked fuller. Clean unflagged width medians are 338.75 m in 1989 and 197.72 m in 2024-2026.
- **Impact:** The zone layer is a measured bank-change record with 0 STRONG, 0 MODERATE, 11 LAND GAINED, and 39 NO CLEAR out of 50 stretches. Forty-nine features have geometry, and four intervals are undefined. The relative layer is absent rather than hidden or silently approximated.

## 21. Keep the map center inside the corridor without event recursion

- **Date:** 2026-10-21
- **Decision:** Fit the whole corridor with `getBoundsZoom(bounds, false)` floored to 0.25, keep the rectangular `maxBounds` constraint, and defer any center correction out of Leaflet's `moveend` event. If the center leaves the corridor, schedule one `setView` correction and ignore re-entry while it is pending.
- **Reason:** The browser proof found that a drag could leave the center outside the diagonal corridor. Calling `setView` directly inside `moveend` could fire `moveend` again and overflow the stack. The deferred guard keeps the visible center inside without changing the map data.
- **Rejected:** Relying only on the rectangular bounding box, leaving the center outside the corridor, or calling `setView` synchronously in the event handler. Literal `getBoundsZoom(bounds, true)` was not used because it cropped the corridor.
- **Impact:** The full corridor is visible and the center guard survives drag, wheel, keyboard, and button zoom. Minimum zoom is 13 at 1440x900, 12.75 at 1024x768, and 12.25 at 390x844. The Playwright proof covers these interactions and checks for browser errors.

## 22. Use the basemap metadata bounds for the offline photo

- **Date:** 2026-10-21
- **Decision:** Enable the offline Sentinel-2 photo only when both `data/basemap/sentinel2_overlay.png` and a valid `data/basemap/basemap.json` exist. The API returns the photo's real `bounds`, and the map uses those bounds instead of stretching the image to the corridor rectangle.
- **Reason:** The GEE export uses a 200 m buffer around the corridor, so its footprint is larger than the corridor bounds. Stretching that image to the corridor rectangle would shift every measured feature relative to the photo. Keeping the real bounds makes the offline view spatially honest.
- **Rejected:** Assuming the photo matches the corridor bounds, hard-coding a footprint, or fetching the photo from the network at request time.
- **Impact:** The fallback remains off until the owner exports and converts the image. The online Esri layer is unchanged. The offline path shows a neutral background plus a clear internet message when the asset is absent, and uses the metadata bounds when it is present.

## 23. Keep the origin-2024 second look as a zero fallback and a negative result

- **Date:** 2026-10-21
- **Decision:** Freeze and report the origin-2024 refit with the zero-change predictor, keep `forecast_supported=false`, and do not replace v1 or wire this second look into the API/UI. Report the old and new scores side by side with their different origins and pair sets.
- **Reason:** The refit used 47 rolling-origin folds and 5,392 validation rows with targets no later than 2024. Zero change had pooled validation MAE 13.769637 m; the best fitted candidate, `random_forest_depth_4_leaf_5`, had 15.340780 m. No candidate beat zero, so the pre-registered fallback applied. On the one second-look score, 256 of 300 pairs were good. The frozen zero/selected forecast had MAE 5.900698 m and RMSE 16.573643 m. The old v1 RandomForest had 2025 MAE 10.745538 m (n=134) and 2026 MAE 10.122948 m (n=130); old zero change had 7.294485 m and 6.293853 m. These are different origins and different eligible pairs, so the comparison is not paired and is not a blind test.
- **Rejected:** Promoting the best fitted candidate despite its worse validation MAE, retuning after opening 2025-2026, presenting the old/new comparison as paired, changing the 15 m tolerance, or presenting the second look as a validated model.
- **Impact:** `forecasts/frozen_origin2024/READY` is `6c6455f39f80ec811667ad8db9b42bc6d139ad4b202531093dde7cfbd4547fd0`. The result is recorded in `reports/second_look_not_blind.md`, the v1 frozen artifacts are unchanged, and `tests/test_origin2024.py` enforces the cutoff, forecast-only rows, freeze hashes, and zero-fallback outcome. The first evaluation invocation exceeded the 5-minute tool limit after writing predictions but before writing metrics; the same frozen code was rerun unchanged with a longer limit, so no metric or model choice was available before the successful run.

## 24. Do not claim that the most active stretches persist

- **Date:** 2026-10-21
- **Decision:** Report the pre-registered ranking test as a negative result. Do not add a “most active stretch” layer to the UI, do not reword it as persistence, and do not change the fixed pass rule after seeing the numbers. The rule required a top-20% lift of at least 1.5 and a positive Spearman interval in at least 4 of the 5 splits.
- **Reason:** The test used 50 one-kilometre stretches, each made of three consecutive transects on one bank. A period’s activity was the change in outward bank position from the first to the last usable year, divided by elapsed time; flagged years, missing endpoints and 1997 were not filled. The five pairs had 10, 20, 28, 33 and 39 common stretches. Only split 2 (1994–2003 to 2004–2013) cleared both thresholds: lift 2.50 and rank agreement 0.404 with a 90% interval of 0.087 to 0.840. Split 1 had lift 0.00 and rank agreement -0.285; split 3 had lift 0.83 and agreement 0.162 with an interval spanning zero; split 4 had lift 0.71 and agreement 0.021; split 5 had lift 0.00 and agreement 0.128 with an interval spanning zero. Lift passed in 1 of 5 splits and the rank interval passed in 1 of 5, so the required 4 of 5 failed. The split-2 lift interval also included zero (0 to 4.0). The curvature-only ranking did not rescue it: its lifts were 0.00, 1.25, 0.83, 0.71 and 0.63. The transect-level check was similarly inconsistent. The five pairs reuse years and are not independent evidence, and 2025–2026 had already been seen in the origin-2024 second look.
- **Rejected:** Relaxing the 4-of-5 rule after the result, treating split 2 as confirmation, dropping the sparse 1989 split, using the transect or curvature result to rescue the stretch result, redefining overlap as a share of all stretches, or presenting the already-seen 2025–2026 years as a fresh test.
- **Impact:** `reports/ranking_persistence.json` and `reports/ranking_persistence.png` hold the result and the fixed-rule decision. The earlier long-period rank score was 0.146260 (Decision 20), also below its 0.30 minimum, so the new test does not overturn that warning. The share of stretches whose within-stretch interval included zero ranged from 12.5% to 63.2% across periods, but that check was descriptive and not part of pass/fail. The pre-registration hash is `2d0e1567ff811b9dfa7a1eabf8fdd04c7b85e92e08cc85ecf060a12778c17957`. No frozen forecast, `final_eval*` file, model or UI file was changed.

## 25. Display the unsimplified mask boundary as the observed bank line

- **Date:** 2026-10-23
- **Decision:** In the 2024-2026 comparison figures, draw the observed bank line as the unsimplified selected-river mask boundary, including all components and holes, rather than the supplied 75-vertex `observed_banklines` polyline.
- **Reason:** The supplied vertices lie on the mask boundary, but straight chords between them cut bends. Dense sampling of those chords reaches 88.97 m from the boundary and fails the fixed 30 m boundary check. Drawing the failing chord would misrepresent the observed bank, while smoothing or clipping it would create an invented line.
- **Rejected:** Drawing the supplied chord, smoothing the chord, dropping small mask components, or quietly relaxing the 30 m check.
- **Impact:** The displayed boundary has maximum boundary distance 0.00 m; observed points are within 2.04e-09 m. The 2024 left-bank T070 point is on a 6-pixel component and is retained. This is a display choice only: inputs, predictions, `evaluation/metrics.json`, the frozen forecast, and the model are unchanged. The source-chord deviation is documented in the comparison report.

## 26. Add a post-hoc spatial holdout as a low-power sensitivity check

- **Date:** 2026-10-23
- **Decision:** Run a five-block spatial holdout over contiguous 15-transect blocks, excluding each block plus two transects on each side from training, refitting the frozen RandomForest design with targets through 2023, and comparing 2024-2026 forecasts with zero change. Report the result without changing the model, thresholds, claims, or frozen files.
- **Reason:** The request asked for a spatial sensitivity check. The years were already scored and the blocks have about 15 transects each, so this is a post-hoc diagnostic with very low power, not a blind test or a replacement evaluation.
- **Rejected:** Tuning the model or thresholds on these blocks, treating the result as a pre-registered test, adding a bootstrap interval, or using the result to replace the frozen forecast.
- **Impact:** The model loses to zero overall and in every block: pooled RF/zero MAE 10.448732/5.817694 m; block MAEs 11.137/5.337, 11.104/7.503, 10.950/4.477, 9.743/6.032, and 9.053/5.630 m; 0 of 5 blocks beat zero. Outputs are in `figures/compare_2024_2026/spatial_block_holdout.csv` and `reports/compare_2024_2026.md`. Frozen artifacts and `evaluation/metrics.json` remain unchanged.

## 27. Make the comparison figures expose forecast errors honestly

- **Date:** 2026-10-23
- **Decision:** In the 2024-2026 comparison figures, use the forecast/zero MAEs and n from `evaluation/metrics.json`, but compute the closer/farther/tie shares from `evaluation/predictions.csv` because `metrics.json` has no closer field. Select six of the seven existing 4 km sections per year by the largest maximum absolute observed displacement among valid pairs. Draw the 2023 boundary at 4 final image pixels and 60% opacity beneath a 2-pixel black observed boundary, draw connectors at line width 2, and show a second overview panel labelled `error exaggerated 5x` in which only connector lengths are multiplied by 5.
- **Reason:** The request asks for visible overlap, an honest closer-than-zero share, visible connectors, a dedicated exaggeration panel, and a changed-place crop. `metrics.json` cannot supply the closer share without changing the frozen metrics file, so the share is derived from the same predictions that reproduce its MAEs and n. The six-of-seven rule keeps the existing 4 km section geography and uses maximum movement rather than a mean that can hide one large event. Four image pixels at 200 dpi is 1.44 pt, so the observed line was reduced to 2 px; otherwise the grey line would be hidden under it. Short connectors are still subpixel at true scale, so the separate 5x panel makes that limitation explicit rather than exaggerating the main map.
- **Rejected:** Editing `evaluation/metrics.json` to add a closer field, silently using green connector counts as the closer share, selecting sections by mean movement, exaggerating connector length on the true-scale map, drawing the old equal-width black line over the grey line, or omitting short connectors without explanation.
- **Impact:** `overview_stats.csv`/`.json` record the numbers used in the overviews; `changed_places_selection.csv` records the six-section selection; `closer_vs_farther.csv` and `closer_vs_farther_pairs.csv` record both groups; `figure_text_audit.json` records the strings printed on the figures; `connector_visibility.json` records the subpixel counts. The frozen forecast, model, `evaluation/metrics.json`, and all input data remain unchanged. The 36-PNG output supersedes the earlier 33-PNG comparison package.

## 28. Make forecast-derived risk zones the default map view

- **Date:** 2026-10-24
- **Decision:** Add `GET /api/forecast/risk-zones/?year=YYYY` and make its view the default in the UI. The endpoint verifies the frozen artifacts, then derives display-only ribbons between the observed 2023 bank and the selected frozen predicted bank, clipped to the forecast corridor. Mark intervals with either endpoint beyond the frozen 15 m low-movement tolerance; if endpoints disagree, use the larger absolute displacement. Draw outward movement red and inward movement green. Count low-movement segments but do not draw them. Keep the measured 1989–2026 record, including its 0/0/11/39 fixed-rule result, in a separate `Past change` tab.
- **Reason:** The user asked for a clear bottom-left panel where the predicted shift and risk zones are visible by default, with red for outward/high movement and green for accretion. The earlier fixed-rule map was too empty for that purpose and answers a different question: long-term measured change, not a forward scenario. Keeping the two views separate lets the map show the frozen forecast without presenting it as a validated safety rating.
- **Rejected:** Recoloring the fixed-rule stretches as if they were predicted risk; changing the model, the 15 m tolerance, or the 0/0/11/39 rule; drawing all 150 segments so the map looks fuller; presenting ribbons as probability, certainty, or a safety class; or removing the measured past from the interface.
- **Impact:** The API now exposes six endpoints, with segment counts 2024 `{erosion: 2, accretion: 2, low_movement: 146}`, 2025 `{8, 3, 139}`, and 2026 `{9, 11, 130}`, producing 3, 8, and 14 display zones respectively. In 2026, 9 erosion and 11 accretion segments form 5 erosion and 9 accretion ribbons. The risk view shows scenario-year pills, segment counts, a largest-shift shortcut, the 2023 edge, the predicted bank, and an explicit “Model scenario · not a safety rating” label. The measured tab and its 11 land-gain/39 unclear headline remain unchanged. Django tests cover all three years, high-segment coverage, popup behavior, and unverified-artifact refusal. **Assumption:** a ribbon between the 2023 edge and the predicted bank is a readable approximation of the possible swept area; it is not a calibrated probability or a claim that the whole ribbon will move. This decision changes presentation only and does not overturn the negative findings in Decisions 20 or 24.

## 29. Keep the five-model comparison descriptive and do not promote a model

- **Date:** 2026-10-25
- **Decision:** Run an isolated comparison of random forest, scikit-learn gradient boosting, XGBoost, LightGBM, and CatBoost with fixed settings, training targets through 2023 and scoring the same 398 valid 2024-2026 pairs. Publish the result as a post-hoc performance report. Do not replace the frozen model, tune on the test years, add the optional libraries to the app environment, or select a production model from these scores.
- **Reason:** The user asked how the five model families perform with a 2023 cutoff and 2024-2026 test. Those test years were already opened, so the only defensible use is a descriptive comparison, not blind selection. CatBoost had the lowest machine-learning MAE at 8.5992 m, but the zero-change baseline was 5.8177 m; no model beat zero on MAE overall or in any year. LightGBM had RMSE 15.5673 m versus zero 15.7213 m, but its MAE was 9.3965 m, so that is not an overall win. The five models captured only 4 to 9 of the 64 large movements. The retrained random forest matched the frozen random forest exactly (9.148572 m MAE, maximum prediction difference 7.1e-15 m), confirming the harness.
- **Rejected:** Promoting CatBoost or another model because it was the best of five despite losing to zero; tuning hyperparameters on 2024-2026; treating the opened test years as a blind test; adding XGBoost, LightGBM, or CatBoost to the app requirements; hiding the zero-baseline loss; or using these scores to overturn the frozen forecast.
- **Impact:** `scripts/compare_models_2023.py` and `reports/model_comparison_2024_2026/` hold the comparison. The optional libraries were installed under `/tmp/opencode/river-model-libs` and loaded through `PYTHONPATH`, not added to the app environment. The report is linked from `README.md`. The frozen forecast, `evaluation/metrics.json`, model artifacts, API, UI, and app requirements are unchanged. This adds negative evidence to Decisions 23 and 26; it does not supersede them. **Assumption:** the fixed hyperparameters were set before scoring, and no test-year label was used for fitting.
