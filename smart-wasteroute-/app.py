"""
app.py

Flask application entry point.

Creates the Flask app, initialises the SQLite database and registers the
page routes and REST API blueprints.

Pages for a normal user: Dashboard, Add Bins & Route (/add-bin), Requests,
History, Reports, Profile (+ the public Data Structures page).
Collectors use /collector/dashboard (route, collection and vehicle management).
There is deliberately NO separate Routes, Vehicles, Bins or Map page.
"""

from flask import Flask, render_template, request, send_from_directory, session, redirect, url_for
from config import Config
from database.db import init_db
from utils.api_helpers import error

from routes.bin_routes import bin_bp, depot_bp
from routes.vehicle_routes import vehicle_bp
from routes.route_routes import route_bp
from routes.planning_routes import planning_bp
from routes.history_routes import history_bp
from routes.dashboard_routes import dashboard_bp
from routes.request_routes import request_bp
from routes.report_routes import report_bp
from routes.data_structure_routes import ds_bp
from routes.demo_routes import demo_bp
from routes.auth_routes import auth_bp
from routes.collector_routes import collector_bp, collectors_bp
from routes.user_routes import user_bp
from routes.auth_routes import login_required, collector_required


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    # Initialize the database (creates instance/database.db and all
    # tables from database/schema.sql if they don't already exist).
    init_db()

    register_routes(app)
    register_api_blueprints(app)

    return app


def register_api_blueprints(app):
    """REST API endpoints (Section 25 of the spec)."""
    app.register_blueprint(bin_bp)
    app.register_blueprint(depot_bp)
    app.register_blueprint(vehicle_bp)
    app.register_blueprint(route_bp)
    app.register_blueprint(planning_bp)
    app.register_blueprint(history_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(request_bp)
    app.register_blueprint(report_bp)
    app.register_blueprint(ds_bp)
    app.register_blueprint(demo_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(collector_bp)
    app.register_blueprint(collectors_bp)
    app.register_blueprint(user_bp)


def register_routes(app):

    @app.route("/uploads/bins/<filename>")
    def uploaded_bin_image(filename):
        return send_from_directory(Config.UPLOAD_FOLDER, filename)

    @app.route("/")
    def home():
        return render_template("index.html")

    @app.route("/register")
    def register_page():
        if session.get("role") == "user":
            return redirect(url_for("dashboard_page"))
        return render_template("register.html")

    @app.route("/login")
    def login_page():
        if session.get("role") == "user":
            return redirect(url_for("dashboard_page"))
        return render_template("login.html")

    @app.route("/collector/login")
    def collector_login_page():
        if session.get("role") == "collector":
            return redirect(url_for("collector_dashboard_page"))
        return render_template("collector_login.html")

    @app.route("/profile")
    @login_required
    def profile_page():
        return render_template("profile.html")

    @app.route("/add-bin")
    @login_required
    def add_bin_page():
        # "Add Bins & Route": the ONE workflow for bins -> priority -> vehicle -> road route -> save.
        return render_template("add_bin.html")

    @app.route("/collector/dashboard")
    @collector_required
    def collector_dashboard_page():
        return render_template("collector_dashboard.html")

    @app.route("/data-structures")
    def data_structures_page():
        # Deliberately left PUBLIC (not @login_required): this page is
        # purely educational/read-only, and keeping it open lets a
        # professor review the DSA explanations without needing to
        # register or log in first - a reasonable exception to an
        # otherwise fully login-gated app.
        return render_template("data_structures.html")

    @app.route("/history")
    @login_required
    def history_page():
        return render_template("history.html")

    @app.route("/reports")
    @login_required
    def reports_page():
        return render_template("reports.html")

    @app.route("/requests")
    @login_required
    def requests_page():
        return render_template("requests.html")

    @app.route("/dashboard")
    @login_required
    def dashboard_page():
        return render_template("dashboard.html")

    @app.errorhandler(404)
    def not_found(e):
        if request.path.startswith("/api/"):
            return error("The requested API endpoint does not exist.", status=404)
        return "Page not found. (Custom 404 handling will improve in a later step.)", 404

    @app.errorhandler(500)
    def server_error(e):
        if request.path.startswith("/api/"):
            return error("An unexpected server error occurred.", status=500)
        return "Something went wrong on the server. (Custom error handling improves in a later step.)", 500


# Module-level app object - lets `flask run` and WSGI servers find it,
# and lets `python app.py` work directly too.
app = create_app()

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
