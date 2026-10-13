"""
services/vehicle_service.py

Vehicle management service - the orchestration layer between the
Vehicle model (models/vehicle_model.py), the database, and an
in-memory cache for fast lookups.

WHAT THIS STEP ADDS ON TOP OF THE Vehicle CLASS (Step 3):
    The Vehicle class already enforces "never exceed capacity" at the
    object level (load_waste() raises VehicleCapacityError). This
    service layer is what makes that enforcement REAL across the whole
    application:
        - persists every load/unload to SQLite, so capacity state
          survives between requests (Flask handles one request at a
          time, with no shared memory between them by default other
          than what we deliberately cache).
        - validates vehicle data BEFORE it ever reaches the database
          (duplicate IDs, invalid capacities).
        - implements the exact depot-return workflow from Section 19:

              Vehicle -> Return to Depot -> Unload -> Reset load -> Continue

HASH TABLE USAGE (Step 8 tie-in):
    A Python dict (_vehicle_cache) is used here as the LIVE
    application's fast-lookup structure: vehicle_id -> Vehicle object,
    O(1) average lookup. As documented in data_structures/hash_table.py,
    Python's dict IS a hash table internally - this is the "production"
    hash table usage, while data_structures/hash_table.py's custom
    HashTable class is reserved for the Data Structures demo page where
    the underlying mechanics need to be visible.
"""

import json
from database.db import query_all, query_one, execute
from models.vehicle_model import Vehicle, VehicleCapacityError


class VehicleServiceError(Exception):
    """Raised for validation failures (duplicate ID, invalid capacity, not found)."""
    pass


# In-memory hash table (Python dict) cache: vehicle_id -> Vehicle object.
# Populated lazily; refreshed whenever a vehicle is created/updated/deleted
# so it never serves stale data within a single running process.
_vehicle_cache = {}


def _row_to_vehicle_and_cache(row):
    vehicle = Vehicle.from_row(row)
    _vehicle_cache[vehicle.vehicle_id] = vehicle
    return vehicle


def _persist_vehicle_state(vehicle):
    """Write a Vehicle object's current load/status back to the database."""
    execute(
        "UPDATE vehicles SET current_load_kg = ?, status = ? WHERE vehicle_id = ?",
        (vehicle.current_load_kg, vehicle.status, vehicle.vehicle_id),
    )


# ----------------------------------------------------------------------
# CRUD
# ----------------------------------------------------------------------

def create_vehicle(vehicle_id, vehicle_number, driver_name, maximum_capacity_kg, is_demo=False, vehicle_type=None):
    """
    Create and persist a new vehicle.
    Raises VehicleServiceError on duplicate vehicle_id or invalid capacity.
    """
    existing = query_one("SELECT id FROM vehicles WHERE vehicle_id = ?", (vehicle_id,))
    if existing is not None:
        raise VehicleServiceError(f"Vehicle ID '{vehicle_id}' already exists.")

    try:
        vehicle = Vehicle(
            vehicle_id=vehicle_id,
            vehicle_number=vehicle_number,
            driver_name=driver_name,
            maximum_capacity_kg=maximum_capacity_kg,
            is_demo=is_demo,
            vehicle_type=vehicle_type,
        )
    except ValueError as e:
        raise VehicleServiceError(str(e))

    new_id = execute(
        """INSERT INTO vehicles
           (vehicle_id, vehicle_number, driver_name, maximum_capacity_kg,
            current_load_kg, status, is_demo, vehicle_type)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (vehicle.vehicle_id, vehicle.vehicle_number, vehicle.driver_name,
         vehicle.maximum_capacity_kg, vehicle.current_load_kg, vehicle.status,
         int(vehicle.is_demo), vehicle.vehicle_type),
    )
    vehicle.id = new_id
    _vehicle_cache[vehicle.vehicle_id] = vehicle
    return vehicle


def get_vehicle(vehicle_id):
    """
    Fetch a vehicle by ID.
    Time: O(1) average - checks the in-memory hash table cache first,
    only falling back to the database (O(1) via SQLite's own index on
    the UNIQUE vehicle_id column) on a cache miss.
    Returns None if not found.
    """
    if vehicle_id in _vehicle_cache:
        return _vehicle_cache[vehicle_id]

    row = query_one("SELECT * FROM vehicles WHERE vehicle_id = ?", (vehicle_id,))
    if row is None:
        return None
    return _row_to_vehicle_and_cache(row)


def get_all_vehicles():
    """
    Fetch every vehicle, refreshing the cache from the database.
    Time: O(n).
    """
    rows = query_all("SELECT * FROM vehicles ORDER BY vehicle_id")
    return [_row_to_vehicle_and_cache(row) for row in rows]


def update_vehicle_details(vehicle_id, vehicle_number=None, driver_name=None):
    """Update non-capacity fields. Capacity changes are intentionally not
    allowed here - changing a vehicle's max capacity mid-route would make
    in-progress load calculations meaningless, so it isn't exposed."""
    vehicle = get_vehicle(vehicle_id)
    if vehicle is None:
        raise VehicleServiceError(f"Vehicle '{vehicle_id}' not found.")

    if vehicle_number is not None:
        vehicle.vehicle_number = vehicle_number
    if driver_name is not None:
        vehicle.driver_name = driver_name

    execute(
        "UPDATE vehicles SET vehicle_number = ?, driver_name = ? WHERE vehicle_id = ?",
        (vehicle.vehicle_number, vehicle.driver_name, vehicle.vehicle_id),
    )
    _vehicle_cache[vehicle_id] = vehicle
    return vehicle


def delete_vehicle(vehicle_id):
    vehicle = get_vehicle(vehicle_id)
    if vehicle is None:
        raise VehicleServiceError(f"Vehicle '{vehicle_id}' not found.")

    execute("DELETE FROM vehicles WHERE vehicle_id = ?", (vehicle_id,))
    _vehicle_cache.pop(vehicle_id, None)


# ----------------------------------------------------------------------
# Capacity management (Section 19 of the spec)
# ----------------------------------------------------------------------

def load_waste_onto_vehicle(vehicle_id, waste_kg):
    """
    Load waste onto a vehicle, enforcing capacity, and persist the result.
    Raises VehicleServiceError if the vehicle doesn't exist, or
    VehicleCapacityError (re-raised from the model) if this would
    exceed the vehicle's maximum capacity.
    """
    vehicle = get_vehicle(vehicle_id)
    if vehicle is None:
        raise VehicleServiceError(f"Vehicle '{vehicle_id}' not found.")

    vehicle.load_waste(waste_kg)  # raises VehicleCapacityError if it would overflow
    _persist_vehicle_state(vehicle)
    return vehicle


def can_vehicle_collect(vehicle_id, waste_kg):
    """
    Check WITHOUT modifying anything whether a vehicle has room for
    waste_kg more. Used by route_service to decide whether a bin fits
    on the current route leg before committing to loading it.
    """
    vehicle = get_vehicle(vehicle_id)
    if vehicle is None:
        raise VehicleServiceError(f"Vehicle '{vehicle_id}' not found.")
    return vehicle.can_collect(waste_kg)


def return_vehicle_to_depot(vehicle_id):
    """
    Implements the exact workflow from Section 19:
        Vehicle -> Return to Depot -> Unload -> Reset current load -> Continue
    """
    vehicle = get_vehicle(vehicle_id)
    if vehicle is None:
        raise VehicleServiceError(f"Vehicle '{vehicle_id}' not found.")

    vehicle.unload_at_depot()
    _persist_vehicle_state(vehicle)
    return vehicle


def set_vehicle_status(vehicle_id, status):
    if status not in Vehicle.VALID_STATUSES:
        raise VehicleServiceError(
            f"Invalid status '{status}'. Must be one of {Vehicle.VALID_STATUSES}."
        )
    vehicle = get_vehicle(vehicle_id)
    if vehicle is None:
        raise VehicleServiceError(f"Vehicle '{vehicle_id}' not found.")

    vehicle.status = status
    _persist_vehicle_state(vehicle)
    return vehicle


def get_available_vehicles():
    """Vehicles currently free to be assigned a new route."""
    return [v for v in get_all_vehicles() if v.status == "AVAILABLE"]


def update_vehicle(vehicle_id, vehicle_number=None, driver_name=None, status=None):
    """
    General-purpose update used by the PUT /api/vehicles/<id> endpoint.
    Deliberately does NOT allow changing maximum_capacity_kg or
    current_load_kg directly here - capacity changes mid-operation
    would make in-progress load calculations meaningless (see
    update_vehicle_details's docstring), and load must only ever change
    via load_waste_onto_vehicle() / return_vehicle_to_depot() so it can
    never drift out of sync with actual collected bins.
    """
    vehicle = get_vehicle(vehicle_id)
    if vehicle is None:
        raise VehicleServiceError(f"Vehicle '{vehicle_id}' not found.")

    if vehicle_number is not None:
        vehicle.vehicle_number = vehicle_number
    if driver_name is not None:
        vehicle.driver_name = driver_name
    if status is not None:
        if status not in Vehicle.VALID_STATUSES:
            raise VehicleServiceError(
                f"Invalid status '{status}'. Must be one of {Vehicle.VALID_STATUSES}."
            )
        vehicle.status = status

    execute(
        "UPDATE vehicles SET vehicle_number = ?, driver_name = ?, status = ? WHERE vehicle_id = ?",
        (vehicle.vehicle_number, vehicle.driver_name, vehicle.status, vehicle.vehicle_id),
    )
    _vehicle_cache[vehicle_id] = vehicle
    return vehicle


def clear_cache():
    """
    Reset the in-memory cache. Used mainly by tests and by 'Clear Demo
    Data' so stale Vehicle objects from deleted demo rows can never be
    served from cache after the underlying DB rows are gone.
    """
    _vehicle_cache.clear()


# ----------------------------------------------------------------------
# Collector-owned vehicles (vehicle information belongs to the COLLECTOR)
# ----------------------------------------------------------------------
# The link is collectors.vehicle_id -> vehicles.vehicle_id (already in the
# schema). A vehicle's collector is simply the collector row pointing at it.

COLLECTOR_EDITABLE_STATUSES = {"AVAILABLE", "MAINTENANCE"}


def get_collector_for_vehicle(vehicle_id):
    row = query_one(
        "SELECT collector_code, name, mobile FROM collectors WHERE vehicle_id = ? ORDER BY id LIMIT 1",
        (vehicle_id,),
    )
    return dict(row) if row else None


def get_vehicle_for_collector(collector_code):
    row = query_one("SELECT vehicle_id FROM collectors WHERE collector_code = ?", (collector_code,))
    if row is None or not row["vehicle_id"]:
        return None
    return get_vehicle(row["vehicle_id"])


def vehicle_with_collector_dict(vehicle):
    d = vehicle.to_dict()
    d["collector"] = get_collector_for_vehicle(vehicle.vehicle_id)
    return d


def get_available_vehicles_for_planning():
    """
    Vehicles a normal user may pick when generating a route: AVAILABLE and
    owned by a collector (a route has to be executable by somebody).
    Read-only view - users can never change vehicle data.
    """
    result = []
    for v in get_all_vehicles():
        if v.status != "AVAILABLE":
            continue
        d = vehicle_with_collector_dict(v)
        if d["collector"] is None:
            continue
        result.append(d)
    return result


def _next_vehicle_id():
    rows = query_all("SELECT vehicle_id FROM vehicles WHERE vehicle_id LIKE 'VEH%'")
    max_num = 0
    for row in rows:
        suffix = row["vehicle_id"][3:]
        if suffix.isdigit():
            max_num = max(max_num, int(suffix))
    return f"VEH{str(max_num + 1).zfill(3)}"


def create_vehicle_for_collector(collector_code, vehicle_number, vehicle_type, maximum_capacity_kg):
    """A collector registers the vehicle they drive (only if they don't have one)."""
    collector = query_one("SELECT name, vehicle_id FROM collectors WHERE collector_code = ?", (collector_code,))
    if collector is None:
        raise VehicleServiceError("Collector not found.")
    if collector["vehicle_id"] and get_vehicle(collector["vehicle_id"]) is not None:
        raise VehicleServiceError("You already have a vehicle. Edit it instead.")
    try:
        capacity = float(maximum_capacity_kg)
    except (TypeError, ValueError):
        raise VehicleServiceError("Maximum capacity must be a number.")
    vehicle = create_vehicle(_next_vehicle_id(), (vehicle_number or "").strip() or "Unnamed vehicle",
                             collector["name"], capacity, vehicle_type=(vehicle_type or "").strip() or None)
    execute("UPDATE collectors SET vehicle_id = ? WHERE collector_code = ?", (vehicle.vehicle_id, collector_code))
    return vehicle


def update_vehicle_by_collector(collector_code, vehicle_number=None, vehicle_type=None,
                                maximum_capacity_kg=None, current_load_kg=None, status=None):
    """
    A collector edits THEIR OWN vehicle. While the vehicle is ON ROUTE (or
    FULL mid-route) capacity / load / status are locked, because changing
    them would corrupt the in-progress load tracking.
    """
    vehicle = get_vehicle_for_collector(collector_code)
    if vehicle is None:
        raise VehicleServiceError("You do not have a vehicle yet.")
    locked = vehicle.status in ("ON ROUTE", "FULL")

    if vehicle_number is not None:
        if not str(vehicle_number).strip():
            raise VehicleServiceError("Vehicle name/number cannot be empty.")
        vehicle.vehicle_number = str(vehicle_number).strip()
    if vehicle_type is not None:
        vehicle.vehicle_type = str(vehicle_type).strip() or None

    if maximum_capacity_kg is not None or current_load_kg is not None or status is not None:
        if locked:
            raise VehicleServiceError("Capacity, load and status cannot be changed while the vehicle is on a route.")
        if maximum_capacity_kg is not None:
            try:
                cap = float(maximum_capacity_kg)
            except (TypeError, ValueError):
                raise VehicleServiceError("Maximum capacity must be a number.")
            if cap <= 0:
                raise VehicleServiceError("Maximum capacity must be greater than 0.")
            if vehicle.current_load_kg > cap:
                raise VehicleServiceError("Maximum capacity cannot be lower than the current load.")
            vehicle.maximum_capacity_kg = cap
        if current_load_kg is not None:
            try:
                load = float(current_load_kg)
            except (TypeError, ValueError):
                raise VehicleServiceError("Current load must be a number.")
            if load < 0 or load > vehicle.maximum_capacity_kg:
                raise VehicleServiceError("Current load must be between 0 and the maximum capacity.")
            vehicle.current_load_kg = load
        if status is not None:
            if status not in COLLECTOR_EDITABLE_STATUSES:
                raise VehicleServiceError("Status can only be set to AVAILABLE or MAINTENANCE.")
            vehicle.status = status

    execute(
        """UPDATE vehicles SET vehicle_number = ?, vehicle_type = ?, maximum_capacity_kg = ?,
           current_load_kg = ?, status = ? WHERE vehicle_id = ?""",
        (vehicle.vehicle_number, vehicle.vehicle_type, vehicle.maximum_capacity_kg,
         vehicle.current_load_kg, vehicle.status, vehicle.vehicle_id),
    )
    _vehicle_cache[vehicle.vehicle_id] = vehicle
    return vehicle
