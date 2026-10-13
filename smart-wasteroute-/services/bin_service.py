"""
services/bin_service.py

Bin management service - CRUD for bins, plus depot management (the
project has exactly one depot, stored in the `locations` table).

Mirrors the structure of services/vehicle_service.py: a Python dict
acts as the in-memory hash-table cache (bin_id -> Bin object) for O(1)
average lookup, falling back to SQLite on a cache miss.
"""

from database.db import query_all, query_one, execute
from models.bin_model import Bin


class BinServiceError(Exception):
    """Raised for validation failures (duplicate ID, invalid data, not found)."""
    pass


# In-memory hash table (Python dict) cache: bin_id -> Bin object.
_bin_cache = {}


def _row_to_bin_and_cache(row):
    bin_obj = Bin.from_row(row)
    _bin_cache[bin_obj.bin_id] = bin_obj
    return bin_obj


def _persist_bin_state(bin_obj):
    execute(
        """UPDATE bins
           SET waste_level = ?, current_waste_kg = ?, priority = ?, status = ?,
               automatic_priority = ?, priority_boost = ?, requested_priority = ?,
               boost_reason = ?
           WHERE bin_id = ?""",
        (bin_obj.waste_level, bin_obj.current_waste_kg, bin_obj.priority,
         bin_obj.status, bin_obj.automatic_priority, int(bin_obj.priority_boost),
         bin_obj.requested_priority, bin_obj.boost_reason, bin_obj.bin_id),
    )


# ----------------------------------------------------------------------
# CRUD
# ----------------------------------------------------------------------

def create_bin(bin_id, name, latitude, longitude, waste_level=0,
                current_waste_kg=0, maximum_capacity_kg=100, is_demo=False,
                user_id=None, image_filename=None, waste_category=None, notes=None):
    existing = query_one("SELECT id FROM bins WHERE bin_id = ?", (bin_id,))
    if existing is not None:
        raise BinServiceError(f"Bin ID '{bin_id}' already exists.")

    if not (-90 <= latitude <= 90) or not (-180 <= longitude <= 180):
        raise BinServiceError(f"Invalid coordinates: ({latitude}, {longitude})")

    try:
        bin_obj = Bin(
            bin_id=bin_id, name=name, latitude=latitude, longitude=longitude,
            waste_level=waste_level, current_waste_kg=current_waste_kg,
            maximum_capacity_kg=maximum_capacity_kg, is_demo=is_demo,
            user_id=user_id, image_filename=image_filename,
            waste_category=waste_category, notes=notes,
        )
    except ValueError as e:
        raise BinServiceError(str(e))

    new_id = execute(
        """INSERT INTO bins
           (bin_id, name, latitude, longitude, waste_level, current_waste_kg,
            maximum_capacity_kg, priority, automatic_priority, status, is_demo,
            user_id, image_filename, waste_category, notes)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (bin_obj.bin_id, bin_obj.name, bin_obj.latitude, bin_obj.longitude,
         bin_obj.waste_level, bin_obj.current_waste_kg, bin_obj.maximum_capacity_kg,
         bin_obj.priority, bin_obj.automatic_priority, bin_obj.status, int(bin_obj.is_demo),
         bin_obj.user_id, bin_obj.image_filename, bin_obj.waste_category, bin_obj.notes),
    )
    bin_obj.id = new_id
    _bin_cache[bin_obj.bin_id] = bin_obj
    return bin_obj


def get_bin(bin_id):
    """O(1) average lookup: cache first, DB fallback on miss."""
    if bin_id in _bin_cache:
        return _bin_cache[bin_id]
    row = query_one("SELECT * FROM bins WHERE bin_id = ?", (bin_id,))
    if row is None:
        return None
    return _row_to_bin_and_cache(row)


def get_all_bins():
    rows = query_all("SELECT * FROM bins ORDER BY bin_id")
    return [_row_to_bin_and_cache(row) for row in rows]


def get_active_bins():
    """Bins currently eligible for collection (not already collected/inactive)."""
    return [b for b in get_all_bins() if b.status == "ACTIVE"]


def get_bins_for_user(user_id):
    """A user's own submitted bins (for the 'My Bins' dashboard view)."""
    return [b for b in get_all_bins() if b.user_id == user_id]


def request_priority_boost(bin_id, requested_priority, reason, requested_by_user_id=None):
    """
    Apply a priority boost request to a bin and log it to
    priority_requests for audit history. See Bin.apply_priority_boost
    for the "can only ever raise urgency, never lower it" guarantee.
    """
    bin_obj = get_bin(bin_id)
    if bin_obj is None:
        raise BinServiceError(f"Bin '{bin_id}' not found.")

    try:
        bin_obj.apply_priority_boost(requested_priority, reason)
    except ValueError as e:
        raise BinServiceError(str(e))

    _persist_bin_state(bin_obj)
    execute(
        """INSERT INTO priority_requests
           (bin_id, requested_by_user_id, automatic_priority, requested_priority, reason)
           VALUES (?, ?, ?, ?, ?)""",
        (bin_id, requested_by_user_id, bin_obj.automatic_priority, requested_priority, reason),
    )
    return bin_obj


def update_bin_waste_level(bin_id, new_waste_level):
    """
    Update a bin's waste level. Priority is recomputed automatically
    (Bin.update_waste_level enforces this - see models/bin_model.py).
    """
    bin_obj = get_bin(bin_id)
    if bin_obj is None:
        raise BinServiceError(f"Bin '{bin_id}' not found.")
    try:
        bin_obj.update_waste_level(new_waste_level)
    except ValueError as e:
        raise BinServiceError(str(e))
    _persist_bin_state(bin_obj)
    return bin_obj


def mark_bin_collected(bin_id):
    bin_obj = get_bin(bin_id)
    if bin_obj is None:
        raise BinServiceError(f"Bin '{bin_id}' not found.")
    bin_obj.mark_collected()
    _persist_bin_state(bin_obj)
    return bin_obj


def mark_bin_assigned(bin_id):
    """
    Reserve a bin into a GENERATED/ASSIGNED route without collecting it
    yet. An ASSIGNED bin is excluded from get_active_bins() (so it
    won't be planned into a second, overlapping route), but its waste
    data is untouched until a collector actually collects it.
    """
    bin_obj = get_bin(bin_id)
    if bin_obj is None:
        raise BinServiceError(f"Bin '{bin_id}' not found.")
    bin_obj.status = "ASSIGNED"
    _persist_bin_state(bin_obj)
    return bin_obj


def reactivate_bin(bin_id):
    """Used after a demo reset, or when a collected bin starts filling again."""
    bin_obj = get_bin(bin_id)
    if bin_obj is None:
        raise BinServiceError(f"Bin '{bin_id}' not found.")
    bin_obj.status = "ACTIVE"
    _persist_bin_state(bin_obj)
    return bin_obj


def delete_bin(bin_id):
    bin_obj = get_bin(bin_id)
    if bin_obj is None:
        raise BinServiceError(f"Bin '{bin_id}' not found.")
    if bin_obj.status == "ASSIGNED":
        raise BinServiceError("This bin is part of a saved route and cannot be deleted. Cancel the route first.")
    execute("DELETE FROM pending_requests WHERE bin_id = ?", (bin_id,))
    execute("DELETE FROM bins WHERE bin_id = ?", (bin_id,))
    _bin_cache.pop(bin_id, None)


def update_bin(bin_id, name=None, current_waste_kg=None, waste_level=None,
                maximum_capacity_kg=None, status=None, waste_category=None, notes=None):
    """
    General-purpose update used by the PUT /api/bins/<id> endpoint.
    Only the fields actually passed in are changed. If waste_level is
    provided, priority is automatically recomputed (via Bin.update_waste_level) -
    the caller never sets priority directly.
    """
    bin_obj = get_bin(bin_id)
    if bin_obj is None:
        raise BinServiceError(f"Bin '{bin_id}' not found.")

    if name is not None:
        bin_obj.name = name
    if current_waste_kg is not None:
        if current_waste_kg < 0:
            raise BinServiceError("current_waste_kg cannot be negative.")
        bin_obj.current_waste_kg = current_waste_kg
    if maximum_capacity_kg is not None:
        if maximum_capacity_kg <= 0:
            raise BinServiceError("maximum_capacity_kg must be greater than 0.")
        bin_obj.maximum_capacity_kg = maximum_capacity_kg
    if waste_level is not None:
        try:
            bin_obj.update_waste_level(waste_level)
        except ValueError as e:
            raise BinServiceError(str(e))
    if status is not None:
        bin_obj.status = status
    if waste_category is not None:
        bin_obj.waste_category = waste_category or None
    if notes is not None:
        bin_obj.notes = notes or None

    execute(
        """UPDATE bins
           SET name = ?, current_waste_kg = ?, waste_level = ?, priority = ?,
               automatic_priority = ?, maximum_capacity_kg = ?, status = ?,
               waste_category = ?, notes = ?
           WHERE bin_id = ?""",
        (bin_obj.name, bin_obj.current_waste_kg, bin_obj.waste_level, bin_obj.priority,
         bin_obj.automatic_priority, bin_obj.maximum_capacity_kg, bin_obj.status,
         bin_obj.waste_category, bin_obj.notes, bin_obj.bin_id),
    )
    _bin_cache[bin_id] = bin_obj
    return bin_obj


def clear_cache():
    _bin_cache.clear()


# ----------------------------------------------------------------------
# Depot management (single depot, stored in the `locations` table)
# ----------------------------------------------------------------------

def set_depot(name, latitude, longitude, is_demo=False):
    """
    Create or replace the single depot location.
    This project supports exactly one depot at a time, matching the
    spec's "Select/add a waste collection depot" (one depot, section 3).
    """
    if not (-90 <= latitude <= 90) or not (-180 <= longitude <= 180):
        raise BinServiceError(f"Invalid depot coordinates: ({latitude}, {longitude})")

    existing = query_one("SELECT id FROM locations WHERE location_type = 'DEPOT'")
    if existing is not None:
        execute(
            "UPDATE locations SET name = ?, latitude = ?, longitude = ?, is_demo = ? WHERE location_type = 'DEPOT'",
            (name, latitude, longitude, int(is_demo)),
        )
    else:
        execute(
            "INSERT INTO locations (name, latitude, longitude, location_type, is_demo) VALUES (?, ?, ?, 'DEPOT', ?)",
            (name, latitude, longitude, int(is_demo)),
        )
    return get_depot()


def get_depot():
    """Returns a dict {name, latitude, longitude, is_demo} or None if no depot is set yet."""
    row = query_one("SELECT * FROM locations WHERE location_type = 'DEPOT'")
    if row is None:
        return None
    return {
        "name": row["name"], "latitude": row["latitude"], "longitude": row["longitude"],
        "is_demo": bool(row["is_demo"]),
    }
