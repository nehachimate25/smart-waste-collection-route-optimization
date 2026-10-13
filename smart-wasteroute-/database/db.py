"""
database/db.py

Small helper module around Python's built-in sqlite3 library.
Keeps all raw SQL connection handling in one place so services never
open a connection directly - they call get_connection() or the
convenience query functions below.
"""

import sqlite3
import os
from config import Config


def get_connection():
    """
    Open a new SQLite connection.

    row_factory = sqlite3.Row lets us access columns by name
    (row["bin_id"]) instead of by index (row[1]), which makes the
    rest of the codebase far more readable.
    """
    conn = sqlite3.connect(Config.DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _ensure_column(conn, table, column, coldef):
    """
    Add a column to an existing table ONLY if it doesn't already exist.
    SQLite has no "ADD COLUMN IF NOT EXISTS", so this checks
    PRAGMA table_info first. This is what makes schema changes SAFE
    for an existing database created by an earlier version of this
    project - no table is ever dropped or recreated, and no existing
    row's data is touched.
    """
    existing_columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in existing_columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {coldef}")


def _migrate_bins_table(conn):
    """
    Add the new bin columns introduced for user ownership, image
    storage, and the priority-boost workflow. Every ADD COLUMN below
    is guarded by _ensure_column, so running this against a database
    that already has these columns (or a brand-new database) is a
    harmless no-op either way.
    """
    _ensure_column(conn, "bins", "user_id", "TEXT")
    _ensure_column(conn, "bins", "image_filename", "TEXT")
    _ensure_column(conn, "bins", "automatic_priority", "TEXT")
    _ensure_column(conn, "bins", "priority_boost", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(conn, "bins", "requested_priority", "TEXT")
    _ensure_column(conn, "bins", "boost_reason", "TEXT")
    _ensure_column(conn, "bins", "waste_category", "TEXT")
    _ensure_column(conn, "bins", "notes", "TEXT")


def _migrate_collection_history_table(conn):
    """Links a completed route's full detail (collector, timing, status) back to its archival history row."""
    _ensure_column(conn, "collection_history", "route_code", "TEXT")


def _migrate_route_workflow_tables(conn):
    """Columns added for the road-based multi-trip workflow (all guarded, additive)."""
    _ensure_column(conn, "routes", "root_route_code", "TEXT")
    _ensure_column(conn, "routes", "parent_route_code", "TEXT")
    _ensure_column(conn, "routes", "version", "INTEGER NOT NULL DEFAULT 1")
    _ensure_column(conn, "routes", "priority_mode", "TEXT")
    _ensure_column(conn, "routes", "total_trips", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(conn, "routes", "total_time_min", "REAL NOT NULL DEFAULT 0")
    _ensure_column(conn, "vehicles", "vehicle_type", "TEXT")
    _ensure_column(conn, "collectors", "is_demo", "INTEGER NOT NULL DEFAULT 0")


def init_db():
    """
    Create the instance/ folder if missing, then run schema.sql.
    Safe to call every time the app starts - all statements in
    schema.sql use CREATE TABLE IF NOT EXISTS. After that, run the
    small set of guarded column migrations for tables that existed
    before this feature set was added (see _migrate_bins_table) -
    this is what lets an existing database upgrade safely instead of
    silently breaking.
    """
    instance_dir = os.path.dirname(Config.DATABASE_PATH)
    os.makedirs(instance_dir, exist_ok=True)

    with open(Config.SCHEMA_PATH, "r") as f:
        schema_sql = f.read()

    conn = get_connection()
    try:
        conn.executescript(schema_sql)
        _migrate_bins_table(conn)
        _migrate_collection_history_table(conn)
        _migrate_route_workflow_tables(conn)
        conn.commit()
    finally:
        conn.close()


def query_all(sql, params=()):
    """Run a SELECT and return all rows as a list of sqlite3.Row objects."""
    conn = get_connection()
    try:
        cursor = conn.execute(sql, params)
        return cursor.fetchall()
    finally:
        conn.close()


def query_one(sql, params=()):
    """Run a SELECT and return a single row (or None)."""
    conn = get_connection()
    try:
        cursor = conn.execute(sql, params)
        return cursor.fetchone()
    finally:
        conn.close()


def execute(sql, params=()):
    """
    Run an INSERT/UPDATE/DELETE.
    Returns the new row's id (for INSERT) via cursor.lastrowid.
    """
    conn = get_connection()
    try:
        cursor = conn.execute(sql, params)
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()
