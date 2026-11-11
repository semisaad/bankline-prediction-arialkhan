from __future__ import annotations

import collections
import hashlib
import re
from pathlib import Path

import numpy as np
import rasterio

from .config import ensure_output_dirs, load_config, project_path
from .io import sha256_file, write_json

FILENAME_RE = re.compile(r"^MNDWI_Mask_(\d{4})\.tif$")


def _pixel_hash(path: Path) -> str:
    h = hashlib.sha256()
    with rasterio.open(path) as src:
        arr = src.read()
        h.update(arr.tobytes())
        h.update(str(arr.shape).encode())
    return h.hexdigest()


def run() -> dict:
    ensure_output_dirs()
    cfg = load_config()
    src_dir = project_path(cfg["source_dir"])
    test_years = set(cfg["test_years"])
    rows: list[dict] = []
    naming_issues: list[str] = []
    duplicate_years: dict[int, list[str]] = collections.defaultdict(list)
    pixel_hashes: dict[str, list[int]] = collections.defaultdict(list)

    for path in sorted(src_dir.iterdir()):
        if not path.is_file():
            continue
        match = FILENAME_RE.match(path.name)
        if not match:
            if path.suffix.lower() in {".tif", ".tiff"}:
                naming_issues.append(f"Non-standard raster filename: {path.name}")
            continue
        year = int(match.group(1))
        duplicate_years[year].append(path.name)
        row = {
            "filename": path.name,
            "year_from_filename": year,
            "size_bytes": path.stat().st_size,
            "sha256_file": sha256_file(path),
            "temporal_precision": "year only in filename; dry-season January 1-March 25 composite",
            "metadata_source": "filename and file bytes only" if year in test_years else "filename plus raster metadata",
        }
        if year in test_years:
            row.update(
                {
                    "pixel_contents_inspected": False,
                    "test_lock": "2024-2026 pixel contents not opened before forecast freeze",
                }
            )
        else:
            try:
                with rasterio.open(path) as src:
                    water = src.read(cfg["mask_encoding"]["water_band"])
                    valid = src.read(cfg["mask_encoding"]["valid_band"])
                    wvals, wcounts = np.unique(water, return_counts=True)
                    vvals, vcounts = np.unique(valid, return_counts=True)
                    row.update(
                        {
                            "pixel_contents_inspected": True,
                            "width": src.width,
                            "height": src.height,
                            "band_count": src.count,
                            "dtype": src.dtypes[0],
                            "crs": src.crs.to_string() if src.crs else None,
                            "affine_transform": list(tuple(src.transform)[:6]),
                            "pixel_size": list(src.res),
                            "extent": list(src.bounds),
                            "nodata": src.nodata,
                            "band_descriptions": list(src.descriptions),
                            "water_values": {str(k): int(v) for k, v in zip(wvals, wcounts)},
                            "valid_values": {str(k): int(v) for k, v in zip(vvals, vcounts)},
                            "valid_fraction": float((valid == cfg["mask_encoding"]["valid_value"]).mean()),
                            "water_fraction_of_valid": float(
                                ((water == cfg["mask_encoding"]["water_value"]) & (valid == cfg["mask_encoding"]["valid_value"])).sum()
                                / max(1, (valid == cfg["mask_encoding"]["valid_value"]).sum())
                            ),
                            "pixel_sha256": _pixel_hash(path),
                            "tags": src.tags(),
                        }
                    )
                    pixel_hashes[row["pixel_sha256"]].append(year)
            except Exception as exc:  # noqa: BLE001
                row["unreadable"] = f"{type(exc).__name__}: {exc}"
        rows.append(row)

    years = sorted(r["year_from_filename"] for r in rows)
    expected = set(range(1989, 2027))
    missing = sorted(expected - set(years))
    duplicate_content = [v for v in pixel_hashes.values() if len(v) > 1]
    grid_variants = collections.Counter(
        (r.get("crs"), tuple(r.get("affine_transform", [])), r.get("width"), r.get("height"))
        for r in rows
        if r.get("pixel_contents_inspected")
    )
    inventory = {
        "source_dir": str(src_dir),
        "discovered_at_utc": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
        "file_count": len(rows),
        "years": years,
        "missing_years": missing,
        "duplicate_year_entries": {str(k): v for k, v in duplicate_years.items() if len(v) > 1},
        "duplicate_pixel_content_groups": duplicate_content,
        "naming_issues": naming_issues,
        "grid_variants_historical": [
            {"crs": k[0], "transform": list(k[1]), "width": k[2], "height": k[3], "count": n}
            for k, n in grid_variants.items()
        ],
        "test_year_lock": {
            "years": sorted(test_years),
            "policy": "Only filename, size and byte hash inspected before freeze. No metadata or pixel content opened.",
        },
        "temporal_ambiguity": (
            "Filenames contain only a year. The export configuration describes a January 1-March 25 "
            "dry-season composite, but individual scene dates are not stored. Labels use 25 March as the "
            "nominal end date and elapsed time is calculated from those nominal dates."
        ),
        "files": rows,
    }
    write_json(project_path("reports", "inventory.json"), inventory)
    _write_markdown(inventory)
    return inventory


def _write_markdown(inv: dict) -> None:
    lines = [
        "# Historical input inventory",
        "",
        f"- Source directory: `{inv['source_dir']}`",
        f"- Files discovered: {inv['file_count']}",
        f"- Years: {inv['years'][0]}–{inv['years'][-1]}",
        f"- Missing years: {inv['missing_years'] or 'none'}",
        f"- Duplicate year entries: {inv['duplicate_year_entries'] or 'none'}",
        f"- Identical pixel-array groups: {inv['duplicate_pixel_content_groups'] or 'none'}",
        f"- Non-standard filenames: {inv['naming_issues'] or 'none'}",
        "",
        "## Temporal precision",
        "",
        inv["temporal_ambiguity"],
        "",
        "## Test-period lock",
        "",
        inv["test_year_lock"]["policy"],
        "",
        "## Grid variants among historical files",
        "",
        "| CRS | width | height | transform | files |",
        "|---|---:|---:|---|---:|",
    ]
    for v in inv["grid_variants_historical"]:
        lines.append(
            f"| {v['crs']} | {v['width']} | {v['height']} | `{tuple(v['transform'])}` | {v['count']} |"
        )
    lines += [
        "",
        "## Per-file summary",
        "",
        "| Year | File | Bands | Size (px) | CRS | Water % of valid | Valid % | Locked |",
        "|---:|---|---:|---|---:|---:|---:|---|",
    ]
    for r in sorted(inv["files"], key=lambda x: x["year_from_filename"]):
        if r.get("pixel_contents_inspected"):
            lines.append(
                f"| {r['year_from_filename']} | `{r['filename']}` | {r['band_count']} | "
                f"{r['width']}×{r['height']} | {r['crs']} | {r['water_fraction_of_valid']*100:.2f} | "
                f"{r['valid_fraction']*100:.2f} | no |"
            )
        else:
            lines.append(
                f"| {r['year_from_filename']} | `{r['filename']}` | — | — | — | — | — | yes |"
            )
    lines += [
        "",
        "The water class is `255` in band 1 (`water`); band 2 (`valid`) separates the observed "
        "footprint from the 1-pixel border where focal operations left no data. Land is `0` inside "
        "the valid footprint. This is established from the band descriptions and the spatial pattern, "
        "not from an assumption that white means water.",
    ]
    project_path("reports", "inventory_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    run()
