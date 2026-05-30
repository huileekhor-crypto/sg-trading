"""Settings page — account size, risk%, email."""

from flask import Blueprint, jsonify, request, render_template
from models.journal import get_settings, update_settings

settings_bp = Blueprint("settings", __name__)


@settings_bp.route("/settings")
def settings_page():
    return render_template("settings.html")


@settings_bp.route("/api/settings")
def get_s():
    return jsonify(get_settings())


@settings_bp.route("/api/settings", methods=["PUT"])
def update_s():
    data = request.get_json()
    try:
        update_settings({
            "account_size":  float(data.get("account_size", 20000)),
            "weekly_target": float(data.get("weekly_target", 1500)),
            "swing_risk":    float(data.get("swing_risk", 2.0)),
            "lt_position":   float(data.get("lt_position", 7.5)),
            "email":         str(data.get("email", "")),
        })
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 400
