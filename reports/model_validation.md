# Model validation and selection

Validation uses rolling forecast origins from 2000 to 2020. For each origin, training rows end strictly before that origin; validation rows are the good-quality labels at that origin with targets through 2023. The 2024–2026 years are absent from this exercise.

## Selection rule

Eligibility gates exclude constant/no-skill forecasts: directional accuracy on observed movement >15 m must be at least 0.55, and low-movement F1 must be at least 0.70. Among eligible models, rank by MAE, RMSE, low-movement F1 and directional accuracy (mean rank). Ties break on higher directional accuracy, then lower RMSE, then lower MAE. No test-year observation is used.

## Aggregate validation metrics

| Model | Eligible | MAE (m) | RMSE (m) | Bias (m) | Within ±15 m | Low-movement F1 | Directional accuracy (>15 m) | False movement | Missed movement |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Training median | no | 17.32 | 30.14 | +1.91 | 0.611 | 0.751 | 0.000 | 0.000 | 1.000 |
| Zero change | no | 17.32 | 30.14 | +1.91 | 0.611 | 0.751 | 0.000 | 0.000 | 1.000 |
| Ridge regression | yes | 19.96 | 30.36 | +3.64 | 0.590 | 0.740 | 0.589 | 0.064 | 0.899 |
| Random forest | yes | 19.98 | 29.46 | +3.72 | 0.565 | 0.718 | 0.648 | 0.151 | 0.778 |
| Histogram gradient boosting | no | 22.46 | 31.59 | +4.65 | 0.497 | 0.658 | 0.621 | 0.314 | 0.593 |
| Historic rate trend | no | 28.81 | 47.26 | -1.33 | 0.480 | 0.640 | 0.488 | 0.381 | 0.461 |
| Persistence of last rate | no | 43.32 | 80.28 | -3.56 | 0.452 | 0.673 | 0.247 | 0.302 | 0.557 |

Selected model: **Random forest** (mean rank score 1.50; MAE 19.98 m).

## By horizon

| Model | Horizon | MAE (m) | RMSE (m) | Low-movement F1 | Directional accuracy |
|---|---:|---:|---:|---:|---:|
| Training median | 1 | 12.98 | 25.87 | 0.820 | 0.000 |
| Training median | 2 | 17.38 | 30.22 | 0.748 | 0.000 |
| Training median | 3 | 21.61 | 34.34 | 0.686 | 0.000 |
| Zero change | 1 | 12.98 | 25.87 | 0.820 | 0.000 |
| Zero change | 2 | 17.38 | 30.22 | 0.748 | 0.000 |
| Zero change | 3 | 21.61 | 34.34 | 0.686 | 0.000 |
| Ridge regression | 1 | 15.41 | 25.19 | 0.820 | 0.620 |
| Ridge regression | 2 | 20.14 | 31.37 | 0.742 | 0.572 |
| Ridge regression | 3 | 24.33 | 34.51 | 0.659 | 0.576 |
| Random forest | 1 | 15.55 | 25.04 | 0.811 | 0.658 |
| Random forest | 2 | 20.34 | 29.95 | 0.713 | 0.635 |
| Random forest | 3 | 24.04 | 33.40 | 0.629 | 0.653 |
| Histogram gradient boosting | 1 | 17.72 | 26.56 | 0.766 | 0.620 |
| Histogram gradient boosting | 2 | 22.65 | 32.03 | 0.658 | 0.624 |
| Histogram gradient boosting | 3 | 27.01 | 36.20 | 0.550 | 0.620 |
| Historic rate trend | 1 | 19.39 | 32.83 | 0.772 | 0.433 |
| Historic rate trend | 2 | 28.96 | 47.14 | 0.586 | 0.503 |
| Historic rate trend | 3 | 38.09 | 61.80 | 0.563 | 0.527 |
| Persistence of last rate | 1 | 26.09 | 48.89 | 0.734 | 0.213 |
| Persistence of last rate | 2 | 43.36 | 79.27 | 0.674 | 0.262 |
| Persistence of last rate | 3 | 60.52 | 112.68 | 0.612 | 0.267 |

## Interpretation

The zero and median baselines are strong in MAE because a large share of observed bank displacements are exactly zero at the 30 m pixel resolution. That is why the selection rule also ranks low-movement F1 and directional accuracy, and why results are broken down by horizon. A low MAE alone can hide a model that never predicts movement.

The bank displacement labels are measured at fixed 2023 transects. Early-year labels are more often flagged because the channel occupied a different position; only `good` labels enter validation. This reduces the effective early sample and is reported rather than hidden.

No 2024–2026 raster or label is used in this report.
