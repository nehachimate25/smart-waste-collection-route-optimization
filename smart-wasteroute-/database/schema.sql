-- ============================================================
-- database/schema.sql
-- SQLite schema for Smart Waste Collection Management
-- ============================================================
-- This file is executed once when the app starts (if tables don't
-- already exist). It defines all 5 core tables from the project spec,
-- plus one small extra table (pending_requests) that persists the
-- Queue data structure's contents across server restarts so a live
-- demo doesn't lose pending requests if Flask is restarted.
-- ============================================================

PRAGMA foreign_keys = ON;

-- ------------------------------------------------------------
-- BINS
-- Represents a waste bin. Also becomes a vertex in the Graph and
-- a value stored in the Hash Table (keyed by bin_id).
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS bins (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    bin_id              TEXT UNIQUE NOT NULL,       -- e.g. "BIN001"
    name                TEXT NOT NULL,
    latitude            REAL NOT NULL,
    longitude           REAL NOT NULL,
    waste_level         REAL NOT NULL DEFAULT 0,    -- percentage 0-100
    current_waste_kg    REAL NOT NULL DEFAULT 0,
    maximum_capacity_kg REAL NOT NULL DEFAULT 100,
    priority            TEXT NOT NULL DEFAULT 'LOW', -- LOW/MEDIUM/HIGH/CRITICAL
    status              TEXT NOT NULL DEFAULT 'ACTIVE', -- ACTIVE/COLLECTED/INACTIVE
    is_demo             INTEGER NOT NULL DEFAULT 0,  -- 1 = created by "Load Demo Data"
    created_at          TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ------------------------------------------------------------
-- VEHICLES
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS vehicles (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    vehicle_id          TEXT UNIQUE NOT NULL,        -- e.g. "VEH001"
    vehicle_number      TEXT NOT NULL,
    driver_name         TEXT NOT NULL,
    maximum_capacity_kg REAL NOT NULL,
    current_load_kg     REAL NOT NULL DEFAULT 0,
    status              TEXT NOT NULL DEFAULT 'AVAILABLE', -- AVAILABLE/ON ROUTE/FULL/MAINTENANCE
    is_demo             INTEGER NOT NULL DEFAULT 0,
    created_at          TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ------------------------------------------------------------
-- LOCATIONS
-- Generic location table covering both the DEPOT and BIN points.
-- This is what actually gets loaded into the in-memory Graph as
-- vertices, so depot + bins share one consistent coordinate source.
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS locations (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL,
    latitude        REAL NOT NULL,
    longitude       REAL NOT NULL,
    location_type   TEXT NOT NULL,   -- DEPOT / BIN
    ref_bin_id      TEXT,            -- links to bins.bin_id when location_type = BIN
    is_demo         INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ------------------------------------------------------------
-- ROADS
-- Represents the Graph's edges (adjacency list persisted to disk).
-- Populated automatically from Haversine distance whenever locations
-- change - never hand-edited by the user.
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS roads (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    from_location   TEXT NOT NULL,   -- location name / identifier
    to_location     TEXT NOT NULL,
    distance        REAL NOT NULL,   -- kilometers
    distance_type   TEXT NOT NULL DEFAULT 'HAVERSINE'  -- HAVERSINE / ROAD
);

-- ------------------------------------------------------------
-- COLLECTION_HISTORY
-- One row per completed route (a vehicle's full trip).
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS collection_history (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    date                TEXT NOT NULL DEFAULT (datetime('now')),
    vehicle_id          TEXT NOT NULL,
    collected_bins      TEXT NOT NULL,   -- JSON list of bin_ids, e.g. ["BIN002","BIN005"]
    total_waste         REAL NOT NULL DEFAULT 0,
    total_distance       REAL NOT NULL DEFAULT 0,
    route               TEXT,            -- JSON ordered list of stops (depot -> bins -> depot)
    optimization_result TEXT             -- short text summary, e.g. "Priority-ordered, 2 stops"
);

-- ------------------------------------------------------------
-- USERS
-- Registered end-users who report bins. Passwords are always
-- hashed (werkzeug.security) - never stored in plain text.
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS users (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_code       TEXT UNIQUE NOT NULL,   -- e.g. "USR1001"
    full_name       TEXT NOT NULL,
    date_of_birth   TEXT NOT NULL,          -- ISO date, e.g. "2003-05-14"
    age             INTEGER NOT NULL,       -- always computed server-side from date_of_birth
    email           TEXT UNIQUE NOT NULL,
    mobile          TEXT NOT NULL,
    password_hash   TEXT NOT NULL,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ------------------------------------------------------------
-- COLLECTORS
-- Vehicle drivers/collectors who log in separately from users
-- and execute assigned routes.
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS collectors (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    collector_code  TEXT UNIQUE NOT NULL,   -- e.g. "COL001"
    name            TEXT NOT NULL,
    mobile          TEXT NOT NULL,
    email           TEXT,
    password_hash   TEXT NOT NULL,
    vehicle_id      TEXT,                   -- usually-assigned vehicle (soft reference to vehicles.vehicle_id)
    status          TEXT NOT NULL DEFAULT 'AVAILABLE', -- AVAILABLE / ON_DUTY / INACTIVE
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ------------------------------------------------------------
-- ROUTES
-- The live route-lifecycle table: GENERATED -> ASSIGNED ->
-- IN_PROGRESS -> COMPLETED (or CANCELLED). This is DIFFERENT
-- from collection_history below: a route lives here from the
-- moment it's generated, and is only written into
-- collection_history once it reaches COMPLETED - so existing
-- History/Reports code that reads collection_history keeps
-- working unchanged.
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS routes (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    route_code          TEXT UNIQUE NOT NULL,  -- e.g. "RT1007"
    vehicle_id          TEXT NOT NULL,
    collector_id        TEXT,                  -- NULL until "Assign Collector"
    depot_name          TEXT,
    depot_latitude      REAL,
    depot_longitude     REAL,
    total_bins          INTEGER NOT NULL DEFAULT 0,
    total_waste         REAL NOT NULL DEFAULT 0,   -- planned total, computed at generation time
    total_distance      REAL NOT NULL DEFAULT 0,   -- planned total, computed at generation time
    status              TEXT NOT NULL DEFAULT 'GENERATED', -- GENERATED/ASSIGNED/IN_PROGRESS/COMPLETED/CANCELLED
    created_by_user_id  TEXT,
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    assigned_at         TEXT,
    started_at          TEXT,
    completed_at        TEXT
);

-- ------------------------------------------------------------
-- ROUTE_STOPS  (LEGACY - superseded by route_trips / route_steps below)
-- Kept only so databases created by earlier versions still open.
-- The new workflow never writes to it.
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS route_stops (
    id                          INTEGER PRIMARY KEY AUTOINCREMENT,
    route_id                    INTEGER NOT NULL REFERENCES routes(id),
    sequence_order              INTEGER NOT NULL,
    bin_id                      TEXT NOT NULL,
    planned_waste_kg            REAL NOT NULL DEFAULT 0,
    distance_from_previous_km   REAL NOT NULL DEFAULT 0,
    status                      TEXT NOT NULL DEFAULT 'PENDING', -- PENDING / COLLECTED
    collected_at                TEXT
);

-- ------------------------------------------------------------
-- PRIORITY_REQUESTS
-- Audit log of every priority-boost request a user makes on a
-- bin. The bin's own automatic_priority/requested_priority/
-- priority_boost/boost_reason columns (see migration below)
-- always hold the CURRENT state; this table keeps the history.
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS priority_requests (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    bin_id                  TEXT NOT NULL,
    requested_by_user_id    TEXT,
    automatic_priority      TEXT NOT NULL,
    requested_priority      TEXT NOT NULL,
    reason                  TEXT NOT NULL,
    created_at              TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ------------------------------------------------------------
-- PENDING_REQUESTS  (added beyond the original spec - approved in Step 1)
-- Persists the contents of the in-memory Queue so pending collection
-- requests survive a Flask restart during a live demo.
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS pending_requests (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    bin_id      TEXT NOT NULL,
    requested_at TEXT NOT NULL DEFAULT (datetime('now')),
    status      TEXT NOT NULL DEFAULT 'PENDING' -- PENDING / PROCESSED
);


-- ============================================================
-- ROAD-BASED MULTI-TRIP ROUTE MODEL
-- routes (1) -> route_trips (n) -> route_steps (n)
-- A ROUTE is one collection session. A TRIP is depot -> bins -> depot
-- (a new trip starts whenever the vehicle fills up and unloads).
-- A STEP is one stop: DEPOT_START, BIN or DEPOT_RETURN, and carries the
-- road segment (distance, time, geometry) that leads TO that stop.
-- Route versions (R001, R001-V2 ...) are separate rows in `routes`
-- linked through routes.root_route_code / parent_route_code.
-- bin_id is deliberately NOT a foreign key: history must survive a bin
-- being deleted (e.g. Clear Demo Data), so name/lat/lng are snapshotted.
-- ============================================================
CREATE TABLE IF NOT EXISTS route_trips (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    route_id            INTEGER NOT NULL REFERENCES routes(id),
    trip_number         INTEGER NOT NULL,
    planned_waste_kg    REAL NOT NULL DEFAULT 0,
    total_distance_km   REAL NOT NULL DEFAULT 0,   -- real ROAD distance (OSRM)
    total_time_min      REAL NOT NULL DEFAULT 0,   -- distance x ESTIMATED_MINUTES_PER_KM
    capacity_kg         REAL NOT NULL DEFAULT 0,   -- capacity available when this trip departs
    initial_unload_kg   REAL NOT NULL DEFAULT 0,   -- load already on the vehicle that must be unloaded before this trip departs
    status              TEXT NOT NULL DEFAULT 'PENDING', -- PENDING / IN_PROGRESS / COMPLETED
    started_at          TEXT,
    completed_at        TEXT,
    UNIQUE (route_id, trip_number)
);

CREATE TABLE IF NOT EXISTS route_steps (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    route_id                INTEGER NOT NULL REFERENCES routes(id),
    trip_id                 INTEGER NOT NULL REFERENCES route_trips(id),
    step_order              INTEGER NOT NULL,          -- global order inside the route
    step_type               TEXT NOT NULL,             -- DEPOT_START / BIN / DEPOT_RETURN
    sequence_number         INTEGER,                   -- collection sequence (BIN steps only, 1..n over the whole route)
    bin_id                  TEXT,
    location_name           TEXT NOT NULL,
    latitude                REAL NOT NULL,
    longitude               REAL NOT NULL,
    waste_level             REAL,                      -- snapshot at planning time
    priority                TEXT,                      -- snapshot
    priority_score          REAL,
    planned_waste_kg        REAL NOT NULL DEFAULT 0,
    segment_distance_km     REAL NOT NULL DEFAULT 0,   -- road km from the previous step
    segment_time_min        REAL NOT NULL DEFAULT 0,
    cumulative_distance_km  REAL NOT NULL DEFAULT 0,   -- road km since route start, at this step
    load_after_kg           REAL NOT NULL DEFAULT 0,   -- planned vehicle load after this step
    segment_geometry        TEXT,                      -- JSON [[lat,lng],...] road polyline of the leg
    status                  TEXT NOT NULL DEFAULT 'PENDING', -- PENDING / IN_PROGRESS / COLLECTED / DONE
    started_at              TEXT,                      -- collector pressed "Start Collection"
    collected_at            TEXT                       -- collector pressed "Mark Collected"
);

CREATE TABLE IF NOT EXISTS collection_events (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    route_id                INTEGER NOT NULL REFERENCES routes(id),
    trip_id                 INTEGER NOT NULL REFERENCES route_trips(id),
    step_id                 INTEGER NOT NULL REFERENCES route_steps(id),
    bin_id                  TEXT NOT NULL,
    sequence_number         INTEGER NOT NULL,
    vehicle_id              TEXT NOT NULL,
    collector_id            TEXT NOT NULL,
    latitude                REAL,
    longitude               REAL,
    waste_collected_kg      REAL NOT NULL DEFAULT 0,
    vehicle_load_after_kg   REAL NOT NULL DEFAULT 0,
    segment_distance_km     REAL NOT NULL DEFAULT 0,
    distance_travelled_km   REAL NOT NULL DEFAULT 0,   -- cumulative at this point
    estimated_time_min      REAL NOT NULL DEFAULT 0,
    actual_time_min         REAL,                      -- collected_at - started_at, if the collector pressed Start
    collected_at            TEXT NOT NULL,
    status                  TEXT NOT NULL DEFAULT 'COLLECTED'
);

CREATE TABLE IF NOT EXISTS depot_events (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    route_id            INTEGER NOT NULL REFERENCES routes(id),
    trip_id             INTEGER REFERENCES route_trips(id),
    vehicle_id          TEXT NOT NULL,
    collector_id        TEXT NOT NULL,
    reason              TEXT NOT NULL,                 -- CAPACITY (vehicle full, more bins remain) / FINAL (route finished)
    return_distance_km  REAL NOT NULL DEFAULT 0,
    return_time_min     REAL NOT NULL DEFAULT 0,
    unloaded_kg         REAL NOT NULL DEFAULT 0,
    vehicle_load_after_kg REAL NOT NULL DEFAULT 0,
    vehicle_capacity_kg REAL NOT NULL DEFAULT 0,
    occurred_at         TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS vehicle_assignments (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    route_id        INTEGER NOT NULL REFERENCES routes(id),
    vehicle_id      TEXT NOT NULL,
    collector_id    TEXT,
    assigned_at     TEXT NOT NULL,
    released_at     TEXT
);
