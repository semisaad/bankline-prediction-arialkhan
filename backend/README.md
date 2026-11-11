# Riverbank Monitor API

Read-only Django + Django REST Framework service for the frozen 2024–2026 model outputs, forecast-derived risk-zone geometry, and the measured-bank zone layer. It reads local artifacts and never recomputes rasters. Every request depends on `forecasts/frozen/manifest.json`, `forecasts/frozen/READY`, the frozen artifacts, and the model/config/code hashes recorded in the manifest, except the measured-only `/api/zones/` endpoint and the basemap image.

## Setup

From the project root:

```bash
python3 -m venv .venv
.venv/bin/pip install -r backend/requirements.txt
.venv/bin/python backend/manage.py migrate
.venv/bin/python backend/manage.py runserver 127.0.0.1:8000
```

The API root is `/api/`. The frontend on `http://localhost:5173` proxies `/api` to `http://127.0.0.1:8000`.

## Environment

| Variable | Default | Purpose |
|---|---|---|
| `RIVER_PROJECT_ROOT` | repository root | Directory containing `forecasts/`, `evaluation/`, `models/`, etc. |
| `DJANGO_SECRET_KEY` | development placeholder | Set a unique value outside local development. |
| `DJANGO_DEBUG` | `1` | Set `0` in production. |
| `DJANGO_ALLOWED_HOSTS` | `127.0.0.1,localhost` | Comma-separated host allowlist. |
| `CORS_ALLOWED_ORIGINS` | `http://localhost:5173,http://127.0.0.1:5173` | Comma-separated frontend origins. |
| `DJANGO_LOG_LEVEL` | `INFO` | Console log level. |

## Artifact contract

The API refuses to claim verified model outputs unless all of these hold:

- `manifest.frozen` is `true`.
- `READY` equals the SHA-256 of `manifest.json`.
- Every file in `manifest.files` exists with the recorded hash and size.
- The config, dataset, input features, model artifact, and model metadata hashes match.
- The pipeline code hashes in `manifest.inputs.code` match `src/riverforecast/`.

`GET /api/health/` returns HTTP 200 only when `status` is `ok`; otherwise it returns HTTP 503. The summary, maps, metrics, and risk-zones endpoints also verify provenance and return HTTP 503 rather than serving unverified model outputs. The risk-zones endpoint then derives display ribbons from the verified frozen segments and the 2023 observed bank line; it does not use the frozen model to make a new prediction or alter thresholds. The zones endpoint reads the measured derived assets and does not depend on the frozen model. The data-quality endpoint reports the failure instead, so it can be used to diagnose it.

## Endpoints

All endpoints are `GET` and return JSON. Error responses have the shape `{"error": "message"}`.

### `GET /api/health/`

Returns provenance state and every individual check.

```json
{
  "status": "ok",
  "service": "river-bank-forecast-api",
  "project_root": "/path/to/project",
  "frozen": true,
  "origin_year": 2023,
  "forecast_years": [2024, 2025, 2026],
  "training_cutoff_year": 2023,
  "model": "random_forest",
  "model_label": "Random forest",
  "checks": [{"name": "ready_hash", "ok": true, "detail": "..."}],
  "errors": [],
  "ready_sha256": "..."
}
```

### `GET /api/forecast/summary/`

Returns the frozen summary. Key fields: `status`, `created_utc`, `origin_year`, `forecast_years`, `training_cutoff_year`, `model`, `model_label`, `features`, `low_movement_tolerance_m`, `implausible_threshold_m`, `n_transects`, `n_segments_per_year`, `by_year`.

Each `by_year["YYYY"]` object contains `year`, `horizon_years`, `n`, class `counts`, `quality_counts`, displacement statistics (`mean_m`, `median_m`, `min_m`, `max_m`, `mean_abs_m`, `mean_ensemble_std_m`), `by_reach`, `banklines`, and artifact `files`.

### `GET /api/forecast/maps/?year=2024`

`year` is required and must be one of `2024`, `2025`, `2026`; anything else returns HTTP 400. The response contains:

- `segments`: 150 transect bank segments with `transect_id`, `side`, `reach`, `predicted_displacement_m`, `predicted_rate_m_per_yr`, class, uncertainty, and origin-quality fields.
- `banklines`: three GeoJSON features — left model bank, right model bank, and model corridor.
- `bank_points`: 150 model bank points.
- `observed_banklines` / `observed_bank_points`: post-freeze observed test banks, or `null` when unavailable.
- `observed_available`: boolean.
- `summary`, `retrospective_metrics`, `legend`, `note`, and `observed_note`.

All GeoJSON is EPSG:4326 (longitude/latitude). Positive displacement means erosion (outward); negative means accretion (inward).

### `GET /api/forecast/risk-zones/?year=2024`

`year` is required and must be one of `2024`, `2025`, `2026`; anything else returns HTTP 400. This endpoint verifies the frozen artifacts, then builds display-only ribbon polygons between the 2023 observed bank and the selected frozen year's predicted bank. Ribbons are clipped to the forecast corridor. A bank interval is included when either endpoint is non-low; when the endpoints disagree, the larger absolute displacement sets the class. Invalid polygons are repaired with `shapely.make_valid` at request time.

Response fields: `year`, `origin_year`, `threshold_m`, `total_segments`, `segment_counts`, `zone_counts`, `zones`, `predicted_banklines`, `timeline`, `legend`, `largest`, `low_movement_segments_drawn`, `note`, and `limitations`. `zones` and `predicted_banklines` are GeoJSON FeatureCollections in EPSG:4326.

| Year | Erosion segments | Accretion segments | Low movement | Zone features |
|---|---:|---:|---:|---:|
| 2024 | 2 | 2 | 146 | 3 |
| 2025 | 8 | 3 | 139 | 8 |
| 2026 | 9 | 11 | 130 | 14 |

The classes use the frozen 15 m low-movement tolerance. Low-movement intervals are counted in `segment_counts` but not drawn. `zone_counts` counts connected display features and can differ from the segment counts. The risk zones are a scenario overlay, not a safety rating, a validated erosion forecast, or the pre-registered 1989–2026 zone tiers from `/api/zones/`.

### `GET /api/forecast/metrics/`

Returns post-freeze retrospective metrics. Key fields: `kind`, `test_years`, `origin_year`, `n_pairs`, `n_good_pairs`, `n_flagged_or_invalid`, `low_movement_tolerance_m`, `models`, `event_audit`, `largest_errors`, `selected_model`, `selection_rule`, `validation_aggregate_metrics`, `validation_origins`, `test_data_audit`, `headline`, and `limitations`.

`models` includes `random_forest`, `zero`, `median`, `persistence`, and `trend` entries with `mae_m`, `rmse_m`, `bias_m`, `within_15m`, `low_movement_f1`, `directional_accuracy_moving`, and related fields. `headline.frozen_model_improves_mae_over_zero` is the honest comparison; the current frozen model does not beat zero-change MAE.

### `GET /api/forecast/data-quality/`

Returns `inventory`, `historical_qa`, `test_extraction`, `freeze`, and `warnings`. `freeze` is the same provenance object used by health.

### `GET /api/zones/`

Returns the measured-bank record for 1989–2026. Key fields: `total_stretches`, `counts`, `tier_order`, `tier_labels`, `tier_colors`, `clear_layer_label`, `relative_available`, `relative_layer`, `diagnostics`, `bounds`, `jumps`, `years`, `starting_year`, `latest_year`, `observed_years`, `features_with_geometry`, `undefined_intervals`, `sample`, `zones`, `corridor`, `edges`, `fallback_available`, `fallback_image_url`, and `fallback_bounds`.

`zones`, `corridor`, and `edges` are GeoJSON FeatureCollections in EPSG:4326. The fixed rule is applied before serving: STRONG lower bound at least 150 m, MODERATE lower bound above zero and at least 30 m, LAND GAINED upper bound at most -30 m, and NO CLEAR otherwise. The current counts are 0 STRONG, 0 MODERATE, 11 LAND GAINED, and 39 NO CLEAR out of 50. The relative layer is omitted because the early/late rank score is below 0.30.

### `GET /api/basemap/image/`

Returns the optional offline Sentinel-2 PNG when both `data/basemap/sentinel2_overlay.png` and a valid `data/basemap/basemap.json` are present. Otherwise returns HTTP 404 with an error object. `basemap.json` must contain a `bounds` array `[west, south, east, north]`; the frontend uses it so the photo stays aligned even when the export footprint is larger than the corridor.

## Tests

```bash
.venv/bin/python backend/manage.py test api
```

The tests cover the health contract, summary, all three map years, invalid-year handling, refusal of unverified artifacts, metrics/baseline honesty, the risk-zone contract and yearly counts, high-segment coverage, CORS, data-quality provenance, the measured-zone contract, the fixed-rule tiers, zone geometry inside the corridor, and the zone sample calculation.
