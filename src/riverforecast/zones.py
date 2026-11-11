from __future__ import annotations

import glob
import json
import math
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd
from scipy.stats import spearmanr, theilslopes
from shapely.geometry import mapping
from shapely.ops import unary_union

from .config import PROJECT_ROOT, project_path

UI_CONFIG_PATH = PROJECT_ROOT / "config" / "ui.json"
ZONE_DIR = project_path("derived", "zones")


def load_ui_config() -> dict[str, Any]:
    with open(UI_CONFIG_PATH, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _clean_positions() -> pd.DataFrame:
    paths = [project_path("derived", "measurements", "bank_positions.csv")]
    paths.extend(sorted(glob.glob(str(project_path("evaluation", "observed_bank_positions_*.csv")))))
    frames = [pd.read_csv(path) for path in paths]
    data = pd.concat(frames, ignore_index=True)
    flags = data["flags"].fillna("[]")
    keep = data["valid_bank"] & (flags == "[]") & (data["year"] != 1997)
    data = data.loc[keep].copy()
    data["outward_m"] = data["bank_dist_m"] * data["outward_sign"]
    return data


def _stretch_net(data: pd.DataFrame, transect_ids: list[int], first: int | None = None, last: int | None = None) -> float | None:
    subset = data[data["transect_id"].isin(transect_ids)]
    if first is not None:
        subset = subset[(subset["year"] >= first) & (subset["year"] <= last)]
    values: list[float] = []
    for transect_id in transect_ids:
        rows = subset[subset["transect_id"] == transect_id]
        if len(rows) < 3:
            continue
        span = rows["year"].max() - rows["year"].min()
        if span > 0:
            slope = theilslopes(rows["outward_m"].to_numpy(), rows["year"].to_numpy(), 0.90)[0]
            values.append(float(slope * span))
    return float(np.median(values)) if values else None


def _tier(lower: float | None, upper: float | None, thresholds: dict[str, float]) -> str:
    if lower is None or upper is None:
        return "no_clear"
    if lower >= thresholds["strong_lower"]:
        return "strong"
    if lower > 0 and lower >= thresholds["moderate_lower"]:
        return "moderate"
    if upper <= thresholds["land_gained_upper"]:
        return "land_gained"
    return "no_clear"


def _stretch_stats(data: pd.DataFrame, config: dict[str, Any]) -> list[dict[str, Any]]:
    zones = config["zones"]
    block_years = int(zones["block_years"])
    reps = int(zones["bootstrap_replicates"])
    rng = np.random.default_rng(int(zones["bootstrap_seed"]))
    thresholds = zones["thresholds_m"]
    results: list[dict[str, Any]] = []
    for side in ("L", "R"):
        for start in range(1, 76, int(zones["stretch_transects"])):
            ids = list(range(start, min(start + int(zones["stretch_transects"]), 76)))
            subset = data[(data["side"] == side) & data["transect_id"].isin(ids)]
            years = np.array(sorted(subset["year"].unique()))
            matrix: list[np.ndarray] = []
            series: list[tuple[np.ndarray, np.ndarray]] = []
            for transect_id in ids:
                rows = subset[subset["transect_id"] == transect_id].sort_values("year")
                if len(rows) >= 3:
                    series.append((rows["year"].to_numpy(dtype=float), rows["outward_m"].to_numpy(dtype=float)))
                    matrix.append(rows.set_index("year")["outward_m"].reindex(years).to_numpy(dtype=float))
                else:
                    matrix.append(np.full(len(years), np.nan))
            values = np.column_stack(matrix)
            lower = upper = None
            if len(series) >= 2 and len(years) >= 4:
                span = float(years.max() - years.min())
                points = [theilslopes(y, x, 0.90)[0] * span for x, y in series]
                blocks = [years[i : i + block_years] for i in range(0, len(years), block_years)]
                samples: list[float] = []
                for _ in range(reps):
                    take = rng.integers(0, len(blocks), size=len(blocks))
                    sample = np.concatenate([blocks[int(i)] for i in take])[: len(years)]
                    positions = np.searchsorted(years, sample)
                    x = years[positions].astype(float)
                    y = values[positions, :]
                    ii, jj = np.triu_indices(len(x), 1)
                    dx = x[jj] - x[ii]
                    valid = dx != 0
                    diff = y[jj, :] - y[ii, :]
                    slopes = []
                    for column in range(diff.shape[1]):
                        good = valid & ~np.isnan(diff[:, column])
                        if good.any():
                            slopes.append(np.median(diff[good, column] / dx[good]))
                    if slopes:
                        samples.append(float(np.median(np.array(slopes) * span)))
                if samples:
                    lower, upper = (float(v) for v in np.percentile(samples, [5, 95]))
                net = float(np.median(points))
            else:
                net = 0.0
            results.append(
                {
                    "side": side,
                    "start": ids[0],
                    "end": ids[-1],
                    "net_m": net,
                    "lower_m": lower,
                    "upper_m": upper,
                    "interval_width_m": (upper - lower) if lower is not None and upper is not None else None,
                    "tier": _tier(lower, upper, thresholds),
                    "n_transects": len(series),
                }
            )
    return results


def _corridor(config: dict[str, Any]) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
    river_paths = sorted(glob.glob(str(project_path("processed", "river", "river_*.geojson"))))
    if not river_paths:
        raise FileNotFoundError("No processed river polygons found")
    rivers = pd.concat([gpd.read_file(path).to_crs(32646) for path in river_paths], ignore_index=True)
    union = unary_union(rivers.geometry)
    corridor = gpd.GeoDataFrame(geometry=[union.buffer(float(config["corridor_buffer_m"]))], crs=32646)
    return corridor, rivers


def _band_geometry(data: pd.DataFrame, corridor_geom, band_width_m: float, latest_year: int | None = None) -> Any:
    subset = data
    if latest_year is not None:
        subset = subset[subset["year"] >= latest_year - 9]
    pieces = []
    for (_, _), group in subset.groupby(["side", "year"]):
        points = gpd.GeoDataFrame(
            group,
            geometry=gpd.points_from_xy(group["bank_x"], group["bank_y"]),
            crs=32646,
        ).sort_values("transect_id")
        if len(points) >= 2:
            pieces.append(points.geometry.unary_union.buffer(band_width_m / 2, cap_style="flat"))
        elif len(points) == 1:
            pieces.append(points.geometry.iloc[0].buffer(band_width_m / 2))
    if not pieces:
        return None
    geom = unary_union(pieces).intersection(corridor_geom)
    return geom.simplify(2.0)


def _observed_edges(years: list[int], band_width_m: float, corridor_geom):
    edges = {}
    for year in years:
        if year == 2023:
            path = project_path("forecasts", "frozen", "observed_banklines_2023.geojson")
        else:
            path = project_path("evaluation", f"observed_banklines_{year}.geojson")
        lines = gpd.read_file(path).to_crs(32646)
        geom = unary_union(lines.geometry).buffer(band_width_m / 2, cap_style="flat").intersection(corridor_geom)
        edges[year] = geom.simplify(1.0)
    return edges


def _reach_points() -> list[dict[str, Any]]:
    transects = gpd.read_file(project_path("derived", "transects.geojson")).to_crs(4326)
    jumps = []
    for reach, group in transects.groupby("reach"):
        center = group.geometry.unary_union.centroid
        jumps.append({"id": str(reach), "center": [float(center.y), float(center.x)]})
    return jumps


def _diagnostics(results: list[dict[str, Any]], data: pd.DataFrame, config: dict[str, Any]) -> dict[str, Any]:
    frame = pd.DataFrame(results)
    thresholds = config["zones"]["thresholds_m"]
    transects = gpd.read_file(project_path("derived", "transects.geojson")).to_crs(32646)
    half = transects.geometry.length / 2
    widths = data.drop_duplicates(["year", "transect_id"]).groupby("year")["width_m"].median().dropna()
    land = frame[frame["tier"] == "land_gained"]
    opposite = []
    for _, row in land.iterrows():
        other = frame[(frame["side"] != row["side"]) & (frame["start"] == row["start"]) & (frame["end"] == row["end"])]
        value = float(other["net_m"].iloc[0]) if len(other) else None
        opposite.append(
            {
                "id": f"{row['side']}{int(row['start'])}-{int(row['end'])}",
                "net_m": float(row["net_m"]),
                "opposite_net_m": value,
                "opposite_outward": bool(value is not None and value > 0),
                "both_inward": bool(value is not None and value < 0),
            }
        )
    period = []
    for _, row in frame.iterrows():
        if int(row["n_transects"]) < 2:
            continue
        ids = list(range(int(row["start"]), int(row["end"]) + 1))
        subset = data[(data["side"] == row["side"]) & data["transect_id"].isin(ids)]
        early = _stretch_net(subset, ids, 1989, 2007)
        late = _stretch_net(subset, ids, 2008, 2026)
        if early is not None and late is not None:
            period.append((early, late))
    if len(period) >= 3:
        corr, pvalue = spearmanr([p[0] for p in period], [p[1] for p in period])
    else:
        corr, pvalue = float("nan"), float("nan")
    widths_out = {str(int(year)): float(value) for year, value in widths.items()}
    return {
        "transect_half_m": {
            "n": int(len(half)),
            "min": float(half.min()),
            "q1": float(half.quantile(0.25)),
            "median": float(half.median()),
            "q3": float(half.quantile(0.75)),
            "max": float(half.max()),
        },
        "net_m": {
            "min": float(frame["net_m"].min()),
            "q1": float(frame["net_m"].quantile(0.25)),
            "median": float(frame["net_m"].median()),
            "q3": float(frame["net_m"].quantile(0.75)),
            "max": float(frame["net_m"].max()),
        },
        "interval_width_m": {
            "n": int(frame["interval_width_m"].notna().sum()),
            "min": float(frame["interval_width_m"].min()),
            "q1": float(frame["interval_width_m"].quantile(0.25)),
            "median": float(frame["interval_width_m"].median()),
            "q3": float(frame["interval_width_m"].quantile(0.75)),
            "max": float(frame["interval_width_m"].max()),
        },
        "tier_counts": {tier: int((frame["tier"] == tier).sum()) for tier in config["zones"]["tier_order"]},
        "total_stretches": int(len(frame)),
        "land_gained": opposite,
        "land_gained_opposite_outward": int(sum(1 for row in opposite if row["opposite_outward"])),
        "land_gained_both_inward": int(sum(1 for row in opposite if row["both_inward"])),
        "median_width_by_year": widths_out,
        "period_rank": {
            "n": int(len(period)),
            "spearman": float(corr),
            "p": float(pvalue),
        },
        "thresholds_m": thresholds,
    }


def _feature(row: dict[str, Any], geometry, config: dict[str, Any], data: pd.DataFrame, latest_year: int) -> dict[str, Any]:
    zones = config["zones"]
    ids = list(range(int(row["start"]), int(row["end"]) + 1))
    subset = data[(data["side"] == row["side"]) & data["transect_id"].isin(ids)]
    recent = _stretch_net(subset, ids, latest_year - int(zones["recent_years"]) + 1, latest_year)
    tier = row["tier"]
    colour = zones["tier_colors"][tier]
    net = float(row["net_m"])
    geometry_4326 = gpd.GeoSeries([geometry], crs=32646).to_crs(4326).iloc[0]
    return {
        "type": "Feature",
        "id": f"{row['side']}{int(row['start'])}-{int(row['end'])}",
        "geometry": mapping(geometry_4326),
        "properties": {
            "id": f"{row['side']}-{int(row['start'])}-{int(row['end'])}",
            "side": row["side"],
            "start_transect": int(row["start"]),
            "end_transect": int(row["end"]),
            "reach": "north" if int(row["start"]) <= 25 else "middle" if int(row["start"]) <= 50 else "south",
            "tier": tier,
            "tier_label": zones["tier_labels"][tier],
            "net_m": round(net, 1),
            "lower_m": round(row["lower_m"], 1) if row["lower_m"] is not None else None,
            "upper_m": round(row["upper_m"], 1) if row["upper_m"] is not None else None,
            "interval_width_m": round(row["interval_width_m"], 1) if row["interval_width_m"] is not None else None,
            "recent_10y_m": round(recent, 1) if recent is not None else None,
            "recent_years": int(zones["recent_years"]),
            "n_transects": int(row["n_transects"]),
            "confidence": "clear" if tier != "no_clear" else "unclear",
            "direction": "land_gained" if tier == "land_gained" else "outward" if net > 0 else "inward" if net < 0 else "little",
            "fill": colour["fill"],
            "fill_opacity": colour["fill_opacity"],
            "outline": colour["outline"],
            "outline_style": zones["outline_styles"][tier],
            "years": zones["years"],
        },
    }


def build_zones(config: dict[str, Any] | None = None) -> dict[str, Any]:
    config = config or load_ui_config()
    zones = config["zones"]
    ZONE_DIR.mkdir(parents=True, exist_ok=True)
    data = _clean_positions()
    corridor, _ = _corridor(config)
    corridor_geom = corridor.geometry.iloc[0]
    results = _stretch_stats(data, config)
    latest_year = int(max(data["year"].max(), max(zones["years"])))
    features = []
    for row in results:
        band = _band_geometry(data[(data["side"] == row["side"]) & (data["transect_id"].between(row["start"], row["end"]))], corridor_geom, float(zones["band_width_m"]))
        if band is None or band.is_empty:
            band = _band_geometry(data[(data["side"] == row["side"]) & (data["transect_id"].between(row["start"], row["end"]))], corridor_geom, float(zones["band_width_m"]) * 2)
        if band is None or band.is_empty:
            continue
        features.append(_feature(row, band, config, data, latest_year))
    edges = _observed_edges([2023, 2024, 2025, 2026], float(zones["band_width_m"]), corridor_geom)
    diagnostics = _diagnostics(results, data, config)
    relative_available = bool(diagnostics["period_rank"]["spearman"] >= float(zones["relative_min_spearman"]))
    counts = diagnostics["tier_counts"]
    bounds = corridor.to_crs(4326).total_bounds
    summary = {
        "years": zones["years"],
        "latest_year": latest_year,
        "starting_year": 2023,
        "method": {
            "corridor_buffer_m": config["corridor_buffer_m"],
            "band_width_m": zones["band_width_m"],
            "stretch_transects": zones["stretch_transects"],
            "block_years": zones["block_years"],
            "bootstrap_replicates": zones["bootstrap_replicates"],
            "bootstrap_seed": zones["bootstrap_seed"],
            "confidence": zones["confidence"],
            "skip_years": zones["skip_years"],
            "recent_years": zones["recent_years"],
            "thresholds_m": zones["thresholds_m"],
            "transect_half_m": diagnostics["transect_half_m"]["median"],
        },
        "total_stretches": len(results),
        "counts": counts,
        "tier_order": zones["tier_order"],
        "tier_labels": zones["tier_labels"],
        "tier_colors": zones["tier_colors"],
        "outline_styles": zones["outline_styles"],
        "clear_layer_label": zones["clear_layer_label"],
        "relative_available": relative_available,
        "relative_layer": {
            "label": zones["relative_layer_label"],
            "note": zones["relative_note"],
            "share": zones["relative_share"],
            "min_spearman": zones["relative_min_spearman"],
        },
        "diagnostics": diagnostics,
        "bounds": [float(v) for v in bounds],
        "jumps": _reach_points(),
        "basemap": config["basemap"],
        "map": config["map"],
        "years_available": [int(year) for year in sorted(data["year"].unique())],
        "observed_years": [2024, 2025, 2026],
    }
    sample_id = next((f["properties"]["id"] for f in features if f["properties"]["tier"] == "no_clear" and f["properties"]["n_transects"] == 3), features[0]["properties"]["id"])
    sample_row = next(row for row in results if f"{row['side']}-{row['start']}-{row['end']}" == sample_id.replace("-", "-"))
    sample_ids = list(range(int(sample_row["start"]), int(sample_row["end"]) + 1))
    sample_data = data[(data["side"] == sample_row["side"]) & data["transect_id"].isin(sample_ids)]
    sample = {
        "id": sample_id,
        "side": sample_row["side"],
        "transect_ids": sample_ids,
        "years": zones["years"],
        "observations": [
            {"year": int(row["year"]), "transect_id": int(row["transect_id"]), "outward_m": float(row["outward_m"])}
            for _, row in sample_data.sort_values(["year", "transect_id"]).iterrows()
        ],
        "net_m": round(float(sample_row["net_m"]), 6),
        "lower_m": round(float(sample_row["lower_m"]), 6),
        "upper_m": round(float(sample_row["upper_m"]), 6),
        "tier": sample_row["tier"],
    }
    collection = {
        "type": "FeatureCollection",
        "features": features,
        "metadata": {
            "total_stretches": len(results),
            "counts": counts,
            "coordinates": "EPSG:4326",
            "band_width_m": zones["band_width_m"],
        },
    }
    corridor_collection = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"buffer_m": config["corridor_buffer_m"], "bounds": [float(v) for v in bounds]},
                "geometry": mapping(corridor.to_crs(4326).geometry.iloc[0]),
            }
        ],
    }
    edges_collection = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"year": year, "kind": "observed", "band_width_m": zones["band_width_m"]},
                "geometry": mapping(gpd.GeoSeries([geom], crs=32646).to_crs(4326).iloc[0]),
            }
            for year, geom in edges.items()
        ],
    }
    bad_rows = [row for row in results if row["lower_m"] is None or row["upper_m"] is None]
    for row in bad_rows:
        if row["tier"] != "no_clear":
            raise ValueError(f"Undefined interval left a non-clear tier: {row}")
    summary["features_with_geometry"] = len(features)
    summary["undefined_intervals"] = len(bad_rows)
    summary["sample"] = sample
    (ZONE_DIR / "zones.geojson").write_text(json.dumps(collection), encoding="utf-8")
    (ZONE_DIR / "corridor.geojson").write_text(json.dumps(corridor_collection), encoding="utf-8")
    (ZONE_DIR / "edges.geojson").write_text(json.dumps(edges_collection), encoding="utf-8")
    (ZONE_DIR / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    (project_path("reports", "zone_diagnostics.json")).write_text(json.dumps(diagnostics, indent=2), encoding="utf-8")
    return summary


if __name__ == "__main__":
    print(json.dumps(build_zones(), indent=2))
