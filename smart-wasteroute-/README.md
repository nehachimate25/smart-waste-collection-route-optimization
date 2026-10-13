# Smart Waste Collection Management (Flask + SQLite) — road-based workflow

Data Structures project: Queue, Priority Queue (Min Heap), Graph (adjacency list), Stack and Hash Table
(Python dict cache) decide **which bin is collected when**; the **OSRM** routing engine supplies the **real
road geometry and road distance** that Leaflet draws.

## Run

```bash
pip install -r requirements.txt
python app.py                      # http://localhost:5000
```
Internet access is needed in the browser (Leaflet + OpenStreetMap tiles) and on the server (OSRM).
Default routing server is the public OSRM demo (`https://router.project-osrm.org`, fair-use only). For
real use run your own OSRM and set `OSRM_BASE_URL`, e.g. `set OSRM_BASE_URL=http://localhost:5001`.

Tests (use a local mock routing server, no internet): `python -m unittest tests.test_workflow -v`

## Pages

| Normal user | Collector |
|---|---|
| Dashboard · **Add Bins & Route** · Requests · History · Reports · Profile (+ public Data Structures page) | Collector Dashboard with sections: Today's Assignment, **My Vehicle**, Assigned Routes, Collection History, Profile |

Removed: Routes page, Vehicles page, Bins page, Map page (and their JS/templates/nav links).

## The workflow

```
Add Bins & Route:  depot -> click map (many bins) -> bin details modal -> Priority Analysis
  -> choose priority mode -> choose available vehicle -> GENERATE (draft, nothing saved)
  -> review road route on the map -> Regenerate or Save
Collector:         Start Collection -> Mark Collected (strict sequence) -> Return to Depot (unload) -> next trip ... -> route COMPLETED
History / Reports: read the stored routes, trips, collection events and depot events
Requests:          pick a saved (not yet started) route + pending bins -> Update Route -> saved as R001-V2 (R001 kept)
```

## Road routing (real roads, never straight lines)

`services/osrm_service.py` is the only module that talks to OSRM:
* `/table` -> road distance matrix (priority analysis, Graph edge weights),
* `/route` (`steps=true`, `geometries=geojson`) -> per-leg road polyline + road km.

Each leg's polyline is stored in `route_steps.segment_geometry` and drawn by `static/js/route_view.js`.
If OSRM is unreachable the API answers HTTP 503 with `osrm_unavailable: true`, the UI shows a warning and a
Retry button, **nothing is drawn and nothing is saved** — there is no straight-line fallback.
Haversine remains only in `algorithms/distance.py`, the Data Structures demo graph, and as a small
"straight-line (academic)" column in the analysis table.

## Priority

Bands (single source `utils/priority_config.py`, shown in the UI): LOW 0–50, MEDIUM 51–75, HIGH 76–90, CRITICAL 91–100.
Modes (same file): **Balanced (default)**, Highest Waste, Shortest Distance, Fastest Estimated Time.
Pipeline (`services/planning_service.py`): selected bins -> **Queue** (arrival order) -> drained into the
**Priority Queue / Min Heap** with a mode-specific key:

* Balanced: (urgency band, −score, road km, minutes) — urgency first, then score, then distance, then time
* Highest Waste: (−waste %, km, min) · Shortest Distance: (km, −waste %, min) · Fastest Time: (min, −waste %, km)

`score = 0.60·waste% + 0.25·closeness + 0.15·time-closeness` (nearest bin = 100, farthest = 0; weights in
`PRIORITY_SCORE_WEIGHTS`). Because time = km × constant, time-closeness equals distance-closeness; it is kept as
the third criterion the spec asks for. Every row shows a plain-language "why this position".

## Estimated time

`ESTIMATED_MINUTES_PER_KM = 10` lives only in `config.py`; `utils/travel_time.estimate_travel_minutes()` is the only
place that applies it (analysis, every route segment, history, reports). The UI reads it from `/api/planning/config`.

## Vehicle capacity

Bins are taken in priority order. If the next bin does not fit, the vehicle returns to the depot (unload) and a
**new trip** starts with that bin — a more urgent bin is never delayed for a less urgent one. First trip capacity =
vehicle max − current load; later trips = full capacity. A bin heavier than the vehicle's maximum is skipped with
"Bin cannot be collected because its waste quantity exceeds vehicle capacity." and stays pending.

## Database (additive; existing databases upgrade automatically)

New tables: `route_trips`, `route_steps`, `collection_events`, `depot_events`, `vehicle_assignments`.
New columns: `routes` (root_route_code, parent_route_code, version, priority_mode, total_trips, total_time_min),
`vehicles.vehicle_type`, `collectors.is_demo`. `route_stops` is legacy (no longer written).
Route codes: `R001`, versions `R001-V2`… Route statuses: ASSIGNED, IN_PROGRESS, COMPLETED, CANCELLED, SUPERSEDED.

## API

`GET /api/planning/config` · `POST /api/planning/analyze` · `POST /api/planning/generate` · `POST /api/planning/save`
`GET /api/routes[?status=]` · `GET /api/routes/<code>` · `POST /api/routes/<code>/cancel`
`GET /api/vehicles` · `GET /api/vehicles/available` (read-only for users)
`GET /api/collector/my-route|routes|vehicle|profile` · `POST /api/collector/start-collection|collect-stop|return-to-depot|vehicle` · `PUT /api/collector/vehicle|profile`
`GET /api/history` · `GET /api/reports/summary` · `GET /api/requests/pending|priority`
Existing: bins, depot, dashboard, demo, auth, data-structures, `POST /api/routes/shortest-path`, legacy `POST /api/routes/collect`.

## Demo

Dashboard -> *Load Demo Data*: depot, 8 bins, 2 vehicles, each owned by a demo collector (`COL001`, `COL002`,
password `collector123`). Then: Add Bins & Route -> add the pending bins -> pick a vehicle -> Generate -> Save ->
log in as the collector -> collect.
