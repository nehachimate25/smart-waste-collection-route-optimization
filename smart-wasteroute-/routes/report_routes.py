"""
routes/report_routes.py

    GET /api/reports/summary

Computed from the real stored data (route_trips, collection_events,
depot_events, plus legacy collection_history rows) - nothing hard-coded.

Definitions used on the Reports page:
    Trips               completed trips (a trip = depot -> bins -> depot)
    Waste Filled Times  times the vehicle had to return to the depot because it
                        was full (depot_events reason CAPACITY) or came back
                        loaded to its full capacity
    Distance Covered    total ROAD distance of the completed trips
    Utilization %       waste collected / capacity offered by the completed trips
"""

import json
from collections import defaultdict
from flask import Blueprint
from database.db import query_all
from utils.api_helpers import success

report_bp = Blueprint("reports_api", __name__, url_prefix="/api/reports")


@report_bp.route("/summary", methods=["GET"])
def reports_summary():
    vehicle_names = {r["vehicle_id"]: r["vehicle_number"] for r in query_all("SELECT vehicle_id, vehicle_number FROM vehicles")}
    per_vehicle = defaultdict(lambda: {"trips": 0, "filled": 0, "distance": 0.0, "waste": 0.0, "capacity": 0.0})
    bin_frequency = defaultdict(int)

    trip_rows = query_all(
        """SELECT t.id, t.capacity_kg, t.total_distance_km, r.vehicle_id,
                  COALESCE((SELECT SUM(waste_collected_kg) FROM collection_events WHERE trip_id = t.id), 0) AS waste
           FROM route_trips t JOIN routes r ON r.id = t.route_id
           WHERE t.status = 'COMPLETED'""")
    for t in trip_rows:
        v = per_vehicle[t["vehicle_id"]]
        v["trips"] += 1
        v["distance"] += t["total_distance_km"]
        v["waste"] += t["waste"]
        v["capacity"] += t["capacity_kg"]

    for e in query_all(
            """SELECT r.vehicle_id, d.reason, d.unloaded_kg, d.vehicle_capacity_kg
               FROM depot_events d JOIN routes r ON r.id = d.route_id"""):
        if e["reason"] == "CAPACITY" or (e["reason"] == "FINAL" and e["vehicle_capacity_kg"] > 0
                                         and e["unloaded_kg"] >= e["vehicle_capacity_kg"] - 1e-9):
            per_vehicle[e["vehicle_id"]]["filled"] += 1

    for e in query_all("SELECT bin_id, COUNT(*) AS c FROM collection_events GROUP BY bin_id"):
        bin_frequency[e["bin_id"]] += e["c"]

    legacy_routes = 0
    for row in query_all("SELECT * FROM collection_history WHERE route_code IS NULL"):
        legacy_routes += 1
        v = per_vehicle[row["vehicle_id"]]
        v["trips"] += 1
        v["distance"] += row["total_distance"]
        v["waste"] += row["total_waste"]
        for bin_id in json.loads(row["collected_bins"]):
            bin_frequency[bin_id] += 1

    routes_completed = query_all("SELECT COUNT(*) AS c FROM routes WHERE status = 'COMPLETED'")[0]["c"] + legacy_routes
    total_trips = sum(v["trips"] for v in per_vehicle.values())
    total_waste = sum(v["waste"] for v in per_vehicle.values())
    total_distance = sum(v["distance"] for v in per_vehicle.values())
    total_capacity = sum(v["capacity"] for v in per_vehicle.values())
    bins_collected = sum(bin_frequency.values())

    per_vehicle_list = []
    for vid, v in sorted(per_vehicle.items()):
        per_vehicle_list.append({
            "vehicle_id": vid, "vehicle_name": vehicle_names.get(vid, vid),
            "trips": v["trips"], "waste_filled_times": v["filled"],
            "distance_km": round(v["distance"], 2), "total_waste_kg": round(v["waste"], 2),
            "utilization_percent": round(100 * v["waste"] / v["capacity"], 1) if v["capacity"] else None,
        })

    top_bins = sorted(bin_frequency.items(), key=lambda item: item[1], reverse=True)[:10]
    return success({
        "total_waste_kg": round(total_waste, 2),
        "total_routes": routes_completed,
        "total_trips": total_trips,
        "total_bins_collected": bins_collected,
        "total_distance_km": round(total_distance, 2),
        "avg_distance_per_trip_km": round(total_distance / total_trips, 2) if total_trips else 0,
        "avg_waste_per_trip_kg": round(total_waste / total_trips, 2) if total_trips else 0,
        "vehicle_utilization_percent": round(100 * total_waste / total_capacity, 1) if total_capacity else None,
        "per_vehicle": per_vehicle_list,
        "top_collected_bins": [{"bin_id": b, "times_collected": c} for b, c in top_bins],
    })
