"""
services/planning_service.py

ROUTE PLANNING for the "Add Bins -> Priority -> Vehicle -> Generate Route"
workflow. Two clearly separated layers live side by side here:

    ACADEMIC ROUTE LOGIC  (our own data structures decide the ORDER)
        Queue           pending collection requests, in arrival order
        Priority Queue  (Min Heap) drains the Queue, most urgent bin first
        Graph           adjacency list of depot + bins, edge weight = road km
        Stack           records every stop of a trip (and is unwound to show
                        the reverse / return sequence)

    REAL ROAD VISUALIZATION  (services/osrm_service.py)
        OSRM supplies the road distance matrix and the real road geometry
        that Leaflet draws. Nothing in the academic layer is replaced by
        it - it only supplies real numbers and real polylines.

Nothing here is saved to the database. generate_plan() returns a DRAFT
that the user reviews; route_service.save_planned_route() persists it
only when the user presses "Save Route".
"""

import secrets
import time

from config import Config
from algorithms.distance import haversine_distance
from data_structures.graph import Graph
from data_structures.priority_queue import PriorityQueue
from data_structures.queue import Queue
from data_structures.stack import Stack
from services import bin_service, osrm_service, route_service, vehicle_service
from services.osrm_service import OsrmError
from utils.priority_config import (
    DEFAULT_PRIORITY_MODE, PRIORITY_MODES, PRIORITY_SCORE_WEIGHTS,
    PRIORITY_THRESHOLDS, PRIORITY_WEIGHT,
)
from utils.travel_time import estimate_travel_minutes

DEPOT_VERTEX = "DEPOT"
EXCEEDS_VEHICLE_MESSAGE = "Bin cannot be collected because its waste quantity exceeds vehicle capacity."


class PlanningError(Exception):
    """Validation / routing failure while analysing or generating a plan."""

    def __init__(self, message, osrm=False):
        super().__init__(message)
        self.osrm = osrm  # True when the cause is the road-routing service


# ----------------------------------------------------------------------
# Draft store (a generated-but-not-yet-saved plan lives here until Save)
# ----------------------------------------------------------------------
_DRAFTS = {}
_DRAFT_TTL_SECONDS = 2 * 60 * 60


def _store_draft(plan):
    now = time.time()
    for token in [t for t, d in _DRAFTS.items() if now - d["_created"] > _DRAFT_TTL_SECONDS]:
        _DRAFTS.pop(token, None)
    token = secrets.token_urlsafe(12)
    plan["draft_token"] = token
    _DRAFTS[token] = {**plan, "_created": now}
    return token


def get_draft(token):
    draft = _DRAFTS.get(token)
    if draft is None:
        raise PlanningError("This generated route has expired. Please generate the route again.")
    return {k: v for k, v in draft.items() if k != "_created"}


def discard_draft(token):
    _DRAFTS.pop(token, None)


# ----------------------------------------------------------------------
# Public config for the UI (so the front end never hard-codes any of it)
# ----------------------------------------------------------------------

def planning_config():
    return {
        "minutes_per_km": Config.ESTIMATED_MINUTES_PER_KM,
        "default_mode": DEFAULT_PRIORITY_MODE,
        "modes": [{"key": k, **v} for k, v in PRIORITY_MODES.items()],
        "thresholds": [{"label": k, "min": lo, "max": hi} for k, (lo, hi) in PRIORITY_THRESHOLDS.items()],
        "score_weights": PRIORITY_SCORE_WEIGHTS,
    }


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------

def _select_bins(bin_ids, allowed_assigned=()):
    seen, bins = set(), []
    for bin_id in bin_ids or []:
        if bin_id in seen:
            continue
        seen.add(bin_id)
        b = bin_service.get_bin(bin_id)
        if b is None:
            raise PlanningError(f"Bin '{bin_id}' no longer exists.")
        if b.status != "ACTIVE" and not (b.status == "ASSIGNED" and bin_id in allowed_assigned):
            raise PlanningError(f"Bin '{b.name}' is not available for a new route (status {b.status}).")
        bins.append(b)
    if not bins:
        raise PlanningError("Add at least one bin before analysing priority.")
    return bins


def _ordering_key(mode, weight, waste_level, score, dist, minutes):
    d = dist if dist is not None else 0.0
    t = minutes if minutes is not None else 0.0
    if mode == "HIGHEST_WASTE":
        return (-waste_level, d, t)
    if mode == "SHORTEST_DISTANCE":
        return (d, -waste_level, t)
    if mode == "FASTEST_TIME":
        return (t, -waste_level, d)
    return (weight, -score, d, t)  # BALANCED: urgency band, score, distance, time


def _reason(mode, b):
    where = (f"{b['distance_km']} km / {b['travel_minutes']} min from the depot"
             if b["distance_km"] is not None else "road distance unavailable")
    if mode == "HIGHEST_WASTE":
        return f"Fullest first: {b['waste_level']:g}% full ({b['priority']}). Distance only breaks ties ({where})."
    if mode == "SHORTEST_DISTANCE":
        return f"Closest first: {where}. Waste level ({b['waste_level']:g}%) only breaks ties."
    if mode == "FASTEST_TIME":
        return f"Fastest first: {where}. Waste level ({b['waste_level']:g}%) only breaks ties."
    return (f"{b['priority']} urgency band ({b['waste_level']:g}% full) is ranked first; "
            f"inside a band the higher score ({b['score']}) wins, then the shorter road distance ({where}).")


def _build_road_graph(depot, bins, matrix):
    """Academic Graph (adjacency list): depot + bins, edge weight = ROAD km."""
    graph = Graph()
    graph.add_vertex(DEPOT_VERTEX, data={"display_name": depot["name"]})
    for b in bins:
        graph.add_vertex(b.bin_id, data={"display_name": b.name})
    keys = [DEPOT_VERTEX] + [b.bin_id for b in bins]
    for i, a in enumerate(keys):
        for j, c in enumerate(keys):
            if i != j:
                graph.add_edge(a, c, matrix[i][j], directed=True)
    return graph


# ----------------------------------------------------------------------
# 1. PRIORITY ANALYSIS
# ----------------------------------------------------------------------

def analyze(bin_ids, mode=None, vehicle_id=None, allowed_assigned=()):
    """Priority analysis for the UI (see _analyze for the work)."""
    result, _graph = _analyze(bin_ids, mode, vehicle_id, allowed_assigned)
    return result


def _analyze(bin_ids, mode=None, vehicle_id=None, allowed_assigned=()):
    mode = mode if mode in PRIORITY_MODES else DEFAULT_PRIORITY_MODE
    depot = bin_service.get_depot()
    if depot is None:
        raise PlanningError("Set a depot on the map before analysing priority.")
    bins = _select_bins(bin_ids, allowed_assigned)

    vehicle = vehicle_service.get_vehicle(vehicle_id) if vehicle_id else None

    # ---- REAL ROAD DISTANCE (OSRM) -------------------------------------
    points = [depot] + [{"latitude": b.latitude, "longitude": b.longitude} for b in bins]
    matrix, warning = None, None
    try:
        matrix = osrm_service.road_distance_matrix(points)
    except OsrmError as e:
        warning = (f"{e} Road distances are unavailable, so no distance or time is shown and a route "
                   "cannot be generated until the routing service responds. Your bins are safe - retry.")

    # ---- ACADEMIC GRAPH + DSA -----------------------------------------
    graph = _build_road_graph(depot, bins, matrix) if matrix else None

    dists = [graph.get_weight(DEPOT_VERTEX, b.bin_id) for b in bins] if graph else [None] * len(bins)
    known = [d for d in dists if d is not None]
    dmin, dmax = (min(known), max(known)) if known else (0, 0)

    w = PRIORITY_SCORE_WEIGHTS
    rows = {}
    for b, dist in zip(bins, dists):
        minutes = estimate_travel_minutes(dist)
        if dist is None:
            closeness = 0.0
        elif dmax == dmin:
            closeness = 100.0
        else:
            closeness = 100.0 * (1 - (dist - dmin) / (dmax - dmin))
        score = round(w["waste"] * b.waste_level + (w["distance"] + w["time"]) * closeness
                      if dist is not None else b.waste_level, 1)
        row = {
            **b.to_dict(),
            "fill_percent": b.waste_level,
            "priority_weight": PRIORITY_WEIGHT[b.priority],
            "distance_km": dist,
            "travel_minutes": minutes,
            "straight_line_km": haversine_distance(depot["latitude"], depot["longitude"], b.latitude, b.longitude),
            "score": score,
            "exceeds_vehicle": bool(vehicle and b.current_waste_kg > vehicle.maximum_capacity_kg),
        }
        rows[b.bin_id] = row

    # Queue (arrival order) -> Priority Queue (Min Heap, ordered by the chosen mode)
    pending = Queue()
    for b in bins:
        route_service.enqueue_bin_for_collection(b.bin_id)
        pending.enqueue({"bin_id": b.bin_id})
    arrival_order = [rows[r["bin_id"]]["name"] for r in pending.to_list()]

    pq = PriorityQueue()
    while not pending.is_empty():
        req = pending.dequeue()
        r = rows[req["bin_id"]]
        pq.push(req, _ordering_key(mode, r["priority_weight"], r["waste_level"], r["score"],
                                   r["distance_km"], r["travel_minutes"]))

    ranked = []
    while not pq.is_empty():
        req, _key = pq.pop()
        r = rows[req["bin_id"]]
        r["rank"] = len(ranked) + 1
        r["reason"] = _reason(mode, r)
        ranked.append(r)

    if vehicle:
        for r in ranked:
            if r["exceeds_vehicle"]:
                r["warning"] = EXCEEDS_VEHICLE_MESSAGE

    return {
        "mode": mode,
        "mode_label": PRIORITY_MODES[mode]["label"],
        "depot": depot,
        "bins": ranked,
        "road_ok": matrix is not None,
        "warning": warning,
        "minutes_per_km": Config.ESTIMATED_MINUTES_PER_KM,
        "total_waste_kg": round(sum(r["current_waste_kg"] for r in ranked), 2),
        "dsa": {
            "queue_arrival_order": arrival_order,
            "priority_queue_pop_order": [r["name"] for r in ranked],
            "graph_vertices": [DEPOT_VERTEX] + [b.bin_id for b in bins],
            "graph_edge_weight": "road distance (km) from OSRM",
        },
    }, graph


# ----------------------------------------------------------------------
# 2. ROUTE GENERATION (priority order -> capacity-aware trips -> road legs)
# ----------------------------------------------------------------------

def _split_into_trips(ranked, vehicle):
    """
    Walk the bins in PRIORITY order and cut them into trips by capacity.
    Strict priority: a bin is never collected before a more urgent one.
    When the next bin does not fit, the vehicle returns to the depot,
    unloads, and a NEW trip starts with that same bin.
    """
    max_cap = vehicle.maximum_capacity_kg
    trips, unfitted = [], []
    current = None

    def new_trip(capacity, initial_unload=0.0):
        return {"capacity_kg": capacity, "left": capacity, "bins": [], "initial_unload_kg": initial_unload}

    for r in ranked:
        kg = r["current_waste_kg"]
        if kg > max_cap:
            unfitted.append({**r, "warning": EXCEEDS_VEHICLE_MESSAGE})
            continue
        if current is None:
            current = new_trip(vehicle.remaining_capacity())
        if kg > current["left"]:
            if current["bins"]:
                trips.append(current)
                current = new_trip(max_cap)
            else:
                # Vehicle still carries an old load that blocks the very first bin:
                # it unloads at the depot before departing.
                current = new_trip(max_cap, initial_unload=vehicle.current_load_kg)
        current["bins"].append(r)
        current["left"] -= kg
    if current and current["bins"]:
        trips.append(current)
    return trips, unfitted


def generate_plan(bin_ids, vehicle_id, mode=None, user_code=None, base_route_code=None):
    allowed_assigned = ()
    base = None
    if base_route_code:
        base = route_service.get_route_summary_row(base_route_code)
        if base is None:
            raise PlanningError(f"Route '{base_route_code}' not found.")
        if base["status"] != "ASSIGNED":
            raise PlanningError("A route can only be updated before the collector starts it "
                                f"(this route is {base['status']}).")
        base_bin_ids = route_service.get_route_bin_ids(base_route_code)
        allowed_assigned = tuple(base_bin_ids)
        bin_ids = list(base_bin_ids) + [b for b in (bin_ids or []) if b not in base_bin_ids]
        vehicle_id = vehicle_id or base["vehicle_id"]
        mode = mode or base["priority_mode"]

    if not vehicle_id:
        raise PlanningError("Select an available collection vehicle first.")
    vehicle = vehicle_service.get_vehicle(vehicle_id)
    if vehicle is None:
        raise PlanningError(f"Vehicle '{vehicle_id}' not found.")
    own_base_vehicle = base is not None and base["vehicle_id"] == vehicle_id
    if vehicle.status != "AVAILABLE" and not own_base_vehicle:
        raise PlanningError(f"Vehicle {vehicle.vehicle_number} is not available (status: {vehicle.status}).")
    collector = vehicle_service.get_collector_for_vehicle(vehicle_id)
    if collector is None:
        raise PlanningError(f"Vehicle {vehicle.vehicle_number} has no collector assigned, so nobody could run this route.")

    analysis, graph = _analyze(bin_ids, mode, vehicle_id, allowed_assigned)
    if not analysis["road_ok"]:
        raise PlanningError(analysis["warning"], osrm=True)
    mode = analysis["mode"]
    depot = analysis["depot"]

    trips_raw, unfitted = _split_into_trips(analysis["bins"], vehicle)
    if not trips_raw:
        raise PlanningError(EXCEEDS_VEHICLE_MESSAGE + " No bin could be planned for this vehicle.")

    depot_pt = {"latitude": depot["latitude"], "longitude": depot["longitude"]}
    trips, step_order, sequence, cumulative = [], 0, 0, 0.0
    total_waste = total_distance = total_time = 0.0
    stack_trace = []

    try:
        for t_index, t in enumerate(trips_raw, start=1):
            stack = Stack()
            points = [depot_pt] + [{"latitude": r["latitude"], "longitude": r["longitude"]} for r in t["bins"]] + [depot_pt]
            road = osrm_service.road_route(points)  # REAL road legs + geometry

            load = 0.0 if t["initial_unload_kg"] else vehicle.current_load_kg if t_index == 1 else 0.0
            steps = []

            def add_step(step_type, name, lat, lng, leg, r=None, kg=0.0, load_after=0.0):
                nonlocal step_order, sequence, cumulative
                step_order += 1
                dist = leg["distance_km"] if leg else 0.0
                cumulative = round(cumulative + dist, 3)
                if step_type == "BIN":
                    sequence += 1
                steps.append({
                    "step_order": step_order, "step_type": step_type,
                    "sequence_number": sequence if step_type == "BIN" else None,
                    "bin_id": r["bin_id"] if r else None, "location_name": name,
                    "latitude": lat, "longitude": lng,
                    "waste_level": r["waste_level"] if r else None,
                    "priority": r["priority"] if r else None,
                    "priority_score": r["score"] if r else None,
                    "planned_waste_kg": kg,
                    "segment_distance_km": dist,
                    "segment_time_min": estimate_travel_minutes(dist),
                    "cumulative_distance_km": cumulative,
                    "load_after_kg": round(load_after, 2),
                    "segment_geometry": leg["geometry"] if leg else None,
                    "status": "PENDING",
                })

            add_step("DEPOT_START", depot["name"], depot["latitude"], depot["longitude"], None, load_after=load)
            stack.push(DEPOT_VERTEX)
            for i, r in enumerate(t["bins"]):
                load += r["current_waste_kg"]
                add_step("BIN", r["name"], r["latitude"], r["longitude"], road["legs"][i], r=r,
                         kg=r["current_waste_kg"], load_after=load)
                stack.push(r["bin_id"])
            add_step("DEPOT_RETURN", depot["name"], depot["latitude"], depot["longitude"], road["legs"][-1], load_after=0.0)
            stack.push(DEPOT_VERTEX)

            visit_order = [graph.get_vertex_data(v)["display_name"] for v in stack.to_list(most_recent_first=False)]
            unwind = []
            while not stack.is_empty():
                unwind.append(graph.get_vertex_data(stack.pop())["display_name"])
            stack_trace.append({"trip_number": t_index, "pushed": visit_order, "unwound": unwind})

            trip_dist = round(sum(s["segment_distance_km"] for s in steps), 3)
            trip_time = round(sum(s["segment_time_min"] for s in steps), 1)
            trip_waste = round(sum(s["planned_waste_kg"] for s in steps), 2)
            trips.append({
                "trip_number": t_index, "capacity_kg": t["capacity_kg"],
                "initial_unload_kg": t["initial_unload_kg"], "planned_waste_kg": trip_waste,
                "total_distance_km": trip_dist, "total_time_min": trip_time,
                "ended_by_capacity": t_index < len(trips_raw), "steps": steps,
            })
            total_waste += trip_waste
            total_distance += trip_dist
            total_time += trip_time
    except OsrmError as e:
        raise PlanningError(f"{e} The route was not generated and nothing was saved - retry when the routing service responds.", osrm=True)

    warnings = [f"{u['name']}: {EXCEEDS_VEHICLE_MESSAGE}" for u in unfitted]
    plan = {
        "mode": mode, "mode_label": analysis["mode_label"],
        "minutes_per_km": Config.ESTIMATED_MINUTES_PER_KM,
        "depot": depot,
        "vehicle": vehicle_service.vehicle_with_collector_dict(vehicle),
        "collector": collector,
        "base_route_code": base_route_code,
        "user_code": user_code,
        "trips": trips,
        "unfitted": unfitted,
        "warnings": warnings,
        "analysis": analysis["bins"],
        "totals": {
            "trips": len(trips),
            "bins": sum(1 for t in trips for s in t["steps"] if s["step_type"] == "BIN"),
            "waste_kg": round(total_waste, 2),
            "distance_km": round(total_distance, 3),
            "time_min": round(total_time, 1),
        },
        "dsa": {**analysis["dsa"], "stack_trace": stack_trace},
    }
    _store_draft(plan)
    return plan
