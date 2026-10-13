"""
routes/auth_routes.py

Session-based authentication for two roles: USER and COLLECTOR.
Uses Flask's built-in signed-cookie session (backed by app.config["SECRET_KEY"],
already set in config.py) - no extra library needed.

    POST /api/auth/register             - user self-registration
    POST /api/auth/login                - user login
    POST /api/auth/logout               - clears the session (either role)
    POST /api/auth/collector/register   - demo/admin-style collector creation
    POST /api/auth/collector/login      - collector login
    GET  /api/auth/me                   - current session identity, for the frontend

@login_required and @collector_required are used to protect PAGE routes in
app.py - an unauthenticated visitor is redirected to the appropriate login
page rather than seeing a blank/broken page.
"""

from functools import wraps
from flask import Blueprint, request, session, redirect, url_for
from services import auth_service
from services.auth_service import AuthError
from utils.api_helpers import success, error

auth_bp = Blueprint("auth_api", __name__, url_prefix="/api/auth")


def login_required(view_func):
    """Protects USER-facing pages. Redirects to the login page if not logged in as a user."""
    @wraps(view_func)
    def wrapped(*args, **kwargs):
        if session.get("role") != "user" or not session.get("user_code"):
            return redirect(url_for("login_page"))
        return view_func(*args, **kwargs)
    return wrapped


def collector_required(view_func):
    """Protects COLLECTOR-facing pages. Redirects to the collector login page if not logged in as a collector."""
    @wraps(view_func)
    def wrapped(*args, **kwargs):
        if session.get("role") != "collector" or not session.get("collector_code"):
            return redirect(url_for("collector_login_page"))
        return view_func(*args, **kwargs)
    return wrapped


def require_login_api(view_func):
    """
    Protects MUTATING API endpoints (bins/vehicles/depot/routes/requests/demo)
    from being called directly by an unauthenticated client, independent of
    whether the page itself was reached. Returns a clean 401 JSON error
    rather than redirecting, since this is an API response, not a page.
    """
    @wraps(view_func)
    def wrapped(*args, **kwargs):
        if session.get("role") != "user" or not session.get("user_code"):
            return error("Please log in to continue.", status=401)
        return view_func(*args, **kwargs)
    return wrapped


@auth_bp.route("/register", methods=["POST"])
def register():
    body = request.get_json(silent=True)
    if not body:
        return error("Request body must be valid JSON.")

    required = ["full_name", "date_of_birth", "email", "mobile", "password", "confirm_password"]
    missing = [f for f in required if f not in body]
    if missing:
        return error(f"Missing required field(s): {', '.join(missing)}")

    try:
        result = auth_service.register_user(
            body["full_name"], body["date_of_birth"], body["email"],
            body["mobile"], body["password"], body["confirm_password"],
        )
    except AuthError as e:
        return error(str(e))

    return success(result, status=201)


@auth_bp.route("/login", methods=["POST"])
def login():
    body = request.get_json(silent=True)
    if not body or "identifier" not in body or "password" not in body:
        return error("Both 'identifier' (User ID or email) and 'password' are required.")

    try:
        user = auth_service.login_user(body["identifier"], body["password"])
    except AuthError as e:
        return error(str(e), status=401)

    session["role"] = "user"
    session["user_code"] = user["user_code"]
    session["full_name"] = user["full_name"]

    return success({"user_code": user["user_code"], "full_name": user["full_name"]})


@auth_bp.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return success({"logged_out": True})


@auth_bp.route("/collector/register", methods=["POST"])
def collector_register():
    body = request.get_json(silent=True)
    if not body:
        return error("Request body must be valid JSON.")

    required = ["name", "mobile", "password"]
    missing = [f for f in required if f not in body]
    if missing:
        return error(f"Missing required field(s): {', '.join(missing)}")

    try:
        result = auth_service.register_collector(
            body["name"], body["mobile"], body.get("email", ""), body["password"], body.get("vehicle_id"),
        )
    except AuthError as e:
        return error(str(e))

    return success(result, status=201)


@auth_bp.route("/collector/login", methods=["POST"])
def collector_login():
    body = request.get_json(silent=True)
    if not body or "collector_code" not in body or "password" not in body:
        return error("Both 'collector_code' and 'password' are required.")

    try:
        collector = auth_service.login_collector(body["collector_code"], body["password"])
    except AuthError as e:
        return error(str(e), status=401)

    session["role"] = "collector"
    session["collector_code"] = collector["collector_code"]
    session["collector_name"] = collector["name"]

    return success({"collector_code": collector["collector_code"], "name": collector["name"]})


@auth_bp.route("/me", methods=["GET"])
def me():
    if session.get("role") == "user":
        return success({"role": "user", "user_code": session.get("user_code"), "full_name": session.get("full_name")})
    if session.get("role") == "collector":
        return success({"role": "collector", "collector_code": session.get("collector_code"), "name": session.get("collector_name")})
    return success(None)
