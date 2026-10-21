# Origin-2024 second look: pre-registration

**Date:** 2026-10-21  
**Status:** frozen before any origin-2024 fitting, tuning, freeze, or 2025–2026 scoring.  
**Report title:** “second look, not blind”.

## Why this is a second look, not a blind test

The original frozen forecast used origin 2023 and scored 2024, 2025 and 2026 once. Those three years have already been seen, and their results are in `evaluation/metrics.json`. This experiment deliberately moves 2024 into training and uses only 2025 and 2026 for scoring. It cannot be called a blind test. It is a second look at two years whose outcomes are already known.

`forecast_supported` remains **false**. The purpose is to measure whether adding the 2024 observation changes the result, not to search for a positive verdict.

## Immutable v1 artifacts

This experiment will not modify:

- `forecasts/frozen/` or its `READY` file
- `evaluation/metrics.json`
- `models/final_models.joblib`
- `datasets/bank_migration_dataset.csv`
- `datasets/forecast_features_2023.csv`
- `config/pipeline.json`

New outputs go only to the paths named below. The v1 API and UI must continue to read the v1 freeze.

## Knowledge and contamination statement

- The v1 test years 2024, 2025 and 2026 were opened once after the v1 freeze and have been seen.
- 2024 is now a training year, as explicitly requested. Its bank observations are taken from the existing post-freeze observation files; those files are not modified.
- 2025 and 2026 remain scoring years only. No 2025 or 2026 observation will be used to build features, choose features, choose a model, choose a hyperparameter, choose a fold, or set a threshold.
- The choice of features, folds, grid, eligibility rule and success metric in this document is fixed before running the origin-2024 experiment.

## Data construction

New data files:

- `datasets/origin2024_bank_migration.csv`
- `datasets/origin2024_forecast_features.csv`
- `datasets/origin2024_provenance.json`

Training rows are the same leakage-resistant bank-side design as v1: one row per transect, side, origin and horizon. Features come only from intervals ending at or before the origin.

- All training target years must be `<= 2024`.
- A training row with `target_year > 2024` is forbidden; a test must fail if one exists.
- No target year 2025 or 2026 may appear in the training table.
- The 2024 target labels are built from the already-opened 2024 observed bank positions.
- Origin-2024 features are built from bank positions and intervals ending at or before 2024. No 2025 or 2026 bank observation is used to build them.
- Forecast feature rows are created for origin 2024, horizons 1 and 2 only, with target years 2025 and 2026.
- Rows are retained for audit when geometry quality fails, but only `good` rows are used for fitting or validation.

The 20 features, unchanged from v1, are:

`last_rate_m_per_yr`, `last2_mean_rate_m_per_yr`, `last3_mean_rate_m_per_yr`, `acceleration_m_per_yr2`, `last_displacement_m`, `last_interval_years`, `last_interval_good`, `width_m`, `width_change_last_m`, `abs_curvature_1_m`, `sinuosity`, `is_left_bank`, `horizon_years`, `elapsed_years`, `last_rate_missing`, `last2_missing`, `last3_missing`, `width_missing`, `curvature_missing`, `sinuosity_missing`.

Identifiers, coordinates, target values, future observations and test-year information remain excluded from the feature list.

## Rolling-origin validation

Validation is restricted to horizons 1 and 2, because those are the two forecast horizons being produced.

For each origin in 2000 through 2023 and each horizon in 1 and 2:

- Training rows must have `target_year < origin`, the same horizon, `usable_for_training = true`, and `target_year <= 2024`.
- Validation rows must have `origin_year = origin`, the same horizon, `target_year <= 2024`, `target_year > origin`, and `label_quality = good`.
- A fold is used only if it has at least 100 training rows and at least one validation row.
- No validation target after 2024 is permitted.
- The zero-change baseline is calculated on exactly the same validation rows as each candidate.

The already-declared validation origins 2000–2020 are retained. Origins 2021–2023 are added only because their validation targets are now available through 2024. Their inclusion is fixed here before seeing the new result.

## Candidate grid

The grid is the existing small grid in `config/pipeline.json`, not a new search:

- Baselines: zero change, training median, persistence of last rate, historic rate trend.
- Ridge: alpha in `{1.0, 10.0, 100.0}`.
- Random forest: `n_estimators = 300`, `max_depth` in `{4, 8, null}`, `min_samples_leaf` in `{5, 10}`.
- Histogram gradient boosting: `max_iter = 200`, `max_depth` in `{2, 3}`, `learning_rate` in `{0.05, 0.1}`.

That is 13 fitted configurations, plus the four untuned baselines. Every configuration is evaluated on every usable fold. Every candidate result is written to a machine-readable log before a model is selected.

Hyperparameters are compared only across the rolling-origin validation folds above. No test year enters this search.

## Eligibility and selection

A candidate is eligible only if its pooled validation MAE across all validation rows is strictly lower than the pooled validation MAE of zero change on the same rows.

If no candidate is eligible, the frozen forecast is the zero-change baseline and the report says so explicitly. No fitted model is used in that case.

If one or more candidates are eligible, the eligible candidate with the lowest pooled validation MAE is selected. Ties break on, in order: lower pooled RMSE, higher low-movement F1, higher directional accuracy on movement beyond 15 m, then deterministic grid order. One selected configuration is used for both horizons, matching the v1 design; separate models are still fitted for horizon 1 and horizon 2.

The selection rule is fixed before any validation run. The test years are not inspected to break a tie.

## Final fit and freeze

If a fitted candidate is selected, it is refitted on every usable training row with `target_year <= 2024` for that horizon. If zero change is selected, the frozen artifact is an explicit zero predictor for each horizon.

The freeze directory is:

- `forecasts/frozen_origin2024/`

It will contain at least:

- `model.joblib`
- `forecast_features_2024.csv`
- `predictions_2025.csv`
- `predictions_2026.csv`
- `summary.json`
- `model_metadata.json`
- `tuning_candidates.jsonl`
- `manifest.json`
- `READY`

The manifest records SHA256 hashes for every frozen file, the training dataset, forecast features, model, code, feature list, grid, selected model, training cutoff 2024, origin 2024, forecast years 2025–2026, and the fact that 2025–2026 were already seen. `READY` contains the SHA256 of `manifest.json`.

The freeze step refuses to overwrite a non-empty directory. After `READY` is written, the forecast is immutable for this experiment.

## One-time scoring

Only after the new manifest and every frozen file pass hash verification, the frozen predictions will be scored against the 2025 and 2026 observed bank positions.

The scored models are:

- selected frozen model (or zero-change fallback)
- zero change
- training median
- persistence of last rate
- historic rate trend

The evaluation uses `good` pairs only. It reports, overall and by year and horizon:

- MAE in metres
- RMSE in metres
- bias in metres
- share within ±15 m
- low-movement F1
- directional accuracy for movement beyond 15 m
- share of bank sides predicted to move more than 15 m
- per-model absolute errors and the largest errors

The primary comparison is the paired MAE difference between each model and zero change. The 90% interval is a transect-cluster bootstrap: resample transects with replacement 10,000 times, keep all rows belonging to a resampled transect, compute the difference in mean absolute error, and take the 5th and 95th percentiles. The random seed is 42.

Test results are written to:

- `evaluation_origin2024/metrics.json`
- `evaluation_origin2024/predictions.csv`
- `evaluation_origin2024/bootstrap.json`

These files are produced once. No model, feature, fold, threshold or hyperparameter may change after this scoring run.

## Old versus new

The second-look report is `reports/second_look_not_blind.md`. It will show the old v1 results and the new origin-2024 results side by side. Old numbers are read from the immutable `evaluation/metrics.json`; they are not retyped. The comparison will show that the two runs use different origins and therefore different eligible bank pairs, and will not present the difference as a paired like-for-like experiment.

## Success language

The new run is not called validated, accurate or safe. If it beats zero change, that is a second-look result on already-seen years. If it loses, that is the result and is reported as such. `forecast_supported` remains `false` either way.

## Freeze of this pre-registration

This file is committed to git before any fitting, tuning, freeze or 2025–2026 scoring. It will not be edited after the test run.
