# Post-freeze evaluation, 2024–2026

This is the only report that reads 2024–2026 pixel data. It was produced after the forecast manifest was frozen and hash-verified. No model, feature, threshold or transect was changed after seeing these observations.

## Test data audit

| Year | Valid px | Water px | Selected river px | Area (km²) | Aligned | Components | Fallback |
|---|---:|---:|---:|---:|---|---:|---|
| 2024 | 162665 | 7374 | 5934 | 5.341 | True | 1 | False |
| 2025 | 162665 | 7233 | 6058 | 5.452 | True | 1 | False |
| 2026 | 162665 | 8373 | 6112 | 5.501 | True | 1 | False |

Test polygons were built from the test masks using the frozen historical core and the same selection rule. The fixed 2023 transects were re-verified against `derived/transects.csv`.

## Forecast vs observed

Only pairs where both the 2023 origin bank and test-year bank pass the geometry quality rules are scored. Positive is erosion (outward); negative is accretion (inward).

| Model | n | MAE (m) | RMSE (m) | Bias (m) | Within ±15 m | Low-movement F1 | Directional accuracy (>15 m) | False movement | Missed movement |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Frozen random forest | 398 | 9.15 | 15.90 | 2.90 | 0.804 | 0.897 | 0.594 | 0.048 | 0.891 |
| Zero change | 398 | 5.82 | 15.72 | 1.53 | 0.839 | 0.913 | 0.000 | 0.000 | 1.000 |
| Persistence | 398 | 13.44 | 39.29 | -5.89 | 0.781 | 0.896 | 0.078 | 0.075 | 0.734 |
| Historic trend | 398 | 13.22 | 30.20 | -0.86 | 0.714 | 0.844 | 0.328 | 0.177 | 0.672 |
| Historical median | 398 | 5.82 | 15.72 | 1.53 | 0.839 | 0.913 | 0.000 | 0.000 | 1.000 |

## Frozen model by horizon

| Horizon | n | MAE (m) | RMSE (m) | Bias (m) | Low-movement F1 | Directional accuracy |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 134 | 6.61 | 11.98 | 4.52 | 0.932 | 0.500 |
| 2 | 134 | 10.75 | 19.55 | 3.00 | 0.877 | 0.600 |
| 3 | 130 | 10.12 | 15.23 | 1.15 | 0.879 | 0.652 |

## Frozen model by reach

| Reach | n | MAE (m) | RMSE (m) | Bias (m) | Directional accuracy |
|---|---:|---:|---:|---:|---:|
| middle | 144 | 8.27 | 15.69 | 1.52 | 0.381 |
| north | 132 | 9.16 | 13.41 | 3.54 | 0.696 |
| south | 122 | 10.17 | 18.42 | 3.85 | 0.700 |

## Confusion matrix, frozen model

Rows are observed classes; columns are predicted classes.

| Observed \ predicted | Erosion | Accretion | Low movement |
|---|---:|---:|---:|
| erosion | 3 | 1 | 18 |
| accretion | 1 | 2 | 39 |
| low_movement | 12 | 4 | 318 |

## Event audit

| Observed class | n | Captured | Capture rate | Predicted low | Opposite direction | Mean observed (m) | Mean predicted (m) | MAE (m) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| erosion | 22 | 3 | 0.136 | 18 | 1 | 37.13 | 4.60 | 32.53 |
| accretion | 42 | 2 | 0.048 | 39 | 1 | -33.33 | -2.13 | 31.24 |
| low_movement | 334 | 318 | 0.952 | 318 | 12 | -0.08 | 1.60 | 4.83 |

## Largest frozen-model errors

| Year | Transect | Side | Reach | Observed (m) | Predicted (m) | Error (m) |
|---:|---:|---|---|---:|---:|---:|
| 2025 | 71 | L | south | 146.83 | 19.87 | -126.96 |
| 2026 | 31 | R | middle | -63.20 | 2.59 | 65.79 |
| 2025 | 31 | R | middle | -63.20 | 2.56 | 65.77 |
| 2025 | 69 | L | south | 68.72 | 5.21 | -63.51 |
| 2025 | 29 | R | middle | -60.91 | -7.08 | 53.84 |
| 2025 | 70 | L | south | -35.21 | 17.45 | 52.66 |
| 2024 | 29 | R | middle | -60.91 | -8.83 | 52.08 |
| 2026 | 29 | R | middle | -60.91 | -15.33 | 45.58 |
| 2026 | 57 | L | south | -41.87 | 2.49 | 44.36 |
| 2024 | 54 | R | south | -30.03 | 12.68 | 42.71 |
| 2026 | 27 | L | middle | 24.81 | -16.06 | -40.87 |
| 2025 | 45 | R | middle | -34.20 | 3.49 | 37.69 |
| 2024 | 45 | R | middle | -34.20 | 1.86 | 36.06 |
| 2026 | 17 | R | north | 37.33 | 1.29 | -36.04 |
| 2026 | 30 | L | middle | 31.09 | -4.68 | -35.77 |
| 2025 | 39 | L | middle | 30.07 | -3.98 | -34.05 |
| 2024 | 71 | L | south | 0.00 | 34.05 | 34.05 |
| 2026 | 31 | L | middle | 31.60 | -2.10 | -33.70 |
| 2024 | 23 | R | north | -32.03 | 1.65 | 33.68 |
| 2024 | 46 | R | middle | -32.96 | 0.53 | 33.49 |

## Interpretation

The frozen forecast is a bank-displacement forecast at fixed transects, not a forecast of every pixel. The test masks are classified water observations at the same nominal late-March season; water level, cloud and classification error remain part of the observed signal.

The baselines are shown because they expose the zero-inflated nature of the labels: a large share of observed bank displacements are exactly zero at 30 m resolution. A model can have a low MAE while capturing very few moving segments; the event audit and confusion matrix are therefore reported alongside MAE.

No retuning was performed after this evaluation. The frozen files and hashes in `forecasts/frozen/manifest.json` remain authoritative.
