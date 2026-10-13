"""
End-to-end backend test of the redesigned workflow (uses tests/mock_osrm.py as the
routing engine because the sandbox has no internet). Run:  python -m unittest tests.test_workflow -v
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import Config  # noqa: E402

_tmp = tempfile.mkdtemp()
Config.DATABASE_PATH = os.path.join(_tmp, "test.db")

from tests import mock_osrm  # noqa: E402
_server, _url = mock_osrm.start()
Config.OSRM_BASE_URL = _url
Config.OSRM_RETRIES = 0

from app import app  # noqa: E402

DEPOT = (18.5204, 73.8567)


def post(c, url, body=None):
    r = c.post(url, json=body or {})
    return r.status_code, r.get_json()


class WorkflowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.user = app.test_client()
        cls.collector = app.test_client()
        cls.anon = app.test_client()
        s, b = post(cls.user, "/api/auth/register", {"full_name": "Test User", "date_of_birth": "2000-01-01",
                    "email": "t@example.com", "mobile": "9876543210", "password": "secret1", "confirm_password": "secret1"})
        assert s == 201, b
        s, b = post(cls.user, "/api/auth/login", {"identifier": "t@example.com", "password": "secret1"})
        assert s == 200, b
        s, b = post(cls.user, "/api/depot", {"name": "Pune Depot", "latitude": DEPOT[0], "longitude": DEPOT[1]})
        assert s == 200, b
        s, b = post(cls.collector, "/api/auth/collector/register", {"name": "Rahul", "mobile": "9000000009", "password": "secret1"})
        assert s == 201, b
        cls.col_code = b["data"]["collector_code"]
        s, b = post(cls.collector, "/api/auth/collector/login", {"collector_code": cls.col_code, "password": "secret1"})
        assert s == 200, b

    # ---- helpers ----
    def make_bin(self, name, level, kg, dlat, dlng, cap=200):
        r = self.user.post("/api/bins", data={"bin_id": f"T{abs(hash((name, dlat)))%10**8}", "name": name,
                           "latitude": DEPOT[0] + dlat, "longitude": DEPOT[1] + dlng, "waste_level": level,
                           "current_waste_kg": kg, "maximum_capacity_kg": cap},
                           content_type="multipart/form-data")
        self.assertEqual(r.status_code, 201, r.get_json())
        return r.get_json()["data"]["bin_id"]

    def test_01_vehicle_ownership_and_permissions(self):
        # no vehicle yet -> not offered to planning
        self.assertEqual(self.user.get("/api/vehicles/available").get_json()["data"], [])
        # normal user cannot create/edit/delete vehicles
        for m in ("post", "put", "delete"):
            self.assertEqual(getattr(self.user, m)("/api/vehicles").status_code, 405)
        self.assertEqual(post(self.user, "/api/collector/vehicle", {"vehicle_number": "X"})[0], 401)
        # collector registers + edits own vehicle
        s, b = post(self.collector, "/api/collector/vehicle", {"vehicle_number": "MH-12-AB-1234", "vehicle_type": "Van", "maximum_capacity_kg": 500})
        self.assertEqual(s, 201, b)
        self.assertEqual(post(self.collector, "/api/collector/vehicle", {"vehicle_number": "dup", "maximum_capacity_kg": 1})[0], 400)
        r = self.collector.put("/api/collector/vehicle", json={"vehicle_type": "Waste Collector Van", "current_load_kg": 0})
        self.assertEqual(r.get_json()["data"]["vehicle_type"], "Waste Collector Van")
        v = self.user.get("/api/vehicles/available").get_json()["data"]
        self.assertEqual(len(v), 1)
        self.assertEqual(v[0]["collector"]["name"], "Rahul")
        self.assertEqual(v[0]["available_capacity_kg"], 500)
        self.__class__.vehicle_id = v[0]["vehicle_id"]
        # password hash never leaks
        self.assertNotIn("password_hash", self.anon.get("/api/collectors").get_data(as_text=True))

    def test_02_full_scenario(self):
        vid = self.__class__.vehicle_id
        C = self.make_bin("Bin C", 92, 150, 0.010, 0.002)
        A = self.make_bin("Bin A", 85, 100, 0.004, 0.008)
        D = self.make_bin("Bin D", 65, 180, -0.006, 0.006)
        B = self.make_bin("Bin B", 45, 120, -0.004, -0.009)
        E = self.make_bin("Bin E", 30, 60, 0.002, -0.012)
        bins = [A, B, C, D, E]

        # ---- priority analysis: road distance, 1 km = 10 min, balanced order
        s, b = post(self.user, "/api/planning/analyze", {"bin_ids": bins, "priority_mode": "BALANCED", "vehicle_id": vid})
        self.assertEqual(s, 200, b)
        an = b["data"]
        self.assertTrue(an["road_ok"])
        self.assertEqual([x["name"] for x in an["bins"]], ["Bin C", "Bin A", "Bin D", "Bin B", "Bin E"])
        self.assertEqual(an["minutes_per_km"], Config.ESTIMATED_MINUTES_PER_KM)
        for x in an["bins"]:
            self.assertAlmostEqual(x["travel_minutes"], round(x["distance_km"] * Config.ESTIMATED_MINUTES_PER_KM, 1), places=1)
            self.assertGreater(x["distance_km"], x["straight_line_km"] - 1e-9)  # road >= straight line
            self.assertTrue(x["reason"])
        self.assertEqual(an["bins"][0]["priority"], "CRITICAL")

        # other modes reorder
        s, b = post(self.user, "/api/planning/analyze", {"bin_ids": bins, "priority_mode": "SHORTEST_DISTANCE"})
        dists = [x["distance_km"] for x in b["data"]["bins"]]
        self.assertEqual(dists, sorted(dists))

        # ---- generate: capacity 500 -> 2 trips (C,A,D = 430 | B,E = 180), depot return between
        s, b = post(self.user, "/api/planning/generate", {"bin_ids": bins, "vehicle_id": vid, "priority_mode": "BALANCED"})
        self.assertEqual(s, 200, b)
        plan = b["data"]
        self.assertEqual(plan["totals"]["trips"], 2)
        t1, t2 = plan["trips"]
        self.assertEqual([s["location_name"] for s in t1["steps"]], ["Pune Depot", "Bin C", "Bin A", "Bin D", "Pune Depot"])
        self.assertEqual([s["location_name"] for s in t2["steps"]], ["Pune Depot", "Bin B", "Bin E", "Pune Depot"])
        self.assertEqual(t1["planned_waste_kg"], 430)
        self.assertTrue(t1["ended_by_capacity"] and not t2["ended_by_capacity"])
        for t in plan["trips"]:
            self.assertLessEqual(t["planned_waste_kg"], t["capacity_kg"])
            for st in t["steps"][1:]:
                self.assertGreaterEqual(len(st["segment_geometry"]), 3)  # road polyline, not a 2-point straight line
                self.assertAlmostEqual(st["segment_time_min"], round(st["segment_distance_km"] * Config.ESTIMATED_MINUTES_PER_KM, 1), places=1)
        self.assertEqual(plan["dsa"]["stack_trace"][0]["unwound"][0], "Pune Depot")
        self.assertEqual(plan["dsa"]["stack_trace"][0]["pushed"][1], "Bin C")
        total_km = sum(s["segment_distance_km"] for t in plan["trips"] for s in t["steps"])
        self.assertAlmostEqual(plan["totals"]["distance_km"], total_km, places=2)

        # nothing saved yet
        self.assertEqual(self.user.get("/api/routes").get_json()["data"], [])
        # ---- save
        s, b = post(self.user, "/api/planning/save", {"draft_token": plan["draft_token"]})
        self.assertEqual(s, 201, b)
        route = b["data"]
        code = route["route_code"]
        self.assertEqual(code, "R001")
        self.assertEqual(route["status"], "ASSIGNED")
        self.assertEqual(route["collector"]["name"], "Rahul")
        self.assertEqual(post(self.user, "/api/planning/save", {"draft_token": plan["draft_token"]})[0], 400)  # draft consumed
        self.assertEqual(self.user.get("/api/vehicles/available").get_json()["data"], [])  # vehicle now on route

        # ---- collector executes
        my = self.collector.get("/api/collector/my-route").get_json()["data"]
        self.assertEqual(my["route_code"], code)
        P = "/api/collector/"
        s, b = post(self.collector, P + "collect-stop", {"route_code": code, "bin_id": C})
        self.assertEqual(s, 400)  # must start first
        s, b = post(self.collector, P + "start-collection", {"route_code": code, "bin_id": A})
        self.assertEqual(s, 400)  # wrong order
        for bid in (C, A, D):
            self.assertEqual(post(self.collector, P + "start-collection", {"route_code": code, "bin_id": bid})[0], 200)
            s, b = post(self.collector, P + "collect-stop", {"route_code": code, "bin_id": bid})
            self.assertEqual(s, 200, b)
        self.assertEqual(b["data"]["trips"][0]["steps"][3]["actual_load_after_kg"], 430)
        # next trip is locked until the vehicle returns to the depot
        self.assertEqual(post(self.collector, P + "start-collection", {"route_code": code, "bin_id": B})[0], 400)
        s, b = post(self.collector, P + "return-to-depot", {"route_code": code})
        self.assertEqual(s, 200, b)
        ev = b["data"]["trips"][0]["depot_event"]
        self.assertEqual((ev["reason"], ev["unloaded_kg"], ev["vehicle_load_after_kg"]), ("CAPACITY", 430, 0))
        self.assertEqual(post(self.collector, P + "return-to-depot", {"route_code": code})[0], 400)  # trip 2 not done
        for bid in (B, E):
            post(self.collector, P + "start-collection", {"route_code": code, "bin_id": bid})
            s, b = post(self.collector, P + "collect-stop", {"route_code": code, "bin_id": bid})
            self.assertEqual(s, 200, b)
        s, b = post(self.collector, P + "return-to-depot", {"route_code": code})
        self.assertEqual(b["data"]["status"], "COMPLETED")
        self.assertEqual(b["data"]["trips"][1]["depot_event"]["reason"], "FINAL")
        # vehicle freed, load zero
        veh = self.collector.get("/api/collector/vehicle").get_json()["data"]
        self.assertEqual((veh["status"], veh["current_load_kg"]), ("AVAILABLE", 0))

        # ---- stored collection events
        from database.db import query_all
        evs = query_all("SELECT * FROM collection_events ORDER BY sequence_number")
        self.assertEqual([e["sequence_number"] for e in evs], [1, 2, 3, 4, 5])
        self.assertEqual([e["waste_collected_kg"] for e in evs], [150, 100, 180, 120, 60])
        self.assertTrue(all(e["collected_at"] and e["collector_id"] == self.col_code for e in evs))
        cum = [e["distance_travelled_km"] for e in evs]
        self.assertEqual(cum, sorted(cum))

        # ---- history + reports
        h = self.user.get("/api/history").get_json()["data"]["routes"]
        self.assertEqual(len(h), 1)
        self.assertEqual(h[0]["total_trips"], 2)
        rep = self.user.get("/api/reports/summary").get_json()["data"]
        pv = rep["per_vehicle"][0]
        self.assertEqual((pv["trips"], pv["waste_filled_times"]), (2, 1))
        self.assertAlmostEqual(pv["distance_km"], round(plan["totals"]["distance_km"], 2), places=1)
        self.assertEqual(rep["total_waste_kg"], 610)
        self.assertEqual(rep["total_bins_collected"], 5)
        self.assertEqual(rep["total_routes"], 1)

    def test_03_capacity_edge_cases(self):
        vid = self.__class__.vehicle_id
        big = self.make_bin("Huge", 99, 650, 0.02, 0.02, cap=700)
        ok = self.make_bin("Small", 50, 40, 0.001, 0.001)
        s, b = post(self.user, "/api/planning/analyze", {"bin_ids": [big, ok], "vehicle_id": vid})
        flagged = [x for x in b["data"]["bins"] if x.get("warning")]
        self.assertEqual(flagged[0]["warning"], "Bin cannot be collected because its waste quantity exceeds vehicle capacity.")
        s, b = post(self.user, "/api/planning/generate", {"bin_ids": [big, ok], "vehicle_id": vid})
        self.assertEqual(s, 200, b)
        self.assertEqual(len(b["data"]["unfitted"]), 1)
        self.assertEqual(b["data"]["totals"]["bins"], 1)
        post(self.user, "/api/planning/save", {"draft_token": b["data"]["draft_token"]})
        self.__class__.edge_route = b["data"]
        # the oversize bin stays pending (not assigned)
        from services import bin_service
        self.assertEqual(bin_service.get_bin(big).status, "ACTIVE")

    def test_04_update_creates_new_version(self):
        vid = self.__class__.vehicle_id
        base = self.user.get("/api/routes?status=ASSIGNED").get_json()["data"]
        self.assertEqual(len(base), 1)
        base_code = base[0]["route_code"]  # route made in test_03
        new_bin = self.make_bin("Late bin", 95, 30, -0.01, 0.01)
        s, b = post(self.user, "/api/planning/generate", {"bin_ids": [new_bin], "base_route_code": base_code})
        self.assertEqual(s, 200, b)
        self.assertEqual(b["data"]["totals"]["bins"], 2)
        s, saved = post(self.user, "/api/planning/save", {"draft_token": b["data"]["draft_token"]})
        self.assertEqual(s, 201, saved)
        self.assertEqual(saved["data"]["route_code"], f"{base_code}-V2")
        self.assertEqual(saved["data"]["label"], "Updated (V2)")
        old = self.user.get(f"/api/routes/{base_code}").get_json()["data"]
        self.assertEqual(old["status"], "SUPERSEDED")
        self.assertEqual(old["label"], "Original")
        self.assertEqual(old["total_bins"], 1)  # original untouched
        codes = [r["route_code"] for r in self.user.get("/api/history").get_json()["data"]["routes"]]
        self.assertIn(base_code, codes)
        self.assertIn(f"{base_code}-V2", codes)
        # only the new version is active for the collector
        self.assertEqual(self.collector.get("/api/collector/my-route").get_json()["data"]["route_code"], f"{base_code}-V2")
        # started routes cannot be updated
        post(self.collector, "/api/collector/start-collection",
             {"route_code": f"{base_code}-V2", "bin_id": saved["data"]["trips"][0]["steps"][1]["bin_id"]})
        s, b = post(self.user, "/api/planning/generate", {"bin_ids": [], "base_route_code": f"{base_code}-V2"})
        self.assertEqual(s, 400)

    def test_05_routing_failure_is_honest(self):
        # a second, idle vehicle (the first one is busy on a started route by now)
        c2 = app.test_client()
        s, b = post(c2, "/api/auth/collector/register", {"name": "Suresh", "mobile": "9000000010", "password": "secret1"})
        post(c2, "/api/auth/collector/login", {"collector_code": b["data"]["collector_code"], "password": "secret1"})
        post(c2, "/api/collector/vehicle", {"vehicle_number": "MH-12-ZZ-9999", "maximum_capacity_kg": 300})
        vid2 = self.user.get("/api/vehicles/available").get_json()["data"][0]["vehicle_id"]
        good = Config.OSRM_BASE_URL
        Config.OSRM_BASE_URL = "http://127.0.0.1:9"  # nothing listens here
        try:
            b1 = self.make_bin("Offline bin", 70, 20, 0.03, 0.03)
            s, b = post(self.user, "/api/planning/analyze", {"bin_ids": [b1]})
            self.assertEqual(s, 200)
            self.assertFalse(b["data"]["road_ok"])
            self.assertIn("unreachable", b["data"]["warning"])
            self.assertIsNone(b["data"]["bins"][0]["distance_km"])
            self.assertIsNone(b["data"]["bins"][0]["travel_minutes"])
            s, b = post(self.user, "/api/planning/generate", {"bin_ids": [b1], "vehicle_id": vid2})
            self.assertEqual(s, 503)
            self.assertTrue(b["osrm_unavailable"])
            self.assertNotIn("trips", b)
        finally:
            Config.OSRM_BASE_URL = good


if __name__ == "__main__":
    unittest.main()


class ZPageSmokeTest(unittest.TestCase):  # named Z... so it runs after WorkflowTest
    """Every page renders; removed pages are really gone."""

    def test_pages(self):
        user = app.test_client()
        post(user, "/api/auth/login", {"identifier": "t@example.com", "password": "secret1"})
        for url in ("/dashboard", "/add-bin", "/requests", "/history", "/reports", "/profile", "/data-structures"):
            self.assertEqual(user.get(url).status_code, 200, url)
        for url in ("/routes", "/map", "/vehicles", "/bins", "/route/R001"):
            self.assertEqual(user.get(url).status_code, 404, url)
        nav = user.get("/dashboard").get_data(as_text=True)
        for gone in ("href=\"/routes\"", "href=\"/map\"", "href=\"/vehicles\""):
            self.assertNotIn(gone, nav)
        col = app.test_client()
        post(col, "/api/auth/collector/login", {"collector_code": "COL001", "password": "secret1"})
        self.assertEqual(col.get("/collector/dashboard").status_code, 200)

    def test_data_structures_page_api_still_works(self):
        user = app.test_client()
        post(user, "/api/auth/login", {"identifier": "t@example.com", "password": "secret1"})
        r = user.get("/api/data-structures/live")
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True)[:300])
        self.assertTrue(r.get_json()["success"])
