"""
services/osrm_service.py

REAL ROAD VISUALIZATION layer.

This module is the ONLY place that talks to the road-routing engine
(OSRM). Leaflet is just the map-drawing library; the road geometry,
road distance and the road distance matrix all come from OSRM:

    coordinates -> OSRM -> road geometry -> Leaflet polyline

A straight line between two coordinates is NEVER produced here. If OSRM
cannot be reached we raise OsrmError and let the caller show a warning;
we do not fall back to fake geometry.

Uses only the standard library (urllib), so requirements.txt stays
"Flask only".
"""

import json
import time
import urllib.error
import urllib.request

from config import Config


class OsrmError(Exception):
    """Raised when the routing engine is unreachable or returns no route."""
    pass


def _coords_param(points):
    # OSRM wants lon,lat (note the order) separated by ';'
    return ";".join(f"{p['longitude']:.6f},{p['latitude']:.6f}" for p in points)


def _get_json(path_and_query):
    url = Config.OSRM_BASE_URL.rstrip("/") + path_and_query
    last_error = None
    for attempt in range(Config.OSRM_RETRIES + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "smart-waste-route/1.0"})
            with urllib.request.urlopen(req, timeout=Config.OSRM_TIMEOUT_SECONDS) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            if data.get("code") != "Ok":
                raise OsrmError(f"Routing engine replied '{data.get('code')}': {data.get('message', 'no route found')}")
            return data
        except OsrmError:
            raise
        except (urllib.error.URLError, TimeoutError, ValueError, OSError) as e:
            last_error = e
            time.sleep(0.4 * (attempt + 1))
    raise OsrmError(f"Road routing service is unreachable ({last_error}).")


def road_distance_matrix(points):
    """
    Road distance (km) between EVERY pair of points via OSRM /table.
    points: list of {"latitude":..,"longitude":..}
    Returns an n x n list of lists (km). matrix[i][j] = road km from i to j.
    """
    if len(points) < 2:
        return [[0.0]]
    data = _get_json(f"/table/v1/{Config.OSRM_PROFILE}/{_coords_param(points)}?annotations=distance")
    rows = data.get("distances")
    if not rows:
        raise OsrmError("Routing engine returned no distance table.")
    matrix = []
    for r in rows:
        matrix.append([(None if v is None else round(v / 1000.0, 3)) for v in r])
    for r in matrix:
        if any(v is None for v in r):
            raise OsrmError("One of the locations is not reachable by road.")
    return matrix


def road_route(points):
    """
    Drive through `points` in the given order (depot, bin, bin, ..., depot).

    Returns {
        "distance_km": total road km,
        "legs": [ {"distance_km": km, "geometry": [[lat, lng], ...]}, ... ]  # len = len(points)-1
    }
    The geometry of each leg is the road polyline OSRM returned for that
    leg (assembled from OSRM's road-step geometries).
    """
    if len(points) < 2:
        raise OsrmError("At least two points are needed to build a road route.")
    data = _get_json(
        f"/route/v1/{Config.OSRM_PROFILE}/{_coords_param(points)}"
        "?overview=false&geometries=geojson&steps=true"
    )
    routes = data.get("routes") or []
    if not routes:
        raise OsrmError("Routing engine returned no route.")
    route = routes[0]

    legs = []
    for leg in route["legs"]:
        line = []
        for step in leg.get("steps", []):
            for lon, lat in step["geometry"]["coordinates"]:
                pt = [round(lat, 6), round(lon, 6)]
                if not line or line[-1] != pt:
                    line.append(pt)
        if len(line) < 2:
            raise OsrmError("Routing engine returned an empty road geometry.")
        legs.append({"distance_km": round(leg["distance"] / 1000.0, 3), "geometry": line})
    return {"distance_km": round(route["distance"] / 1000.0, 3), "legs": legs}
