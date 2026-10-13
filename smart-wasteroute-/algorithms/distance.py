"""
algorithms/distance.py

Haversine distance calculation - a SUPPORTING ALGORITHM, not a data
structure. Its only job is to answer: "given two (latitude, longitude)
points on Earth, how far apart are they in a straight line?"

WHY WE NEED THIS:
    The Graph's edge weights (data_structures/graph.py) need to be real
    numbers representing distance. Rather than requiring the user to
    manually type in distances between every bin and the depot, we
    calculate them automatically from the GPS coordinates captured by
    clicking on the map.

WHY HAVERSINE (not straight-line Euclidean distance on lat/lng)?
    Latitude and longitude are angles on a SPHERE, not flat x/y
    coordinates. Treating them as flat coordinates and using ordinary
    Euclidean distance (Pythagoras) would give a wrong, meaningless
    number, especially over larger distances, because the same change
    in longitude covers a different real-world distance depending on
    how far you are from the equator. The Haversine formula accounts
    for the Earth's curvature and gives distance in real kilometers.

IMPORTANT HONESTY NOTE (per the project spec):
    Haversine distance is a STRAIGHT-LINE ("as the crow flies") distance
    between two GPS points. It is NOT the actual road distance a
    vehicle would drive - a real road has turns, one-way streets, and
    obstacles a straight line ignores. This project clearly labels
    every distance calculated this way as "Haversine / Geographic"
    distance (see roads.distance_type in the database schema) and never
    pretends it is actual road distance. Getting real road distance
    would require a routing engine (e.g. Google Maps Directions API),
    which is intentionally NOT used here - the DSA logic (Graph,
    Priority Queue, Dijkstra) must operate on data our own Python code
    computes, not on results from an external service.

THE FORMULA:
    a = sin²(Δlat / 2) + cos(lat1) * cos(lat2) * sin²(Δlon / 2)
    c = 2 * atan2( sqrt(a), sqrt(1 - a) )
    distance = R * c

    where R = Earth's mean radius (6371 km), and all angles are in
    radians (GPS coordinates are normally given in degrees, so they
    must be converted first).

COMPLEXITY:
    Time:  O(1) - a fixed number of arithmetic operations per pair of points.
    Space: O(1).
"""

import math

EARTH_RADIUS_KM = 6371.0


def haversine_distance(lat1, lon1, lat2, lon2):
    """
    Calculate the great-circle (straight-line) distance in kilometers
    between two GPS coordinates using the Haversine formula.

    Args:
        lat1, lon1: latitude/longitude of the first point, in degrees.
        lat2, lon2: latitude/longitude of the second point, in degrees.

    Returns:
        Distance in kilometers (float), rounded to 3 decimal places.
    """
    # Convert all degrees to radians - Python's math trig functions
    # expect radians, not degrees.
    lat1_rad = math.radians(lat1)
    lon1_rad = math.radians(lon1)
    lat2_rad = math.radians(lat2)
    lon2_rad = math.radians(lon2)

    delta_lat = lat2_rad - lat1_rad
    delta_lon = lon2_rad - lon1_rad

    a = (math.sin(delta_lat / 2) ** 2 +
         math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(delta_lon / 2) ** 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    distance_km = EARTH_RADIUS_KM * c
    return round(distance_km, 3)


def build_distance_matrix(locations):
    """
    Given a list of locations, each a dict with at least
    {"name": ..., "latitude": ..., "longitude": ...}, compute the
    Haversine distance between every unique pair.

    This is a convenience helper (not itself a new algorithm) used by
    route_service.py in a later step to populate Graph edges without
    hand-writing nested loops there. It does not decide WHICH edges to
    keep (that is route_service's job) - it simply returns every
    pairwise distance.

    Returns:
        A list of tuples: (location_a_name, location_b_name, distance_km)
        One tuple per unique pair (n*(n-1)/2 pairs for n locations).

    Complexity:
        Time:  O(n^2) - every pair of n locations is compared once.
                For this project's scale (1 depot + 5-10 bins, so
                n <= 11), this is at most 55 pairs - trivially fast.
        Space: O(n^2) for the returned list of pairs.
    """
    pairs = []
    n = len(locations)
    for i in range(n):
        for j in range(i + 1, n):
            loc_a = locations[i]
            loc_b = locations[j]
            dist = haversine_distance(
                loc_a["latitude"], loc_a["longitude"],
                loc_b["latitude"], loc_b["longitude"],
            )
            pairs.append((loc_a["name"], loc_b["name"], dist))
    return pairs
