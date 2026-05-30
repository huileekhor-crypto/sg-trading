"""Tab 3: Manage — open positions with live P&L."""

from flask import Blueprint, jsonify, request, render_template
from models.journal import (get_positions, add_position, update_position,
                             close_position, log_trade, get_settings)
from utils.prices import get_live_price
from utils.position_calc import position_health
from utils.unusual_whales import smart_money_score

manage_bp = Blueprint("manage", __name__)


@manage_bp.route("/manage")
def manage_page():
    return render_template("manage.html")


@manage_bp.route("/api/positions")
def positions():
    pos_list = get_positions()
    enriched = []
    for p in pos_list:
        pd = get_live_price(p["ticker"])
        current = pd.get("price", p["entry_price"])
        health  = position_health(
            p["entry_price"], current, p.get("stop"), p.get("target"), p.get("mode", "SWING")
        )
        # Check if swing stop is hit and user is holding — Metaplanet warning
        stop_warning = False
        if p.get("mode") == "SWING" and p.get("stop") and current <= p["stop"] * 1.02:
            stop_warning = True

        enriched.append({
            **p,
            "current_price": current,
            "pnl_dollars":   round((current - p["entry_price"]) * (p.get("shares") or 0), 2),
            "pnl_pct":       health.get("pnl_pct", 0),
            "signals":       health.get("signals", []),
            "stop_warning":  stop_warning,
            "price_data":    pd,
        })
    return jsonify(enriched)


@manage_bp.route("/api/positions", methods=["POST"])
def add_pos():
    data = request.get_json()
    required = ["ticker", "entry_price", "shares"]
    if not all(data.get(k) for k in required):
        return jsonify({"error": "ticker, entry_price, shares required"}), 400
    data["ticker"] = data["ticker"].upper()
    add_position(data)
    return jsonify({"success": True})


@manage_bp.route("/api/positions/<int:pos_id>", methods=["PUT"])
def update_pos(pos_id):
    data = request.get_json()
    update_position(pos_id, data)
    return jsonify({"success": True})


@manage_bp.route("/api/positions/<int:pos_id>/close", methods=["POST"])
def close_pos(pos_id):
    data      = request.get_json()
    exit_price = data.get("exit_price")
    if not exit_price:
        return jsonify({"error": "exit_price required"}), 400

    pos = close_position(pos_id)
    if not pos:
        return jsonify({"error": "Position not found"}), 404

    # Auto-log to journal
    log_trade({
        "ticker":      pos["ticker"],
        "mode":        pos.get("mode", "SWING"),
        "entry_price": pos["entry_price"],
        "exit_price":  float(exit_price),
        "shares":      pos.get("shares", 0),
        "stop":        pos.get("stop"),
        "target":      pos.get("target"),
        "score":       pos.get("score", 0),
        "notes":       data.get("notes", ""),
        "date_open":   pos.get("date_open"),
    })
    return jsonify({"success": True})


@manage_bp.route("/api/positions/<int:pos_id>/uw-check")
def uw_check(pos_id):
    pos_list = get_positions()
    pos = next((p for p in pos_list if p["id"] == pos_id), None)
    if not pos:
        return jsonify({"error": "Not found"}), 404
    uw = smart_money_score(pos["ticker"])
    return jsonify({"ticker": pos["ticker"], "uw": uw})
