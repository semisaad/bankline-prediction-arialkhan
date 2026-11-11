import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import shape

from riverforecast.config import project_path


def test_dataset_has_no_future_or_test_labels():
    checks = json.load(open(project_path("datasets", "leakage_checks.json"), encoding="utf-8"))
    assert checks["all_checks_pass"] is True
    df = pd.read_csv(project_path("datasets", "bank_migration_dataset.csv"))
    assert int(df["target_year"].max()) == 2023
    assert (df["target_year"] > df["origin_year"]).all()
    assert (df["feature_cutoff_year"] == df["origin_year"]).all()
    assert not set(df["target_year"]).intersection({2024, 2025, 2026})
    assert "transect_id" not in json.load(open(project_path("datasets", "feature_dictionary.json")))["features"]


def test_forecast_features_have_no_labels_and_only_test_years():
    f = pd.read_csv(project_path("datasets", "forecast_features_2023.csv"))
    assert len(f) == 450
    assert set(f["forecast_year"]) == {2024, 2025, 2026}
    assert set(f["origin_year"]) == {2023}
    assert set(f["horizon_years"]) == {1, 2, 3}
    for forbidden in ["target_displacement_m", "target_bank_x", "target_bank_y", "label_quality", "usable_for_training"]:
        assert forbidden not in f.columns


def test_selected_model_artifacts_cover_all_horizons():
    meta = json.load(open(project_path("models", "model_metadata.json"), encoding="utf-8"))
    assert meta["selected_model"] == "random_forest"
    assert meta["training_cutoff_year"] == 2023
    artifacts = joblib.load(project_path("models", "final_models.joblib"))
    assert set(artifacts) == {1, 2, 3}
    f = pd.read_csv(project_path("datasets", "forecast_features_2023.csv"))
    for h, art in artifacts.items():
        sub = f[f["horizon_years"] == h]
        p1 = art["pipeline"].predict(sub[art["features"]])
        p2 = art["pipeline"].predict(sub[art["features"]])
        assert np.allclose(p1, p2, atol=1e-10)
        assert np.isfinite(p1).all()


def test_forecast_segments_and_banklines_are_consistent():
    summary = json.load(open(project_path("forecasts", "staging", "forecast_summary.json"), encoding="utf-8"))
    assert summary["origin_year"] == 2023
    assert set(summary["forecast_years"]) == {2024, 2025, 2026}
    for year in [2024, 2025, 2026]:
        seg = pd.read_csv(project_path("forecasts", "staging", f"segments_{year}.csv"))
        assert len(seg) == 150
        assert set(seg["forecast_class"]).issubset({"erosion", "accretion", "low_movement"})
        erosion = seg["predicted_displacement_m"] > 15.0
        accretion = seg["predicted_displacement_m"] < -15.0
        assert (seg.loc[erosion, "forecast_class"] == "erosion").all()
        assert (seg.loc[accretion, "forecast_class"] == "accretion").all()
        assert (seg.loc[~(erosion | accretion), "forecast_class"] == "low_movement").all()
        assert np.allclose(np.hypot(seg["predicted_displacement_m"], 0), seg["abs_displacement_m"])
        gj = json.load(open(project_path("forecasts", "staging", f"banklines_{year}.geojson"), encoding="utf-8"))
        corridor = [f for f in gj["features"] if f["properties"].get("kind") == "corridor"]
        assert len(corridor) == 1
        geom = shape(corridor[0]["geometry"])
        assert geom.is_valid
        assert geom.area > 0
        assert corridor[0]["properties"]["repair_applied"] is False
