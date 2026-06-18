"""Tab 1: Scanner — daily 6-layer scan + manual trigger."""

import time
import threading
from flask import Blueprint, jsonify, render_template
from models.journal import get_latest_scan, save_scan_results, get_settings
from utils.tickers import get_scan_universe
from utils.analysis_engine import (
    run_full_analysis,
    _ema, _rsi, layer1_trend, layer2_momentum, layer4_structure,
)
from utils.position_calc import calc_swing_setup, calc_lt_setup

scanner_bp = Blueprint("scanner", __name__)

_scan_running = False
_scan_progress = {"status": "idle", "done": 0, "total": 0, "phase": ""}


@scanner_bp.route("/scan")
def scan_page():
    return render_template("scanner.html")


@scanner_bp.route("/api/scan/results")
def scan_results():
    rows = get_latest_scan()
    swing = [r for r in rows if r.get("mode_tag") == "SWING"]
    lt = [r for r in rows if r.get("mode_tag") == "LONG-TERM"]
    return jsonify({
        "swing": swing,
        "long_term": lt,
        "scan_date": rows[0]["scan_date"] if rows else None,
        "generated_at": rows[0].get("generated_at") if rows else None,
        "count": len(rows),
    })


@scanner_bp.route("/api/scan/freshness")
def freshness_prices():
    """Current prices for per-candidate freshness drift check."""
    import yfinance as yf
    from flask import request
    tickers = [t.strip().upper()
               for t in request.args.get("tickers", "").split(",")
               if t.strip()][:30]
    prices = {t: None for t in tickers}
    if tickers:
        try:
            raw = yf.download(tickers, period="2d", auto_adjust=True,
                              progress=False, threads=True)
            if not raw.empty:
                close = raw["Close"]
                if len(tickers) == 1:
                    prices[tickers[0]] = round(float(close.dropna().iloc[-1]), 2)
                else:
                    for t in tickers:
                        try:
                            prices[t] = round(float(close[t].dropna().iloc[-1]), 2)
                        except Exception:
                            pass
        except Exception:
            pass
    return jsonify({"prices": prices})


@scanner_bp.route("/api/scan/progress")
def scan_progress():
    return jsonify(_scan_progress)


@scanner_bp.route("/api/scan/sector-flow")
def sector_flow():
    from utils.unusual_whales import get_sector_flow
    try:
        sectors = get_sector_flow()
    except Exception:
        sectors = []
    return jsonify({"sectors": sectors})


@scanner_bp.route("/api/scan/top-flow")
def top_flow():
    from utils.unusual_whales import get_top_flow
    try:
        names = get_top_flow(limit=15)
    except Exception:
        names = []
    return jsonify({"names": names})


@scanner_bp.route("/api/market/regime")
def market_regime():
    from utils.unusual_whales import get_market_regime
    try:
        regime = get_market_regime()
    except Exception:
        regime = {"regime": "NEUTRAL", "summary": "Unavailable", "advice": "Trade normal sizing",
                  "available": False, "color": "yellow"}
    return jsonify(regime)


@scanner_bp.route("/api/scan/run", methods=["POST"])
def trigger_scan():
    if _scan_running:
        return jsonify({"error": "Scan already running"}), 409
    thread = threading.Thread(target=run_scan_job, daemon=True)
    thread.start()
    return jsonify({"message": "Scan started"})


def _get_uw_screener_tickers():
    """Pull extra tickers from UW screener."""
    from utils.unusual_whales import uw_screener
    extra = set()
    try:
        data = uw_screener({"order": "volume", "order_direction": "desc", "limit": 30})
        if data:
            for item in data.get("data", []):
                t = str(item.get("ticker", item.get("symbol", ""))).upper()
                if t and t.isalpha() and len(t) <= 5:
                    extra.add(t)
    except Exception:
        pass
    return list(extra)


def _get_analyst_rating(ticker):
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


def _batch_quick_scan(universe):
    """
    Download 1y of daily candles for the full universe in batched yfinance
    calls then compute 4-layer quick scores.
    """
    import yfinance as yf
    import concurrent.futures

    all_data = {}
    batch_size = 50          # smaller batches are less likely to time out
    batches = [universe[i:i + batch_size] for i in range(0, len(universe), batch_size)]
    done_count = 0

    for batch in batches:
        raw = None
        try:
            # 60s hard timeout per batch — yf.download has no built-in timeout
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
                future = ex.submit(
                    yf.download, batch,
                    period="1y", auto_adjust=True, progress=False, threads=False,
                )
                try:
                    raw = future.result(timeout=60)
                except concurrent.futures.TimeoutError:
                    print(f"[SCANNER] Batch timeout ({len(batch)} tickers) — skipping")
        except Exception as e:
            print(f"[SCANNER] Batch download error: {e}")

        if raw is not None and not raw.empty:
            multi = len(batch) > 1
            for ticker in batch:
                try:
                    if multi:
                        closes = raw["Close"][ticker].dropna().tolist()
                        volumes = raw["Volume"][ticker].dropna().tolist()
                    else:
                        closes = raw["Close"].dropna().tolist()
                        volumes = raw["Volume"].dropna().tolist()
                    if len(closes) >= 20:
                        all_data[ticker] = {"closes": closes, "volumes": volumes}
                except Exception:
                    pass

        done_count += len(batch)
        _scan_progress["done"] = done_count

    results = []
    for ticker in universe:
        try:
            d = all_data.get(ticker, {})
            closes = d.get("closes", [])
            volumes = d.get("volumes", [])
            if len(closes) < 20:
                continue

            price = round(float(closes[-1]), 2)
            if price <= 0:
                continue   # no valid price data for this ticker
            vol_today = float(volumes[-1]) if volumes else 0

            ema20 = _ema(closes, 20) if len(closes) >= 20 else None
            ema50 = _ema(closes, 50) if len(closes) >= 50 else None
            ema200 = _ema(closes, 200) if len(closes) >= 200 else None
            rsi = _rsi(closes, 14) if len(closes) >= 15 else None

            l1 = layer1_trend(price, ema20, ema50, ema200)
            l2 = layer2_momentum(rsi)
            l4 = layer4_structure(price, ema20)

            avg20 = sum(volumes[-21:-1]) / 20 if len(volumes) >= 21 else 0
            ratio = vol_today / avg20 if avg20 > 0 else 0
            l3_score = 20 if ratio >= 2 else 15 if ratio >= 1.5 else 10 if ratio >= 1 else 5

            partial = l1["score"] + l2["score"] + l3_score + l4["score"]
            score4 = round(partial / 90 * 100)

            results.append({
                "ticker": ticker,
                "price": price,
                "score4": score4,
                "rsi": round(rsi, 1) if rsi else None,
                "ema20": ema20,
                "l1": l1["score"], "l2": l2["score"],
                "l3": l3_score, "l4": l4["score"],
            })
        except Exception:
            pass

    return results


def run_scan_job():
    """Full 6-layer scan. Phase 1: batch yfinance quick score. Phase 2: deep UW analysis."""
    global _scan_running, _scan_progress
    _scan_running = True
    _scan_progress = {"status": "running", "done": 0, "total": 0, "phase": "Loading tickers"}

    try:
        settings = get_settings()
        account = settings.get("account_size", 20000)
        risk = settings.get("swing_risk", 2.0)
        lt_pos = settings.get("lt_position", 7.5)

        # ── Startup self-test ──────────────────────────────────────────────────
        _scan_progress["phase"] = "Self-test"
        _scan_progress["warnings"] = []

        from utils.tickers import _get_live_universe, _FALLBACK
        live = _get_live_universe()
        if live:
            _scan_progress["universe_source"] = f"UW live holdings ({len(live)} tickers)"
        else:
            msg = "WARNING: UW ETF holdings unavailable — using static fallback list"
            _scan_progress["warnings"].append(msg)
            _scan_progress["universe_source"] = f"static fallback ({len(_FALLBACK)} tickers)"
            print(f"[SCANNER] {msg}")

        import concurrent.futures as _cf
        from utils.prices import get_live_price
        try:
            spy_check = _cf.ThreadPoolExecutor(max_workers=1).submit(
                get_live_price, "SPY").result(timeout=15)
        except Exception:
            spy_check = {}
        spy_px = spy_check.get("price", 0)
        if spy_px <= 0:
            msg = "CRITICAL: SPY price returned $0 — Yahoo Finance feed may be down"
            _scan_progress["warnings"].append(msg)
            print(f"[SCANNER] {msg}")
        elif spy_px < 100 or spy_px > 10_000:
            msg = f"WARNING: SPY price ${spy_px} looks implausible — verify data feed"
            _scan_progress["warnings"].append(msg)
            print(f"[SCANNER] {msg}")
        else:
            print(f"[SCANNER] Self-test: SPY ${spy_px} OK, universe {_scan_progress['universe_source']}")

        # ── Build universe ────────────────────────────────────────────────────
        _scan_progress["phase"] = "Fetching UW screener"
        uw_extra = _get_uw_screener_tickers()
        uw_extra_set = set(uw_extra)

        universe_mode = settings.get("universe_mode", "full")
        custom_raw = settings.get("custom_watchlist", "")
        custom_tickers = [t.strip().upper() for t in custom_raw.split(",") if t.strip()] if custom_raw else []
        if custom_tickers:
            print(f"[SCANNER] Custom watchlist: {custom_tickers}")

        universe = get_scan_universe(universe_mode=universe_mode, extra_watchlist=uw_extra + custom_tickers)

        if not universe:
            msg = "CRITICAL: Empty scan universe — check ticker source"
            _scan_progress["warnings"].append(msg)
            print(f"[SCANNER] {msg}")

        _scan_progress["total"] = len(universe)
        print(f"[SCANNER] Universe: {_scan_progress['universe_source']} + {len(uw_extra)} UW extras + {len(custom_tickers)} custom = {len(universe)} total")

        # ── Phase 1: batch download + quick 4-layer score ─────────────────────
        _scan_progress["phase"] = f"Batch downloading {len(universe)} tickers (yfinance)..."
        quick_results = _batch_quick_scan(universe)
        _scan_progress["done"] = len(universe)

        for q in quick_results:
            if q["ticker"] in uw_extra_set:
                q["uw_screener"] = True
                q["score4"] = min(q.get("score4", 0) + 5, 100)

        candidates = [r for r in quick_results
                      if r.get("score4", 0) >= 55
                      or (r.get("uw_screener") and r.get("score4", 0) >= 45)]
        candidates.sort(key=lambda x: x.get("score4", 0), reverse=True)
        candidates = candidates[:25]   # cap at 25 for deep scan timing

        # ── Phase 2: full 6-layer deep scan ───────────────────────────────────
        _scan_progress["phase"] = f"Deep scan on {len(candidates)} candidates"
        _scan_progress["done"] = 0
        _scan_progress["total"] = len(candidates)

        from utils.unusual_whales import pre_burst_check
        throttle = pre_burst_check(n_calls=len(candidates) * 2)
        if throttle["throttled"]:
            print(f"[SCANNER] Throttled {throttle['slept']:.0f}s before deep scan")

        final_results = []
        for i, cand in enumerate(candidates):
            ticker = cand["ticker"]
            try:
                full = run_full_analysis(ticker, "SWING")
                score = full["score"]
                price = full["price"]
                layers = full["layers"]
                fund = full.get("fundamentals", {})

                trend_score = layers["trend"]["score"]
                rev_growth = fund.get("revenue_growth") or 0
                is_lt = (trend_score >= 18 and rev_growth >= 0.15 and score >= 65)
                mode_tag = "LONG-TERM" if is_lt else "SWING"

                atr = full["technicals"].get("atr")
                planned = full.get("planned_entry", {})
                planned_entry = planned.get("entry", price)

                if mode_tag == "SWING":
                    ps = calc_swing_setup(planned_entry, atr, account, risk)
                else:
                    ps = calc_lt_setup(planned_entry, atr, account, lt_pos)

                uw = layers["smart_money"]
                analyst = None
                try:
                    analyst = _get_analyst_rating(ticker)
                except Exception:
                    pass

                from_uw = cand.get("uw_screener", False)
                priority = "HIGH" if (from_uw and score >= 70) else "NORMAL"

                final_results.append({
                    "ticker": ticker,
                    "score": score,
                    "verdict": full["verdict"],
                    "mode_tag": mode_tag,
                    "price": price,
                    "rsi": full["technicals"].get("rsi"),
                    "ema20": full["technicals"].get("ema20"),
                    "stop": ps.get("stop"),
                    "target": ps.get("target"),
                    "shares": ps.get("shares", 0),
                    "uw_notes": uw.get("notes", []),
                    "uw_score": uw.get("score", 0),
                    "analyst": analyst,
                    "uw_screener": from_uw,
                    "priority": priority,
                    "layers": {
                        "trend": layers["trend"]["score"],
                        "momentum": layers["momentum"]["score"],
                        "volume": layers["volume"]["score"],
                        "structure": layers["structure"]["score"],
                        "catalyst": layers["catalyst"]["score"],
                        "sm": uw.get("score", 0),
                    },
                })
            except Exception as e:
                print(f"Scan error {ticker}: {e}")

            _scan_progress["done"] = i + 1
            time.sleep(0.1)   # light spacing for UW rate limit

        final_results.sort(key=lambda x: x["score"], reverse=True)
        save_scan_results(final_results)

        _scan_progress = {
            "status": "done",
            "done": len(final_results),
            "total": len(final_results),
            "phase": "Complete",
        }

        try:
            from utils.emailer import send_daily_brief
            swing_r = [r for r in final_results if r["mode_tag"] == "SWING" and r["score"] >= 70]
            lt_r = [r for r in final_results if r["mode_tag"] == "LONG-TERM" and r["score"] >= 65]
            send_daily_brief(swing_r[:5], lt_r[:3], settings)
        except Exception as e:
            print(f"Email error: {e}")

    except Exception as e:
        _scan_progress = {
            "status": "error",
            "error": str(e),
            "phase": f"Failed: {str(e)[:120]}",
        }
        print(f"Scan job error: {e}")
    finally:
        _scan_running = False
        from utils.unusual_whales import set_scanner_priority
        set_scanner_priority(False)
