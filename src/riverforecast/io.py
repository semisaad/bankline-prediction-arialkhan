from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.warp import reproject
from shapely.geometry import mapping
from shapely.ops import transform as shapely_transform
from pyproj import Transformer

from .config import (
    PROJECT_ROOT,
    is_test_year,
    load_config,
    nominal_date,
    project_path,
)


class TestDataLockError(RuntimeError):
    __test__ = False


class DataDefect(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _freeze_ready() -> bool:
    frozen = project_path("forecasts", "frozen")
    manifest = frozen / "manifest.json"
    ready = frozen / "READY"
    if not manifest.exists() or not ready.exists():
        return False
    expected = ready.read_text(encoding="utf-8").strip()
    return expected == sha256_file(manifest)


def require_freeze_ready() -> dict:
    frozen = project_path("forecasts", "frozen")
    manifest_path = frozen / "manifest.json"
    if not _freeze_ready():
        raise TestDataLockError(
            "Test data access is locked: a valid frozen forecast manifest and READY "
            "marker are required before any 2024-2026 raster can be opened."
        )
    with open(manifest_path, "r", encoding="utf-8") as fh:
        manifest = json.load(fh)
    if not manifest.get("frozen"):
        raise TestDataLockError("Forecast manifest is not marked frozen.")
    verify_frozen_manifest(manifest)
    return manifest


def verify_frozen_manifest(manifest: dict) -> None:
    """Re-hash every frozen artifact and enforce the temporal holdout contract."""
    frozen = project_path("forecasts", "frozen")
    cfg = load_config()
    if set(int(y) for y in manifest.get("forecast_years", [])) != set(int(y) for y in cfg["test_years"]):
        raise TestDataLockError("Frozen manifest forecast years do not match the configured test years.")
    if int(manifest.get("training_cutoff_year", 9999)) >= min(int(y) for y in cfg["test_years"]):
        raise TestDataLockError("Frozen manifest training cutoff reaches the test period.")
    if int(manifest.get("origin_year", 9999)) >= min(int(y) for y in cfg["test_years"]):
        raise TestDataLockError("Frozen manifest origin year reaches the test period.")
    inputs = manifest.get("inputs") or {}
    required_inputs = {
        "config_sha256": project_path("config", "pipeline.json"),
        "dataset_sha256": project_path("datasets", "bank_migration_dataset.csv"),
        "forecast_features_sha256": project_path("datasets", "forecast_features_2023.csv"),
        "model_artifact_sha256": project_path("models", "final_models.joblib"),
        "model_metadata_sha256": project_path("models", "model_metadata.json"),
    }
    for key, path in required_inputs.items():
        expected = inputs.get(key)
        if not expected or not path.is_file() or sha256_file(path) != expected:
            raise TestDataLockError(f"Frozen input changed or is missing: {key}")
    code_hashes = inputs.get("code") or {}
    if not code_hashes:
        raise TestDataLockError("Frozen manifest has no code hashes.")
    for name, expected in code_hashes.items():
        path = project_path("src", "riverforecast", name)
        if not path.is_file() or sha256_file(path) != expected:
            raise TestDataLockError(f"Pipeline code changed after the forecast was frozen: {name}")
    files = manifest.get("files") or []
    if not files:
        raise TestDataLockError("Frozen manifest has no file hashes.")
    for item in files:
        path = frozen / item["name"]
        if not path.exists():
            raise TestDataLockError(f"Frozen artifact is missing: {item['name']}")
        if sha256_file(path) != item["sha256"]:
            raise TestDataLockError(f"Frozen artifact hash mismatch: {item['name']}")
        if path.stat().st_size != int(item["size"]):
            raise TestDataLockError(f"Frozen artifact size mismatch: {item['name']}")


def assert_read_allowed(year: int, purpose: str) -> None:
    year = int(year)
    if is_test_year(year):
        if purpose != "evaluation":
            raise TestDataLockError(
                f"Refusing to open test-year raster {year} for purpose {purpose!r}. "
                "Forecast freeze is required first."
            )
        require_freeze_ready()


def source_raster(year: int) -> Path:
    cfg = load_config()
    return project_path(cfg["source_dir"], f"MNDWI_Mask_{int(year)}.tif")


def _canonical_profile() -> dict:
    grid = load_config()["canonical_grid"]
    return {
        "driver": "GTiff",
        "height": int(grid["height"]),
        "width": int(grid["width"]),
        "count": 2,
        "dtype": "uint8",
        "crs": grid["crs"],
        "transform": rasterio.Affine(*grid["transform"]),
        "compress": "deflate",
    }


def _transform_matches(src) -> bool:
    grid = load_config()["canonical_grid"]
    return (
        src.width == int(grid["width"])
        and src.height == int(grid["height"])
        and src.crs is not None
        and src.crs.to_string() == grid["crs"]
        and np.allclose(tuple(src.transform)[:6], tuple(grid["transform"]), atol=1e-9)
    )


def read_mask(year: int, purpose: str = "training") -> tuple[np.ndarray, np.ndarray, dict]:
    """Return (water, valid, info) on the frozen canonical grid.

    water and valid are boolean arrays. The frozen encoding is band 1 = water,
    band 2 = valid, 255 = true, 0 = false.
    """
    assert_read_allowed(year, purpose)
    cfg = load_config()
    enc = cfg["mask_encoding"]
    path = source_raster(year)
    if not path.exists():
        raise DataDefect(f"Missing raster for {year}: {path}")
    with rasterio.open(path) as src:
        info: dict[str, Any] = {
            "year": int(year),
            "path": str(path),
            "width": src.width,
            "height": src.height,
            "count": src.count,
            "dtypes": list(src.dtypes),
            "crs": src.crs.to_string() if src.crs else None,
            "transform": list(tuple(src.transform)[:6]),
            "bounds": list(src.bounds),
            "res": list(src.res),
            "nodata": src.nodata,
            "descriptions": list(src.descriptions),
            "sha256": sha256_file(path),
            "aligned": False,
        }
        if src.count < 2:
            raise DataDefect(
                f"{path.name} has {src.count} band(s); frozen encoding requires "
                "band 1 water and band 2 valid."
            )
        if _transform_matches(src):
            water = src.read(enc["water_band"]) == enc["water_value"]
            valid = src.read(enc["valid_band"]) == enc["valid_value"]
            info["aligned"] = True
        else:
            grid = cfg["canonical_grid"]
            dst_transform = rasterio.Affine(*grid["transform"])
            dst_crs = grid["crs"]
            shape = (int(grid["height"]), int(grid["width"]))
            water_src = src.read(enc["water_band"])
            valid_src = src.read(enc["valid_band"])
            water_dst = np.zeros(shape, dtype="uint8")
            valid_dst = np.zeros(shape, dtype="uint8")
            reproject(
                source=(water_src == enc["water_value"]).astype("uint8"),
                destination=water_dst,
                src_transform=src.transform,
                src_crs=src.crs,
                dst_transform=dst_transform,
                dst_crs=dst_crs,
                resampling=Resampling.nearest,
                src_nodata=0,
                dst_nodata=0,
            )
            reproject(
                source=(valid_src == enc["valid_value"]).astype("uint8"),
                destination=valid_dst,
                src_transform=src.transform,
                src_crs=src.crs,
                dst_transform=dst_transform,
                dst_crs=dst_crs,
                resampling=Resampling.nearest,
                src_nodata=0,
                dst_nodata=0,
            )
            water = water_dst.astype(bool) & valid_dst.astype(bool)
            valid = valid_dst.astype(bool)
            info["aligned"] = True
            info["reprojected_from"] = {
                "crs": info["crs"],
                "transform": info["transform"],
                "width": info["width"],
                "height": info["height"],
            }
    if water.shape != (cfg["canonical_grid"]["height"], cfg["canonical_grid"]["width"]):
        raise DataDefect(f"Unexpected array shape for {year}: {water.shape}")
    return water, valid, info


def write_mask(path: Path, water: np.ndarray, valid: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    profile = _canonical_profile()
    with rasterio.open(path, "w", **profile) as dst:
        dst.write((water.astype("uint8") * 255), 1)
        dst.write((valid.astype("uint8") * 255), 2)
        dst.set_band_description(1, "water")
        dst.set_band_description(2, "valid")
        dst.update_tags(class_encoding="255=true,0=false", source="rivererosionaccretion")


def read_harmonized_mask(year: int) -> tuple[np.ndarray, np.ndarray]:
    path = project_path("processed", "masks", f"water_{int(year)}.tif")
    if not path.exists():
        raise DataDefect(f"Missing processed mask {path}")
    with rasterio.open(path) as src:
        water = src.read(1) == 255
        valid = src.read(2) == 255
    return water, valid


def read_river_mask(year: int) -> tuple[np.ndarray, np.ndarray]:
    path = project_path("processed", "river", f"river_{int(year)}.tif")
    if not path.exists():
        raise DataDefect(f"Missing river mask {path}")
    with rasterio.open(path) as src:
        water = src.read(1) == 255
        valid = src.read(2) == 255
    return water, valid


def write_geojson(path: Path, features: list[dict], crs: str = "EPSG:32646") -> None:
    """Write features with shapely geometries, converting to EPSG:4326 for web maps."""
    path.parent.mkdir(parents=True, exist_ok=True)
    out = []
    transformer = None
    if crs.upper() != "EPSG:4326":
        transformer = Transformer.from_crs(crs, "EPSG:4326", always_xy=True)
    for feat in features:
        geom = feat["geometry"]
        if transformer is not None:
            geom = shapely_transform(transformer.transform, geom)
        out.append(
            {
                "type": "Feature",
                "geometry": mapping(geom),
                "properties": feat.get("properties", {}),
            }
        )
    payload = {"type": "FeatureCollection", "name": path.stem, "features": out}
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=1, allow_nan=False)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, allow_nan=False, default=str)


def read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def nominal_date_iso(year: int) -> str:
    return nominal_date(year)


def iter_historical_years() -> list[int]:
    cfg = load_config()
    years = []
    for path in sorted(project_path(cfg["source_dir"]).glob("MNDWI_Mask_*.tif")):
        try:
            year = int(path.stem.split("_")[-1])
        except ValueError:
            continue
        if year <= int(cfg["training_cutoff_year"]):
            years.append(year)
    return sorted(set(years))
