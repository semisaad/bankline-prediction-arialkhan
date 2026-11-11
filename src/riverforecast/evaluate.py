from __future__ import annotations

import datetime as dt
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
from pyproj import Transformer
from shapely.geometry import shape
from shapely.ops import transform as shapely_transform

from .config import ensure_output_dirs, load_config, project_path
from .extract import polygonize, select_river
from .geometry import bank_positions, build_transects
from .io import read_mask, sha256_file, write_json, write_mask
from .models import _metrics


def run() -> dict:
    ensure_output_dirs()
    cfg = load_config()
    manifest = _require_manifest()
    out_dir = project_path("evaluation")
    mask_dir = out_dir / "masks"
    mask_dir.mkdir(parents=True, exist_ok=True)
    features = pd.read_csv(project_path("datasets", "forecast_features_2023.csv"))
    if sha256_file(project_path("datasets", "forecast_features_2023.csv")) != manifest["inputs"]["forecast_features_sha256"]:
        raise RuntimeError("Forecast feature file changed after freeze.")
    core_npz = np.load(project_path("processed", "river", "river_core.npz"))
    core = core_npz["core"]
    transects = build_transects(int(cfg["transects"]["reference_year"]))
    _check_transects(transects)
    origin_pos = pd.read_csv(project_path("derived", "measurements", "bank_positions.csv"))
    origin_pos = origin_pos[origin_pos["year"] == int(cfg["dataset"]["final_origin_year"])].copy()
    test_years = [int(y) for y in cfg["test_years"]]
    audit = []
    observed_frames = []
    for year in test_years:
        water, valid, info = read_mask(year, purpose="evaluation")
        selected, sel_info = select_river(water, valid, core)
        write_mask(mask_dir / f"river_{year}.tif", selected, valid)
        with rasterio.open(mask_dir / f"river_{year}.tif") as src:
            transform = src.transform
            crs = src.crs
        poly, poly_info = polygonize(selected, transform)
        rows = bank_positions(year, transects, poly)
        df = pd.DataFrame(rows)
        df["year"] = year
        df["observation_date"] = f"{year}-03-25"
        df.to_csv(out_dir / f"observed_bank_positions_{year}.csv", index=False)
        observed_frames.append(df)
        audit.append(
            {
                "year": year,
                "source_sha256": info["sha256"],
                "source_size_bytes": Path(info["path"]).stat().st_size,
                "source_width": info["width"],
                "source_height": info["height"],
                "source_crs": info["crs"],
                "source_transform": info["transform"],
                "aligned_to_canonical_grid": info["aligned"],
                "valid_pixels": int(valid.sum()),
                "water_pixels": int(water.sum()),
                "selected_river_pixels": int(selected.sum()),
                "selected_river_area_m2": float(selected.sum() * 900.0),
                "excluded_water_pixels": int((water & valid & ~selected).sum()),
                "selected_component_count": int(sel_info["selected_component_count"]),
                "anchor_fallback_used": bool(sel_info["anchor_fallback_used"]),
                "polygon_valid_raw": bool(poly_info["polygon_valid_raw"]),
                "polygon_repair_applied": bool(poly_info["repair_applied"]),
            }
        )
    write_json(out_dir / "test_data_audit.json", {"manifest": manifest, "years": audit})
    observed = pd.concat(observed_frames, ignore_index=True)
    for year in test_years:
        _write_observed_layers(year, observed, transects)
    predictions = _build_predictions(origin_pos, observed, features, manifest, cfg)
    predictions.to_csv(out_dir / "predictions.csv", index=False)
    metrics = _evaluate(predictions, cfg)
    write_json(out_dir / "metrics.json", _safe(metrics))
    _write_report(metrics, predictions, audit, manifest, cfg)
    for year in test_years:
        _plot_overlay(year, observed, predictions, mask_dir)
    return {"metrics": metrics, "audit": audit}


def _write_observed_layers(year: int, observed: pd.DataFrame, transects) -> None:
    from shapely.geometry import LineString, Point

    from .io import write_geojson

    sub = observed[observed["year"] == year]
    feats = []
    for side, label in [("L", "left"), ("R", "right")]:
        g = sub[(sub["side"] == side) & sub["valid_bank"]].sort_values("transect_id")
        coords = [(float(r["bank_x"]), float(r["bank_y"])) for _, r in g.iterrows()]
        if len(coords) >= 2:
            line = LineString(coords)
            feats.append(
                {
                    "geometry": line,
                    "properties": {
                        "year": year,
                        "side": side,
                        "bank": label,
                        "kind": "observed",
                        "n_points": len(coords),
                        "length_m": round(float(line.length), 2),
                    },
                }
            )
    write_geojson(project_path("evaluation", f"observed_banklines_{year}.geojson"), feats)
    pts = [
        {
            "geometry": Point(float(r["bank_x"]), float(r["bank_y"])),
            "properties": {
                "year": year,
                "transect_id": int(r["transect_id"]),
                "side": r["side"],
                "valid_bank": bool(r["valid_bank"]),
                "flags": r["flags"] if isinstance(r["flags"], str) else "",
            },
        }
        for _, r in sub[sub["valid_bank"]].iterrows()
    ]
    write_geojson(project_path("evaluation", f"observed_bank_points_{year}.geojson"), pts)


def _require_manifest() -> dict:
    from .io import require_freeze_ready

    return require_freeze_ready()


def _check_transects(transects) -> None:
    stored = pd.read_csv(project_path("derived", "transects.csv"))
    if len(stored) != len(transects):
        raise RuntimeError("Derived transect count does not match the fixed 2023 geometry.")
    for t, (_, r) in zip(transects, stored.sort_values("transect_id").iterrows()):
        if int(r["transect_id"]) != t.transect_id:
            raise RuntimeError("Transect IDs changed after freeze.")
        if abs(float(r["center_x"]) - t.center_x) > 1e-6 or abs(float(r["center_y"]) - t.center_y) > 1e-6:
            raise RuntimeError("Fixed transect geometry changed after freeze.")


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


def _good_bank(row, min_width: float) -> bool:
    flags = _parse_flags(row.get("flags"))
    return bool(
        row["valid_bank"]
        and row["center_inside"]
        and not ({"missing_bank", "multiple_crossings", "width_below_min"} & flags)
        and not row["border_transect"]
        and not math.isnan(float(row["width_m"]))
        and float(row["width_m"]) >= min_width
    )


def _build_predictions(origin: pd.DataFrame, observed: pd.DataFrame, features: pd.DataFrame, manifest: dict, cfg: dict) -> pd.DataFrame:
    min_width = float(cfg["transects"]["min_width_m"])
    tol = float(cfg["labels"]["low_movement_tolerance_m"])
    origin = origin.set_index(["transect_id", "side"])
    frames = []
    for year in [int(y) for y in cfg["test_years"]]:
        h = year - int(cfg["dataset"]["final_origin_year"])
        seg = pd.read_csv(project_path("forecasts", "frozen", f"segments_{year}.csv"))
        seg = seg.rename(columns={"abs_displacement_m": "forecast_abs_m"})
        obs = observed[observed["year"] == year].set_index(["transect_id", "side"])
        feat = features[features["horizon_years"] == h].set_index(["transect_id", "side"])
        for key in sorted(set(origin.index) & set(obs.index) & set(seg.set_index(["transect_id", "side"]).index)):
            o = origin.loc[key]
            t = obs.loc[key]
            f = feat.loc[key] if key in feat.index else None
            s = seg.set_index(["transect_id", "side"]).loc[key]
            valid = bool(o["valid_bank"] and t["valid_bank"])
            d_obs = np.nan
            if valid:
                dx = float(t["bank_x"] - o["bank_x"])
                dy = float(t["bank_y"] - o["bank_y"])
                d_obs = (dx * float(o["normal_x"]) + dy * float(o["normal_y"])) * float(o["outward_sign"])
            elapsed = (pd.Timestamp(f"{year}-03-25") - pd.Timestamp(f"{int(cfg['dataset']['final_origin_year'])}-03-25")).days / 365.25
            quality = "good" if _good_bank(o, min_width) and _good_bank(t, min_width) else "flagged"
            if not valid:
                quality = "invalid"
            row = {
                "year": year,
                "origin_year": int(cfg["dataset"]["final_origin_year"]),
                "horizon_years": h,
                "transect_id": key[0],
                "side": key[1],
                "reach": o["reach"],
                "observation_date": f"{year}-03-25",
                "elapsed_years": elapsed,
                "origin_bank_x": o["bank_x"],
                "origin_bank_y": o["bank_y"],
                "normal_x": o["normal_x"],
                "normal_y": o["normal_y"],
                "outward_sign": o["outward_sign"],
                "origin_flags": o["flags"],
                "observed_bank_x": t["bank_x"],
                "observed_bank_y": t["bank_y"],
                "observed_flags": t["flags"],
                "observed_displacement_m": d_obs,
                "observed_rate_m_per_yr": d_obs / elapsed if not np.isnan(d_obs) else np.nan,
                "observed_class": _classify(d_obs, tol),
                "label_quality": quality,
                "model_prediction_m": float(s["predicted_displacement_m"]),
                "model_class": s["forecast_class"],
                "model_quality": s["forecast_quality"],
                "model_ensemble_std_m": float(s["ensemble_std_m"]),
                "last_rate_2023_m_per_yr": float(f["last_rate_m_per_yr"]) if f is not None else np.nan,
                "last3_mean_2023_m_per_yr": float(f["last3_mean_rate_m_per_yr"]) if f is not None else np.nan,
                "last2_mean_2023_m_per_yr": float(f["last2_mean_rate_m_per_yr"]) if f is not None else np.nan,
            }
            row["forecast_bank_x"] = row["origin_bank_x"] + row["normal_x"] * row["outward_sign"] * row["model_prediction_m"]
            row["forecast_bank_y"] = row["origin_bank_y"] + row["normal_y"] * row["outward_sign"] * row["model_prediction_m"]
            row["zero_prediction_m"] = 0.0
            row["persistence_prediction_m"] = _nan_to_zero(row["last_rate_2023_m_per_yr"] * elapsed)
            trend = row["last3_mean_2023_m_per_yr"]
            if np.isnan(trend):
                trend = row["last2_mean_2023_m_per_yr"]
            if np.isnan(trend):
                trend = row["last_rate_2023_m_per_yr"]
            row["trend_prediction_m"] = _nan_to_zero(trend * elapsed)
            frames.append(row)
    out = pd.DataFrame(frames)
    medians = (
        pd.read_csv(project_path("datasets", "bank_migration_dataset.csv"))
        .query("usable_for_training and target_year <= 2023")
        .groupby("horizon_years")["target_displacement_m"]
        .median()
        .to_dict()
    )
    out["median_prediction_m"] = out["horizon_years"].map(medians)
    for c in ["model_prediction_m", "zero_prediction_m", "persistence_prediction_m", "trend_prediction_m", "median_prediction_m"]:
        out[c.replace("_prediction_m", "_error_m")] = out[c] - out["observed_displacement_m"]
        out[c.replace("_prediction_m", "_abs_error_m")] = out[c.replace("_prediction_m", "_error_m")].abs()
    out["model_direction_correct"] = np.sign(out["model_prediction_m"]) == np.sign(out["observed_displacement_m"])
    out["observed_low_movement"] = out["observed_displacement_m"].abs() <= tol
    out["model_low_movement"] = out["model_prediction_m"].abs() <= tol
    return out


def _nan_to_zero(v: float) -> float:
    return 0.0 if v is None or (isinstance(v, float) and math.isnan(v)) else float(v)


def _classify(d: float, tol: float) -> str:
    if d is None or (isinstance(d, float) and math.isnan(d)):
        return "invalid"
    if d > tol:
        return "erosion"
    if d < -tol:
        return "accretion"
    return "low_movement"


def _evaluate(pred: pd.DataFrame, cfg: dict) -> dict:
    tol = float(cfg["labels"]["low_movement_tolerance_m"])
    good = pred[pred["label_quality"] == "good"].copy()
    models = {
        "random_forest": "model_prediction_m",
        "zero": "zero_prediction_m",
        "persistence": "persistence_prediction_m",
        "trend": "trend_prediction_m",
        "median": "median_prediction_m",
    }
    out = {
        "created_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "test_years": [int(y) for y in cfg["test_years"]],
        "origin_year": int(cfg["dataset"]["final_origin_year"]),
        "n_pairs": int(len(pred)),
        "n_good_pairs": int(len(good)),
        "n_flagged_or_invalid": int(len(pred) - len(good)),
        "low_movement_tolerance_m": tol,
        "models": {},
    }
    for name, col in models.items():
        sub = good[good[col].notna()]
        m = _metrics(sub["observed_displacement_m"].to_numpy(), sub[col].to_numpy())
        m["by_horizon"] = {
            str(int(h)): _metrics(g["observed_displacement_m"].to_numpy(), g[col].to_numpy())
            for h, g in sub.groupby("horizon_years")
        }
        m["by_reach"] = {
            str(r): _metrics(g["observed_displacement_m"].to_numpy(), g[col].to_numpy())
            for r, g in sub.groupby("reach")
        }
        m["by_year"] = {
            str(int(y)): _metrics(g["observed_displacement_m"].to_numpy(), g[col].to_numpy())
            for y, g in sub.groupby("year")
        }
        m["confusion"] = _confusion(sub, col, tol)
        out["models"][name] = m
    out["event_audit"] = _event_audit(good, tol)
    out["largest_errors"] = (
        good.assign(abs_error=good["model_error_m"].abs())
        .sort_values("abs_error", ascending=False)
        .head(20)[
            [
                "year",
                "transect_id",
                "side",
                "reach",
                "observed_displacement_m",
                "model_prediction_m",
                "model_error_m",
                "observed_flags",
            ]
        ]
        .to_dict(orient="records")
    )
    return out


def _confusion(sub: pd.DataFrame, col: str, tol: float) -> dict:
    rows = {}
    for obs_class, g in sub.groupby("observed_class"):
        pred_class = np.where(g[col] > tol, "erosion", np.where(g[col] < -tol, "accretion", "low_movement"))
        rows[str(obs_class)] = {str(k): int(v) for k, v in pd.Series(pred_class).value_counts().items()}
    return rows


def _event_audit(good: pd.DataFrame, tol: float) -> dict:
    out = {}
    for cls in ["erosion", "accretion", "low_movement"]:
        g = good[good["observed_class"] == cls]
        if g.empty:
            out[cls] = {"n": 0}
            continue
        out[cls] = {
            "n": int(len(g)),
            "captured": int((g["model_class"] == cls).sum()),
            "capture_rate": float((g["model_class"] == cls).mean()),
            "predicted_low": int((g["model_class"] == "low_movement").sum()),
            "opposite_direction": int((g["model_class"] == ("accretion" if cls == "erosion" else "erosion")).sum()),
            "mean_observed_m": float(g["observed_displacement_m"].mean()),
            "mean_predicted_m": float(g["model_prediction_m"].mean()),
            "mae_m": float(g["model_abs_error_m"].mean()),
        }
    return out


def _safe(obj):
    if isinstance(obj, dict):
        return {str(k): _safe(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_safe(v) for v in obj]
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        v = float(obj)
        return None if math.isnan(v) or math.isinf(v) else v
    if isinstance(obj, float):
        return None if math.isnan(obj) or math.isinf(obj) else obj
    return obj


def _write_report(metrics: dict, pred: pd.DataFrame, audit: list[dict], manifest: dict, cfg: dict) -> None:
    lines = [
        "# Post-freeze evaluation, 2024–2026",
        "",
        "This is the only report that reads 2024–2026 pixel data. It was produced after the forecast "
        "manifest was frozen and hash-verified. No model, feature, threshold or transect was changed "
        "after seeing these observations.",
        "",
        "## Test data audit",
        "",
        "| Year | Valid px | Water px | Selected river px | Area (km²) | Aligned | Components | Fallback |",
        "|---|---:|---:|---:|---:|---|---:|---|",
    ]
    for a in audit:
        lines.append(
            f"| {a['year']} | {a['valid_pixels']} | {a['water_pixels']} | {a['selected_river_pixels']} | "
            f"{a['selected_river_area_m2']/1e6:.3f} | {a['aligned_to_canonical_grid']} | "
            f"{a['selected_component_count']} | {a['anchor_fallback_used']} |"
        )
    lines += [
        "",
        "Test polygons were built from the test masks using the frozen historical core and the same "
        "selection rule. The fixed 2023 transects were re-verified against `derived/transects.csv`.",
        "",
        "## Forecast vs observed",
        "",
        "Only pairs where both the 2023 origin bank and test-year bank pass the geometry quality "
        "rules are scored. Positive is erosion (outward); negative is accretion (inward).",
        "",
        "| Model | n | MAE (m) | RMSE (m) | Bias (m) | Within ±15 m | Low-movement F1 | Directional accuracy (>15 m) | False movement | Missed movement |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    labels = {
        "random_forest": "Frozen random forest",
        "zero": "Zero change",
        "persistence": "Persistence",
        "trend": "Historic trend",
        "median": "Historical median",
    }
    for name, m in metrics["models"].items():
        lines.append(
            f"| {labels.get(name, name)} | {m['n']} | {_f(m['mae_m'])} | {_f(m['rmse_m'])} | "
            f"{_f(m['bias_m'])} | {_f(m['within_15m'], 3)} | {_f(m['low_movement_f1'], 3)} | "
            f"{_f(m['directional_accuracy_moving'], 3)} | {_f(m['false_movement_rate'], 3)} | "
            f"{_f(m['missed_movement_rate'], 3)} |"
        )
    rf = metrics["models"]["random_forest"]
    lines += [
        "",
        "## Frozen model by horizon",
        "",
        "| Horizon | n | MAE (m) | RMSE (m) | Bias (m) | Low-movement F1 | Directional accuracy |",
        "|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for h, m in rf["by_horizon"].items():
        lines.append(
            f"| {h} | {m['n']} | {_f(m['mae_m'])} | {_f(m['rmse_m'])} | {_f(m['bias_m'])} | "
            f"{_f(m['low_movement_f1'], 3)} | {_f(m['directional_accuracy_moving'], 3)} |"
        )
    lines += [
        "",
        "## Frozen model by reach",
        "",
        "| Reach | n | MAE (m) | RMSE (m) | Bias (m) | Directional accuracy |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for r, m in rf["by_reach"].items():
        lines.append(
            f"| {r} | {m['n']} | {_f(m['mae_m'])} | {_f(m['rmse_m'])} | {_f(m['bias_m'])} | "
            f"{_f(m['directional_accuracy_moving'], 3)} |"
        )
    lines += [
        "",
        "## Confusion matrix, frozen model",
        "",
        "Rows are observed classes; columns are predicted classes.",
        "",
        "| Observed \\ predicted | Erosion | Accretion | Low movement |",
        "|---|---:|---:|---:|",
    ]
    conf = rf["confusion"]
    for cls in ["erosion", "accretion", "low_movement"]:
        row = conf.get(cls, {})
        lines.append(
            f"| {cls} | {row.get('erosion', 0)} | {row.get('accretion', 0)} | {row.get('low_movement', 0)} |"
        )
    lines += [
        "",
        "## Event audit",
        "",
        "| Observed class | n | Captured | Capture rate | Predicted low | Opposite direction | Mean observed (m) | Mean predicted (m) | MAE (m) |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for cls, e in metrics["event_audit"].items():
        lines.append(
            f"| {cls} | {e.get('n', 0)} | {e.get('captured', 0)} | {_f(e.get('capture_rate'), 3)} | "
            f"{e.get('predicted_low', 0)} | {e.get('opposite_direction', 0)} | "
            f"{_f(e.get('mean_observed_m'))} | {_f(e.get('mean_predicted_m'))} | {_f(e.get('mae_m'))} |"
        )
    lines += [
        "",
        "## Largest frozen-model errors",
        "",
        "| Year | Transect | Side | Reach | Observed (m) | Predicted (m) | Error (m) |",
        "|---:|---:|---|---|---:|---:|---:|",
    ]
    for r in metrics["largest_errors"]:
        lines.append(
            f"| {r['year']} | {r['transect_id']} | {r['side']} | {r['reach']} | "
            f"{_f(r['observed_displacement_m'])} | {_f(r['model_prediction_m'])} | {_f(r['model_error_m'])} |"
        )
    lines += [
        "",
        "## Interpretation",
        "",
        "The frozen forecast is a bank-displacement forecast at fixed transects, not a forecast of "
        "every pixel. The test masks are classified water observations at the same nominal late-March "
        "season; water level, cloud and classification error remain part of the observed signal.",
        "",
        "The baselines are shown because they expose the zero-inflated nature of the labels: a large "
        "share of observed bank displacements are exactly zero at 30 m resolution. A model can have "
        "a low MAE while capturing very few moving segments; the event audit and confusion matrix are "
        "therefore reported alongside MAE.",
        "",
        "No retuning was performed after this evaluation. The frozen files and hashes in "
        "`forecasts/frozen/manifest.json` remain authoritative.",
    ]
    project_path("reports", "evaluation.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _f(v, nd=2) -> str:
    if v is None:
        return "—"
    try:
        if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
            return "—"
        return f"{float(v):.{nd}f}"
    except Exception:  # noqa: BLE001
        return "—"


def _plot_overlay(year: int, observed: pd.DataFrame, predictions: pd.DataFrame, mask_dir: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig_dir = project_path("evaluation", "figures")
    fig_dir.mkdir(parents=True, exist_ok=True)
    with rasterio.open(mask_dir / f"river_{year}.tif") as src:
        arr = src.read(1) == 255
        extent = (src.bounds.left, src.bounds.right, src.bounds.bottom, src.bounds.top)
    obs = observed[observed["year"] == year]
    pred = predictions[predictions["year"] == year]
    fig, ax = plt.subplots(figsize=(7.2, 9.4))
    ax.imshow(arr, cmap="Blues", alpha=0.25, extent=extent, origin="upper")
    for side, color in [("L", "tab:blue"), ("R", "tab:green")]:
        sub = pred[pred["side"] == side].sort_values("transect_id")
        ax.plot(sub["observed_bank_x"], sub["observed_bank_y"], "-", color="0.65", lw=0.8, label="2023 origin" if side == "L" else None)
        ax.plot(sub["forecast_bank_x"], sub["forecast_bank_y"], "-", color=color, lw=1.4, label=f"forecast {side}" if side == "L" else None)
        ot = obs[(obs["side"] == side) & obs["valid_bank"]].sort_values("transect_id")
        ax.plot(ot["bank_x"], ot["bank_y"], "-", color="darkorange", lw=1.3, label=f"observed {side}" if side == "L" else None)
    movers = pred[pred["label_quality"] == "good"]
    ax.quiver(
        movers["observed_bank_x"],
        movers["observed_bank_y"],
        movers["normal_x"] * movers["outward_sign"] * movers["model_prediction_m"] * 3.0,
        movers["normal_y"] * movers["outward_sign"] * movers["model_prediction_m"] * 3.0,
        angles="xy",
        scale_units="xy",
        scale=1,
        color="crimson",
        width=0.002,
        alpha=0.75,
        label="forecast displacement ×3",
    )
    ax.set_title(f"{year}: frozen forecast vs observed banks")
    ax.set_xlabel("Easting (m)")
    ax.set_ylabel("Northing (m)")
    ax.set_aspect("equal")
    ax.legend(loc="lower left", fontsize=7)
    fig.tight_layout()
    fig.savefig(fig_dir / f"overlay_{year}.png", dpi=150)
    plt.close(fig)


if __name__ == "__main__":
    print(json.dumps(_safe(run()["metrics"]), indent=2))
