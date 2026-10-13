"""
routes/demo_routes.py

REST API for demo data (Section 25 of the spec).
    POST   /api/demo/load
    DELETE /api/demo/clear

These were intentionally NOT registered back in Step 13 - registering
them before demo_service actually existed would have meant fake/stub
API responses, which Section 32 forbids. Now that Step 20 has built
the real logic behind them, they're wired up for real.
"""

from flask import Blueprint
from services import demo_service
from services.demo_service import DemoServiceError
from utils.api_helpers import success, error

demo_bp = Blueprint("demo_api", __name__, url_prefix="/api/demo")


@demo_bp.route("/load", methods=["POST"])
def load_demo():
    try:
        result = demo_service.load_demo_data()
    except DemoServiceError as e:
        return error(str(e))
    return success(result, status=201)


@demo_bp.route("/clear", methods=["DELETE"])
def clear_demo():
    result = demo_service.clear_demo_data()
    return success(result)
