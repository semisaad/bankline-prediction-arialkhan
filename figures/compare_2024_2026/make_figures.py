from __future__ import annotations

import gc
import math
from pathlib import Path

import geopandas as gpd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
import pandas as pd
from matplotlib.collections import LineCollection
from matplotlib.colors import BoundaryNorm, ListedColormap
from matplotlib.lines import Line2D
from matplotlib.patches import Patch, Rectangle
from PIL import Image

from common import (
    BOUNDARY_TOL_M,
    COLORS,
    CONNECTOR_LW,
    FIGURE_DPI,
    OBSERVED_LINE_PX,
    OUT,
    SECTION_MARGIN_M,
    START_LINE_ALPHA,
    START_LINE_PX,
    YEARS,
    changed_place_lines,
    overview_box_lines,
    px_to_pt,
    rel,
    section_bounds,
)

plt.rcParams.update(
    {
        "font.size": 14,
        "axes.titlesize": 20,
        "axes.labelsize": 14,
        "xtick.labelsize": 14,
        "ytick.labelsize": 14,
        "legend.fontsize": 14,
        "figure.facecolor": "white",
        "axes.facecolor": "white",
        "savefig.facecolor": "white",
    }
)


def setup_figure(figsize: tuple[float, float]):
    return plt.figure(figsize=figsize, dpi=FIGURE_DPI)


def map_handles() -> list:
    return [
        Patch(facecolor=COLORS["water"], edgecolor="none", label="Observed-year water mask"),
        Line2D(
            [0], [0], color=COLORS["start"], lw=px_to_pt(START_LINE_PX),
            alpha=START_LINE_ALPHA, label="2023 bank boundary (zero change)",
        ),
        Line2D([0], [0], color=COLORS["observed"], lw=px_to_pt(OBSERVED_LINE_PX), label="Observed mask boundary"),
        Line2D([0], [0], color=COLORS["forecast"], lw=2.4, ls="--", label="Forecast bank"),
        Line2D([0], [0], color=COLORS["green"], lw=CONNECTOR_LW, label="Connector: forecast closer"),
        Line2D([0], [0], color=COLORS["red"], lw=CONNECTOR_LW, label="Connector: forecast farther"),
        Line2D([0], [0], color=COLORS["grey"], lw=CONNECTOR_LW, label="Connector: both <= 15 m / tie"),
        Line2D([0], [0], marker="o", color="none", markerfacecolor="black", markeredgecolor="black", markersize=5, label="Observed bank point"),
        Line2D([0], [0], marker="o", color="none", markerfacecolor="none", markeredgecolor="black", markersize=7, markeredgewidth=1.2, label="Flagged/invalid bank (hollow)"),
        Line2D([0], [0], marker="o", color="none", markerfacecolor="none", markeredgecolor=COLORS["forecast"], markersize=7, markeredgewidth=1.2, label="Flagged forecast origin (hollow)"),
    ]


def draw_base_map(ax, mask: dict, bounds: dict[str, float], title: str = "") -> None:
    left, right = bounds["left"], bounds["right"]
    bottom, top = bounds["bottom"], bounds["top"]
    ax.imshow(
        mask["water"].astype(float),
        cmap=ListedColormap(["#ffffff", COLORS["water"]]),
        vmin=0,
        vmax=1,
        origin="upper",
        extent=(mask["bounds"][0], mask["bounds"][2], mask["bounds"][1], mask["bounds"][3]),
        interpolation="nearest",
        zorder=0,
        aspect="auto",
    )
    ax.set_xlim(left, right)
    ax.set_ylim(bottom, top)
    ax.set_aspect("equal", adjustable="box")
    if title:
        ax.set_title(title, fontsize=22, pad=12)
    ax.set_xlabel("UTM easting (km)")
    ax.set_ylabel("UTM northing (km)")
    ax.xaxis.set_major_locator(mticker.MultipleLocator(1000))
    ax.yaxis.set_major_locator(mticker.MultipleLocator(1000))
    ax.xaxis.set_major_formatter(mticker.FuncFormatter(lambda v, pos: f"{v / 1000:.0f}"))
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, pos: f"{v / 1000:.0f}"))
    ax.grid(True, which="major", color="#b0b0b0", linewidth=0.4, alpha=0.7, zorder=1)
    ax.tick_params(labelsize=14)
    for spine in ax.spines.values():
        spine.set_linewidth(1.0)


def draw_boundary(ax, rings: list, color: str, linewidth: float, zorder: int, alpha: float = 1.0) -> None:
    segments = [np.asarray(ring.coords) for ring in rings]
    ax.add_collection(
        LineCollection(segments, colors=color, linewidths=linewidth, zorder=zorder, alpha=alpha)
    )


def draw_transect_labels(ax, transects: pd.DataFrame, bounds: dict[str, float], fontsize: int = 14) -> None:
    for tid in range(5, 76, 5):
        row = transects[transects["transect_id"] == tid]
        if row.empty:
            continue
        x = float(row["center_x"].iloc[0])
        y = float(row["center_y"].iloc[0])
        if not (bounds["left"] <= x <= bounds["right"] and bounds["bottom"] <= y <= bounds["top"]):
            continue
        ax.text(
            x,
            y + 110,
            f"T{tid:03d}",
            fontsize=fontsize,
            ha="center",
            va="bottom",
            zorder=12,
            bbox=dict(facecolor="white", edgecolor="none", alpha=0.78, pad=0.15),
        )


def draw_scale_north(ax, bounds: dict[str, float]) -> None:
    dx = bounds["right"] - bounds["left"]
    dy = bounds["top"] - bounds["bottom"]
    x0 = bounds["left"] + 0.055 * dx
    y0 = bounds["bottom"] + 0.045 * dy
    ax.plot([x0, x0 + 500], [y0, y0], color="black", linewidth=4, solid_capstyle="butt", zorder=20)
    ax.text(
        x0 + 250,
        y0 + 0.012 * dy,
        "500 m",
        fontsize=14,
        ha="center",
        va="bottom",
        zorder=20,
        bbox=dict(facecolor="white", edgecolor="none", alpha=0.85, pad=0.15),
    )
    ax.annotate(
        "",
        xy=(0.945, 0.965),
        xytext=(0.945, 0.875),
        xycoords="axes fraction",
        arrowprops=dict(facecolor="black", edgecolor="black", width=2.0, headwidth=10, headlength=12),
        zorder=21,
    )
    ax.text(
        0.945,
        0.970,
        "N",
        transform=ax.transAxes,
        fontsize=16,
        ha="center",
        va="bottom",
        zorder=21,
        bbox=dict(facecolor="white", edgecolor="none", alpha=0.8, pad=0.1),
    )


def draw_frame(
    ax,
    mask: dict,
    transects: pd.DataFrame,
    forecast_lines: gpd.GeoDataFrame,
    forecast_points: gpd.GeoDataFrame,
    pred: pd.DataFrame,
    year: int,
    bounds: dict[str, float],
    start_mask: dict,
    linewidth_scale: float,
    point_size: float,
    label_size: int,
    title: str = "",
    include_forecast: bool = True,
    include_forecast_points: bool = True,
    include_connectors: bool = True,
    connector_exaggeration: float = 1.0,
    connector_lw: float = CONNECTOR_LW,
) -> None:
    draw_base_map(ax, mask, bounds, title)
    draw_boundary(ax, start_mask["rings"], COLORS["start"], px_to_pt(START_LINE_PX), 2, START_LINE_ALPHA)
    draw_boundary(ax, mask["rings"], COLORS["observed"], px_to_pt(OBSERVED_LINE_PX), 3)
    if include_forecast:
        for _, row in forecast_lines.iterrows():
            x, y = row.geometry.xy
            ax.plot(
                x,
                y,
                color=COLORS["halo"],
                linewidth=5.2 * linewidth_scale,
                solid_capstyle="round",
                zorder=4,
            )
            ax.plot(
                x,
                y,
                color=COLORS["forecast"],
                linewidth=2.5 * linewidth_scale,
                linestyle="--",
                solid_capstyle="round",
                zorder=5,
            )
    valid = pred[pred["valid"]]
    if include_connectors:
        segments = []
        colors = []
        for _, row in valid.iterrows():
            ox = float(row["observed_bank_x"])
            oy = float(row["observed_bank_y"])
            fx = float(row["forecast_bank_x"])
            fy = float(row["forecast_bank_y"])
            segments.append(
                [
                    (ox + (fx - ox) * connector_exaggeration, oy + (fy - oy) * connector_exaggeration),
                    (ox, oy),
                ]
            )
            colors.append(COLORS[row["connector"]])
        if segments:
            ax.add_collection(
                LineCollection(segments, colors=colors, linewidths=connector_lw, zorder=7.5, alpha=0.95)
            )
    ax.scatter(
        valid["observed_bank_x"],
        valid["observed_bank_y"],
        s=point_size,
        c="black",
        edgecolors="none",
        zorder=8,
    )
    flagged = pred[~pred["valid"]]
    if len(flagged):
        fx = flagged["observed_bank_x"].to_numpy()
        fy = flagged["observed_bank_y"].to_numpy()
        finite = np.isfinite(fx) & np.isfinite(fy)
        ax.scatter(
            fx[finite],
            fy[finite],
            s=point_size * 2.2,
            facecolors="none",
            edgecolors="black",
            linewidths=1.1,
            zorder=9,
        )
    if include_forecast_points:
        fpx = forecast_points.geometry.x.to_numpy()
        fpy = forecast_points.geometry.y.to_numpy()
        ax.scatter(fpx, fpy, s=point_size * 0.45, c=COLORS["forecast"], edgecolors="none", zorder=6.5, alpha=0.8)
        fflags = forecast_points[forecast_points["forecast_quality"] != "forecast"]
        if len(fflags):
            ax.scatter(
                fflags.geometry.x,
                fflags.geometry.y,
                s=point_size * 2.0,
                facecolors="none",
                edgecolors=COLORS["forecast"],
                linewidths=1.0,
                zorder=6.5,
            )
    draw_transect_labels(ax, transects, bounds, fontsize=label_size)
    draw_scale_north(ax, bounds)


def add_legend(fig, handles: list, anchor: tuple[float, float] = (0.735, 0.90)) -> None:
    fig.legend(
        handles=handles,
        loc="upper left",
        bbox_to_anchor=anchor,
        frameon=False,
        fontsize=14,
        borderaxespad=0.0,
        handlelength=2.4,
        labelspacing=0.55,
    )


def save_figure(fig, path: Path) -> None:
    fig.savefig(path, dpi=FIGURE_DPI)
    plt.close(fig)
    gc.collect()


def add_legend_bottom(fig) -> None:
    fig.legend(
        handles=map_handles(),
        loc="lower center",
        bbox_to_anchor=(0.5, 0.003),
        ncol=4,
        frameon=False,
        fontsize=12.5,
        handlelength=2.3,
        columnspacing=1.8,
        labelspacing=0.35,
    )


def draw_overview(
    year: int,
    mask: dict,
    start_mask: dict,
    data: dict,
    bounds: dict[str, float],
    overview_stats: pd.DataFrame,
) -> Path:
    stats = overview_stats[overview_stats["year"] == year]
    if len(stats) != 1:
        raise RuntimeError(f"Expected one overview stats row for {year}")
    stats = stats.iloc[0]
    path = OUT / f"overview_{year}.png"
    fig = setup_figure((36, 27))
    ax_true = fig.add_axes([0.025, 0.075, 0.455, 0.78])
    ax_exag = fig.add_axes([0.520, 0.075, 0.455, 0.78])
    pred = data["pred"][data["pred"]["year"] == year]
    draw_frame(
        ax_true,
        mask,
        data["transects"],
        data["forecast_lines"][year],
        data["forecast_points"][year],
        pred,
        year,
        bounds,
        start_mask,
        0.9,
        11,
        12,
        "True scale",
    )
    draw_frame(
        ax_exag,
        mask,
        data["transects"],
        data["forecast_lines"][year],
        data["forecast_points"][year],
        pred,
        year,
        bounds,
        start_mask,
        0.9,
        11,
        12,
        "error exaggerated 5x",
        include_forecast=False,
        include_forecast_points=False,
        connector_exaggeration=5.0,
    )
    ax_exag.text(
        0.012,
        0.018,
        "Connector lengths ×5; observed points are true locations; endpoints are illustrative",
        transform=ax_exag.transAxes,
        fontsize=10.5,
        ha="left",
        va="bottom",
        zorder=30,
        bbox=dict(facecolor="white", edgecolor="#888888", linewidth=0.8, alpha=0.92, pad=0.3),
    )
    box = fig.add_axes([0.024, 0.872, 0.952, 0.075])
    box.set_axis_off()
    box.add_patch(
        Rectangle(
            (0, 0), 1, 1, transform=box.transAxes,
            facecolor="#f7f7f7", edgecolor="#888888", linewidth=0.9, zorder=0,
        )
    )
    line1, caption = overview_box_lines(stats)
    box.text(0.012, 0.66, line1, fontsize=15.5, ha="left", va="center", zorder=2)
    box.text(0.012, 0.22, caption, fontsize=14.5, ha="left", va="center", zorder=2)
    add_legend_bottom(fig)
    fig.text(
        0.025,
        0.982,
        f"Overview {year}: frozen forecast vs observed bank, whole study rectangle",
        fontsize=24,
        ha="left",
        va="top",
    )
    fig.text(
        0.025,
        0.961,
        "Native 30 m selected-river mask; no simplification or smoothing; EPSG:32646, north up",
        fontsize=14,
        ha="left",
        va="top",
        color="#444444",
    )
    save_figure(fig, path)
    return path


def draw_full(year: int, mask: dict, start_mask: dict, data: dict, bounds: dict[str, float]) -> Path:
    path = OUT / f"full_{year}.png"
    fig = setup_figure((35, 34))
    ax = fig.add_axes([0.02, 0.035, 0.68, 0.925])
    draw_frame(
        ax,
        mask,
        data["transects"],
        data["forecast_lines"][year],
        data["forecast_points"][year],
        data["pred"][data["pred"]["year"] == year],
        year,
        bounds,
        start_mask,
        1.25,
        24,
        14,
    )
    add_legend(fig, map_handles(), (0.72, 0.92))
    fig.text(
        0.02,
        0.985,
        f"Full resolution {year}: frozen forecast vs observed bank boundary",
        fontsize=24,
        ha="left",
        va="top",
    )
    fig.text(
        0.02,
        0.967,
        "Unsimplified 30 m mask boundary; all selected-river components and holes retained",
        fontsize=14,
        ha="left",
        va="top",
        color="#444444",
    )
    save_figure(fig, path)
    return path


def draw_section(year: int, section_id: int, mask: dict, start_mask: dict, data: dict, section_table: pd.DataFrame) -> Path | None:
    transects = data["transects"]
    sec_transects = transects[transects["section_id"] == section_id]
    if sec_transects.empty:
        return None
    bounds = section_bounds(transects, section_id)
    path = OUT / f"section_{year}_{section_id:02d}.png"
    fig = setup_figure((24, 17))
    ax = fig.add_axes([0.02, 0.215, 0.70, 0.72])
    draw_frame(
        ax,
        mask,
        transects,
        data["forecast_lines"][year],
        data["forecast_points"][year],
        data["pred"][data["pred"]["year"] == year],
        year,
        bounds,
        start_mask,
        1.15,
        20,
        14,
    )
    add_legend(fig, map_handles(), (0.735, 0.93))
    tmin = int(sec_transects["transect_id"].min())
    tmax = int(sec_transects["transect_id"].max())
    fig.text(
        0.02,
        0.975,
        f"Section {section_id:02d} ({year})  T{tmin:03d}–T{tmax:03d}",
        fontsize=24,
        ha="left",
        va="top",
    )
    row = section_table[(section_table["year"] == year) & (section_table["section_id"] == section_id)]
    if row.empty:
        raise RuntimeError(f"No section metrics for {year} section {section_id}")
    row = row.iloc[0]
    strip_ax = fig.add_axes([0.02, 0.015, 0.70, 0.145])
    strip_ax.axis("off")
    strip_ax.text(
        0.0,
        0.94,
        f"Valid {int(row['n_valid'])}/{int(row['n_total'])}   flagged {int(row['n_flagged'])}   "
        f"forecast MAE {row['model_mae_m']:.2f} m   zero MAE {row['zero_mae_m']:.2f} m   "
        f"forecast closer {100 * row['model_closer_share']:.1f}%",
        fontsize=14,
        ha="left",
        va="top",
        family="DejaVu Sans",
    )
    strip_ax.text(
        0.0,
        0.52,
        f"Both within 15 m {100 * row['both_within_15_share']:.1f}%   "
        f"changed n={int(row['n_changed'])}   "
        f"changed RF/zero MAE {row['model_mae_changed_m']:.2f}/{row['zero_mae_changed_m']:.2f} m   "
        f"unchanged false alarm {100 * row['model_false_alarm_unchanged_share']:.1f}%",
        fontsize=14,
        ha="left",
        va="top",
        family="DejaVu Sans",
    )
    fig.text(
        0.02,
        0.952,
        "Section is 4 km along the centerline plus a 300 m margin; numbers are in the strip under the map",
        fontsize=14,
        ha="left",
        va="top",
        color="#444444",
    )
    save_figure(fig, path)
    return path


def draw_change(year: int, mask: dict, start_mask: dict, data: dict, bounds: dict[str, float], masks: dict[int, dict]) -> Path:
    base = masks[2023]
    valid = base["valid"] & mask["valid"]
    change = np.zeros(base["water"].shape, dtype=np.int8)
    change[valid & (~base["water"]) & mask["water"]] = 1
    change[valid & base["water"] & (~mask["water"])] = 2
    change[~valid] = -1
    path = OUT / f"change_{year}.png"
    fig = setup_figure((20, 26))
    ax = fig.add_axes([0.03, 0.055, 0.68, 0.88])
    ax.imshow(
        np.ma.masked_where(change < 0, change),
        cmap=ListedColormap([COLORS["unchanged"], COLORS["land_to_water"], COLORS["water_to_land"]]),
        norm=BoundaryNorm([-0.5, 0.5, 1.5, 2.5], 3),
        origin="upper",
        extent=(mask["bounds"][0], mask["bounds"][2], mask["bounds"][1], mask["bounds"][3]),
        interpolation="nearest",
        zorder=0,
        aspect="auto",
    )
    ax.set_xlim(bounds["left"], bounds["right"])
    ax.set_ylim(bounds["bottom"], bounds["top"])
    ax.set_aspect("equal", adjustable="box")
    ax.set_title(f"Water-mask change 2023 → {year}", fontsize=22, pad=12)
    ax.set_xlabel("UTM easting (km)")
    ax.set_ylabel("UTM northing (km)")
    ax.xaxis.set_major_locator(mticker.MultipleLocator(1000))
    ax.yaxis.set_major_locator(mticker.MultipleLocator(1000))
    ax.xaxis.set_major_formatter(mticker.FuncFormatter(lambda v, pos: f"{v / 1000:.0f}"))
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, pos: f"{v / 1000:.0f}"))
    ax.grid(True, which="major", color="#b0b0b0", linewidth=0.4, alpha=0.7, zorder=1)
    for spine in ax.spines.values():
        spine.set_linewidth(1.0)
    draw_boundary(ax, start_mask["rings"], COLORS["start"], px_to_pt(START_LINE_PX), 2, START_LINE_ALPHA)
    draw_boundary(ax, mask["rings"], COLORS["observed"], px_to_pt(OBSERVED_LINE_PX), 3)
    for _, row in data["forecast_lines"][year].iterrows():
        x, y = row.geometry.xy
        ax.plot(x, y, color=COLORS["halo"], linewidth=5.2, zorder=4)
        ax.plot(x, y, color=COLORS["forecast"], linewidth=2.5, linestyle="--", zorder=5)
    pred = data["pred"][data["pred"]["year"] == year]
    valid_pred = pred[pred["valid"]]
    segments = []
    colors = []
    for _, row in valid_pred.iterrows():
        segments.append(
            [
                (float(row["forecast_bank_x"]), float(row["forecast_bank_y"])),
                (float(row["observed_bank_x"]), float(row["observed_bank_y"])),
            ]
        )
        colors.append(COLORS[row["connector"]])
    if segments:
        ax.add_collection(LineCollection(segments, colors=colors, linewidths=CONNECTOR_LW, zorder=7.5, alpha=0.95))
    ax.scatter(
        valid_pred["observed_bank_x"],
        valid_pred["observed_bank_y"],
        s=11,
        c="black",
        edgecolors="none",
        zorder=8,
    )
    flagged = pred[~pred["valid"]]
    if len(flagged):
        ax.scatter(
            flagged["observed_bank_x"],
            flagged["observed_bank_y"],
            s=24,
            facecolors="none",
            edgecolors="black",
            linewidths=1.1,
            zorder=9,
        )
    draw_transect_labels(ax, data["transects"], bounds, fontsize=13)
    draw_scale_north(ax, bounds)
    handles = [
        Patch(facecolor=COLORS["land_to_water"], edgecolor="none", label="Land lost to water"),
        Patch(facecolor=COLORS["water_to_land"], edgecolor="none", label="Water lost to land"),
        Patch(facecolor=COLORS["unchanged"], edgecolor="none", label="Unchanged (water or land)"),
        Line2D(
            [0], [0], color=COLORS["start"], lw=px_to_pt(START_LINE_PX),
            alpha=START_LINE_ALPHA, label="2023 bank boundary",
        ),
        Line2D([0], [0], color=COLORS["observed"], lw=px_to_pt(OBSERVED_LINE_PX), label="Observed mask boundary"),
        Line2D([0], [0], color=COLORS["forecast"], lw=2.4, ls="--", label="Forecast bank"),
    ]
    add_legend(fig, handles)
    fig.text(
        0.03,
        0.975,
        f"Change {year}: 2023 → {year} selected-river water mask",
        fontsize=24,
        ha="left",
        va="top",
    )
    fig.text(
        0.03,
        0.955,
        "Land lost to water red; water lost to land blue; unchanged light grey; invalid white",
        fontsize=14,
        ha="left",
        va="top",
        color="#444444",
    )
    save_figure(fig, path)
    return path


def draw_error_profiles_year(pred: pd.DataFrame, year: int) -> Path:
    path = OUT / f"error_profile_{year}.png"
    fig = setup_figure((12, 10))
    axes = [
        fig.add_axes([0.09, 0.53, 0.86, 0.36]),
        fig.add_axes([0.09, 0.08, 0.86, 0.36]),
    ]
    for ax, side, panel_title in zip(axes, ["L", "R"], ["Left bank", "Right bank"]):
        group = pred[pred["side"] == side].sort_values("along_m")
        good = group[group["valid"]]
        flagged = group[~group["valid"]]
        ax.plot(group["along_m"] / 1000, group["model_error_m"], color=COLORS["forecast"], linewidth=0.7, alpha=0.35, zorder=1)
        ax.plot(group["along_m"] / 1000, group["zero_error_m"], color=COLORS["start"], linewidth=0.8, alpha=0.8, zorder=1)
        ax.axhline(0, color="black", linewidth=0.8, zorder=2)
        ax.axhline(15, color="#777777", linewidth=0.7, linestyle=":", zorder=2)
        ax.axhline(-15, color="#777777", linewidth=0.7, linestyle=":", zorder=2)
        colors = [COLORS[c] for c in good["connector"]]
        ax.scatter(good["along_m"] / 1000, good["model_error_m"], s=26, c=colors, edgecolors="none", zorder=4)
        if len(flagged):
            fcolors = [COLORS[c] for c in flagged["connector"]]
            ax.scatter(
                flagged["along_m"] / 1000,
                flagged["model_error_m"],
                s=55,
                facecolors="none",
                edgecolors=fcolors,
                linewidths=1.1,
                zorder=5,
            )
        ax.set_title(panel_title, fontsize=18, pad=6)
        ax.set_ylabel("Signed error (m)")
        ax.grid(True, color="#d0d0d0", linewidth=0.4, alpha=0.7)
        ax.tick_params(labelsize=14)
        all_abs = np.nanmax(np.abs(group[["model_error_m", "zero_error_m"]].to_numpy()))
        limit = max(60.0, math.ceil((all_abs + 10.0) / 30.0) * 30.0)
        ax.set_ylim(-limit, limit)
        ax.set_xlim(0, 27.0)
    axes[1].set_xlabel("Chainage along centerline (km)")
    handles = [
        Line2D([0], [0], marker="o", color="none", markerfacecolor=COLORS["green"], markeredgecolor="none", markersize=6, label="Forecast closer"),
        Line2D([0], [0], marker="o", color="none", markerfacecolor=COLORS["red"], markeredgecolor="none", markersize=6, label="Zero closer"),
        Line2D([0], [0], marker="o", color="none", markerfacecolor=COLORS["grey"], markeredgecolor="none", markersize=6, label="Both <= 15 m / tie"),
        Line2D([0], [0], color=COLORS["forecast"], linewidth=1.0, label="Forecast error"),
        Line2D([0], [0], color=COLORS["start"], linewidth=1.0, label="Zero-change error"),
        Line2D([0], [0], marker="o", color="none", markerfacecolor="none", markeredgecolor="black", markersize=7, label="Flagged (hollow)"),
    ]
    axes[0].legend(handles=handles, loc="upper right", fontsize=12.5, frameon=True, framealpha=0.9)
    fig.text(
        0.5,
        0.985,
        f"{year}: signed forecast and zero-change error along chainage",
        fontsize=22,
        ha="center",
        va="top",
    )
    fig.text(
        0.5,
        0.955,
        "Markers are coloured by which line is closer; the dotted lines are ±15 m",
        fontsize=14,
        ha="center",
        va="top",
        color="#444444",
    )
    save_figure(fig, path)
    return path


def draw_changed_places(
    year: int,
    mask: dict,
    start_mask: dict,
    data: dict,
    changed_selection: pd.DataFrame,
) -> Path:
    selection = changed_selection[changed_selection["year"] == year].sort_values("rank")
    if len(selection) != 6:
        raise RuntimeError(f"Expected 6 changed-place sections for {year}")
    path = OUT / f"changed_places_{year}.png"
    fig = setup_figure((36, 30))
    fig.text(
        0.5,
        0.985,
        f"Changed places {year}: six 4 km sections with largest observed movement",
        fontsize=24,
        ha="center",
        va="top",
    )
    fig.text(
        0.5,
        0.960,
        "Selected by maximum |observed displacement| among valid pairs; each tile shows the 2023 bank, observed bank, forecast, and section numbers",
        fontsize=13,
        ha="center",
        va="top",
        color="#444444",
    )
    for i, (_, row) in enumerate(selection.iterrows()):
        col = i % 3
        row_idx = i // 3
        x0 = 0.012 + col * 0.329
        y0 = 0.510 if row_idx == 0 else 0.055
        ax = fig.add_axes([x0, y0 + 0.085, 0.306, 0.31])
        section_id = int(row["section_id"])
        draw_frame(
            ax,
            mask,
            data["transects"],
            data["forecast_lines"][year],
            data["forecast_points"][year],
            data["pred"][data["pred"]["year"] == year],
            year,
            section_bounds(data["transects"], section_id),
            start_mask,
            0.55,
            8,
            9,
            include_connectors=False,
        )
        fig.text(
            x0 + 0.006,
            y0 + 0.425,
            f"Rank {int(row['rank'])}  |  Section {section_id:02d}  |  "
            f"T{int(row['transect_min']):03d}–T{int(row['transect_max']):03d}",
            fontsize=17,
            ha="left",
            va="top",
        )
        line1, line2 = changed_place_lines(row)
        fig.text(x0 + 0.006, y0 + 0.020, line1, fontsize=10.5, ha="left", va="bottom")
        fig.text(x0 + 0.006, y0 + 0.006, line2, fontsize=10.5, ha="left", va="bottom")
    handles = [
        Patch(facecolor=COLORS["water"], edgecolor="none", label="Observed-year water mask"),
        Line2D(
            [0], [0], color=COLORS["start"], lw=px_to_pt(START_LINE_PX),
            alpha=START_LINE_ALPHA, label="2023 bank boundary (zero change)",
        ),
        Line2D([0], [0], color=COLORS["observed"], lw=px_to_pt(OBSERVED_LINE_PX), label="Observed mask boundary"),
        Line2D([0], [0], color=COLORS["forecast"], lw=2.4, ls="--", label="Forecast bank"),
    ]
    fig.legend(
        handles=handles,
        loc="lower center",
        bbox_to_anchor=(0.5, 0.003),
        ncol=4,
        frameon=False,
        fontsize=11.5,
        handlelength=2.4,
        columnspacing=2.0,
    )
    save_figure(fig, path)
    return path


def validate_image_dims(path: Path, min_long: int, min_width: int | None = None) -> dict:
    with Image.open(path) as im:
        width, height = im.size
    ok = max(width, height) >= min_long
    if min_width is not None:
        ok = ok and width >= min_width
    if not ok:
        raise RuntimeError(f"{rel(path)} dimensions {width}x{height} fail minimum")
    return {"path": rel(path), "width": width, "height": height, "pass": True}


def draw_outputs(
    data: dict,
    masks: dict[int, dict],
    bounds: dict[str, float],
    section_table: pd.DataFrame,
    overview_stats: pd.DataFrame,
    changed_selection: pd.DataFrame,
) -> list[Path]:
    created = []
    for year in YEARS:
        created.append(draw_overview(year, masks[year], masks[2023], data, bounds, overview_stats))
        print("wrote", rel(created[-1]), flush=True)
    for year in YEARS:
        for section_id in sorted(data["transects"]["section_id"].unique()):
            path = draw_section(year, int(section_id), masks[year], masks[2023], data, section_table)
            if path is not None:
                created.append(path)
                print("wrote", rel(path), flush=True)
    for year in YEARS:
        created.append(draw_changed_places(year, masks[year], masks[2023], data, changed_selection))
        print("wrote", rel(created[-1]), flush=True)
    for year in YEARS:
        created.append(draw_full(year, masks[year], masks[2023], data, bounds))
        print("wrote", rel(created[-1]), flush=True)
    for year in YEARS:
        created.append(draw_change(year, masks[year], masks[2023], data, bounds, masks))
        print("wrote", rel(created[-1]), flush=True)
    for year in YEARS:
        created.append(draw_error_profiles_year(data["pred"][data["pred"]["year"] == year], year))
        print("wrote", rel(created[-1]), flush=True)
    return created


def image_dimensions(path: Path) -> tuple[int, int]:
    with Image.open(path) as im:
        return im.size
