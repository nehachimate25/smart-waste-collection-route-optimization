"""
routes/route_routes.py

REST API for route-related operations (Section 25 of the spec).
    POST /api/routes/shortest-path   - Dijkstra demo between any two points
    POST /api/routes/collect         - LEGACY one-shot academic pipeline (not used by the UI)
    GET  /api/routes[?status=...]    - saved routes (summaries, no geometry)
    GET  /api/routes/<code>          - one saved route with trips, steps and road geometry
    POST /api/routes/<code>/cancel   - cancel a route that has not started

Route PLANNING (analyse / generate / save) lives in routes/planning_routes.py.
"""

from flask import Blueprint, request
from services import route_service
from services.route_service import RouteServiceError
from services.vehicle_service import VehicleCapacityError
from algorithms.dijkstra import shortest_path
from utils.api_helpers import success, error

route_bp = Blueprint("routes_api", __name__, url_prefix="/api/routes")


@route_bp.route("/shortest-path", methods=["POST"])
def shortest_path_endpoint():
    """
    Body: {"start": "<vertex>", "destination": "<vertex>"}
    Vertex names are DEPOT or a bin_id (BIN001 etc.) - exactly the
    vertex keys used internally by route_service.build_graph_from_db().
    """
    body = request.get_json(silent=True)
    if not body:
        return error("Request body must be valid JSON.")
    if "start" not in body or "destination" not in body:
        return error("Both 'start' and 'destination' are required.")

    try:
        graph = route_service.build_graph_from_db()
    except RouteServiceError as e:
        return error(str(e))

    if not graph.has_vertex(body["start"]):
        return error(f"Unknown start vertex '{body['start']}'.", status=404)
    if not graph.has_vertex(body["destination"]):
        return error(f"Unknown destination vertex '{body['destination']}'.", status=404)

    result = shortest_path(graph, body["start"], body["destination"])
    return success(result)


@route_bp.route("/collect", methods=["POST"])
def collect_route():
    """
    Body: {"vehicle_id": "<vehicle_id>"}
    Runs the full Queue -> Priority Queue -> Graph -> Vehicle capacity
    -> Stack pipeline (services/route_service.generate_route) and
    persists the result to collection_history.
    """
    body = request.get_json(silent=True)
    if not body or "vehicle_id" not in body:
        return error("'vehicle_id' is required.")

    try:
        result = route_service.generate_route(body["vehicle_id"])
    except RouteServiceError as e:
        return error(str(e))
    except VehicleCapacityError as e:
        # Should not normally surface here (route_service checks capacity
        # before ever calling load_waste_onto_vehicle), but caught defensively
        # so a capacity bug never crashes the request.
        return error(str(e))

    return success({
        "history_id": result["history_id"],
        "route": result["route"].to_dict(),
        "stack_history": result["stack_history"],
        "notes": result["notes"],
        "unfitted_bins": result["unfitted_bins"],
    })


# ----------------------------------------------------------------------
# Saved-route read endpoints
# ----------------------------------------------------------------------

from services.route_service import RouteLifecycleError
from routes.auth_routes import require_login_api


@route_bp.route("", methods=["GET"])
def list_routes():
    status = request.args.get("status")
    return success(route_service.get_all_routes(status=status))


@route_bp.route("/<route_code>", methods=["GET"])
def get_route(route_code):
    route = route_service.get_route_details(route_code)
    if route is None:
        return error(f"Route '{route_code}' not found.", status=404)
    return success(route)


@route_bp.route("/<route_code>/cancel", methods=["POST"])
@require_login_api
def cancel_route_endpoint(route_code):
    try:
        route = route_service.cancel_route(route_code)
    except RouteLifecycleError as e:
        return error(str(e))
    return success(route)
