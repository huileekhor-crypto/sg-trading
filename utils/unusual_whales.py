import os
import time
import requests

UW_KEY  = os.environ.get("UW_API_KEY", "")
BASE    = "https://api.unusualwhales.com"
HEADERS = {"Authorization": f"Bearer {UW_KEY}"}

_cache = {}
CACHE_TTL = 300  # 5 min


def _get(endpoint, params=None):
    key = f"{endpoint}:{str(params)}"
    now = time.time()
    if key in _cache and now - _cache[key]["ts"] < CACHE_TTL:
        return _cache[key]["data"]
    if not UW_KEY:
        return None
    try:
        r = requests.get(f"{BASE}{endpoint}", params=params,
                         headers=HEADERS, timeout=10)
        if not r.ok:
            return None
        data = r.json()
        _cache[key] = {"data": data, "ts": now}
        return data
    except Exception:
        return None


def uw_flow_alerts(ticker):
    return _get("/api/option-trades/flow-alerts", {"ticker": ticker, "limit": 20})


def uw_darkpool(ticker):
    return _get("/api/darkpool/recent", {"ticker": ticker, "limit": 10})


def uw_insider(ticker):
    return _get("/api/insider/transactions", {"ticker": ticker, "limit": 10})


def uw_congress(ticker):
    return _get("/api/congress/recent-trades", {"ticker": ticker, "limit": 5})


def smart_money_score(ticker):
    """Returns {score: 0-20, notes: [...], available: bool}."""
    if not UW_KEY:
        return {"score": 0, "notes": [], "available": False,
                "detail": "UW_API_KEY not configured"}

    score = 0
    notes = []
    raw   = {}

    # --- Options flow ---
    flow_data = uw_flow_alerts(ticker)
    if flow_data:
        items = flow_data.get("data", flow_data if isinstance(flow_data, list) else [])
        bullish_sweeps = []
        for item in items[:20]:
            # Look for bullish call sweeps bought at ask > $500k
            sentiment = str(item.get("sentiment", "")).lower()
            side      = str(item.get("side", "")).lower()
            put_call  = str(item.get("put_call", item.get("type", ""))).lower()
            premium   = _safe_float(item.get("premium") or item.get("size", 0))
            execution = str(item.get("execution_estimate", "")).lower()

            is_call    = "call" in put_call
            is_bullish = "bullish" in sentiment or "bull" in sentiment
            at_ask     = "ask" in execution or "above" in execution

            if (is_call or is_bullish) and premium >= 500_000:
                bullish_sweeps.append(premium)

        if bullish_sweeps:
            total = sum(bullish_sweeps)
            score += 10
            notes.append(f"${total/1e6:.1f}M bullish call sweep{'s' if len(bullish_sweeps)>1 else ''}")
            raw["flow"] = bullish_sweeps

    # --- Dark pool ---
    dp_data = uw_darkpool(ticker)
    if dp_data:
        items = dp_data.get("data", dp_data if isinstance(dp_data, list) else [])
        big_prints = []
        for item in items[:10]:
            size    = _safe_float(item.get("size") or item.get("notional_value", 0))
            dp_price = _safe_float(item.get("price", 0))
            if size >= 1_000_000:
                big_prints.append({"size": size, "price": dp_price})

        if big_prints:
            total = sum(p["size"] for p in big_prints)
            score += 5
            notes.append(f"${total/1e6:.0f}M dark pool print")
            raw["darkpool"] = big_prints

    # --- Insider transactions ---
    ins_data = uw_insider(ticker)
    if ins_data:
        items = ins_data.get("data", ins_data if isinstance(ins_data, list) else [])
        insider_buys = []
        now_ts = time.time()
        for item in items[:10]:
            tx_type = str(item.get("transaction_type", item.get("type", ""))).lower()
            value   = _safe_float(item.get("value") or item.get("shares_value", 0))
            date_str = item.get("filing_date", item.get("date", ""))
            if ("buy" in tx_type or "purchase" in tx_type) and value >= 100_000:
                insider_buys.append({"value": value, "who": item.get("insider_name", "Insider")})

        if insider_buys:
            score += 5
            biggest = max(insider_buys, key=lambda x: x["value"])
            notes.append(f"{biggest['who']} bought ${biggest['value']/1e6:.1f}M")
            raw["insider"] = insider_buys

    # --- Congress ---
    cong_data = uw_congress(ticker)
    if cong_data:
        items = cong_data.get("data", cong_data if isinstance(cong_data, list) else [])
        buys = [i for i in items[:5]
                if "buy" in str(i.get("transaction_type", "")).lower()
                or "purchase" in str(i.get("transaction_type", "")).lower()]
        if buys:
            name = buys[0].get("politician_name", buys[0].get("name", "Congress"))
            notes.append(f"Congress buy: {name}")
            raw["congress"] = buys

    return {
        "score":     min(score, 20),
        "notes":     notes,
        "available": True,
        "raw":       raw,
    }


def _safe_float(val):
    try:
        return float(val or 0)
    except (TypeError, ValueError):
        return 0.0
