"""
routes/bin_routes.py

REST API for bin management (Section 25 of the spec).
    GET    /api/bins
    POST   /api/bins
    PUT    /api/bins/<bin_id>
    DELETE /api/bins/<bin_id>

Every error path (missing depot, duplicate ID, invalid coordinates,
bin not found, etc.) is caught here and returned as a clean JSON error
instead of crashing Flask (Section 26 of the spec).
"""

from flask import Blueprint, request, session
from services import bin_service
from services.bin_service import BinServiceError
from services import image_service
from services.image_service import ImageServiceError
from routes.auth_routes import require_login_api
from utils.api_helpers import success, error

bin_bp = Blueprint("bins_api", __name__, url_prefix="/api/bins")


@bin_bp.route("", methods=["GET"])
def list_bins():
    bins = bin_service.get_all_bins()
    return success([b.to_dict() for b in bins])


@bin_bp.route("/mine", methods=["GET"])
def my_bins():
    """A logged-in user's own submitted bins ('My Bins' view)."""
    if session.get("role") != "user" or not session.get("user_code"):
        return error("Please log in to view your bins.", status=401)
    bins = bin_service.get_bins_for_user(session["user_code"])
    return success([b.to_dict() for b in bins])


@bin_bp.route("", methods=["POST"])
@require_login_api
def create_bin():
    """
    Accepts EITHER a JSON body OR a multipart/form-data submission with an
    optional 'image' file (used by the Add Bins & Route page). user_id is NEVER taken from the
    request body - it comes only from the server-side session, so a
    bin can never be created "as" a different user than whoever is
    actually logged in.
    """
    is_multipart = bool(request.files) or (request.content_type or "").startswith("multipart/form-data")

    if is_multipart:
        body = request.form
        image_file = request.files.get("image")
    else:
        body = request.get_json(silent=True)
        image_file = None
        if not body:
            return error("Request body must be valid JSON.")

    required = ["bin_id", "name", "latitude", "longitude"]
    missing = [f for f in required if f not in body or body[f] in (None, "")]
    if missing:
        return error(f"Missing required field(s): {', '.join(missing)}")

    try:
        image_filename = image_service.save_bin_image(image_file) if image_file else None
    except ImageServiceError as e:
        return error(str(e))

    user_id = session.get("user_code") if session.get("role") == "user" else None

    try:
        new_bin = bin_service.create_bin(
            bin_id=body["bin_id"],
            name=body["name"],
            latitude=float(body["latitude"]),
            longitude=float(body["longitude"]),
            waste_level=float(body.get("waste_level", 0)),
            current_waste_kg=float(body.get("current_waste_kg", 0)),
            maximum_capacity_kg=float(body.get("maximum_capacity_kg", 100)),
            user_id=user_id,
            image_filename=image_filename,
            waste_category=body.get("waste_category") or None,
            notes=body.get("notes") or None,
        )
    except BinServiceError as e:
        return error(str(e))
    except (TypeError, ValueError) as e:
        return error(f"Invalid data: {e}")

    # A bin a user just reported is, by definition, ready to be collected -
    # no separate manual "report this bin" step needed in this workflow.
    # (Demo Data loading bypasses this API route entirely and still uses
    # its own explicit enqueue_all_active_bins() call, so that path is
    # unaffected.) enqueue_bin_for_collection() is itself a no-op if this
    # bin somehow already has a pending request, so this is always safe.
    from services import route_service
    route_service.enqueue_bin_for_collection(new_bin.bin_id)

    return success(new_bin.to_dict(), status=201)


@bin_bp.route("/<bin_id>/boost", methods=["POST"])
@require_login_api
def boost_bin_priority(bin_id):
    """
    Body: {"requested_priority": "CRITICAL", "reason": "Overflow risk"}
    See models/bin_model.py - a boost can only ever raise urgency,
    never lower it below the bin's real automatic priority.
    """
    body = request.get_json(silent=True)
    if not body or "requested_priority" not in body or "reason" not in body:
        return error("'requested_priority' and 'reason' are required.")

    user_id = session.get("user_code") if session.get("role") == "user" else None

    try:
        updated = bin_service.request_priority_boost(
            bin_id, body["requested_priority"], body["reason"], requested_by_user_id=user_id,
        )
    except BinServiceError as e:
        return error(str(e), status=404 if "not found" in str(e) else 400)

    return success(updated.to_dict())


@bin_bp.route("/<bin_id>", methods=["PUT"])
@require_login_api
def update_bin(bin_id):
    body = request.get_json(silent=True)
    if not body:
        return error("Request body must be valid JSON.")

    try:
        updated = bin_service.update_bin(
            bin_id,
            name=body.get("name"),
            current_waste_kg=body.get("current_waste_kg"),
            waste_level=body.get("waste_level"),
            maximum_capacity_kg=body.get("maximum_capacity_kg"),
            status=body.get("status"),
            waste_category=body.get("waste_category"),
            notes=body.get("notes"),
        )
    except BinServiceError as e:
        return error(str(e), status=404 if "not found" in str(e) else 400)

    return success(updated.to_dict())


@bin_bp.route("/<bin_id>", methods=["DELETE"])
@require_login_api
def delete_bin(bin_id):
    try:
        bin_service.delete_bin(bin_id)
    except BinServiceError as e:
        return error(str(e), status=404 if "not found" in str(e) else 400)

    return success({"deleted": bin_id})


# ----------------------------------------------------------------------
# Depot endpoints (single depot for this project, stored via bin_service).
# Not explicitly listed in Section 25's endpoint table, but required for
# the Map page (Step 15) to read/write the depot location.
# ----------------------------------------------------------------------

depot_bp = Blueprint("depot_api", __name__, url_prefix="/api/depot")


@depot_bp.route("", methods=["GET"])
def get_depot():
    depot = bin_service.get_depot()
    if depot is None:
        return success(None)
    return success(depot)


@depot_bp.route("", methods=["POST"])
def set_depot():
    body = request.get_json(silent=True)
    if not body:
        return error("Request body must be valid JSON.")

    required = ["name", "latitude", "longitude"]
    missing = [f for f in required if f not in body]
    if missing:
        return error(f"Missing required field(s): {', '.join(missing)}")

    try:
        depot = bin_service.set_depot(body["name"], body["latitude"], body["longitude"])
    except BinServiceError as e:
        return error(str(e))

    return success(depot)
