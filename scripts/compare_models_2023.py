#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import math
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import sklearn
from sklearn.ensemble import GradientBoostingRegressor, RandomForestRegressor
from sklearn.impute import SimpleImputer
from sklearn.metrics import f1_score
from sklearn.pipeline import Pipeline

try:
    import lightgbm as lgb
    import xgboost as xgb
    from catboost import CatBoostRegressor
    from lightgbm import LGBMRegressor
    from xgboost import XGBRegressor
except ImportError as exc:
    raise SystemExit(
        "Missing optional model library. Install xgboost, lightgbm and catboost "
        "outside the app environment, then put that directory on PYTHONPATH."
    ) from exc

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
except ImportError as exc:
    raise SystemExit("matplotlib is required for the comparison figure.") from exc


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "reports" / "model_comparison_2024_2026"
FIG_DIR = ROOT / "reports" / "figures"
TRAIN_PATH = ROOT / "datasets" / "bank_migration_dataset.csv"
TEST_PATH = ROOT / "datasets" / "forecast_features_2023.csv"
TRUTH_PATH = ROOT / "evaluation" / "predictions.csv"
META_PATH = ROOT / "models" / "model_metadata.json"
TOL = 15.0

MODEL_LABELS = {
    "zero": "Zero change",
    "random_forest": "Random forest",
    "gradient_boosting": "Gradient boosting",
    "xgboost": "XGBoost",
    "lightgbm": "LightGBM",
    "catboost": "CatBoost",
}

MODEL_SETTINGS = {
    "random_forest": {
        "n_estimators": 300,
        "min_samples_leaf": 5,
        "max_features": 0.75,
        "random_state": 42,
        "n_jobs": 4,
    },
    "gradient_boosting": {
        "n_estimators": 300,
        "learning_rate": 0.05,
        "max_depth": 3,
        "min_samples_leaf": 20,
        "subsample": 1.0,
        "random_state": 42,
    },
    "xgboost": {
        "n_estimators": 300,
        "learning_rate": 0.05,
        "max_depth": 3,
        "min_child_weight": 5,
        "subsample": 0.9,
        "colsample_bytree": 0.9,
        "reg_lambda": 1.0,
        "objective": "reg:squarederror",
        "tree_method": "hist",
        "n_jobs": 4,
        "random_state": 42,
        "verbosity": 0,
    },
    "lightgbm": {
        "n_estimators": 300,
        "learning_rate": 0.05,
        "num_leaves": 15,
        "min_child_samples": 20,
        "subsample": 0.9,
        "subsample_freq": 1,
        "colsample_bytree": 0.9,
        "reg_lambda": 1.0,
        "random_state": 42,
        "n_jobs": 4,
        "verbose": -1,
    },
    "catboost": {
        "iterations": 300,
        "learning_rate": 0.05,
        "depth": 4,
        "l2_leaf_reg": 3.0,
        "loss_function": "RMSE",
        "random_seed": 42,
        "thread_count": 4,
        "verbose": False,
        "allow_writing_files": False,
    },
}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def make_model(name: str):
    if name == "random_forest":
        return RandomForestRegressor(**MODEL_SETTINGS[name])
    if name == "gradient_boosting":
        return GradientBoostingRegressor(**MODEL_SETTINGS[name])
    if name == "xgboost":
        return XGBRegressor(**MODEL_SETTINGS[name])
    if name == "lightgbm":
        return LGBMRegressor(**MODEL_SETTINGS[name])
    if name == "catboost":
        return CatBoostRegressor(**MODEL_SETTINGS[name])
    raise ValueError(name)


def metric_block(y: np.ndarray, p: np.ndarray) -> dict:
    err = p - y
    abs_err = np.abs(err)
    low = np.abs(y) <= TOL
    pred_low = np.abs(p) <= TOL
    moving = ~low
    return {
        "n": int(len(y)),
        "mae_m": float(np.mean(abs_err)),
        "rmse_m": float(np.sqrt(np.mean(err**2))),
        "bias_m": float(np.mean(err)),
        "within_15m": float(np.mean(abs_err <= TOL)),
        "low_movement_f1": float(f1_score(low, pred_low, zero_division=0)),
        "low_movement_precision": float(
            np.sum(low & pred_low) / max(np.sum(pred_low), 1)
        ),
        "low_movement_recall": float(
            np.sum(low & pred_low) / max(np.sum(low), 1)
        ),
        "directional_accuracy_moving": float(
            np.mean(np.sign(p[moving]) == np.sign(y[moving]))
        ) if moving.any() else None,
        "false_movement_rate": float(np.mean(~pred_low[low])) if low.any() else None,
        "missed_movement_rate": float(np.mean(pred_low[moving])) if moving.any() else None,
        "mae_low_m": float(np.mean(abs_err[low])) if low.any() else None,
        "mae_moving_m": float(np.mean(abs_err[moving])) if moving.any() else None,
        "closer_than_zero_n": int(np.sum(abs_err < np.abs(y))),
        "farther_than_zero_n": int(np.sum(abs_err > np.abs(y))),
        "tie_zero_n": int(np.sum(abs_err == np.abs(y))),
        "prediction_min_m": float(np.min(p)),
        "prediction_max_m": float(np.max(p)),
    }


def event_block(y: np.ndarray, p: np.ndarray, classes: np.ndarray) -> dict:
    out = {}
    for cls in ("erosion", "accretion", "low_movement"):
        mask = classes == cls
        if not mask.any():
            out[cls] = {"n": 0}
            continue
        pred_cls = np.where(p[mask] > TOL, "erosion", np.where(p[mask] < -TOL, "accretion", "low_movement"))
        out[cls] = {
            "n": int(mask.sum()),
            "captured": int((pred_cls == cls).sum()),
            "capture_rate": float(np.mean(pred_cls == cls)),
            "predicted_low": int((pred_cls == "low_movement").sum()),
            "opposite_direction": int(
                np.sum((p[mask] > TOL) & (y[mask] < -TOL))
                + np.sum((p[mask] < -TOL) & (y[mask] > TOL))
            ),
            "mean_observed_m": float(np.mean(y[mask])),
            "mean_predicted_m": float(np.mean(p[mask])),
            "mae_m": float(np.mean(np.abs(p[mask] - y[mask]))),
        }
    return out


def clean_json(value):
    if isinstance(value, dict):
        return {str(k): clean_json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean_json(v) for v in value]
    if isinstance(value, (np.floating, float)):
        return None if math.isnan(float(value)) else float(value)
    if isinstance(value, (np.integer, int)):
        return int(value)
    return value


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    FIG_DIR.mkdir(parents=True, exist_ok=True)

    metadata = json.loads(META_PATH.read_text())
    features = list(metadata["features"])
    if len(features) != 20:
        raise ValueError(f"Expected 20 frozen features, found {len(features)}")

    train = pd.read_csv(TRAIN_PATH)
    train = train[
        (train["target_year"] <= 2023) & (train["usable_for_training"])
    ].copy()
    if train.empty or train["target_year"].max() > 2023:
        raise ValueError("Training rows include targets after 2023")
    if train[features].shape[1] != len(features):
        raise ValueError("Feature mismatch")

    test = pd.read_csv(TEST_PATH)
    truth = pd.read_csv(TRUTH_PATH)
    truth = truth.rename(columns={"year": "target_year"})
    truth_cols = [
        "target_year",
        "transect_id",
        "side",
        "observed_displacement_m",
        "observed_class",
        "label_quality",
        "model_prediction_m",
        "model_abs_error_m",
    ]
    test = test.merge(
        truth[truth_cols],
        on=["target_year", "transect_id", "side"],
        how="left",
        validate="one_to_one",
    )
    if test["observed_displacement_m"].isna().any():
        raise ValueError("Missing observed labels for test rows")
    if test["target_year"].min() != 2024 or test["target_year"].max() != 2026:
        raise ValueError("Test years must be 2024-2026")
    if train["sample_id"].isin(test["sample_id"]).any():
        raise ValueError("Training and test sample IDs overlap")
    forbidden = {
        "target_displacement_m",
        "target_rate_m_per_yr",
        "target_bank_x",
        "target_bank_y",
    }
    if forbidden & set(test.columns):
        raise ValueError("Test feature table contains target columns")

    good = test[test["label_quality"] == "good"].copy()
    if len(good) != 398:
        raise ValueError(f"Expected 398 valid test rows, found {len(good)}")

    y_all = good["observed_displacement_m"].to_numpy(dtype=float)
    classes_all = good["observed_class"].to_numpy(dtype=object)
    years_all = good["target_year"].to_numpy(dtype=int)

    predictions = good[
        [
            "sample_id",
            "target_year",
            "horizon_years",
            "transect_id",
            "side",
            "reach",
            "observed_displacement_m",
            "observed_class",
            "label_quality",
            "model_prediction_m",
        ]
    ].copy()
    predictions = predictions.rename(columns={"model_prediction_m": "frozen_random_forest"})

    results = {
        "created_utc": pd.Timestamp.now(tz="UTC").isoformat(),
        "status": "post_hoc_isolated_comparison",
        "training_cutoff_year": 2023,
        "test_years": [2024, 2025, 2026],
        "features": features,
        "n_train_rows": int(len(train)),
        "n_train_rows_by_horizon": {
            str(h): int(len(train[train["horizon_years"] == h]))
            for h in sorted(train["horizon_years"].unique())
        },
        "n_test_rows": int(len(test)),
        "n_valid_test_rows": int(len(good)),
        "valid_rows_by_year": {
            str(y): int((years_all == y).sum()) for y in sorted(np.unique(years_all))
        },
        "flagged_rows_by_year": {
            str(y): int(((test["target_year"] == y) & (test["label_quality"] != "good")).sum())
            for y in (2024, 2025, 2026)
        },
        "model_settings": MODEL_SETTINGS,
        "versions": {
            "python": sys.version.split()[0],
            "pandas": pd.__version__,
            "numpy": np.__version__,
            "scikit_learn": sklearn.__version__,
            "xgboost": xgb.__version__,
            "lightgbm": lgb.__version__,
            "catboost": __import__("catboost").__version__,
        },
        "source_sha256": {
            "train": sha256(TRAIN_PATH),
            "test_features": sha256(TEST_PATH),
            "truth": sha256(TRUTH_PATH),
            "model_metadata": sha256(META_PATH),
        },
        "leakage_checks": {
            "max_training_target_year": int(train["target_year"].max()),
            "train_test_sample_overlap": 0,
            "test_target_columns_present": 0,
            "test_feature_cutoff_max": int(test["feature_cutoff_year"].max()),
        },
        "models": {},
        "per_year": {},
        "feature_importance": {},
    }

    pred_arrays = {"zero": np.zeros(len(good), dtype=float)}
    eval_mask = np.ones(len(good), dtype=bool)
    frozen_pred = good["model_prediction_m"].to_numpy(dtype=float)
    results["frozen_reference"] = {
        "mae_m": float(np.mean(np.abs(frozen_pred - y_all))),
        "max_abs_diff_vs_retrained_rf": None,
    }

    for name in ("random_forest", "gradient_boosting", "xgboost", "lightgbm", "catboost"):
        started = time.perf_counter()
        pred = np.full(len(test), np.nan)
        importances = []
        for horizon in (1, 2, 3):
            train_h = train[train["horizon_years"] == horizon]
            model = Pipeline(
                [
                    ("imputer", SimpleImputer(strategy="median")),
                    ("model", make_model(name)),
                ]
            )
            model.fit(
                train_h[features],
                train_h["target_displacement_m"].to_numpy(dtype=float),
            )
            year = 2023 + horizon
            idx = test.index[test["target_year"] == year]
            pred[idx] = model.predict(test.loc[idx, features])
            fitted = model.named_steps["model"]
            if hasattr(fitted, "get_feature_importance"):
                values = np.asarray(fitted.get_feature_importance(), dtype=float)
            else:
                values = np.asarray(fitted.feature_importances_, dtype=float)
            importances.append(values / values.sum())
        pred = pred[test.index.isin(good.index)]
        if np.isnan(pred).any():
            raise ValueError(f"{name} produced missing predictions")
        pred_arrays[name] = pred
        elapsed = time.perf_counter() - started
        m = metric_block(y_all, pred)
        m["train_seconds"] = round(elapsed, 3)
        m["event_audit"] = event_block(y_all, pred, classes_all)
        results["models"][name] = m
        predictions[name] = pred
        mean_importance = np.mean(np.vstack(importances), axis=0)
        order = np.argsort(mean_importance)[::-1][:12]
        results["feature_importance"][name] = [
            {"feature": features[i], "importance": float(mean_importance[i])}
            for i in order
        ]

    results["models"]["zero"] = metric_block(y_all, pred_arrays["zero"])
    results["models"]["zero"]["train_seconds"] = 0.0
    results["models"]["zero"]["event_audit"] = event_block(
        y_all, pred_arrays["zero"], classes_all
    )
    predictions["zero"] = pred_arrays["zero"]
    results["frozen_reference"]["max_abs_diff_vs_retrained_rf"] = float(
        np.max(np.abs(predictions["frozen_random_forest"] - predictions["random_forest"]))
    )

    for year in (2024, 2025, 2026):
        mask = years_all == year
        results["per_year"][str(year)] = {}
        for name, pred in pred_arrays.items():
            results["per_year"][str(year)][name] = metric_block(y_all[mask], pred[mask])

    order = sorted(
        (name for name in results["models"] if name != "zero"),
        key=lambda name: results["models"][name]["mae_m"],
    )
    results["ranking_by_test_mae"] = order
    results["best_nonzero_model"] = order[0] if order else None
    results["zero_baseline_mae_m"] = results["models"]["zero"]["mae_m"]
    results["any_model_beats_zero_mae"] = bool(
        order and results["models"][order[0]]["mae_m"] < results["zero_baseline_mae_m"]
    )

    for name in ("zero", "random_forest", "gradient_boosting", "xgboost", "lightgbm", "catboost"):
        predictions[f"{name}_error_m"] = predictions[name] - predictions["observed_displacement_m"]

    results = clean_json(results)
    (OUT_DIR / "results.json").write_text(json.dumps(results, indent=2) + "\n")
    predictions.to_csv(OUT_DIR / "predictions.csv", index=False)

    rows = []
    for name in ("zero", "random_forest", "gradient_boosting", "xgboost", "lightgbm", "catboost"):
        m = results["models"][name]
        rows.append(
            {
                "model": name,
                "label": MODEL_LABELS[name],
                "mae_m": m["mae_m"],
                "rmse_m": m["rmse_m"],
                "bias_m": m["bias_m"],
                "within_15m": m["within_15m"],
                "low_movement_f1": m["low_movement_f1"],
                "directional_accuracy_moving": m["directional_accuracy_moving"],
                "missed_movement_rate": m["missed_movement_rate"],
                "mae_moving_m": m["mae_moving_m"],
                "closer_than_zero_n": m["closer_than_zero_n"],
                "train_seconds": m["train_seconds"],
            }
        )
    pd.DataFrame(rows).to_csv(OUT_DIR / "overall_metrics.csv", index=False)

    year_rows = []
    for year in (2024, 2025, 2026):
        for name in order + ["zero"]:
            m = results["per_year"][str(year)][name]
            year_rows.append(
                {
                    "year": year,
                    "model": name,
                    "mae_m": m["mae_m"],
                    "rmse_m": m["rmse_m"],
                    "within_15m": m["within_15m"],
                    "directional_accuracy_moving": m["directional_accuracy_moving"],
                    "missed_movement_rate": m["missed_movement_rate"],
                }
            )
    pd.DataFrame(year_rows).to_csv(OUT_DIR / "by_year.csv", index=False)

    imp_rows = []
    for name, values in results["feature_importance"].items():
        for rank, item in enumerate(values, 1):
            imp_rows.append({"model": name, "rank": rank, **item})
    pd.DataFrame(imp_rows).to_csv(OUT_DIR / "feature_importance.csv", index=False)

    fig, axes = plt.subplots(1, 2, figsize=(13, 5.4), dpi=170)
    models = order + ["zero"]
    labels = [MODEL_LABELS[m] for m in models]
    colors = {
        "random_forest": "#2b6cb0",
        "gradient_boosting": "#6b46c1",
        "xgboost": "#c05621",
        "lightgbm": "#2f855a",
        "catboost": "#b83280",
        "zero": "#4a5568",
    }
    axes[0].bar(labels, [results["models"][m]["mae_m"] for m in models], color=[colors[m] for m in models])
    for i, m in enumerate(models):
        axes[0].text(i, results["models"][m]["mae_m"] + 0.16, f"{results['models'][m]['mae_m']:.2f}", ha="center", va="bottom", fontsize=8)
    axes[0].set_ylabel("Mean absolute error (m)")
    axes[0].set_title("Overall test error, lower is better")
    axes[0].tick_params(axis="x", rotation=28, labelsize=8)
    axes[0].grid(axis="y", alpha=0.2)
    axes[0].set_axisbelow(True)

    year_colors = {2024: "#2b6cb0", 2025: "#dd6b20", 2026: "#2f855a"}
    width = 0.25
    x = np.arange(len(models))
    for offset, year in zip((-width, 0, width), (2024, 2025, 2026)):
        vals = [results["per_year"][str(year)][m]["mae_m"] for m in models]
        axes[1].bar(x + offset, vals, width=width, label=str(year), color=year_colors[year])
    axes[1].set_xticks(x, labels, rotation=28, ha="right", fontsize=8)
    axes[1].set_ylabel("Mean absolute error (m)")
    axes[1].set_title("Test error by forecast year")
    axes[1].grid(axis="y", alpha=0.2)
    axes[1].set_axisbelow(True)
    axes[1].legend(title="Test year", frameon=False, fontsize=8)
    fig.suptitle("2023-trained models tested on 2024–2026", fontsize=12, fontweight="bold")
    fig.tight_layout()
    fig.savefig(FIG_DIR / "model_comparison_2024_2026.png", bbox_inches="tight")
    plt.close(fig)

    print(json.dumps({
        "ranking": order,
        "best_nonzero": order[0],
        "zero_mae": results["zero_baseline_mae_m"],
        "any_model_beats_zero": results["any_model_beats_zero_mae"],
        "frozen_max_abs_diff": results["frozen_reference"]["max_abs_diff_vs_retrained_rf"],
        "out": str(OUT_DIR),
    }, indent=2))


if __name__ == "__main__":
    main()
