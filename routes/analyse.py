"""Tab 2: Analyse — single stock 6-layer deep dive."""

from flask import Blueprint, jsonify, request, render_template
from utils.analysis_engine import run_full_analysis
from utils.position_calc import calc_swing_setup, calc_lt_setup
from utils.senior_trader import generate_analysis
from models.journal import get_settings

analyse_bp = Blueprint("analyse", __name__)


@analyse_bp.route("/api/seasonality/<ticker>")
def seasonality(ticker):
    from utils.unusual_whales import get_seasonality_note, uw_seasonality
    note = get_seasonality_note(ticker.upper())
    raw  = uw_seasonality(ticker.upper())
    return jsonify({"ticker": ticker.upper(), "note": note, "data": raw})


@analyse_bp.route("/analyse")
def analyse_page():
    ticker = request.args.get("ticker", "").upper()
    return render_template("analyse.html", ticker=ticker)


@analyse_bp.route("/api/analyse", methods=["POST"])
def analyse():
    data   = request.get_json()
    ticker = (data.get("ticker") or "").upper().strip()
    mode   = (data.get("mode") or "SWING").upper()

    if not ticker:
        return jsonify({"error": "Ticker required"}), 400
    if mode not in ("SWING", "LONG-TERM"):
        mode = "SWING"

    settings = get_settings()
    account  = settings.get("account_size", 20000)
    risk     = settings.get("swing_risk", 2.0)
    lt_pos   = settings.get("lt_position", 7.5)

    try:
        analysis = run_full_analysis(ticker, mode)
    except Exception as e:
        return jsonify({"error": f"Analysis failed: {e}"}), 500

    price = analysis["price"]
    if not price:
        return jsonify({"error": f"Could not fetch price for {ticker}"}), 404

    atr = analysis["technicals"].get("atr")
    if mode == "SWING":
        trade = calc_swing_setup(price, atr, account, risk)
    else:
        trade = calc_lt_setup(price, atr, account, lt_pos)

    # AI narrative
    try:
        ai = generate_analysis(ticker, analysis, settings)
    except Exception:
        ai = {"why_buy": "", "why_fail": "", "when_to_enter": "",
              "exit_strategy": "", "verdict": ""}

    # Weekly target progress
    weekly_target = settings.get("weekly_target", 1500)
    pot_gain = trade.get("potential_gain", 0)
    weekly_pct = round(pot_gain / weekly_target * 100, 1) if weekly_target else 0

    # Build IBKR order string
    ibkr_order = (
        f"Buy {trade.get('shares', 0)} {ticker} limit ${price:.2f}, "
        f"stop ${trade.get('stop', 0):.2f}, "
        f"target ${trade.get('target', 0):.2f}"
    )

    return jsonify({
        "ticker":           ticker,
        "mode":             mode,
        "score":            analysis["score"],
        "verdict":          analysis["verdict"],
        "verdict_class":    analysis["verdict_class"],
        "price_data":       analysis["price_data"],
        "price":            price,
        "layers":           analysis["layers"],
        "technicals":       analysis["technicals"],
        "fundamentals":     analysis["fundamentals"],
        "news":             analysis["news"],
        "discipline":       analysis["discipline"],
        "trade":            trade,
        "ai":               ai,
        "candles":          analysis["candles"],
        "weekly_pct":       weekly_pct,
        "ibkr_order":       ibkr_order,
        "earnings_warning": analysis.get("earnings_warning"),
        "seasonality_note": analysis.get("seasonality_note"),
        "settings":         {"account": account, "risk": risk, "weekly": weekly_target},
    })
