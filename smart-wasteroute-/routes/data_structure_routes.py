"""
routes/data_structure_routes.py

REST API backing the Data Structures demonstration page (Section 23 -
arguably the most important page in the whole project for viva).

    GET /api/data-structures/live

Unlike every other endpoint so far, this one doesn't serve a single
resource - it takes a LIVE SNAPSHOT of every data structure the
project uses, built by genuinely re-running their real operations
against whatever is currently in the database. Nothing here is
pre-computed or faked:
    - Graph:          rebuilt fresh via route_service.build_graph_from_db()
    - Queue:           loaded fresh from pending_requests
    - Priority Queue:  built fresh from that Queue (real heap operations)
    - Stack:           reconstructed by genuinely pushing the most recent
                        real route's stops, one at a time
    - Hash Table:      a real data_structures.hash_table.HashTable,
                        populated fresh from the current active bins
    - List/Array:      the current bins/vehicles lists themselves
"""

import json
from flask import Blueprint
from database.db import query_all
from services import bin_service, vehicle_service, route_service
from data_structures.hash_table import HashTable
from data_structures.stack import Stack
from utils.api_helpers import success

ds_bp = Blueprint("data_structures_api", __name__, url_prefix="/api/data-structures")


@ds_bp.route("/live", methods=["GET"])
def live_snapshot():
    return success({
        "graph": _graph_snapshot(),
        "queue_and_priority_queue": _queue_and_priority_snapshot(),
        "stack": _stack_snapshot(),
        "hash_table": _hash_table_snapshot(),
        "list_array": _list_array_snapshot(),
    })


def _graph_snapshot():
    """Rebuild the real Graph (depot + active bins, Haversine edges) and inspect it."""
    try:
        graph = route_service.build_graph_from_db()
    except route_service.RouteServiceError as e:
        return {"available": False, "reason": str(e)}

    adjacency_list = {
        vertex: [{"neighbor": n, "distance_km": w} for n, w in neighbors]
        for vertex, neighbors in graph.to_display_dict().items()
    }

    return {
        "available": True,
        "vertex_count": graph.vertex_count(),
        "edge_count": graph.edge_count(),
        "is_connected": graph.is_connected(),
        "adjacency_list": adjacency_list,
    }


def _queue_and_priority_snapshot():
    """
    Load real pending requests into a Queue (arrival order), then
    genuinely drain a fresh copy of that Queue into a Priority Queue
    (urgency order via real Min Heap operations). Both are read-only
    previews - see routes/request_routes.py for the same guarantee.
    """
    pending_queue = route_service.load_pending_requests_queue()
    queue_view = [{"bin_id": r["bin_id"]} for r in pending_queue.to_list()]

    fresh_queue = route_service.load_pending_requests_queue()
    priority_queue, skipped = route_service.evaluate_priority_queue(fresh_queue)
    priority_view = [
        {"bin_id": req["bin_id"], "priority_weight": weight}
        for req, weight in priority_queue.view_priority_order()
    ]

    return {
        "queue_arrival_order": queue_view,
        "priority_queue_urgency_order": priority_view,
        "skipped_stale_requests": [s["bin_id"] for s in skipped],
    }


def _stack_snapshot():
    """
    Demonstrate the Stack using the most recently saved real route:
    genuinely push each stop (in the order the vehicle actually
    visited them) onto a fresh Stack object, then read peek() and
    both list orderings straight off that real Stack instance.
    """
    rows = query_all("SELECT * FROM collection_history ORDER BY date DESC LIMIT 1")
    if not rows:
        return {"available": False, "reason": "No routes have been generated yet."}

    row = rows[0]
    steps = json.loads(row["route"])

    demo_stack = Stack()
    for step in steps:
        demo_stack.push(step["location_name"])

    return {
        "available": True,
        "vehicle_id": row["vehicle_id"],
        "push_order": [s["location_name"] for s in steps],
        "peek_top": demo_stack.peek(),
        "most_recent_first": demo_stack.to_list(most_recent_first=True),
    }


def _hash_table_snapshot():
    """
    Populate a real data_structures.hash_table.HashTable (separate
    chaining, custom hash function) from the CURRENT active bins, so
    the demo page shows genuine hash values and any real collisions -
    not a hand-picked example.
    """
    ht = HashTable(num_buckets=16)
    for b in bin_service.get_active_bins():
        ht.put(b.bin_id, f"{b.name} ({b.priority})")

    return {
        "bucket_count": ht.num_buckets,
        "item_count": ht.size(),
        "rows": ht.to_display_rows(),
    }


def _list_array_snapshot():
    """The current bins/vehicles lists themselves - the List/Dynamic Array in daily use."""
    all_bins = bin_service.get_all_bins()
    all_vehicles = vehicle_service.get_all_vehicles()
    return {
        "bins_count": len(all_bins),
        "vehicles_count": len(all_vehicles),
        "bin_ids": [b.bin_id for b in all_bins],
        "vehicle_ids": [v.vehicle_id for v in all_vehicles],
    }
