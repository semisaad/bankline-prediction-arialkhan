from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from PIL import Image
from rasterio.warp import transform_bounds
import rasterio


def stretch(band: np.ma.MaskedArray) -> tuple[np.ndarray, np.ndarray]:
    values = band.compressed()
    if values.size == 0:
        return np.zeros(band.shape, dtype=np.uint8), np.zeros(band.shape, dtype=bool)
    low, high = np.percentile(values, [2, 98])
    if high <= low:
        low = float(values.min())
        high = float(values.max())
    if high <= low:
        scaled = np.zeros(band.shape, dtype=np.float32)
    else:
        scaled = np.clip((band.filled(low) - low) / (high - low), 0, 1)
    return (scaled * 255).astype(np.uint8), ~np.ma.getmaskarray(band)


def load_rgb(path: Path) -> tuple[np.ndarray, np.ndarray, list[float]]:
    with rasterio.open(path) as src:
        indexes = list(range(1, min(src.count, 3) + 1))
        data = src.read(indexes, masked=True)
        if src.crs is None:
            west, south, east, north = src.bounds
        else:
            west, south, east, north = transform_bounds(src.crs, "EPSG:4326", *src.bounds)
        count = data.shape[0]
        if count == 1:
            gray, valid = stretch(data[0])
            rgb = np.stack([gray, gray, gray], axis=-1)
            alpha = valid
        else:
            converted = [stretch(data[index]) for index in range(count)]
            rgb = np.stack([item[0] for item in converted], axis=-1)
            alpha = np.logical_and.reduce([item[1] for item in converted])
        while rgb.shape[2] < 3:
            rgb = np.concatenate([rgb, rgb[:, :, -1:]], axis=2)
    return rgb, alpha, [float(west), float(south), float(east), float(north)]


def save_overlay(rgb: np.ndarray, alpha: np.ndarray, out_path: Path, max_mb: float, max_width: int) -> tuple[int, int, int]:
    height, width = alpha.shape
    alpha_pixels = np.where(alpha, 255, 0).astype(np.uint8)
    rgba = np.dstack([rgb, alpha_pixels])
    image = Image.fromarray(rgba, mode="RGBA")
    if width > max_width:
        ratio = max_width / width
        image = image.resize((max_width, max(1, round(height * ratio))), Image.Resampling.LANCZOS)
    limit = int(max_mb * 1024 * 1024)
    candidate = image
    while True:
        candidate.save(out_path, format="PNG", optimize=True)
        size = out_path.stat().st_size
        if size <= limit or candidate.width <= 1200:
            break
        next_width = max(1200, int(candidate.width * 0.8))
        ratio = next_width / candidate.width
        candidate = candidate.resize((next_width, max(1, round(candidate.height * ratio))), Image.Resampling.LANCZOS)
    return candidate.width, candidate.height, out_path.stat().st_size


def main() -> None:
    parser = argparse.ArgumentParser(description="Convert a GEE Sentinel-2 GeoTIFF into the offline UI overlay.")
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path, default=Path("data/basemap"))
    parser.add_argument("--max-width", type=int, default=2400)
    parser.add_argument("--max-mb", type=float, default=15.0)
    args = parser.parse_args()

    if not args.input.is_file():
        raise SystemExit(f"Input file not found: {args.input}")
    args.output.mkdir(parents=True, exist_ok=True)
    rgb, alpha, bounds = load_rgb(args.input)
    image_path = args.output / "sentinel2_overlay.png"
    width, height, size = save_overlay(rgb, alpha, image_path, args.max_mb, args.max_width)
    meta = {
        "source": "Sentinel-2 SR Harmonized dry-season median",
        "input": args.input.name,
        "bounds": bounds,
        "crs": "EPSG:4326",
        "width": width,
        "height": height,
        "bytes": size,
        "created_utc": datetime.now(timezone.utc).isoformat(),
    }
    (args.output / "basemap.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {image_path} ({width}x{height}, {size / 1024 / 1024:.2f} MB)")
    print(f"wrote {args.output / 'basemap.json'}")


if __name__ == "__main__":
    main()
