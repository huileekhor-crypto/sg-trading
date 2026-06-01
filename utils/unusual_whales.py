"""Unusual Whales API client — full smart money coverage."""

import os
import time
import requests

UW_KEY = os.environ.get("UW_API_KEY", "")
BASE = "https://api.unusualwhales.com"

_cache = {}
CACHE_TTL = 300  # 5 min


def _headers():
    # Re-read at call time so hot env reloads work
    key = os.environ.get("UW_API_KEY", UW_KEY)
    return {
        "Authorization": f"Bearer {key}",
        "UW-CLIENT-API-ID": "100001",
    }


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


_BREAKOUT_PRESETS = {
    'aggressive': {
        'min_bullish_perc': '0.50',
        'min_net_call_premium': '50000',
        'limit': 40,
    },
    'balanced': {
        'min_bullish_perc': '0.55',
        'min_net_call_premium': '100000',
        'limit': 30,
    },
    'conservative': {
        'min_bullish_perc': '0.65',
        'min_net_call_premium': '300000',
        'limit': 20,
    },
}


def uw_breakout_screener(preset='balanced'):
    """
    UW screener tuned for weekly breakout setups.
    Filters by bullish options flow + net call premium.
    Returns list of enriched ticker dicts.
    """
    base = _BREAKOUT_PRESETS.get(preset, _BREAKOUT_PRESETS['balanced'])
    params = {
        **base,
        'issue_types': ['Common Stock'],
        'order': 'net_call_premium',
        'order_direction': 'desc',
    }
    data = uw_screener(params)
    if not data:
        return []

    results = []
    for item in data.get('data', []):
        ticker = str(item.get('ticker', '')).upper()
        if not ticker or any(c.isdigit() for c in ticker) or ticker in _FLOW_EXCLUDE:
            continue

        bull_prem = _sf(item.get('bullish_premium', 0))
        bear_prem = _sf(item.get('bearish_premium', 0))
        total_prem = bull_prem + bear_prem
        bull_pct = round(bull_prem / total_prem * 100, 1) if total_prem else 50.0

        net_call = _sf(item.get('net_call_premium', 0))
        call_vol = _sf(item.get('call_volume', 0))
        put_vol = _sf(item.get('put_volume', 0))
        avg30_call = _sf(item.get('avg_30_day_call_volume', item.get('avg30_call_volume', 1)))
        call_vs30 = round(call_vol / avg30_call, 2) if avg30_call else 1.0

        results.append({
            'ticker': ticker,
            'bullish_pct': bull_pct,
            'net_call_premium': net_call,
            'call_volume': int(call_vol),
            'put_volume': int(put_vol),
            'call_vs30': call_vs30,
            'iv_rank': round(_sf(item.get('iv_rank', 0)), 1),
            'sector': item.get('sector', '') or '',
            'perc_change': round(_sf(item.get('perc_change', 0)), 2),
        })

    return results


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


def uw_gex(ticker):
    """Greek exposure by expiry date — /api/stock/{ticker}/greek-exposure."""
    return _get(f"/api/stock/{ticker}/greek-exposure", ttl=300)


def uw_sector_etfs():
    """All 11 SPDR sector ETFs with options flow and money-flow data."""
    return _get("/api/market/sector-etfs", ttl=300)


def get_sector_flow():
    """
    Process sector ETF data into scored, ranked sector flow summary.
    Returns list of dicts sorted by bullishness descending.
    """
    data = uw_sector_etfs()
    if not data:
        return []

    # ETF → readable sector name map (override UW's full_name where needed)
    etf_names = {
        "XLK": "Technology", "XLF": "Financials", "XLV": "Healthcare",
        "XLE": "Energy", "XLI": "Industrials", "XLB": "Materials",
        "XLP": "Cons. Staples", "XLY": "Cons. Discr.", "XLC": "Comm. Services",
        "XLRE": "Real Estate", "XLU": "Utilities", "SPY": "S&P 500",
    }

    results = []
    for item in data.get("data", []):
        ticker = item.get("ticker", "")
        if not ticker:
            continue

        bull_prem = _sf(item.get("bullish_premium", 0))
        bear_prem = _sf(item.get("bearish_premium", 0))
        call_vol = _sf(item.get("call_volume", 0))
        put_vol = _sf(item.get("put_volume", 0))
        avg30_call = _sf(item.get("avg30_call_volume", item.get("avg_30_day_call_volume", 0)))

        total_prem = bull_prem + bear_prem
        call_pct = round(bull_prem / total_prem * 100, 1) if total_prem else 50.0
        cp_ratio = round(call_vol / put_vol, 2) if put_vol else 0
        call_vs30 = round(call_vol / avg30_call, 2) if avg30_call else 1.0

        # 5-day ETF share flow (positive = money flowing in)
        raw_flow = item.get("in_out_flow", [])
        if isinstance(raw_flow, list):
            etf_flow_5d = sum(
                _sf(f.get("change", 0)) if isinstance(f, dict) else 0
                for f in raw_flow
            )
        else:
            etf_flow_5d = 0

        # Sentiment
        if call_pct >= 55 or (call_pct >= 50 and etf_flow_5d > 0):
            sentiment = "BULLISH"
        elif call_pct <= 45 or (call_pct < 50 and etf_flow_5d < 0):
            sentiment = "BEARISH"
        else:
            sentiment = "NEUTRAL"

        # Price performance vs prev close
        last = _sf(item.get("last", 0))
        prev_close = _sf(item.get("prev_close", 0))
        chg_pct = round((last - prev_close) / prev_close * 100, 2) if prev_close else 0.0

        results.append({
            "ticker": ticker,
            "name": etf_names.get(ticker, item.get("full_name", ticker)),
            "last": last,
            "chg_pct": chg_pct,         # price % change today
            "call_pct": call_pct,
            "cp_ratio": cp_ratio,
            "call_vs30": call_vs30,
            "etf_flow_5d": int(etf_flow_5d),
            "bull_prem": round(bull_prem),
            "bear_prem": round(bear_prem),
            "sentiment": sentiment,
        })

    results.sort(key=lambda x: x["call_pct"], reverse=True)
    return results


# Index/ETF tickers to exclude from individual stock flow leaderboard
_FLOW_EXCLUDE = {
    "SPX", "SPXW", "NDX", "RUT", "VIX", "VIXW", "SPY", "QQQ", "IWM",
    "DIA", "GLD", "SLV", "TLT", "HYG", "EEM", "EFA", "XLK", "XLF",
    "XLV", "XLE", "XLI", "XLB", "XLP", "XLY", "XLC", "XLRE", "XLU",
}


def get_top_flow(limit=15):
    """
    Top individual stocks by unusual options flow from UW screener.
    Scores by: relative call volume × bullish premium %.
    Returns list sorted by flow score descending.
    """
    data = uw_screener({"order": "call_volume", "order_direction": "desc", "limit": 50})
    if not data:
        return []

    results = []
    for item in data.get("data", []):
        ticker = str(item.get("ticker", "")).upper()
        if not ticker or ticker in _FLOW_EXCLUDE:
            continue
        # Skip obvious index names (numeric-heavy)
        if any(c.isdigit() for c in ticker):
            continue

        bull_prem = _sf(item.get("bullish_premium", 0))
        bear_prem = _sf(item.get("bearish_premium", 0))
        total_prem = bull_prem + bear_prem
        bull_pct = round(bull_prem / total_prem * 100, 1) if total_prem else 50.0

        call_vol = _sf(item.get("call_volume", 0))
        put_vol = _sf(item.get("put_volume", 0))
        avg30_call = _sf(item.get("avg_30_day_call_volume",
                                  item.get("avg30_call_volume", 1)))
        call_vs30 = round(call_vol / avg30_call, 2) if avg30_call else 1.0

        # Aggressive call buying (at the ask)
        call_ask = _sf(item.get("call_volume_ask_side", 0))
        ask_pct = round(call_ask / call_vol * 100, 1) if call_vol else 0.0

        pcr = round(put_vol / call_vol, 2) if call_vol else 99.0
        iv_rank = round(_sf(item.get("iv_rank", 0)), 1)
        sector = item.get("sector", "") or ""

        # Flow score: unusual call activity weighted by bullish premium direction
        flow_score = round(call_vs30 * (bull_pct / 50), 2)

        if bull_pct >= 57 and pcr <= 0.45:
            sentiment = "STRONG BULL"
        elif bull_pct >= 52:
            sentiment = "BULLISH"
        elif bull_pct <= 43 and pcr >= 1.5:
            sentiment = "STRONG BEAR"
        elif bull_pct <= 48:
            sentiment = "BEARISH"
        else:
            sentiment = "NEUTRAL"

        results.append({
            "ticker": ticker,
            "sector": sector,
            "bull_pct": bull_pct,
            "pcr": pcr,
            "call_vs30": call_vs30,
            "ask_pct": ask_pct,
            "iv_rank": iv_rank,
            "bull_prem": round(bull_prem),
            "bear_prem": round(bear_prem),
            "call_vol": int(call_vol),
            "flow_score": flow_score,
            "sentiment": sentiment,
        })

    results.sort(key=lambda x: x["flow_score"], reverse=True)
    return results[:limit]


def uw_seasonality(ticker):
    """Monthly seasonality for ticker."""
    return _get(f"/api/seasonality/{ticker}/monthly", ttl=86400)


def uw_news_headlines():
    """Live news headlines."""
    return _get("/api/news/headlines", ttl=120)


# ─── GEX helper ──────────────────────────────────────────────────────────────

def _compute_gex(ticker):
    """
    Fetch greek-exposure and return a plain-English GEX summary dict.
    Net GEX = sum(call_gamma + put_gamma) across all expiries.
    Positive = dealers long gamma (mean-reverting / pinning).
    Negative = dealers short gamma (moves amplified / trending).
    """
    data = uw_gex(ticker)
    if not data:
        return {"available": False, "text": "not available"}

    rows = data.get("data", [])
    if not rows:
        return {"available": False, "text": "no data returned"}

    # Aggregate net GEX across all expiries
    net_gex = sum(_sf(r.get("call_gamma", 0)) + _sf(r.get("put_gamma", 0)) for r in rows)

    # Largest single-expiry wall (most gamma concentration)
    def _row_net(r):
        return abs(_sf(r.get("call_gamma", 0)) + _sf(r.get("put_gamma", 0)))
    wall_row = max(rows, key=_row_net)
    wall_date = wall_row.get("date", "")
    wall_net = _sf(wall_row.get("call_gamma", 0)) + _sf(wall_row.get("put_gamma", 0))

    # Net delta (dealer directional exposure)
    net_delta = sum(_sf(r.get("call_delta", 0)) + _sf(r.get("put_delta", 0)) for r in rows)

    # Interpretation
    if net_gex > 0:
        regime = "POSITIVE"
        meaning = "dealers are long gamma — expect mean-reversion, moves get faded"
    elif net_gex < 0:
        regime = "NEGATIVE"
        meaning = "dealers are short gamma — moves tend to be amplified and trending"
    else:
        regime = "NEUTRAL"
        meaning = "balanced gamma — no strong pinning or amplification"

    sign = "+" if net_gex >= 0 else ""
    delta_sign = "+" if net_delta >= 0 else ""

    return {
        "available": True,
        "net_gex": round(net_gex),
        "net_delta": round(net_delta),
        "regime": regime,
        "wall_date": wall_date,
        "wall_net": round(wall_net),
        "expiry_count": len(rows),
        "text": (
            f"{regime} ({sign}{net_gex / 1e6:.1f}M net) — {meaning}. "
            f"Largest wall: {wall_date} ({'+' if wall_net >= 0 else ''}{wall_net / 1e6:.1f}M). "
            f"Net delta: {delta_sign}{net_delta / 1e6:.0f}M."
        ),
    }


# ─── Smart Money Score (Layer 6) — upgraded ──────────────────────────────────

def smart_money_score(ticker):
    """
    Returns {score, notes, signals, evidence, available}.
    Scoring weights are unchanged. Evidence block added for display.
    """
    uw_key = os.environ.get("UW_API_KEY", UW_KEY)
    if not uw_key:
        return {"score": 0, "notes": [], "signals": [], "evidence": {}, "available": False,
                "detail": "UW_API_KEY not configured"}

    score = 0
    notes = []
    signals = []
    raw = {}

    # Evidence block — all raw data for display, no fabrication
    evidence = {
        "flow": [],
        "darkpool": [],
        "insider": [],
        "congress": [],
        "gex": _compute_gex(ticker),
        "short_interest": None,
    }

    # ─── Options flow ─────────────────────────────────────────────────────────
    flow_data = uw_ticker_flow(ticker) or uw_flow_alerts(ticker)
    if flow_data:
        items = flow_data.get("data", flow_data if isinstance(flow_data, list) else [])
        bullish_sweeps = []
        for item in items[:25]:
            put_call = str(item.get("type", item.get("put_call", ""))).lower()
            premium = _sf(item.get("total_premium") or item.get("premium") or item.get("size", 0))
            strike = str(item.get("strike", item.get("strike_price", "?")))
            expiry = item.get("expiry", item.get("expiration_date", ""))

            # ASK vs BID — prefer direct fields, fallback to execution_estimate
            ask_prem = _sf(item.get("total_ask_side_prem", 0))
            bid_prem = _sf(item.get("total_bid_side_prem", 0))
            if ask_prem or bid_prem:
                at_ask = ask_prem >= bid_prem
            else:
                execution = str(item.get("execution_estimate", "")).lower()
                at_ask = "ask" in execution or "above" in execution

            is_sweep = bool(item.get("has_sweep", False))
            is_call = "call" in put_call
            is_put = "put" in put_call
            sentiment = str(item.get("sentiment", "")).lower()
            is_bullish = "bullish" in sentiment or "bull" in sentiment or is_call

            # Opening vs closing
            all_opening = bool(item.get("all_opening_trades", False))
            vol_oi = _sf(item.get("volume_oi_ratio", 0))
            is_opening = all_opening or vol_oi > 1.0

            alert_rule = item.get("alert_rule", "")
            trade_count = item.get("trade_count", 0) or item.get("trades", 0)

            # Evidence item — every trade regardless of size threshold
            evidence["flow"].append({
                "direction": "BULLISH" if (is_call or (is_bullish and not is_put)) else "BEARISH",
                "type": put_call or "unknown",
                "at_ask": at_ask,
                "is_sweep": is_sweep,
                "premium": premium,
                "strike": strike,
                "expiry": expiry,
                "opening": is_opening,
                "vol_oi_ratio": round(vol_oi, 2) if vol_oi else None,
                "alert_rule": alert_rule,
                "trade_count": trade_count,
            })

            # Scoring: large bullish flow only (unchanged)
            if (is_call or is_bullish) and premium >= 500_000:
                bullish_sweeps.append({"premium": premium, "strike": strike,
                                       "expiry": expiry, "at_ask": at_ask})

        if bullish_sweeps:
            total = sum(s["premium"] for s in bullish_sweeps)
            best = max(bullish_sweeps, key=lambda x: x["premium"])
            score += 8
            note = f"${total / 1e6:.1f}M bullish call sweep"
            if best.get("strike"):
                note += f" (${best['strike']} strike)"
            notes.append(note)
            signals.append({
                "type": "FLOW", "icon": "🔥", "text": note, "bullish": True,
                "detail": (
                    f"Largest: ${best['premium'] / 1e6:.1f}M"
                    f" · Strike ${best['strike']} · Expiry {best['expiry']}"
                ),
            })
            raw["flow"] = bullish_sweeps

    # ─── Dark pool ────────────────────────────────────────────────────────────
    dp_data = uw_darkpool(ticker)
    if dp_data:
        items = dp_data.get("data", dp_data if isinstance(dp_data, list) else [])
        big_prints = []
        for item in items[:15]:
            shares = _sf(item.get("size", 0))
            dp_price = _sf(item.get("price", 0))
            notional = _sf(item.get("premium") or item.get("notional_value", 0))
            if not notional and shares and dp_price:
                notional = shares * dp_price
            nbbo_bid = _sf(item.get("nbbo_bid", 0))
            nbbo_ask = _sf(item.get("nbbo_ask", 0))
            nbbo_mid = (nbbo_bid + nbbo_ask) / 2 if nbbo_bid and nbbo_ask else None

            evidence["darkpool"].append({
                "shares": int(shares),
                "price": round(dp_price, 2),
                "notional": round(notional, 2),
                "nbbo_bid": nbbo_bid,
                "nbbo_ask": nbbo_ask,
                "below_mid": (dp_price < nbbo_mid) if nbbo_mid else None,
                "ext_hours": bool(item.get("ext_hour_sold_codes")),
                "executed_at": item.get("executed_at", ""),
            })

            if notional >= 1_000_000:
                big_prints.append({"size": notional, "price": dp_price, "shares": int(shares)})

        if big_prints:
            total = sum(p["size"] for p in big_prints)
            score += 5
            note = f"${total / 1e6:.0f}M dark pool print"
            notes.append(note)
            biggest = max(big_prints, key=lambda x: x["size"])
            signals.append({
                "type": "DARKPOOL", "icon": "🌊", "text": note, "bullish": True,
                "detail": f"Largest: ${biggest['size'] / 1e6:.1f}M @ ${biggest['price']:.2f}",
            })
            raw["darkpool"] = big_prints

    # ─── Insider ──────────────────────────────────────────────────────────────
    ins_data = uw_insider(ticker)
    if ins_data:
        items = ins_data.get("data", ins_data if isinstance(ins_data, list) else [])
        insider_buys = []
        for item in items[:15]:
            tx_type = str(item.get("transaction_type", item.get("type", ""))).lower()
            value = _sf(item.get("value") or item.get("shares_value") or item.get("total_value", 0))
            who = item.get("insider_name", item.get("name", "Insider"))
            role = item.get("title", item.get("insider_title", ""))
            date_str = item.get("filing_date", item.get("date", ""))

            evidence["insider"].append({
                "type": tx_type, "value": value, "who": who,
                "role": role, "date": date_str,
                "is_buy": "buy" in tx_type or "purchase" in tx_type,
            })

            if ("buy" in tx_type or "purchase" in tx_type) and value >= 100_000:
                insider_buys.append({"value": value, "who": who, "role": role, "date": date_str})

        if insider_buys:
            score += 4
            biggest = max(insider_buys, key=lambda x: x["value"])
            note = f"{biggest['who']} bought ${biggest['value'] / 1e6:.1f}M"
            if biggest["role"]:
                note += f" ({biggest['role']})"
            notes.append(note)
            signals.append({
                "type": "INSIDER", "icon": "👔", "text": note, "bullish": True,
                "detail": f"Filed: {biggest['date']} · {len(insider_buys)} insider buy(s)",
            })
            raw["insider"] = insider_buys

    # ─── Congress ─────────────────────────────────────────────────────────────
    cong_data = uw_congress(ticker) or uw_congress_unusual(ticker)
    if cong_data:
        items = cong_data.get("data", cong_data if isinstance(cong_data, list) else [])
        for item in items[:10]:
            tx = str(item.get("transaction_type", "")).lower()
            evidence["congress"].append({
                "name": item.get("politician_name", item.get("name", "Unknown")),
                "party": item.get("party", ""),
                "type": tx,
                "amount": item.get("amount", item.get("trade_size", "")),
                "date": item.get("transaction_date", item.get("date", "")),
                "is_buy": "buy" in tx or "purchase" in tx,
            })

        buys = [i for i in items[:10]
                if "buy" in str(i.get("transaction_type", "")).lower()
                or "purchase" in str(i.get("transaction_type", "")).lower()]
        if buys:
            score += 3
            name = buys[0].get("politician_name", buys[0].get("name", "Congress"))
            party = buys[0].get("party", "")
            note = f"Congress buy: {name}" + (f" ({party})" if party else "")
            notes.append(note)
            signals.append({
                "type": "CONGRESS", "icon": "🏛", "text": note, "bullish": True,
                "detail": f"{len(buys)} congressional purchase(s)",
            })
            raw["congress"] = buys

    # ─── Short interest (note only, no score) ────────────────────────────────
    short_data = uw_shorts(ticker)
    if short_data:
        sdata = short_data.get("data", {})
        if isinstance(sdata, list) and sdata:
            sdata = sdata[0]
        short_float = _sf(sdata.get("short_float_pct", sdata.get("short_percent_of_float", 0)))
        evidence["short_interest"] = round(short_float, 1) if short_float else None
        if short_float > 20:
            note = f"High short interest {short_float:.1f}% float — squeeze potential"
            notes.append(note)
            signals.append({
                "type": "SHORT", "icon": "⚡", "text": note, "bullish": None,
                "detail": f"Short float: {short_float:.1f}%",
            })
            raw["shorts"] = short_float

    return {
        "score": min(score, 20),
        "notes": notes,
        "signals": signals,
        "evidence": evidence,
        "available": True,
        "raw": raw,
    }


def get_market_regime():
    """Return {regime: 'BULLISH'|'NEUTRAL'|'BEARISH', summary, advice}."""
    tide_data = uw_market_tide()

    if not tide_data:
        return {"regime": "NEUTRAL", "summary": "UW market data unavailable",
                "advice": "Trade normal position sizing", "available": False}

    data = tide_data.get("data", tide_data if isinstance(tide_data, dict) else {})
    if isinstance(data, list) and data:
        data = data[0]

    bull_score = _sf(data.get("bullish_premium") or data.get("call_premium", 0))
    bear_score = _sf(data.get("bearish_premium") or data.get("put_premium", 0))
    net_gamma = _sf(data.get("net_gamma", 0))
    sentiment = str(data.get("sentiment", data.get("market_sentiment", ""))).lower()

    # Determine regime
    if "bullish" in sentiment or bull_score > bear_score * 1.3 or net_gamma > 0:
        regime = "BULLISH"
        summary = "Market tide is bullish — options flow favors upside"
        advice = "Risk-on: normal position sizing, setups more reliable"
        color = "green"
    elif "bearish" in sentiment or bear_score > bull_score * 1.3 or net_gamma < 0:
        regime = "BEARISH"
        summary = "Market tide is bearish — defensive positioning"
        advice = "Risk-off: reduce size 50%, only trade 85+ scores"
        color = "red"
    else:
        regime = "NEUTRAL"
        summary = "Market tide is neutral — mixed signals"
        advice = "Be selective: only high-conviction setups (80+)"
        color = "yellow"

    return {
        "regime": regime,
        "summary": summary,
        "advice": advice,
        "color": color,
        "available": True,
        "raw": data,
    }


def get_earnings_warning(ticker):
    """Check if earnings within 14 days — returns warning string or None."""
    import datetime
    today = datetime.date.today()
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
                    when = "TODAY" if days_away == 0 else f"in {days_away}d"
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
    month_names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
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
                return f"{ticker} historically +{avg_ret * 100:.1f}% in {month_name} ({win_pct * 100:.0f}% win rate)"
            elif avg_ret < -0.01:
                return (
                    f"{ticker} historically {avg_ret * 100:.1f}% in {month_name} "
                    f"({win_pct * 100:.0f}% win rate) — seasonally weak"
                )
    return None


def _sf(val):
    try:
        return float(val or 0)
    except (TypeError, ValueError):
        return 0.0
