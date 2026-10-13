"""
routes/planning_routes.py

REST API for the single "Add Bins -> Priority -> Vehicle -> Generate Route
-> Save Route" workflow (also used by the Requests page to build an
UPDATED version of a saved route).

    GET  /api/planning/config      - minutes-per-km, priority modes, thresholds
    POST /api/planning/analyze     - priority analysis (road distance + time per bin)
    POST /api/planning/generate    - build a DRAFT road route (nothing saved)
    POST /api/planning/save        - save the reviewed draft as a route (or a new version)
"""

from flask import Blueprint, jsonify, request, session
from routes.auth_routes import require_login_api
from services import planning_service, route_service
from services.planning_service import PlanningError
from services.route_service import RouteLifecycleError
from utils.api_helpers import success, error

planning_bp = Blueprint("planning_api", __name__, url_prefix="/api/planning")


def _planning_error(e):
    # 503 when the road-routing service is the problem, so the UI can offer "Retry".
    status = 503 if e.osrm else 400
    return jsonify({"success": False, "error": str(e), "osrm_unavailable": bool(e.osrm)}), status


@planning_bp.route("/config", methods=["GET"])
@require_login_api
def planning_config():
    return success(planning_service.planning_config())


@planning_bp.route("/analyze", methods=["POST"])
@require_login_api
def analyze():
    body = request.get_json(silent=True) or {}
    base = body.get("base_route_code")
    allowed = ()
    bin_ids = body.get("bin_ids") or []
    if base:
        allowed = tuple(route_service.get_route_bin_ids(base))
        bin_ids = list(allowed) + [b for b in bin_ids if b not in allowed]
    try:
        result = planning_service.analyze(bin_ids, body.get("priority_mode"), body.get("vehicle_id"), allowed)
    except PlanningError as e:
        return _planning_error(e)
    return success(result)


@planning_bp.route("/generate", methods=["POST"])
@require_login_api
def generate():
    body = request.get_json(silent=True) or {}
    try:
        plan = planning_service.generate_plan(
            body.get("bin_ids") or [], body.get("vehicle_id"), body.get("priority_mode"),
            user_code=session.get("user_code"), base_route_code=body.get("base_route_code"),
        )
    except PlanningError as e:
        return _planning_error(e)
    return success(plan)


@planning_bp.route("/save", methods=["POST"])
@require_login_api
def save():
    body = request.get_json(silent=True) or {}
    token = body.get("draft_token")
    if not token:
        return error("'draft_token' is required. Generate a route first.")
    try:
        plan = planning_service.get_draft(token)
        saved = route_service.save_planned_route(plan, user_code=session.get("user_code"))
    except (PlanningError, RouteLifecycleError) as e:
        return error(str(e))
    planning_service.discard_draft(token)
    return success(saved, status=201)
