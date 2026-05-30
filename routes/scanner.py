"""Tab 1: Scanner — daily 6-layer scan + manual trigger."""

import time
import threading
from flask import Blueprint, jsonify, request, render_template
from models.journal import get_latest_scan, save_scan_results, get_settings
from utils.tickers import get_scan_universe
from utils.analysis_engine import quick_score, run_full_analysis
from utils.position_calc import calc_swing_setup, calc_lt_setup

scanner_bp = Blueprint("scanner", __name__)

_scan_running = False
_scan_progress = {"status": "idle", "done": 0, "total": 0, "phase": ""}


@scanner_bp.route("/scan")
def scan_page():
    return render_template("scanner.html")


@scanner_bp.route("/api/scan/results")
def scan_results():
    rows  = get_latest_scan()
    swing = [r for r in rows if r.get("mode_tag") == "SWING"]
    lt    = [r for r in rows if r.get("mode_tag") == "LONG-TERM"]
    return jsonify({
        "swing":     swing,
        "long_term": lt,
        "scan_date": rows[0]["scan_date"] if rows else None,
        "count":     len(rows),
    })


@scanner_bp.route("/api/scan/progress")
def scan_progress():
    return jsonify(_scan_progress)


@scanner_bp.route("/api/market/regime")
def market_regime():
    from utils.unusual_whales import get_market_regime
    try:
        regime = get_market_regime()
    except Exception as e:
        regime = {"regime": "NEUTRAL", "summary": "Unavailable", "advice": "Trade normal sizing",
                  "available": False, "color": "yellow"}
    return jsonify(regime)


@scanner_bp.route("/api/scan/run", methods=["POST"])
def trigger_scan():
    global _scan_running
    if _scan_running:
        return jsonify({"error": "Scan already running"}), 409
    thread = threading.Thread(target=run_scan_job, daemon=True)
    thread.start()
    return jsonify({"message": "Scan started"})


def _get_uw_screener_tickers():
    """Pull extra tickers from UW screener + movers."""
    from utils.unusual_whales import uw_screener, uw_movers
    extra = set()
    try:
        screener_data = uw_screener({
            "order": "volume", "order_direction": "desc", "limit": 30
        })
        if screener_data:
            items = screener_data.get("data", [])
            for item in items:
                t = str(item.get("ticker", item.get("symbol", ""))).upper()
                if t and t.isalpha() and len(t) <= 5:
                    extra.add(t)
    except Exception:
        pass
    try:
        movers_data = uw_movers()
        if movers_data:
            items = movers_data.get("data", movers_data if isinstance(movers_data, list) else [])
            for item in (items or [])[:20]:
                t = str(item.get("ticker", item.get("symbol", ""))).upper()
                if t and t.isalpha() and len(t) <= 5:
                    extra.add(t)
    except Exception:
        pass
    return list(extra)


def _get_analyst_rating(ticker):
    """Pull analyst consensus rating for ticker."""
    from utils.unusual_whales import uw_analysts
    try:
        data = uw_analysts(ticker)
        if not data:
            return None
        items = data.get("data", [])
        if not items:
            return None
        item = items[0] if isinstance(items, list) else data
        rating = item.get("consensus", item.get("rating", item.get("analyst_consensus", "")))
        target = item.get("price_target", item.get("mean_target", ""))
        if rating:
            return {"rating": str(rating), "target": target}
    except Exception:
        pass
    return None


def run_scan_job():
    """Full 6-layer scan with UW screener. Called by scheduler and manual trigger."""
    global _scan_running, _scan_progress
    _scan_running = True
    _scan_progress = {"status": "running", "done": 0, "total": 0, "phase": "Loading tickers"}

    try:
        settings = get_settings()
        account  = settings.get("account_size", 20000)
        risk     = settings.get("swing_risk", 2.0)
        lt_pos   = settings.get("lt_position", 7.5)

        _scan_progress["phase"] = "Fetching UW screener + movers"
        uw_extra = _get_uw_screener_tickers()

        universe = get_scan_universe(extra_watchlist=uw_extra)
        _scan_progress["total"] = len(universe)
        _scan_progress["phase"] = "Quick scan (layers 1-4)"

        # Phase 1: quick 4-layer scan
        quick_results = []
        uw_extra_set  = set(uw_extra)
        for i, ticker in enumerate(universe):
            try:
                q = quick_score(ticker)
                # UW screener results get a small boost in priority
                if ticker in uw_extra_set:
                    q["uw_screener"] = True
                    q["score4"] = min(q.get("score4", 0) + 5, 100)
                quick_results.append(q)
                time.sleep(0.05)
            except Exception:
                pass
            _scan_progress["done"] = i + 1

        # Keep top 40 (UW screener + movers always included if 4-layer >=45)
        candidates = [r for r in quick_results if r.get("score4", 0) >= 55
                      or (r.get("uw_screener") and r.get("score4", 0) >= 45)]
        candidates.sort(key=lambda x: x.get("score4", 0), reverse=True)
        candidates = candidates[:40]

        _scan_progress["phase"] = f"Deep scan on {len(candidates)} candidates"
        _scan_progress["done"]  = 0
        _scan_progress["total"] = len(candidates)

        # Phase 2: full 6-layer + UW
        final_results = []
        for i, cand in enumerate(candidates):
            ticker = cand["ticker"]
            try:
                full   = run_full_analysis(ticker, "SWING")
                score  = full["score"]
                price  = full["price"]
                layers = full["layers"]
                fund   = full.get("fundamentals", {})

                trend_score = layers["trend"]["score"]
                rev_growth  = fund.get("revenue_growth") or 0
                is_lt = (trend_score >= 18 and rev_growth >= 0.15 and score >= 65)
                mode_tag = "LONG-TERM" if is_lt else "SWING"

                atr = full["technicals"].get("atr")
                if mode_tag == "SWING":
                    ps = calc_swing_setup(price, atr, account, risk)
                else:
                    ps = calc_lt_setup(price, atr, account, lt_pos)

                uw = layers["smart_money"]
                # Analyst rating (best-effort, non-blocking)
                analyst = None
                try:
                    analyst = _get_analyst_rating(ticker)
                except Exception:
                    pass

                # UW screener flag: 6-layer >=70 + from screener = highest priority
                from_uw_screener = cand.get("uw_screener", False)
                priority = "HIGH" if (from_uw_screener and score >= 70) else "NORMAL"

                final_results.append({
                    "ticker":       ticker,
                    "score":        score,
                    "verdict":      full["verdict"],
                    "mode_tag":     mode_tag,
                    "price":        price,
                    "rsi":          full["technicals"].get("rsi"),
                    "ema20":        full["technicals"].get("ema20"),
                    "stop":         ps.get("stop"),
                    "target":       ps.get("target"),
                    "shares":       ps.get("shares", 0),
                    "uw_notes":     uw.get("notes", []),
                    "uw_score":     uw.get("score", 0),
                    "analyst":      analyst,
                    "uw_screener":  from_uw_screener,
                    "priority":     priority,
                    "layers":       {
                        "trend":     layers["trend"]["score"],
                        "momentum":  layers["momentum"]["score"],
                        "volume":    layers["volume"]["score"],
                        "structure": layers["structure"]["score"],
                        "catalyst":  layers["catalyst"]["score"],
                        "sm":        uw.get("score", 0),
                    }
                })
            except Exception as e:
                print(f"Scan error {ticker}: {e}")

            _scan_progress["done"] = i + 1
            time.sleep(0.2)

        final_results.sort(key=lambda x: x["score"], reverse=True)
        save_scan_results(final_results)

        _scan_progress = {
            "status": "done",
            "done": len(final_results),
            "total": len(final_results),
            "phase": "Complete"
        }

        try:
            from utils.emailer import send_daily_brief
            swing_r = [r for r in final_results if r["mode_tag"] == "SWING" and r["score"] >= 70]
            lt_r    = [r for r in final_results if r["mode_tag"] == "LONG-TERM" and r["score"] >= 65]
            send_daily_brief(swing_r[:5], lt_r[:3], settings)
        except Exception as e:
            print(f"Email error: {e}")

    except Exception as e:
        _scan_progress = {"status": "error", "error": str(e), "phase": "Failed"}
        print(f"Scan job error: {e}")
    finally:
        _scan_running = False
