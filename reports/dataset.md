# Leakage-resistant training dataset

- Historical rows: 13950
- Usable (`good`) historical rows: 8425
- Forecast feature rows for origin 2023: 450
- Target years: 1990–2023
- Origin years: 1989–2022

Each row is one bank side (left or right of a fixed transect) at one forecast origin and one horizon (1, 2 or 3 years). The target is signed bank displacement in metres. Positive is erosion (outward); negative is accretion (inward).

## Features

| Feature | Unit | Availability |
|---|---|---|
| `last_rate_m_per_yr` | m/yr | origin |
| `last2_mean_rate_m_per_yr` | m/yr | origin |
| `last3_mean_rate_m_per_yr` | m/yr | origin |
| `acceleration_m_per_yr2` | m/yr² | origin |
| `last_displacement_m` | m | origin |
| `last_interval_years` | years | origin |
| `last_interval_good` | 0/1 | origin |
| `width_m` | m | origin |
| `width_change_last_m` | m | origin |
| `abs_curvature_1_m` | 1/m | origin |
| `sinuosity` | ratio | origin |
| `is_left_bank` | 0/1 | origin |
| `horizon_years` | years | forecast design |
| `elapsed_years` | years | forecast design |
| `last_rate_missing` | 0/1 | origin |
| `last2_missing` | 0/1 | origin |
| `last3_missing` | 0/1 | origin |
| `width_missing` | 0/1 | origin |
| `curvature_missing` | 0/1 | origin |
| `sinuosity_missing` | 0/1 | origin |

`transect_id`, `reach`, coordinates and `sample_id` are identifiers, not features. No target-year label, area statistic, future discharge/rainfall or test-year observation is used as a predictor.

## Leakage checks

| Check | Result |
|---|---|
| `max_target_year` | 2023 |
| `max_target_year_at_most_2023` | True |
| `min_origin_year` | 1989 |
| `max_origin_year` | 2022 |
| `all_targets_after_origin` | True |
| `all_feature_cutoffs_at_origin` | True |
| `no_test_years_in_training` | True |
| `no_forecast_years_in_training` | True |
| `duplicate_sample_ids` | 0 |
| `duplicate_transect_side_origin_horizon` | 0 |
| `segment_id_in_features` | False |
| `transect_id_in_features` | False |
| `coordinate_in_features` | False |
| `target_columns_in_features` | False |
| `forecast_rows_have_no_labels` | True |
| `forecast_years` | [2024, 2025, 2026] |
| `forecast_origin_year` | [2023] |
| `forecast_feature_cutoffs` | [2023] |
| `forecast_contains_test_years_only` | True |
| `next_observation_year_not_used_before_origin` | True |
| `feature_dictionary_has_availability` | True |
| `all_horizons_positive` | True |
| `no_rows_from_2024_plus` | True |
| `all_checks_pass` | True |

All checks pass: **True**.

## Split design

Model selection uses rolling origins before 2024. For a validation origin `v`, only rows whose target year is strictly before `v` are eligible for training. The validation rows are the rows at origin `v` with targets through 2023. The 2024–2026 rows are not present in the training file at all; they exist only in `forecast_features_2023.csv` without labels.

Rows with `label_quality` `flagged`, `implausible` or `invalid` are retained for audit but are not used for training. This is decided from historical geometry evidence, not from test performance.
