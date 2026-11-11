# Second look, not blind

This is the origin-2024 refit. It is **not a blind test**: 2024 was moved into training and 2025–2026 had already been seen in the v1 test. `forecast_supported` remains **false**.

The v1 frozen forecast, `evaluation/metrics.json` and `models/final_models.joblib` were not modified. Old numbers below are read from the immutable v1 metrics file.

## What changed

- Origin: **2024** (v1 origin was 2023).
- Training target cutoff: **2024**.
- Forecast horizons: **1 and 2 only** (2025 and 2026).
- 2024 observations were previously part of the v1 test; they are now training data.
- 2025 and 2026 were seen before this experiment and are used for one second-look score only.

- Training rows target ≤ 2024: **6053** usable rows across both horizons.
- Rolling-origin folds used for choice: **47**, maximum validation target **2024**.
- Candidate configurations logged: **13**; eligible by zero-change gate: **0**.
- Selected predictor: **Zero change** (`zero`).

> No fitted candidate beat zero change on the pooled rolling-origin validation folds. The frozen origin-2024 forecast is therefore the zero-change baseline, as pre-registered.

## Validation result

Zero-change pooled validation MAE: **13.77 m**.

| Candidate | Pooled MAE (m) | RMSE (m) | Low-movement F1 | Directional accuracy | Eligible |
|---|---:|---:|---:|---:|---|
| `ridge_alpha_1` | 16.49 | 27.98 | 0.810 | 0.598 | no |
| `ridge_alpha_10` | 16.47 | 27.96 | 0.810 | 0.598 | no |
| `ridge_alpha_100` | 16.27 | 27.82 | 0.812 | 0.592 | no |
| `random_forest_depth_4_leaf_5` | 15.34 | 26.65 | 0.812 | 0.625 | no |
| `random_forest_depth_4_leaf_10` | 15.47 | 26.69 | 0.812 | 0.628 | no |
| `random_forest_depth_8_leaf_5` | 15.79 | 26.59 | 0.806 | 0.641 | no |
| `random_forest_depth_8_leaf_10` | 15.90 | 26.62 | 0.806 | 0.643 | no |
| `random_forest_depth_none_leaf_5` | 16.51 | 26.71 | 0.797 | 0.649 | no |
| `random_forest_depth_none_leaf_10` | 16.39 | 26.70 | 0.800 | 0.640 | no |
| `hist_gradient_boosting_depth_2_lr_0.05` | 16.52 | 27.06 | 0.804 | 0.605 | no |
| `hist_gradient_boosting_depth_2_lr_0.1` | 17.04 | 27.41 | 0.797 | 0.607 | no |
| `hist_gradient_boosting_depth_3_lr_0.05` | 16.75 | 27.15 | 0.802 | 0.614 | no |
| `hist_gradient_boosting_depth_3_lr_0.1` | 17.39 | 27.62 | 0.789 | 0.613 | no |

The gate is strict: a candidate needed a pooled MAE lower than zero change on the same validation rows. No 2025 or 2026 observation entered this choice.

## Frozen forecast

| Year | Erosion | Accretion | Low movement | Share predicted to move | Mean (m) |
|---|---:|---:|---:|---:|---:|
| 2025 | 0 | 0 | 150 | 0.0% | +0.00 |
| 2026 | 0 | 0 | 150 | 0.0% | +0.00 |

The forecast is conditional on the observed 2024 banks and fixed 2023 transects. It is not a hydrodynamic or sediment-transport simulation.

## 2025–2026 score

Scored pairs: **256** good of **300**; 44 flagged or invalid pairs excluded.

| Model | n | MAE (m) | RMSE (m) | Bias (m) | Within ±15 m | Low-movement F1 | Directional accuracy | Predicted move |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Selected origin-2024 forecast | 256 | 5.90 | 16.57 | -1.93 | 0.844 | 0.915 | 0.000 | 0.0% |
| Zero change | 256 | 5.90 | 16.57 | -1.93 | 0.844 | 0.915 | 0.000 | 0.0% |
| Training median | 256 | 5.90 | 16.57 | -1.93 | 0.844 | 0.915 | 0.000 | 0.0% |
| Persistence | 256 | 11.96 | 27.88 | -6.23 | 0.770 | 0.897 | 0.000 | 12.9% |
| Historic trend | 256 | 9.46 | 20.23 | -3.79 | 0.773 | 0.896 | 0.125 | 10.9% |

## Paired difference from zero change

Negative values mean the model has a lower MAE than zero change. The interval is a 90% transect-cluster bootstrap with 10,000 draws.

| Model | MAE difference (m) | 90% interval |
|---|---:|---:|
| Selected origin-2024 forecast | 0.00 | [0.00, 0.00] |
| Training median | 0.00 | [0.00, 0.00] |
| Persistence | 6.05 | [3.81, 8.20] |
| Historic trend | 3.56 | [2.60, 4.53] |

## Old versus new, 2025 and 2026

The old v1 model used origin 2023; the new model uses origin 2024. They therefore score different eligible bank pairs, and the comparison is not a paired like-for-like test. Old numbers are taken from `evaluation/metrics.json`; new numbers are from this run.

| Year | Run | Model | n | MAE (m) | RMSE (m) | Bias (m) | Predicted move |
|---:|---|---|---:|---:|---:|---:|---:|
| 2025 | v1, origin 2023 | v1 random forest | 134 | 10.75 | 19.55 | 3.00 | — |
| 2025 | v1, origin 2023 | v1 zero | 134 | 7.29 | 19.72 | 1.59 | — |
| 2025 | v1, origin 2023 | v1 median | 134 | 7.29 | 19.72 | 1.59 | — |
| 2025 | v1, origin 2023 | v1 persistence | 134 | 15.47 | 44.10 | -6.57 | — |
| 2025 | v1, origin 2023 | v1 trend | 134 | 15.48 | 35.88 | -1.53 | — |
| 2025 | new, origin 2024 | Selected origin-2024 forecast | 130 | 5.55 | 18.47 | -1.46 | 0.0% |
| 2025 | new, origin 2024 | Zero change | 130 | 5.55 | 18.47 | -1.46 | 0.0% |
| 2025 | new, origin 2024 | Training median | 130 | 5.55 | 18.47 | -1.46 | 0.0% |
| 2025 | new, origin 2024 | Persistence | 130 | 9.53 | 23.61 | -4.28 | 12.3% |
| 2025 | new, origin 2024 | Historic trend | 130 | 7.98 | 20.13 | -2.63 | 1.5% |
| 2026 | v1, origin 2023 | v1 random forest | 130 | 10.12 | 15.23 | 1.15 | — |
| 2026 | v1, origin 2023 | v1 zero | 130 | 6.29 | 14.90 | 0.21 | — |
| 2026 | v1, origin 2023 | v1 median | 130 | 6.29 | 14.90 | 0.21 | — |
| 2026 | v1, origin 2023 | v1 persistence | 130 | 18.05 | 48.96 | -10.70 | — |
| 2026 | v1, origin 2023 | v1 trend | 130 | 16.52 | 34.78 | -2.62 | — |
| 2026 | new, origin 2024 | Selected origin-2024 forecast | 126 | 6.27 | 14.36 | -2.42 | 0.0% |
| 2026 | new, origin 2024 | Zero change | 126 | 6.27 | 14.36 | -2.42 | 0.0% |
| 2026 | new, origin 2024 | Training median | 126 | 6.27 | 14.36 | -2.42 | 0.0% |
| 2026 | new, origin 2024 | Persistence | 126 | 14.46 | 31.69 | -8.24 | 13.5% |
| 2026 | new, origin 2024 | Historic trend | 126 | 10.99 | 20.32 | -4.99 | 20.6% |

## What this means

The selected origin-2024 forecast does not beat zero change on the already-seen 2025–2026 pairs. The honest result is that moving 2024 into training did not produce a model that beats the trivial baseline here.

The selected predictor is the zero-change fallback.

`forecast_supported` is false. No forecast line or claim of validation should be built on this second look. The exact frozen files and hashes are in `forecasts/frozen_origin2024/manifest.json`.

## Limits

- 2025 and 2026 are not unseen years; the v1 test had already opened them.
- 2024 is now training data, so the two runs use different origins and different eligible pairs.
- The labels are 30 m water-mask bank positions, not surveyed ground truth.
- No post-score model, feature, fold or threshold change was made.
- The test is one reach and two years.
