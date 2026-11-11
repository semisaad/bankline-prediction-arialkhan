from __future__ import annotations

from unittest.mock import patch

from django.test import TestCase

from api import services


class ApiContractTests(TestCase):
    def test_health(self):
        r = self.client.get("/api/health/")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data["status"], "ok")
        self.assertTrue(data["frozen"])
        self.assertEqual(data["forecast_years"], [2024, 2025, 2026])
        check_names = {c["name"] for c in data["checks"]}
        self.assertIn("manifest_code_inputs", check_names)
        self.assertIn("input:code:forecast.py", check_names)
        self.assertTrue(all(c["ok"] for c in data["checks"]))

    def test_summary(self):
        r = self.client.get("/api/forecast/summary/")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data["model"], "random_forest")
        self.assertEqual(sorted(data["by_year"]), ["2024", "2025", "2026"])
        self.assertEqual(data["n_segments_per_year"], 150)

    def test_maps_returns_layers(self):
        r = self.client.get("/api/forecast/maps/?year=2024")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data["year"], 2024)
        self.assertEqual(data["segments"]["type"], "FeatureCollection")
        self.assertEqual(len(data["segments"]["features"]), 150)
        self.assertEqual(data["banklines"]["type"], "FeatureCollection")
        self.assertTrue(data["observed_available"])
        self.assertEqual(data["observed_banklines"]["type"], "FeatureCollection")
        self.assertNotIn("landsat", str(data).lower())

    def test_risk_zones_contract(self):
        r = self.client.get("/api/forecast/risk-zones/?year=2026")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data["year"], 2026)
        self.assertEqual(data["origin_year"], 2023)
        self.assertEqual(data["threshold_m"], 15.0)
        self.assertEqual(data["total_segments"], 150)
        self.assertEqual(data["segment_counts"], {"erosion": 9, "accretion": 11, "low_movement": 130})
        self.assertEqual(data["zones"]["type"], "FeatureCollection")
        self.assertEqual(len(data["zones"]["features"]), 14)
        self.assertEqual(sum(data["zone_counts"].values()), 14)
        self.assertFalse(data["low_movement_segments_drawn"])
        self.assertEqual(data["predicted_banklines"]["type"], "FeatureCollection")
        self.assertTrue(data["limitations"])
        self.assertEqual(len(data["timeline"]), 3)
        self.assertEqual(data["timeline"][-1]["year"], 2026)
        self.assertEqual(data["timeline"][-1]["counts"], data["segment_counts"])
        self.assertIsNotNone(data["largest"])
        self.assertFalse(data["largest"]["risk_class"] == "low_movement")

        maps = self.client.get("/api/forecast/maps/?year=2026").json()
        high = {
            (f["properties"]["side"], f["properties"]["transect_id"])
            for f in maps["segments"]["features"]
            if f["properties"]["forecast_class"] != "low_movement"
        }
        covered = set()
        for feature in data["zones"]["features"]:
            p = feature["properties"]
            self.assertIn(p["risk_class"], ("erosion", "accretion"))
            self.assertEqual(p["year"], 2026)
            self.assertIn(feature["geometry"]["type"], ("Polygon", "MultiPolygon"))
            self.assertTrue(p["fill"].startswith("#"))
            self.assertTrue(p["outline"].startswith("#"))
            self.assertGreaterEqual(p["segment_count"], 1)
            self.assertGreaterEqual(p["max_abs_m"], 15.0)
            self.assertLessEqual(p["min_predicted_m"], p["max_predicted_m"])
            for transect_id in range(p["start_transect"], p["end_transect"] + 1):
                covered.add((p["side"], transect_id))
        self.assertTrue(high.issubset(covered), f"uncovered high segments: {sorted(high - covered)}")

    def test_risk_zones_year_counts(self):
        expected = {
            2024: ({"erosion": 2, "accretion": 2, "low_movement": 146}, 3),
            2025: ({"erosion": 8, "accretion": 3, "low_movement": 139}, 8),
            2026: ({"erosion": 9, "accretion": 11, "low_movement": 130}, 14),
        }
        for year, (counts, n_zones) in expected.items():
            data = self.client.get(f"/api/forecast/risk-zones/?year={year}").json()
            self.assertEqual(data["segment_counts"], counts, year)
            self.assertEqual(sum(data["zone_counts"].values()), n_zones, year)
            self.assertEqual(len(data["zones"]["features"]), n_zones, year)

    def test_risk_zones_reject_non_forecast_year(self):
        for year in ("2023", "2027", "abc"):
            r = self.client.get(f"/api/forecast/risk-zones/?year={year}")
            self.assertEqual(r.status_code, 400, year)
        self.assertEqual(self.client.get("/api/forecast/risk-zones/").status_code, 400)

    def test_maps_rejects_non_forecast_year(self):
        for year in ("2023", "2027", "abc"):
            r = self.client.get(f"/api/forecast/maps/?year={year}")
            self.assertEqual(r.status_code, 400, year)

    def test_maps_requires_year(self):
        r = self.client.get("/api/forecast/maps/")
        self.assertEqual(r.status_code, 400)

    def test_metrics_are_retrospective_and_include_baseline(self):
        r = self.client.get("/api/forecast/metrics/")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data["kind"], "retrospective_post_freeze_test_evaluation")
        self.assertEqual(data["n_good_pairs"], 398)
        self.assertIn("random_forest", data["models"])
        self.assertIn("zero", data["models"])
        self.assertFalse(data["headline"]["frozen_model_improves_mae_over_zero"])
        self.assertTrue(data["limitations"])

    def test_cors_allows_local_frontend(self):
        r = self.client.get("/api/health/", HTTP_ORIGIN="http://localhost:5173")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r["Access-Control-Allow-Origin"], "http://localhost:5173")

    def test_data_quality_checks(self):
        r = self.client.get("/api/forecast/data-quality/")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertTrue(data["freeze"]["ok"])
        self.assertTrue(data["historical_qa"]["all_recomputed_masks_match"])
        self.assertEqual(data["inventory"]["missing_years"], [1997])
        self.assertTrue(data["warnings"])


    @patch.object(services, "verify_frozen", return_value={"ok": False, "errors": ["tampered"]})
    def test_forecast_endpoints_refuse_unverified_artifacts(self, _verify):
        for path in (
            "/api/forecast/summary/",
            "/api/forecast/maps/?year=2024",
            "/api/forecast/metrics/",
            "/api/forecast/risk-zones/?year=2024",
        ):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 503, path)
            self.assertIn("provenance", response.json()["error"])

    def test_zones_contract(self):
        r = self.client.get("/api/zones/")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data["total_stretches"], 50)
        self.assertEqual(sum(data["counts"].values()), 50)
        self.assertEqual(data["counts"], {"strong": 0, "moderate": 0, "land_gained": 11, "no_clear": 39})
        self.assertEqual(data["zones"]["type"], "FeatureCollection")
        self.assertGreaterEqual(len(data["zones"]["features"]), 49)
        self.assertEqual(data["corridor"]["type"], "FeatureCollection")
        self.assertEqual(data["edges"]["type"], "FeatureCollection")
        self.assertFalse(data["relative_available"])
        self.assertIn("fallback_bounds", data)
        self.assertIn("fallback_available", data)
        west, south, east, north = data["bounds"]
        for feature in data["zones"]["features"]:
            props = feature["properties"]
            self.assertIn(props["tier"], data["counts"])
            self.assertIn(props["confidence"], ("clear", "unclear"))
        self.assertLess(west, east)
        self.assertLess(south, north)

    def test_zone_tiers_follow_fixed_rule(self):
        data = self.client.get("/api/zones/").json()
        for feature in data["zones"]["features"]:
            p = feature["properties"]
            lower, upper = p["lower_m"], p["upper_m"]
            if lower is None or upper is None:
                expected = "no_clear"
            elif lower >= 150:
                expected = "strong"
            elif lower > 0 and lower >= 30:
                expected = "moderate"
            elif upper <= -30:
                expected = "land_gained"
            else:
                expected = "no_clear"
            self.assertEqual(p["tier"], expected, p["id"])

    def test_zone_geometry_is_inside_corridor_bounds(self):
        from shapely.geometry import shape
        from shapely.ops import unary_union

        data = self.client.get("/api/zones/").json()
        west, south, east, north = data["bounds"]
        corridor = unary_union([shape(f["geometry"]) for f in data["corridor"]["features"]])
        for feature in data["zones"]["features"]:
            geom = shape(feature["geometry"])
            self.assertTrue(geom.is_valid, feature["properties"]["id"])
            self.assertTrue(corridor.buffer(1e-6).contains(geom), feature["properties"]["id"])
            minx, miny, maxx, maxy = geom.bounds
            self.assertGreaterEqual(minx, west - 0.001)
            self.assertLessEqual(maxx, east + 0.001)
            self.assertGreaterEqual(miny, south - 0.001)
            self.assertLessEqual(maxy, north + 0.001)

    def test_zone_sample_net_matches_raw_observations(self):
        import numpy as np
        from scipy.stats import theilslopes

        data = self.client.get("/api/zones/").json()
        sample = data["sample"]
        rows = sample["observations"]
        values = []
        for transect_id in sample["transect_ids"]:
            part = [(r["year"], r["outward_m"]) for r in rows if r["transect_id"] == transect_id]
            if len(part) < 3:
                continue
            years = np.array([p[0] for p in part])
            outward = np.array([p[1] for p in part])
            span = years.max() - years.min()
            values.append(theilslopes(outward, years, 0.90)[0] * span)
        self.assertAlmostEqual(float(np.median(values)), sample["net_m"], places=5)
