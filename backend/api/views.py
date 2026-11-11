from __future__ import annotations

import logging

from django.http import FileResponse
from rest_framework.decorators import api_view
from rest_framework.response import Response

from django.conf import settings

from . import services

logger = logging.getLogger(__name__)


def _error(exc: services.ArtifactError) -> Response:
    return Response({"error": str(exc)}, status=exc.status)


def _unexpected(exc: Exception) -> Response:
    logger.exception("Unhandled API error")
    return Response({"error": "Internal artifact read error."}, status=500)


@api_view(["GET"])
def health(request):
    try:
        payload = services.health()
    except Exception as exc:
        logger.exception("Health check failed")
        return Response({"status": "error", "error": str(exc)}, status=503)
    status_code = 200 if payload["status"] == "ok" else 503
    return Response(payload, status=status_code)


@api_view(["GET"])
def forecast_summary(request):
    try:
        return Response(services.summary())
    except services.ArtifactError as exc:
        return _error(exc)
    except Exception as exc:
        return _unexpected(exc)


@api_view(["GET"])
def forecast_maps(request):
    try:
        year = services.parse_year(request.query_params.get("year"))
        return Response(services.maps(year))
    except services.ArtifactError as exc:
        return _error(exc)
    except Exception as exc:
        return _unexpected(exc)


@api_view(["GET"])
def forecast_risk_zones(request):
    try:
        year = services.parse_year(request.query_params.get("year"))
        return Response(services.forecast_risk_zones(year))
    except services.ArtifactError as exc:
        return _error(exc)
    except Exception as exc:
        return _unexpected(exc)


@api_view(["GET"])
def forecast_metrics(request):
    try:
        return Response(services.metrics())
    except services.ArtifactError as exc:
        return _error(exc)
    except Exception as exc:
        return _unexpected(exc)


@api_view(["GET"])
def forecast_quality(request):
    try:
        return Response(services.data_quality())
    except services.ArtifactError as exc:
        return _error(exc)
    except Exception as exc:
        return _unexpected(exc)


@api_view(["GET"])
def zones(request):
    try:
        return Response(services.zones())
    except services.ArtifactError as exc:
        return _error(exc)
    except Exception as exc:
        return _unexpected(exc)


def basemap_image(request):
    path = settings.BASEMAP_DIR / "sentinel2_overlay.png"
    if not path.is_file():
        return Response({"error": "Basemap image is not available."}, status=404)
    return FileResponse(path.open("rb"), content_type="image/png")
