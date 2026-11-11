from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd
import rasterio
from rasterio.features import shapes
from scipy import ndimage
from shapely.geometry import shape
from shapely.ops import unary_union

from .config import ensure_output_dirs, load_config, project_path
from .io import read_river_mask, write_geojson, write_json


def _dates(years: list[int]) -> dict[int, pd.Timestamp]:
    return {y: pd.Timestamp(f"{int(y)}-03-25") for y in years}


def change_maps(years: list[int]) -> pd.DataFrame:
    cfg = load_config()
    min_px = int(cfg["labels"]["change_min_patch_px"])
    rows = []
    cache = {y: read_river_mask(y) for y in years}
    with rasterio.open(project_path("processed", "river", f"river_{years[0]}.tif")) as src:
        transform = src.transform
        crs = src.crs
    dates = _dates(years)
    for a, b in zip(years[:-1], years[1:]):
        wa, va = cache[a]
        wb, vb = cache[b]
        common = va & vb
        erosion = common & ~wa & wb
        accretion = common & wa & ~wb
        raw = np.zeros_like(wa, dtype="int16")
        raw[erosion] = 1
        raw[accretion] = -1
        raw[~common] = 255
        raw_path = project_path("derived", "change_maps", f"change_{a}_{b}.tif")
        _write_change(raw_path, raw, transform, crs, nodata=255)
        filt = np.zeros_like(raw)
        filt[~common] = 255
        for value, mask in [(1, erosion), (-1, accretion)]:
            lab, n = ndimage.label(mask, structure=np.ones((3, 3), int))
            if n == 0:
                continue
            sizes = ndimage.sum(mask, lab, range(1, n + 1))
            keep = np.isin(lab, [i + 1 for i, s in enumerate(sizes) if s >= min_px])
            filt[keep] = value
        filt_path = project_path("derived", "change_maps", f"change_filtered_{a}_{b}.tif")
        _write_change(filt_path, filt, transform, crs, nodata=255)
        _change_geojson(a, b, filt, transform, crs)
        elapsed = (dates[b] - dates[a]).days
        rows.append(
            {
                "from_year": a,
                "to_year": b,
                "from_date": dates[a].date().isoformat(),
                "to_date": dates[b].date().isoformat(),
                "elapsed_days": elapsed,
                "elapsed_years": elapsed / 365.25,
                "erosion_pixels_raw": int(erosion.sum()),
                "accretion_pixels_raw": int(accretion.sum()),
                "erosion_pixels_filtered": int((filt == 1).sum()),
                "accretion_pixels_filtered": int((filt == -1).sum()),
                "erosion_area_m2_raw": float(erosion.sum() * 900.0),
                "accretion_area_m2_raw": float(accretion.sum() * 900.0),
                "erosion_area_m2_filtered": float((filt == 1).sum() * 900.0),
                "accretion_area_m2_filtered": float((filt == -1).sum() * 900.0),
                "net_area_m2_filtered": float(((filt == -1).sum() - (filt == 1).sum()) * 900.0),
                "interval_gt_5yr": bool((dates[b] - dates[a]).days > 5 * 365.25 + 2),
                "min_patch_px": min_px,
            }
        )
    df = pd.DataFrame(rows)
    df.to_csv(project_path("derived", "measurements", "change_intervals.csv"), index=False)
    return df


def _write_change(path, arr, transform, crs, nodata):
    path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=arr.shape[0],
        width=arr.shape[1],
        count=1,
        dtype="int16",
        crs=crs,
        transform=transform,
        nodata=nodata,
        compress="deflate",
    ) as dst:
        dst.write(arr, 1)
        dst.update_tags(encoding="1=erosion(land->water), -1=accretion(water->land), 0=no change, 255=nodata")


def _change_geojson(a, b, arr, transform, crs):
    feats = []
    for geom, value in shapes(arr.astype("int16"), mask=(arr != 0) & (arr != 255), transform=transform, connectivity=8):
        if value == 1:
            kind = "erosion"
        elif value == -1:
            kind = "accretion"
        else:
            continue
        g = shape(geom)
        feats.append(
            {
                "geometry": g,
                "properties": {
                    "from_year": a,
                    "to_year": b,
                    "change_type": kind,
                    "area_m2": float(g.area),
                },
            }
        )
    if feats:
        write_geojson(project_path("derived", "change_maps", f"change_{a}_{b}.geojson"), feats, crs=crs.to_string())


def bank_intervals(years: list[int]) -> pd.DataFrame:
    cfg = load_config()
    df = pd.read_csv(project_path("derived", "measurements", "bank_positions.csv"))
    df = df[df["year"].isin(years)].copy()
    dates = _dates(years)
    rows = []
    for a, b in zip(years[:-1], years[1:]):
        da = df[df["year"] == a].set_index(["transect_id", "side"])
        db = df[df["year"] == b].set_index(["transect_id", "side"])
        for key in sorted(set(da.index) & set(db.index)):
            ra = da.loc[key]
            rb = db.loc[key]
            valid = bool(ra["valid_bank"] and rb["valid_bank"])
            displacement = np.nan
            if valid:
                dx = float(rb["bank_x"] - ra["bank_x"])
                dy = float(rb["bank_y"] - ra["bank_y"])
                displacement = (dx * ra["normal_x"] + dy * ra["normal_y"]) * ra["outward_sign"]
            elapsed_days = (dates[b] - dates[a]).days
            flags = sorted(set(list(ra["flags"]) + list(rb["flags"])))
            if valid and abs(displacement) > float(cfg["labels"]["max_plausible_abs_displacement_m"]):
                flags.append("displacement_gt_5px")
            if elapsed_days > 5 * 365.25 + 2:
                flags.append("interval_gt_5yr")
            row = {
                "from_year": a,
                "to_year": b,
                "from_date": dates[a].date().isoformat(),
                "to_date": dates[b].date().isoformat(),
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
            row["quality"] = _quality(row, cfg)
            rows.append(row)
    out = pd.DataFrame(rows)
    out.to_csv(project_path("derived", "measurements", "bank_migration_intervals_raw.csv"), index=False)
    filtered = out[out["quality"] == "good"].copy()
    filtered.to_csv(project_path("derived", "measurements", "bank_migration_intervals_filtered.csv"), index=False)
    return out


def _quality(row: dict, cfg: dict) -> str:
    if not row["valid_bank"]:
        return "invalid"
    if "missing_bank" in row["flags"]:
        return "invalid"
    if "displacement_gt_5px" in row["flags"] or "interval_gt_5yr" in row["flags"]:
        return "implausible"
    bad = {"multiple_crossings", "width_below_min"}
    if bad & set(row["flags"]):
        return "flagged"
    if not row["center_inside_from"] or not row["center_inside_to"]:
        return "flagged"
    if "border_transect" in row["flags"]:
        return "flagged"
    return "good"


def run() -> dict:
    ensure_output_dirs()
    cfg = load_config()
    years = sorted(
        int(p.stem.split("_")[-1])
        for p in project_path("processed", "river").glob("river_*.tif")
    )
    years = [y for y in years if y <= int(cfg["training_cutoff_year"])]
    changes = change_maps(years)
    intervals = bank_intervals(years)
    good = intervals[intervals["quality"] == "good"]
    low = good["signed_displacement_m"].abs() <= float(cfg["labels"]["low_movement_tolerance_m"])
    low_counts = {
        "low_movement": int(low.sum()),
        "erosion": int(((good["signed_displacement_m"] > float(cfg["labels"]["low_movement_tolerance_m"])) & ~low).sum()),
        "accretion": int(((good["signed_displacement_m"] < -float(cfg["labels"]["low_movement_tolerance_m"])) & ~low).sum()),
    }
    summary = {
        "created_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "years": years,
        "intervals": len(years) - 1,
        "change_rows": int(len(changes)),
        "bank_interval_rows": int(len(intervals)),
        "bank_quality_counts": intervals["quality"].value_counts().to_dict(),
        "usable_bank_intervals": int((intervals["quality"] == "good").sum()),
        "good_interval_class_counts": low_counts,
        "sign_counts_all_valid": {
            "erosion_positive": int((intervals["signed_displacement_m"] > 0).sum()),
            "accretion_negative": int((intervals["signed_displacement_m"] < 0).sum()),
            "exact_zero": int((intervals["signed_displacement_m"] == 0).sum()),
        },
        "elapsed_days_range": [
            int(changes["elapsed_days"].min()),
            int(changes["elapsed_days"].max()),
        ],
        "change_area_summary_m2": {
            "erosion_total_raw": float(changes["erosion_area_m2_raw"].sum()),
            "accretion_total_raw": float(changes["accretion_area_m2_raw"].sum()),
            "erosion_total_filtered": float(changes["erosion_area_m2_filtered"].sum()),
            "accretion_total_filtered": float(changes["accretion_area_m2_filtered"].sum()),
        },
        "note": (
            "Land-to-water and water-to-land pixel transitions are potential erosion and accretion "
            "signals. They can be caused by water stage, seasonal wetness or classification error. "
            "They are not proof of sediment erosion or deposition."
        ),
    }
    write_json(project_path("derived", "measurements", "measurement_summary.json"), summary)
    _write_report(summary, changes, intervals)
    return summary


def _write_report(summary: dict, changes: pd.DataFrame, intervals: pd.DataFrame) -> None:
    lines = [
        "# Historical movement measurements (1989–2023)",
        "",
        "## Product A — pixel change maps",
        "",
        "For each consecutive pair of eligible observations, land→water is labelled **potential "
        "erosion** (+1) and water→land **potential accretion** (−1). Pixels invalid in either "
        "observation are nodata. Filtered maps remove connected patches smaller than "
        f"{int(changes['min_patch_px'].iloc[0])} pixels; raw and filtered maps "
        "are both saved.",
        "",
        "| Interval | Days | Erosion raw (m²) | Accretion raw (m²) | Erosion filtered (m²) | Accretion filtered (m²) |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for _, r in changes.iterrows():
        lines.append(
            f"| {int(r['from_year'])}→{int(r['to_year'])} | {int(r['elapsed_days'])} | "
            f"{r['erosion_area_m2_raw']:.0f} | {r['accretion_area_m2_raw']:.0f} | "
            f"{r['erosion_area_m2_filtered']:.0f} | {r['accretion_area_m2_filtered']:.0f} |"
        )
    lines += [
        "",
        "## Product B — bankline migration",
        "",
        "Bank displacement is measured along the fixed transect normal. Positive means outward, "
        "into land (erosion); negative means inward, toward the channel (accretion). The rate uses "
        "the nominal 25 March observation dates, so a missing year produces a two-year interval "
        "with two years of elapsed time rather than an assumed annual step.",
        "",
        f"- Raw bank-interval rows: {summary['bank_interval_rows']}",
        f"- Quality counts: {summary['bank_quality_counts']}",
        f"- Sign counts among valid intervals: {summary['sign_counts_all_valid']}",
        f"- Good intervals by class (±15 m tolerance): {summary['good_interval_class_counts']}",
        f"- Elapsed-day range: {summary['elapsed_days_range']}",
        "",
        "### Quality rules",
        "",
        "- `good`: both banks valid, no multiple crossings, width at least 60 m, centre inside the "
        "river in both years, not a border transect, displacement ≤150 m, interval ≤5 years.",
        "- `flagged`: valid but has a geometry warning (multiple crossings, centre outside, border).",
        "- `implausible`: displacement >150 m (5 pixels) or interval >5 years.",
        "- `invalid`: a bank intersection is missing.",
        "",
        "Raw rows are preserved. Filtered rows contain only `good` intervals. The large number of "
        "`flagged` early-year rows reflects the fixed 2023 transects versus a channel that was in a "
        "different position; it is a label-quality limitation, not a hidden correction.",
        "",
        "## Caveats",
        "",
        "Water-mask transitions alone do not prove sediment erosion or deposition. Water level, "
        "seasonal wetness, cloud and classification error can all create apparent change. The "
        "30 m pixel and the ±15 m low-movement tolerance are carried into the model evaluation.",
    ]
    project_path("reports", "historical_measurements.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    run()
