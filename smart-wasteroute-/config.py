"""
config.py

Central configuration for the Flask app.
Keeping all configuration in one file makes it easy to explain in viva
and easy to change (e.g. switching database path) without hunting
through the codebase.
"""

import os

# Base directory of the project (folder containing this file)
BASE_DIR = os.path.abspath(os.path.dirname(__file__))


class Config:
    # --- Flask settings ---
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-key-change-in-production")
    DEBUG = True

    # --- Database settings ---
    DATABASE_PATH = os.path.join(BASE_DIR, "instance", "database.db")
    SCHEMA_PATH = os.path.join(BASE_DIR, "database", "schema.sql")

    # --- Map settings ---
    # The Map page uses Leaflet + OpenStreetMap, which needs no API key
    # or billing account - nothing to configure here.

    # --- Bin image upload settings ---
    UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads", "bins")
    ALLOWED_IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}
    MAX_IMAGE_SIZE_BYTES = 5 * 1024 * 1024  # 5 MB

    # --- Vehicle / route settings ---
    # Used by route_service.py so these numbers aren't hard-coded there.
    DEFAULT_VEHICLE_CAPACITY_KG = 100

    # --- Travel-time rule (SINGLE place this number lives) ---
    # estimated minutes = road distance (km) x ESTIMATED_MINUTES_PER_KM
    # Everything (analysis, route legs, history, reports) calls
    # utils.travel_time.estimate_travel_minutes(), which reads this value.
    ESTIMATED_MINUTES_PER_KM = 10

    # --- Road routing engine (OSRM) ---
    # REAL road geometry + road distance come from here. The public demo
    # server is fine for a college demo (fair-use only); for heavier use
    # point OSRM_BASE_URL at your own OSRM instance, e.g.
    #   set OSRM_BASE_URL=http://localhost:5001
    OSRM_BASE_URL = os.environ.get("OSRM_BASE_URL", "https://router.project-osrm.org")
    OSRM_PROFILE = "driving"
    OSRM_TIMEOUT_SECONDS = 15
    OSRM_RETRIES = 2

    # --- Priority thresholds ---
    # Imported from utils/priority_config.py so this remains the ONE
    # place priority logic lives, even though config.py re-exports it
    # for convenience (services can do `from config import get_priority`).
    from utils.priority_config import get_priority, get_priority_weight, PRIORITY_THRESHOLDS  # noqa: E402,F401
