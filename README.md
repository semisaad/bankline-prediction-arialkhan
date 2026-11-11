# Riverbank Change Monitor, 1989–2026

A reproducible Landsat-based record of bank movement for one reach of the Arial Khan River near Madaripur, Bangladesh. A model was frozen after training through 2023 and tested once against 2024–2026 observations. The default map shows a forecast-derived risk-zone scenario; the measured 1989–2026 record remains a separate tab. The model output is still not a validated erosion forecast or a safety rating.

**Honest headline:** the frozen random forest does not beat a zero-change baseline on overall test MAE (9.15 m vs 5.82 m). It is retained unchanged because it was selected and frozen before the test years were opened. It has some directional skill but misses most large events. Do not use it as a precise displacement predictor.

**Origin-2024 second look (not blind):** a separate pre-registered refit moved 2024 into training. No fitted candidate beat zero change on 47 rolling-origin folds, so its frozen forecast is the zero-change fallback. Its 2025 and 2026 MAE was 5.55 m and 6.27 m, versus 10.75 m and 10.12 m for the old v1 random forest, but the runs use different origins and eligible pairs and are not a paired comparison. See `reports/second_look_not_blind.md`.

## What is here

- `src/riverforecast/`: inventory, harmonization, river extraction, transects, bank measurement, dataset construction, rolling validation, model output, and evaluation.
- `forecasts/frozen/`: read-only 2024–2026 model outputs, manifest, and `READY` hash.
- `forecasts/frozen_origin2024/`: read-only second-look zero fallback for 2025–2026; not served by the API.
- `evaluation/`: post-freeze test metrics, predictions, audit, observed banks, and figures.
- `evaluation_origin2024/`: one-time second-look score and old-versus-new comparison.
- `derived/zones/`: corridor, 1989–2026 measured-bank zone layer, 2023 edge, and summary diagnostics.
- `backend/`: Django API. See `backend/README.md` for setup and endpoint schema.
- `frontend/`: React + Vite + Leaflet interface.
- `config/ui.json`: map, basemap, layer, and fixed-rule settings.
- `reports/`: method reports, decisions, frozen model outputs, evaluation, and the final report.
- `demo/ui-v2/`: UI-v2 screenshots and browser-proof artifacts.
- `scripts/`: pipeline utilities, including the optional Sentinel-2 basemap export and conversion helpers.
- `tests/`: pipeline and contract tests.

## Quick start

The API only needs the already-frozen artifacts.

```bash
cd /media/saad/HDD/rivererosionaccretion
python3 -m venv .venv
.venv/bin/pip install -r backend/requirements.txt
.venv/bin/python backend/manage.py runserver 127.0.0.1:8000
```

In another terminal:

```bash
cd /media/saad/HDD/rivererosionaccretion/frontend
npm install
npm run dev
```

Open `http://localhost:5173/`. The Vite dev server proxies `/api` to Django.

## What the UI shows

- A full-screen map locked to the measured corridor. The default **Risk zones** view draws red ribbons where the frozen model predicts outward movement and green ribbons where it predicts inward movement; low-movement segments are counted but not drawn.
- Scenario pills for 2024, 2025, and 2026. The bottom-left panel shows the segment counts, the largest-shift shortcut, the 2023 edge, the predicted bank, and a clear scenario-not-safety warning.
- A **Past change** tab for the measured 1989–2026 record, including the 11 land-gain and 39 no-clear stretches. An **Observed years** tab compares the 2023 edge with a selected measured edge.
- Satellite imagery when online, a street-map fallback, and a neutral offline state with the risk zones still available.
- Evidence panels for the fixed-rule counts, diagnostics, test result, and file provenance.
- The forecast-derived risk colors are a presentation of the frozen scenario, not the pre-registered long-term zone tiers. Those tiers remain **0 strong, 0 moderate, 11 land gained, and 39 no-clear** out of 50; the 0.15 early/late rank score is below the 0.30 threshold, so the relative-ranking layer is not shown.
- The raw model bank lines remain collapsed under Advanced and off by default.

## Verify

```bash
cd /media/saad/HDD/rivererosionaccretion
PYTHONPATH=src .venv/bin/python -m pytest -q
.venv/bin/python backend/manage.py test api

cd frontend
npm run build
npm test
```

`npm test` expects Django and Vite to be running, plus Chrome or Chromium. It checks the measured-zone contract, fixed rule, forecast risk-zone contract, default risk view, risk-zone rendering and popup, zoom lock across buttons, wheel, keyboard, pinch, drag, and shift-drag at three widths, evidence-panel focus and Escape close, satellite/street switching, the offline risk state, attribution, no page scroll, no browser errors, API-derived year labels, and banned-word/wrong-number guards. It writes screenshots and `ui-check.json` to `demo/ui-v2/`. Set `CHROMIUM_PATH` if the browser is not found automatically.

Current result: Python **15 passed, 1 skipped**; Django **16 passed**; production build succeeds; UI-v2 proof passes.

## Optional offline satellite photo

The owner runs this once with their Earth Engine account:

1. Open `scripts/gee_sentinel2_basemap.js` in the Earth Engine Code Editor, run the export task, and download the GeoTIFF.
2. Convert it locally:
   ```bash
   .venv/bin/python scripts/prepare_basemap.py /path/to/sentinel2_basemap_raw.tif
   ```
3. Keep both generated files: `data/basemap/sentinel2_overlay.png` and `data/basemap/basemap.json`.
4. Compare the photo with the measured bands at the river bend, bridge, and town edge. The overlay uses its real metadata bounds, so the measured data is not shifted.
5. Restart nothing: the API reads the files per request and `fallback_available` switches on.

Without those files, the map still works online and shows a clear offline message when satellite tiles fail.

## Guardrails

- `forecasts/frozen/` is read-only. The API re-hashes every frozen file plus config, dataset, input features, model, metadata, and pipeline code.
- 2024–2026 were opened only after the freeze. Do not retrain, refreeze, retune, or use those years for model selection.
- A new model needs an independent reach or 2027+ observations before it can be promoted.
- The fixed zone rule and the 0/0/11/39 result are frozen before any threshold change. See `reports/DECISIONS.md` entries 19–22. The forecast risk-zone view is a separate scenario overlay; it does not change that result or create a new validated risk class (entry 28).
- The risk zones use the frozen model’s 15 m tolerance and are clipped ribbon geometry derived at request time. They do not retrain, refreeze, or retune the model.
- V2 experiments with neighbour/history, area, and external flow/rain features did not produce a credible improvement; see `reports/DECISIONS.md` entries 17–18.
- The origin-2024 second look is a zero fallback and is not served by the API/UI; see `reports/DECISIONS.md` entry 23.

## Main documents

| Document | Purpose |
|---|---|
| `reports/final_report.md` | End-to-end results, method, limits, and run instructions |
| `reports/DECISIONS.md` | Append-only numbered method and product decisions |
| `reports/zone_diagnostics.json` | Zone diagnostics: transect length, net movement, interval width, width by year, and rank stability |
| `reports/forecast_freeze.md` | Frozen artifact and input hashes |
| `reports/evaluation.md` | Post-freeze test tables |
| `reports/forecast_2025_alignment.md` | 2025 predicted-vs-observed bankline alignment, error distribution, and large-movement failure modes |
| `reports/model_comparison_2024_2026.md` | Post-hoc comparison of five 2023-trained models on 2024–2026; none beats no change on MAE |
| `reports/second_look_not_blind.md` | Origin-2024 second look and old-versus-new score |
| `reports/model_validation.md` | Rolling-origin validation and model selection |
| `reports/dataset.md` | Feature and label contract |
| `backend/README.md` | API setup, artifact contract, endpoints, and error handling |
