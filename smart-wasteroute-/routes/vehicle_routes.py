"""
routes/vehicle_routes.py

READ-ONLY vehicle API for normal users.

    GET /api/vehicles             - every vehicle with its collector (read-only)
    GET /api/vehicles/available   - vehicles a user may pick when generating a route

Vehicle information belongs to the COLLECTOR. Creating / editing a vehicle
happens in the Collector Dashboard (routes/collector_routes.py); there is
deliberately no POST / PUT / DELETE here, so a normal user cannot manage
vehicles.
"""

from flask import Blueprint
from routes.auth_routes import require_login_api
from services import vehicle_service
from utils.api_helpers import success

vehicle_bp = Blueprint("vehicles_api", __name__, url_prefix="/api/vehicles")


@vehicle_bp.route("", methods=["GET"])
@require_login_api
def list_vehicles():
    return success([vehicle_service.vehicle_with_collector_dict(v) for v in vehicle_service.get_all_vehicles()])


@vehicle_bp.route("/available", methods=["GET"])
@require_login_api
def list_available_vehicles():
    return success(vehicle_service.get_available_vehicles_for_planning())
