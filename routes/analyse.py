"""Tab 2: Analyse — single stock 6-layer deep dive."""

from flask import Blueprint, jsonify, request, render_template
from utils.analysis_engine import run_full_analysis
from utils.position_calc import calc_swing_setup, calc_lt_setup
from utils.senior_trader import generate_analysis
from models.journal import get_settings


def _stale_check(ticker, price_data):
    """
    Compare extended-hours price (pre/post market) to regular-session close.
    UW has no price data — Yahoo Finance is the only source.
    Returns dict with stale flag, extended price, session label, and message.
    """
    reg_price  = price_data.get("price", 0)
    pre_price  = price_data.get("pre_price")
    post_price = price_data.get("post_price")
    mkt_state  = price_data.get("market_state", "CLOSED")

    # Map Yahoo marketState to human label (shown in SGT context)
    session_labels = {
        "REGULAR": "Regular session",
        "PRE":     "Pre-market",
        "PREPRE":  "Pre-market",
        "POST":    "After-hours",
        "POSTPOST":"After-hours",
        "CLOSED":  "Market closed",
    }
    session_label = session_labels.get(mkt_state, mkt_state or "Unknown")

    # Pick the relevant extended price
    if mkt_state in ("PRE", "PREPRE") and pre_price:
        ext_price = pre_price
    elif mkt_state in ("POST", "POSTPOST") and post_price:
        ext_price = post_price
    elif pre_price:   # CLOSED but pre-market data available (early morning)
        ext_price = pre_price
    elif post_price:  # CLOSED but post-market data available (overnight)
        ext_price = post_price
    else:
        ext_price = None

    if mkt_state == "REGULAR":
        return {
            "stale": False, "extended_price": None, "extended_pct": 0,
            "session_label": session_label,
            "message": "Prices current — live regular session",
            "source": "Yahoo Finance",
        }

    if not ext_price or not reg_price:
        return {
            "stale": False, "extended_price": None, "extended_pct": 0,
            "session_label": session_label,
            "message": "Prices current — no extended-hours data available",
            "source": "Yahoo Finance",
        }

    pct = (ext_price - reg_price) / reg_price * 100
    sign = "+" if pct >= 0 else ""
    stale = abs(pct) > 1.0

    if stale:
        msg = (
            f"⚠ STALE: {ticker} is ${ext_price:.2f} in {session_label.lower()} "
            f"({sign}{pct:.1f}% vs ${reg_price:.2f} this setup is based on). "
            f"Recalculate before trading."
        )
    else:
        msg = f"Prices current ({sign}{pct:.1f}% in {session_label.lower()})"

    return {
        "stale":          stale,
        "extended_price": ext_price,
        "extended_pct":   round(pct, 2),
        "session_label":  session_label,
        "message":        msg,
        "source":         "Yahoo Finance (UW has no price data on this plan)",
    }

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

    atr           = analysis["technicals"].get("atr")
    planned       = analysis.get("planned_entry", {})
    planned_entry = planned.get("entry", price)

    if mode == "SWING":
        trade = calc_swing_setup(planned_entry, atr, account, risk)
    else:
        trade = calc_lt_setup(planned_entry, atr, account, lt_pos)

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

    stale = _stale_check(ticker, analysis["price_data"])

    entry_type = planned.get("entry_type", "MARKET")
    ibkr_order = (
        f"Buy {trade.get('shares', 0)} {ticker} "
        f"{'LMT' if entry_type in ('BREAKOUT','PULLBACK') else 'MKT'} "
        f"${planned_entry:.2f} GTC, "
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
        "planned_entry":    planned,
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
        "stale_setup":      stale,
        "settings":         {"account": account, "risk": risk, "weekly": weekly_target},
    })
