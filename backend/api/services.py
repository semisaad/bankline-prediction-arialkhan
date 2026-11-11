from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from django.conf import settings
from shapely.geometry import Polygon, mapping, shape
from shapely.ops import unary_union
from shapely.validation import make_valid


class ArtifactError(Exception):
    def __init__(self, message: str, status: int = 404):
        super().__init__(message)
        self.status = status


def _read_json(path: Path) -> Any:
    if not path.is_file():
        raise ArtifactError(f"Missing artifact: {path.name}", 503)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ArtifactError(f"Invalid JSON in {path.name}: {exc}", 500) from exc


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def manifest() -> dict:
    return _read_json(settings.FROZEN_DIR / "manifest.json")


def verify_frozen() -> dict:
    checks: list[dict] = []
    errors: list[str] = []
    manifest_path = settings.FROZEN_DIR / "manifest.json"
    ready_path = settings.FROZEN_DIR / "READY"

    if not manifest_path.is_file():
        return {
            "ok": False,
            "checks": [],
            "errors": ["Frozen manifest is missing."],
            "ready_sha256": None,
        }

    data = _read_json(manifest_path)
    ready = ready_path.read_text(encoding="utf-8").strip() if ready_path.is_file() else None
    manifest_hash = _sha256(manifest_path)
    checks.append(
        {
            "name": "manifest_frozen",
            "ok": data.get("frozen") is True,
            "detail": f"frozen={data.get('frozen')}",
        }
    )
    checks.append(
        {
            "name": "ready_hash",
            "ok": ready == manifest_hash,
            "detail": ready or "READY file missing",
        }
    )
    for item in data.get("files", []):
        path = settings.FROZEN_DIR / item["name"]
        ok = path.is_file() and _sha256(path) == item.get("sha256")
        checks.append(
            {
                "name": f"frozen_file:{item['name']}",
                "ok": ok,
                "detail": "sha256 matches" if ok else "missing or changed",
            }
        )

    inputs = data.get("inputs", {})
    expected = {
        "config_sha256": settings.PROJECT_ROOT / "config" / "pipeline.json",
        "dataset_sha256": settings.DATASETS_DIR / "bank_migration_dataset.csv",
        "forecast_features_sha256": settings.DATASETS_DIR / "forecast_features_2023.csv",
        "model_artifact_sha256": settings.MODELS_DIR / "final_models.joblib",
        "model_metadata_sha256": settings.MODELS_DIR / "model_metadata.json",
    }
    for key, path in expected.items():
        want = inputs.get(key)
        ok = bool(want) and path.is_file() and _sha256(path) == want
        checks.append(
            {
                "name": f"input:{key}",
                "ok": ok,
                "detail": "sha256 matches" if ok else "missing or changed",
            }
        )

    code_inputs = inputs.get("code") or {}
    checks.append(
        {
            "name": "manifest_code_inputs",
            "ok": bool(code_inputs),
            "detail": f"{len(code_inputs)} code hashes",
        }
    )
    for name, want in code_inputs.items():
        path = settings.PROJECT_ROOT / "src" / "riverforecast" / name
        ok = bool(want) and path.is_file() and _sha256(path) == want
        checks.append(
            {
                "name": f"input:code:{name}",
                "ok": ok,
                "detail": "sha256 matches" if ok else "missing or changed",
            }
        )

    errors = [c["name"] for c in checks if not c["ok"]]
    return {
        "ok": not errors,
        "checks": checks,
        "errors": errors,
        "ready_sha256": ready,
        "manifest_sha256": manifest_hash,
    }


def require_verified() -> dict:
    frozen = verify_frozen()
    if not frozen["ok"]:
        raise ArtifactError(
            "Frozen forecast provenance check failed: " + ", ".join(frozen["errors"]),
            503,
        )
    return frozen


def summary() -> dict:
    require_verified()
    data = _read_json(settings.FROZEN_DIR / "forecast_summary.json")
    data["frozen"] = data.get("status") == "frozen"
    data["n_files"] = len(manifest().get("files", []))
    return data


def forecast_years() -> list[int]:
    years = manifest().get("forecast_years", [])
    return [int(y) for y in years]


def parse_year(value: str | None) -> int:
    if value is None or str(value).strip() == "":
        raise ArtifactError("Query parameter 'year' is required.", 400)
    try:
        year = int(value)
    except (TypeError, ValueError) as exc:
        raise ArtifactError("Query parameter 'year' must be an integer.", 400) from exc
    if year not in forecast_years():
        allowed = ", ".join(str(y) for y in forecast_years())
        raise ArtifactError(f"Year {year} is not a frozen forecast year. Allowed: {allowed}.", 400)
    return year


def _load_geojson(path: Path) -> dict:
    data = _read_json(path)
    if data.get("type") != "FeatureCollection":
        raise ArtifactError(f"{path.name} is not a GeoJSON FeatureCollection.", 500)
    return data


def maps(year: int) -> dict:
    frozen = settings.FROZEN_DIR
    summary_data = summary()
    if str(year) not in summary_data.get("by_year", {}):
        raise ArtifactError(f"No frozen summary for {year}.", 404)
    year_summary = summary_data["by_year"][str(year)]
    segments = _load_geojson(frozen / f"segments_{year}.geojson")
    banklines = _load_geojson(frozen / f"banklines_{year}.geojson")
    bank_points = _load_geojson(frozen / f"bank_points_{year}.geojson")

    observed_lines_path = settings.EVALUATION_DIR / f"observed_banklines_{year}.geojson"
    observed_points_path = settings.EVALUATION_DIR / f"observed_bank_points_{year}.geojson"
    observed_lines = _load_geojson(observed_lines_path) if observed_lines_path.is_file() else None
    observed_points = _load_geojson(observed_points_path) if observed_points_path.is_file() else None

    metrics_data = _read_json(settings.EVALUATION_DIR / "metrics.json")
    model_metrics = metrics_data.get("models", {}).get("random_forest", {})
    year_metrics = model_metrics.get("by_year", {}).get(str(year))

    return {
        "year": year,
        "origin_year": summary_data.get("origin_year"),
        "training_cutoff_year": summary_data.get("training_cutoff_year"),
        "horizon_years": year_summary.get("horizon_years"),
        "model": summary_data.get("model"),
        "model_label": summary_data.get("model_label"),
        "frozen": summary_data.get("frozen"),
        "segments": segments,
        "banklines": banklines,
        "bank_points": bank_points,
        "observed_banklines": observed_lines,
        "observed_bank_points": observed_points,
        "observed_available": observed_lines is not None,
        "summary": year_summary,
        "retrospective_metrics": year_metrics,
        "legend": {
            "erosion_m": "> 15",
            "accretion_m": "< -15",
            "low_movement_m": "-15 to 15",
            "tolerance_m": summary_data.get("low_movement_tolerance_m"),
            "colors": {
                "erosion": "#c83e2d",
                "accretion": "#2478bf",
                "low_movement": "#8b9098",
                "forecast_bank": "#173b57",
                "observed_bank": "#e28a1a",
            },
        },
        "note": (
            "Forecast is conditional on the observed 2023 bank and fixed 2023 transects. "
            "Positive displacement means outward bank movement (erosion)."
        ),
        "observed_note": (
            "Observed layers are the post-freeze 2024-2026 test bank positions. "
            "Only banks marked good for measurement are drawn."
        ),
    }




RISK_CLASSES = {
    "erosion": {
        "label": "Potential erosion",
        "short_label": "Bank moved outward",
        "fill": "#c83e2d",
        "outline": "#8f271d",
    },
    "accretion": {
        "label": "Potential accretion",
        "short_label": "Bank moved inward",
        "fill": "#2f9e63",
        "outline": "#137a47",
    },
}


def _polygonal(geometry):
    if geometry is None or geometry.is_empty:
        return None
    if geometry.geom_type in {"Polygon", "MultiPolygon"}:
        return geometry
    parts = [
        part
        for part in getattr(geometry, "geoms", [])
        if part.geom_type in {"Polygon", "MultiPolygon"} and not part.is_empty
    ]
    return unary_union(parts) if parts else None


def _interval_risk_class(first: dict, second: dict) -> str | None:
    first_class = first.get("forecast_class")
    second_class = second.get("forecast_class")
    if first_class == "low_movement" and second_class == "low_movement":
        return None
    if first_class == second_class and first_class in RISK_CLASSES:
        return first_class
    first_size = abs(float(first.get("predicted_displacement_m") or 0.0))
    second_size = abs(float(second.get("predicted_displacement_m") or 0.0))
    chosen = first if first_size >= second_size else second
    chosen_class = chosen.get("forecast_class")
    return chosen_class if chosen_class in RISK_CLASSES else None


def _risk_zone_feature(
    *,
    year: int,
    side: str,
    start: int,
    end: int,
    risk_class: str,
    origin_coords: list,
    forecast_coords: list,
    segment_points: list[dict],
    corridor,
) -> dict | None:
    ring = (
        origin_coords[start : end + 2]
        + list(reversed(forecast_coords[start : end + 2]))
    )
    if len(ring) < 4:
        return None
    polygon = _polygonal(make_valid(Polygon(ring)))
    if polygon is None:
        return None
    clipped = _polygonal(make_valid(polygon.intersection(corridor)))
    if clipped is None:
        return None

    matching = [
        point
        for point in segment_points[start : end + 2]
        if point.get("forecast_class") == risk_class
    ]
    if not matching:
        return None
    values = [float(point.get("predicted_displacement_m") or 0.0) for point in matching]
    uncertainty = [
        float(point.get("ensemble_std_m") or 0.0)
        for point in matching
        if point.get("ensemble_std_m") is not None
    ]
    flagged = sum(1 for point in matching if point.get("forecast_quality") != "forecast")
    reaches = sorted({str(point.get("reach")) for point in matching if point.get("reach")})
    centroid = clipped.centroid
    style = RISK_CLASSES[risk_class]
    return {
        "type": "Feature",
        "geometry": mapping(clipped),
        "properties": {
            "id": f"risk-{year}-{side}-{start + 1}-{end + 2}",
            "year": year,
            "side": side,
            "side_label": "left" if side == "L" else "right",
            "risk_class": risk_class,
            "label": style["label"],
            "short_label": style["short_label"],
            "fill": style["fill"],
            "outline": style["outline"],
            "fill_opacity": 0.42,
            "start_transect": start + 1,
            "end_transect": end + 2,
            "covered_segments": end - start + 2,
            "segment_count": len(matching),
            "flagged_segments": flagged,
            "reach": reaches[0] if len(reaches) == 1 else "mixed",
            "reaches": reaches,
            "min_predicted_m": round(min(values), 3),
            "max_predicted_m": round(max(values), 3),
            "mean_abs_m": round(sum(abs(value) for value in values) / len(values), 3),
            "max_abs_m": round(max(abs(value) for value in values), 3),
            "mean_uncertainty_m": round(sum(uncertainty) / len(uncertainty), 3) if uncertainty else None,
            "center": [round(centroid.y, 7), round(centroid.x, 7)],
        },
    }


def forecast_risk_zones(year: int) -> dict:
    require_verified()
    frozen_dir = settings.FROZEN_DIR
    summary_data = summary()
    year_summary = summary_data.get("by_year", {}).get(str(year))
    if year_summary is None:
        raise ArtifactError(f"No frozen summary for {year}.", 404)

    segments = _load_geojson(frozen_dir / f"segments_{year}.geojson")
    banklines = _load_geojson(frozen_dir / f"banklines_{year}.geojson")
    origin_lines = _load_geojson(frozen_dir / "observed_banklines_2023.geojson")
    corridor_feature = next(
        (feature for feature in banklines["features"] if feature["properties"].get("kind") == "corridor"),
        None,
    )
    if corridor_feature is None:
        raise ArtifactError("Forecast banklines do not contain a corridor.", 500)
    corridor = shape(corridor_feature["geometry"]).buffer(1e-7)

    origin_by_side = {
        feature["properties"].get("side"): feature
        for feature in origin_lines["features"]
        if feature["properties"].get("side") in {"L", "R"}
    }
    segment_counts = {"erosion": 0, "accretion": 0, "low_movement": 0}
    zones: list[dict] = []

    for side in ("L", "R"):
        origin_feature = origin_by_side.get(side)
        if origin_feature is None:
            raise ArtifactError(f"Observed 2023 bank is missing side {side}.", 500)
        origin_coords = [tuple(value) for value in origin_feature["geometry"]["coordinates"]]
        points = sorted(
            (
                {
                    **feature["properties"],
                    "coordinates": tuple(feature["geometry"]["coordinates"][-1]),
                }
                for feature in segments["features"]
                if feature["properties"].get("side") == side
            ),
            key=lambda point: int(point["transect_id"]),
        )
        for point in points:
            segment_counts[point["forecast_class"]] = segment_counts.get(point["forecast_class"], 0) + 1
        if len(origin_coords) != len(points):
            raise ArtifactError(f"2023 {side} bank has {len(origin_coords)} points but {len(points)} forecast points.", 500)
        forecast_coords = [point["coordinates"] for point in points]

        current_class = None
        run_start = None
        for index in range(len(points) - 1):
            interval_class = _interval_risk_class(points[index], points[index + 1])
            if interval_class != current_class:
                if current_class is not None and run_start is not None:
                    feature = _risk_zone_feature(
                        year=year,
                        side=side,
                        start=run_start,
                        end=index - 1,
                        risk_class=current_class,
                        origin_coords=origin_coords,
                        forecast_coords=forecast_coords,
                        segment_points=points,
                        corridor=corridor,
                    )
                    if feature is not None:
                        zones.append(feature)
                current_class = interval_class
                run_start = index if interval_class is not None else None
        if current_class is not None and run_start is not None:
            feature = _risk_zone_feature(
                year=year,
                side=side,
                start=run_start,
                end=len(points) - 2,
                risk_class=current_class,
                origin_coords=origin_coords,
                forecast_coords=forecast_coords,
                segment_points=points,
                corridor=corridor,
            )
            if feature is not None:
                zones.append(feature)

    zones.sort(key=lambda feature: (feature["properties"]["risk_class"], feature["properties"]["side"], feature["properties"]["start_transect"]))
    zone_counts = {risk_class: 0 for risk_class in RISK_CLASSES}
    for feature in zones:
        zone_counts[feature["properties"]["risk_class"]] += 1

    unflagged = [
        feature
        for feature in zones
        if feature["properties"]["flagged_segments"] < feature["properties"]["segment_count"]
    ]
    largest = max(
        unflagged or zones,
        key=lambda feature: feature["properties"]["max_abs_m"],
        default=None,
    )
    predicted_banklines = {
        "type": "FeatureCollection",
        "features": [
            feature for feature in banklines["features"] if feature["properties"].get("kind") != "corridor"
        ],
    }
    years = forecast_years()
    timeline = []
    for item_year in years:
        item = summary_data.get("by_year", {}).get(str(item_year), {})
        timeline.append(
            {
                "year": item_year,
                "horizon_years": item.get("horizon_years"),
                "counts": item.get("counts", {}),
                "mean_m": item.get("mean_m"),
                "mean_abs_m": item.get("mean_abs_m"),
            }
        )

    return {
        "year": year,
        "origin_year": summary_data.get("origin_year"),
        "model": summary_data.get("model"),
        "model_label": summary_data.get("model_label"),
        "frozen": summary_data.get("frozen"),
        "threshold_m": summary_data.get("low_movement_tolerance_m"),
        "total_segments": summary_data.get("n_segments_per_year"),
        "segment_counts": segment_counts,
        "zone_counts": zone_counts,
        "low_movement_segments_drawn": False,
        "zones": {"type": "FeatureCollection", "features": zones},
        "predicted_banklines": predicted_banklines,
        "timeline": timeline,
        "legend": {
            "erosion": RISK_CLASSES["erosion"],
            "accretion": RISK_CLASSES["accretion"],
            "low_movement": {
                "label": "Little predicted change",
                "fill": "#c9ced2",
                "outline": "#7b848a",
            },
            "predicted_bank": "#173b57",
        },
        "largest": largest["properties"] if largest is not None else None,
        "note": (
            "Risk zones show where the frozen model predicts a bank segment to move more than "
            f"{summary_data.get('low_movement_tolerance_m')} m between {summary_data.get('origin_year')} and {year}. "
            "Each polygon spans the 2023 bank and the predicted bank. Low-movement segments are counted but not drawn. "
            "These are scenario areas, not safety ratings or observed erosion."
        ),
        "limitations": [
            "The frozen model does not beat a no-change baseline on overall 2024-2026 test MAE.",
            "Only 3 of 22 observed outward events and 2 of 42 observed inward events were classified correctly.",
            "Zones are conditional on the observed 2023 bank and are not a hydrodynamic or sediment-transport simulation.",
            "Flagged segments are still shown where the model produced a class; their origin flags are reported in the popup.",
        ],
    }

def metrics() -> dict:
    require_verified()
    data = _read_json(settings.EVALUATION_DIR / "metrics.json")
    audit = _read_json(settings.EVALUATION_DIR / "test_data_audit.json")
    metadata = _read_json(settings.MODELS_DIR / "model_metadata.json")
    models = data.get("models", {})
    rf = models.get("random_forest", {})
    zero = models.get("zero", {})
    return {
        "kind": "retrospective_post_freeze_test_evaluation",
        "test_years": data.get("test_years"),
        "origin_year": data.get("origin_year"),
        "n_pairs": data.get("n_pairs"),
        "n_good_pairs": data.get("n_good_pairs"),
        "n_flagged_or_invalid": data.get("n_flagged_or_invalid"),
        "low_movement_tolerance_m": data.get("low_movement_tolerance_m"),
        "models": models,
        "event_audit": data.get("event_audit"),
        "largest_errors": data.get("largest_errors"),
        "selected_model": metadata.get("selected_model"),
        "selected_label": metadata.get("selected_label"),
        "selection_rule": metadata.get("selection_rule"),
        "validation_aggregate_metrics": metadata.get("aggregate_metrics"),
        "validation_origins": metadata.get("validation_origins"),
        "test_data_audit": audit,
        "headline": {
            "frozen_model": metadata.get("selected_model"),
            "n_good_pairs": data.get("n_good_pairs"),
            "frozen_model_mae_m": rf.get("mae_m"),
            "zero_baseline_mae_m": zero.get("mae_m"),
            "frozen_model_rmse_m": rf.get("rmse_m"),
            "zero_baseline_rmse_m": zero.get("rmse_m"),
            "frozen_model_improves_mae_over_zero": (
                rf.get("mae_m") is not None
                and zero.get("mae_m") is not None
                and rf["mae_m"] < zero["mae_m"]
            ),
            "directional_accuracy_moving": rf.get("directional_accuracy_moving"),
            "low_movement_f1": rf.get("low_movement_f1"),
        },
        "limitations": [
            "The frozen random forest does not beat the zero-change baseline on overall test MAE; it is retained because it was selected and frozen before test access, and it does not move as often as the baseline.",
            "Only 3 of 22 observed erosion events and 2 of 42 observed accretion events were classified correctly.",
            "Bank movement is inferred from annual water masks and is not a direct sediment-transport measurement.",
            "Exact observation dates are unavailable; labels use a nominal 25 March date.",
            "Test results cover 2024-2026 in one river reach and should not be generalized without new validation.",
        ],
    }


def zones() -> dict:
    zone_dir = settings.DERIVED_DIR / "zones"
    summary_data = _read_json(zone_dir / "summary.json")
    summary_data["zones"] = _load_geojson(zone_dir / "zones.geojson")
    summary_data["corridor"] = _load_geojson(zone_dir / "corridor.geojson")
    summary_data["edges"] = _load_geojson(zone_dir / "edges.geojson")
    overlay = settings.BASEMAP_DIR / "sentinel2_overlay.png"
    meta = settings.BASEMAP_DIR / "basemap.json"
    fallback_available = False
    fallback_bounds = None
    if overlay.is_file() and meta.is_file():
        try:
            meta_data = _read_json(meta)
            bounds = meta_data.get("bounds")
            if (
                isinstance(bounds, list)
                and len(bounds) == 4
                and all(isinstance(value, (int, float)) for value in bounds)
                and bounds[0] < bounds[2]
                and bounds[1] < bounds[3]
            ):
                fallback_available = True
                fallback_bounds = [float(value) for value in bounds]
        except (ArtifactError, TypeError, ValueError):
            fallback_available = False
    summary_data["fallback_available"] = fallback_available
    summary_data["fallback_bounds"] = fallback_bounds
    summary_data["fallback_image_url"] = "/api/basemap/image/" if fallback_available else None
    return summary_data


def data_quality() -> dict:
    inventory = _read_json(settings.REPORTS_DIR / "inventory.json")
    qa2 = _read_json(settings.VALIDATION_DIR / "qa_pass2.json")
    qa3 = _read_json(settings.VALIDATION_DIR / "qa_pass3.json")
    audit = _read_json(settings.EVALUATION_DIR / "test_data_audit.json")
    frozen = verify_frozen()
    repairs = sorted(int(y) for y in qa3.get("repairs", {}))
    flagged = [
        {
            "from_year": p.get("from_year"),
            "to_year": p.get("to_year"),
            "flags": p.get("flags", []),
            "best_iou_shift": p.get("best_iou_shift"),
        }
        for p in qa2.get("flagged_pairs", [])
    ]
    return {
        "inventory": {
            "file_count": inventory.get("file_count"),
            "years": inventory.get("years"),
            "missing_years": inventory.get("missing_years"),
            "grid_variants_historical": inventory.get("grid_variants_historical"),
            "temporal_ambiguity": inventory.get("temporal_ambiguity"),
            "test_year_lock": inventory.get("test_year_lock"),
        },
        "historical_qa": {
            "n_pairs": len(qa2.get("pairs", [])),
            "n_flagged_pairs": len(qa2.get("flagged_pairs", [])),
            "flagged_pairs": flagged,
            "all_recomputed_masks_match": qa3.get("all_recomputed_masks_match"),
            "all_polygons_valid": qa3.get("all_polygons_valid"),
            "all_selected_subset_of_valid_water": qa3.get("all_selected_subset_of_valid_water"),
            "all_excluded_disjoint": qa3.get("all_excluded_disjoint"),
            "all_excluded_subset_of_water": qa3.get("all_excluded_subset_of_water"),
            "all_river_plus_excluded_equals_water": qa3.get("all_river_plus_excluded_equals_water"),
            "max_polygon_vs_mask_area_difference_m2": qa3.get("max_polygon_vs_mask_area_difference_m2"),
            "polygon_repair_years": repairs,
        },
        "test_extraction": audit.get("years"),
        "freeze": {
            "ok": frozen["ok"],
            "errors": frozen["errors"],
            "ready_sha256": frozen["ready_sha256"],
            "frozen_utc": audit.get("manifest", {}).get("frozen_utc"),
            "forecast_years": audit.get("manifest", {}).get("forecast_years"),
        },
        "warnings": [
            "The 1997 Landsat mask is missing. Intervals spanning that gap cover two years and are allowed.",
            "Filenames contain only a year; labels use a nominal 25 March date from the dry-season composite description.",
            "Selected river polygons near the image border can be cut off by the study extent.",
            "Flagged transects are excluded from metrics; 12 of 150 forecast segments per year carry flagged 2023 origins.",
            "Polygon repairs were applied for historical masks; the mask itself is the area authority.",
            "Forecast maps are scenario-conditional, not hydrodynamic predictions.",
        ],
    }


def health() -> dict:
    frozen = verify_frozen()
    data = manifest() if frozen.get("manifest_sha256") else {}
    return {
        "status": "ok" if frozen["ok"] else "degraded",
        "service": "river-bank-forecast-api",
        "project_root": str(settings.PROJECT_ROOT),
        "frozen": frozen["ok"],
        "origin_year": data.get("origin_year"),
        "forecast_years": data.get("forecast_years"),
        "training_cutoff_year": data.get("training_cutoff_year"),
        "model": data.get("model"),
        "model_label": data.get("model_label"),
        "checks": frozen["checks"],
        "errors": frozen["errors"],
        "ready_sha256": frozen.get("ready_sha256"),
    }
