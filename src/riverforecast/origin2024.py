from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import shutil
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor, RandomForestRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from .config import load_config, project_path
from .dataset import FEATURES, IDENTIFIERS, LABEL_COLUMNS
from .geometry import add_sinuosity
from .io import sha256_file, write_json
from .measure import _quality as interval_quality
from .models import BASELINES, MODEL_LABELS, _metrics

ORIGIN_YEAR = 2024
TRAINING_CUTOFF_YEAR = 2024
FORECAST_YEARS = (2025, 2026)
HORIZONS = (1, 2)
VALIDATION_ORIGINS = tuple(range(2000, 2024))
RANDOM_SEED = 42
LOW_MOVEMENT_M = 15.0
BOOTSTRAP_DRAWS = 10000
BOOTSTRAP_ALPHA = 0.10
DATASET_PATH = project_path("datasets", "origin2024_bank_migration.csv")
FEATURES_PATH = project_path("datasets", "origin2024_forecast_features.csv")
PROVENANCE_PATH = project_path("datasets", "origin2024_provenance.json")
LEAKAGE_PATH = project_path("datasets", "origin2024_leakage_checks.json")
STAGING_DIR = project_path("forecasts", "origin2024_staging")
FROZEN_DIR = project_path("forecasts", "frozen_origin2024")
EVALUATION_DIR = project_path("evaluation_origin2024")
PREREG_PATH = project_path("reports", "prereg_origin2024.md")
REPORT_PATH = project_path("reports", "second_look_not_blind.md")


def _flags(row) -> set[str]:
    return set(row["flags"].split("|")) if isinstance(row["flags"], str) and row["flags"] else set()


def _good(row, min_width: float) -> bool:
    flags = _flags(row)
    return bool(
        row["valid_bank"]
        and row["center_inside"]
        and not ({"multiple_crossings", "width_below_min", "missing_bank"} & flags)
        and not row["border_transect"]
        and (not np.isnan(row["width_m"]))
        and row["width_m"] >= min_width
    )


def _row_quality(origin, target, displacement, min_width, max_disp) -> str:
    if not _good(origin, min_width) or not _good(target, min_width):
        return "flagged"
    if abs(displacement) > max_disp:
        return "implausible"
    return "good"


def _nominal(year: int) -> pd.Timestamp:
    return pd.Timestamp(f"{int(year)}-03-25")


def _load_positions() -> tuple[pd.DataFrame, pd.DataFrame]:
    positions = pd.read_csv(project_path("derived", "measurements", "bank_positions.csv"))
    observed_2024_path = project_path("evaluation", "observed_bank_positions_2024.csv")
    observed_2024 = pd.read_csv(observed_2024_path)
    observed_2024 = add_sinuosity(observed_2024)
    observed_2024["observation_date"] = f"{ORIGIN_YEAR}-03-25"
    combined = pd.concat([positions, observed_2024], ignore_index=True)
    combined["year"] = combined["year"].astype(int)
    combined["transect_id"] = combined["transect_id"].astype(int)
    combined = combined.sort_values(["year", "transect_id", "side"]).reset_index(drop=True)
    return combined, observed_2024


def _build_intervals(positions: pd.DataFrame, years: list[int], cfg: dict) -> pd.DataFrame:
    rows = []
    for a, b in zip(years[:-1], years[1:]):
        da = positions[positions["year"] == a].set_index(["transect_id", "side"])
        db = positions[positions["year"] == b].set_index(["transect_id", "side"])
        for key in sorted(set(da.index) & set(db.index)):
            ra = da.loc[key]
            rb = db.loc[key]
            valid = bool(ra["valid_bank"] and rb["valid_bank"])
            displacement = np.nan
            if valid:
                dx = float(rb["bank_x"] - ra["bank_x"])
                dy = float(rb["bank_y"] - ra["bank_y"])
                displacement = (dx * float(ra["normal_x"]) + dy * float(ra["normal_y"])) * float(ra["outward_sign"])
            elapsed_days = (_nominal(b) - _nominal(a)).days
            flags = sorted(set(list(ra["flags"]) + list(rb["flags"])))
            if valid and abs(displacement) > float(cfg["labels"]["max_plausible_abs_displacement_m"]):
                flags.append("displacement_gt_5px")
            if elapsed_days > 5 * 365.25 + 2:
                flags.append("interval_gt_5yr")
            row = {
                "from_year": a,
                "to_year": b,
                "from_date": _nominal(a).date().isoformat(),
                "to_date": _nominal(b).date().isoformat(),
                "elapsed_days": elapsed_days,
                "elapsed_years": elapsed_days / 365.25,
                "transect_id": key[0],
                "side": key[1],
                "reach": ra["reach"],
                "along_m": ra["along_m"],
                "normal_x": ra["normal_x"],
                "normal_y": ra["normal_y"],
                "outward_sign": ra["outward_sign"],
                "bank_from_x": ra["bank_x"] if valid else np.nan,
                "bank_from_y": ra["bank_y"] if valid else np.nan,
                "bank_to_x": rb["bank_x"] if valid else np.nan,
                "bank_to_y": rb["bank_y"] if valid else np.nan,
                "bank_dist_from_m": ra["bank_dist_m"],
                "bank_dist_to_m": rb["bank_dist_m"],
                "signed_displacement_m": displacement,
                "annualized_rate_m_per_yr": displacement / (elapsed_days / 365.25) if valid else np.nan,
                "width_from_m": ra["width_m"],
                "width_to_m": rb["width_m"],
                "center_inside_from": bool(ra["center_inside"]),
                "center_inside_to": bool(rb["center_inside"]),
                "valid_bank": valid,
                "flags": flags,
            }
            row["quality"] = interval_quality(row, cfg)
            rows.append(row)
    return pd.DataFrame(rows)


def _history(intervals: pd.DataFrame, origin: int) -> list[pd.Series]:
    sub = intervals[(intervals["to_year"] <= origin) & (intervals["valid_bank"])]
    return [r for _, r in sub.sort_values("to_year").iterrows()]


def _feature_row(o: pd.Series, hist: list[pd.Series], horizon: int, origin: int, target: int) -> dict:
    last = hist[-1] if hist else None
    prev = hist[-2] if len(hist) >= 2 else None
    rates = [float(r["annualized_rate_m_per_yr"]) for r in hist if not np.isnan(r["annualized_rate_m_per_yr"])]
    last_rate = float(last["annualized_rate_m_per_yr"]) if last is not None else np.nan
    prev_rate = float(prev["annualized_rate_m_per_yr"]) if prev is not None else np.nan
    last2_mean = float(np.mean(rates[-2:])) if len(rates) >= 2 else np.nan
    last3_mean = float(np.mean(rates[-3:])) if len(rates) >= 3 else np.nan
    accel = last_rate - prev_rate if not (np.isnan(last_rate) or np.isnan(prev_rate)) else np.nan
    width = float(o["width_m"]) if not np.isnan(o["width_m"]) else np.nan
    curvature = float(abs(o["curvature_1_m"])) if not np.isnan(o["curvature_1_m"]) else np.nan
    sinuosity = float(o["sinuosity"]) if not np.isnan(o["sinuosity"]) else np.nan
    last_width_change = (
        float(last["width_to_m"] - last["width_from_m"])
        if last is not None and not np.isnan(last["width_to_m"]) and not np.isnan(last["width_from_m"])
        else np.nan
    )
    elapsed = (_nominal(target) - _nominal(origin)).days / 365.25
    return {
        "last_rate_m_per_yr": last_rate,
        "last2_mean_rate_m_per_yr": last2_mean,
        "last3_mean_rate_m_per_yr": last3_mean,
        "acceleration_m_per_yr2": accel,
        "last_displacement_m": float(last["signed_displacement_m"]) if last is not None else np.nan,
        "last_interval_years": float(last["elapsed_years"]) if last is not None else np.nan,
        "last_interval_good": int(last["quality"] == "good") if last is not None else np.nan,
        "width_m": width,
        "width_change_last_m": last_width_change,
        "abs_curvature_1_m": curvature,
        "sinuosity": sinuosity,
        "is_left_bank": 1 if o["side"] == "L" else 0,
        "horizon_years": horizon,
        "elapsed_years": elapsed,
        "last_rate_missing": int(np.isnan(last_rate)),
        "last2_missing": int(np.isnan(last2_mean)),
        "last3_missing": int(np.isnan(last3_mean)),
        "width_missing": int(np.isnan(width)),
        "curvature_missing": int(np.isnan(curvature)),
        "sinuosity_missing": int(np.isnan(sinuosity)),
    }


def _build_training(positions: pd.DataFrame, intervals: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    min_width = float(cfg["transects"]["min_width_m"])
    max_disp = float(cfg["labels"]["max_plausible_abs_displacement_m"])
    years = sorted(int(y) for y in positions["year"].unique())
    lookup = {(int(r.year), int(r.transect_id), r.side): r for _, r in positions.iterrows()}
    interval_lookup = {}
    for (tid, side), grp in intervals.groupby(["transect_id", "side"], sort=False):
        interval_lookup[(tid, side)] = grp.sort_values("to_year").reset_index(drop=True)
    rows = []
    for origin in years:
        for _, o in positions[positions["year"] == origin].iterrows():
            grp = interval_lookup.get((int(o["transect_id"]), o["side"]))
            hist = [r for _, r in grp[grp["to_year"] <= origin].iterrows() if bool(r["valid_bank"])] if grp is not None else []
            for h in HORIZONS:
                target = origin + h
                if target not in years or target > TRAINING_CUTOFF_YEAR:
                    continue
                tb = lookup.get((target, int(o["transect_id"]), o["side"]))
                if tb is None:
                    continue
                disp = np.nan
                target_x = tb["bank_x"] if bool(tb["valid_bank"]) else np.nan
                target_y = tb["bank_y"] if bool(tb["valid_bank"]) else np.nan
                if bool(o["valid_bank"]) and bool(tb["valid_bank"]):
                    dx = float(tb["bank_x"] - o["bank_x"])
                    dy = float(tb["bank_y"] - o["bank_y"])
                    disp = (dx * float(o["normal_x"]) + dy * float(o["normal_y"])) * float(o["outward_sign"])
                quality = "invalid" if np.isnan(disp) else _row_quality(o, tb, disp, min_width, max_disp)
                row = {
                    "sample_id": f"T{int(o['transect_id']):03d}_{o['side']}_{origin}_{target}",
                    "forecast_year": target,
                    "target_year": target,
                    "origin_year": origin,
                    "horizon_years": h,
                    "elapsed_years": (_nominal(target) - _nominal(origin)).days / 365.25,
                    "transect_id": int(o["transect_id"]),
                    "side": o["side"],
                    "reach": o["reach"],
                    "along_m": float(o["along_m"]),
                    "origin_bank_x": float(o["bank_x"]) if bool(o["valid_bank"]) else np.nan,
                    "origin_bank_y": float(o["bank_y"]) if bool(o["valid_bank"]) else np.nan,
                    "normal_x": float(o["normal_x"]),
                    "normal_y": float(o["normal_y"]),
                    "outward_sign": float(o["outward_sign"]),
                    "target_displacement_m": disp,
                    "target_rate_m_per_yr": disp / ((_nominal(target) - _nominal(origin)).days / 365.25) if not np.isnan(disp) else np.nan,
                    "target_bank_x": target_x,
                    "target_bank_y": target_y,
                    "label_quality": quality,
                    "usable_for_training": quality == "good",
                    "feature_cutoff_year": origin,
                }
                row.update(_feature_row(o, hist, h, origin, target))
                rows.append(row)
    df = pd.DataFrame(rows)
    df = df.sort_values(["origin_year", "horizon_years", "transect_id", "side"]).reset_index(drop=True)
    return df


def _build_forecast_features(positions: pd.DataFrame, intervals: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    years = sorted(int(y) for y in positions["year"].unique())
    interval_lookup = {}
    for (tid, side), grp in intervals.groupby(["transect_id", "side"], sort=False):
        interval_lookup[(tid, side)] = grp.sort_values("to_year").reset_index(drop=True)
    rows = []
    for _, o in positions[positions["year"] == ORIGIN_YEAR].iterrows():
        grp = interval_lookup.get((int(o["transect_id"]), o["side"]))
        hist = [r for _, r in grp[grp["to_year"] <= ORIGIN_YEAR].iterrows() if bool(r["valid_bank"])] if grp is not None else []
        for h in HORIZONS:
            target = ORIGIN_YEAR + h
            base = {
                "sample_id": f"T{int(o['transect_id']):03d}_{o['side']}_{ORIGIN_YEAR}_{target}",
                "forecast_year": target,
                "target_year": target,
                "origin_year": ORIGIN_YEAR,
                "horizon_years": h,
                "elapsed_years": (_nominal(target) - _nominal(ORIGIN_YEAR)).days / 365.25,
                "transect_id": int(o["transect_id"]),
                "side": o["side"],
                "reach": o["reach"],
                "along_m": float(o["along_m"]),
                "origin_bank_x": float(o["bank_x"]) if bool(o["valid_bank"]) else np.nan,
                "origin_bank_y": float(o["bank_y"]) if bool(o["valid_bank"]) else np.nan,
                "normal_x": float(o["normal_x"]),
                "normal_y": float(o["normal_y"]),
                "outward_sign": float(o["outward_sign"]),
                "feature_cutoff_year": ORIGIN_YEAR,
            }
            base.update(_feature_row(o, hist, h, ORIGIN_YEAR, target))
            rows.append(base)
    out = pd.DataFrame(rows)
    columns = list(dict.fromkeys([c for c in IDENTIFIERS if c in out.columns] + FEATURES + ["feature_cutoff_year"]))
    return out[columns].sort_values(["horizon_years", "transect_id", "side"]).reset_index(drop=True)


def _json_safe(value):
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_safe(v) for v in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        value = float(value)
    if isinstance(value, float):
        return None if math.isnan(value) or math.isinf(value) else value
    return value


def _sha256(path: Path) -> str:
    return sha256_file(path)


def _v1_hashes() -> dict:
    return {
        "frozen_ready": (project_path("forecasts", "frozen", "READY")).read_text(encoding="utf-8").strip(),
        "metrics_sha256": _sha256(project_path("evaluation", "metrics.json")),
        "model_sha256": _sha256(project_path("models", "final_models.joblib")),
        "dataset_sha256": _sha256(project_path("datasets", "bank_migration_dataset.csv")),
        "forecast_features_sha256": _sha256(project_path("datasets", "forecast_features_2023.csv")),
    }


def prepare() -> dict:
    cfg = load_config()
    positions, observed_2024 = _load_positions()
    years = sorted(int(y) for y in positions["year"].unique())
    intervals = _build_intervals(positions, years, cfg)
    training = _build_training(positions, intervals, cfg)
    forecast = _build_forecast_features(positions, intervals, cfg)
    if int(training["target_year"].max()) > TRAINING_CUTOFF_YEAR:
        raise RuntimeError("Training target year exceeds the pre-registered 2024 cutoff.")
    if set(int(y) for y in training["target_year"]).intersection(FORECAST_YEARS):
        raise RuntimeError("Training data contain a test year.")
    if set(int(y) for y in forecast["forecast_year"]) != set(FORECAST_YEARS):
        raise RuntimeError("Forecast years do not match the pre-registration.")
    if set(int(y) for y in forecast["origin_year"]) != {ORIGIN_YEAR}:
        raise RuntimeError("Forecast origin does not match the pre-registration.")

    v1 = pd.read_csv(project_path("datasets", "bank_migration_dataset.csv"))
    v1 = v1[(v1["target_year"] <= 2023) & (v1["horizon_years"].isin(HORIZONS))].copy()
    compare_cols = ["target_displacement_m", "target_rate_m_per_yr", "feature_cutoff_year"] + FEATURES
    old = v1.set_index("sample_id")
    new = training.set_index("sample_id")
    common = old.index.intersection(new.index)
    mismatches = {}
    for col in compare_cols:
        a = old.loc[common, col].astype(float).to_numpy()
        b = new.loc[common, col].astype(float).to_numpy()
        same = np.isclose(a, b, rtol=0.0, atol=1e-10, equal_nan=True)
        if not same.all():
            mismatches[col] = int((~same).sum())
    if len(common) != len(old):
        mismatches["v1_rows_missing_from_new"] = int(len(old) - len(common))
    new_2024 = training[training["target_year"] == 2024]
    provenance = {
        "created_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "origin_year": ORIGIN_YEAR,
        "training_cutoff_year": TRAINING_CUTOFF_YEAR,
        "forecast_years": list(FORECAST_YEARS),
        "training_inputs": [
            str(project_path("derived", "measurements", "bank_positions.csv")),
            str(project_path("evaluation", "observed_bank_positions_2024.csv")),
        ],
        "training_2024_observations_already_seen": True,
        "n_rows": int(len(training)),
        "n_usable": int(training["usable_for_training"].sum()),
        "n_target_2024_rows": int(len(new_2024)),
        "n_forecast_rows": int(len(forecast)),
        "features": FEATURES,
        "identifiers": IDENTIFIERS,
        "labels": LABEL_COLUMNS,
        "historical_rows_compared_to_v1": int(len(common)),
        "historical_v1_mismatches": mismatches,
        "v1_immutable_hashes": _v1_hashes(),
    }
    checks = {
        "max_target_year": int(training["target_year"].max()),
        "max_target_year_at_most_2024": bool(training["target_year"].max() <= TRAINING_CUTOFF_YEAR),
        "no_test_years_in_training": bool(not set(int(y) for y in training["target_year"]).intersection(FORECAST_YEARS)),
        "all_targets_after_origin": bool((training["target_year"] > training["origin_year"]).all()),
        "all_feature_cutoffs_at_origin": bool((training["feature_cutoff_year"] == training["origin_year"]).all()),
        "horizons": sorted(int(h) for h in training["horizon_years"].unique()),
        "all_horizons_positive": bool((training["horizon_years"] >= 1).all()),
        "duplicate_sample_ids": int(training["sample_id"].duplicated().sum()),
        "duplicate_transect_side_origin_horizon": int(training.duplicated(["transect_id", "side", "origin_year", "horizon_years"]).sum()),
        "transect_id_in_features": "transect_id" in FEATURES,
        "coordinate_in_features": any(c in FEATURES for c in ["origin_bank_x", "origin_bank_y", "along_m", "reach"]),
        "target_columns_in_features": any(c in FEATURES for c in ["target_displacement_m", "target_bank_x", "target_bank_y", "target_rate_m_per_yr"]),
        "forecast_rows_have_no_labels": bool(not any(c in forecast.columns for c in ["target_displacement_m", "target_rate_m_per_yr", "target_bank_x", "target_bank_y"])),
        "forecast_years": sorted(int(v) for v in forecast["forecast_year"].unique()),
        "forecast_origin_year": sorted(int(v) for v in forecast["origin_year"].unique()),
        "forecast_feature_cutoffs": sorted(int(v) for v in forecast["feature_cutoff_year"].unique()),
        "forecast_contains_only_2025_2026": bool(set(int(v) for v in forecast["forecast_year"]) == set(FORECAST_YEARS)),
        "historical_v1_mismatches": mismatches,
    }
    checks["all_checks_pass"] = bool(
        checks["max_target_year_at_most_2024"]
        and checks["no_test_years_in_training"]
        and checks["all_targets_after_origin"]
        and checks["all_feature_cutoffs_at_origin"]
        and checks["all_horizons_positive"]
        and checks["duplicate_sample_ids"] == 0
        and checks["duplicate_transect_side_origin_horizon"] == 0
        and not checks["transect_id_in_features"]
        and not checks["coordinate_in_features"]
        and not checks["target_columns_in_features"]
        and checks["forecast_rows_have_no_labels"]
        and checks["forecast_contains_only_2025_2026"]
        and not mismatches
    )
    if not checks["all_checks_pass"]:
        raise RuntimeError(f"Origin-2024 dataset checks failed: {checks}")
    training.to_csv(DATASET_PATH, index=False)
    forecast.to_csv(FEATURES_PATH, index=False)
    write_json(PROVENANCE_PATH, _json_safe(provenance))
    write_json(LEAKAGE_PATH, _json_safe(checks))
    return checks


def _candidate_specs(cfg: dict) -> list[dict]:
    m = cfg["modeling"]
    specs: list[dict] = []
    for alpha in m["ridge_alphas"]:
        specs.append(
            {
                "candidate_id": f"ridge_alpha_{alpha:g}",
                "family": "ridge",
                "params": {"alpha": float(alpha)},
            }
        )
    for depth in m["rf_max_depth"]:
        for leaf in m["rf_min_samples_leaf"]:
            depth_label = "none" if depth is None else f"{int(depth)}"
            specs.append(
                {
                    "candidate_id": f"random_forest_depth_{depth_label}_leaf_{int(leaf)}",
                    "family": "random_forest",
                    "params": {"n_estimators": int(m["rf_n_estimators"][0]), "max_depth": depth, "min_samples_leaf": int(leaf)},
                }
            )
    for depth in m["hgb_max_depth"]:
        for lr in m["hgb_learning_rate"]:
            specs.append(
                {
                    "candidate_id": f"hist_gradient_boosting_depth_{int(depth)}_lr_{float(lr):g}",
                    "family": "hist_gradient_boosting",
                    "params": {"max_iter": int(m["hgb_max_iter"][0]), "max_depth": int(depth), "learning_rate": float(lr)},
                }
            )
    return specs


def _pipeline_for(spec: dict) -> Pipeline:
    family = spec["family"]
    params = spec["params"]
    if family == "ridge":
        return Pipeline(
            [
                ("imputer", SimpleImputer(strategy="median")),
                ("scaler", StandardScaler()),
                ("model", Ridge(alpha=float(params["alpha"]))),
            ]
        )
    if family == "random_forest":
        return Pipeline(
            [
                ("imputer", SimpleImputer(strategy="median")),
                (
                    "model",
                    RandomForestRegressor(
                        n_estimators=int(params["n_estimators"]),
                        max_depth=None if params["max_depth"] is None else int(params["max_depth"]),
                        min_samples_leaf=int(params["min_samples_leaf"]),
                        max_features=0.75,
                        n_jobs=4,
                        random_state=RANDOM_SEED,
                    ),
                ),
            ]
        )
    if family == "hist_gradient_boosting":
        return Pipeline(
            [
                ("imputer", SimpleImputer(strategy="median")),
                (
                    "model",
                    HistGradientBoostingRegressor(
                        max_iter=int(params["max_iter"]),
                        max_depth=int(params["max_depth"]),
                        learning_rate=float(params["learning_rate"]),
                        min_samples_leaf=20,
                        l2_regularization=1.0,
                        random_state=RANDOM_SEED,
                    ),
                ),
            ]
        )
    raise ValueError(family)


def _fold_rows(df: pd.DataFrame) -> list[dict]:
    folds = []
    for origin in VALIDATION_ORIGINS:
        for h in HORIZONS:
            train = df[
                (df["target_year"] < origin)
                & (df["horizon_years"] == h)
                & (df["target_year"] <= TRAINING_CUTOFF_YEAR)
                & (df["usable_for_training"])
            ].copy()
            val = df[
                (df["origin_year"] == origin)
                & (df["horizon_years"] == h)
                & (df["target_year"] <= TRAINING_CUTOFF_YEAR)
                & (df["target_year"] > origin)
                & (df["label_quality"] == "good")
            ].copy()
            if len(train) < 100 or len(val) == 0:
                continue
            if int(val["target_year"].max()) > TRAINING_CUTOFF_YEAR:
                raise RuntimeError("A validation target reaches a test year.")
            folds.append(
                {
                    "origin_year": int(origin),
                    "horizon_years": int(h),
                    "train": train,
                    "validation": val,
                    "n_train": int(len(train)),
                    "n_validation": int(len(val)),
                    "max_training_target_year": int(train["target_year"].max()),
                    "max_validation_target_year": int(val["target_year"].max()),
                    "training_targets_before_origin": bool(train["target_year"].max() < origin),
                    "features_cutoff_at_or_before_origin": bool(train["feature_cutoff_year"].max() <= origin),
                    "no_test_years": bool(not set(train["target_year"]).intersection(FORECAST_YEARS)),
                }
            )
    return folds


def _pooled_metrics(y: np.ndarray, p: np.ndarray) -> dict:
    m = _metrics(y, p)
    m["share_predicted_move"] = float(np.mean(np.abs(p) > LOW_MOVEMENT_M))
    m["share_observed_move"] = float(np.mean(np.abs(y) > LOW_MOVEMENT_M))
    return _json_safe(m)


def tune() -> dict:
    cfg = load_config()
    df = pd.read_csv(DATASET_PATH)
    folds = _fold_rows(df)
    if not folds:
        raise RuntimeError("No valid rolling-origin folds.")
    fold_check = {
        "n_folds": len(folds),
        "max_validation_target_year": max(f["max_validation_target_year"] for f in folds),
        "all_training_targets_before_origin": all(f["training_targets_before_origin"] for f in folds),
        "all_features_cutoff_at_or_before_origin": all(f["features_cutoff_at_or_before_origin"] for f in folds),
        "no_test_years": all(f["no_test_years"] for f in folds),
        "folds": [
            {k: v for k, v in f.items() if k not in {"train", "validation"}}
            for f in folds
        ],
    }
    if fold_check["max_validation_target_year"] > TRAINING_CUTOFF_YEAR:
        raise RuntimeError("A validation target reaches a test year.")
    y_all = np.concatenate([f["validation"]["target_displacement_m"].to_numpy(dtype=float) for f in folds])
    zero_all = np.zeros(len(y_all), dtype=float)
    zero_pooled = _pooled_metrics(y_all, zero_all)
    zero_fold = []
    for f in folds:
        y = f["validation"]["target_displacement_m"].to_numpy(dtype=float)
        zero_fold.append(_pooled_metrics(y, np.zeros(len(y), dtype=float)))

    STAGING_DIR.mkdir(parents=True, exist_ok=True)
    log_path = STAGING_DIR / "tuning_candidates.jsonl"
    if log_path.exists():
        log_path.unlink()
    candidates = []
    for spec in _candidate_specs(cfg):
        predictions = []
        fold_metrics = []
        for f in folds:
            train = f["train"]
            val = f["validation"]
            model = _pipeline_for(spec)
            model.fit(train[FEATURES], train["target_displacement_m"].to_numpy(dtype=float))
            p = model.predict(val[FEATURES])
            predictions.append(p)
            y = val["target_displacement_m"].to_numpy(dtype=float)
            fold_metrics.append(
                {
                    "origin_year": f["origin_year"],
                    "horizon_years": f["horizon_years"],
                    "n": int(len(y)),
                    **_pooled_metrics(y, p),
                }
            )
        p_all = np.concatenate(predictions)
        pooled = _pooled_metrics(y_all, p_all)
        fold_mean_mae = float(np.mean([m["mae_m"] for m in fold_metrics]))
        record = {
            "candidate_id": spec["candidate_id"],
            "family": spec["family"],
            "params": spec["params"],
            "n_folds": len(folds),
            "n_validation": int(len(y_all)),
            "pooled": pooled,
            "fold_mean_mae_m": fold_mean_mae,
            "fold_metrics": fold_metrics,
            "eligible": bool(pooled["mae_m"] < zero_pooled["mae_m"]),
            "zero_pooled_mae_m": float(zero_pooled["mae_m"]),
        }
        candidates.append(record)
        with open(log_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(_json_safe(record), sort_keys=True) + "\n")
        print(f"candidate {spec['candidate_id']}: MAE {pooled['mae_m']:.6f} (zero {zero_pooled['mae_m']:.6f})")

    eligible = [c for c in candidates if c["eligible"]]
    if eligible:
        selected = sorted(
            eligible,
            key=lambda c: (
                c["pooled"]["mae_m"],
                c["pooled"]["rmse_m"],
                -c["pooled"]["low_movement_f1"],
                -c["pooled"]["directional_accuracy_moving"],
                c["candidate_id"],
            ),
        )[0]
        selected_id = selected["candidate_id"]
        selected_kind = "candidate"
    else:
        selected = None
        selected_id = "zero"
        selected_kind = "zero_fallback"

    artifacts = {}
    medians = {}
    n_by_horizon = {}
    for h in HORIZONS:
        train = df[
            (df["horizon_years"] == h)
            & (df["usable_for_training"])
            & (df["target_year"] <= TRAINING_CUTOFF_YEAR)
        ].copy()
        n_by_horizon[str(h)] = int(len(train))
        medians[str(h)] = float(train["target_displacement_m"].median())
        if selected is None:
            artifacts[int(h)] = {
                "kind": "zero",
                "features": FEATURES,
                "horizon_years": int(h),
                "n_train": int(len(train)),
            }
        else:
            model = _pipeline_for(selected)
            model.fit(train[FEATURES], train["target_displacement_m"].to_numpy(dtype=float))
            artifacts[int(h)] = {
                "kind": selected["family"],
                "candidate_id": selected["candidate_id"],
                "params": selected["params"],
                "features": FEATURES,
                "horizon_years": int(h),
                "pipeline": model,
                "n_train": int(len(train)),
            }
    joblib.dump(artifacts, STAGING_DIR / "model.joblib")
    shutil.copy2(FEATURES_PATH, STAGING_DIR / "forecast_features_2024.csv")
    metadata = {
        "created_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "origin_year": ORIGIN_YEAR,
        "forecast_years": list(FORECAST_YEARS),
        "training_cutoff_year": TRAINING_CUTOFF_YEAR,
        "selected_model": selected_id,
        "selected_kind": selected_kind,
        "selected_label": MODEL_LABELS.get(selected["family"], "Zero change") if selected else MODEL_LABELS["zero"],
        "selection_rule": (
            "A fitted candidate is eligible only if its pooled rolling-origin validation MAE is "
            "strictly lower than the pooled zero-change MAE on the same rows. Among eligible "
            "candidates, choose the lowest pooled MAE; ties break on lower RMSE, higher "
            "low-movement F1, higher directional accuracy, then candidate id. If none qualify, "
            "freeze the zero-change forecast."
        ),
        "zero_pooled_metrics": zero_pooled,
        "zero_fold_metrics": zero_fold,
        "fold_checks": fold_check,
        "n_eligible": len(eligible),
        "eligible_candidate_ids": [c["candidate_id"] for c in eligible],
        "selected_candidate": selected,
        "candidates": [{k: v for k, v in c.items() if k != "fold_metrics"} for c in candidates],
        "features": FEATURES,
        "medians_by_horizon": medians,
        "final_training_rows_by_horizon": n_by_horizon,
        "dataset_sha256": _sha256(DATASET_PATH),
        "forecast_features_sha256": _sha256(FEATURES_PATH),
        "prereg_sha256": _sha256(PREREG_PATH),
        "random_seed": RANDOM_SEED,
        "forecast_supported": False,
        "second_look": True,
        "test_years_seen_before_experiment": list(FORECAST_YEARS),
    }
    write_json(STAGING_DIR / "model_metadata.json", _json_safe(metadata))
    forecast = pd.read_csv(STAGING_DIR / "forecast_features_2024.csv")
    summary_by_year = {}
    for year in FORECAST_YEARS:
        h = year - ORIGIN_YEAR
        frame = forecast[forecast["forecast_year"] == year].copy()
        art = artifacts[h]
        if art["kind"] == "zero":
            p = np.zeros(len(frame), dtype=float)
        else:
            p = art["pipeline"].predict(frame[art["features"]])
        frame["predicted_displacement_m"] = p
        frame["predicted_rate_m_per_yr"] = p / frame["elapsed_years"].to_numpy(dtype=float)
        frame["abs_displacement_m"] = np.abs(p)
        frame["predicted_class"] = np.where(p > LOW_MOVEMENT_M, "erosion", np.where(p < -LOW_MOVEMENT_M, "accretion", "low_movement"))
        frame["predicted_to_move"] = np.abs(p) > LOW_MOVEMENT_M
        frame["origin_year"] = ORIGIN_YEAR
        frame["year"] = year
        columns = [
            "year",
            "origin_year",
            "horizon_years",
            "sample_id",
            "transect_id",
            "side",
            "reach",
            "origin_bank_x",
            "origin_bank_y",
            "normal_x",
            "normal_y",
            "outward_sign",
            "elapsed_years",
            "predicted_displacement_m",
            "predicted_rate_m_per_yr",
            "abs_displacement_m",
            "predicted_class",
            "predicted_to_move",
        ]
        frame[columns].to_csv(STAGING_DIR / f"predictions_{year}.csv", index=False)
        summary_by_year[str(year)] = {
            "n": int(len(frame)),
            "counts": {k: int((frame["predicted_class"] == k).sum()) for k in ["erosion", "accretion", "low_movement"]},
            "share_predicted_move": float(frame["predicted_to_move"].mean()),
            "mean_m": float(frame["predicted_displacement_m"].mean()),
            "median_m": float(frame["predicted_displacement_m"].median()),
            "mean_abs_m": float(frame["abs_displacement_m"].mean()),
            "by_reach": {
                str(reach): {
                    "n": int(len(g)),
                    "mean_m": float(g["predicted_displacement_m"].mean()),
                    "share_predicted_move": float(g["predicted_to_move"].mean()),
                }
                for reach, g in frame.groupby("reach")
            },
        }
    summary = {
        "status": "staging",
        "created_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "origin_year": ORIGIN_YEAR,
        "forecast_years": list(FORECAST_YEARS),
        "training_cutoff_year": TRAINING_CUTOFF_YEAR,
        "selected_model": selected_id,
        "selected_kind": selected_kind,
        "selected_label": metadata["selected_label"],
        "features": FEATURES,
        "n_transects": int(forecast["transect_id"].nunique()),
        "n_segments_per_year": int(len(forecast) / len(FORECAST_YEARS)),
        "by_year": summary_by_year,
        "forecast_supported": False,
        "second_look": True,
        "test_years_seen_before_experiment": list(FORECAST_YEARS),
        "note": (
            "Second look: 2024 is a training year and 2025-2026 were already seen in the v1 test. "
            "Predictions are conditional on the observed 2024 banks and fixed transects. "
            "forecast_supported remains false."
        ),
    }
    write_json(STAGING_DIR / "summary.json", _json_safe(summary))
    return {
        "n_folds": len(folds),
        "zero_pooled": zero_pooled,
        "n_candidates": len(candidates),
        "n_eligible": len(eligible),
        "selected": selected_id,
        "summary": summary,
    }


def _verify_prereg() -> None:
    if not PREREG_PATH.exists():
        raise RuntimeError("Pre-registration is missing.")
    if "second look, not blind" not in PREREG_PATH.read_text(encoding="utf-8").lower():
        raise RuntimeError("Pre-registration does not contain the required title.")


def freeze() -> dict:
    _verify_prereg()
    if not STAGING_DIR.exists():
        raise RuntimeError("No origin-2024 staging forecast; run tune first.")
    if FROZEN_DIR.exists() and any(FROZEN_DIR.iterdir()):
        raise RuntimeError("forecasts/frozen_origin2024 is not empty; refusing to overwrite.")
    summary = json.load(open(STAGING_DIR / "summary.json", encoding="utf-8"))
    if summary.get("status") != "staging":
        raise RuntimeError("Staging summary is not in staging state.")
    if summary.get("forecast_supported") is not False:
        raise RuntimeError("Origin-2024 forecast_supported must remain false.")
    frozen_summary = dict(summary)
    frozen_summary["status"] = "frozen"
    frozen_summary["frozen_utc"] = dt.datetime.now(dt.timezone.utc).isoformat()
    FROZEN_DIR.mkdir(parents=True, exist_ok=True)
    files = []
    for src in sorted(STAGING_DIR.iterdir()):
        if not src.is_file():
            continue
        dst = FROZEN_DIR / src.name
        if src.name == "summary.json":
            write_json(dst, _json_safe(frozen_summary))
        else:
            shutil.copy2(src, dst)
        files.append({"name": src.name, "sha256": _sha256(dst), "size": dst.stat().st_size})
    manifest = {
        "frozen": True,
        "frozen_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "origin_year": ORIGIN_YEAR,
        "forecast_years": list(FORECAST_YEARS),
        "training_cutoff_year": TRAINING_CUTOFF_YEAR,
        "selected_model": summary["selected_model"],
        "selected_label": summary["selected_label"],
        "forecast_supported": False,
        "second_look": True,
        "test_years_seen_before_experiment": list(FORECAST_YEARS),
        "features": FEATURES,
        "files": files,
        "inputs": {
            "prereg_sha256": _sha256(PREREG_PATH),
            "dataset_sha256": _sha256(DATASET_PATH),
            "forecast_features_sha256": _sha256(FEATURES_PATH),
            "v1_forecast_ready": _v1_hashes()["frozen_ready"],
            "v1_metrics_sha256": _v1_hashes()["metrics_sha256"],
            "v1_model_sha256": _v1_hashes()["model_sha256"],
            "code": {
                "origin2024.py": _sha256(project_path("src", "riverforecast", "origin2024.py")),
            },
        },
        "note": summary["note"],
    }
    write_json(FROZEN_DIR / "manifest.json", _json_safe(manifest))
    ready_hash = _sha256(FROZEN_DIR / "manifest.json")
    (FROZEN_DIR / "READY").write_text(ready_hash + "\n", encoding="utf-8")
    for item in manifest["files"]:
        if _sha256(FROZEN_DIR / item["name"]) != item["sha256"]:
            raise RuntimeError(f"Frozen file hash mismatch: {item['name']}")
    return manifest


def _verify_frozen() -> dict:
    manifest_path = FROZEN_DIR / "manifest.json"
    ready_path = FROZEN_DIR / "READY"
    if not manifest_path.exists() or not ready_path.exists():
        raise RuntimeError("Origin-2024 freeze is missing.")
    if ready_path.read_text(encoding="utf-8").strip() != _sha256(manifest_path):
        raise RuntimeError("Origin-2024 READY hash does not match manifest.json.")
    manifest = json.load(open(manifest_path, encoding="utf-8"))
    if not manifest.get("frozen") or manifest.get("forecast_supported") is not False:
        raise RuntimeError("Origin-2024 manifest is not a frozen unsupported second look.")
    if int(manifest["training_cutoff_year"]) != 2024 or int(manifest["origin_year"]) != 2024:
        raise RuntimeError("Origin-2024 manifest has the wrong cutoff or origin.")
    if set(int(y) for y in manifest["forecast_years"]) != set(FORECAST_YEARS):
        raise RuntimeError("Origin-2024 manifest has the wrong forecast years.")
    inputs = manifest["inputs"]
    if inputs["prereg_sha256"] != _sha256(PREREG_PATH):
        raise RuntimeError("Pre-registration changed after freeze.")
    if inputs["dataset_sha256"] != _sha256(DATASET_PATH):
        raise RuntimeError("Origin-2024 dataset changed after freeze.")
    if inputs["forecast_features_sha256"] != _sha256(FEATURES_PATH):
        raise RuntimeError("Origin-2024 forecast features changed after freeze.")
    for name, expected in inputs["code"].items():
        if _sha256(project_path("src", "riverforecast", name)) != expected:
            raise RuntimeError(f"Origin-2024 code changed after freeze: {name}")
    for item in manifest["files"]:
        path = FROZEN_DIR / item["name"]
        if not path.exists() or _sha256(path) != item["sha256"]:
            raise RuntimeError(f"Origin-2024 frozen file changed: {item['name']}")
    return manifest


def _parse_flags(value) -> set[str]:
    if isinstance(value, (list, tuple, set)):
        return {str(v) for v in value}
    if not isinstance(value, str) or value in {"", "[]", "nan", "None"}:
        return set()
    import ast

    try:
        parsed = ast.literal_eval(value)
        return {str(v) for v in parsed} if isinstance(parsed, (list, tuple, set)) else {str(parsed)}
    except Exception:  # noqa: BLE001
        return {value}


def _good_eval(row, min_width: float) -> bool:
    flags = _parse_flags(row.get("flags"))
    return bool(
        row["valid_bank"]
        and row["center_inside"]
        and not ({"missing_bank", "multiple_crossings", "width_below_min"} & flags)
        and not row["border_transect"]
        and not math.isnan(float(row["width_m"]))
        and float(row["width_m"]) >= min_width
    )


def _classify(d: float, tol: float) -> str:
    if math.isnan(d):
        return "invalid"
    if d > tol:
        return "erosion"
    if d < -tol:
        return "accretion"
    return "low_movement"


def _evaluation_frame(manifest: dict) -> pd.DataFrame:
    cfg = load_config()
    frozen_features = pd.read_csv(FROZEN_DIR / "forecast_features_2024.csv")
    origin = pd.read_csv(project_path("evaluation", "observed_bank_positions_2024.csv"))
    origin = origin.set_index(["transect_id", "side"])
    min_width = float(cfg["transects"]["min_width_m"])
    tol = LOW_MOVEMENT_M
    rows = []
    for year in FORECAST_YEARS:
        target = pd.read_csv(project_path("evaluation", f"observed_bank_positions_{year}.csv"))
        target = target.set_index(["transect_id", "side"])
        pred = pd.read_csv(FROZEN_DIR / f"predictions_{year}.csv").set_index(["transect_id", "side"])
        feat = frozen_features[frozen_features["forecast_year"] == year].set_index(["transect_id", "side"])
        for key in sorted(set(origin.index) & set(target.index) & set(pred.index) & set(feat.index)):
            o = origin.loc[key]
            t = target.loc[key]
            s = pred.loc[key]
            f = feat.loc[key]
            valid = bool(o["valid_bank"] and t["valid_bank"])
            d_obs = np.nan
            if valid:
                dx = float(t["bank_x"] - o["bank_x"])
                dy = float(t["bank_y"] - o["bank_y"])
                d_obs = (dx * float(o["normal_x"]) + dy * float(o["normal_y"])) * float(o["outward_sign"])
            elapsed = float(f["elapsed_years"])
            quality = "good" if _good_eval(o, min_width) and _good_eval(t, min_width) else "flagged"
            if not valid:
                quality = "invalid"
            last_rate = float(f["last_rate_m_per_yr"])
            last3 = float(f["last3_mean_rate_m_per_yr"])
            last2 = float(f["last2_mean_rate_m_per_yr"])
            if math.isnan(last3):
                last3 = last2
            if math.isnan(last3):
                last3 = last_rate
            row = {
                "year": year,
                "origin_year": ORIGIN_YEAR,
                "horizon_years": int(year - ORIGIN_YEAR),
                "transect_id": int(key[0]),
                "side": key[1],
                "reach": o["reach"],
                "elapsed_years": elapsed,
                "observed_displacement_m": d_obs,
                "observed_class": _classify(d_obs, tol),
                "label_quality": quality,
                "selected_prediction_m": float(s["predicted_displacement_m"]),
                "zero_prediction_m": 0.0,
                "persistence_prediction_m": 0.0 if math.isnan(last_rate) else last_rate * elapsed,
                "trend_prediction_m": 0.0 if math.isnan(last3) else last3 * elapsed,
                "last_rate_2024_m_per_yr": last_rate,
                "last3_mean_2024_m_per_yr": last3,
                "origin_flags": o["flags"],
                "observed_flags": t["flags"],
            }
            rows.append(row)
    out = pd.DataFrame(rows)
    medians = json.load(open(FROZEN_DIR / "model_metadata.json", encoding="utf-8"))["medians_by_horizon"]
    out["median_prediction_m"] = out["horizon_years"].astype(str).map(medians)
    for col in ["selected_prediction_m", "zero_prediction_m", "persistence_prediction_m", "trend_prediction_m", "median_prediction_m"]:
        out[col.replace("_prediction_m", "_error_m")] = out[col] - out["observed_displacement_m"]
        out[col.replace("_prediction_m", "_abs_error_m")] = out[col.replace("_prediction_m", "_error_m")].abs()
    out["selected_to_move"] = out["selected_prediction_m"].abs() > tol
    out["observed_to_move"] = out["observed_displacement_m"].abs() > tol
    return out


def _metrics_with_share(sub: pd.DataFrame, col: str) -> dict:
    y = sub["observed_displacement_m"].to_numpy(dtype=float)
    p = sub[col].to_numpy(dtype=float)
    m = _metrics(y, p)
    m["share_predicted_move"] = float(np.mean(np.abs(p) > LOW_MOVEMENT_M))
    m["share_observed_move"] = float(np.mean(np.abs(y) > LOW_MOVEMENT_M))
    return _json_safe(m)


def _bootstrap(pred: pd.DataFrame) -> dict:
    rng = np.random.default_rng(RANDOM_SEED)
    clusters = [g for _, g in pred.groupby("transect_id", sort=True)]
    model_cols = {
        "selected": "selected_abs_error_m",
        "median": "median_abs_error_m",
        "persistence": "persistence_abs_error_m",
        "trend": "trend_abs_error_m",
    }
    zero = pred["zero_abs_error_m"].to_numpy(dtype=float)
    out = {}
    for name, col in model_cols.items():
        values = pred[col].to_numpy(dtype=float)
        observed = float(values.mean() - zero.mean())
        draws = np.empty(BOOTSTRAP_DRAWS, dtype=float)
        for i in range(BOOTSTRAP_DRAWS):
            chosen = rng.integers(0, len(clusters), len(clusters))
            mae_model = []
            mae_zero = []
            for j in chosen:
                g = clusters[j]
                mae_model.append(float(g[col].mean()))
                mae_zero.append(float(g["zero_abs_error_m"].mean()))
            draws[i] = np.mean(mae_model) - np.mean(mae_zero)
        out[name] = {
            "difference_mae_m": observed,
            "ci90_low_m": float(np.quantile(draws, BOOTSTRAP_ALPHA / 2)),
            "ci90_high_m": float(np.quantile(draws, 1 - BOOTSTRAP_ALPHA / 2)),
            "n_bootstrap": BOOTSTRAP_DRAWS,
            "n_transects": len(clusters),
            "seed": RANDOM_SEED,
        }
    return _json_safe(out)


def evaluate() -> dict:
    manifest = _verify_frozen()
    EVALUATION_DIR.mkdir(parents=True, exist_ok=True)
    pred = _evaluation_frame(manifest)
    pred.to_csv(EVALUATION_DIR / "predictions.csv", index=False)
    good = pred[pred["label_quality"] == "good"].copy()
    models = {
        "selected": "selected_prediction_m",
        "zero": "zero_prediction_m",
        "median": "median_prediction_m",
        "persistence": "persistence_prediction_m",
        "trend": "trend_prediction_m",
    }
    metrics = {
        "created_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "second_look": True,
        "forecast_supported": False,
        "origin_year": ORIGIN_YEAR,
        "test_years": list(FORECAST_YEARS),
        "test_years_seen_before_experiment": list(FORECAST_YEARS),
        "n_pairs": int(len(pred)),
        "n_good_pairs": int(len(good)),
        "n_flagged_or_invalid": int(len(pred) - len(good)),
        "low_movement_tolerance_m": LOW_MOVEMENT_M,
        "selected_model": manifest["selected_model"],
        "selected_label": manifest["selected_label"],
        "models": {},
    }
    for name, col in models.items():
        sub = good[good[col].notna()]
        m = _metrics_with_share(sub, col)
        m["by_horizon"] = {
            str(int(h)): _metrics_with_share(g, col)
            for h, g in sub.groupby("horizon_years")
        }
        m["by_year"] = {
            str(int(y)): _metrics_with_share(g, col)
            for y, g in sub.groupby("year")
        }
        m["by_reach"] = {
            str(r): _metrics_with_share(g, col)
            for r, g in sub.groupby("reach")
        }
        metrics["models"][name] = m
    bootstrap = _bootstrap(good)
    write_json(EVALUATION_DIR / "bootstrap.json", bootstrap)
    write_json(EVALUATION_DIR / "metrics.json", _json_safe(metrics))
    old_metrics = json.load(open(project_path("evaluation", "metrics.json"), encoding="utf-8"))
    old_models = {
        "random_forest": "random_forest",
        "zero": "zero",
        "median": "median",
        "persistence": "persistence",
        "trend": "trend",
    }
    old = {}
    for label, key in old_models.items():
        old[label] = {
            str(y): old_metrics["models"][key]["by_year"].get(str(y))
            for y in FORECAST_YEARS
        }
    write_json(EVALUATION_DIR / "old_vs_new.json", _json_safe({
        "old_source": "evaluation/metrics.json",
        "old_origin_year": old_metrics["origin_year"],
        "new_origin_year": ORIGIN_YEAR,
        "old": old,
        "new": {
            name: {
                str(y): metrics["models"][name]["by_year"].get(str(y))
                for y in FORECAST_YEARS
            }
            for name in metrics["models"]
        },
    }))
    _write_report(metrics, bootstrap, old_metrics, pred, manifest)
    return {"metrics": metrics, "bootstrap": bootstrap}


def _f(v, nd=2) -> str:
    if v is None:
        return "—"
    try:
        if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
            return "—"
        return f"{float(v):.{nd}f}"
    except Exception:  # noqa: BLE001
        return "—"


def _pct(v, nd=1) -> str:
    if v is None:
        return "—"
    return f"{100*float(v):.{nd}f}%"


def _write_report(metrics: dict, bootstrap: dict, old_metrics: dict, pred: pd.DataFrame, manifest: dict) -> None:
    good = pred[pred["label_quality"] == "good"]
    metadata = json.load(open(FROZEN_DIR / "model_metadata.json", encoding="utf-8"))
    summary = json.load(open(FROZEN_DIR / "summary.json", encoding="utf-8"))
    lines = [
        "# Second look, not blind",
        "",
        "This is the origin-2024 refit. It is **not a blind test**: 2024 was moved into training and "
        "2025–2026 had already been seen in the v1 test. `forecast_supported` remains **false**.",
        "",
        "The v1 frozen forecast, `evaluation/metrics.json` and `models/final_models.joblib` were not "
        "modified. Old numbers below are read from the immutable v1 metrics file.",
        "",
        "## What changed",
        "",
        "- Origin: **2024** (v1 origin was 2023).",
        "- Training target cutoff: **2024**.",
        "- Forecast horizons: **1 and 2 only** (2025 and 2026).",
        "- 2024 observations were previously part of the v1 test; they are now training data.",
        "- 2025 and 2026 were seen before this experiment and are used for one second-look score only.",
        "",
        f"- Training rows target ≤ 2024: **{metadata['final_training_rows_by_horizon'].get('1', 0) + metadata['final_training_rows_by_horizon'].get('2', 0)}** usable rows across both horizons.",
        f"- Rolling-origin folds used for choice: **{metadata['fold_checks']['n_folds']}**, maximum validation target **{metadata['fold_checks']['max_validation_target_year']}**.",
        f"- Candidate configurations logged: **{len(metadata['candidates'])}**; eligible by zero-change gate: **{metadata['n_eligible']}**.",
        f"- Selected predictor: **{manifest['selected_label']}** (`{manifest['selected_model']}`).",
        "",
    ]
    if metadata["n_eligible"] == 0:
        lines += [
            "> No fitted candidate beat zero change on the pooled rolling-origin validation folds. "
            "The frozen origin-2024 forecast is therefore the zero-change baseline, as pre-registered.",
            "",
        ]
    lines += [
        "## Validation result",
        "",
        f"Zero-change pooled validation MAE: **{_f(metadata['zero_pooled_metrics']['mae_m'])} m**.",
        "",
        "| Candidate | Pooled MAE (m) | RMSE (m) | Low-movement F1 | Directional accuracy | Eligible |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for c in metadata["candidates"]:
        p = c["pooled"]
        lines.append(
            f"| `{c['candidate_id']}` | {_f(p['mae_m'])} | {_f(p['rmse_m'])} | {_f(p['low_movement_f1'], 3)} | "
            f"{_f(p['directional_accuracy_moving'], 3)} | {'yes' if c['eligible'] else 'no'} |"
        )
    lines += [
        "",
        "The gate is strict: a candidate needed a pooled MAE lower than zero change on the same "
        "validation rows. No 2025 or 2026 observation entered this choice.",
        "",
        "## Frozen forecast",
        "",
        "| Year | Erosion | Accretion | Low movement | Share predicted to move | Mean (m) |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for y, s in summary["by_year"].items():
        c = s["counts"]
        lines.append(
            f"| {y} | {c['erosion']} | {c['accretion']} | {c['low_movement']} | "
            f"{_pct(s['share_predicted_move'])} | {s['mean_m']:+.2f} |"
        )
    lines += [
        "",
        "The forecast is conditional on the observed 2024 banks and fixed 2023 transects. It is not "
        "a hydrodynamic or sediment-transport simulation.",
        "",
        "## 2025–2026 score",
        "",
        f"Scored pairs: **{metrics['n_good_pairs']}** good of **{metrics['n_pairs']}**; "
        f"{metrics['n_flagged_or_invalid']} flagged or invalid pairs excluded.",
        "",
        "| Model | n | MAE (m) | RMSE (m) | Bias (m) | Within ±15 m | Low-movement F1 | Directional accuracy | Predicted move |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    labels = {
        "selected": "Selected origin-2024 forecast",
        "zero": "Zero change",
        "median": "Training median",
        "persistence": "Persistence",
        "trend": "Historic trend",
    }
    for name, m in metrics["models"].items():
        lines.append(
            f"| {labels[name]} | {m['n']} | {_f(m['mae_m'])} | {_f(m['rmse_m'])} | {_f(m['bias_m'])} | "
            f"{_f(m['within_15m'], 3)} | {_f(m['low_movement_f1'], 3)} | "
            f"{_f(m['directional_accuracy_moving'], 3)} | {_pct(m['share_predicted_move'])} |"
        )
    lines += [
        "",
        "## Paired difference from zero change",
        "",
        "Negative values mean the model has a lower MAE than zero change. The interval is a 90% "
        "transect-cluster bootstrap with 10,000 draws.",
        "",
        "| Model | MAE difference (m) | 90% interval |",
        "|---|---:|---:|",
    ]
    for name, b in bootstrap.items():
        lines.append(
            f"| {labels[name]} | {_f(b['difference_mae_m'])} | "
            f"[{_f(b['ci90_low_m'])}, {_f(b['ci90_high_m'])}] |"
        )
    lines += [
        "",
        "## Old versus new, 2025 and 2026",
        "",
        "The old v1 model used origin 2023; the new model uses origin 2024. They therefore score "
        "different eligible bank pairs, and the comparison is not a paired like-for-like test. Old "
        "numbers are taken from `evaluation/metrics.json`; new numbers are from this run.",
        "",
        "| Year | Run | Model | n | MAE (m) | RMSE (m) | Bias (m) | Predicted move |",
        "|---:|---|---|---:|---:|---:|---:|---:|",
    ]
    old_label = {
        "random_forest": "v1 random forest",
        "zero": "v1 zero",
        "median": "v1 median",
        "persistence": "v1 persistence",
        "trend": "v1 trend",
    }
    for y in FORECAST_YEARS:
        for old_name, old_label_name in old_label.items():
            m = old_metrics["models"][old_name]["by_year"].get(str(y))
            if m:
                lines.append(
                    f"| {y} | v1, origin 2023 | {old_label_name} | {m['n']} | {_f(m['mae_m'])} | "
                    f"{_f(m['rmse_m'])} | {_f(m['bias_m'])} | — |"
                )
        for name in ["selected", "zero", "median", "persistence", "trend"]:
            m = metrics["models"][name]["by_year"].get(str(y))
            if m:
                lines.append(
                    f"| {y} | new, origin 2024 | {labels[name]} | {m['n']} | {_f(m['mae_m'])} | "
                    f"{_f(m['rmse_m'])} | {_f(m['bias_m'])} | {_pct(m['share_predicted_move'])} |"
                )
    lines += [
        "",
        "## What this means",
        "",
    ]
    selected_metrics = metrics["models"]["selected"]
    zero_metrics = metrics["models"]["zero"]
    if selected_metrics["mae_m"] < zero_metrics["mae_m"]:
        lines.append(
            "The selected origin-2024 forecast has a lower MAE than zero change on the already-seen "
            "2025–2026 pairs. That is a second-look result, not a blind validation, and it does not "
            "establish that the model will generalise."
        )
    else:
        lines.append(
            "The selected origin-2024 forecast does not beat zero change on the already-seen 2025–2026 "
            "pairs. The honest result is that moving 2024 into training did not produce a model that "
            "beats the trivial baseline here."
        )
    lines += [
        "",
        "The selected predictor is the zero-change fallback."
        if metadata["n_eligible"] == 0
        else "The selected predictor is a fitted candidate that passed the pre-registered zero-change gate.",
        "",
        "`forecast_supported` is false. No forecast line or claim of validation should be built on this "
        "second look. The exact frozen files and hashes are in `forecasts/frozen_origin2024/manifest.json`.",
        "",
        "## Limits",
        "",
        "- 2025 and 2026 are not unseen years; the v1 test had already opened them.",
        "- 2024 is now training data, so the two runs use different origins and different eligible pairs.",
        "- The labels are 30 m water-mask bank positions, not surveyed ground truth.",
        "- No post-score model, feature, fold or threshold change was made.",
        "- The test is one reach and two years.",
    ]
    REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Origin-2024 second-look pipeline")
    parser.add_argument("stage", choices=["prepare", "tune", "freeze", "evaluate", "all-before-test"])
    args = parser.parse_args()
    if args.stage in {"prepare", "all-before-test"}:
        print(json.dumps(_json_safe(prepare()), indent=2))
    if args.stage == "tune":
        print(json.dumps(_json_safe(tune()), indent=2))
    if args.stage == "freeze":
        print(json.dumps(_json_safe(freeze()), indent=2))
    if args.stage == "evaluate":
        print(json.dumps(_json_safe(evaluate()), indent=2))
    if args.stage == "all-before-test":
        print(json.dumps(_json_safe(tune()), indent=2))
        print(json.dumps(_json_safe(freeze()), indent=2))


if __name__ == "__main__":
    main()
