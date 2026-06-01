"""Unusual Whales API client — full smart money coverage."""

import os
import time
import requests

UW_KEY  = os.environ.get("UW_API_KEY", "")
BASE    = "https://api.unusualwhales.com"

_cache = {}
CACHE_TTL = 300  # 5 min


def _headers():
    # Re-read at call time so hot env reloads work
    key = os.environ.get("UW_API_KEY", UW_KEY)
    return {"Authorization": f"Bearer {key}"}


def _get(endpoint, params=None, ttl=CACHE_TTL):
    key = f"{endpoint}:{str(params)}"
    now = time.time()
    if key in _cache and now - _cache[key]["ts"] < ttl:
        return _cache[key]["data"]
    uw_key = os.environ.get("UW_API_KEY", UW_KEY)
    if not uw_key:
        return None
    try:
        r = requests.get(f"{BASE}{endpoint}", params=params,
                         headers=_headers(), timeout=10)
        if not r.ok:
            return None
        data = r.json()
        _cache[key] = {"data": data, "ts": now}
        return data
    except Exception:
        return None


# ─── Public fetch functions ───────────────────────────────────────────────────

def uw_flow_alerts(ticker):
    """Global flow alerts filtered by ticker."""
    return _get("/api/option-trades/flow-alerts", {"ticker": ticker, "limit": 25})


def uw_ticker_flow(ticker):
    """Ticker-specific flow alerts."""
    return _get(f"/api/stock/{ticker}/flow-alerts", {"limit": 25})


def uw_darkpool(ticker):
    """Dark pool prints for ticker."""
    result = _get(f"/api/darkpool/{ticker}", {"limit": 15})
    if result is None:
        result = _get("/api/darkpool/recent", {"ticker": ticker, "limit": 15})
    return result


def uw_insider(ticker):
    """Insider transactions."""
    return _get(f"/api/insider/{ticker}", {"limit": 15})


def uw_insider_summary(ticker):
    """Insider buy/sell summary."""
    return _get(f"/api/stock/{ticker}/insider-buy-sells")


def uw_congress(ticker):
    """Congress recent trades for ticker."""
    return _get("/api/congress/recent-trades", {"ticker": ticker, "limit": 10})


def uw_congress_unusual(ticker):
    """Unusual congress activity."""
    return _get("/api/congress/unusual-trades", {"ticker": ticker, "limit": 5})


def uw_shorts(ticker):
    """Short interest data."""
    return _get(f"/api/shorts/{ticker}/data")


def uw_screener(params=None):
    """Stock screener — quality momentum names."""
    return _get("/api/screener/stocks", params or {}, ttl=900)


def uw_analysts(ticker):
    """Analyst ratings."""
    return _get("/api/screener/analysts", {"ticker": ticker})


def uw_movers():
    """Top market movers."""
    return _get("/api/market/movers", ttl=120)


def uw_market_tide():
    """Overall market sentiment/tide."""
    return _get("/api/market/market-tide", ttl=300)


def uw_earnings_premarket():
    """Today's premarket earnings."""
    return _get("/api/earnings/premarket", ttl=3600)


def uw_earnings_afterhours():
    """Today's afterhours earnings."""
    return _get("/api/earnings/afterhours", ttl=3600)


def uw_earnings_estimates(ticker):
    """Earnings estimates for ticker."""
    return _get(f"/api/companies/{ticker}/earnings-estimates")


def uw_ticker_earnings(ticker):
    """Full earnings history + upcoming for ticker — /api/stock/{ticker}/earnings."""
    return _get(f"/api/stock/{ticker}/earnings", ttl=3600)


def uw_seasonality(ticker):
    """Monthly seasonality for ticker."""
    return _get(f"/api/seasonality/{ticker}/monthly", ttl=86400)


def uw_news_headlines():
    """Live news headlines."""
    return _get("/api/news/headlines", ttl=120)


# ─── Smart Money Score (Layer 6) — upgraded ──────────────────────────────────

def smart_money_score(ticker):
    """
    Returns {score: 0-20, notes: [...], signals: [...], available: bool}.
    Scoring:
      Large bullish call sweep at ask: +8
      Dark pool print >$1M above price: +5
      Insider buy >$100k last 30d: +4
      Congress/politician buy recent: +3
      Note: short squeeze potential (no score)
    """
    uw_key = os.environ.get("UW_API_KEY", UW_KEY)
    if not uw_key:
        return {"score": 0, "notes": [], "signals": [], "available": False,
                "detail": "UW_API_KEY not configured"}

    score   = 0
    notes   = []
    signals = []  # detailed signals for display
    raw     = {}

    # ─── Options flow (try ticker-specific first, then global) ───────────────
    flow_data = uw_ticker_flow(ticker) or uw_flow_alerts(ticker)
    if flow_data:
        items = flow_data.get("data", flow_data if isinstance(flow_data, list) else [])
        bullish_sweeps = []
        for item in items[:25]:
            put_call  = str(item.get("put_call", item.get("type", ""))).lower()
            premium   = _sf(item.get("premium") or item.get("size") or item.get("total_premium", 0))
            sentiment = str(item.get("sentiment", "")).lower()
            execution = str(item.get("execution_estimate", "")).lower()
            strike    = item.get("strike", item.get("strike_price", "?"))
            expiry    = item.get("expiry", item.get("expiration_date", ""))

            is_call    = "call" in put_call
            is_bullish = "bullish" in sentiment or "bull" in sentiment
            at_ask     = "ask" in execution or "above" in execution

            if (is_call or is_bullish) and premium >= 500_000:
                bullish_sweeps.append({
                    "premium": premium,
                    "strike": strike,
                    "expiry": expiry,
                    "at_ask": at_ask,
                })

        if bullish_sweeps:
            total = sum(s["premium"] for s in bullish_sweeps)
            best  = max(bullish_sweeps, key=lambda x: x["premium"])
            score += 8
            note = f"${total/1e6:.1f}M bullish call sweep"
            if best.get("strike"):
                note += f" (${best['strike']} strike)"
            notes.append(note)
            signals.append({
                "type": "FLOW",
                "icon": "🔥",
                "text": note,
                "detail": f"Largest: ${best['premium']/1e6:.1f}M · Strike ${best['strike']} · Expiry {best['expiry']}",
                "bullish": True,
            })
            raw["flow"] = bullish_sweeps

    # ─── Dark pool ────────────────────────────────────────────────────────────
    dp_data = uw_darkpool(ticker)
    if dp_data:
        items = dp_data.get("data", dp_data if isinstance(dp_data, list) else [])
        big_prints = []
        for item in items[:15]:
            size     = _sf(item.get("size") or item.get("notional_value") or item.get("premium", 0))
            dp_price = _sf(item.get("price", 0))
            if size >= 1_000_000:
                big_prints.append({"size": size, "price": dp_price})

        if big_prints:
            total = sum(p["size"] for p in big_prints)
            score += 5
            note = f"${total/1e6:.0f}M dark pool print"
            notes.append(note)
            biggest = max(big_prints, key=lambda x: x["size"])
            signals.append({
                "type": "DARKPOOL",
                "icon": "🌊",
                "text": note,
                "detail": f"Largest: ${biggest['size']/1e6:.1f}M @ ${biggest['price']:.2f}",
                "bullish": True,
            })
            raw["darkpool"] = big_prints

    # ─── Insider transactions ─────────────────────────────────────────────────
    ins_data = uw_insider(ticker)
    if ins_data:
        items = ins_data.get("data", ins_data if isinstance(ins_data, list) else [])
        insider_buys = []
        cutoff = time.time() - 30 * 86400  # last 30 days
        for item in items[:15]:
            tx_type  = str(item.get("transaction_type", item.get("type", ""))).lower()
            value    = _sf(item.get("value") or item.get("shares_value") or item.get("total_value", 0))
            who      = item.get("insider_name", item.get("name", "Insider"))
            role     = item.get("title", item.get("insider_title", ""))
            date_str = item.get("filing_date", item.get("date", ""))

            if ("buy" in tx_type or "purchase" in tx_type) and value >= 100_000:
                insider_buys.append({"value": value, "who": who, "role": role, "date": date_str})

        if insider_buys:
            score += 4
            biggest = max(insider_buys, key=lambda x: x["value"])
            note = f"{biggest['who']} bought ${biggest['value']/1e6:.1f}M"
            if biggest["role"]:
                note += f" ({biggest['role']})"
            notes.append(note)
            signals.append({
                "type": "INSIDER",
                "icon": "👔",
                "text": note,
                "detail": f"Filed: {biggest['date']} · {len(insider_buys)} insider buy(s)",
                "bullish": True,
            })
            raw["insider"] = insider_buys

    # ─── Congress trades ──────────────────────────────────────────────────────
    cong_data = uw_congress(ticker) or uw_congress_unusual(ticker)
    if cong_data:
        items = cong_data.get("data", cong_data if isinstance(cong_data, list) else [])
        buys = [
            i for i in items[:10]
            if "buy" in str(i.get("transaction_type", "")).lower()
            or "purchase" in str(i.get("transaction_type", "")).lower()
        ]
        if buys:
            score += 3
            name = buys[0].get("politician_name", buys[0].get("name", "Congress"))
            party = buys[0].get("party", "")
            note = f"Congress buy: {name}" + (f" ({party})" if party else "")
            notes.append(note)
            signals.append({
                "type": "CONGRESS",
                "icon": "🏛",
                "text": note,
                "detail": f"{len(buys)} congressional purchase(s)",
                "bullish": True,
            })
            raw["congress"] = buys

    # ─── Short interest (note only, no score) ────────────────────────────────
    short_data = uw_shorts(ticker)
    if short_data:
        sdata = short_data.get("data", {})
        if isinstance(sdata, list) and sdata:
            sdata = sdata[0]
        short_float = _sf(sdata.get("short_float_pct", sdata.get("short_percent_of_float", 0)))
        if short_float > 20:
            note = f"High short interest {short_float:.1f}% float — squeeze potential"
            notes.append(note)
            signals.append({
                "type": "SHORT",
                "icon": "⚡",
                "text": note,
                "detail": f"Short float: {short_float:.1f}%",
                "bullish": None,  # context, not directional
            })
            raw["shorts"] = short_float

    return {
        "score":     min(score, 20),
        "notes":     notes,
        "signals":   signals,
        "available": True,
        "raw":       raw,
    }


def get_market_regime():
    """Return {regime: 'BULLISH'|'NEUTRAL'|'BEARISH', summary, advice}."""
    tide_data = uw_market_tide()
    movers    = uw_movers()

    if not tide_data:
        return {"regime": "NEUTRAL", "summary": "UW market data unavailable",
                "advice": "Trade normal position sizing", "available": False}

    data = tide_data.get("data", tide_data if isinstance(tide_data, dict) else {})
    if isinstance(data, list) and data:
        data = data[0]

    bull_score = _sf(data.get("bullish_premium") or data.get("call_premium", 0))
    bear_score = _sf(data.get("bearish_premium") or data.get("put_premium", 0))
    net_gamma  = _sf(data.get("net_gamma", 0))
    sentiment  = str(data.get("sentiment", data.get("market_sentiment", ""))).lower()

    # Determine regime
    if "bullish" in sentiment or bull_score > bear_score * 1.3 or net_gamma > 0:
        regime = "BULLISH"
        summary = "Market tide is bullish — options flow favors upside"
        advice  = "Risk-on: normal position sizing, setups more reliable"
        color   = "green"
    elif "bearish" in sentiment or bear_score > bull_score * 1.3 or net_gamma < 0:
        regime = "BEARISH"
        summary = "Market tide is bearish — defensive positioning"
        advice  = "Risk-off: reduce size 50%, only trade 85+ scores"
        color   = "red"
    else:
        regime = "NEUTRAL"
        summary = "Market tide is neutral — mixed signals"
        advice  = "Be selective: only high-conviction setups (80+)"
        color   = "yellow"

    return {
        "regime":    regime,
        "summary":   summary,
        "advice":    advice,
        "color":     color,
        "available": True,
        "raw":       data,
    }


def get_earnings_warning(ticker):
    """Check if earnings within 14 days — returns warning string or None."""
    import datetime
    today  = datetime.date.today()
    window = 14  # warn 14 days in advance

    # Primary: per-ticker earnings calendar (has future dates)
    data = uw_ticker_earnings(ticker)
    if data:
        items = data.get("data", data if isinstance(data, list) else [])
        for item in items:
            # Only upcoming (unreported) earnings
            if item.get("reported_eps") is not None:
                continue
            date_str = item.get("report_date", "")
            if not date_str:
                continue
            try:
                earn_date = datetime.date.fromisoformat(date_str[:10])
                days_away = (earn_date - today).days
                if -1 <= days_away <= window:
                    timing = item.get("report_time") or "TBC"
                    timing = timing.replace("postmarket", "AMC").replace("premarket", "BMO")
                    if days_away <= 0:
                        when = "TODAY" if days_away == 0 else "YESTERDAY"
                    elif days_away == 1:
                        when = "TOMORROW"
                    else:
                        when = f"in {days_away}d ({earn_date.strftime('%b %d')})"
                    est_eps = item.get("estimated_eps")
                    eps_str = f" — est. EPS ${est_eps}" if est_eps else ""
                    return (
                        f"⚠ EARNINGS {when} ({timing}){eps_str} — "
                        f"wait for reaction, don't enter before"
                    )
            except Exception:
                pass

    # Fallback: today's premarket / afterhours lists
    for fetch_fn in [uw_earnings_premarket, uw_earnings_afterhours]:
        data = fetch_fn()
        if not data:
            continue
        items = data.get("data", data if isinstance(data, list) else [])
        for item in items:
            t = str(item.get("ticker", item.get("symbol", ""))).upper()
            if t != ticker.upper():
                continue
            date_str = item.get("report_date", item.get("date", ""))
            try:
                earn_date = datetime.date.fromisoformat(date_str[:10])
                days_away = (earn_date - today).days
                if -1 <= days_away <= window:
                    timing = item.get("report_time", item.get("time", "TBC"))
                    when   = "TODAY" if days_away == 0 else f"in {days_away}d"
                    return f"⚠ EARNINGS {when} ({timing}) — wait for reaction, don't enter before"
            except Exception:
                pass

    return None


def get_seasonality_note(ticker):
    """Return monthly seasonality note for ticker, or None."""
    import datetime
    data = uw_seasonality(ticker)
    if not data:
        return None
    items = data.get("data", data if isinstance(data, list) else [])
    current_month = datetime.date.today().month
    month_names = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
    for item in items:
        m = item.get("month", item.get("month_number", 0))
        try:
            m = int(m)
        except Exception:
            continue
        if m == current_month:
            avg_ret = _sf(item.get("avg_return", item.get("average_return", 0)))
            win_pct = _sf(item.get("win_rate", item.get("positive_rate", 0)))
            month_name = month_names[current_month - 1]
            if avg_ret > 0.01:
                return f"{ticker} historically +{avg_ret*100:.1f}% in {month_name} ({win_pct*100:.0f}% win rate)"
            elif avg_ret < -0.01:
                return f"{ticker} historically {avg_ret*100:.1f}% in {month_name} ({win_pct*100:.0f}% win rate) — seasonally weak"
    return None


def _sf(val):
    try:
        return float(val or 0)
    except (TypeError, ValueError):
        return 0.0
