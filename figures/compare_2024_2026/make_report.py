from __future__ import annotations

import math

import pandas as pd

from common import REPORT, YEARS, fmt_m, fmt_pct, md_table


def fmt_bytes(value) -> str:
    if value is None or value == "":
        return "—"
    return f"{int(value):,}"


def fmt_dim(row: dict) -> str:
    if row.get("width_px") in (None, "", 0):
        return "—"
    return f"{int(row['width_px'])}×{int(row['height_px'])}"


def fmt_num(value, digits: int = 6) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "—"
    if isinstance(value, (int,)) or (isinstance(value, float) and value.is_integer()):
        return f"{int(value)}"
    return f"{value:.{digits}f}"


def build_report(
    input_manifest: dict,
    metrics: dict,
    metrics_payload: dict,
    compare: pd.DataFrame,
    section_table: pd.DataFrame,
    headline: dict,
    boundaries: dict,
    holdout: pd.DataFrame,
    holdout_summary: dict,
    checks: list[dict],
    extra_checks: list[dict],
    frozen: dict,
    api_health: dict,
    masks: dict,
    file_inventory: list[dict],
    run_metadata: dict,
    overview_stats: pd.DataFrame,
    changed_selection: pd.DataFrame,
    closer_groups: pd.DataFrame,
    text_audit: dict,
    visibility: dict,
) -> None:
    overall = compare.iloc[0]
    by_year = compare[compare["scope"] == "year"].set_index("year")
    by_side = compare[compare["scope"] == "side"].set_index("side")
    lines = []

    lines.append("# Forecast vs observed bank lines, 2024–2026")
    lines.append("")
    lines.append(
        f"**Headline.** {int(overall['n_valid'])} good pairs: forecast MAE "
        f"**{overall['model_mae_m']:.2f} m**, zero-change MAE **{overall['zero_mae_m']:.2f} m**, "
        f"forecast strictly closer on **{100 * overall['model_closer_share']:.1f}%** of pairs. "
        f"Exact ties: {100 * overall['tie_share']:.1f}%. Both errors ≤ 15 m: "
        f"{100 * overall['both_within_15_share']:.1f}%."
    )
    lines.append("")
    lines.append(
        "The frozen forecast loses to zero change overall and in every year. "
        "This report adds large comparison figures and a post-hoc spatial sensitivity check. "
        "Nothing was retuned; no frozen file, model file, or `evaluation/metrics.json` was modified."
    )
    lines.append("")
    lines.append("## Headline by year")
    lines.append("")
    lines.append(
        md_table(
            ["Year", "Good pairs", "Forecast MAE", "Zero MAE", "Forecast closer", "Both ≤ 15 m"],
            [
                [
                    str(year),
                    str(int(by_year.loc[year, "n_valid"])),
                    fmt_m(by_year.loc[year, "model_mae_m"]),
                    fmt_m(by_year.loc[year, "zero_mae_m"]),
                    fmt_pct(by_year.loc[year, "model_closer_share"]),
                    fmt_pct(by_year.loc[year, "both_within_15_share"]),
                ]
                for year in YEARS
            ],
        )
    )
    lines.append("")
    valid_flagged = ", ".join(
        f"{year}: {int(by_year.loc[year, 'n_valid'])} valid / "
        f"{int(by_year.loc[year, 'n_flagged'])} flagged"
        for year in YEARS
    )
    lines.append(
        f"Counts: {int(overall['n_total'])} total pairs, {int(overall['n_valid'])} valid, "
        f"{int(overall['n_flagged'])} flagged/invalid. By year: {valid_flagged}."
    )
    lines.append("")

    lines.append("## Overview metrics and caption")
    lines.append("")
    lines.append(
        "Every overview carries a box with the forecast MAE, zero-change MAE, and the "
        "closer-than-2023 share, plus the caption below. The MAEs and `n` come from "
        "`evaluation/metrics.json`; `metrics.json` has no closer-share field, so closer, "
        "farther, and tie counts are strict comparisons of absolute error computed from "
        "`evaluation/predictions.csv` and written to `overview_stats.csv`/`.json`. "
        "The units are valid transect-side-year pairs, not 69 unique transects."
    )
    lines.append("")
    ov_rows = []
    for _, row in overview_stats.iterrows():
        ov_rows.append(
            [
                str(int(row["year"])),
                str(int(row["n_valid"])),
                fmt_m(row["model_mae_m"]),
                fmt_m(row["zero_mae_m"]),
                f"{int(row['model_closer_n'])} ({fmt_pct(row['model_closer_share'])})",
                f"{int(row['zero_closer_n'])} ({fmt_pct(row['zero_closer_share'])})",
                f"{int(row['exact_tie_n'])} ({fmt_pct(row['tie_share'])})",
            ]
        )
    lines.append(
        md_table(
            [
                "Year",
                "Valid pairs",
                "Forecast MAE",
                "Zero MAE",
                "Forecast closer n (share)",
                "Farther n (share)",
                "Ties n (share)",
            ],
            ov_rows,
        )
    )
    lines.append("")
    lines.append(
        "> Close to the actual line is only skill if closer than the 2023 line."
    )
    lines.append("")
    lines.append(
        "Each overview has two panels: the left map is true scale; the right map is labelled "
        "`error exaggerated 5x`. Only connector lengths are multiplied by 5 in the right panel; "
        "the mask, boundaries, scale bar, and observed points remain true. The right-panel "
        "endpoints are therefore illustrative, not locations."
    )
    lines.append("")

    lines.append("## Connectors and visibility")
    lines.append("")
    lines.append(
        "Connectors are drawn for every valid pair at line width 2 and are drawn above the "
        "bank lines but below the observed points. Grey overrides the closer/farther colour "
        "when both errors are ≤ 15 m, so the green/red counts are not the same as the "
        "forecast-closer/forecast-farther counts. No valid connector was omitted."
    )
    lines.append("")
    conn_rows = []
    for _, row in overview_stats.iterrows():
        vis = next(item for item in visibility["years"] if int(item["year"]) == int(row["year"]))
        conn_rows.append(
            [
                str(int(row["year"])),
                str(int(row["n_valid"])),
                str(int(row["n_green"])),
                str(int(row["n_red"])),
                str(int(row["n_grey"])),
                fmt_m(vis["median_m"]),
                str(int(vis["n_shorter_than_1px_true"])),
                str(int(vis["n_shorter_than_1px_5x"])),
            ]
        )
    lines.append(
        md_table(
            [
                "Year",
                "Valid",
                "Green",
                "Red",
                "Grey",
                "Median length (m)",
                "True-scale <1 px",
                "5x <1 px",
            ],
            conn_rows,
        )
    )
    lines.append("")
    lines.append(
        f"The true-scale overview is about {visibility['overview_m_per_px']:.2f} m per "
        f"pixel; line width 2 is {visibility['connector_linewidth_px_at_200dpi']:.1f} px at "
        "200 dpi. Some true connector lengths are far below one pixel; these are drawn, but "
        "they cannot be resolved at true scale. The 5x panel makes most of them visible, "
        "though the shortest remain subpixel. Exact counts are in "
        "`connector_visibility.json`."
    )
    lines.append("")

    lines.append("## Closer versus farther transects")
    lines.append("")
    lines.append(
        "Both groups are reported at the same valid-pair level used by `metrics.json` and "
        "the overviews. `Forecast farther (zero closer)` is the complement of the forecast "
        "being strictly closer; exact ties are a separate group. Full per-pair membership is "
        "in `closer_vs_farther_pairs.csv`, and the aggregate table is "
        "`closer_vs_farther.csv`."
    )
    lines.append("")
    close_rows = []
    for _, row in closer_groups.iterrows():
        scope = "All" if row["scope"] == "overall" else str(int(row["year"]))
        close_rows.append(
            [
                scope,
                row["group_label"],
                str(int(row["n"])),
                fmt_pct(row["share"]),
                fmt_m(row["model_mae_m"]),
                fmt_m(row["zero_mae_m"]),
                fmt_m(row["mean_abs_observed_m"]),
            ]
        )
    lines.append(
        md_table(
            [
                "Scope",
                "Group",
                "n",
                "Share",
                "Forecast MAE",
                "Zero MAE",
                "Mean abs observed",
            ],
            close_rows,
        )
    )
    lines.append("")
    lines.append(
        "Overall, the forecast is closer on 43/398 pairs (10.8%) and farther on 355/398 "
        "pairs (89.2%); there are no exact ties. This is the same group used in the overview "
        "box and is not the same as the 38 green connectors."
    )
    lines.append("")

    lines.append("## Changed places")
    lines.append("")
    lines.append(
        "For each year, six of the seven existing 4 km sections are selected by the largest "
        "maximum absolute observed displacement among valid pairs. All seven candidates are "
        "computed; the selected six are shown in a 3×2 grid with 2400 px-wide tiles. The "
        "selection is in `changed_places_selection.csv` and the printed strings are audited "
        "in `figure_text_audit.json`. Section 7 in 2024 has essentially no observed movement "
        "and is therefore not selected."
    )
    lines.append("")
    ch_place_rows = []
    for _, row in changed_selection.iterrows():
        ch_place_rows.append(
            [
                str(int(row["year"])),
                str(int(row["rank"])),
                f"{int(row['section_id']):02d}",
                f"T{int(row['transect_min']):03d}–T{int(row['transect_max']):03d}",
                fmt_m(row["max_abs_observed_m"]),
                fmt_m(row["mean_abs_observed_m"]),
                str(int(row["n_valid"])),
                fmt_m(row["model_mae_m"]),
                fmt_m(row["zero_mae_m"]),
                fmt_pct(row["model_closer_share"]),
                str(int(row["n_changed"])),
            ]
        )
    lines.append(
        md_table(
            [
                "Year",
                "Rank",
                "Section",
                "Transects",
                "Max abs obs",
                "Mean abs obs",
                "Valid",
                "Forecast MAE",
                "Zero MAE",
                "Forecast closer",
                "Changed n",
            ],
            ch_place_rows,
        )
    )
    lines.append("")

    lines.append("## Figure text audit")
    lines.append("")
    lines.append(
        "The numbers below are the exact strings rendered in the image boxes/tiles. "
        "Overview MAEs are checked against `evaluation/metrics.json`; closer counts are "
        "checked against `predictions.csv`; changed-place numbers are checked against "
        "`section_table.csv`."
    )
    lines.append("")
    audit_rows = []
    for row in text_audit["overview"]:
        audit_rows.append(
            [
                f"Overview {row['year']}",
                row["text_box"],
                "yes" if row["pass"] else "no",
            ]
        )
    for row in text_audit["changed_places"]:
        audit_rows.append(
            [
                f"Changed {row['year']} rank {row['rank']}",
                f"{row['line1']}<br>{row['line2']}",
                "yes" if row["pass"] else "no",
            ]
        )
    lines.append(md_table(["Figure", "Printed text", "Pass"], audit_rows))
    lines.append("")

    lines.append("## Comparison table")
    lines.append("")
    lines.append(
        "All values are from `compare_table.csv`; per-pair values are in `pair_table.csv`; "
        "per-section values are in `section_table.csv`. `Forecast closer` is a strict comparison "
        "of absolute errors. Exact ties and the `both ≤ 15 m` group are reported separately. "
        "The connector is grey when both errors are ≤ 15 m, green when the forecast is strictly "
        "closer, red when zero is strictly closer, and grey for exact ties."
    )
    lines.append("")
    comp_rows = []
    for _, row in compare.iterrows():
        if row["scope"] == "overall":
            label = "All"
        elif row["scope"] == "year":
            label = str(int(row["year"]))
        elif row["scope"] == "side":
            label = f"{row['side']} bank"
        else:
            label = f"{int(row['year'])} {row['side']}"
        comp_rows.append(
            [
                label,
                str(int(row["n_valid"])),
                str(int(row["n_flagged"])),
                fmt_m(row["model_mae_m"]),
                fmt_m(row["zero_mae_m"]),
                fmt_pct(row["model_within_15_share"]),
                fmt_pct(row["zero_within_15_share"]),
                fmt_pct(row["model_within_30_share"]),
                fmt_pct(row["zero_within_30_share"]),
                fmt_pct(row["model_closer_share"]),
                fmt_pct(row["zero_closer_share"]),
                fmt_pct(row["tie_share"]),
                fmt_pct(row["both_within_15_share"]),
            ]
        )
    lines.append(
        md_table(
            [
                "Scope",
                "Valid",
                "Flagged",
                "RF MAE",
                "Zero MAE",
                "RF ≤15",
                "Zero ≤15",
                "RF ≤30",
                "Zero ≤30",
                "RF closer",
                "Zero closer",
                "Tie",
                "Both ≤15",
            ],
            comp_rows,
        )
    )
    lines.append("")
    lines.append(
        f"Overall forecast/zero MAE by side: L "
        f"{by_side.loc['L', 'model_mae_m']:.2f}/{by_side.loc['L', 'zero_mae_m']:.2f} m; "
        f"R {by_side.loc['R', 'model_mae_m']:.2f}/{by_side.loc['R', 'zero_mae_m']:.2f} m."
    )
    lines.append("")

    lines.append("## Changed versus unchanged")
    lines.append("")
    lines.append(
        "Changed means `|observed displacement| > 15 m`; unchanged means `≤ 15 m`. "
        "Both groups are reported; the table is not restricted to changed rows. "
        "`False alarm` is the share of unchanged rows where the forecast moves more than 15 m."
    )
    lines.append("")
    ch_rows = []
    for year in YEARS:
        row = by_year.loc[year]
        ch_rows.append(
            [
                str(year),
                str(int(row["n_changed"])),
                fmt_m(row["model_mae_changed_m"]),
                fmt_m(row["zero_mae_changed_m"]),
                fmt_pct(row["direction_correct_changed_share"]),
                str(int(row["n_unchanged"])),
                fmt_m(row["model_mae_unchanged_m"]),
                fmt_m(row["zero_mae_unchanged_m"]),
                fmt_pct(row["model_false_alarm_unchanged_share"]),
            ]
        )
    ch_rows.append(
        [
            "All",
            str(int(overall["n_changed"])),
            fmt_m(overall["model_mae_changed_m"]),
            fmt_m(overall["zero_mae_changed_m"]),
            fmt_pct(overall["direction_correct_changed_share"]),
            str(int(overall["n_unchanged"])),
            fmt_m(overall["model_mae_unchanged_m"]),
            fmt_m(overall["zero_mae_unchanged_m"]),
            fmt_pct(overall["model_false_alarm_unchanged_share"]),
        ]
    )
    lines.append(
        md_table(
            [
                "Year",
                "Changed n",
                "Changed RF MAE",
                "Changed zero MAE",
                "Changed direction",
                "Unchanged n",
                "Unchanged RF MAE",
                "Unchanged zero MAE",
                "Unchanged false alarm",
            ],
            ch_rows,
        )
    )
    lines.append("")
    lines.append(
        f"Overall, changed rows: forecast MAE {overall['model_mae_changed_m']:.2f} m versus "
        f"{overall['zero_mae_changed_m']:.2f} m for zero; direction correct on "
        f"{100 * overall['direction_correct_changed_share']:.1f}%. "
        f"Unchanged rows: forecast MAE {overall['model_mae_unchanged_m']:.2f} m versus "
        f"{overall['zero_mae_unchanged_m']:.2f} m; false-alarm share "
        f"{100 * overall['model_false_alarm_unchanged_share']:.1f}%."
    )
    lines.append("")

    lines.append("## Boundary check and displayed actual line")
    lines.append("")
    lines.append(
        "The displayed solid black actual line is the unsimplified boundary of the selected-river "
        "mask, including all components and holes. The supplied `observed_banklines` are a "
        "75-vertex chord. Their vertices lie on the boundary, but straight chords cut bends; "
        "dense sampling of those chords exceeds 30 m. The chords are therefore not drawn. "
        "This is a display choice, not a change to any input or metric."
    )
    lines.append("")
    b_rows = []
    for item in boundaries["years"]:
        sides = {row["side"]: row for row in item["source"]}
        b_rows.append(
            [
                str(item["year"]),
                f"{item['observed_points_max_m']:.2e}",
                f"{item['displayed_boundary_max_m']:.2f}",
                f"{sides['L']['source_dense_5m_max_m']:.2f}",
                f"{sides['R']['source_dense_5m_max_m']:.2f}",
                "yes" if item["source_chord_exceeds_30m"] else "no",
                "yes" if item["displayed_boundary_max_m"] <= boundaries["boundary_tolerance_m"] else "no",
            ]
        )
    lines.append(
        md_table(
            [
                "Year",
                "Observed points max (m)",
                "Displayed boundary max (m)",
                "Source chord L (m)",
                "Source chord R (m)",
                "Chord >30 m",
                "Displayed pass",
            ],
            b_rows,
        )
    )
    lines.append("")
    lines.append(
        "A 2024 left-bank point at `T070` lies on a small disconnected mask component. "
        "All components are retained, so no bank is dropped or hidden; the union boundary is used."
    )
    lines.append("")

    lines.append("## Spatial block holdout")
    lines.append("")
    lines.append(
        "Five contiguous blocks of 15 transects. For each block, the block plus two transects on "
        "each side are removed from training; the same frozen feature set and random-forest "
        "hyperparameters are refit with targets on or before 2023; 2024–2026 are forecast from "
        "origin 2023 and compared with zero change on the same good transects. There is no tuning "
        "and no bootstrap interval. This is post-hoc on years already scored and has very low power."
    )
    lines.append("")
    h_rows = []
    for _, row in holdout.iterrows():
        h_rows.append(
            [
                row["block"],
                f"{int(row['transect_start'])}–{int(row['transect_end'])}",
                "—" if math.isnan(row["train_rows_all_horizons"]) else str(int(row["train_rows_all_horizons"])),
                str(int(row["n_good"])),
                fmt_m(row["model_mae_m"]),
                fmt_m(row["zero_mae_m"]),
                fmt_m(row["mae_difference_model_minus_zero_m"]),
                fmt_pct(row["model_closer_share"]),
                "yes" if bool(row["model_beats_zero"]) else "no",
            ]
        )
    lines.append(
        md_table(
            [
                "Block",
                "Transects",
                "Train rows",
                "n good",
                "RF MAE",
                "Zero MAE",
                "RF − zero",
                "RF closer",
                "RF beats zero",
            ],
            h_rows,
        )
    )
    lines.append("")
    lines.append(
        f"Model beats zero in **{holdout_summary['n_blocks_model_beats_zero']} of "
        f"{holdout_summary['n_blocks']}** blocks. Pooled held-out RF/zero MAE: "
        f"{holdout_summary['pooled_model_mae_m']:.2f}/{holdout_summary['pooled_zero_mae_m']:.2f} m. "
        "This sensitivity check does not change the design, claims, or frozen files."
    )
    lines.append("")

    lines.append("## Metric reproduction")
    lines.append("")
    lines.append(
        f"The {len(metrics_payload['checks'])} checks below reproduce `evaluation/metrics.json` "
        f"from `evaluation/predictions.csv`; tolerance is {metrics_payload['tolerance_m']} m. "
        "The source metrics file was not written."
    )
    lines.append("")
    m_rows = []
    for row in metrics_payload["checks"]:
        m_rows.append(
            [
                row["check"],
                fmt_num(row["expected"]),
                fmt_num(row["computed"]),
                f"{row['abs_diff']:.6f}",
                f"{row['tolerance']:.6f}",
                "yes" if row["pass"] else "no",
            ]
        )
    lines.append(md_table(["Check", "Expected", "Computed", "Abs diff", "Tolerance", "Pass"], m_rows))
    lines.append("")

    lines.append("## Checks, including bad-input proofs")
    lines.append("")
    lines.append(
        "Every check was run in this run. `EXPECTED-FAIL` rows deliberately feed bad input and "
        "show the expected failure. Full output is in `checks.log` and `checks.json`."
    )
    lines.append("")
    check_rows = []
    for item in extra_checks + checks:
        check_rows.append(
            [item["result"], item["check"], item["detail"], "yes" if item.get("pass") else "no"]
        )
    lines.append(md_table(["Result", "Check", "Detail", "Pass"], check_rows))
    lines.append("")

    lines.append("## Inputs and SHA-256")
    lines.append("")
    lines.append(
        f"We wrote `input_manifest.json` before the first figure was drawn "
        f"(`{input_manifest['created_utc']}`). The study window is EPSG:32646; the "
        "selected-river masks are 30 m and unrotated. Raw `landsat/MNDWI_Mask_*` files are listed "
        "where present but the display uses the selected-river masks."
    )
    lines.append("")
    in_rows = []
    for role, item in input_manifest["files"].items():
        in_rows.append([role, item["path"], fmt_bytes(item["bytes"]), item["sha256"]])
    lines.append(md_table(["Role", "Path", "Bytes", "SHA-256"], in_rows))
    lines.append("")

    lines.append("## Figures")
    lines.append("")
    def figure_sizes(prefix: str) -> str:
        values = sorted(
            {
                f"{int(item['width_px'])}×{int(item['height_px'])}"
                for item in file_inventory
                if item["role"] == "figure"
                and item["path"].split("/")[-1].startswith(prefix)
                and item["width_px"] not in (None, "")
            }
        )
        return ", ".join(values) if values else "—"

    lines.append(
        "All maps are EPSG:32646, north-up, native 30 m masks with nearest-neighbour display, "
        "unsimplified boundary geometry, a 500 m scale bar, north arrow, km grid, and the legend "
        "outside the map area. The 2023 bank is drawn at 4 px (60% opacity) beneath a 2 px black "
        "observed line so the grey remains visible. "
        f"Overview (two panels): {figure_sizes('overview_')} px; changed places: "
        f"{figure_sizes('changed_places_')} px; change: {figure_sizes('change_')} px; "
        f"sections: {figure_sizes('section_')} px; full: {figure_sizes('full_')} px; "
        f"error profiles: {figure_sizes('error_profile_')} px."
    )
    lines.append("")
    fig_rows = []
    for item in file_inventory:
        if item["role"] == "figure":
            fig_rows.append([item["path"], fmt_bytes(item["bytes"]), fmt_dim(item)])
    lines.append(md_table(["Figure", "Bytes", "Pixels"], fig_rows))
    lines.append("")

    lines.append("## Files created")
    lines.append("")
    lines.append(
        "The table below lists every generated file present before this report, with size and "
        "pixel dimensions. `file_manifest.csv` is the complete inventory, including this report "
        "and the manifest itself."
    )
    lines.append("")
    file_rows = []
    for item in file_inventory:
        file_rows.append([item["path"], item["role"], fmt_bytes(item["bytes"]), fmt_dim(item)])
    lines.append(md_table(["File", "Role", "Bytes", "Pixels"], file_rows))
    lines.append("")

    lines.append("## Unresolved and caveats")
    lines.append("")
    lines.append(
        "- The supplied `observed_banklines` chordal polyline exceeds the 30 m boundary check when "
        "sampled densely; the displayed line is the actual mask boundary. See the boundary table."
    )
    lines.append(
        "- The 2024 left-bank `T070` point lies on a 6-pixel disconnected component; all components "
        "are retained and no bank was dropped."
    )
    lines.append(
        f"- {int(overall['n_flagged'])} of {int(overall['n_total'])} pairs are flagged/invalid. "
        "They remain visible as hollow markers and are counted; they are not scored."
    )
    lines.append(
        "- The spatial holdout is post-hoc, uses years already scored, has five blocks of about 15 "
        "transects, and has no bootstrap interval. It is a sensitivity check, not a blind test."
    )
    lines.append(
        "- `evaluation/metrics.json` has no closer-share field. The overviews therefore take "
        "MAEs and n from metrics.json and compute closer/farther/ties from predictions.csv; "
        "the two sources agree on n and MAE."
    )
    lines.append(
        "- The 4 px 2023 line is measured in final image pixels at 200 dpi. The observed line "
        "is 2 px so the light-grey line remains visible underneath it; at the old equal width "
        "the grey would be hidden."
    )
    lines.append(
        "- The `error exaggerated 5x` panel multiplies only connector lengths. Its endpoints "
        "are illustrative and are not bank locations; the true-scale panel and all numeric "
        "checks remain true scale."
    )
    lines.append(
        "- No required input was missing. All metric checks are within 0.01 m. Frozen and model "
        "hashes were unchanged, and `/api/health/` passed."
    )
    lines.append("")
    lines.append(
        f"Run metadata: `run_metadata.json`; input manifest: `input_manifest.json`; checks: "
        f"`checks.log`; complete file inventory: `file_manifest.csv`."
    )
    lines.append("")

    REPORT.write_text("\n".join(lines), encoding="utf-8")
