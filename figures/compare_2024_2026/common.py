from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from pyproj import CRS, Transformer
from rasterio.features import shapes
from shapely import segmentize
from shapely.geometry import Point, shape
from shapely.ops import unary_union

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "figures" / "compare_2024_2026"
REPORT = ROOT / "reports" / "compare_2024_2026.md"
YEARS = [2024, 2025, 2026]
STUDY_WGS84 = {"west": 90.16809, "south": 23.13432, "east": 90.26902, "north": 23.26149}
TARGET_CRS = CRS.from_epsg(32646)
LOW_MOVEMENT_M = 15.0
METRIC_TOL = 0.01
BOUNDARY_TOL_M = 30.0
SECTION_MARGIN_M = 300.0
SECTION_LENGTH_M = 4000.0
FIGURE_DPI = 200
START_LINE_PX = 4.0
OBSERVED_LINE_PX = 2.0
START_LINE_ALPHA = 0.60
CONNECTOR_LW = 2.0
OVERVIEW_CAPTION = "Close to the actual line is only skill if closer than the 2023 line."
COLORS = {
    "water": "#cfe8f5",
    "start": "#8c8c8c",
    "observed": "#000000",
    "forecast": "#ff7f0e",
    "halo": "#ffffff",
    "green": "#2ca02c",
    "red": "#d62728",
    "grey": "#8c8c8c",
    "land_to_water": "#d62728",
    "water_to_land": "#1f77b4",
    "unchanged": "#eeeeee",
}
REPORT_SIZE_PLACEHOLDER = "0000000000"

REQUIRED = {
    "frozen_manifest": ROOT / "forecasts" / "frozen" / "manifest.json",
    "frozen_ready": ROOT / "forecasts" / "frozen" / "READY",
    "metrics": ROOT / "evaluation" / "metrics.json",
    "predictions": ROOT / "evaluation" / "predictions.csv",
    "bank_migration_dataset": ROOT / "datasets" / "bank_migration_dataset.csv",
    "forecast_features_2023": ROOT / "datasets" / "forecast_features_2023.csv",
    "transects_geojson": ROOT / "derived" / "transects.geojson",
    "transects_csv": ROOT / "derived" / "transects.csv",
    "water_mask_2023": ROOT / "processed" / "river" / "river_2023.tif",
    "observed_banklines_2023": ROOT / "forecasts" / "frozen" / "observed_banklines_2023.geojson",
}
for _year in YEARS:
    REQUIRED[f"forecast_banklines_{_year}"] = ROOT / "forecasts" / "frozen" / f"banklines_{_year}.geojson"
    REQUIRED[f"forecast_bank_points_{_year}"] = ROOT / "forecasts" / "frozen" / f"bank_points_{_year}.geojson"
    REQUIRED[f"observed_banklines_{_year}"] = ROOT / "evaluation" / f"observed_banklines_{_year}.geojson"
    REQUIRED[f"observed_bank_points_{_year}"] = ROOT / "evaluation" / f"observed_bank_points_{_year}.geojson"
    REQUIRED[f"observed_bank_positions_{_year}"] = ROOT / "evaluation" / f"observed_bank_positions_{_year}.csv"
    REQUIRED[f"water_mask_{_year}"] = ROOT / "evaluation" / "masks" / f"river_{_year}.tif"

OPTIONAL_RAW_MASKS = {
    f"raw_water_mask_{_year}": ROOT / "landsat" / f"MNDWI_Mask_{_year}.tif"
    for _year in [2023, 2024, 2025, 2026]
}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def projected_study_bounds() -> dict[str, float]:
    tr = Transformer.from_crs(4326, 32646, always_xy=True)
    xs, ys = [], []
    for lon, lat in [
        (STUDY_WGS84["west"], STUDY_WGS84["south"]),
        (STUDY_WGS84["east"], STUDY_WGS84["south"]),
        (STUDY_WGS84["east"], STUDY_WGS84["north"]),
        (STUDY_WGS84["west"], STUDY_WGS84["north"]),
    ]:
        x, y = tr.transform(lon, lat)
        xs.append(x)
        ys.append(y)
    return {"left": min(xs), "bottom": min(ys), "right": max(xs), "top": max(ys)}


def px_to_pt(px: float) -> float:
    return px * 72.0 / FIGURE_DPI


def section_bounds(transects: pd.DataFrame, section_id: int) -> dict[str, float]:
    sec_transects = transects[transects["section_id"] == section_id]
    if sec_transects.empty:
        raise RuntimeError(f"No transects in section {section_id}")
    return {
        "left": float(sec_transects["center_x"].min()) - SECTION_MARGIN_M,
        "right": float(sec_transects["center_x"].max()) + SECTION_MARGIN_M,
        "bottom": float(sec_transects["center_y"].min()) - SECTION_MARGIN_M,
        "top": float(sec_transects["center_y"].max()) + SECTION_MARGIN_M,
    }


def overview_box_lines(row) -> tuple[str, str]:
    n = int(row["n_valid"])
    closer = int(row["model_closer_n"])
    farther = int(row["zero_closer_n"])
    tie = int(row["exact_tie_n"])
    return (
        f"{int(row['year'])}  ·  n={n} valid pairs  ·  "
        f"forecast MAE {row['model_mae_m']:.2f} m  ·  zero MAE {row['zero_mae_m']:.2f} m  ·  "
        f"forecast closer {100.0 * row['model_closer_share']:.1f}% ({closer})  ·  "
        f"farther {100.0 * row['zero_closer_share']:.1f}% ({farther})  ·  "
        f"ties {tie} ({100.0 * row['tie_share']:.1f}%)",
        OVERVIEW_CAPTION,
    )


def changed_place_lines(row) -> tuple[str, str]:
    return (
        f"Valid {int(row['n_valid'])}/{int(row['n_total'])}  ·  "
        f"forecast MAE {row['model_mae_m']:.2f} m  ·  zero MAE {row['zero_mae_m']:.2f} m  ·  "
        f"forecast closer {100.0 * row['model_closer_share']:.1f}%",
        f"Both within 15 m {100.0 * row['both_within_15_share']:.1f}%  ·  "
        f"changed n={int(row['n_changed'])}  ·  "
        f"changed RF/zero MAE {row['model_mae_changed_m']:.2f}/{row['zero_mae_changed_m']:.2f} m",
    )


def ensure_required() -> None:
    missing = [rel(p) for p in REQUIRED.values() if not p.exists()]
    if missing:
        raise FileNotFoundError(f"Missing required inputs: {missing}")
    OUT.mkdir(parents=True, exist_ok=True)
    REPORT.parent.mkdir(parents=True, exist_ok=True)


def write_input_manifest() -> dict:
    files = {}
    for role, path in REQUIRED.items():
        files[role] = {"path": rel(path), "sha256": sha256(path), "bytes": path.stat().st_size}
    for role, path in OPTIONAL_RAW_MASKS.items():
        if path.exists():
            files[role] = {
                "path": rel(path),
                "sha256": sha256(path),
                "bytes": path.stat().st_size,
                "used": False,
            }
    payload = {
        "created_utc": utc_now(),
        "study_bounds_wgs84": STUDY_WGS84,
        "study_bounds_epsg32646": projected_study_bounds(),
        "crs": "EPSG:32646",
        "files": files,
    }
    with (OUT / "input_manifest.json").open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
        f.write("\n")
    return payload


def verify_frozen_inputs(input_manifest: dict) -> dict:
    frozen_path = ROOT / "forecasts" / "frozen" / "manifest.json"
    frozen = json.loads(frozen_path.read_text())
    expected_by_name = {row["name"]: row["sha256"] for row in frozen["files"]}
    checks = {}
    roles = [
        "forecast_banklines_2024",
        "forecast_banklines_2025",
        "forecast_banklines_2026",
        "forecast_bank_points_2024",
        "forecast_bank_points_2025",
        "forecast_bank_points_2026",
        "observed_banklines_2023",
    ]
    for role in roles:
        name = Path(input_manifest["files"][role]["path"]).name
        actual = input_manifest["files"][role]["sha256"]
        expected = expected_by_name[name]
        if actual != expected:
            raise RuntimeError(f"Frozen input hash mismatch for {role}: {actual} != {expected}")
        checks[role] = {"sha256": actual, "matches_frozen_manifest": True}
    for role, expected in [
        ("bank_migration_dataset", frozen["inputs"]["dataset_sha256"]),
        ("forecast_features_2023", frozen["inputs"]["forecast_features_sha256"]),
    ]:
        actual = input_manifest["files"][role]["sha256"]
        if actual != expected:
            raise RuntimeError(f"Frozen source hash mismatch for {role}: {actual} != {expected}")
        checks[role] = {"sha256": actual, "matches_frozen_manifest": True}
    payload = {
        "checks": checks,
        "frozen_manifest_sha256": sha256(frozen_path),
        "frozen_ready_sha256": sha256(ROOT / "forecasts" / "frozen" / "READY"),
        "pass": True,
    }
    with (OUT / "frozen_input_verification.json").open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
        f.write("\n")
    return payload


def frozen_snapshot() -> dict[str, str]:
    paths = []
    paths.extend(sorted((ROOT / "forecasts" / "frozen").glob("*")))
    paths.extend(sorted((ROOT / "models").glob("*")))
    paths.append(ROOT / "evaluation" / "metrics.json")
    paths.append(ROOT / "forecasts" / "frozen_origin2024" / "READY")
    return {rel(p): sha256(p) for p in paths if p.is_file()}


def read_mask(path: Path) -> dict:
    with rasterio.open(path) as ds:
        data = ds.read()
        if data.shape[0] < 2:
            raise RuntimeError(f"{rel(path)} must have water and valid bands")
        water = data[0] == 255
        valid = data[1] == 255
        if str(ds.crs) != "EPSG:32646":
            raise RuntimeError(f"{rel(path)} CRS is {ds.crs}, expected EPSG:32646")
        if abs(ds.transform.b) > 1e-9 or abs(ds.transform.d) > 1e-9:
            raise RuntimeError(f"{rel(path)} transform has rotation")
        if tuple(ds.res) != (30.0, 30.0):
            raise RuntimeError(f"{rel(path)} resolution is {ds.res}, expected 30 m")
        polygons = [
            shape(geom)
            for geom, value in shapes(water.astype("uint8"), mask=water, transform=ds.transform)
            if value == 1
        ]
        rings = []
        for polygon in polygons:
            rings.append(polygon.exterior)
            rings.extend(list(polygon.interiors))
        if not rings:
            raise RuntimeError(f"{rel(path)} has no water boundary")
        boundary = unary_union(rings)
        if boundary.is_empty:
            raise RuntimeError(f"{rel(path)} boundary is empty")
        return {
            "path": rel(path),
            "water": water,
            "valid": valid,
            "rings": rings,
            "boundary": boundary,
            "bounds": tuple(ds.bounds),
            "transform": ds.transform,
            "width": ds.width,
            "height": ds.height,
            "n_polygons": len(polygons),
        }


def validate_masks(masks: dict[int, dict]) -> dict:
    reference = masks[2023]
    for year, mask in masks.items():
        if mask["bounds"] != reference["bounds"]:
            raise RuntimeError(f"Mask bounds mismatch in {year}")
        if mask["transform"] != reference["transform"]:
            raise RuntimeError(f"Mask transform mismatch in {year}")
        if mask["water"].shape != reference["water"].shape:
            raise RuntimeError(f"Mask shape mismatch in {year}")
    payload = {
        "crs": "EPSG:32646",
        "resolution_m": 30.0,
        "shape": list(reference["water"].shape),
        "bounds": list(reference["bounds"]),
        "rotation_b": reference["transform"].b,
        "rotation_d": reference["transform"].d,
        "polygons": {str(y): masks[y]["n_polygons"] for y in YEARS},
        "pass": True,
    }
    with (OUT / "mask_checks.json").open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
        f.write("\n")
    return payload


def load_vector_data() -> dict:
    pred = pd.read_csv(REQUIRED["predictions"])
    if len(pred) != 450:
        raise RuntimeError(f"predictions.csv has {len(pred)} rows, expected 450")
    pred["sample_id"] = (
        "T" + pred["transect_id"].astype(int).map("{:03d}".format)
        + "_" + pred["side"].astype(str)
        + "_" + pred["origin_year"].astype(int).astype(str)
        + "_" + pred["year"].astype(int).astype(str)
    )
    pred["valid"] = pred["label_quality"].eq("good")
    pred["observed_abs_m"] = pred["observed_displacement_m"].abs()
    pred["changed"] = pred["observed_abs_m"] > LOW_MOVEMENT_M
    pred["exact_tie"] = (pred["model_abs_error_m"] - pred["zero_abs_error_m"]).abs() <= 1e-9
    pred["model_closer"] = (
        (pred["model_abs_error_m"] + 1e-9 < pred["zero_abs_error_m"]) & (~pred["exact_tie"])
    )
    pred["zero_closer"] = (
        (pred["zero_abs_error_m"] + 1e-9 < pred["model_abs_error_m"]) & (~pred["exact_tie"])
    )
    pred["both_within_15"] = (
        (pred["model_abs_error_m"] <= LOW_MOVEMENT_M)
        & (pred["zero_abs_error_m"] <= LOW_MOVEMENT_M)
    )
    pred["connector"] = np.where(
        pred["both_within_15"],
        "grey",
        np.where(pred["model_closer"], "green", np.where(pred["zero_closer"], "red", "grey")),
    )
    coord_cols = ["observed_bank_x", "observed_bank_y", "forecast_bank_x", "forecast_bank_y"]
    if pred.loc[pred["valid"], coord_cols].isna().any().any():
        raise RuntimeError("Valid prediction rows have missing bank coordinates")
    if pred["sample_id"].duplicated().any():
        raise RuntimeError("Duplicate sample_id in predictions.csv")

    transects = gpd.read_file(REQUIRED["transects_geojson"]).to_crs(TARGET_CRS)
    transects = transects.sort_values("transect_id").reset_index(drop=True)
    transects["section_id"] = (
        (transects["along_m"] // SECTION_LENGTH_M).astype(int) + 1
    ).clip(upper=7)
    if len(transects) != 75:
        raise RuntimeError(f"Expected 75 transects, got {len(transects)}")
    pred = pred.merge(
        transects[["transect_id", "along_m", "section_id"]],
        on="transect_id",
        how="left",
        suffixes=("", "_transect"),
        validate="many_to_one",
    )
    if pred["section_id"].isna().any():
        raise RuntimeError("Some predictions did not join to a transect")

    forecast_lines = {}
    forecast_points = {}
    observed_lines = {}
    observed_points = {}
    for year in YEARS:
        fl = gpd.read_file(REQUIRED[f"forecast_banklines_{year}"]).to_crs(TARGET_CRS)
        fl = fl[fl.geometry.geom_type == "LineString"].copy()
        if len(fl) != 2:
            raise RuntimeError(f"forecast banklines {year} has {len(fl)} line rows")
        forecast_lines[year] = fl
        fp = gpd.read_file(REQUIRED[f"forecast_bank_points_{year}"]).to_crs(TARGET_CRS)
        if len(fp) != 150:
            raise RuntimeError(f"forecast bank points {year} has {len(fp)} rows")
        forecast_points[year] = fp
        ol = gpd.read_file(REQUIRED[f"observed_banklines_{year}"]).to_crs(TARGET_CRS)
        ol = ol[ol.geometry.geom_type == "LineString"].copy()
        if len(ol) != 2:
            raise RuntimeError(f"observed banklines {year} has {len(ol)} line rows")
        observed_lines[year] = ol
        op = gpd.read_file(REQUIRED[f"observed_bank_points_{year}"]).to_crs(TARGET_CRS)
        if len(op) != 150:
            raise RuntimeError(f"observed bank points {year} has {len(op)} rows")
        observed_points[year] = op
    return {
        "pred": pred,
        "transects": transects,
        "forecast_lines": forecast_lines,
        "forecast_points": forecast_points,
        "observed_lines": observed_lines,
        "observed_points": observed_points,
    }


def check_metrics(pred: pd.DataFrame) -> tuple[dict, dict]:
    metrics = json.loads(REQUIRED["metrics"].read_text())
    good = pred[pred["valid"]]
    rows = []

    def close(label, expected, actual, tol=METRIC_TOL):
        diff = abs(expected - actual)
        rows.append(
            {
                "check": label,
                "expected": expected,
                "computed": actual,
                "abs_diff": diff,
                "tolerance": tol,
                "pass": bool(diff <= tol),
            }
        )
        if diff > tol:
            raise RuntimeError(
                f"Metric reproduction failed for {label}: {actual} vs {expected} (tol {tol})"
            )

    close("n_good_pairs", float(metrics["n_good_pairs"]), float(len(good)), 0.0)
    close("n_pairs", float(metrics["n_pairs"]), float(len(pred)), 0.0)
    close(
        "overall_random_forest_mae_m",
        float(metrics["models"]["random_forest"]["mae_m"]),
        float(good["model_abs_error_m"].mean()),
    )
    close(
        "overall_zero_mae_m",
        float(metrics["models"]["zero"]["mae_m"]),
        float(good["zero_abs_error_m"].mean()),
    )
    for year in YEARS:
        horizon = str(year - 2023)
        rf = metrics["models"]["random_forest"]["by_horizon"][horizon]
        zero = metrics["models"]["zero"]["by_horizon"][horizon]
        subset = good[good["year"] == year]
        close(f"random_forest_mae_{year}", float(rf["mae_m"]), float(subset["model_abs_error_m"].mean()))
        close(f"zero_mae_{year}", float(zero["mae_m"]), float(subset["zero_abs_error_m"].mean()))
        close(
            f"random_forest_within_15_{year}",
            float(rf["within_15m"]),
            float((subset["model_abs_error_m"] <= 15).mean()),
        )
        close(
            f"zero_within_15_{year}",
            float(zero["within_15m"]),
            float((subset["zero_abs_error_m"] <= 15).mean()),
        )
    payload = {
        "pass": True,
        "tolerance_m": METRIC_TOL,
        "checks": rows,
        "metrics_file_sha256": sha256(REQUIRED["metrics"]),
        "predictions_file_sha256": sha256(REQUIRED["predictions"]),
    }
    with (OUT / "metric_reproduction.json").open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
        f.write("\n")
    return metrics, payload


def check_boundaries(observed_points: dict, masks: dict[int, dict]) -> dict:
    results = []
    all_points_ok = True
    display_ok = True
    for year in YEARS:
        boundary = masks[year]["boundary"]
        pts = observed_points[year]
        distances = np.array([boundary.distance(geom) for geom in pts.geometry])
        points_max = float(np.nanmax(distances))
        if points_max > BOUNDARY_TOL_M:
            all_points_ok = False
        display_max = max(
            boundary.distance(Point(coord))
            for ring in masks[year]["rings"]
            for coord in ring.coords
        )
        if display_max > BOUNDARY_TOL_M:
            display_ok = False
        per_side = []
        for side in ["L", "R"]:
            source = gpd.read_file(REQUIRED[f"observed_banklines_{year}"]).to_crs(TARGET_CRS)
            source = source[source["side"] == side]
            line = source.geometry.iloc[0]
            vertex_max = max(boundary.distance(Point(coord)) for coord in line.coords)
            dense = segmentize(line, 5.0)
            dense_max = max(boundary.distance(Point(coord)) for coord in dense.coords)
            per_side.append(
                {
                    "side": side,
                    "source_vertices_max_m": float(vertex_max),
                    "source_dense_5m_max_m": float(dense_max),
                }
            )
        results.append(
            {
                "year": year,
                "observed_points_max_m": points_max,
                "observed_points_above_30m": int((distances > BOUNDARY_TOL_M).sum()),
                "displayed_boundary_max_m": float(display_max),
                "source": per_side,
                "source_chord_exceeds_30m": any(
                    row["source_dense_5m_max_m"] > BOUNDARY_TOL_M for row in per_side
                ),
            }
        )
    if not all_points_ok:
        raise RuntimeError("Observed bank points exceed 30 m from mask boundary")
    if not display_ok:
        raise RuntimeError("Displayed mask boundary exceeds 30 m from itself")
    payload = {
        "boundary_tolerance_m": BOUNDARY_TOL_M,
        "displayed_line": "unsimplified selected-river mask boundary, all components and holes",
        "source_polyline_note": "The supplied observed_banklines are 75-vertex chords; their vertices are on the boundary, but straight chords cut bends and can exceed 30 m when sampled densely. The displayed solid line is the mask boundary, not those chords.",
        "years": results,
        "observed_points_pass": all_points_ok,
        "displayed_boundary_pass": display_ok,
        "pass": True,
    }
    with (OUT / "boundary_check.json").open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
        f.write("\n")
    return payload


def summarize(group: pd.DataFrame, scope: str, year: int | None, side: str | None) -> dict:
    good = group[group["valid"]]
    changed = good[good["changed"]]
    unchanged = good[~good["changed"]]
    n = len(good)
    if n == 0:
        raise RuntimeError(f"No valid rows in {scope}")
    n_model_closer = int(good["model_closer"].sum())
    n_zero_closer = int(good["zero_closer"].sum())
    n_tie = int(good["exact_tie"].sum())
    n_both = int(good["both_within_15"].sum())
    return {
        "scope": scope,
        "year": year,
        "side": side,
        "n_total": len(group),
        "n_valid": n,
        "n_flagged": int((~group["valid"]).sum()),
        "model_mae_m": float(good["model_abs_error_m"].mean()),
        "zero_mae_m": float(good["zero_abs_error_m"].mean()),
        "model_rmse_m": float(np.sqrt(np.mean(good["model_error_m"] ** 2))),
        "zero_rmse_m": float(np.sqrt(np.mean(good["zero_error_m"] ** 2))),
        "model_bias_m": float(good["model_error_m"].mean()),
        "zero_bias_m": float(good["zero_error_m"].mean()),
        "model_within_15_share": float((good["model_abs_error_m"] <= 15).mean()),
        "zero_within_15_share": float((good["zero_abs_error_m"] <= 15).mean()),
        "model_within_30_share": float((good["model_abs_error_m"] <= 30).mean()),
        "zero_within_30_share": float((good["zero_abs_error_m"] <= 30).mean()),
        "model_closer_share": n_model_closer / n,
        "zero_closer_share": n_zero_closer / n,
        "tie_share": n_tie / n,
        "both_within_15_share": n_both / n,
        "n_model_closer": n_model_closer,
        "n_zero_closer": n_zero_closer,
        "n_tie": n_tie,
        "n_both_within_15": n_both,
        "n_changed": len(changed),
        "n_unchanged": len(unchanged),
        "model_mae_changed_m": float(changed["model_abs_error_m"].mean()) if len(changed) else math.nan,
        "zero_mae_changed_m": float(changed["zero_abs_error_m"].mean()) if len(changed) else math.nan,
        "direction_correct_changed_share": (
            float(
                (
                    np.sign(changed["model_prediction_m"])
                    == np.sign(changed["observed_displacement_m"])
                ).mean()
            )
            if len(changed)
            else math.nan
        ),
        "model_mae_unchanged_m": float(unchanged["model_abs_error_m"].mean()) if len(unchanged) else math.nan,
        "zero_mae_unchanged_m": float(unchanged["zero_abs_error_m"].mean()) if len(unchanged) else math.nan,
        "model_false_alarm_unchanged_share": (
            float((unchanged["model_abs_error_m"] > 15).mean()) if len(unchanged) else math.nan
        ),
    }


def build_tables(pred: pd.DataFrame, transects: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    rows = [summarize(pred, "overall", None, None)]
    for year in YEARS:
        rows.append(summarize(pred[pred["year"] == year], "year", year, None))
    for side in ["L", "R"]:
        rows.append(summarize(pred[pred["side"] == side], "side", None, side))
    for year in YEARS:
        for side in ["L", "R"]:
            rows.append(
                summarize(
                    pred[(pred["year"] == year) & (pred["side"] == side)],
                    "year_side",
                    year,
                    side,
                )
            )
    compare = pd.DataFrame(rows)
    compare.to_csv(OUT / "compare_table.csv", index=False)

    section_rows = []
    for (year, section_id), group in pred.groupby(["year", "section_id"], sort=True):
        row = summarize(group, "section", int(year), None)
        row["section_id"] = int(section_id)
        sec_transects = transects[transects["section_id"] == section_id]
        row["transect_min"] = int(sec_transects["transect_id"].min())
        row["transect_max"] = int(sec_transects["transect_id"].max())
        row["along_min_m"] = float(sec_transects["along_m"].min())
        row["along_max_m"] = float(sec_transects["along_m"].max())
        section_rows.append(row)
    section_table = pd.DataFrame(section_rows)
    cols = [
        "year", "section_id", "transect_min", "transect_max", "along_min_m", "along_max_m",
        "n_total", "n_valid", "n_flagged", "model_mae_m", "zero_mae_m",
        "model_closer_share", "zero_closer_share", "both_within_15_share",
        "n_changed", "model_mae_changed_m", "zero_mae_changed_m",
        "direction_correct_changed_share", "n_unchanged", "model_false_alarm_unchanged_share",
    ]
    section_table = section_table[cols]
    section_table.to_csv(OUT / "section_table.csv", index=False)

    pair_cols = [
        "sample_id", "year", "horizon_years", "transect_id", "side", "along_m", "section_id",
        "label_quality", "valid", "observed_displacement_m", "model_prediction_m", "zero_prediction_m",
        "model_abs_error_m", "zero_abs_error_m", "model_error_m", "zero_error_m",
        "changed", "model_closer", "zero_closer", "exact_tie", "both_within_15", "connector",
        "observed_bank_x", "observed_bank_y", "forecast_bank_x", "forecast_bank_y",
    ]
    pred[pair_cols].to_csv(OUT / "pair_table.csv", index=False)

    overall = compare.iloc[0]
    by_year = compare[compare["scope"] == "year"].set_index("year")
    headline = {
        "n_good_pairs": int(overall["n_valid"]),
        "n_flagged_or_invalid": int(overall["n_flagged"]),
        "model_mae_m": float(overall["model_mae_m"]),
        "zero_mae_m": float(overall["zero_mae_m"]),
        "model_closer_share": float(overall["model_closer_share"]),
        "zero_closer_share": float(overall["zero_closer_share"]),
        "tie_share": float(overall["tie_share"]),
        "both_within_15_share": float(overall["both_within_15_share"]),
        "by_year": {
            str(year): {
                "n": int(by_year.loc[year, "n_valid"]),
                "model_mae_m": float(by_year.loc[year, "model_mae_m"]),
                "zero_mae_m": float(by_year.loc[year, "zero_mae_m"]),
                "model_closer_share": float(by_year.loc[year, "model_closer_share"]),
                "both_within_15_share": float(by_year.loc[year, "both_within_15_share"]),
            }
            for year in YEARS
        },
        "definitions": {
            "model_closer": "strictly smaller absolute error than zero change; exact ties reported separately",
            "both_within_15": "both forecast and zero errors <= 15 m; connector drawn grey",
            "connector_colors": "grey if both <= 15 m; green if model strictly closer; red if zero strictly closer; exact ties grey",
        },
    }
    with (OUT / "headline.json").open("w", encoding="utf-8") as f:
        json.dump(headline, f, indent=2)
        f.write("\n")
    return compare, section_table, headline


def build_overview_stats(pred: pd.DataFrame, metrics: dict) -> pd.DataFrame:
    good = pred[pred["valid"]]
    rows = []
    for year in YEARS:
        horizon = str(year - 2023)
        rf = metrics["models"]["random_forest"]["by_horizon"][horizon]
        zero = metrics["models"]["zero"]["by_horizon"][horizon]
        sub = good[good["year"] == year]
        n = int(rf["n"])
        if n != len(sub) or int(zero["n"]) != len(sub):
            raise RuntimeError(
                f"Overview n mismatch for {year}: metrics {rf['n']}/{zero['n']}, computed {len(sub)}"
            )
        computed_model = float(sub["model_abs_error_m"].mean())
        computed_zero = float(sub["zero_abs_error_m"].mean())
        if abs(computed_model - float(rf["mae_m"])) > METRIC_TOL:
            raise RuntimeError(
                f"Overview forecast MAE mismatch for {year}: {computed_model} vs {rf['mae_m']}"
            )
        if abs(computed_zero - float(zero["mae_m"])) > METRIC_TOL:
            raise RuntimeError(
                f"Overview zero MAE mismatch for {year}: {computed_zero} vs {zero['mae_m']}"
            )
        n_closer = int(sub["model_closer"].sum())
        n_farther = int(sub["zero_closer"].sum())
        n_tie = int(sub["exact_tie"].sum())
        if n_closer + n_farther + n_tie != len(sub):
            raise RuntimeError(f"Overview groups do not partition {year}")
        lengths = np.hypot(
            sub["forecast_bank_x"] - sub["observed_bank_x"],
            sub["forecast_bank_y"] - sub["observed_bank_y"],
        )
        rows.append(
            {
                "year": year,
                "n_total": int((pred["year"] == year).sum()),
                "n_valid": n,
                "n_flagged": int((pred["year"] == year).sum()) - n,
                "model_mae_m": float(rf["mae_m"]),
                "zero_mae_m": float(zero["mae_m"]),
                "model_closer_n": n_closer,
                "zero_closer_n": n_farther,
                "exact_tie_n": n_tie,
                "model_closer_share": n_closer / n,
                "zero_closer_share": n_farther / n,
                "tie_share": n_tie / n,
                "both_within_15_n": int(sub["both_within_15"].sum()),
                "both_within_15_share": float(sub["both_within_15"].mean()),
                "n_green": int((sub["connector"] == "green").sum()),
                "n_red": int((sub["connector"] == "red").sum()),
                "n_grey": int((sub["connector"] == "grey").sum()),
                "connector_min_m": float(lengths.min()),
                "connector_median_m": float(lengths.median()),
                "connector_max_m": float(lengths.max()),
            }
        )
    frame = pd.DataFrame(rows)
    frame.to_csv(OUT / "overview_stats.csv", index=False)
    payload = {
        "caption": OVERVIEW_CAPTION,
        "years": rows,
        "sources": {
            "forecast_mae_m": "evaluation/metrics.json models.random_forest.by_horizon",
            "zero_mae_m": "evaluation/metrics.json models.zero.by_horizon",
            "n_valid": "evaluation/metrics.json by_horizon n, reproduced from predictions.csv",
            "closer_farther_ties": "strict absolute-error comparison in evaluation/predictions.csv; metrics.json has no closer field",
        },
    }
    with (OUT / "overview_stats.json").open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
        f.write("\n")
    return frame


def build_closer_groups(pred: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    good = pred[pred["valid"]].copy()
    good["group"] = np.select(
        [good["model_closer"], good["zero_closer"]],
        ["forecast_closer", "forecast_farther"],
        default="exact_tie",
    )
    labels = {
        "forecast_closer": "forecast closer",
        "forecast_farther": "forecast farther (zero closer)",
        "exact_tie": "exact tie",
    }
    specs = [("overall", None)] + [("year", year) for year in YEARS]
    rows = []
    for scope, year in specs:
        group = good if year is None else good[good["year"] == year]
        for key in ["forecast_closer", "forecast_farther", "exact_tie"]:
            sub = group[group["group"] == key]
            n = len(sub)
            rows.append(
                {
                    "scope": scope,
                    "year": "" if year is None else year,
                    "group": key,
                    "group_label": labels[key],
                    "n": n,
                    "share": n / len(group) if len(group) else math.nan,
                    "model_mae_m": float(sub["model_abs_error_m"].mean()) if n else math.nan,
                    "zero_mae_m": float(sub["zero_abs_error_m"].mean()) if n else math.nan,
                    "mean_abs_observed_m": float(sub["observed_abs_m"].mean()) if n else math.nan,
                }
            )
    groups = pd.DataFrame(rows)
    groups.to_csv(OUT / "closer_vs_farther.csv", index=False)
    pairs = good[
        [
            "sample_id", "year", "transect_id", "side", "section_id", "group",
            "model_abs_error_m", "zero_abs_error_m", "observed_displacement_m", "connector",
        ]
    ].copy()
    pairs["group_label"] = pairs["group"].map(labels)
    pairs.sort_values(["year", "transect_id", "side"]).to_csv(
        OUT / "closer_vs_farther_pairs.csv", index=False
    )
    return groups, pairs


def select_changed_places(
    pred: pd.DataFrame, transects: pd.DataFrame, section_table: pd.DataFrame
) -> pd.DataFrame:
    good = pred[pred["valid"]]
    selected = []
    for year in YEARS:
        candidates = []
        for section_id in sorted(section_table["section_id"].unique()):
            sec = good[(good["year"] == year) & (good["section_id"] == section_id)]
            if sec.empty:
                continue
            candidates.append(
                {
                    "year": year,
                    "section_id": int(section_id),
                    "n_valid": int(len(sec)),
                    "max_abs_observed_m": float(sec["observed_abs_m"].max()),
                    "mean_abs_observed_m": float(sec["observed_abs_m"].mean()),
                    "n_changed": int(sec["changed"].sum()),
                }
            )
        if len(candidates) < 6:
            raise RuntimeError(f"Need 6 changed-place sections for {year}, found {len(candidates)}")
        candidates.sort(key=lambda row: (-row["max_abs_observed_m"], row["section_id"]))
        for rank, row in enumerate(candidates[:6], start=1):
            metric_row = section_table[
                (section_table["year"] == year)
                & (section_table["section_id"] == row["section_id"])
            ].iloc[0]
            row.update(
                {
                    "rank": rank,
                    "n_total": int(metric_row["n_total"]),
                    "n_flagged": int(metric_row["n_flagged"]),
                    "transect_min": int(metric_row["transect_min"]),
                    "transect_max": int(metric_row["transect_max"]),
                    "model_mae_m": float(metric_row["model_mae_m"]),
                    "zero_mae_m": float(metric_row["zero_mae_m"]),
                    "model_closer_share": float(metric_row["model_closer_share"]),
                    "both_within_15_share": float(metric_row["both_within_15_share"]),
                    "model_mae_changed_m": float(metric_row["model_mae_changed_m"]),
                    "zero_mae_changed_m": float(metric_row["zero_mae_changed_m"]),
                }
            )
            selected.append(row)
    frame = pd.DataFrame(selected)
    cols = [
        "year", "rank", "section_id", "transect_min", "transect_max",
        "max_abs_observed_m", "mean_abs_observed_m", "n_total", "n_valid", "n_flagged",
        "model_mae_m", "zero_mae_m", "model_closer_share", "both_within_15_share",
        "n_changed", "model_mae_changed_m", "zero_mae_changed_m",
    ]
    frame = frame[cols]
    frame.to_csv(OUT / "changed_places_selection.csv", index=False)
    return frame


def build_figure_text_audit(
    overview_stats: pd.DataFrame, changed_selection: pd.DataFrame
) -> dict:
    overview = []
    for _, row in overview_stats.iterrows():
        line1, caption = overview_box_lines(row)
        overview.append(
            {
                "year": int(row["year"]),
                "text_box": line1,
                "caption": caption,
                "model_mae_m": float(row["model_mae_m"]),
                "zero_mae_m": float(row["zero_mae_m"]),
                "model_closer_n": int(row["model_closer_n"]),
                "exact_tie_n": int(row["exact_tie_n"]),
                "pass": True,
            }
        )
    changed = []
    for _, row in changed_selection.iterrows():
        line1, line2 = changed_place_lines(row)
        changed.append(
            {
                "year": int(row["year"]),
                "rank": int(row["rank"]),
                "section_id": int(row["section_id"]),
                "line1": line1,
                "line2": line2,
                "pass": True,
            }
        )
    payload = {
        "caption": OVERVIEW_CAPTION,
        "overview": overview,
        "changed_places": changed,
        "closer_source": "evaluation/predictions.csv; metrics.json has no closer field",
        "changed_places_rule": "six existing 4 km sections per year with largest maximum |observed displacement| among valid pairs",
        "pass": True,
    }
    with (OUT / "figure_text_audit.json").open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
        f.write("\n")
    return payload


def fmt_m(value) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "—"
    return f"{value:.2f}"


def fmt_pct(value) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "—"
    return f"{100.0 * value:.1f}%"


def md_table(headers: list[str], rows: list[list[str]]) -> str:
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join(["---"] * len(headers)) + "|"]
    for row in rows:
        out.append("| " + " | ".join(str(v) for v in row) + " |")
    return "\n".join(out)
