"""
services/auth_service.py

Authentication for two separate roles: USER and COLLECTOR.
Passwords are always hashed with werkzeug.security (bundled with
Flask - no new dependency needed) and NEVER stored or returned in
plain text.

Session-based auth: on successful login, a small set of values is
stored in Flask's session (server-signed cookie) - user_code/
collector_code and role. routes/auth_routes.py provides
@login_required / @collector_required decorators that check these.
"""

import re
from datetime import date, datetime
from werkzeug.security import generate_password_hash, check_password_hash
from database.db import query_one, query_all, execute

MIN_PASSWORD_LENGTH = 6
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MOBILE_RE = re.compile(r"^\+?\d{7,15}$")


class AuthError(Exception):
    """Raised for validation or credential failures."""
    pass


def _calculate_age(date_of_birth_str):
    """
    Compute age from a date-of-birth string (YYYY-MM-DD), server-side.
    The client-submitted "age" field, if any, is never trusted -
    this is the only source of truth for age.
    """
    try:
        dob = datetime.strptime(date_of_birth_str, "%Y-%m-%d").date()
    except ValueError:
        raise AuthError("Date of birth must be in YYYY-MM-DD format.")

    today = date.today()
    if dob > today:
        raise AuthError("Date of birth cannot be in the future.")

    age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
    if age < 5 or age > 120:
        raise AuthError(f"Calculated age ({age}) is not reasonable. Please check the date of birth.")
    return age


def _next_code(table, code_column, prefix, start, pad_width=0):
    """
    Generate the next sequential code like USR1001 / COL001 by finding
    the highest existing numeric suffix for this prefix and adding 1.
    Simple and sufficient at this project's scale (no concurrent
    signups to race against in a single-process Flask dev server).

    pad_width: if > 0, zero-pads the number to this width (e.g.
    pad_width=3 -> COL001, COL002, ... COL010, ...).
    """
    rows = query_all(f"SELECT {code_column} FROM {table} WHERE {code_column} LIKE ?", (f"{prefix}%",))
    max_num = start - 1
    for row in rows:
        suffix = row[code_column][len(prefix):]
        if suffix.isdigit():
            max_num = max(max_num, int(suffix))
    next_num = max_num + 1
    number_str = str(next_num).zfill(pad_width) if pad_width else str(next_num)
    return f"{prefix}{number_str}"


# ----------------------------------------------------------------------
# USER registration / login
# ----------------------------------------------------------------------

def register_user(full_name, date_of_birth, email, mobile, password, confirm_password):
    full_name = (full_name or "").strip()
    email = (email or "").strip().lower()
    mobile = (mobile or "").strip()

    if len(full_name) < 2:
        raise AuthError("Please enter a valid full name.")
    if not EMAIL_RE.match(email):
        raise AuthError("Please enter a valid email address.")
    if not MOBILE_RE.match(mobile):
        raise AuthError("Please enter a valid mobile number.")
    if len(password) < MIN_PASSWORD_LENGTH:
        raise AuthError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters.")
    if password != confirm_password:
        raise AuthError("Passwords do not match.")

    age = _calculate_age(date_of_birth)  # also validates the date format/range

    if query_one("SELECT id FROM users WHERE email = ?", (email,)) is not None:
        raise AuthError("An account with this email already exists.")

    user_code = _next_code("users", "user_code", "USR", 1001)
    password_hash = generate_password_hash(password)

    execute(
        """INSERT INTO users (user_code, full_name, date_of_birth, age, email, mobile, password_hash)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (user_code, full_name, date_of_birth, age, email, mobile, password_hash),
    )
    return {"user_code": user_code, "full_name": full_name, "age": age}


def login_user(identifier, password):
    """identifier can be a user_code (USR1001) or an email."""
    identifier = (identifier or "").strip()
    row = query_one("SELECT * FROM users WHERE user_code = ? OR email = ?", (identifier, identifier.lower()))
    if row is None or not check_password_hash(row["password_hash"], password):
        raise AuthError("Invalid login ID or password.")
    return dict(row)


def get_user(user_code):
    row = query_one("SELECT * FROM users WHERE user_code = ?", (user_code,))
    return dict(row) if row else None


def update_user_profile(user_code, full_name=None, mobile=None):
    """Only non-sensitive fields (name, mobile) may be edited - email/DOB/age are fixed identity facts."""
    user = get_user(user_code)
    if user is None:
        raise AuthError("User not found.")
    full_name = full_name.strip() if full_name else user["full_name"]
    mobile = mobile.strip() if mobile else user["mobile"]
    if len(full_name) < 2:
        raise AuthError("Please enter a valid full name.")
    if not MOBILE_RE.match(mobile):
        raise AuthError("Please enter a valid mobile number.")
    execute("UPDATE users SET full_name = ?, mobile = ? WHERE user_code = ?", (full_name, mobile, user_code))
    return get_user(user_code)


# ----------------------------------------------------------------------
# COLLECTOR registration / login
# ----------------------------------------------------------------------

def register_collector(name, mobile, email, password, vehicle_id=None):
    """
    No public collector self-registration page is exposed (collectors
    are added by whoever runs the demo, matching the spec's "for demo
    purposes, create an easy way for an admin/demo setup to create
    collector accounts") - this function is called from a small
    admin-style form on the Collector Portal page.
    """
    name = (name or "").strip()
    mobile = (mobile or "").strip()
    if len(name) < 2:
        raise AuthError("Please enter a valid collector name.")
    if not MOBILE_RE.match(mobile):
        raise AuthError("Please enter a valid mobile number.")
    if len(password) < MIN_PASSWORD_LENGTH:
        raise AuthError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters.")

    collector_code = _next_code("collectors", "collector_code", "COL", 1, pad_width=3)
    password_hash = generate_password_hash(password)

    execute(
        """INSERT INTO collectors (collector_code, name, mobile, email, password_hash, vehicle_id)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (collector_code, name, mobile, (email or "").strip() or None, password_hash, vehicle_id),
    )
    return {"collector_code": collector_code, "name": name}


def login_collector(collector_code, password):
    collector_code = (collector_code or "").strip()
    row = query_one("SELECT * FROM collectors WHERE collector_code = ?", (collector_code,))
    if row is None or not check_password_hash(row["password_hash"], password):
        raise AuthError("Invalid Collector ID or password.")
    return dict(row)


def get_collector(collector_code):
    row = query_one("SELECT * FROM collectors WHERE collector_code = ?", (collector_code,))
    return dict(row) if row else None


def get_all_collectors():
    return [dict(row) for row in query_all("SELECT * FROM collectors ORDER BY collector_code")]
