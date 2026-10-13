"""
routes/dashboard_routes.py

REST API for dashboard summary statistics (Section 22 of the spec).
    GET /api/dashboard

Returns exactly the cards the Dashboard page (Step 16) will need:
    Total Bins, Critical Bins, High Priority Bins, Total Vehicles,
    Available Vehicles, Total Waste, Pending Requests,
    Completed Collections, Total Distance
"""

from flask import Blueprint
from database.db import query_all, query_one
from services import bin_service, vehicle_service
from utils.api_helpers import success

dashboard_bp = Blueprint("dashboard_api", __name__, url_prefix="/api/dashboard")


@dashboard_bp.route("", methods=["GET"])
def dashboard_stats():
    all_bins = bin_service.get_all_bins()
    active_bins = [b for b in all_bins if b.status == "ACTIVE"]
    all_vehicles = vehicle_service.get_all_vehicles()

    pending_count_row = query_one(
        "SELECT COUNT(*) as cnt FROM pending_requests WHERE status = 'PENDING'"
    )
    completed_row = query_one("SELECT COUNT(*) as cnt FROM collection_history")
    total_distance_row = query_one(
        "SELECT COALESCE(SUM(total_distance), 0) as total FROM collection_history"
    )
    active_routes_row = query_one(
        "SELECT COUNT(*) as cnt FROM routes WHERE status IN ('GENERATED', 'ASSIGNED', 'IN_PROGRESS')"
    )

    stats = {
        "total_bins": len(all_bins),
        "critical_bins": len([b for b in active_bins if b.priority == "CRITICAL"]),
        "high_priority_bins": len([b for b in active_bins if b.priority == "HIGH"]),
        "total_vehicles": len(all_vehicles),
        "available_vehicles": len([v for v in all_vehicles if v.status == "AVAILABLE"]),
        "total_waste_kg": sum(b.current_waste_kg for b in active_bins),
        "pending_requests": pending_count_row["cnt"],
        "completed_collections": completed_row["cnt"],
        "total_distance_km": round(total_distance_row["total"], 3),
        "active_routes": active_routes_row["cnt"],
        "priority_breakdown": {
            "LOW": len([b for b in active_bins if b.priority == "LOW"]),
            "MEDIUM": len([b for b in active_bins if b.priority == "MEDIUM"]),
            "HIGH": len([b for b in active_bins if b.priority == "HIGH"]),
            "CRITICAL": len([b for b in active_bins if b.priority == "CRITICAL"]),
        },
    }
    return success(stats)
