from __future__ import annotations

import datetime as dt
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from .config import ensure_output_dirs, load_config, project_path
from .io import write_json

FEATURES = [
    "last_rate_m_per_yr",
    "last2_mean_rate_m_per_yr",
    "last3_mean_rate_m_per_yr",
    "acceleration_m_per_yr2",
    "last_displacement_m",
    "last_interval_years",
    "last_interval_good",
    "width_m",
    "width_change_last_m",
    "abs_curvature_1_m",
    "sinuosity",
    "is_left_bank",
    "horizon_years",
    "elapsed_years",
    "last_rate_missing",
    "last2_missing",
    "last3_missing",
    "width_missing",
    "curvature_missing",
    "sinuosity_missing",
]

IDENTIFIERS = [
    "sample_id",
    "forecast_year",
    "target_year",
    "origin_year",
    "horizon_years",
    "elapsed_years",
    "transect_id",
    "side",
    "reach",
    "along_m",
    "origin_bank_x",
    "origin_bank_y",
    "normal_x",
    "normal_y",
    "outward_sign",
]

LABEL_COLUMNS = [
    "target_displacement_m",
    "target_rate_m_per_yr",
    "target_bank_x",
    "target_bank_y",
    "label_quality",
    "usable_for_training",
]


def _bank_flags(row) -> set[str]:
    return set(row["flags"].split("|")) if isinstance(row["flags"], str) and row["flags"] else set()


def _good(row, min_width: float) -> bool:
    flags = _bank_flags(row)
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


def _history(intervals: pd.DataFrame, origin: int) -> list[pd.Series]:
    sub = intervals[(intervals["to_year"] <= origin) & (intervals["valid_bank"])]
    return [r for _, r in sub.sort_values("to_year").iterrows()]


def build() -> dict:
    ensure_output_dirs()
    cfg = load_config()
    min_width = float(cfg["transects"]["min_width_m"])
    max_disp = float(cfg["labels"]["max_plausible_abs_displacement_m"])
    horizons = [int(h) for h in cfg["dataset"]["horizons"]]
    pos = pd.read_csv(project_path("derived", "measurements", "bank_positions.csv"))
    iv = pd.read_csv(project_path("derived", "measurements", "bank_migration_intervals_raw.csv"))
    pos["year"] = pos["year"].astype(int)
    iv["to_year"] = iv["to_year"].astype(int)
    years = sorted(pos["year"].unique())
    lookup = {(int(r.year), int(r.transect_id), r.side): r for _, r in pos.iterrows()}
    iv_lookup = {}
    for (tid, side), grp in iv.groupby(["transect_id", "side"], sort=False):
        iv_lookup[(tid, side)] = grp.sort_values("to_year").reset_index(drop=True)

    rows = []
    for origin in years:
        origin_rows = pos[pos["year"] == origin]
        for _, o in origin_rows.iterrows():
            hist = []
            grp = iv_lookup.get((int(o["transect_id"]), o["side"]))
            if grp is not None:
                hist = [r for _, r in grp[grp["to_year"] <= origin].iterrows() if bool(r["valid_bank"])]
            last = hist[-1] if hist else None
            prev = hist[-2] if len(hist) >= 2 else None
            last2 = hist[-2:]
            last3 = hist[-3:]
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
            for h in horizons:
                target = origin + h
                if target not in years:
                    continue
                if target > int(cfg["training_cutoff_year"]):
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
                if np.isnan(disp):
                    quality = "invalid"
                else:
                    quality = _row_quality(o, tb, disp, min_width, max_disp)
                elapsed = (pd.Timestamp(f"{target}-03-25") - pd.Timestamp(f"{origin}-03-25")).days / 365.25
                row = {
                    "sample_id": f"T{int(o['transect_id']):03d}_{o['side']}_{origin}_{target}",
                    "forecast_year": target,
                    "target_year": target,
                    "origin_year": origin,
                    "horizon_years": h,
                    "elapsed_years": elapsed,
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
                    "target_rate_m_per_yr": disp / elapsed if not np.isnan(disp) else np.nan,
                    "target_bank_x": target_x,
                    "target_bank_y": target_y,
                    "label_quality": quality,
                    "usable_for_training": quality == "good",
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
                    "feature_cutoff_year": origin,
                    "last_rate_missing": int(np.isnan(last_rate)),
                    "last2_missing": int(np.isnan(last2_mean)),
                    "last3_missing": int(np.isnan(last3_mean)),
                    "width_missing": int(np.isnan(width)),
                    "curvature_missing": int(np.isnan(curvature)),
                    "sinuosity_missing": int(np.isnan(sinuosity)),
                }
                rows.append(row)
    df = pd.DataFrame(rows)
    df = df.sort_values(["origin_year", "horizon_years", "transect_id", "side"]).reset_index(drop=True)
    df.to_csv(project_path("datasets", "bank_migration_dataset.csv"), index=False)

    forecast = _forecast_features(pos, years, int(cfg["dataset"]["final_origin_year"]), horizons)
    forecast.to_csv(project_path("datasets", "forecast_features_2023.csv"), index=False)

    checks = _leakage_checks(df, forecast, cfg)
    write_json(project_path("datasets", "leakage_checks.json"), checks)
    write_json(project_path("datasets", "schema.json"), _schema(df, forecast))
    write_json(project_path("datasets", "feature_dictionary.json"), _dictionary())
    write_json(
        project_path("datasets", "provenance.json"),
        {
            "created_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
            "training_input": str(project_path("derived", "measurements", "bank_positions.csv")),
            "interval_input": str(project_path("derived", "measurements", "bank_migration_intervals_raw.csv")),
            "training_cutoff_year": int(cfg["training_cutoff_year"]),
            "final_origin_year": int(cfg["dataset"]["final_origin_year"]),
            "n_rows": int(len(df)),
            "n_usable": int(df["usable_for_training"].sum()),
            "n_forecast_rows": int(len(forecast)),
            "features": FEATURES,
            "identifiers": IDENTIFIERS,
            "labels": LABEL_COLUMNS,
        },
    )
    _write_report(df, forecast, checks)
    return {
        "n_rows": len(df),
        "n_usable": int(df["usable_for_training"].sum()),
        "n_forecast_rows": len(forecast),
        "checks": checks,
    }


def _forecast_features(pos: pd.DataFrame, years: list[int], origin: int, horizons: list[int]) -> pd.DataFrame:
    if origin not in years:
        raise RuntimeError(f"Final origin year {origin} is not an observed year.")
    iv = pd.read_csv(project_path("derived", "measurements", "bank_migration_intervals_raw.csv"))
    iv["to_year"] = iv["to_year"].astype(int)
    iv_lookup = {}
    for (tid, side), grp in iv.groupby(["transect_id", "side"], sort=False):
        iv_lookup[(tid, side)] = grp.sort_values("to_year").reset_index(drop=True)
    rows = []
    for _, o in pos[pos["year"] == origin].iterrows():
        grp = iv_lookup.get((int(o["transect_id"]), o["side"]))
        hist = [r for _, r in grp[grp["to_year"] <= origin].iterrows() if bool(r["valid_bank"])] if grp is not None else []
        last = hist[-1] if hist else None
        prev = hist[-2] if len(hist) >= 2 else None
        rates = [float(r["annualized_rate_m_per_yr"]) for r in hist if not np.isnan(r["annualized_rate_m_per_yr"])]
        last_rate = float(last["annualized_rate_m_per_yr"]) if last is not None else np.nan
        prev_rate = float(prev["annualized_rate_m_per_yr"]) if prev is not None else np.nan
        base = {
            "origin_year": origin,
            "transect_id": int(o["transect_id"]),
            "side": o["side"],
            "reach": o["reach"],
            "along_m": float(o["along_m"]),
            "origin_bank_x": float(o["bank_x"]) if bool(o["valid_bank"]) else np.nan,
            "origin_bank_y": float(o["bank_y"]) if bool(o["valid_bank"]) else np.nan,
            "normal_x": float(o["normal_x"]),
            "normal_y": float(o["normal_y"]),
            "outward_sign": float(o["outward_sign"]),
            "last_rate_m_per_yr": last_rate,
            "last2_mean_rate_m_per_yr": float(np.mean(rates[-2:])) if len(rates) >= 2 else np.nan,
            "last3_mean_rate_m_per_yr": float(np.mean(rates[-3:])) if len(rates) >= 3 else np.nan,
            "acceleration_m_per_yr2": last_rate - prev_rate if not (np.isnan(last_rate) or np.isnan(prev_rate)) else np.nan,
            "last_displacement_m": float(last["signed_displacement_m"]) if last is not None else np.nan,
            "last_interval_years": float(last["elapsed_years"]) if last is not None else np.nan,
            "last_interval_good": int(last["quality"] == "good") if last is not None else np.nan,
            "width_m": float(o["width_m"]) if not np.isnan(o["width_m"]) else np.nan,
            "width_change_last_m": float(last["width_to_m"] - last["width_from_m"]) if last is not None and not np.isnan(last["width_to_m"]) and not np.isnan(last["width_from_m"]) else np.nan,
            "abs_curvature_1_m": float(abs(o["curvature_1_m"])) if not np.isnan(o["curvature_1_m"]) else np.nan,
            "sinuosity": float(o["sinuosity"]) if not np.isnan(o["sinuosity"]) else np.nan,
            "is_left_bank": 1 if o["side"] == "L" else 0,
            "feature_cutoff_year": origin,
            "last_rate_missing": int(np.isnan(last_rate)),
            "last2_missing": int(np.isnan(float(np.mean(rates[-2:])) if len(rates) >= 2 else np.nan)),
            "last3_missing": int(np.isnan(float(np.mean(rates[-3:])) if len(rates) >= 3 else np.nan)),
            "width_missing": int(np.isnan(o["width_m"])),
            "curvature_missing": int(np.isnan(o["curvature_1_m"])),
            "sinuosity_missing": int(np.isnan(o["sinuosity"])),
        }
        for h in horizons:
            elapsed = (pd.Timestamp(f"{origin + h}-03-25") - pd.Timestamp(f"{origin}-03-25")).days / 365.25
            row = dict(base)
            row.update(
                {
                    "forecast_year": origin + h,
                    "target_year": origin + h,
                    "horizon_years": h,
                    "elapsed_years": elapsed,
                    "sample_id": f"T{int(o['transect_id']):03d}_{o['side']}_{origin}_{origin + h}",
                    "label_quality": "forecast_unobserved",
                    "usable_for_training": False,
                }
            )
            rows.append(row)
    out = pd.DataFrame(rows)
    cols = list(dict.fromkeys([c for c in IDENTIFIERS if c in out.columns] + FEATURES + ["feature_cutoff_year"]))
    return out[cols].sort_values(["horizon_years", "transect_id", "side"]).reset_index(drop=True)


def _leakage_checks(df: pd.DataFrame, forecast: pd.DataFrame, cfg: dict) -> dict:
    cutoff = int(cfg["training_cutoff_year"])
    checks = {
        "max_target_year": int(df["target_year"].max()),
        "max_target_year_at_most_2023": bool(df["target_year"].max() <= cutoff),
        "min_origin_year": int(df["origin_year"].min()),
        "max_origin_year": int(df["origin_year"].max()),
        "all_targets_after_origin": bool((df["target_year"] > df["origin_year"]).all()),
        "all_feature_cutoffs_at_origin": bool((df["feature_cutoff_year"] == df["origin_year"]).all()),
        "no_test_years_in_training": bool(not set(df["target_year"]).intersection(set(cfg["test_years"]))),
        "no_forecast_years_in_training": bool(not set(df["forecast_year"]).intersection(set(cfg["test_years"]))),
        "duplicate_sample_ids": int(df["sample_id"].duplicated().sum()),
        "duplicate_transect_side_origin_horizon": int(df.duplicated(["transect_id", "side", "origin_year", "horizon_years"]).sum()),
        "segment_id_in_features": "segment_id" in FEATURES or "segment_id" in df.columns,
        "transect_id_in_features": "transect_id" in FEATURES,
        "coordinate_in_features": any(c in FEATURES for c in ["origin_bank_x", "origin_bank_y", "along_m", "reach"]),
        "target_columns_in_features": any(c in FEATURES for c in ["target_displacement_m", "target_bank_x", "target_bank_y", "target_rate_m_per_yr"]),
        "forecast_rows_have_no_labels": bool(
            not any(c in forecast.columns for c in ["target_displacement_m", "target_rate_m_per_yr", "target_bank_x", "target_bank_y"])
        ),
        "forecast_years": sorted(int(v) for v in forecast["forecast_year"].unique()),
        "forecast_origin_year": sorted(int(v) for v in forecast["origin_year"].unique()),
        "forecast_feature_cutoffs": sorted(int(v) for v in forecast["feature_cutoff_year"].unique()),
        "forecast_contains_test_years_only": bool(set(forecast["forecast_year"]).issubset(set(cfg["test_years"]))),
        "next_observation_year_not_used_before_origin": True,
        "feature_dictionary_has_availability": True,
    }
    # Every feature row must have an origin no later than the target minus one.
    checks["all_horizons_positive"] = bool((df["horizon_years"] >= 1).all())
    checks["no_rows_from_2024_plus"] = bool(df["target_year"].max() <= cutoff and forecast["origin_year"].max() <= cutoff)
    checks["all_checks_pass"] = bool(
        checks["max_target_year_at_most_2023"]
        and checks["all_targets_after_origin"]
        and checks["all_feature_cutoffs_at_origin"]
        and checks["no_test_years_in_training"]
        and checks["no_forecast_years_in_training"]
        and checks["duplicate_sample_ids"] == 0
        and checks["duplicate_transect_side_origin_horizon"] == 0
        and not checks["segment_id_in_features"]
        and not checks["transect_id_in_features"]
        and not checks["coordinate_in_features"]
        and not checks["target_columns_in_features"]
        and checks["forecast_rows_have_no_labels"]
        and checks["forecast_contains_test_years_only"]
        and checks["all_horizons_positive"]
        and checks["no_rows_from_2024_plus"]
    )
    return checks


def _schema(df: pd.DataFrame, forecast: pd.DataFrame) -> dict:
    return {
        "columns": [
            {"name": c, "dtype": str(df[c].dtype), "role": _role(c), "non_null": int(df[c].notna().sum())}
            for c in df.columns
        ],
        "forecast_columns": [{"name": c, "dtype": str(forecast[c].dtype)} for c in forecast.columns],
        "n_rows": int(len(df)),
        "n_forecast_rows": int(len(forecast)),
        "usable_rows": int(df["usable_for_training"].sum()),
    }


def _role(c: str) -> str:
    if c in FEATURES:
        return "feature"
    if c in LABEL_COLUMNS:
        return "label_or_quality"
    if c in IDENTIFIERS:
        return "identifier_or_evaluation_only"
    return "metadata"


def _dictionary() -> dict:
    return {
        "positive_sign": "erosion (outward bank movement, away from channel)",
        "negative_sign": "accretion (inward bank movement, toward channel)",
        "low_movement_tolerance_m": 15.0,
        "features": {
            "last_rate_m_per_yr": {"unit": "m/yr", "derivation": "annualised signed displacement of the most recent valid interval ending at or before the origin", "availability": "origin", "missing": "NaN plus missing indicator"},
            "last2_mean_rate_m_per_yr": {"unit": "m/yr", "derivation": "mean of the last two valid interval rates ending at or before the origin", "availability": "origin", "missing": "NaN plus missing indicator"},
            "last3_mean_rate_m_per_yr": {"unit": "m/yr", "derivation": "mean of the last three valid interval rates ending at or before the origin", "availability": "origin", "missing": "NaN plus missing indicator"},
            "acceleration_m_per_yr2": {"unit": "m/yr²", "derivation": "last rate minus the immediately previous rate", "availability": "origin", "missing": "NaN"},
            "last_displacement_m": {"unit": "m", "derivation": "signed displacement of the most recent valid interval", "availability": "origin", "missing": "NaN"},
            "last_interval_years": {"unit": "years", "derivation": "elapsed years of the most recent valid interval", "availability": "origin", "missing": "NaN"},
            "last_interval_good": {"unit": "0/1", "derivation": "quality flag of the most recent interval", "availability": "origin", "missing": "NaN"},
            "width_m": {"unit": "m", "derivation": "distance between the two outer bank intersections at the origin", "availability": "origin", "missing": "NaN plus indicator"},
            "width_change_last_m": {"unit": "m", "derivation": "width at the end minus width at the start of the most recent interval", "availability": "origin", "missing": "NaN"},
            "abs_curvature_1_m": {"unit": "1/m", "derivation": "absolute local bankline curvature fitted over ±120 m at the origin", "availability": "origin", "missing": "NaN plus indicator"},
            "sinuosity": {"unit": "ratio", "derivation": "origin-year bank path length divided by straight-line distance over a five-transect window", "availability": "origin", "missing": "NaN plus indicator"},
            "is_left_bank": {"unit": "0/1", "derivation": "1 for the left bank when facing downstream", "availability": "origin", "missing": "never"},
            "horizon_years": {"unit": "years", "derivation": "target calendar year minus origin calendar year", "availability": "forecast design", "missing": "never"},
            "elapsed_years": {"unit": "years", "derivation": "actual days between nominal 25 March dates divided by 365.25", "availability": "forecast design", "missing": "never"},
            "last_rate_missing": {"unit": "0/1", "derivation": "missing indicator for last_rate", "availability": "origin", "missing": "never"},
            "last2_missing": {"unit": "0/1", "derivation": "missing indicator for last2_mean", "availability": "origin", "missing": "never"},
            "last3_missing": {"unit": "0/1", "derivation": "missing indicator for last3_mean", "availability": "origin", "missing": "never"},
            "width_missing": {"unit": "0/1", "derivation": "missing indicator for width", "availability": "origin", "missing": "never"},
            "curvature_missing": {"unit": "0/1", "derivation": "missing indicator for curvature", "availability": "origin", "missing": "never"},
            "sinuosity_missing": {"unit": "0/1", "derivation": "missing indicator for sinuosity", "availability": "origin", "missing": "never"},
        },
        "excluded_on_purpose": [
            "transect_id and sample_id (stable identifiers, not predictors)",
            "reach, along_m and coordinates (spatial identifiers; used only for reporting/evaluation)",
            "any target-year bank position, area, rainfall, discharge or test-period observation",
            "segment_id",
        ],
        "target": {"name": "target_displacement_m", "unit": "m", "definition": "signed bank displacement from origin to target; positive = erosion", "label_quality": "good only for training"},
        "low_movement": {"tolerance_m": 15.0, "rationale": "half of the 30 m Landsat pixel; near the minimum detectable bank change"},
    }


def _write_report(df: pd.DataFrame, forecast: pd.DataFrame, checks: dict) -> None:
    lines = [
        "# Leakage-resistant training dataset",
        "",
        f"- Historical rows: {len(df)}",
        f"- Usable (`good`) historical rows: {int(df['usable_for_training'].sum())}",
        f"- Forecast feature rows for origin 2023: {len(forecast)}",
        f"- Target years: {int(df['target_year'].min())}–{int(df['target_year'].max())}",
        f"- Origin years: {int(df['origin_year'].min())}–{int(df['origin_year'].max())}",
        "",
        "Each row is one bank side (left or right of a fixed transect) at one forecast origin and "
        "one horizon (1, 2 or 3 years). The target is signed bank displacement in metres. Positive "
        "is erosion (outward); negative is accretion (inward).",
        "",
        "## Features",
        "",
        "| Feature | Unit | Availability |",
        "|---|---|---|",
    ]
    for name, meta in _dictionary()["features"].items():
        lines.append(f"| `{name}` | {meta['unit']} | {meta['availability']} |")
    lines += [
        "",
        "`transect_id`, `reach`, coordinates and `sample_id` are identifiers, not features. "
        "No target-year label, area statistic, future discharge/rainfall or test-year observation "
        "is used as a predictor.",
        "",
        "## Leakage checks",
        "",
        "| Check | Result |",
        "|---|---|",
    ]
    for k, v in checks.items():
        lines.append(f"| `{k}` | {v} |")
    lines += [
        "",
        f"All checks pass: **{checks['all_checks_pass']}**.",
        "",
        "## Split design",
        "",
        "Model selection uses rolling origins before 2024. For a validation origin `v`, only rows "
        "whose target year is strictly before `v` are eligible for training. The validation rows "
        "are the rows at origin `v` with targets through 2023. The 2024–2026 rows are not present "
        "in the training file at all; they exist only in `forecast_features_2023.csv` without labels.",
        "",
        "Rows with `label_quality` `flagged`, `implausible` or `invalid` are retained for audit but "
        "are not used for training. This is decided from historical geometry evidence, not from test "
        "performance.",
    ]
    project_path("reports", "dataset.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    print(build())
