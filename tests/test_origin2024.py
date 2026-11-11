import json

import pandas as pd
import pytest

from riverforecast.config import project_path
from riverforecast.io import sha256_file
from riverforecast.origin2024 import _fold_rows


def test_origin2024_training_never_targets_a_forecast_year():
    df = pd.read_csv(project_path("datasets", "origin2024_bank_migration.csv"))
    assert len(df) == 9750
    assert int(df["usable_for_training"].sum()) == 6053
    assert int((df["target_year"] == 2024).sum()) == 300
    assert int(df["target_year"].max()) == 2024
    assert (df["target_year"] > df["origin_year"]).all()
    assert (df["feature_cutoff_year"] == df["origin_year"]).all()
    assert set(df["horizon_years"]) == {1, 2}
    assert not set(df["target_year"]).intersection({2025, 2026})
    assert not df["sample_id"].duplicated().any()

    folds = _fold_rows(df)
    assert len(folds) == 47
    assert sum(f["n_validation"] for f in folds) == 5392
    for fold in folds:
        assert fold["max_training_target_year"] < fold["origin_year"]
        assert fold["max_validation_target_year"] <= 2024
        assert not set(fold["train"]["target_year"]).intersection({2025, 2026})
        assert not set(fold["validation"]["target_year"]).intersection({2025, 2026})


def test_origin2024_forecast_features_are_unlabelled_and_test_years_only():
    df = pd.read_csv(project_path("datasets", "origin2024_forecast_features.csv"))
    assert len(df) == 300
    assert set(df["origin_year"]) == {2024}
    assert set(df["forecast_year"]) == {2025, 2026}
    assert set(df["horizon_years"]) == {1, 2}
    assert set(df["feature_cutoff_year"]) == {2024}
    assert df["forecast_year"].value_counts().to_dict() == {2025: 150, 2026: 150}
    for forbidden in [
        "target_displacement_m",
        "target_rate_m_per_yr",
        "target_bank_x",
        "target_bank_y",
        "label_quality",
        "usable_for_training",
    ]:
        assert forbidden not in df.columns


def test_origin2024_frozen_artifacts_verify_and_select_zero():
    frozen = project_path("forecasts", "frozen_origin2024")
    manifest_path = frozen / "manifest.json"
    assert (frozen / "READY").read_text(encoding="utf-8").strip() == sha256_file(manifest_path)
    manifest = json.load(open(manifest_path, encoding="utf-8"))
    assert manifest["frozen"] is True
    assert manifest["second_look"] is True
    assert manifest["forecast_supported"] is False
    assert manifest["origin_year"] == 2024
    assert manifest["training_cutoff_year"] == 2024
    assert manifest["selected_model"] == "zero"
    assert set(manifest["forecast_years"]) == {2025, 2026}
    assert manifest["files"]
    for item in manifest["files"]:
        assert sha256_file(frozen / item["name"]) == item["sha256"]
    inputs = manifest["inputs"]
    assert inputs["prereg_sha256"] == sha256_file(project_path("reports", "prereg_origin2024.md"))
    assert inputs["dataset_sha256"] == sha256_file(project_path("datasets", "origin2024_bank_migration.csv"))
    assert inputs["forecast_features_sha256"] == sha256_file(project_path("datasets", "origin2024_forecast_features.csv"))
    for name, expected in inputs["code"].items():
        assert sha256_file(project_path("src", "riverforecast", name)) == expected

    for year in (2025, 2026):
        pred = pd.read_csv(frozen / f"predictions_{year}.csv")
        assert len(pred) == 150
        assert (pred["predicted_displacement_m"] == 0.0).all()
        assert (pred["predicted_class"] == "low_movement").all()
        assert not pred["predicted_to_move"].any()
        for forbidden in ["target_displacement_m", "target_bank_x", "target_bank_y", "observed_displacement_m"]:
            assert forbidden not in pred.columns


def test_origin2024_candidates_fail_the_zero_gate_and_report_is_explicit():
    log = [
        json.loads(line)
        for line in (project_path("forecasts", "frozen_origin2024", "tuning_candidates.jsonl")).read_text(encoding="utf-8").splitlines()
    ]
    assert len(log) == 13
    assert all(c["n_validation"] == 5392 for c in log)
    assert all(c["zero_pooled_mae_m"] == pytest.approx(13.769637, abs=1e-6) for c in log)
    assert not any(c["eligible"] for c in log)

    metrics_path = project_path("evaluation_origin2024", "metrics.json")
    if not metrics_path.exists():
        pytest.skip("One-time origin-2024 evaluation has not run.")
    metrics = json.load(open(metrics_path, encoding="utf-8"))
    assert metrics["second_look"] is True
    assert metrics["forecast_supported"] is False
    assert metrics["origin_year"] == 2024
    assert set(metrics["test_years"]) == {2025, 2026}
    assert metrics["n_pairs"] == 300
    assert metrics["n_good_pairs"] == 256
    assert metrics["selected_model"] == "zero"
    selected = metrics["models"]["selected"]
    zero = metrics["models"]["zero"]
    assert selected["mae_m"] == zero["mae_m"]
    assert selected["mae_m"] == pytest.approx(5.900697771514006)
    assert selected["share_predicted_move"] == 0.0

    report = project_path("reports", "second_look_not_blind.md").read_text(encoding="utf-8")
    assert report.startswith("# Second look, not blind")
    assert "## Old versus new, 2025 and 2026" in report
    assert "not a paired like-for-like test" in report
    assert "`forecast_supported` is false" in report
