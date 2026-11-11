from __future__ import annotations

import datetime as dt
import hashlib
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor, RandomForestRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.metrics import f1_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from .config import ensure_output_dirs, load_config, project_path
from .dataset import FEATURES
from .io import write_json

MODEL_LABELS = {
    "zero": "Zero change",
    "median": "Training median",
    "persistence": "Persistence of last rate",
    "trend": "Historic rate trend",
    "ridge": "Ridge regression",
    "random_forest": "Random forest",
    "hist_gradient_boosting": "Histogram gradient boosting",
}
ML_MODELS = ["ridge", "random_forest", "hist_gradient_boosting"]
BASELINES = ["zero", "median", "persistence", "trend"]


def _pipeline(kind: str) -> Pipeline:
    if kind == "ridge":
        return Pipeline(
            [
                ("imputer", SimpleImputer(strategy="median")),
                ("scaler", StandardScaler()),
                ("model", Ridge(alpha=10.0)),
            ]
        )
    if kind == "random_forest":
        return Pipeline(
            [
                ("imputer", SimpleImputer(strategy="median")),
                (
                    "model",
                    RandomForestRegressor(
                        n_estimators=300,
                        min_samples_leaf=5,
                        max_features=0.75,
                        n_jobs=4,
                        random_state=42,
                    ),
                ),
            ]
        )
    if kind == "hist_gradient_boosting":
        return Pipeline(
            [
                ("imputer", SimpleImputer(strategy="median")),
                (
                    "model",
                    HistGradientBoostingRegressor(
                        max_iter=300,
                        learning_rate=0.05,
                        max_leaf_nodes=31,
                        min_samples_leaf=20,
                        l2_regularization=1.0,
                        random_state=42,
                    ),
                ),
            ]
        )
    raise ValueError(kind)


def _baseline_predict(kind: str, val: pd.DataFrame, train: pd.DataFrame) -> np.ndarray:
    if kind == "zero":
        return np.zeros(len(val), dtype=float)
    if kind == "median":
        return np.full(len(val), float(train["target_displacement_m"].median()), dtype=float)
    if kind == "persistence":
        p = val["last_rate_m_per_yr"].to_numpy(dtype=float) * val["elapsed_years"].to_numpy(dtype=float)
        return np.nan_to_num(p, nan=0.0)
    if kind == "trend":
        p = val["last3_mean_rate_m_per_yr"].to_numpy(dtype=float)
        p = np.where(np.isnan(p), val["last2_mean_rate_m_per_yr"].to_numpy(dtype=float), p)
        p = np.where(np.isnan(p), val["last_rate_m_per_yr"].to_numpy(dtype=float), p)
        p = np.nan_to_num(p, nan=0.0) * val["elapsed_years"].to_numpy(dtype=float)
        return p
    raise ValueError(kind)


def _metrics(y: np.ndarray, p: np.ndarray) -> dict:
    err = p - y
    low = np.abs(y) <= 15.0
    pred_low = np.abs(p) <= 15.0
    moving = ~low
    directional = float(np.mean(np.sign(p[moving]) == np.sign(y[moving]))) if moving.any() else float("nan")
    return {
        "n": int(len(y)),
        "mae_m": float(np.mean(np.abs(err))),
        "rmse_m": float(np.sqrt(np.mean(err**2))),
        "bias_m": float(np.mean(err)),
        "within_15m": float(np.mean(np.abs(err) <= 15.0)),
        "low_movement_f1": float(f1_score(low, pred_low, zero_division=0)),
        "low_movement_precision": float(np.sum(low & pred_low) / max(np.sum(pred_low), 1)),
        "low_movement_recall": float(np.sum(low & pred_low) / max(np.sum(low), 1)),
        "directional_accuracy_moving": directional,
        "false_movement_rate": float(np.mean(~pred_low[low])) if low.any() else float("nan"),
        "missed_movement_rate": float(np.mean(pred_low[moving])) if moving.any() else float("nan"),
        "mae_low_m": float(np.mean(np.abs(err[low]))) if low.any() else float("nan"),
        "mae_moving_m": float(np.mean(np.abs(err[moving]))) if moving.any() else float("nan"),
    }


def _rank(series: pd.Series, ascending: bool) -> pd.Series:
    return series.rank(method="min", ascending=ascending)


def backtest() -> dict:
    ensure_output_dirs()
    cfg = load_config()
    df = pd.read_csv(project_path("datasets", "bank_migration_dataset.csv"))
    origins = [int(y) for y in cfg["dataset"]["validation_origins"] if int(y) in set(df["origin_year"])]
    rows = []
    fold_checks = []
    for origin in origins:
        for h in cfg["dataset"]["horizons"]:
            train = df[
                (df["target_year"] < origin)
                & (df["horizon_years"] == h)
                & (df["usable_for_training"])
            ].copy()
            val = df[
                (df["origin_year"] == origin)
                & (df["horizon_years"] == h)
                & (df["target_year"] <= int(cfg["training_cutoff_year"]))
                & (df["label_quality"] == "good")
            ].copy()
            if len(train) < 100 or len(val) == 0:
                continue
            fold_checks.append(
                {
                    "origin_year": origin,
                    "horizon_years": int(h),
                    "n_train": int(len(train)),
                    "n_validation": int(len(val)),
                    "max_training_target_year": int(train["target_year"].max()),
                    "max_training_origin_year": int(train["origin_year"].max()),
                    "min_validation_target_year": int(val["target_year"].min()),
                    "max_validation_target_year": int(val["target_year"].max()),
                    "training_targets_strictly_before_origin": bool(train["target_year"].max() < origin),
                    "training_features_cutoff_before_origin": bool(train["feature_cutoff_year"].max() < origin),
                    "validation_origin_matches_fold": bool((val["origin_year"] == origin).all()),
                    "validation_targets_after_origin": bool((val["target_year"] > origin).all()),
                    "no_shared_sample_ids": bool(not set(train["sample_id"]).intersection(set(val["sample_id"]))),
                    "no_test_years": bool(not set(train["target_year"]).intersection(set(cfg["test_years"])) and not set(val["target_year"]).intersection(set(cfg["test_years"]))),
                }
            )
            y = val["target_displacement_m"].to_numpy(dtype=float)
            for kind in BASELINES:
                p = _baseline_predict(kind, val, train)
                _append(rows, kind, origin, h, val, y, p)
            X_train = train[FEATURES]
            X_val = val[FEATURES]
            for kind in ML_MODELS:
                model = _pipeline(kind)
                model.fit(X_train, train["target_displacement_m"].to_numpy(dtype=float))
                p = model.predict(X_val)
                _append(rows, kind, origin, h, val, y, p)
    pred = pd.DataFrame(rows)
    pred.to_csv(project_path("validation", "model_backtest_predictions.csv"), index=False)
    leakage = {
        "n_folds": len(fold_checks),
        "all_checks_pass": all(
            all(
                bool(f[k])
                for k in [
                    "training_targets_strictly_before_origin",
                    "training_features_cutoff_before_origin",
                    "validation_origin_matches_fold",
                    "validation_targets_after_origin",
                    "no_shared_sample_ids",
                    "no_test_years",
                ]
            )
            for f in fold_checks
        ),
        "folds": fold_checks,
    }
    write_json(project_path("validation", "backtest_leakage_checks.json"), leakage)
    metrics = []
    for (kind, origin, h), grp in pred.groupby(["model", "validation_origin", "horizon_years"]):
        m = _metrics(grp["observed_m"].to_numpy(), grp["predicted_m"].to_numpy())
        m.update({"model": kind, "validation_origin": int(origin), "horizon_years": int(h)})
        metrics.append(m)
    met = pd.DataFrame(metrics)
    met.to_csv(project_path("validation", "model_backtest_metrics.csv"), index=False)
    aggregate = _aggregate(met)
    aggregate.to_csv(project_path("validation", "model_selection_metrics.csv"), index=False)
    selected, decision = _select(aggregate, met)
    metadata = {
        "created_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "selected_model": selected,
        "selected_label": MODEL_LABELS[selected],
        "selection_rule": decision["rule"],
        "selection_score": decision["scores"],
        "validation_origins": origins,
        "horizons": list(cfg["dataset"]["horizons"]),
        "training_cutoff_year": int(cfg["training_cutoff_year"]),
        "features": FEATURES,
        "dataset_sha256": _sha256(project_path("datasets", "bank_migration_dataset.csv")),
        "backtest_leakage_checks": {
            "n_folds": leakage["n_folds"],
            "all_checks_pass": leakage["all_checks_pass"],
        },
        "aggregate_metrics": aggregate.to_dict(orient="records"),
    }
    write_json(project_path("validation", "model_selection.json"), metadata)
    _write_report(aggregate, decision, met, pred)
    _fit_final(df, selected, cfg, metadata)
    return {
        "selected_model": selected,
        "aggregate": aggregate.to_dict(orient="records"),
        "decision": decision,
    }


def _append(rows: list[dict], kind: str, origin: int, h: int, val: pd.DataFrame, y: np.ndarray, p: np.ndarray) -> None:
    for i, (_, r) in enumerate(val.iterrows()):
        rows.append(
            {
                "model": kind,
                "validation_origin": origin,
                "horizon_years": h,
                "sample_id": r["sample_id"],
                "transect_id": r["transect_id"],
                "side": r["side"],
                "reach": r["reach"],
                "observed_m": float(y[i]),
                "predicted_m": float(p[i]),
                "low_movement_observed": bool(abs(y[i]) <= 15.0),
            }
        )


def _aggregate(met: pd.DataFrame) -> pd.DataFrame:
    group = met.groupby("model")
    out = pd.DataFrame(
        {
            "fold_mean_mae_m": group["mae_m"].mean(),
            "fold_mean_rmse_m": group["rmse_m"].mean(),
            "fold_mean_bias_m": group["bias_m"].mean(),
            "fold_mean_within_15m": group["within_15m"].mean(),
            "fold_mean_low_movement_f1": group["low_movement_f1"].mean(),
            "fold_mean_directional_accuracy": group["directional_accuracy_moving"].mean(),
            "fold_mean_false_movement_rate": group["false_movement_rate"].mean(),
            "fold_mean_missed_movement_rate": group["missed_movement_rate"].mean(),
            "folds": group.size(),
        }
    ).reset_index()
    out["label"] = out["model"].map(MODEL_LABELS)
    return out.sort_values("fold_mean_mae_m").reset_index(drop=True)


def _select(aggregate: pd.DataFrame, met: pd.DataFrame) -> tuple[str, dict]:
    a = aggregate.set_index("model").copy()
    gate_directional = 0.55
    gate_low_f1 = 0.70
    eligible = a[
        (a["fold_mean_directional_accuracy"] >= gate_directional)
        & (a["fold_mean_low_movement_f1"] >= gate_low_f1)
    ]
    if eligible.empty:
        eligible = a.sort_values("fold_mean_directional_accuracy", ascending=False).head(2)
    ranks = pd.DataFrame(index=eligible.index)
    ranks["mae"] = _rank(eligible["fold_mean_mae_m"], ascending=True)
    ranks["rmse"] = _rank(eligible["fold_mean_rmse_m"], ascending=True)
    ranks["low_f1"] = _rank(eligible["fold_mean_low_movement_f1"], ascending=False)
    ranks["directional"] = _rank(eligible["fold_mean_directional_accuracy"], ascending=False)
    score = ranks.mean(axis=1)
    tie = eligible.assign(score=score).sort_values(
        ["score", "fold_mean_directional_accuracy", "fold_mean_rmse_m", "fold_mean_mae_m"],
        ascending=[True, False, True, True],
    )
    selected = str(tie.index[0])
    decision = {
        "rule": (
            "Eligibility gates exclude constant/no-skill forecasts: directional accuracy on "
            "observed movement >15 m must be at least 0.55, and low-movement F1 must be at least "
            "0.70. Among eligible models, rank by MAE, RMSE, low-movement F1 and directional "
            "accuracy (mean rank). Ties break on higher directional accuracy, then lower RMSE, then "
            "lower MAE. No test-year observation is used."
        ),
        "gates": {"directional_accuracy_min": gate_directional, "low_movement_f1_min": gate_low_f1},
        "eligible_models": sorted(eligible.index.tolist()),
        "ranks": ranks.round(3).reset_index().to_dict(orient="records"),
        "scores": {str(k): float(v) for k, v in score.round(4).items()},
        "selected": selected,
        "selected_mae_m": float(a.loc[selected, "fold_mean_mae_m"]),
        "selected_rmse_m": float(a.loc[selected, "fold_mean_rmse_m"]),
        "selected_directional": float(a.loc[selected, "fold_mean_directional_accuracy"]),
        "selected_low_f1": float(a.loc[selected, "fold_mean_low_movement_f1"]),
        "reference_best_mae": str(a["fold_mean_mae_m"].idxmin()),
        "reference_best_mae_m": float(a["fold_mean_mae_m"].min()),
    }
    return selected, decision

def _fit_final(df: pd.DataFrame, selected: str, cfg: dict, metadata: dict) -> None:
    train_all = df[(df["target_year"] <= int(cfg["training_cutoff_year"])) & (df["usable_for_training"])].copy()
    artifacts = {}
    for h in cfg["dataset"]["horizons"]:
        train = train_all[train_all["horizon_years"] == h]
        if selected in BASELINES:
            artifacts[int(h)] = {
                "kind": selected,
                "features": FEATURES,
                "horizon_years": int(h),
                "median_m": float(train["target_displacement_m"].median()) if selected == "median" else None,
                "n_train": int(len(train)),
            }
        else:
            model = _pipeline(selected)
            model.fit(train[FEATURES], train["target_displacement_m"].to_numpy(dtype=float))
            artifacts[int(h)] = {
                "kind": selected,
                "features": FEATURES,
                "horizon_years": int(h),
                "pipeline": model,
                "n_train": int(len(train)),
            }
    joblib.dump(artifacts, project_path("models", "final_models.joblib"))
    metadata["final_training_rows_by_horizon"] = {
        str(h): int(len(train_all[train_all["horizon_years"] == h])) for h in cfg["dataset"]["horizons"]
    }
    metadata["artifact"] = str(project_path("models", "final_models.joblib"))
    write_json(project_path("models", "model_metadata.json"), metadata)


def predict_artifact(artifact: dict, frame: pd.DataFrame) -> np.ndarray:
    kind = artifact["kind"]
    if kind == "zero":
        return np.zeros(len(frame), dtype=float)
    if kind == "median":
        return np.full(len(frame), float(artifact["median_m"]), dtype=float)
    if kind == "persistence":
        return np.nan_to_num(frame["last_rate_m_per_yr"].to_numpy(dtype=float) * frame["elapsed_years"].to_numpy(dtype=float), nan=0.0)
    if kind == "trend":
        p = frame["last3_mean_rate_m_per_yr"].to_numpy(dtype=float)
        p = np.where(np.isnan(p), frame["last2_mean_rate_m_per_yr"].to_numpy(dtype=float), p)
        p = np.where(np.isnan(p), frame["last_rate_m_per_yr"].to_numpy(dtype=float), p)
        return np.nan_to_num(p, nan=0.0) * frame["elapsed_years"].to_numpy(dtype=float)
    return artifact["pipeline"].predict(frame[artifact["features"]])


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _write_report(aggregate: pd.DataFrame, decision: dict, met: pd.DataFrame, pred: pd.DataFrame) -> None:
    lines = [
        "# Model validation and selection",
        "",
        "Validation uses rolling forecast origins from 2000 to 2020. For each origin, training rows "
        "end strictly before that origin; validation rows are the good-quality labels at that origin "
        "with targets through 2023. The 2024–2026 years are absent from this exercise.",
        "",
        "## Selection rule",
        "",
        decision["rule"],
        "",
        "## Aggregate validation metrics",
        "",
        "| Model | Eligible | MAE (m) | RMSE (m) | Bias (m) | Within ±15 m | Low-movement F1 | Directional accuracy (>15 m) | False movement | Missed movement |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for _, r in aggregate.iterrows():
        eligible = r["model"] in decision["eligible_models"]
        lines.append(
            f"| {r['label']} | {'yes' if eligible else 'no'} | {r['fold_mean_mae_m']:.2f} | {r['fold_mean_rmse_m']:.2f} | "
            f"{r['fold_mean_bias_m']:+.2f} | {r['fold_mean_within_15m']:.3f} | "
            f"{r['fold_mean_low_movement_f1']:.3f} | {r['fold_mean_directional_accuracy']:.3f} | "
            f"{r['fold_mean_false_movement_rate']:.3f} | {r['fold_mean_missed_movement_rate']:.3f} |"
        )
    lines += [
        "",
        f"Selected model: **{MODEL_LABELS[decision['selected']]}** "
        f"(mean rank score {decision['scores'][decision['selected']]:.2f}; "
        f"MAE {decision['selected_mae_m']:.2f} m).",
        "",
        "## By horizon",
        "",
        "| Model | Horizon | MAE (m) | RMSE (m) | Low-movement F1 | Directional accuracy |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for model in aggregate["model"]:
        for h in sorted(met["horizon_years"].unique()):
            rows = met[(met["model"] == model) & (met["horizon_years"] == h)]
            lines.append(
                f"| {MODEL_LABELS[model]} | {h} | {rows['mae_m'].mean():.2f} | {rows['rmse_m'].mean():.2f} | "
                f"{rows['low_movement_f1'].mean():.3f} | {rows['directional_accuracy_moving'].mean():.3f} |"
            )
    lines += [
        "",
        "## Interpretation",
        "",
        "The zero and median baselines are strong in MAE because a large share of observed bank "
        "displacements are exactly zero at the 30 m pixel resolution. That is why the selection rule "
        "also ranks low-movement F1 and directional accuracy, and why results are broken down by "
        "horizon. A low MAE alone can hide a model that never predicts movement.",
        "",
        "The bank displacement labels are measured at fixed 2023 transects. Early-year labels are "
        "more often flagged because the channel occupied a different position; only `good` labels "
        "enter validation. This reduces the effective early sample and is reported rather than hidden.",
        "",
        "No 2024–2026 raster or label is used in this report.",
    ]
    project_path("reports", "model_validation.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    print(backtest())
