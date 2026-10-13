"""
routes/request_routes.py

REST API for the Collection Requests page (Section 30 of the spec).
This is the page specifically designed to demonstrate:

    New request -> Queue -> Priority evaluation -> Priority Queue -> Collection

Endpoints:
    POST /api/requests            - report a new collection request (enqueue a bin)
    GET  /api/requests/pending    - Queue view: requests in arrival order
    GET  /api/requests/priority   - Priority Queue view: same requests, urgency order
    GET  /api/requests/collected  - recently collected bins (from collection_history)

IMPORTANT: /pending and /priority are BOTH READ-ONLY PREVIEWS.
    route_service.load_pending_requests_queue() builds a fresh Queue
    from the database every time it's called, and
    route_service.evaluate_priority_queue() only builds a PriorityQueue
    in memory - neither one marks anything as PROCESSED or touches the
    database. This means refreshing this page never has side effects;
    the actual state only changes when /api/routes/collect is called
    (Step 12/13) or a new request is reported here.
"""

from flask import Blueprint
from routes.auth_routes import require_login_api
from services import route_service, bin_service
from utils.api_helpers import success

request_bp = Blueprint("requests_api", __name__, url_prefix="/api/requests")


@request_bp.route("/pending", methods=["GET"])
@require_login_api
def list_pending():
    """
    Queue view: pending requests in ARRIVAL order (FIFO), exactly as
    they sit in the Queue data structure - not reordered by urgency.
    """
    queue = route_service.load_pending_requests_queue()
    items = []
    for req in queue.to_list():  # non-destructive view (Step 6's Queue.to_list())
        bin_obj = bin_service.get_bin(req["bin_id"])
        items.append({
            "request_id": req["request_id"],
            "bin_id": req["bin_id"],
            "bin": bin_obj.to_dict() if bin_obj else None,
        })
    return success(items)


@request_bp.route("/priority", methods=["GET"])
@require_login_api
def list_priority_order():
    """
    Priority Queue view: the SAME pending requests, but shown in the
    order the Min-Heap-backed Priority Queue would actually pop them -
    most urgent (CRITICAL) first. This is a live, real reordering, not
    a hand-arranged display list.
    """
    queue = route_service.load_pending_requests_queue()
    priority_queue, skipped = route_service.evaluate_priority_queue(queue)

    ordered = []
    for req, weight in priority_queue.view_priority_order():
        bin_obj = bin_service.get_bin(req["bin_id"])
        ordered.append({
            "request_id": req["request_id"],
            "bin_id": req["bin_id"],
            "priority_weight": weight,
            "bin": bin_obj.to_dict() if bin_obj else None,
        })

    # Stale requests: bin was deleted or already collected since the
    # request was made - shown separately so the UI can flag them
    # rather than silently hiding them.
    stale = [{"request_id": r["request_id"], "bin_id": r["bin_id"]} for r in skipped]

    return success({"priority_order": ordered, "stale_requests": stale})
