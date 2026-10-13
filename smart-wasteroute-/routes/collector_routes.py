"""
routes/collector_routes.py

Collector-facing API - requires a COLLECTOR session (not a user session).

    GET  /api/collector/my-route           - active route (ASSIGNED / IN_PROGRESS) with trips + road geometry
    GET  /api/collector/routes             - every route ever assigned to this collector
    POST /api/collector/start-collection   - "Start Collection" on the NEXT bin in sequence
    POST /api/collector/collect-stop       - "Mark Collected" for that bin
    POST /api/collector/return-to-depot    - end of trip: unload at the depot (next trip / route complete)
    GET  /api/collector/vehicle            - the collector's own vehicle
    POST /api/collector/vehicle            - register a vehicle (only if none yet)
    PUT  /api/collector/vehicle            - update own vehicle information
    GET/PUT /api/collector/profile         - own profile
    GET  /api/collectors                   - list collectors
"""

from functools import wraps
from flask import Blueprint, request, session
from database.db import execute
from services import route_service, auth_service, vehicle_service
from services.route_service import RouteLifecycleError
from services.vehicle_service import VehicleServiceError
from utils.api_helpers import success, error

collector_bp = Blueprint("collector_api", __name__, url_prefix="/api/collector")
collectors_bp = Blueprint("collectors_api", __name__, url_prefix="/api/collectors")


def require_collector_session(view_func):
    @wraps(view_func)
    def wrapped(*args, **kwargs):
        if session.get("role") != "collector" or not session.get("collector_code"):
            return error("Please log in as a collector to continue.", status=401)
        return view_func(*args, **kwargs)
    return wrapped


@collector_bp.route("/my-route", methods=["GET"])
@require_collector_session
def my_route():
    return success(route_service.get_active_route_for_collector(session["collector_code"]))


@collector_bp.route("/routes", methods=["GET"])
@require_collector_session
def my_routes():
    return success(route_service.get_routes_for_collector(session["collector_code"]))


def _stop_action(fn):
    body = request.get_json(silent=True)
    if not body or "route_code" not in body or "bin_id" not in body:
        return error("'route_code' and 'bin_id' are required.")
    try:
        return success(fn(body["route_code"], body["bin_id"], session["collector_code"]))
    except RouteLifecycleError as e:
        return error(str(e))


@collector_bp.route("/start-collection", methods=["POST"])
@require_collector_session
def start_collection():
    return _stop_action(route_service.start_collection)


@collector_bp.route("/collect-stop", methods=["POST"])
@require_collector_session
def collect_stop():
    return _stop_action(route_service.collect_stop)


@collector_bp.route("/return-to-depot", methods=["POST"])
@require_collector_session
def return_to_depot():
    body = request.get_json(silent=True)
    if not body or "route_code" not in body:
        return error("'route_code' is required.")
    try:
        return success(route_service.return_to_depot(body["route_code"], session["collector_code"]))
    except RouteLifecycleError as e:
        return error(str(e))


# ---------------------------------------------------------------- vehicle ---

@collector_bp.route("/vehicle", methods=["GET"])
@require_collector_session
def get_my_vehicle():
    v = vehicle_service.get_vehicle_for_collector(session["collector_code"])
    return success(vehicle_service.vehicle_with_collector_dict(v) if v else None)


@collector_bp.route("/vehicle", methods=["POST"])
@require_collector_session
def create_my_vehicle():
    body = request.get_json(silent=True) or {}
    try:
        v = vehicle_service.create_vehicle_for_collector(
            session["collector_code"], body.get("vehicle_number"), body.get("vehicle_type"),
            body.get("maximum_capacity_kg"))
    except VehicleServiceError as e:
        return error(str(e))
    return success(vehicle_service.vehicle_with_collector_dict(v), status=201)


@collector_bp.route("/vehicle", methods=["PUT"])
@require_collector_session
def update_my_vehicle():
    body = request.get_json(silent=True) or {}
    try:
        v = vehicle_service.update_vehicle_by_collector(
            session["collector_code"], vehicle_number=body.get("vehicle_number"),
            vehicle_type=body.get("vehicle_type"), maximum_capacity_kg=body.get("maximum_capacity_kg"),
            current_load_kg=body.get("current_load_kg"), status=body.get("status"))
    except VehicleServiceError as e:
        return error(str(e))
    return success(vehicle_service.vehicle_with_collector_dict(v))


# ---------------------------------------------------------------- profile ---

@collector_bp.route("/profile", methods=["GET"])
@require_collector_session
def get_profile():
    c = auth_service.get_collector(session["collector_code"])
    c.pop("password_hash", None)
    return success(c)


@collector_bp.route("/profile", methods=["PUT"])
@require_collector_session
def update_profile():
    body = request.get_json(silent=True) or {}
    c = auth_service.get_collector(session["collector_code"])
    name = (body.get("name") or c["name"]).strip()
    mobile = (body.get("mobile") or c["mobile"]).strip()
    if len(name) < 2:
        return error("Please enter a valid name.")
    if not auth_service.MOBILE_RE.match(mobile):
        return error("Please enter a valid mobile number.")
    execute("UPDATE collectors SET name = ?, mobile = ? WHERE collector_code = ?", (name, mobile, c["collector_code"]))
    session["collector_name"] = name
    c = auth_service.get_collector(c["collector_code"])
    c.pop("password_hash", None)
    return success(c)


@collectors_bp.route("", methods=["GET"])
def list_collectors():
    rows = auth_service.get_all_collectors()
    for r in rows:
        r.pop("password_hash", None)
    return success(rows)
