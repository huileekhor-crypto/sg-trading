"""Tab 4: Journal — trade history, stats, $1M mission tracker."""

from flask import Blueprint, jsonify, request, render_template
from models.journal import get_trades, log_trade, get_stats, get_settings
from utils.senior_trader import generate_journal_insight

journal_bp = Blueprint("journal", __name__)


@journal_bp.route("/journal")
def journal_page():
    return render_template("journal.html")


@journal_bp.route("/api/trades")
def trades():
    limit = int(request.args.get("limit", 100))
    return jsonify(get_trades(limit))


@journal_bp.route("/api/trades", methods=["POST"])
def add_trade():
    data = request.get_json()
    if not data.get("ticker"):
        return jsonify({"error": "ticker required"}), 400
    data["ticker"] = data["ticker"].upper()
    log_trade(data)
    return jsonify({"success": True})


@journal_bp.route("/api/stats")
def stats():
    s        = get_stats()
    settings = get_settings()
    account  = settings.get("account_size", 20000)
    weekly   = settings.get("weekly_target", 1500)
    s["account_size"]  = account
    s["weekly_target"] = weekly
    s["target_1m"]     = 1_000_000
    s["progress_pct"]  = round(account / 1_000_000 * 100, 2)
    return jsonify(s)


@journal_bp.route("/api/journal/insight")
def journal_insight():
    trades_list = get_trades(50)
    insight = generate_journal_insight(trades_list)
    return jsonify({"insight": insight})
