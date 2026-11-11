# Riverbank Change Monitor: Final Report

## What this project delivers

A complete, reproducible pipeline for one Landsat river reach:

1. Audit and harmonize 37 annual MNDWI water masks (1989-2026, missing 1997).
2. Extract the main river and measure bank movement on 75 fixed transects.
3. Build a leakage-checked bank-migration dataset.
4. Backtest candidate models and choose one before seeing 2024-2026.
5. Freeze model outputs for 2024, 2025, and 2026 with file hashes.
6. Open the test years once, evaluate the frozen model outputs, and report the result without retuning.
7. Serve the frozen model outputs and their test results in a self-contained Django + React application.

RiverGuard was not modified.

## Method in plain language

The water masks come from Landsat dry-season composites. Band 1 marks water; band 2 marks pixels that are valid. All 37 files share the same 30 m grid, so no reprojection or resampling was used.

A persistent-water core (present in at least 20% of years) identifies the main river. Each year's river polygon is the water component that overlaps that core. This removes most ponds and canals, while still allowing the channel to move.

A single 2023 centerline defines 75 transects spaced 360 m apart. At each transect, the outermost water-to-land crossings on the left and right define the banks. Positive movement is outward (erosion); negative is inward (accretion). Movement within 15 m is called low movement. This is half a pixel.

The model uses only information available at the model origin: recent annual bank rates, acceleration, last displacement, width, width change, curvature, sinuosity, bank side, horizon, and missing-data indicators. Transect IDs, reach labels, coordinates, and future values are excluded. Backtests use rolling origins from 2000 to 2020, giving 63 folds. Training targets always stay before the validation origin.

## Model selection

Eligibility required directional accuracy of at least 0.55 on movement beyond 15 m and low-movement F1 of at least 0.70. Eligible models were ranked on MAE, RMSE, low-movement F1, and directional accuracy. Ties broke on higher directional accuracy, then lower RMSE, then lower MAE.

Ridge and RandomForest passed. Both had mean rank 1.5. RandomForest won the directional tie-break and was selected for all horizons.

Validation fold means:

| Model | MAE | RMSE | Low-movement F1 | Directional |
|---|---:|---:|---:|---:|
| Zero / median | 17.32 | 30.14 | 0.751 | 0.000 |
| RandomForest | 19.98 | 29.46 | 0.718 | 0.648 |
| Ridge | 19.96 | 30.36 | 0.740 | 0.589 |
| HistGradientBoosting | 22.46 | 31.59 | 0.658 | 0.621 |
| Persistence | 43.32 | 80.28 | 0.673 | 0.247 |
| Trend | 28.81 | 47.26 | 0.640 | 0.488 |

## Frozen model output

The model output is conditional on the observed 2023 bank and fixed 2023 transects. It is not a hydrodynamic or sediment-transport simulation.

| Year | Erosion | Accretion | Low movement | Mean displacement | Corridor area |
|---|---:|---:|---:|---:|---:|
| 2024 | 2 | 2 | 146 | +1.23 m | 5.44 km² |
| 2025 | 8 | 3 | 139 | +0.75 m | 5.42 km² |
| 2026 | 9 | 11 | 130 | +0.07 m | 5.39 km² |

Each year has 150 segments. Twelve segments start from flagged 2023 banks; 138 are fully usable. The frozen files are under `forecasts/frozen/`; the directory and files are read-only (555/444). `READY` is `d113c99da9fed2270dd2dd4892c6812d5aa5b907f0f4b5e4ff42274886f72f98`. The API re-hashes every frozen file plus the config, dataset, input features, model, metadata, and pipeline code.

## Post-freeze test result

The test years were opened only after the freeze. Fifty-two banks were flagged or invalid and excluded, leaving 398 good bank pairs. All test masks aligned to the canonical grid, had one selected river component, and used no anchor fallback.

| Model | MAE | RMSE | Bias | Within 15 m | Low F1 | Directional |
|---|---:|---:|---:|---:|---:|---:|
| Frozen RandomForest | 9.15 | 15.90 | +2.90 | 0.804 | 0.897 | 0.594 |
| Zero / median | 5.82 | 15.72 | +1.53 | 0.839 | 0.913 | 0.000 |
| Persistence | 13.44 | 39.29 | -5.89 | 0.781 | 0.896 | 0.078 |
| Trend | 13.22 | 30.20 | -0.87 | 0.714 | 0.844 | 0.328 |

The honest headline is that the frozen model does not beat a zero-change baseline on overall MAE. It moves less often than the baseline and has some directional skill, but it misses most large events:

- Observed erosion: 22 events; 3 captured (13.6%); 18 predicted as low movement.
- Observed accretion: 42 events; 2 captured (4.8%); 39 predicted as low movement.
- Observed low movement: 334 events; 318 captured (95.2%).

The model was not changed after seeing these results. Doing so would make the 2024-2026 test period part of training. The application shows the frozen model, the baseline comparison, and the event-capture failure side by side.

## Origin-2024 second look (not blind)

A separate pre-registered refit moved 2024 into training and used 2025-2026 as a second-look score. No fitted candidate beat zero change on 47 rolling-origin folds: zero had pooled validation MAE 13.77 m and the best candidate had 15.34 m. The frozen second-look forecast is therefore the zero-change fallback.

On 256 good pairs, the selected/zero forecast had MAE 5.90 m: 5.55 m in 2025 (n=130) and 6.27 m in 2026 (n=126). The old v1 RandomForest had 10.75 m and 10.12 m in those years, but it started from 2023 and scored different eligible pairs. The comparison is not paired and is not a blind test. The second look is `forecast_supported=false` and is not served by the API or UI. See `reports/second_look_not_blind.md`.

## Measured-bank zones (1989–2026)

The default map is the measured record, not a risk class. The fixed rule uses a 90% block-bootstrap interval with 3-year blocks, a Theil–Sen slope times elapsed years, and 3-transect stretches. It found **0 strong, 0 moderate, 11 land gained, and 39 no-clear** stretches out of 50. Four stretches have undefined intervals and remain no-clear. Forty-nine stretches have geometry; the two border groups with one usable transect do not form a complete interval.

Diagnostics:

| Check | Result |
|---|---|
| Transect half-length | 400 m for all 75 transects |
| Net movement | median 0.0 m; Q1 -144.532 m; Q3 30.156 m; min -347.894 m; max 158.562 m |
| Interval width (46 defined) | median 135.252 m; maximum 534.743 m |
| Channel width | 338.75 m in 1989; 197.72 m in 2024–2026 |
| Early/late rank score | 0.146 (n=39, p=0.374) |
| Land-gained with opposite bank outward | 9 of 11 |

The early/late rank score is below the pre-registered 0.30 minimum, so the relative-ranking layer is omitted. The zone counts and diagnostics are stored in `derived/zones/summary.json` and `reports/zone_diagnostics.json`; the decision is recorded in `reports/DECISIONS.md` entry 20.

## Application

The app is intentionally small and reads local artifacts only; it never recomputes rasters at request time.

- `backend/`: Django + Django REST Framework API; schema and setup notes are in `backend/README.md`.
- `frontend/`: React + Vite + Leaflet interface.
- `derived/zones/`: measured-bank corridor, zones, 2023 edge, and summary diagnostics.
- API:
  - `GET /api/health/`: verifies the frozen manifest, `READY`, all frozen files, and key input hashes.
  - `GET /api/forecast/summary/`: frozen yearly summaries.
  - `GET /api/forecast/maps/?year=2024`: model segments, banklines, bank points, corridor, and observed test banks.
  - `GET /api/forecast/metrics/`: post-freeze test metrics, baselines, event audit, and limitations.
  - `GET /api/forecast/data-quality/`: freeze status, historical QA, test extraction audit, and assumptions.
  - `GET /api/zones/`: measured-bank zones, corridor, edges, fixed-rule counts, diagnostics, and jumps.
  - `GET /api/basemap/image/`: optional offline Sentinel-2 overlay, available only after the owner exports and converts it.
- UI:
  - Full-screen map locked to the corridor with the 2023 edge and measured zones visible by default.
  - Online satellite imagery, street-map switch, and an offline message with measured layers still visible.
  - “Past change” and “2023 to 2026” views, with observed-year pills in the second view.
  - Evidence panels for reliability, test method, and technical details.
  - The experimental model scenario is collapsed under Advanced and is off by default.
  - Responsive layout; checked at 1440 px, 1024 px, and 390 px widths with no page scroll.

The zone map is shown above. The offline fallback uses `data/basemap/sentinel2_overlay.png` and `data/basemap/basemap.json` when both exist; the photo's real bounds come from the metadata so the measured layers stay aligned.

## How to run

From the project root:

```bash
.venv/bin/python backend/manage.py runserver 127.0.0.1:8000
```

In a second terminal:

```bash
cd /media/saad/HDD/rivererosionaccretion/frontend
npm install
npm run dev
```

Open `http://localhost:5173/`. The Vite dev server proxies `/api` to Django. For a production build:

```bash
cd frontend
npm run build
```

The API base can be changed with `VITE_API_BASE`; the dev proxy target can be changed with `VITE_PROXY_TARGET`.

## How to verify

```bash
cd /media/saad/HDD/rivererosionaccretion
PYTHONPATH=src .venv/bin/python -m pytest -q
.venv/bin/python backend/manage.py test api
cd frontend
npm run build
npm test
```

Current result:

- Python pipeline tests: 15 passed, 1 skipped. The skipped test is the pre-freeze lock assertion; the post-freeze gate test runs.
- Django API tests: 13 passed.
- Frontend production build: succeeds.
- Frontend UI-v2 proof (`npm test`): passes with Django and Vite running; checks the API zone contract and fixed rule, zoom lock across buttons, wheel, keyboard, pinch, drag, and shift-drag at 1440 px, 1024 px, and 390 px, zone popup behavior, evidence-panel focus and Escape close, satellite/street switching, offline fallback, attribution, no page scroll, no browser errors, API-derived year labels, and banned-word/wrong-number guards. Screenshots are in `demo/ui-v2/`.

## Limits

- Exact Landsat acquisition dates are unavailable; a nominal 25 March date is used and must be treated as an assumption.
- The 1997 mask is missing. Intervals across that gap cover two years.
- Bank movement is inferred from annual water masks, not measured sediment transport.
- Border clipping can cut the selected river polygon at the image edge.
- Results cover one reach and three test years. They are not a general validation of the method.
- The origin-2024 second look uses 2025-2026 that were already seen in v1; it is not a blind test and does not support the forecast.
- The frozen model is weaker than a zero-change baseline on overall MAE. The UI does not hide this.
- The fixed-zone result has no strong or moderate outward stretches; this is a record limitation, not evidence that the banks are stable.
- The offline photo is not bundled. Without the owner-exported Sentinel-2 asset, the app shows a neutral offline background and a clear message.

## Key files

| Path | Contents |
|---|---|
| `README.md` | Quick start, guardrails, and document map |
| `reports/DECISIONS.md` | Numbered method and product decisions |
| `reports/evaluation.md` | Full post-freeze evaluation tables |
| `reports/second_look_not_blind.md` | Origin-2024 second look, side-by-side score, and limits |
| `reports/model_validation.md` | Backtest and model selection detail |
| `forecasts/frozen/` | Immutable 2024-2026 model output and manifest |
| `forecasts/frozen_origin2024/` | Immutable second-look zero fallback and manifest |
| `evaluation/metrics.json` | Test metrics, baselines, event audit, errors |
| `evaluation_origin2024/` | Second-look metrics, bootstrap, and old-versus-new data |
| `derived/zones/` | Measured-bank zones, corridor, edge, and summary |
| `reports/zone_diagnostics.json` | Zone diagnostics and rank-stability check |
| `demo/ui-v2/` | Browser proof screenshots and `ui-check.json` |
| `scripts/gee_sentinel2_basemap.js` | Manual GEE Sentinel-2 export |
| `scripts/prepare_basemap.py` | GeoTIFF to aligned offline PNG/JSON converter |
| `evaluation/observed_banklines_YYYY.geojson` | Observed test bank layers |
| `models/final_models.joblib` | Frozen per-horizon RandomForest models |
| `datasets/bank_migration_dataset.csv` | Leakage-checked training table |
| `backend/` | Django API, API tests, and `backend/README.md` schema/setup notes |
| `frontend/` | React interface, production build, and `tests/smoke.mjs` UI proof |
