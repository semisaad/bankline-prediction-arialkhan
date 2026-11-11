from django.urls import path

from . import views

urlpatterns = [
    path("health/", views.health, name="health"),
    path("forecast/summary/", views.forecast_summary, name="forecast-summary"),
    path("forecast/maps/", views.forecast_maps, name="forecast-maps"),
    path("forecast/metrics/", views.forecast_metrics, name="forecast-metrics"),
    path("forecast/risk-zones/", views.forecast_risk_zones, name="forecast-risk-zones"),
    path("forecast/data-quality/", views.forecast_quality, name="forecast-data-quality"),
    path("zones/", views.zones, name="zones"),
    path("basemap/image/", views.basemap_image, name="basemap-image"),
]
