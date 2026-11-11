from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import shutil
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from shapely.geometry import LineString, Point, Polygon

from .config import ensure_output_dirs, load_config, project_path
from .io import sha256_file, write_geojson, write_json

MODEL = "random_forest"


def _predict(artifact: dict, frame: pd.DataFrame) -> dict:
    pipeline = artifact["pipeline"]
    if artifact.get("kind") == "random_forest":
        model = pipeline.named_steps["model"]
        imputer = pipeline.named_steps["imputer"]
        X = imputer.transform(frame[artifact["features"]])
        preds = np.vstack([tree.predict(X) for tree in model.estimators_])
        return {
            "mean": preds.mean(axis=0),
            "std": preds.std(axis=0),
            "p10": np.quantile(preds, 0.10, axis=0),
            "p90": np.quantile(preds, 0.90, axis=0),
        }
    mean = pipeline.predict(frame[artifact["features"]])
    return {"mean": mean, "std": np.full(len(frame), np.nan), "p10": np.full(len(frame), np.nan), "p90": np.full(len(frame), np.nan)}


def _classify(d: float, tolerance: float) -> tuple[str, str]:
    if d > tolerance:
        return "erosion", "outward"
    if d < -tolerance:
        return "accretion", "inward"
    return "low_movement", "within_tolerance"


def generate() -> dict:
    ensure_output_dirs()
    cfg = load_config()
    staging = project_path("forecasts", "staging")
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    meta = json.load(open(project_path("models", "model_metadata.json"), encoding="utf-8"))
    artifacts = joblib.load(project_path("models", "final_models.joblib"))
    features = pd.read_csv(project_path("datasets", "forecast_features_2023.csv"))
    pos = pd.read_csv(project_path("derived", "measurements", "bank_positions.csv"))
    origin = int(cfg["dataset"]["final_origin_year"])
    origin_info = pos[pos["year"] == origin][["transect_id", "side", "flags", "center_inside", "border_transect", "valid_bank"]].copy()
    origin_info = origin_info.rename(
        columns={
            "flags": "origin_flags",
            "center_inside": "origin_center_inside",
            "border_transect": "origin_border_transect",
            "valid_bank": "origin_valid_bank",
        }
    )
    features = features.merge(origin_info, on=["transect_id", "side"], how="left")
    features["origin_flags"] = features["origin_flags"].fillna("").astype(str).str.strip()
    features.loc[features["origin_flags"].isin(["[]", "nan", "None"]), "origin_flags"] = ""
    tolerance = float(cfg["labels"]["low_movement_tolerance_m"])
    implausible = float(cfg["labels"]["max_plausible_abs_displacement_m"])
    years = [int(y) for y in cfg["test_years"]]
    segments_by_year = {}
    summary_by_year = {}
    all_features = []
    for h in cfg["dataset"]["horizons"]:
        frame = features[features["horizon_years"] == h].copy()
        pred = _predict(artifacts[int(h)], frame)
        frame["predicted_displacement_m"] = pred["mean"]
        frame["ensemble_std_m"] = pred["std"]
        frame["predicted_p10_m"] = pred["p10"]
        frame["predicted_p90_m"] = pred["p90"]
        frame["predicted_rate_m_per_yr"] = frame["predicted_displacement_m"] / frame["elapsed_years"]
        frame["direction"] = np.where(frame["predicted_displacement_m"] > tolerance, "outward", np.where(frame["predicted_displacement_m"] < -tolerance, "inward", "within_tolerance"))
        frame["forecast_class"] = np.select(
            [frame["predicted_displacement_m"] > tolerance, frame["predicted_displacement_m"] < -tolerance],
            ["erosion", "accretion"],
            default="low_movement",
        )
        frame["forecast_bank_x"] = frame["origin_bank_x"] + frame["normal_x"] * frame["outward_sign"] * frame["predicted_displacement_m"]
        frame["forecast_bank_y"] = frame["origin_bank_y"] + frame["normal_y"] * frame["outward_sign"] * frame["predicted_displacement_m"]
        frame["abs_displacement_m"] = frame["predicted_displacement_m"].abs()
        frame["forecast_quality"] = np.select(
            [
                frame["predicted_displacement_m"].abs() > implausible,
                frame["origin_flags"].fillna("").astype(str) != "",
            ],
            ["implausible", "flagged_origin"],
            default="forecast",
        )
        frame["forecast_year"] = int(origin + h)
        year = int(origin + h)
        if year not in years:
            raise RuntimeError(f"Forecast year {year} is not a test year.")
        all_features.append(frame)
        segments = []
        for _, r in frame.sort_values(["transect_id", "side"]).iterrows():
            if pd.isna(r["origin_bank_x"]) or pd.isna(r["forecast_bank_x"]):
                continue
            origin_pt = Point(float(r["origin_bank_x"]), float(r["origin_bank_y"]))
            forecast_pt = Point(float(r["forecast_bank_x"]), float(r["forecast_bank_y"]))
            segments.append(
                {
                    "geometry": LineString([origin_pt, forecast_pt]),
                    "properties": {
                        "year": year,
                        "origin_year": origin,
                        "horizon_years": int(h),
                        "transect_id": int(r["transect_id"]),
                        "side": r["side"],
                        "reach": r["reach"],
                        "predicted_displacement_m": round(float(r["predicted_displacement_m"]), 3),
                        "predicted_rate_m_per_yr": round(float(r["predicted_rate_m_per_yr"]), 3),
                        "ensemble_std_m": round(float(r["ensemble_std_m"]), 3),
                        "p10_m": round(float(r["predicted_p10_m"]), 3),
                        "p90_m": round(float(r["predicted_p90_m"]), 3),
                        "abs_displacement_m": round(abs(float(r["predicted_displacement_m"])), 3),
                        "direction": r["direction"],
                        "forecast_class": r["forecast_class"],
                        "forecast_quality": r["forecast_quality"],
                        "origin_flags": r["origin_flags"] if isinstance(r["origin_flags"], str) else "",
                        "model": meta["selected_model"],
                        "low_movement_tolerance_m": tolerance,
                        "implausible_threshold_m": implausible,
                    },
                }
            )
        segments_by_year[year] = segments
        write_geojson(staging / f"segments_{year}.geojson", segments)
        csv_cols = [
            "year",
            "origin_year",
            "horizon_years",
            "transect_id",
            "side",
            "reach",
            "predicted_displacement_m",
            "predicted_rate_m_per_yr",
            "ensemble_std_m",
            "predicted_p10_m",
            "predicted_p90_m",
            "abs_displacement_m",
            "forecast_class",
            "direction",
            "forecast_quality",
            "origin_flags",
        ]
        frame.assign(year=year)[csv_cols].to_csv(staging / f"segments_{year}.csv", index=False)
        banklines = _banklines(frame, year, origin, meta["selected_model"])
        write_geojson(staging / f"banklines_{year}.geojson", banklines["features"])
        points = _bank_points(frame, year)
        write_geojson(staging / f"bank_points_{year}.geojson", points)
        summary = _year_summary(frame, year, origin, tolerance, implausible)
        summary["banklines"] = banklines["summary"]
        summary["files"] = {
            "segments_geojson": f"segments_{year}.geojson",
            "segments_csv": f"segments_{year}.csv",
            "banklines_geojson": f"banklines_{year}.geojson",
            "bank_points_geojson": f"bank_points_{year}.geojson",
        }
        summary_by_year[str(year)] = summary
    observed = _banklines(features[features["horizon_years"] == 1].copy(), origin, origin, "observed")
    write_geojson(staging / "observed_banklines_2023.geojson", observed["features"])
    summary = {
        "status": "staging",
        "created_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "origin_year": origin,
        "forecast_years": years,
        "training_cutoff_year": int(cfg["training_cutoff_year"]),
        "model": meta["selected_model"],
        "model_label": meta["selected_label"],
        "features": meta["features"],
        "low_movement_tolerance_m": tolerance,
        "implausible_threshold_m": implausible,
        "n_transects": int(features["transect_id"].nunique()),
        "n_segments_per_year": int(len(features) / len(cfg["dataset"]["horizons"])),
        "by_year": summary_by_year,
        "observed_banklines": "observed_banklines_2023.geojson",
        "note": (
            "Forecasts are conditional on the observed 2023 bank positions and fixed 2023 "
            "transects. They are not a full hydrodynamic or sediment-transport simulation. "
            "Positive displacement is outward bank movement (erosion); negative is inward "
            "(accretion). Low movement is within the 15 m tolerance, half a 30 m pixel."
        ),
    }
    write_json(staging / "forecast_summary.json", summary)
    write_json(staging / "model_metadata_used.json", meta)
    _write_report(summary)
    return summary


def _banklines(frame: pd.DataFrame, year: int, origin: int, model: str) -> dict:
    out = []
    info = {}
    for side, label in [("L", "left"), ("R", "right")]:
        sub = frame[frame["side"] == side].sort_values("transect_id")
        coords = []
        xcol = "forecast_bank_x" if "forecast_bank_x" in sub.columns else "origin_bank_x"
        ycol = "forecast_bank_y" if "forecast_bank_y" in sub.columns else "origin_bank_y"
        for _, r in sub.iterrows():
            if pd.isna(r[xcol]) or pd.isna(r[ycol]):
                continue
            coords.append((float(r[xcol]), float(r[ycol])))
        if len(coords) < 2:
            continue
        line = LineString(coords)
        info[label] = {
            "n_points": len(coords),
            "length_m": round(float(line.length), 2),
            "is_simple": bool(line.is_simple),
        }
        out.append(
            {
                "geometry": line,
                "properties": {
                    "year": year,
                    "origin_year": origin,
                    "side": side,
                    "bank": label,
                    "n_points": len(coords),
                    "length_m": round(float(line.length), 2),
                    "is_simple": bool(line.is_simple),
                    "model": model,
                    "kind": "observed" if year == origin else "forecast",
                },
            }
        )
    if len(out) == 2:
        left = out[0]["geometry"]
        right = out[1]["geometry"]
        shell = list(left.coords) + list(reversed(right.coords))
        if len(shell) >= 4:
            corridor = Polygon(shell)
            raw_valid = bool(corridor.is_valid)
            if not corridor.is_valid:
                corridor = corridor.buffer(0)
            if corridor.is_valid and not corridor.is_empty:
                out.append(
                    {
                        "geometry": corridor,
                        "properties": {
                            "year": year,
                            "origin_year": origin,
                            "kind": "corridor",
                            "raw_valid": raw_valid,
                            "repair_applied": not raw_valid,
                            "area_m2": round(float(corridor.area), 2),
                            "model": model,
                        },
                    }
                )
                info["corridor"] = {
                    "raw_valid": raw_valid,
                    "repair_applied": not raw_valid,
                    "area_m2": round(float(corridor.area), 2),
                }
    return {"features": out, "summary": info}


def _bank_points(frame: pd.DataFrame, year: int) -> list[dict]:
    out = []
    for _, r in frame.sort_values(["transect_id", "side"]).iterrows():
        if pd.isna(r["forecast_bank_x"]) or pd.isna(r["forecast_bank_y"]):
            continue
        out.append(
            {
                "geometry": Point(float(r["forecast_bank_x"]), float(r["forecast_bank_y"])),
                "properties": {
                    "year": year,
                    "transect_id": int(r["transect_id"]),
                    "side": r["side"],
                    "predicted_displacement_m": round(float(r["predicted_displacement_m"]), 3),
                    "forecast_class": r["forecast_class"],
                    "forecast_quality": r["forecast_quality"],
                    "origin_flags": r["origin_flags"] if isinstance(r["origin_flags"], str) else "",
                },
            }
        )
    return out


def _year_summary(frame: pd.DataFrame, year: int, origin: int, tolerance: float, implausible: float) -> dict:
    d = frame["predicted_displacement_m"]
    counts = frame["forecast_class"].value_counts().to_dict()
    return {
        "year": year,
        "origin_year": origin,
        "horizon_years": int(year - origin),
        "n": int(len(frame)),
        "counts": {k: int(counts.get(k, 0)) for k in ["erosion", "accretion", "low_movement"]},
        "quality_counts": {str(k): int(v) for k, v in frame["forecast_quality"].value_counts().items()},
        "mean_m": round(float(d.mean()), 3),
        "median_m": round(float(d.median()), 3),
        "min_m": round(float(d.min()), 3),
        "max_m": round(float(d.max()), 3),
        "mean_abs_m": round(float(d.abs().mean()), 3),
        "mean_ensemble_std_m": round(float(frame["ensemble_std_m"].mean()), 3),
        "low_movement_tolerance_m": tolerance,
        "implausible_threshold_m": implausible,
        "by_reach": {
            str(reach): {
                "n": int(len(g)),
                "mean_m": round(float(g["predicted_displacement_m"].mean()), 3),
                "erosion": int((g["forecast_class"] == "erosion").sum()),
                "accretion": int((g["forecast_class"] == "accretion").sum()),
                "low_movement": int((g["forecast_class"] == "low_movement").sum()),
            }
            for reach, g in frame.groupby("reach")
        },
    }


def freeze() -> dict:
    frozen = project_path("forecasts", "frozen")
    staging = project_path("forecasts", "staging")
    if frozen.exists() and any(frozen.iterdir()):
        raise RuntimeError("forecasts/frozen is not empty; refusing to overwrite a frozen forecast.")
    if not staging.exists():
        raise RuntimeError("No staging forecast; run generate first.")
    summary = json.load(open(staging / "forecast_summary.json", encoding="utf-8"))
    if summary.get("status") != "staging":
        raise RuntimeError("Staging summary is not in staging state.")
    frozen.mkdir(parents=True, exist_ok=True)
    files = []
    frozen_summary = dict(summary)
    frozen_summary["status"] = "frozen"
    frozen_summary["frozen_utc"] = dt.datetime.now(dt.timezone.utc).isoformat()
    for src in sorted(staging.iterdir()):
        if not src.is_file():
            continue
        dst = frozen / src.name
        if src.name == "forecast_summary.json":
            write_json(dst, frozen_summary)
        else:
            shutil.copy2(src, dst)
        files.append({"name": src.name, "sha256": sha256_file(dst), "size": dst.stat().st_size})
    manifest = {
        "frozen": True,
        "frozen_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "origin_year": int(summary["origin_year"]),
        "forecast_years": [int(y) for y in summary["forecast_years"]],
        "training_cutoff_year": int(summary["training_cutoff_year"]),
        "model": summary["model"],
        "model_label": summary["model_label"],
        "features": summary["features"],
        "n_segments_per_year": int(summary["n_segments_per_year"]),
        "files": files,
        "inputs": {
            "config_sha256": sha256_file(project_path("config", "pipeline.json")),
            "dataset_sha256": sha256_file(project_path("datasets", "bank_migration_dataset.csv")),
            "forecast_features_sha256": sha256_file(project_path("datasets", "forecast_features_2023.csv")),
            "model_artifact_sha256": sha256_file(project_path("models", "final_models.joblib")),
            "model_metadata_sha256": sha256_file(project_path("models", "model_metadata.json")),
            "code": {
                "forecast.py": sha256_file(project_path("src", "riverforecast", "forecast.py")),
                "models.py": sha256_file(project_path("src", "riverforecast", "models.py")),
                "dataset.py": sha256_file(project_path("src", "riverforecast", "dataset.py")),
            },
        },
        "note": summary["note"],
    }
    write_json(frozen / "manifest.json", manifest)
    ready_hash = sha256_file(frozen / "manifest.json")
    (frozen / "READY").write_text(ready_hash + "\n", encoding="utf-8")
    for item in manifest["files"]:
        if sha256_file(frozen / item["name"]) != item["sha256"]:
            raise RuntimeError(f"Frozen file hash mismatch: {item['name']}")
    _write_freeze_report(manifest)
    return manifest


def _write_report(summary: dict) -> None:
    lines = [
        "# Forecast, 2024–2026",
        "",
        f"- Frozen origin: 2023",
        f"- Forecast years: {', '.join(str(y) for y in summary['forecast_years'])}",
        f"- Model: {summary['model_label']}",
        f"- Training cutoff: {summary['training_cutoff_year']}",
        f"- Transects: {summary['n_transects']} ({summary['n_segments_per_year']} bank segments per year)",
        f"- Low-movement tolerance: ±{summary['low_movement_tolerance_m']} m",
        f"- Implausible threshold: ±{summary['implausible_threshold_m']} m",
        "",
        "Positive displacement is outward bank movement (erosion); negative is inward (accretion). "
        "Forecasts are conditional on the observed 2023 banks and fixed transects, not a full "
        "hydrodynamic or sediment simulation.",
        "",
        "| Year | Erosion | Accretion | Low movement | Mean (m) | Median (m) | Mean |d| (m) |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for y, s in summary["by_year"].items():
        c = s["counts"]
        lines.append(
            f"| {y} | {c['erosion']} | {c['accretion']} | {c['low_movement']} | "
            f"{s['mean_m']:+.2f} | {s['median_m']:+.2f} | {s['mean_abs_m']:.2f} |"
        )
    lines += [
        "",
        "## By reach",
        "",
        "| Year | Reach | n | Mean (m) | Erosion | Accretion | Low movement |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for y, s in summary["by_year"].items():
        for reach, r in s["by_reach"].items():
            lines.append(
                f"| {y} | {reach} | {r['n']} | {r['mean_m']:+.2f} | {r['erosion']} | "
                f"{r['accretion']} | {r['low_movement']} |"
            )
    lines += [
        "",
        "Random-forest uncertainty is the spread of individual tree predictions; `p10` and `p90` "
        "are descriptive, not calibrated confidence intervals.",
        "",
        "The forecast is not frozen yet. `forecasts/staging/` can be regenerated; "
        "`forecasts/frozen/` is created once, by an explicit freeze step.",
    ]
    project_path("reports", "forecast.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_freeze_report(manifest: dict) -> None:
    lines = [
        "# Forecast freeze manifest",
        "",
        f"- Frozen UTC: {manifest['frozen_utc']}",
        f"- Origin year: {manifest['origin_year']}",
        f"- Forecast years: {', '.join(str(y) for y in manifest['forecast_years'])}",
        f"- Model: {manifest['model_label']}",
        f"- Training cutoff: {manifest['training_cutoff_year']}",
        f"- Segments per year: {manifest['n_segments_per_year']}",
        "",
        "## Frozen files",
        "",
        "| File | SHA256 | Size (bytes) |",
        "|---|---|---:|",
    ]
    for f in manifest["files"]:
        lines.append(f"| `{f['name']}` | `{f['sha256']}` | {f['size']} |")
    lines += [
        "",
        "## Input hashes",
        "",
        "| Input | SHA256 |",
        "|---|---|",
    ]
    for k, v in manifest["inputs"].items():
        if isinstance(v, dict):
            for kk, vv in v.items():
                lines.append(f"| `{k}/{kk}` | `{vv}` |")
        else:
            lines.append(f"| `{k}` | `{v}` |")
    lines += [
        "",
        "`READY` contains the SHA256 of `manifest.json`. Evaluation must verify both the manifest "
        "and every frozen file before opening a 2024–2026 raster.",
    ]
    project_path("reports", "forecast_freeze.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--freeze", action="store_true")
    args = parser.parse_args()
    result = generate()
    print(json.dumps({k: result[k] for k in ["status", "origin_year", "forecast_years", "model", "n_segments_per_year"]}, indent=2))
    if args.freeze:
        print(json.dumps(freeze(), indent=2))
