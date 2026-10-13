"""
utils/api_helpers.py

Small shared helpers so every API blueprint returns errors in the same
JSON shape, instead of each route file inventing its own format.
"""

from flask import jsonify


def success(data=None, status=200):
    return jsonify({"success": True, "data": data}), status


def error(message, status=400):
    return jsonify({"success": False, "error": message}), status
