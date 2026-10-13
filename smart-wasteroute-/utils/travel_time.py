"""
utils/travel_time.py

ONE function converts road distance to estimated travel time, using the
single configuration value Config.ESTIMATED_MINUTES_PER_KM (config.py).
Nothing else in the project may multiply distance by a minutes-per-km
number - they all call this function, so changing the rule is a
one-line edit in config.py.
"""

from config import Config


def estimate_travel_minutes(distance_km):
    """distance_km x ESTIMATED_MINUTES_PER_KM, rounded to 1 decimal."""
    if distance_km is None:
        return None
    return round(float(distance_km) * Config.ESTIMATED_MINUTES_PER_KM, 1)
