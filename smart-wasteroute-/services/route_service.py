"""
services/route_service.py

THE ORCHESTRATOR. This is the single most important file in the
project for viva purposes - it is where every data structure we've
built actually works TOGETHER on real data, exactly matching the
workflow diagram from Section 18 of the spec:

    Waste Bins
        |
        v
    Queue                 (pending collection requests, arrival order)
        |
        v
    Priority Queue        (same requests, now ordered by urgency)
        |
        v
    Graph / Adjacency List (depot + bins, edges = Haversine distance)
        |
        v
    Vehicle capacity check
        |
        v
    Route (Stack records each visited stop)
        |
        v
    Saved to collection_history

NOTE (road-based redesign): the ONE-SHOT generate_route() below is the
original academic pipeline and is kept as-is. The user-facing workflow now
lives in services/planning_service.py (analysis + road-based, capacity-aware
multi-trip planning) and in the ROUTE LIFECYCLE section at the bottom of this
file (save, versions, collector start/collect/return-to-depot, history).

NOTHING HERE IS FAKE:
    - Bins genuinely come from the database via bin_service.
    - The Queue genuinely holds pending_requests rows.
    - The Priority Queue genuinely reorders them using each bin's REAL
      current waste_level (re-checked at processing time, not cached
      from when the request was first made).
    - The Graph genuinely computes Haversine distance between every
      real pair of coordinates.
    - Vehicle capacity is genuinely enforced by vehicle_service/Vehicle
      (raises VehicleCapacityError if violated anywhere).
    - The route-selection step (deciding WHICH bin to visit next) is
      simply "pop the next-most-urgent item from the Priority Queue" -
      no greedy nearest-neighbor optimization, no external solver. This
      is intentionally simple and is called out below as exactly that.
"""

import json
from database.db import query_all, query_one, execute, get_connection
from data_structures.graph import Graph
from data_structures.queue import Queue
from data_structures.priority_queue import PriorityQueue
from data_structures.stack import Stack
from algorithms.distance import build_distance_matrix
from models.route_model import Route, RouteStep
from utils.priority_config import get_priority_weight
from services import bin_service
from services import vehicle_service
from services.vehicle_service import VehicleCapacityError

DEPOT_VERTEX = "DEPOT"


class RouteServiceError(Exception):
    """Raised for route-building failures (missing depot, no bins, no vehicle, etc.)."""
    pass


# ----------------------------------------------------------------------
# 1. GRAPH construction (depot + active bins, Haversine-weighted edges)
# ----------------------------------------------------------------------

def build_graph_from_db():
    """
    Build a fresh Graph from the current depot + active bins.
    Vertices are keyed by DEPOT_VERTEX / bin_id (NOT display names,
    which could collide) so every vertex key is guaranteed unique.

    Edges: every pair of locations gets a direct edge weighted by
    Haversine distance (build_distance_matrix from Step 9). At this
    project's scale (<=11 locations) a fully-connected graph is exactly
    what a real short-range collection network would look like, and it
    guarantees the graph is always connected (no "no path" failures
    caused by our own edge-building choices).

    Time: O(n^2) for n = 1 depot + active bins (n <= 11 typically) -
    negligible at this scale.
    """
    depot = bin_service.get_depot()
    if depot is None:
        raise RouteServiceError("No depot has been set. Add a depot before generating a route.")

    active_bins = bin_service.get_active_bins()

    graph = Graph()
    locations = [{"name": DEPOT_VERTEX, "latitude": depot["latitude"], "longitude": depot["longitude"]}]
    graph.add_vertex(DEPOT_VERTEX, data={"display_name": depot["name"], **depot})

    for b in active_bins:
        graph.add_vertex(b.bin_id, data={"display_name": b.name, "latitude": b.latitude, "longitude": b.longitude})
        locations.append({"name": b.bin_id, "latitude": b.latitude, "longitude": b.longitude})

    for name_a, name_b, distance in build_distance_matrix(locations):
        graph.add_edge(name_a, name_b, distance)

    return graph


# ----------------------------------------------------------------------
# 2. QUEUE - pending collection requests (arrival order)
# ----------------------------------------------------------------------

def enqueue_bin_for_collection(bin_id):
    """
    Add a bin to the pending-requests Queue (persisted to the
    pending_requests table so it survives a server restart).
    Refuses to double-enqueue a bin that already has an unprocessed
    pending request.
    """
    bin_obj = bin_service.get_bin(bin_id)
    if bin_obj is None:
        raise RouteServiceError(f"Bin '{bin_id}' not found.")

    already_pending = query_one(
        "SELECT id FROM pending_requests WHERE bin_id = ? AND status = 'PENDING'",
        (bin_id,),
    )
    if already_pending is not None:
        return  # already queued - nothing to do, not an error

    execute(
        "INSERT INTO pending_requests (bin_id, status) VALUES (?, 'PENDING')",
        (bin_id,),
    )


def enqueue_all_active_bins():
    """Convenience: enqueue every currently active bin that isn't already pending."""
    for b in bin_service.get_active_bins():
        enqueue_bin_for_collection(b.bin_id)


def load_pending_requests_queue():
    """
    Load all PENDING rows from the database into our own Queue class,
    in arrival order (oldest request first - the FIFO order the Queue
    is meant to preserve).
    Time: O(n).
    """
    rows = query_all("SELECT * FROM pending_requests WHERE status = 'PENDING' ORDER BY id ASC")
    q = Queue()
    for row in rows:
        q.enqueue({"request_id": row["id"], "bin_id": row["bin_id"]})
    return q


def _mark_request_processed(request_id):
    execute("UPDATE pending_requests SET status = 'PROCESSED' WHERE id = ?", (request_id,))


# ----------------------------------------------------------------------
# 3. QUEUE -> PRIORITY QUEUE (urgency evaluation, Section 30 workflow)
# ----------------------------------------------------------------------

def evaluate_priority_queue(pending_queue):
    """
    Drain the Queue (arrival order) and push every still-valid request
    into a Priority Queue, keyed by the bin's CURRENT waste level
    (re-fetched fresh from the database - not whatever it was when the
    request was first made, since it may have changed).

    Requests for bins that no longer exist or are no longer ACTIVE
    (e.g. already collected by an earlier route) are set aside as
    "skipped" rather than silently dropped, so the caller can still
    account for them.

    Time: O(n log n) - n dequeue operations (O(1) each) each followed
    by one priority-queue push (O(log n)).

    Returns: (PriorityQueue, skipped_requests: list[dict])
    """
    pq = PriorityQueue()
    skipped = []

    while not pending_queue.is_empty():
        request = pending_queue.dequeue()
        bin_obj = bin_service.get_bin(request["bin_id"])

        if bin_obj is None or bin_obj.status != "ACTIVE":
            skipped.append(request)
            continue

        weight = get_priority_weight(bin_obj.waste_level)
        pq.push(request, weight)

    return pq, skipped


# ----------------------------------------------------------------------
# 4-6. GRAPH + VEHICLE CAPACITY + STACK -> full route generation
# ----------------------------------------------------------------------

def _pop_nearest_among_tied_priority(priority_queue, graph, current_vertex):
    """
    Pop the next bin to collect, combining PRIORITY (primary) and
    DISTANCE (tie-breaker) - not distance alone, and not priority alone.

    PRIORITY ALWAYS WINS FIRST: a CRITICAL bin is never skipped over
    for a closer MEDIUM bin. This function only looks at whether the
    single NEXT item in the queue shares the SAME priority weight as
    the item immediately behind it. If so, it compares real Graph
    distances from the vehicle's current position and picks whichever
    of the two is closer, pushing the other back into the queue with
    its original priority unchanged (a harmless O(log n) re-insertion -
    the Min Heap doesn't care that an item was briefly removed and
    reinserted with the same priority).

    WHAT THIS DELIBERATELY DOES NOT DO: it does not look ahead further
    than the immediate next item, and it does not re-order bins with
    DIFFERENT priorities. This is intentionally a small, explainable
    tie-break - not a nearest-neighbor TSP solver. A genuine multi-stop
    distance-optimizing solve is a much harder problem (and explicitly
    out of scope per the project's own instructions); this only
    resolves the ambiguous case where the Priority Queue alone can't
    tell two equally-urgent bins apart, using a resource we already
    computed anyway (the Graph's real distances).

    Time: O(log n) - one pop, and at most one extra peek + pop + push
    compared to a plain priority_queue.pop().
    """
    first_request, first_weight = priority_queue.pop()

    if priority_queue.is_empty():
        return first_request, first_weight

    peeked_item, peeked_weight = priority_queue.peek()
    if peeked_weight != first_weight:
        return first_request, first_weight  # different priority - no tie, no distance comparison

    # Genuine tie: same priority weight. Compare real distances from
    # the vehicle's current position and keep whichever bin is closer.
    dist_to_first = graph.get_weight(current_vertex, first_request["bin_id"])
    dist_to_peeked = graph.get_weight(current_vertex, peeked_item["bin_id"])

    if dist_to_peeked is not None and dist_to_peeked < dist_to_first:
        second_request, second_weight = priority_queue.pop()  # actually remove the closer one
        priority_queue.push(first_request, first_weight)  # put the farther one back, same priority
        return second_request, second_weight

    return first_request, first_weight


def generate_route(vehicle_id):
    """
    THE MAIN ORCHESTRATION FUNCTION. Builds one complete collection
    route (possibly multiple depot-return legs) for a single vehicle,
    following this exact sequence:

        1. Build the Graph (depot + active bins, Haversine edges).
        2. Load pending requests into the Queue.
        3. Drain the Queue into the Priority Queue (urgency order).
        4. Repeatedly pop the most urgent bin. If it fits in the
           vehicle's remaining capacity, collect it: move the graph
           edge distance from the current location, add a RouteStep,
           push the stop onto the Stack, load the waste onto the
           vehicle, mark the bin collected, mark its request processed.
        5. If a bin does NOT fit, the vehicle returns to the depot,
           unloads (Section 19 workflow), and resumes with an empty
           vehicle. If the bin STILL doesn't fit into a fully empty
           vehicle, that bin's waste physically exceeds the vehicle's
           maximum capacity - it is skipped with a clear reason
           (this is the "Invalid vehicle capacity" error case from
           Section 26) rather than crashing the whole route.
        6. The route always ends with a final return to the depot.
        7. The completed route is saved to collection_history.

    ROUTE-SELECTION NOTE (per "do not force a Greedy algorithm unless
    required"): bins are visited in the Priority Queue's urgency order
    FIRST - a CRITICAL bin is never skipped for a closer MEDIUM one.
    Distance only matters as a TIE-BREAKER between bins that share the
    exact same priority weight (see _pop_nearest_among_tied_priority
    above) - not as a nearest-neighbor or full-route-optimizing
    choice. This is a deliberate, documented middle ground: priority
    and distance both genuinely influence the outcome, without
    pretending to solve the much harder multi-stop distance-
    optimization problem.
    """
    vehicle = vehicle_service.get_vehicle(vehicle_id)
    if vehicle is None:
        raise RouteServiceError(f"Vehicle '{vehicle_id}' not found.")
    if vehicle.current_load_kg != 0:
        raise RouteServiceError(
            f"Vehicle '{vehicle_id}' still has {vehicle.current_load_kg}kg loaded. "
            "Return it to the depot before starting a new route."
        )

    graph = build_graph_from_db()
    depot = bin_service.get_depot()

    pending_queue = load_pending_requests_queue()
    if pending_queue.is_empty():
        raise RouteServiceError("No pending collection requests. Nothing to route.")

    priority_queue, skipped_requests = evaluate_priority_queue(pending_queue)
    for req in skipped_requests:
        _mark_request_processed(req["request_id"])  # stale requests are cleared either way

    route = Route(vehicle_id=vehicle_id)
    stack = Stack()

    # Start at the depot.
    route.add_step(RouteStep(depot["name"], depot["latitude"], depot["longitude"], "DEPOT"))
    stack.push(DEPOT_VERTEX)
    current_vertex = DEPOT_VERTEX

    vehicle_service.set_vehicle_status(vehicle_id, "ON ROUTE")

    notes = []
    unfitted_bins = []  # bins that couldn't be collected on ANY leg (their waste > vehicle max capacity)

    while not priority_queue.is_empty():
        request, _weight = _pop_nearest_among_tied_priority(priority_queue, graph, current_vertex)
        bin_obj = bin_service.get_bin(request["bin_id"])

        # Re-check freshness: the bin could have been collected by
        # another process between queueing and processing.
        if bin_obj is None or bin_obj.status != "ACTIVE":
            _mark_request_processed(request["request_id"])
            continue

        vehicle = vehicle_service.get_vehicle(vehicle_id)  # refresh latest load state

        if not vehicle.can_collect(bin_obj.current_waste_kg):
            # Capacity insufficient -> return to depot -> unload -> reset -> continue
            # (Section 19 workflow, executed here for real) - but ONLY if the
            # vehicle isn't already sitting at the depot (e.g. this is the very
            # first bin of the route and it already doesn't fit an empty vehicle -
            # in that case there is no "leg" to travel, so skip straight to the
            # impossible-bin check below instead of adding a meaningless
            # depot-to-depot step with no edge weight to measure).
            if current_vertex != DEPOT_VERTEX:
                distance_back = graph.get_weight(current_vertex, DEPOT_VERTEX)
                route.add_step(RouteStep(depot["name"], depot["latitude"], depot["longitude"],
                                          "DEPOT", distance_from_previous_km=distance_back))
                stack.push(DEPOT_VERTEX)
                vehicle_service.return_vehicle_to_depot(vehicle_id)
                vehicle_service.set_vehicle_status(vehicle_id, "ON ROUTE")
                current_vertex = DEPOT_VERTEX
                notes.append(f"Vehicle returned to depot before collecting {bin_obj.bin_id} (capacity reached).")
                vehicle = vehicle_service.get_vehicle(vehicle_id)

            if not vehicle.can_collect(bin_obj.current_waste_kg):
                # Bin's waste exceeds even a FULLY EMPTY vehicle - impossible to collect.
                # This is the "Invalid vehicle capacity" error case (Section 26) -
                # we skip this one bin with a clear reason rather than crashing the route.
                unfitted_bins.append(bin_obj.bin_id)
                notes.append(
                    f"Skipped {bin_obj.bin_id}: {bin_obj.current_waste_kg}kg exceeds vehicle "
                    f"{vehicle.vehicle_id}'s maximum capacity of {vehicle.maximum_capacity_kg}kg."
                )
                _mark_request_processed(request["request_id"])
                continue

        # Collect this bin.
        distance = graph.get_weight(current_vertex, bin_obj.bin_id)
        route.add_step(RouteStep(
            bin_obj.name, bin_obj.latitude, bin_obj.longitude, "BIN",
            bin_id=bin_obj.bin_id, distance_from_previous_km=distance,
            waste_collected_kg=bin_obj.current_waste_kg,
        ))
        stack.push(bin_obj.bin_id)
        vehicle_service.load_waste_onto_vehicle(vehicle_id, bin_obj.current_waste_kg)
        bin_service.mark_bin_collected(bin_obj.bin_id)
        _mark_request_processed(request["request_id"])
        current_vertex = bin_obj.bin_id

    # Final return to depot.
    distance_home = graph.get_weight(current_vertex, DEPOT_VERTEX) if current_vertex != DEPOT_VERTEX else 0
    route.add_step(RouteStep(depot["name"], depot["latitude"], depot["longitude"],
                              "DEPOT", distance_from_previous_km=distance_home))
    stack.push(DEPOT_VERTEX)

    vehicle_service.return_vehicle_to_depot(vehicle_id)

    optimization_result = "Priority-ordered collection, {} stop(s).".format(len(route.collected_bin_ids()))
    if unfitted_bins:
        optimization_result += f" {len(unfitted_bins)} bin(s) skipped (exceeds vehicle capacity): {unfitted_bins}."

    history_row = route.to_history_row(optimization_result=optimization_result)
    history_id = execute(
        """INSERT INTO collection_history
           (vehicle_id, collected_bins, total_waste, total_distance, route, optimization_result)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (history_row["vehicle_id"], history_row["collected_bins"], history_row["total_waste"],
         history_row["total_distance"], history_row["route"], history_row["optimization_result"]),
    )

    return {
        "history_id": history_id,
        "route": route,
        "stack_history": stack.to_list(most_recent_first=False),  # visit order, for display
        "notes": notes,
        "unfitted_bins": unfitted_bins,
    }


# ============================================================================
# ROUTE LIFECYCLE  (road-based, multi-trip, versioned)
# ============================================================================
"""
routes (session / version) -> route_trips -> route_steps
                           -> collection_events, depot_events, vehicle_assignments

    ASSIGNED -> IN_PROGRESS -> COMPLETED          (normal)
    ASSIGNED -> CANCELLED                         (user cancels before it starts)
    ASSIGNED -> SUPERSEDED                        (user saves an updated version)

Selection / ordering logic is NOT here - it is in planning_service.py. This
section only stores a reviewed plan and then tracks its execution.
"""

import re
from datetime import datetime

from services import auth_service as _auth_service
from services.vehicle_service import VehicleCapacityError


class RouteLifecycleError(RouteServiceError):
    """Raised for lifecycle-specific failures (wrong sequence, wrong collector, etc.)."""
    pass


def _now():
    return datetime.now().isoformat(timespec="seconds")


def _minutes_between(start_iso, end_iso):
    try:
        delta = datetime.fromisoformat(end_iso) - datetime.fromisoformat(start_iso)
        return round(delta.total_seconds() / 60.0, 1)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------- codes ----

def _next_route_code():
    """R001, R002, ... (legacy RT#### codes from older versions are ignored)."""
    max_num = 0
    for row in query_all("SELECT route_code FROM routes"):
        m = re.fullmatch(r"R(\d+)", row["route_code"])
        if m:
            max_num = max(max_num, int(m.group(1)))
    return f"R{str(max_num + 1).zfill(3)}"


def get_route_summary_row(route_code):
    row = query_one("SELECT * FROM routes WHERE route_code = ?", (route_code,))
    return dict(row) if row else None


def get_route_bin_ids(route_code):
    row = query_one("SELECT id FROM routes WHERE route_code = ?", (route_code,))
    if row is None:
        return []
    return [r["bin_id"] for r in query_all(
        "SELECT bin_id FROM route_steps WHERE route_id = ? AND step_type = 'BIN' ORDER BY step_order", (row["id"],))]


# ----------------------------------------------------------------- save ----

def save_planned_route(plan, user_code=None):
    """
    Persist a REVIEWED draft plan (planning_service.generate_plan output).
    Nothing is written until this is called. If the plan is an update of an
    existing route, the old route is kept untouched as history and marked
    SUPERSEDED; the new one is stored as <root>-V<n>.
    """
    vehicle = vehicle_service.get_vehicle(plan["vehicle"]["vehicle_id"])
    if vehicle is None:
        raise RouteLifecycleError("The selected vehicle no longer exists. Generate the route again.")
    base_code = plan.get("base_route_code")
    base = get_route_summary_row(base_code) if base_code else None
    if base_code and (base is None or base["status"] != "ASSIGNED"):
        raise RouteLifecycleError("The route being updated has changed (it may have started). Generate again.")
    if vehicle.status != "AVAILABLE" and not (base and base["vehicle_id"] == vehicle.vehicle_id):
        raise RouteLifecycleError(f"Vehicle {vehicle.vehicle_number} is no longer available. Generate again.")

    allowed = set(get_route_bin_ids(base_code)) if base_code else set()
    plan_bins = [s for t in plan["trips"] for s in t["steps"] if s["step_type"] == "BIN"]
    for s in plan_bins:
        b = bin_service.get_bin(s["bin_id"])
        if b is None or not (b.status == "ACTIVE" or (b.status == "ASSIGNED" and s["bin_id"] in allowed)):
            raise RouteLifecycleError(f"Bin '{s['location_name']}' is no longer available. Generate the route again.")

    collector_code = plan["collector"]["collector_code"]
    now = _now()
    totals = plan["totals"]

    if base:
        root = base["root_route_code"] or base["route_code"]
        version = query_one("SELECT COUNT(*) AS c FROM routes WHERE root_route_code = ? OR route_code = ?",
                            (root, root))["c"] + 1
        route_code = f"{root}-V{version}"
    else:
        route_code = _next_route_code()
        root, version = route_code, 1

    conn = get_connection()
    try:
        cur = conn.execute(
            """INSERT INTO routes
               (route_code, vehicle_id, collector_id, depot_name, depot_latitude, depot_longitude,
                total_bins, total_waste, total_distance, status, created_by_user_id, assigned_at,
                root_route_code, parent_route_code, version, priority_mode, total_trips, total_time_min)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'ASSIGNED', ?, ?, ?, ?, ?, ?, ?, ?)""",
            (route_code, vehicle.vehicle_id, collector_code, plan["depot"]["name"],
             plan["depot"]["latitude"], plan["depot"]["longitude"], totals["bins"], totals["waste_kg"],
             totals["distance_km"], user_code, now, root, base_code, version, plan["mode"],
             totals["trips"], totals["time_min"]),
        )
        route_id = cur.lastrowid
        for t in plan["trips"]:
            tcur = conn.execute(
                """INSERT INTO route_trips (route_id, trip_number, planned_waste_kg, total_distance_km,
                   total_time_min, capacity_kg, initial_unload_kg) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (route_id, t["trip_number"], t["planned_waste_kg"], t["total_distance_km"],
                 t["total_time_min"], t["capacity_kg"], t["initial_unload_kg"]),
            )
            trip_id = tcur.lastrowid
            for s in t["steps"]:
                conn.execute(
                    """INSERT INTO route_steps
                       (route_id, trip_id, step_order, step_type, sequence_number, bin_id, location_name,
                        latitude, longitude, waste_level, priority, priority_score, planned_waste_kg,
                        segment_distance_km, segment_time_min, cumulative_distance_km, load_after_kg,
                        segment_geometry)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (route_id, trip_id, s["step_order"], s["step_type"], s["sequence_number"], s["bin_id"],
                     s["location_name"], s["latitude"], s["longitude"], s["waste_level"], s["priority"],
                     s["priority_score"], s["planned_waste_kg"], s["segment_distance_km"],
                     s["segment_time_min"], s["cumulative_distance_km"], s["load_after_kg"],
                     json.dumps(s["segment_geometry"]) if s["segment_geometry"] else None),
                )
        conn.execute(
            "INSERT INTO vehicle_assignments (route_id, vehicle_id, collector_id, assigned_at) VALUES (?, ?, ?, ?)",
            (route_id, vehicle.vehicle_id, collector_code, now),
        )
        if base:
            conn.execute("UPDATE routes SET status = 'SUPERSEDED' WHERE route_code = ?", (base_code,))
            conn.execute("UPDATE vehicle_assignments SET released_at = ? WHERE route_id = "
                         "(SELECT id FROM routes WHERE route_code = ?) AND released_at IS NULL", (now, base_code))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    for s in plan_bins:
        bin_service.mark_bin_assigned(s["bin_id"])
        execute("UPDATE pending_requests SET status = 'PROCESSED' WHERE bin_id = ? AND status = 'PENDING'", (s["bin_id"],))
    vehicle_service.set_vehicle_status(vehicle.vehicle_id, "ON ROUTE")
    execute("UPDATE collectors SET status = 'ON_DUTY' WHERE collector_code = ?", (collector_code,))

    return get_route_details(route_code)


# -------------------------------------------------------------- read -------

def _route_label(row):
    return "Original" if row["version"] == 1 else f"Updated (V{row['version']})"


def _step_dict(row, include_geometry):
    d = {
        "id": row["id"], "step_order": row["step_order"], "step_type": row["step_type"],
        "sequence_number": row["sequence_number"], "bin_id": row["bin_id"],
        "location_name": row["location_name"], "latitude": row["latitude"], "longitude": row["longitude"],
        "waste_level": row["waste_level"], "priority": row["priority"], "priority_score": row["priority_score"],
        "planned_waste_kg": row["planned_waste_kg"], "segment_distance_km": row["segment_distance_km"],
        "segment_time_min": row["segment_time_min"], "cumulative_distance_km": row["cumulative_distance_km"],
        "load_after_kg": row["load_after_kg"], "status": row["status"],
        "started_at": row["started_at"], "collected_at": row["collected_at"],
        "actual_time_min": None, "actual_load_after_kg": None,
    }
    if include_geometry:
        d["segment_geometry"] = json.loads(row["segment_geometry"]) if row["segment_geometry"] else None
    return d


def get_route_details(route_code, include_geometry=True):
    route_row = query_one("SELECT * FROM routes WHERE route_code = ?", (route_code,))
    if route_row is None:
        return None
    route_id = route_row["id"]

    events = {e["step_id"]: e for e in query_all("SELECT * FROM collection_events WHERE route_id = ?", (route_id,))}
    depot_events = {e["trip_id"]: dict(e) for e in query_all("SELECT * FROM depot_events WHERE route_id = ?", (route_id,))
                    if e["trip_id"] is not None}

    trips = []
    for t in query_all("SELECT * FROM route_trips WHERE route_id = ? ORDER BY trip_number", (route_id,)):
        steps = []
        for sr in query_all("SELECT * FROM route_steps WHERE trip_id = ? ORDER BY step_order", (t["id"],)):
            sd = _step_dict(sr, include_geometry)
            ev = events.get(sr["id"])
            if ev is not None:
                sd["actual_time_min"] = ev["actual_time_min"]
                sd["actual_load_after_kg"] = ev["vehicle_load_after_kg"]
                sd["waste_collected_kg"] = ev["waste_collected_kg"]
            steps.append(sd)
        trips.append({
            "id": t["id"], "trip_number": t["trip_number"], "status": t["status"],
            "planned_waste_kg": t["planned_waste_kg"], "total_distance_km": t["total_distance_km"],
            "total_time_min": t["total_time_min"], "capacity_kg": t["capacity_kg"],
            "initial_unload_kg": t["initial_unload_kg"],
            "started_at": t["started_at"], "completed_at": t["completed_at"],
            "depot_event": depot_events.get(t["id"]), "steps": steps,
        })

    vehicle = vehicle_service.get_vehicle(route_row["vehicle_id"])
    collector = _auth_service.get_collector(route_row["collector_id"]) if route_row["collector_id"] else None
    if collector:
        collector.pop("password_hash", None)
    root = route_row["root_route_code"] or route_row["route_code"]
    versions = [{"route_code": r["route_code"], "version": r["version"], "status": r["status"]}
                for r in query_all("SELECT route_code, version, status FROM routes "
                                   "WHERE root_route_code = ? OR route_code = ? ORDER BY version", (root, root))]

    bin_steps = [s for t in trips for s in t["steps"] if s["step_type"] == "BIN"]
    return {
        "route_code": route_row["route_code"], "label": _route_label(route_row),
        "root_route_code": root, "parent_route_code": route_row["parent_route_code"],
        "version": route_row["version"], "versions": versions,
        "vehicle_id": route_row["vehicle_id"],
        "vehicle": vehicle.to_dict() if vehicle else {"vehicle_id": route_row["vehicle_id"], "vehicle_number": route_row["vehicle_id"]},
        "collector": collector, "priority_mode": route_row["priority_mode"],
        "depot_name": route_row["depot_name"], "depot_latitude": route_row["depot_latitude"],
        "depot_longitude": route_row["depot_longitude"],
        "total_bins": route_row["total_bins"], "total_waste": route_row["total_waste"],
        "total_distance": route_row["total_distance"], "total_time_min": route_row["total_time_min"],
        "total_trips": route_row["total_trips"], "status": route_row["status"],
        "created_at": route_row["created_at"], "assigned_at": route_row["assigned_at"],
        "started_at": route_row["started_at"], "completed_at": route_row["completed_at"],
        "collected_count": sum(1 for s in bin_steps if s["status"] == "COLLECTED"),
        "trips": trips,
    }


def get_all_routes(status=None, include_geometry=False):
    if status:
        rows = query_all("SELECT route_code FROM routes WHERE status = ? ORDER BY id DESC", (status,))
    else:
        rows = query_all("SELECT route_code FROM routes ORDER BY id DESC")
    return [get_route_details(r["route_code"], include_geometry=include_geometry) for r in rows]


def get_active_route_for_collector(collector_id):
    row = query_one(
        "SELECT route_code FROM routes WHERE collector_id = ? AND status IN ('ASSIGNED', 'IN_PROGRESS') "
        "ORDER BY id DESC LIMIT 1", (collector_id,))
    return get_route_details(row["route_code"]) if row else None


def get_routes_for_collector(collector_id):
    rows = query_all("SELECT route_code FROM routes WHERE collector_id = ? ORDER BY id DESC", (collector_id,))
    return [get_route_details(r["route_code"], include_geometry=False) for r in rows]


# ------------------------------------------------- collector execution -----

def _owned_active_route(route_code, collector_id):
    row = query_one("SELECT * FROM routes WHERE route_code = ?", (route_code,))
    if row is None:
        raise RouteLifecycleError(f"Route '{route_code}' not found.")
    if row["collector_id"] != collector_id:
        raise RouteLifecycleError("This route is not assigned to you.")
    if row["status"] not in ("ASSIGNED", "IN_PROGRESS"):
        raise RouteLifecycleError(f"Route '{route_code}' is {row['status']} and cannot accept collections.")
    return row


def _current_trip(route_id):
    """First trip that has not been completed (i.e. has not returned to the depot)."""
    return query_one("SELECT * FROM route_trips WHERE route_id = ? AND status != 'COMPLETED' ORDER BY trip_number LIMIT 1",
                     (route_id,))


def _next_bin_step(trip_id):
    return query_one("SELECT * FROM route_steps WHERE trip_id = ? AND step_type = 'BIN' AND status != 'COLLECTED' "
                     "ORDER BY step_order LIMIT 1", (trip_id,))


def _begin_trip_if_needed(route_row, trip, collector_id):
    now = _now()
    if route_row["status"] == "ASSIGNED":
        execute("UPDATE routes SET status = 'IN_PROGRESS', started_at = ? WHERE id = ?", (now, route_row["id"]))
    if trip["status"] == "PENDING":
        execute("UPDATE route_trips SET status = 'IN_PROGRESS', started_at = ? WHERE id = ?", (now, trip["id"]))
        if trip["initial_unload_kg"] > 0:
            # old load blocked the first bin: it is unloaded at the depot before departure
            vehicle_service.return_vehicle_to_depot(route_row["vehicle_id"])
            execute(
                """INSERT INTO depot_events (route_id, trip_id, vehicle_id, collector_id, reason, unloaded_kg,
                   vehicle_load_after_kg, vehicle_capacity_kg, occurred_at)
                   VALUES (?, ?, ?, ?, 'PRE_UNLOAD', ?, 0, ?, ?)""",
                (route_row["id"], None, route_row["vehicle_id"], collector_id, trip["initial_unload_kg"],
                 trip["capacity_kg"], now))
        vehicle_service.set_vehicle_status(route_row["vehicle_id"], "ON ROUTE")


def start_collection(route_code, bin_id, collector_id):
    route_row = _owned_active_route(route_code, collector_id)
    trip = _current_trip(route_row["id"])
    if trip is None:
        raise RouteLifecycleError("Every trip of this route is already finished.")
    step = _next_bin_step(trip["id"])
    if step is None:
        raise RouteLifecycleError("All bins of this trip are collected - return to the depot and unload.")
    if step["bin_id"] != bin_id:
        raise RouteLifecycleError(f"Please follow the assigned sequence - the next bin is {step['location_name']}.")
    _begin_trip_if_needed(route_row, trip, collector_id)
    if step["status"] == "PENDING":
        execute("UPDATE route_steps SET status = 'IN_PROGRESS', started_at = ? WHERE id = ?", (_now(), step["id"]))
    return get_route_details(route_code)


def collect_stop(route_code, bin_id, collector_id):
    route_row = _owned_active_route(route_code, collector_id)
    trip = _current_trip(route_row["id"])
    if trip is None:
        raise RouteLifecycleError("Every trip of this route is already finished.")
    step = _next_bin_step(trip["id"])
    if step is None:
        raise RouteLifecycleError("All bins of this trip are collected - return to the depot and unload.")
    if step["bin_id"] != bin_id:
        raise RouteLifecycleError(f"Please collect bins in the assigned sequence - the next bin is {step['location_name']}.")
    if step["status"] != "IN_PROGRESS":
        raise RouteLifecycleError("Press 'Start Collection' for this bin first.")

    waste_kg = step["planned_waste_kg"]
    try:
        vehicle = vehicle_service.load_waste_onto_vehicle(route_row["vehicle_id"], waste_kg)
    except VehicleCapacityError as e:
        raise RouteLifecycleError(str(e))

    now = _now()
    execute("UPDATE route_steps SET status = 'COLLECTED', collected_at = ? WHERE id = ?", (now, step["id"]))
    if bin_service.get_bin(bin_id) is not None:
        bin_service.mark_bin_collected(bin_id)
    execute(
        """INSERT INTO collection_events
           (route_id, trip_id, step_id, bin_id, sequence_number, vehicle_id, collector_id, latitude, longitude,
            waste_collected_kg, vehicle_load_after_kg, segment_distance_km, distance_travelled_km,
            estimated_time_min, actual_time_min, collected_at, status)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'COLLECTED')""",
        (route_row["id"], trip["id"], step["id"], bin_id, step["sequence_number"], route_row["vehicle_id"],
         collector_id, step["latitude"], step["longitude"], waste_kg, vehicle.current_load_kg,
         step["segment_distance_km"], step["cumulative_distance_km"], step["segment_time_min"],
         _minutes_between(step["started_at"], now), now),
    )
    return get_route_details(route_code)


def return_to_depot(route_code, collector_id):
    """
    Collector reaches the depot at the end of the CURRENT trip: the vehicle
    unloads (load -> 0). If more trips remain the next trip becomes active
    (reason CAPACITY); if this was the last trip the route is COMPLETED and
    archived into collection_history (reason FINAL).
    """
    route_row = _owned_active_route(route_code, collector_id)
    trip = _current_trip(route_row["id"])
    if trip is None:
        raise RouteLifecycleError("Every trip of this route is already finished.")
    if trip["status"] == "PENDING":
        raise RouteLifecycleError("This trip has not started yet.")
    if _next_bin_step(trip["id"]) is not None:
        raise RouteLifecycleError("Collect every bin of this trip before returning to the depot.")

    return_step = query_one("SELECT * FROM route_steps WHERE trip_id = ? AND step_type = 'DEPOT_RETURN'", (trip["id"],))
    vehicle = vehicle_service.get_vehicle(route_row["vehicle_id"])
    unloaded = vehicle.current_load_kg
    capacity = vehicle.maximum_capacity_kg
    now = _now()

    later_trip = query_one("SELECT id FROM route_trips WHERE route_id = ? AND trip_number > ?",
                           (route_row["id"], trip["trip_number"]))
    is_final = later_trip is None

    vehicle_service.return_vehicle_to_depot(route_row["vehicle_id"])  # unload, load = 0
    execute("UPDATE route_steps SET status = 'DONE', collected_at = ? WHERE id = ?", (now, return_step["id"]))
    execute("UPDATE route_trips SET status = 'COMPLETED', completed_at = ? WHERE id = ?", (now, trip["id"]))
    execute(
        """INSERT INTO depot_events (route_id, trip_id, vehicle_id, collector_id, reason, return_distance_km,
           return_time_min, unloaded_kg, vehicle_load_after_kg, vehicle_capacity_kg, occurred_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)""",
        (route_row["id"], trip["id"], route_row["vehicle_id"], collector_id, "FINAL" if is_final else "CAPACITY",
         return_step["segment_distance_km"], return_step["segment_time_min"], unloaded, capacity, now),
    )

    if is_final:
        _complete_route(route_row, collector_id, now)
    else:
        vehicle_service.set_vehicle_status(route_row["vehicle_id"], "ON ROUTE")
    return get_route_details(route_code)


def _complete_route(route_row, collector_id, now):
    execute("UPDATE routes SET status = 'COMPLETED', completed_at = ? WHERE id = ?", (now, route_row["id"]))
    execute("UPDATE vehicle_assignments SET released_at = ? WHERE route_id = ? AND released_at IS NULL",
            (now, route_row["id"]))
    execute("UPDATE collectors SET status = 'AVAILABLE' WHERE collector_code = ?", (collector_id,))
    vehicle_service.set_vehicle_status(route_row["vehicle_id"], "AVAILABLE")

    # Archive in collection_history (same shape the Data Structures demo page reads).
    details = get_route_details(route_row["route_code"], include_geometry=False)
    flat = []
    for t in details["trips"]:
        for s in t["steps"]:
            flat.append({
                "location_name": s["location_name"],
                "stop_type": "BIN" if s["step_type"] == "BIN" else "DEPOT",
                "bin_id": s["bin_id"], "trip_number": t["trip_number"],
                "distance_from_previous_km": s["segment_distance_km"],
                "waste_collected_kg": s["planned_waste_kg"] if s["step_type"] == "BIN" else 0,
            })
    bin_ids = [s["bin_id"] for t in details["trips"] for s in t["steps"] if s["step_type"] == "BIN"]
    execute(
        """INSERT INTO collection_history
           (vehicle_id, collected_bins, total_waste, total_distance, route, optimization_result, route_code)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (details["vehicle_id"], json.dumps(bin_ids), details["total_waste"], details["total_distance"],
         json.dumps(flat),
         f"Route {details['route_code']}: {details['total_trips']} trip(s), {len(bin_ids)} bin(s), "
         f"road distance {details['total_distance']} km.",
         details["route_code"]),
    )


def cancel_route(route_code):
    """Cancel a route that has not started: its bins go back to the pending Queue, the vehicle is freed."""
    route = get_route_details(route_code, include_geometry=False)
    if route is None:
        raise RouteLifecycleError(f"Route '{route_code}' not found.")
    if route["status"] != "ASSIGNED":
        raise RouteLifecycleError(f"Only a route that has not started can be cancelled (this one is {route['status']}).")

    for t in route["trips"]:
        for s in t["steps"]:
            if s["step_type"] == "BIN" and bin_service.get_bin(s["bin_id"]) is not None:
                bin_service.reactivate_bin(s["bin_id"])
                enqueue_bin_for_collection(s["bin_id"])
    now = _now()
    execute("UPDATE routes SET status = 'CANCELLED' WHERE route_code = ?", (route_code,))
    execute("UPDATE vehicle_assignments SET released_at = ? WHERE route_id = (SELECT id FROM routes WHERE route_code = ?) "
            "AND released_at IS NULL", (now, route_code))
    vehicle_service.return_vehicle_to_depot(route["vehicle_id"])
    if route["collector"]:
        execute("UPDATE collectors SET status = 'AVAILABLE' WHERE collector_code = ?", (route["collector"]["collector_code"],))
    return get_route_details(route_code, include_geometry=False)
