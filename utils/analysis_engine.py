"""6-layer analysis engine. All layers return scores, explanations, raw data."""

import math
from utils.prices import get_candles, get_live_price, get_fundamentals, get_news
from utils.unusual_whales import smart_money_score


# ─── Technical helpers ────────────────────────────────────────────────────────

def _swing_highs(candles, lookback=60, window=3):
    """Pivot highs: bars where high > {window} bars on each side."""
    subset = candles[-lookback:] if len(candles) > lookback else candles
    highs = []
    for i in range(window, len(subset) - window):
        h = subset[i]['h']
        if all(h > subset[j]['h'] for j in range(i - window, i)) and \
           all(h > subset[j]['h'] for j in range(i + 1, i + window + 1)):
            highs.append(round(h, 2))
    return highs


def _swing_lows(candles, lookback=60, window=3):
    """Pivot lows: bars where low < {window} bars on each side."""
    subset = candles[-lookback:] if len(candles) > lookback else candles
    lows = []
    for i in range(window, len(subset) - window):
        l = subset[i]['l']
        if all(l < subset[j]['l'] for j in range(i - window, i)) and \
           all(l < subset[j]['l'] for j in range(i + 1, i + window + 1)):
            lows.append(round(l, 2))
    return lows


def calc_planned_entry(price, candles, ema20, ema50, atr):
    """
    Choose BREAKOUT or PULLBACK entry from actual chart levels.
    Returns: {entry, entry_type, entry_reason, resistance, support, current_price}
    """
    if not candles or not price:
        return {"entry": price, "entry_type": "MARKET",
                "entry_reason": "Insufficient data — using current price",
                "resistance": None, "support": None, "current_price": price}

    recent_highs = _swing_highs(candles, lookback=25, window=3)
    all_highs    = _swing_highs(candles, lookback=60, window=3)
    all_lows     = _swing_lows(candles,  lookback=60, window=3)

    # Nearest resistance above price
    res_above = [h for h in all_highs if h > price * 1.001]
    nearest_resistance = round(min(res_above), 2) if res_above else None

    # Most recent pivot high (for breakout detection)
    recent_pivot = max(recent_highs) if recent_highs else None

    # Nearest swing-low support below price
    sup_below = [l for l in all_lows if l < price * 0.999]
    nearest_support = round(max(sup_below), 2) if sup_below else None

    ext20 = (price - ema20) / ema20 * 100 if ema20 else 0

    # ── BREAKOUT: price is within ±3% of a recent pivot high ──────────────────
    if recent_pivot:
        dist = (price - recent_pivot) / recent_pivot * 100
        if -1.0 <= dist <= 3.0:
            breakout_entry = round(recent_pivot * 1.003, 2)
            pct_above = round(dist, 1)
            return {
                "entry":        breakout_entry,
                "entry_type":   "BREAKOUT",
                "entry_reason": (
                    f"Price {'clearing' if dist >= 0 else 'testing'} "
                    f"${recent_pivot:.2f} pivot high "
                    f"({'up {:.1f}%'.format(pct_above) if dist >= 0 else '{:.1f}% below'.format(abs(pct_above))}). "
                    f"Enter on confirmed close above — limit ${breakout_entry:.2f}."
                ),
                "resistance":   nearest_resistance,
                "support":      nearest_support or (round(ema20, 2) if ema20 else None),
                "current_price": price,
            }

    # ── PULLBACK to EMA50: extended >8% above EMA20 ───────────────────────────
    if ema50 and ext20 > 8:
        entry = round(ema50, 2)
        return {
            "entry":        entry,
            "entry_type":   "PULLBACK",
            "entry_reason": (
                f"Extended {ext20:.1f}% above EMA20 — entering here is FOMO. "
                f"Wait for pullback to EMA50 at ${entry:.2f}."
            ),
            "resistance":   nearest_resistance,
            "support":      entry,
            "current_price": price,
        }

    # ── PULLBACK to EMA20: extended 3-8% above EMA20 ──────────────────────────
    if ema20 and 3 < ext20 <= 8:
        entry = round(ema20, 2)
        return {
            "entry":        entry,
            "entry_type":   "PULLBACK",
            "entry_reason": (
                f"Extended {ext20:.1f}% above EMA20 at ${entry:.2f}. "
                f"Wait for pullback to EMA20 — better risk/reward entry at support."
            ),
            "resistance":   nearest_resistance,
            "support":      entry,
            "current_price": price,
        }

    # ── AT SUPPORT: price near EMA20 (±3%) — good pullback entry ──────────────
    if ema20 and abs(ext20) <= 3:
        entry = round(ema20, 2) if price >= ema20 else price
        return {
            "entry":        entry,
            "entry_type":   "PULLBACK",
            "entry_reason": (
                f"Consolidating at EMA20 support (${entry:.2f}), "
                f"{ext20:.1f}% {'above' if ext20 >= 0 else 'below'} — good risk/reward entry zone."
            ),
            "resistance":   nearest_resistance,
            "support":      nearest_support or entry,
            "current_price": price,
        }

    # ── DEFAULT: use current price ─────────────────────────────────────────────
    return {
        "entry":        price,
        "entry_type":   "MARKET",
        "entry_reason": "No clean chart level identified — entry at current market price.",
        "resistance":   nearest_resistance,
        "support":      nearest_support,
        "current_price": price,
    }


def _ema(prices, period):
    if len(prices) < period:
        return None
    k = 2 / (period + 1)
    ema = sum(prices[:period]) / period
    for p in prices[period:]:
        ema = p * k + ema * (1 - k)
    return round(ema, 4)


def _rsi(closes, period=14):
    if len(closes) < period + 1:
        return None
    gains2, losses2 = [], []
    for i in range(1, len(closes)):
        d = closes[i] - closes[i - 1]
        gains2.append(max(d, 0))
        losses2.append(max(-d, 0))

    if len(gains2) < period:
        return None
    avg_gain = sum(gains2[:period]) / period
    avg_loss = sum(losses2[:period]) / period
    for i in range(period, len(gains2)):
        avg_gain = (avg_gain * (period - 1) + gains2[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses2[i]) / period

    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100 - 100 / (1 + rs), 2)


def _atr(candles, period=14):
    if len(candles) < period + 1:
        return None
    trs = []
    for i in range(1, len(candles)):
        h, l, pc = candles[i]["h"], candles[i]["l"], candles[i - 1]["c"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    if not trs:
        return None
    atr = sum(trs[:period]) / period
    for tr in trs[period:]:
        atr = (atr * (period - 1) + tr) / period
    return round(atr, 4)


# ─── Layer 1: TREND (0-25) ───────────────────────────────────────────────────

def layer1_trend(price, ema20, ema50, ema200):
    score = 0
    reasons = []
    if ema200 and price > ema200:
        score += 10
        reasons.append(f"Above EMA200 (${ema200:.2f})")
    elif ema200:
        reasons.append(f"Below EMA200 (${ema200:.2f}) — bearish")
    if ema50 and price > ema50:
        score += 8
        reasons.append(f"Above EMA50 (${ema50:.2f})")
    elif ema50:
        reasons.append(f"Below EMA50 (${ema50:.2f})")
    if ema20 and price > ema20:
        score += 7
        reasons.append(f"Above EMA20 (${ema20:.2f})")
    elif ema20:
        reasons.append(f"Below EMA20 (${ema20:.2f})")
    return {"score": score, "max": 25, "reasons": reasons,
            "ema20": ema20, "ema50": ema50, "ema200": ema200}


# ─── Layer 2: MOMENTUM / anti-FOMO (0-25) ────────────────────────────────────

def layer2_momentum(rsi):
    if rsi is None:
        return {"score": 0, "max": 25, "rsi": None, "reason": "Insufficient data"}
    if 45 <= rsi <= 60:
        score, label = 25, "Ideal entry zone"
    elif 60 < rsi <= 65:
        score, label = 18, "Slightly elevated"
    elif 65 < rsi <= 70:
        score, label = 10, "Getting stretched"
    elif 70 < rsi <= 75:
        score, label = 5,  "Overbought — caution"
    elif rsi > 75:
        score, label = 0,  "Severely overbought — FOMO zone"
    elif 30 <= rsi < 45:
        score, label = 15, "Oversold bounce potential"
    else:
        score, label = 20, "Deeply oversold — mean reversion"
    return {"score": score, "max": 25, "rsi": round(rsi, 1), "reason": label}


# ─── Layer 3: VOLUME (0-20) ──────────────────────────────────────────────────

def layer3_volume(vol_today, candles):
    if not candles or len(candles) < 20:
        return {"score": 5, "max": 20, "ratio": None, "reason": "Insufficient candle data"}
    avg20 = sum(c["v"] for c in candles[-21:-1]) / 20
    if avg20 == 0:
        return {"score": 5, "max": 20, "ratio": None, "reason": "No volume data"}
    ratio = vol_today / avg20
    if ratio >= 2.0:
        score, label = 20, f"{ratio:.1f}x avg — exceptional volume"
    elif ratio >= 1.5:
        score, label = 15, f"{ratio:.1f}x avg — strong volume"
    elif ratio >= 1.0:
        score, label = 10, f"{ratio:.1f}x avg — normal"
    else:
        score, label = 5,  f"{ratio:.1f}x avg — below average"
    return {"score": score, "max": 20, "ratio": round(ratio, 2), "avg20": round(avg20),
            "vol_today": round(vol_today), "reason": label}


# ─── Layer 4: STRUCTURE / anti-FOMO (0-20) ───────────────────────────────────

def layer4_structure(price, ema20):
    if not ema20 or ema20 == 0:
        return {"score": 10, "max": 20, "extension_pct": None, "reason": "EMA20 unavailable"}
    ext = (price - ema20) / ema20 * 100
    if ext < 3:
        score, label = 20, "At support — ideal entry"
    elif ext < 6:
        score, label = 15, "Slightly extended — still ok"
    elif ext < 10:
        score, label = 10, "Extended — wait for pullback"
    elif ext < 15:
        score, label = 5,  "Very extended — high risk"
    else:
        score, label = 0,  "FOMO territory — do NOT chase"
    return {"score": score, "max": 20, "extension_pct": round(ext, 1),
            "ema20": ema20, "reason": label}


# ─── Layer 5: CATALYST (0-10) ────────────────────────────────────────────────

def layer5_catalyst(ticker, news_items):
    """Rate news catalyst via keyword analysis (Claude rates in senior_trader)."""
    if not news_items:
        return {"score": 0, "max": 10, "reason": "No recent news", "headlines": []}

    headlines = [n.get("headline", "") for n in news_items[:5]]
    combined  = " ".join(headlines).lower()

    major_keywords = ["earnings", "revenue beat", "record", "contract", "acquisition",
                      "partnership", "fda approval", "breakthrough", "raised guidance"]
    theme_keywords = ["ai", "artificial intelligence", "semiconductor", "cloud",
                      "data center", "chip", "upgrade", "sector rally"]
    analyst_keywords = ["analyst", "upgraded", "price target", "overweight", "buy rating",
                        "initiated", "raised target"]
    hype_keywords = ["social", "retail", "trending", "viral", "meme"]

    if any(k in combined for k in major_keywords):
        score, label = 10, "Major catalyst (earnings/contract/milestone)"
    elif any(k in combined for k in theme_keywords):
        score, label = 7, "Theme/sector tailwind"
    elif any(k in combined for k in analyst_keywords):
        score, label = 5, "Analyst upgrade/price target raise"
    elif any(k in combined for k in hype_keywords):
        score, label = 2, "Social/retail hype only"
    else:
        score, label = 3, "Minor news"

    return {"score": score, "max": 10, "reason": label, "headlines": headlines[:3]}


# ─── Layer 6: SMART MONEY (0-20) ─────────────────────────────────────────────

def layer6_smart_money(ticker):
    result = smart_money_score(ticker)
    return {
        "score":     result["score"],
        "max":       20,
        "notes":     result["notes"],
        "signals":   result.get("signals", []),
        "available": result["available"],
        "reason":    ", ".join(result["notes"]) if result["notes"] else "No unusual activity",
        "raw":       result.get("raw", {}),
    }


# ─── Main analysis runner ─────────────────────────────────────────────────────

def run_full_analysis(ticker, mode="SWING"):
    """Run all 6 layers. Returns complete analysis dict."""
    from utils.unusual_whales import get_earnings_warning, get_seasonality_note
    # Fetch data
    price_data   = get_live_price(ticker)
    candles      = get_candles(ticker, days=300)
    news_items   = get_news(ticker, count=5)
    fundamentals = get_fundamentals(ticker)
    # Earnings warning + seasonality (non-blocking)
    try:
        earnings_warning = get_earnings_warning(ticker)
    except Exception:
        earnings_warning = None
    try:
        seasonality_note = get_seasonality_note(ticker)
    except Exception:
        seasonality_note = None

    price = price_data.get("price", 0)
    vol   = price_data.get("volume", 0)

    closes = [c["c"] for c in candles] if candles else []

    ema20  = _ema(closes, 20)  if len(closes) >= 20  else None
    ema50  = _ema(closes, 50)  if len(closes) >= 50  else None
    ema200 = _ema(closes, 200) if len(closes) >= 200 else None
    rsi    = _rsi(closes, 14)  if len(closes) >= 15  else None
    atr    = _atr(candles, 14) if len(candles) >= 15  else None

    # Run layers
    l1 = layer1_trend(price, ema20, ema50, ema200)
    l2 = layer2_momentum(rsi)
    l3 = layer3_volume(vol, candles)
    l4 = layer4_structure(price, ema20)
    l5 = layer5_catalyst(ticker, news_items)
    l6 = layer6_smart_money(ticker)

    # Weighted scoring by mode
    if mode == "LONG-TERM":
        # Emphasise trend + catalyst + fundamentals
        raw_score = (
            l1["score"] * 1.2 +  # trend weighted up
            l2["score"] * 0.8 +  # momentum less critical
            l3["score"] * 0.9 +
            l4["score"] * 0.9 +
            l5["score"] * 1.2 +  # catalyst more important
            l6["score"] * 1.0
        )
        max_possible = 25*1.2 + 25*0.8 + 20*0.9 + 20*0.9 + 10*1.2 + 20*1.0  # 102
    else:  # SWING
        # Emphasise momentum + structure + smart money
        raw_score = (
            l1["score"] * 1.0 +
            l2["score"] * 1.2 +  # momentum critical for timing
            l3["score"] * 1.0 +
            l4["score"] * 1.2 +  # structure (anti-FOMO) critical
            l5["score"] * 0.8 +
            l6["score"] * 1.2    # smart money confirmation
        )
        max_possible = 25*1.0 + 25*1.2 + 20*1.0 + 20*1.2 + 10*0.8 + 20*1.2  # 110

    score = round(min(raw_score / max_possible * 100, 100))

    if score >= 85:
        verdict, verdict_class = "STRONG BUY", "strong-buy"
    elif score >= 70:
        verdict, verdict_class = "BUY", "buy"
    elif score >= 55:
        verdict, verdict_class = "WAIT", "wait"
    elif score >= 40:
        verdict, verdict_class = "WEAK", "weak"
    else:
        verdict, verdict_class = "AVOID", "avoid"

    # Planned entry from chart levels (breakout or pullback)
    planned = calc_planned_entry(price, candles, ema20, ema50, atr)
    entry   = planned["entry"]

    # ATR-based stops/targets built from planned entry (not live price)
    atr_val = atr or 0
    if atr_val:
        stop_swing   = round(entry - 1.5 * atr_val, 2)
        target_swing = round(entry + 3.0 * atr_val, 2)
        stop_lt      = round(entry - 3.0 * atr_val, 2)
        target_lt    = round(entry + 8.0 * atr_val, 2)
    else:
        stop_swing   = round(entry * 0.94, 2)
        target_swing = round(entry * 1.20, 2)
        stop_lt      = round(entry * 0.83, 2)
        target_lt    = round(entry * 1.75, 2)

    # Discipline checks
    no_earnings_risk = earnings_warning is None
    discipline = {
        "not_extended":    l4["score"] >= 10,
        "not_overbought":  l2["score"] >= 10,
        "has_catalyst":    l5["score"] >= 3,
        "stop_defined":    True,
        "smart_money":     l6["score"] >= 5 or not l6["available"],
        "no_earnings_risk": no_earnings_risk,
    }

    return {
        "ticker":    ticker,
        "mode":      mode,
        "score":     score,
        "verdict":   verdict,
        "verdict_class": verdict_class,
        "price_data": price_data,
        "price":     price,
        "earnings_warning": earnings_warning,
        "seasonality_note": seasonality_note,
        "layers": {
            "trend":       l1,
            "momentum":    l2,
            "volume":      l3,
            "structure":   l4,
            "catalyst":    l5,
            "smart_money": l6,
        },
        "technicals": {
            "ema20": ema20, "ema50": ema50, "ema200": ema200,
            "rsi": rsi, "atr": atr,
        },
        "planned_entry": planned,
        "trade_setup": {
            "entry":        entry,
            "stop_swing":   stop_swing,
            "target_swing": target_swing,
            "stop_lt":      stop_lt,
            "target_lt":    target_lt,
            "atr":          atr,
        },
        "fundamentals": fundamentals,
        "news":         news_items[:3],
        "discipline":   discipline,
        "candles":      candles[-50:] if candles else [],
    }


def quick_score(ticker):
    """Fast score using only first 4 layers (for batch scanning)."""
    try:
        candles = get_candles(ticker, days=300)
        price_d = get_live_price(ticker)
        price   = price_d.get("price", 0)
        vol     = price_d.get("volume", 0)
        closes  = [c["c"] for c in candles] if candles else []

        ema20  = _ema(closes, 20)  if len(closes) >= 20  else None
        ema50  = _ema(closes, 50)  if len(closes) >= 50  else None
        ema200 = _ema(closes, 200) if len(closes) >= 200 else None
        rsi    = _rsi(closes, 14)  if len(closes) >= 15  else None

        l1 = layer1_trend(price, ema20, ema50, ema200)
        l2 = layer2_momentum(rsi)
        l3 = layer3_volume(vol, candles)
        l4 = layer4_structure(price, ema20)

        partial = l1["score"] + l2["score"] + l3["score"] + l4["score"]
        max_partial = 90  # 25+25+20+20
        score4 = round(partial / max_partial * 100)

        return {
            "ticker": ticker, "price": price, "score4": score4,
            "rsi": rsi, "ema20": ema20,
            "l1": l1["score"], "l2": l2["score"],
            "l3": l3["score"], "l4": l4["score"],
        }
    except Exception:
        return {"ticker": ticker, "price": 0, "score4": 0, "error": True}
