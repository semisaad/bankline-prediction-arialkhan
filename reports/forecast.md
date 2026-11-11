# Forecast, 2024–2026

- Frozen origin: 2023
- Forecast years: 2024, 2025, 2026
- Model: Random forest
- Training cutoff: 2023
- Transects: 75 (150 bank segments per year)
- Low-movement tolerance: ±15.0 m
- Implausible threshold: ±150.0 m

Positive displacement is outward bank movement (erosion); negative is inward (accretion). Forecasts are conditional on the observed 2023 banks and fixed transects, not a full hydrodynamic or sediment simulation.

| Year | Erosion | Accretion | Low movement | Mean (m) | Median (m) | Mean |d| (m) |
|---|---:|---:|---:|---:|---:|---:|
| 2024 | 2 | 2 | 146 | +1.23 | +0.82 | 4.17 |
| 2025 | 8 | 3 | 139 | +0.75 | +0.26 | 5.66 |
| 2026 | 9 | 11 | 130 | +0.07 | +1.15 | 7.41 |

## By reach

| Year | Reach | n | Mean (m) | Erosion | Accretion | Low movement |
|---|---|---:|---:|---:|---:|---:|
| 2024 | middle | 50 | +0.49 | 0 | 0 | 50 |
| 2024 | north | 50 | +2.01 | 0 | 0 | 50 |
| 2024 | south | 50 | +1.17 | 2 | 2 | 46 |
| 2025 | middle | 50 | -0.51 | 0 | 0 | 50 |
| 2025 | north | 50 | +1.82 | 5 | 1 | 44 |
| 2025 | south | 50 | +0.95 | 3 | 2 | 45 |
| 2026 | middle | 50 | -1.63 | 1 | 3 | 46 |
| 2026 | north | 50 | +1.62 | 4 | 4 | 42 |
| 2026 | south | 50 | +0.22 | 4 | 4 | 42 |

Random-forest uncertainty is the spread of individual tree predictions; `p10` and `p90` are descriptive, not calibrated confidence intervals.

## Freeze status

The forecast is frozen. `forecasts/frozen/manifest.json` records origin 2023, forecast years 2024–2026, all artifact hashes, and the model/config/code inputs. `READY` contains the manifest hash. Freeze time: 2026-10-20T17:25:02Z.

`forecasts/frozen/` is the immutable source for the API and UI. Regeneration is not permitted there; use a new freeze step and a new directory if the model or inputs change. The full freeze report is `reports/forecast_freeze.md`.
