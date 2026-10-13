"""
utils/priority_config.py

SINGLE SOURCE OF TRUTH for waste-bin priority thresholds.

WHY THIS FILE EXISTS:
The project spec requires that priority thresholds (LOW / MEDIUM / HIGH / CRITICAL)
be defined in exactly ONE place and never duplicated across the codebase.
Every other file (bin_service.py, route_service.py, templates, etc.) must
import get_priority() from here instead of re-writing the if/else logic.

This is NOT a data structure itself - it is a small helper function used
BY the data structures (e.g. it decides what "priority" value gets pushed
into the Priority Queue for a given bin).
"""

# Priority bands, in percentage of bin capacity filled.
# Kept as a single dictionary so the ranges can be displayed on the
# Data Structures page exactly as they are used in code (no duplication).
PRIORITY_THRESHOLDS = {
    "LOW": (0, 50),        # 0% - 50%
    "MEDIUM": (51, 75),    # 51% - 75%
    "HIGH": (76, 90),      # 76% - 90%
    "CRITICAL": (91, 100), # 91% - 100%
}

# Numeric weight used internally by the Priority Queue / Min Heap.
# LOWER number = HIGHER real-world urgency, because our Min Heap
# always extracts the SMALLEST value first (see data_structures/min_heap.py).
# So CRITICAL bins must get the smallest number.
PRIORITY_WEIGHT = {
    "CRITICAL": 1,
    "HIGH": 2,
    "MEDIUM": 3,
    "LOW": 4,
}


def get_priority(waste_level: float) -> str:
    """
    Convert a waste level percentage (0-100) into a priority label.

    Args:
        waste_level: float or int, expected range 0-100.

    Returns:
        One of "LOW", "MEDIUM", "HIGH", "CRITICAL".

    Raises:
        ValueError: if waste_level is outside 0-100 (invalid data guard).
    """
    if waste_level is None:
        raise ValueError("waste_level cannot be None")

    if waste_level < 0 or waste_level > 100:
        raise ValueError(f"waste_level must be between 0 and 100, got {waste_level}")

    for label, (low, high) in PRIORITY_THRESHOLDS.items():
        if low <= waste_level <= high:
            return label

    # Should never reach here if thresholds cover 0-100, but kept as a safe default.
    return "LOW"


def get_priority_weight(waste_level: float) -> int:
    """
    Convert a waste level directly into the numeric weight used by the
    Priority Queue / Min Heap (lower number = collected first).
    """
    label = get_priority(waste_level)
    return PRIORITY_WEIGHT[label]


# ----------------------------------------------------------------------
# Route-priority MODES (what the user picks on the Add Bins & Route page).
# The ordering key for each mode is built in services/planning_service.py;
# the labels/descriptions live here so the UI and backend share ONE list.
# ----------------------------------------------------------------------
DEFAULT_PRIORITY_MODE = "BALANCED"

PRIORITY_MODES = {
    "BALANCED": {
        "label": "Balanced Priority",
        "description": "Urgency band first (CRITICAL > HIGH > MEDIUM > LOW), then the "
                       "higher priority score, then shorter distance, then shorter time.",
    },
    "HIGHEST_WASTE": {
        "label": "Highest Waste First",
        "description": "Fullest bin first. Distance and time only break ties.",
    },
    "SHORTEST_DISTANCE": {
        "label": "Shortest Distance First",
        "description": "Closest bin to the depot (by road) first. Waste level breaks ties.",
    },
    "FASTEST_TIME": {
        "label": "Fastest Estimated Time First",
        "description": "Smallest estimated travel time first. Waste level breaks ties.",
    },
}

# Weights of the 0-100 "Priority Score" shown in the analysis table.
# score = W_WASTE * waste% + W_DISTANCE * closeness% + W_TIME * time-closeness%
# (closeness: nearest bin in the session = 100, farthest = 0). Must sum to 1.
PRIORITY_SCORE_WEIGHTS = {"waste": 0.60, "distance": 0.25, "time": 0.15}
