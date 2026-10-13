"""
routes/user_routes.py

    GET /api/users/me   - the logged-in user's own profile
    PUT /api/users/me   - edit non-sensitive profile fields (name, mobile)

Deliberately scoped to "me" only - there's no endpoint to fetch or
edit an arbitrary user by ID, since nothing in this app needs that and
it would be an unnecessary information-disclosure surface.
"""

from flask import Blueprint, request, session
from services import auth_service
from services.auth_service import AuthError
from utils.api_helpers import success, error

user_bp = Blueprint("users_api", __name__, url_prefix="/api/users")


@user_bp.route("/me", methods=["GET"])
def get_me():
    if session.get("role") != "user" or not session.get("user_code"):
        return error("Please log in to continue.", status=401)
    user = auth_service.get_user(session["user_code"])
    if user is None:
        return error("User not found.", status=404)
    user.pop("password_hash", None)  # never send the hash to the client
    return success(user)


@user_bp.route("/me", methods=["PUT"])
def update_me():
    if session.get("role") != "user" or not session.get("user_code"):
        return error("Please log in to continue.", status=401)

    body = request.get_json(silent=True) or {}
    try:
        user = auth_service.update_user_profile(
            session["user_code"], full_name=body.get("full_name"), mobile=body.get("mobile"),
        )
    except AuthError as e:
        return error(str(e))

    user.pop("password_hash", None)
    return success(user)
