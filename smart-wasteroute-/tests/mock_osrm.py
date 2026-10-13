"""
tests/mock_osrm.py

A tiny stand-in for an OSRM server, used ONLY by the automated tests
(the test sandbox has no internet access). It speaks the same two
endpoints the app uses - /table and /route - and returns "roads" laid out
as an L-shaped grid between points (never a single straight segment), so
the tests can prove the app stores/draws whatever geometry the routing
engine returns instead of connecting coordinates with straight lines.

This is NOT the real road network: real-road behaviour must be checked
against a real OSRM server (see README).
"""

import json
import math
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer


def _hav_m(a, b):
    R = 6371000.0
    la1, lo1, la2, lo2 = map(math.radians, (a[1], a[0], b[1], b[0]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * R * math.asin(math.sqrt(h))


def _road_path(a, b):
    """a, b = (lon, lat). Go along a 'north-south street' then an 'east-west street'."""
    corner = (a[0], b[1])
    return [a, corner, b]


def _road_len_m(a, b):
    c = (a[0], b[1])
    return _hav_m(a, c) + _hav_m(c, b)


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        # NOTE: urlparse() would treat ";" in the path as path-params and drop coordinates.
        parts = self.path.split("?")[0].strip("/").split("/")
        service, coords = parts[0], parts[3]
        pts = [tuple(float(x) for x in c.split(",")) for c in coords.split(";")]
        if service == "table":
            body = {"code": "Ok", "distances": [[round(_road_len_m(a, b), 1) if a != b else 0.0 for b in pts] for a in pts]}
        else:
            legs, total = [], 0.0
            for a, b in zip(pts, pts[1:]):
                d = _road_len_m(a, b)
                total += d
                path = _road_path(a, b)
                steps = [{"geometry": {"type": "LineString", "coordinates": [list(p) for p in path[:2]]}},
                         {"geometry": {"type": "LineString", "coordinates": [list(p) for p in path[1:]]}}]
                legs.append({"distance": d, "duration": d / 8.0, "steps": steps})
            body = {"code": "Ok", "routes": [{"distance": total, "duration": total / 8.0, "legs": legs}]}
        data = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def start(port=0):
    server = HTTPServer(("127.0.0.1", port), _Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_port}"
