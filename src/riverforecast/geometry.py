from __future__ import annotations

import heapq
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
from shapely.geometry import LineString, MultiPoint, Point, Polygon
from shapely.ops import linemerge

from .config import ensure_output_dirs, load_config, project_path
from .extract import polygonize
from .io import read_river_mask, write_geojson, write_json


@dataclass
class Transect:
    transect_id: int
    center_x: float
    center_y: float
    tangent_x: float
    tangent_y: float
    normal_x: float
    normal_y: float
    along_m: float
    line: LineString
    reach: str = ""
    border: bool = False


def _skeleton_path(mask: np.ndarray) -> list[tuple[int, int]]:
    from skimage.morphology import skeletonize

    sk = skeletonize(mask)
    if sk.sum() < 50:
        raise RuntimeError("River skeleton is too small to build a centerline.")
    labels = np.zeros_like(sk, dtype=int)
    from scipy import ndimage

    labels, n = ndimage.label(sk, structure=np.ones((3, 3), int))
    if n > 1:
        sizes = ndimage.sum(sk, labels, range(1, n + 1))
        sk = labels == (int(np.argmax(sizes)) + 1)
    pts = [tuple(int(v) for v in p) for p in np.argwhere(sk)]
    point_set = set(pts)
    index = {p: i for i, p in enumerate(pts)}

    def neighbours(p):
        r, c = p
        for dr in (-1, 0, 1):
            for dc in (-1, 0, 1):
                if dr == 0 and dc == 0:
                    continue
                q = (r + dr, c + dc)
                if q in point_set:
                    yield q, (math.sqrt(2.0) if dr and dc else 1.0)

    starts = [p for p in pts if p[0] == min(x[0] for x in pts)]
    ends = [p for p in pts if p[0] == max(x[0] for x in pts)]
    if not starts or not ends:
        raise RuntimeError("Could not find north/south skeleton endpoints.")
    start = min(starts, key=lambda p: abs(p[1] - mask.shape[1] / 2))
    end = min(ends, key=lambda p: abs(p[1] - mask.shape[1] / 2))
    dist = {start: 0.0}
    prev: dict[tuple[int, int], tuple[int, int]] = {}
    heap = [(0.0, start)]
    while heap:
        d, u = heapq.heappop(heap)
        if d != dist[u]:
            continue
        if u == end:
            break
        for v, w in neighbours(u):
            nd = d + w
            if nd < dist.get(v, 1e18):
                dist[v] = nd
                prev[v] = u
                heapq.heappush(heap, (nd, v))
    if end not in dist:
        raise RuntimeError("Skeleton graph does not connect the north and south river ends.")
    path = [end]
    while path[-1] != start:
        path.append(prev[path[-1]])
    return path[::-1]


def _resample_path(path: list[tuple[int, int]], spacing_px: float, transform):
    xy = np.array([rasterio.transform.xy(transform, r, c, offset="center") for r, c in path], dtype=float)
    seg = np.hypot(np.diff(xy[:, 0]), np.diff(xy[:, 1]))
    cum = np.concatenate([[0.0], np.cumsum(seg)])
    targets = np.arange(0.0, cum[-1] + 1e-9, spacing_px * abs(transform.a))
    out = []
    for t in targets:
        i = int(np.searchsorted(cum, t) - 1)
        i = max(0, min(i, len(xy) - 2))
        frac = (t - cum[i]) / max(cum[i + 1] - cum[i], 1e-9)
        out.append(xy[i] + frac * (xy[i + 1] - xy[i]))
    return np.asarray(out), cum[-1]


def build_transects(year: int | None = None) -> list[Transect]:
    cfg = load_config()
    ref_year = int(year or cfg["transects"]["reference_year"])
    mask, valid = read_river_mask(ref_year)
    path = _skeleton_path(mask & valid)
    with rasterio.open(project_path("processed", "river", f"river_{ref_year}.tif")) as src:
        transform = src.transform
    spacing = float(cfg["transects"]["spacing_px"])
    half = float(cfg["transects"]["half_length_m"])
    centers, total_len = _resample_path(path, spacing, transform)
    transects: list[Transect] = []
    for i, p in enumerate(centers):
        lo = max(0, i - 2)
        hi = min(len(centers) - 1, i + 2)
        tangent = centers[hi] - centers[lo]
        norm = float(np.hypot(*tangent))
        if norm < 1e-9:
            continue
        tangent = tangent / norm
        # Left of downstream flow.
        normal = np.array([-tangent[1], tangent[0]])
        line = LineString(
            [
                (p[0] - normal[0] * half, p[1] - normal[1] * half),
                (p[0] + normal[0] * half, p[1] + normal[1] * half),
            ]
        )
        transects.append(
            Transect(
                transect_id=len(transects) + 1,
                center_x=float(p[0]),
                center_y=float(p[1]),
                tangent_x=float(tangent[0]),
                tangent_y=float(tangent[1]),
                normal_x=float(normal[0]),
                normal_y=float(normal[1]),
                along_m=float(i * spacing * abs(transform.a)),
                line=line,
            )
        )
    if len(transects) < 10:
        raise RuntimeError(f"Only {len(transects)} transects were built; too few for modelling.")
    n = len(transects)
    border_n = int(cfg["transects"]["border_transects"])
    for i, t in enumerate(transects):
        t.reach = ["north", "middle", "south"][min(2, int(3 * i / n))]
        t.border = i < border_n or i >= n - border_n
    return transects


def _boundary_lines(poly) -> list[LineString]:
    polys = [poly] if poly.geom_type == "Polygon" else list(poly.geoms)
    lines = []
    for p in polys:
        lines.append(p.exterior)
        lines.extend(list(p.interiors))
    return lines


def _point_parts(geom) -> list[Point]:
    if geom.is_empty:
        return []
    if geom.geom_type == "Point":
        return [geom]
    if geom.geom_type in {"MultiPoint", "GeometryCollection"}:
        out = []
        for g in geom.geoms:
            out.extend(_point_parts(g))
        return out
    return []


def _curvature_at(point: Point, lines: list[LineString], window_m: float = 120.0) -> tuple[float, float]:
    if not lines:
        return float("nan"), float("nan")
    nearest = min(lines, key=lambda ln: ln.distance(point))
    s = nearest.project(point)
    offsets = np.linspace(-window_m, window_m, 9)
    pts = []
    for off in offsets:
        ss = min(max(s + off, 0.0), nearest.length)
        q = nearest.interpolate(ss)
        pts.append((q.x, q.y))
    pts = np.asarray(pts, dtype=float)
    t = offsets / max(window_m, 1.0)
    if np.ptp(pts[:, 0]) < 1e-6 and np.ptp(pts[:, 1]) < 1e-6:
        return float("nan"), float("nan")
    try:
        cx = np.polyfit(t, pts[:, 0], 2)
        cy = np.polyfit(t, pts[:, 1], 2)
        dx, ddx = cx[1], 2 * cx[0]
        dy, ddy = cy[1], 2 * cy[0]
        denom = (dx * dx + dy * dy) ** 1.5
        if denom < 1e-12:
            return float("nan"), float("nan")
        k = (dx * ddy - dy * ddx) / denom
        # Convert from per-scaled-t to per-metre. t = offset/window, so divide by window.
        k = k / window_m
        radius = abs(1.0 / k) if abs(k) > 1e-12 else float("inf")
        return float(k), float(radius)
    except Exception:  # noqa: BLE001
        return float("nan"), float("nan")


def bank_positions(year: int, transects: list[Transect], poly) -> list[dict]:
    cfg = load_config()
    boundary = poly.boundary
    lines = _boundary_lines(poly)
    rows = []
    low_tol = float(cfg["transects"]["min_width_m"])
    for t in transects:
        inter = t.line.intersection(boundary)
        pts = _point_parts(inter)
        # Deduplicate points (a corner can be returned twice).
        unique = []
        for p in pts:
            if not any(p.distance(q) < 1e-6 for q in unique):
                unique.append(p)
        crossings = len(unique)
        ds = [
            ((p.x - t.center_x) * t.normal_x + (p.y - t.center_y) * t.normal_y, p)
            for p in unique
        ]
        center_inside = bool(poly.contains(Point(t.center_x, t.center_y)))
        # Use the two outermost crossings as the outer banks of the selected river
        # corridor. This keeps a bank measurable when the channel has shifted across
        # the fixed 2023 reference centre. Multiple crossings remain flagged.
        sides = {"L": None, "R": None}
        if ds:
            sides["L"] = max(ds, key=lambda x: x[0])[1]
            sides["R"] = min(ds, key=lambda x: x[0])[1]
            if sides["L"].distance(sides["R"]) < 1e-6:
                sides["R"] = None
        width = float("nan")
        if sides["L"] is not None and sides["R"] is not None:
            width = float(sides["L"].distance(sides["R"]))
        for side in ["L", "R"]:
            p = sides[side]
            flags = []
            if p is None:
                flags.append("missing_bank")
            if crossings > int(cfg["transects"]["max_crossings_warn"]):
                flags.append("multiple_crossings")
            if not center_inside:
                flags.append("center_outside_river")
            if not np.isnan(width) and width < low_tol:
                flags.append("width_below_min")
            if t.border:
                flags.append("border_transect")
            kappa, radius = (float("nan"), float("nan")) if p is None else _curvature_at(p, lines)
            if p is not None and abs(kappa) > 0.02:
                flags.append("high_bank_curvature")
            rows.append(
                {
                    "year": int(year),
                    "transect_id": t.transect_id,
                    "side": side,
                    "outward_sign": 1.0 if side == "L" else -1.0,
                    "reach": t.reach,
                    "along_m": t.along_m,
                    "center_x": t.center_x,
                    "center_y": t.center_y,
                    "normal_x": t.normal_x,
                    "normal_y": t.normal_y,
                    "bank_x": float(p.x) if p is not None else np.nan,
                    "bank_y": float(p.y) if p is not None else np.nan,
                    "bank_dist_m": float((p.x - t.center_x) * t.normal_x + (p.y - t.center_y) * t.normal_y) if p is not None else np.nan,
                    "width_m": width,
                    "curvature_1_m": kappa,
                    "curve_radius_m": radius,
                    "crossings": crossings,
                    "center_inside": center_inside,
                    "border_transect": t.border,
                    "flags": flags,
                    "valid_bank": p is not None,
                }
            )
    return rows


def add_sinuosity(df: pd.DataFrame) -> pd.DataFrame:
    # Sinuosity of the origin-year bankline over a five-transect window on each side.
    df = df.copy()
    df["sinuosity"] = np.nan
    for (year, side), grp in df.groupby(["year", "side"], sort=False):
        grp = grp.sort_values("transect_id")
        for idx, row in grp.iterrows():
            if not row["valid_bank"]:
                continue
            window = grp[(grp["transect_id"] >= row["transect_id"] - 5) & (grp["transect_id"] <= row["transect_id"] + 5)]
            window = window[window["valid_bank"]]
            if len(window) < 3:
                continue
            x = window["bank_x"].to_numpy()
            y = window["bank_y"].to_numpy()
            path_len = float(np.hypot(np.diff(x), np.diff(y)).sum())
            straight = float(np.hypot(x[-1] - x[0], y[-1] - y[0]))
            if straight > 1e-6:
                df.at[idx, "sinuosity"] = path_len / straight
    return df


def extract_all() -> dict:
    ensure_output_dirs()
    cfg = load_config()
    years = sorted(
        int(p.stem.split("_")[-1])
        for p in project_path("processed", "river").glob("river_*.tif")
    )
    years = [y for y in years if y <= int(cfg["training_cutoff_year"])]
    transects = build_transects()
    frames = []
    for year in years:
        water, valid = read_river_mask(year)
        with rasterio.open(project_path("processed", "river", f"river_{year}.tif")) as src:
            transform = src.transform
            crs = src.crs
        poly, poly_info = polygonize(water & valid, transform)
        rows = bank_positions(year, transects, poly)
        frames.append(pd.DataFrame(rows))
        boundary_lines = _boundary_lines(poly)
        features = [
            {
                "geometry": geom,
                "properties": {
                    "year": year,
                    "bank_type": "exterior" if i == 0 else "interior",
                    "length_m": float(geom.length),
                },
            }
            for i, geom in enumerate(boundary_lines)
        ]
        write_geojson(project_path("derived", "banklines", f"banklines_{year}.geojson"), features, crs=crs.to_string())
        write_json(
            project_path("derived", "banklines", f"banklines_{year}_meta.json"),
            {
                "year": year,
                "polygon": poly_info,
                "boundary_lines": len(boundary_lines),
                "boundary_length_m": float(sum(g.length for g in boundary_lines)),
                "area_m2": float(poly.area),
            },
        )
    df = pd.concat(frames, ignore_index=True)
    df = add_sinuosity(df)
    df["observation_date"] = [f"{int(y)}-03-25" for y in df["year"]]
    df.to_csv(project_path("derived", "measurements", "bank_positions.csv"), index=False)

    tdf = pd.DataFrame(
        [
            {
                "transect_id": t.transect_id,
                "along_m": t.along_m,
                "center_x": t.center_x,
                "center_y": t.center_y,
                "tangent_x": t.tangent_x,
                "tangent_y": t.tangent_y,
                "normal_x": t.normal_x,
                "normal_y": t.normal_y,
                "reach": t.reach,
                "border_transect": t.border,
                "line_coords": [list(map(float, c)) for c in t.line.coords],
            }
            for t in transects
        ]
    )
    tdf.to_csv(project_path("derived", "transects.csv"), index=False)
    write_geojson(
        project_path("derived", "transects.geojson"),
        [
            {
                "geometry": t.line,
                "properties": {
                    "transect_id": t.transect_id,
                    "along_m": t.along_m,
                    "reach": t.reach,
                    "border_transect": t.border,
                    "center_x": t.center_x,
                    "center_y": t.center_y,
                },
            }
            for t in transects
        ],
        crs="EPSG:32646",
    )
    summary = {
        "reference_year": cfg["transects"]["reference_year"],
        "spacing_px": cfg["transects"]["spacing_px"],
        "spacing_m": cfg["transects"]["spacing_px"] * cfg["canonical_grid"]["resolution_m"],
        "n_transects": len(transects),
        "n_bank_rows": int(len(df)),
        "years": years,
        "valid_bank_rows": int(df["valid_bank"].sum()),
        "missing_bank_rows": int((~df["valid_bank"]).sum()),
        "flag_counts": {
            flag: int(df["flags"].apply(lambda fs: flag in fs).sum())
            for flag in sorted({f for fs in df["flags"] for f in fs})
        },
        "width_m_summary": {
            "min": float(df["width_m"].min()),
            "median": float(df["width_m"].median()),
            "max": float(df["width_m"].max()),
        },
    }
    write_json(project_path("derived", "measurements", "bank_position_summary.json"), summary)
    _write_report(summary, df)
    return summary


def _write_report(summary: dict, df: pd.DataFrame) -> None:
    lines = [
        "# Bankline and transect construction (training period)",
        "",
        f"- Reference year for fixed transects: {summary['reference_year']} (last pre-cutoff observation).",
        f"- Spacing along the channel: {summary['spacing_m']:.0f} m ({summary['spacing_px']} pixels).",
        f"- Transects: {summary['n_transects']}.",
        f"- Bank-position rows: {summary['n_bank_rows']} ({summary['valid_bank_rows']} valid single-bank rows).",
        "",
        "Transects are perpendicular to a pruned 2023 channel skeleton and are fixed for every "
        "historical observation. Each transect has a left (`L`) and right (`R`) bank. The normal "
        "points from the channel to the left bank when facing downstream. A bank point is the "
        "outermost intersection of the transect with the selected river polygon on that side. "
        "This preserves the outer bank of the river corridor if a side channel or island is present, "
        "and the extra crossings are flagged.",
        "",
        "## Sign convention",
        "",
        "Positive signed displacement means the bank moved **outward**, away from the channel and "
        "into land: **erosion**. Negative means the bank moved **inward**, toward the channel: "
        "**accretion**. The same convention is applied to left and right banks.",
        "",
        "## Quality flags",
        "",
        "| Flag | Rows |",
        "|---|---:|",
    ]
    for flag, count in summary["flag_counts"].items():
        lines.append(f"| {flag} | {count} |")
    lines += [
        "",
        f"Width summary (m): min {summary['width_m_summary']['min']:.1f}, median "
        f"{summary['width_m_summary']['median']:.1f}, max {summary['width_m_summary']['max']:.1f}.",
        "",
        "Missing banks, multiple crossings, centres outside the river and implausibly narrow widths "
        "are retained in the raw table and flagged. They are excluded from model labels later.",
    ]
    project_path("reports", "bankline_transects.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    extract_all()
