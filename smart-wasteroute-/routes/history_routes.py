"""
routes/history_routes.py

    GET /api/history

Every route (all versions) with its trips, per-bin collection details and
depot unload events - the single source for the History page's table,
expandable trip details and compact charts. Road geometry is NOT included
here (fetch GET /api/routes/<code> for the map).

Rows archived by the ORIGINAL one-shot pipeline (collection_history rows
with no route_code) are appended as simple "legacy" entries so old data is
never hidden.
"""

import json
from flask import Blueprint
from database.db import query_all
from services import route_service
from utils.api_helpers import success

history_bp = Blueprint("history_api", __name__, url_prefix="/api/history")


@history_bp.route("", methods=["GET"])
def list_history():
    routes = route_service.get_all_routes(include_geometry=False)
    legacy = []
    for row in query_all("SELECT * FROM collection_history WHERE route_code IS NULL ORDER BY date DESC"):
        legacy.append({
            "id": row["id"], "date": row["date"], "vehicle_id": row["vehicle_id"],
            "collected_bins": json.loads(row["collected_bins"]), "total_waste": row["total_waste"],
            "total_distance": row["total_distance"], "route": json.loads(row["route"]) if row["route"] else [],
            "optimization_result": row["optimization_result"],
        })
    return success({"routes": routes, "legacy": legacy})
