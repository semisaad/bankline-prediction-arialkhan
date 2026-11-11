from __future__ import annotations

import datetime as dt
from pathlib import Path

import numpy as np
import rasterio
from rasterio.features import shapes
from scipy import ndimage
from shapely.geometry import shape
from shapely.ops import unary_union
from skimage.measure import regionprops

from .config import ensure_output_dirs, load_config, project_path
from .io import (
    DataDefect,
    iter_historical_years,
    read_mask,
    sha256_file,
    write_geojson,
    write_json,
    write_mask,
)

EIGHT = np.ones((3, 3), dtype=int)


def _components(mask: np.ndarray):
    labels, n = ndimage.label(mask, structure=EIGHT)
    if n == 0:
        return labels, n, []
    props = {p.label: p for p in regionprops(labels)}
    return labels, n, props


def _elongation(prop) -> float:
    minor = float(prop.axis_minor_length if hasattr(prop, "axis_minor_length") else prop.minor_axis_length)
    major = float(prop.axis_major_length if hasattr(prop, "axis_major_length") else prop.major_axis_length)
    if minor <= 0:
        return float("inf") if major > 0 else 1.0
    return major / minor


def build_core(years: list[int]) -> tuple[np.ndarray, dict]:
    cfg = load_config()
    stack_w = []
    stack_v = []
    for year in years:
        water, valid, _ = read_mask(year, purpose="training")
        stack_w.append(water)
        stack_v.append(valid)
    water = np.stack(stack_w)
    valid = np.stack(stack_v)
    valid_count = valid.sum(axis=0)
    occurrence = water.sum(axis=0) / np.maximum(valid_count, 1)
    threshold = float(cfg["river_extraction"]["occurrence_min_fraction"])
    core = occurrence >= threshold
    labels, n, props = _components(core)
    if n == 0:
        raise DataDefect("No persistent water core could be built from the historical masks.")
    sizes = np.array([props[i].area for i in range(1, n + 1)])
    min_px = int(cfg["river_extraction"]["core_min_component_px"])
    candidates = [i for i in range(1, n + 1) if sizes[i - 1] >= min_px]
    if not candidates:
        raise DataDefect("Persistent core has no component above the minimum size.")
    main_label = max(candidates, key=lambda i: sizes[i - 1])
    core_main = labels == main_label
    info = {
        "years": years,
        "occurrence_threshold": threshold,
        "core_pixels": int(core.sum()),
        "core_components": int(n),
        "main_core_component_pixels": int(core_main.sum()),
        "main_core_component_label": int(main_label),
        "component_sizes": sorted([int(x) for x in sizes], reverse=True)[:20],
        "occurrence_min": float(occurrence.min()),
        "occurrence_max": float(occurrence.max()),
    }
    return core_main, info


def select_river(water: np.ndarray, valid: np.ndarray, core: np.ndarray) -> tuple[np.ndarray, dict]:
    cfg = load_config()["river_extraction"]
    m = water & valid
    labels, n, props = _components(m)
    if n == 0:
        raise DataDefect("No water components in this observation.")
    overlap = ndimage.sum(core, labels, index=np.arange(1, n + 1))
    areas = np.array([props[i].area if i in props else 0 for i in range(1, n + 1)])
    anchor_idx = int(np.argmax(overlap))
    anchor_label = anchor_idx + 1
    anchor_overlap = float(overlap[anchor_idx])
    fallback = False
    if anchor_overlap < float(cfg["anchor_min_overlap_px"]):
        anchor_idx = int(np.argmax(areas))
        anchor_label = anchor_idx + 1
        fallback = True
    selected_labels = {anchor_label}
    details = []
    anchor_mask = labels == anchor_label
    near = ndimage.binary_dilation(anchor_mask, structure=EIGHT, iterations=int(cfg["near_gap_px"]))
    for i in range(1, n + 1):
        prop = props.get(i)
        if prop is None:
            continue
        ov = float(overlap[i - 1])
        area = float(areas[i - 1])
        elong = _elongation(prop)
        near_anchor = bool((labels == i)[near].any()) or i == anchor_label
        reason = "anchor"
        include = i == anchor_label
        if not include:
            if ov >= float(cfg["component_overlap_min_px"]) and ov / max(area, 1) >= float(
                cfg["component_overlap_fraction_min"]
            ):
                include = True
                reason = "river_core_overlap"
            elif (
                near_anchor
                and area >= float(cfg["near_min_area_px"])
                and elong >= float(cfg["near_min_elongation"])
                and ov >= 5
            ):
                include = True
                reason = "near_anchor_elongated"
        if include:
            selected_labels.add(i)
        details.append(
            {
                "label": i,
                "area_px": int(area),
                "elongation": float(elong) if np.isfinite(elong) else "inf",
                "core_overlap_px": int(ov),
                "core_overlap_fraction": float(ov / max(area, 1)),
                "distance_band_to_anchor": near_anchor,
                "selected": include,
                "reason": reason if include else "excluded",
                "centroid_row_col": [float(prop.centroid[0]), float(prop.centroid[1])],
                "bbox": [int(x) for x in prop.bbox],
            }
        )
    selected = np.isin(labels, list(selected_labels))
    selected = selected & valid
    excluded = m & ~selected
    selected_part_count = len(selected_labels)
    info = {
        "components_total": int(n),
        "water_pixels": int(m.sum()),
        "selected_pixels": int(selected.sum()),
        "excluded_pixels": int(excluded.sum()),
        "selected_component_count": int(selected_part_count),
        "anchor_label": int(anchor_label),
        "anchor_area_px": int(areas[anchor_idx]),
        "anchor_core_overlap_px": int(overlap[anchor_idx]),
        "anchor_fallback_used": fallback,
        "selected_is_single_connected_component": bool(selected_part_count == 1),
        "components": sorted(details, key=lambda d: d["area_px"], reverse=True),
    }
    return selected, info


def polygonize(mask: np.ndarray, transform) -> tuple[object, dict]:
    if not mask.any():
        raise DataDefect("Cannot polygonize an empty river mask.")
    geoms = []
    for geom, value in shapes(mask.astype("uint8"), mask=mask, connectivity=8, transform=transform):
        if value == 1:
            geoms.append(shape(geom))
    if not geoms:
        raise DataDefect("Polygonization returned no geometry.")
    merged = unary_union(geoms)
    info = {
        "polygon_valid_raw": bool(merged.is_valid),
        "polygon_empty": bool(merged.is_empty),
        "repair_applied": False,
        "repair_reason": None,
        "area_m2_raw": float(merged.area),
    }
    if not merged.is_valid:
        repaired = merged.buffer(0)
        info["repair_applied"] = True
        info["repair_reason"] = "polygon was invalid; buffer(0) applied and recorded"
        info["area_m2_repaired"] = float(repaired.area)
        merged = repaired
    return merged, info


def _plot_year(year: int, water: np.ndarray, valid: np.ndarray, selected: np.ndarray, excluded: np.ndarray, core: np.ndarray) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(6.2, 8.2))
    rgb = np.zeros((*water.shape, 3), dtype=float)
    rgb[valid] = (0.93, 0.93, 0.93)
    rgb[water & valid] = (0.45, 0.68, 0.88)
    rgb[excluded] = (0.95, 0.55, 0.10)
    rgb[selected] = (0.05, 0.25, 0.55)
    ax.imshow(rgb, interpolation="nearest")
    ax.contour(core.astype(float), levels=[0.5], colors=["#19a974"], linewidths=0.6)
    ax.set_title(f"{year}: selected river (dark blue), excluded water (orange), historical core (green)")
    ax.set_xticks([])
    ax.set_yticks([])
    fig.tight_layout()
    out = project_path("processed", "qa", f"river_extraction_{year}.png")
    fig.savefig(out, dpi=110)
    plt.close(fig)


def run() -> dict:
    ensure_output_dirs()
    cfg = load_config()
    years = iter_historical_years()
    core, core_info = build_core(years)
    np.savez_compressed(
        project_path("processed", "river", "river_core.npz"),
        core=core,
        years=np.array(years),
    )
    write_json(project_path("processed", "river", "river_core.json"), core_info)

    with rasterio.open(project_path("processed", "masks", f"water_{years[0]}.tif")) as src:
        transform = src.transform
        crs = src.crs

    records = []
    masks = {}
    for year in years:
        water, valid, _ = read_mask(year, purpose="training")
        selected, info = select_river(water, valid, core)
        masks[year] = selected
        excluded = water & valid & ~selected
        out_mask = project_path("processed", "river", f"river_{year}.tif")
        write_mask(out_mask, selected, valid)
        write_mask(project_path("processed", "river", f"excluded_{year}.tif"), excluded, valid)
        poly, poly_info = polygonize(selected, transform)
        area_px = int(selected.sum())
        info.update(
            {
                "year": year,
                "area_px": area_px,
                "area_m2": float(area_px * 30.0 * 30.0),
                "polygon_area_m2": float(poly.area),
                "mask_sha256": sha256_file(out_mask),
                "polygon": poly_info,
            }
        )
        write_geojson(
            project_path("processed", "river", f"river_{year}.geojson"),
            [
                {
                    "geometry": poly,
                    "properties": {
                        "year": year,
                        "area_m2": float(poly.area),
                        "selected_pixels": area_px,
                        "excluded_water_pixels": int(excluded.sum()),
                        "anchor_fallback": info["anchor_fallback_used"],
                    },
                }
            ],
            crs=crs.to_string(),
        )
        _plot_year(year, water, valid, selected, excluded, core)
        write_json(project_path("processed", "river", f"components_{year}.json"), info)
        records.append(info)

    areas = np.array([r["area_px"] for r in records], dtype=float)
    median_area = float(np.median(areas))
    cfg_ext = cfg["river_extraction"]
    for rec in records:
        frac = rec["area_px"] / median_area if median_area else 0.0
        flags = []
        if rec["anchor_fallback_used"]:
            flags.append("largest_component_fallback")
        if not rec["selected_is_single_connected_component"]:
            flags.append("multiple_selected_components")
        if frac < float(cfg_ext["min_selected_fraction_of_median"]):
            flags.append("river_area_below_expected")
        if frac > float(cfg_ext["max_selected_fraction_of_median"]):
            flags.append("river_area_above_expected")
        if abs(frac - 1.0) > float(cfg_ext["area_jump_flag_fraction"]):
            flags.append("river_area_jump")
        rec["area_fraction_of_median"] = frac
        rec["flags"] = flags
        write_json(project_path("processed", "river", f"components_{rec['year']}.json"), rec)

    summary = {
        "created_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "core": core_info,
        "years": years,
        "median_river_area_px": median_area,
        "median_river_area_m2": median_area * 900.0,
        "total_excluded_pixels": int(sum(r["excluded_pixels"] for r in records)),
        "flagged_years": {str(r["year"]): r["flags"] for r in records if r["flags"]},
        "records": records,
    }
    write_json(project_path("processed", "river", "extraction_summary.json"), summary)
    _write_report(summary)
    return summary


def _write_report(summary: dict) -> None:
    lines = [
        "# Main-river extraction (training period)",
        "",
        "The masks contain the river plus detached ponds and small wet slivers. The extraction is "
        "an explicit two-stage rule based only on 1989–2023 observations:",
        "",
        "1. Build a persistent-water **core** from the fraction of historical years in which each "
        f"valid pixel is water (threshold {summary['core']['occurrence_threshold']:.2f}). Keep the "
        "largest 8-connected core component (the river network).",
        "2. In each year, label all 8-connected water components. Select the component with the "
        "largest overlap with the core (the anchor). Also select a detached component only if it "
        "overlaps the core substantially (at least 20 px and 10% of its own area) or is within "
        "2 px of the anchor and is elongated. All other components are excluded and retained in "
        "the diagnostic layer.",
        "",
        "The largest-component rule is not used by itself. It is only a fallback if no component "
        "overlaps the historical core, and that fallback is flagged.",
        "",
        f"- Historical years used: {summary['years'][0]}–{summary['years'][-1]} ({len(summary['years'])} observations)",
        f"- Core pixels: {summary['core']['core_pixels']}",
        f"- Main core component: {summary['core']['main_core_component_pixels']} px",
        f"- Median selected river area: {summary['median_river_area_px']:.0f} px "
        f"({summary['median_river_area_m2']/1e6:.3f} km²)",
        "",
        "## Per-year selection",
        "",
        "| Year | Selected px | Excluded px | Components selected | Anchor fallback | Flags |",
        "|---:|---:|---:|---:|---|---|",
    ]
    for r in summary["records"]:
        lines.append(
            f"| {r['year']} | {r['selected_pixels']} | {r['excluded_pixels']} | "
            f"{r['selected_component_count']} | {r['anchor_fallback_used']} | "
            f"{', '.join(r['flags']) or 'none'} |"
        )
    lines += [
        "",
        "## Interpretation and limits",
        "",
        "- Connected side channels and braided water are kept because they are part of the anchor "
        "component. Detached oxbows/channel fragments that retain a strong overlap with the "
        "historical core are kept as separate selected components; this is recorded per year.",
        "- Detached ponds are excluded even when they are large. The excluded layer is saved for "
        "every year so a reviewer can inspect what was removed.",
        "- If two water systems are joined by flooding in one year, the 8-connected anchor can "
        "include the joined water. Such a year is flagged by an area jump; the joined water is not "
        "silently relabelled as a separate pond.",
        "- The extraction configuration is fixed before any 2024–2026 raster is opened.",
    ]
    project_path("reports", "river_extraction.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    run()
