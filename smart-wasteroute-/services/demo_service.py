"""
services/demo_service.py

Load Demo Data / Clear Demo Data (Section 21 of the spec).

Creates exactly what the spec asks for:
    1 Depot, 8 Waste Bins, 2 Vehicles, with the exact waste-level
    sequence from the spec's example (35, 95, 82, 67, 91, 48, 76, 88).

EVERY demo-created row is flagged is_demo=1 (bins, vehicles, and the
depot's location row all have this column). Clear Demo Data deletes
ONLY rows flagged is_demo=1 - it can NEVER delete real user-created
data, even if the user has both demo and real bins/vehicles at the
same time. This directly satisfies the spec's requirement: "Do not
accidentally delete real user data unless the user explicitly chooses
to clear everything."

Graph connections are NOT created here - the Graph is always rebuilt
live from whatever depot + active bins currently exist
(route_service.build_graph_from_db), so demo bins automatically become
graph vertices with real Haversine-computed edges the moment they're
created. There is nothing extra to set up for "Graph connections".
"""

from database.db import execute, query_one, query_all
from services import auth_service, bin_service, vehicle_service

DEPOT_NAME = "Demo Depot"
DEPOT_LAT, DEPOT_LON = 18.5204, 73.8567  # a fixed reference point; bins are offset from here

DEFAULT_BIN_CAPACITY_KG = 50

# Exact waste-level sequence from Section 21 of the spec (Bin 1 -> Bin 8).
# Offsets are small lat/lon deltas from the depot so every bin sits a
# realistic 1-4km away by real Haversine distance, not stacked on top
# of each other.
DEMO_BINS = [
    {"bin_id": "DEMOBIN01", "name": "Bin 1 - Hostel Block", "waste_level": 35, "offset": (0.006, -0.004)},
    {"bin_id": "DEMOBIN02", "name": "Bin 2 - Canteen", "waste_level": 95, "offset": (-0.005, 0.007)},
    {"bin_id": "DEMOBIN03", "name": "Bin 3 - Library", "waste_level": 82, "offset": (0.010, 0.003)},
    {"bin_id": "DEMOBIN04", "name": "Bin 4 - Admin Block", "waste_level": 67, "offset": (-0.008, -0.006)},
    {"bin_id": "DEMOBIN05", "name": "Bin 5 - Sports Ground", "waste_level": 91, "offset": (0.013, -0.010)},
    {"bin_id": "DEMOBIN06", "name": "Bin 6 - Parking Lot", "waste_level": 48, "offset": (-0.011, 0.012)},
    {"bin_id": "DEMOBIN07", "name": "Bin 7 - Main Gate", "waste_level": 76, "offset": (0.003, 0.015)},
    {"bin_id": "DEMOBIN08", "name": "Bin 8 - Workshop", "waste_level": 88, "offset": (-0.014, -0.002)},
]

DEMO_VEHICLES = [
    {"vehicle_id": "DEMOVEH01", "vehicle_number": "MH12DM0001", "driver_name": "Ramesh Kumar", "maximum_capacity_kg": 100,
     "vehicle_type": "Compactor Truck", "collector_mobile": "9000000001"},
    {"vehicle_id": "DEMOVEH02", "vehicle_number": "MH12DM0002", "driver_name": "Suresh Patil", "maximum_capacity_kg": 80,
     "vehicle_type": "Mini Van", "collector_mobile": "9000000002"},
]

# Vehicle information belongs to a COLLECTOR, so each demo vehicle also gets a
# demo collector account (flagged is_demo, removed by Clear Demo Data).
DEMO_COLLECTOR_PASSWORD = "collector123"


class DemoServiceError(Exception):
    pass


def is_demo_loaded():
    row = query_one("SELECT COUNT(*) as cnt FROM bins WHERE is_demo = 1")
    return row["cnt"] > 0


def load_demo_data():
    """
    Create 1 demo depot, 8 demo bins (exact waste levels from the
    spec), and 2 demo vehicles. Refuses to run twice in a row without
    a clear in between, since bin_id/vehicle_id are unique - this
    avoids a confusing duplicate-ID error surfacing from deep inside
    bin_service instead of a clear top-level message.
    """
    if is_demo_loaded():
        raise DemoServiceError("Demo data is already loaded. Clear it first before loading again.")

    existing_depot = bin_service.get_depot()
    if existing_depot is not None and not existing_depot["is_demo"]:
        raise DemoServiceError(
            "A real depot is already set. Loading demo data would overwrite it, "
            "since this project supports only one depot at a time. Remove or note "
            "down your real depot's location before loading demo data."
        )

    bin_service.set_depot(DEPOT_NAME, DEPOT_LAT, DEPOT_LON, is_demo=True)

    created_bins = []
    for spec in DEMO_BINS:
        d_lat, d_lon = spec["offset"]
        current_waste_kg = round(spec["waste_level"] / 100 * DEFAULT_BIN_CAPACITY_KG, 1)
        bin_obj = bin_service.create_bin(
            bin_id=spec["bin_id"],
            name=spec["name"],
            latitude=DEPOT_LAT + d_lat,
            longitude=DEPOT_LON + d_lon,
            waste_level=spec["waste_level"],
            current_waste_kg=current_waste_kg,
            maximum_capacity_kg=DEFAULT_BIN_CAPACITY_KG,
            is_demo=True,
        )
        created_bins.append(bin_obj)

    created_vehicles = []
    created_collectors = []
    for spec in DEMO_VEHICLES:
        vehicle_obj = vehicle_service.create_vehicle(
            vehicle_id=spec["vehicle_id"],
            vehicle_number=spec["vehicle_number"],
            driver_name=spec["driver_name"],
            maximum_capacity_kg=spec["maximum_capacity_kg"],
            is_demo=True,
            vehicle_type=spec["vehicle_type"],
        )
        created_vehicles.append(vehicle_obj)
        c = auth_service.register_collector(spec["driver_name"], spec["collector_mobile"], "",
                                            DEMO_COLLECTOR_PASSWORD, vehicle_id=spec["vehicle_id"])
        execute("UPDATE collectors SET is_demo = 1 WHERE collector_code = ?", (c["collector_code"],))
        created_collectors.append(c)

    # Demo bins are real pending collection requests: put them in the Queue.
    from services import route_service
    route_service.enqueue_all_active_bins()

    return {
        "depot": bin_service.get_depot(),
        "bins_created": [b.bin_id for b in created_bins],
        "vehicles_created": [v.vehicle_id for v in created_vehicles],
        "collectors_created": created_collectors,
        "collector_password": DEMO_COLLECTOR_PASSWORD,
    }


def clear_demo_data():
    """
    Delete ONLY rows flagged is_demo=1 across bins, vehicles, and
    locations (the depot). Also cleans up any pending_requests that
    reference a demo bin about to be deleted, so no orphaned request
    rows are left pointing at a bin_id that no longer exists.

    collection_history is deliberately NOT touched - it's a historical
    record of what actually happened and stays intact even after the
    demo bins/vehicles that produced it are cleared, the same way a
    real vehicle's trip log wouldn't be deleted just because the
    vehicle was later decommissioned.
    """
    demo_bin_ids = [row["bin_id"] for row in query_all("SELECT bin_id FROM bins WHERE is_demo = 1")]

    for bin_id in demo_bin_ids:
        execute("DELETE FROM pending_requests WHERE bin_id = ?", (bin_id,))

    execute("DELETE FROM bins WHERE is_demo = 1")
    execute("DELETE FROM vehicles WHERE is_demo = 1")
    execute("DELETE FROM collectors WHERE is_demo = 1")
    execute("DELETE FROM locations WHERE is_demo = 1")

    bin_service.clear_cache()
    vehicle_service.clear_cache()

    return {"bins_deleted": len(demo_bin_ids)}
