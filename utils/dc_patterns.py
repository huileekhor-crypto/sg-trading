"""Danny Cheng style chart pattern detection — shared between chart and breakout routes."""


# ── EMA helpers ───────────────────────────────────────────────────────────────

def _ema_val(prices, period):
    if len(prices) < period:
        return None
    k   = 2 / (period + 1)
    val = sum(prices[:period]) / period
    for p in prices[period:]:
        val = p * k + val * (1 - k)
    return round(val, 4)


def _ema_series(prices, period):
    n   = len(prices)
    k   = 2 / (period + 1)
    out = [None] * (period - 1)
    val = sum(prices[:period]) / period
    out.append(round(val, 4))
    for p in prices[period:]:
        val = p * k + val * (1 - k)
        out.append(round(val, 4))
    return out


# ── RSI (single value) ────────────────────────────────────────────────────────

def _rsi_val(closes, period=14):
    n = len(closes)
    if n < period + 1:
        return None
    deltas = [closes[i] - closes[i-1] for i in range(1, n)]
    gains  = [d if d > 0 else 0 for d in deltas[-period:]]
    losses = [-d if d < 0 else 0 for d in deltas[-period:]]
    ag, al = sum(gains) / period, sum(losses) / period
    return round(100 - 100 / (1 + ag / al), 1) if al > 0 else 100.0


# ── MCDX Series ───────────────────────────────────────────────────────────────

def calc_mcdx_series(closes, volumes):
    """
    MCDX momentum histogram: blend of OBV momentum, MACD histogram, volume-price momentum.
    Returns list of floats (-100 … +100); None for bars with insufficient history.
    """
    n = len(closes)
    if n < 30:
        return [None] * n

    # OBV
    obv = [0]
    for i in range(1, n):
        d = closes[i] - closes[i - 1]
        obv.append(obv[-1] + (volumes[i] if d > 0 else -volumes[i] if d < 0 else 0))

    # MACD histogram (12/26/9)
    def _es(data, p):
        k = 2 / (p + 1); v = sum(data[:p]) / p; r = [None] * (p - 1); r.append(v)
        for x in data[p:]: v = x * k + v * (1 - k); r.append(v)
        return r

    e12 = _es(closes, 12); e26 = _es(closes, 26)
    ml  = [a - b if a and b else None for a, b in zip(e12, e26)]
    vld = [(i, v) for i, v in enumerate(ml) if v is not None]
    sl  = [None] * n
    if len(vld) >= 9:
        vals = [v for _, v in vld]; k = 2 / 10; sig = sum(vals[:9]) / 9
        sl[vld[8][0]] = sig
        for j in range(9, len(vld)):
            sig = vals[j] * k + sig * (1 - k); sl[vld[j][0]] = sig
    mh = [m - s if m is not None and s is not None else None for m, s in zip(ml, sl)]

    price_range = max(closes) - min(closes) or 1
    result = [None] * n

    for i in range(30, n):
        # OBV rate-of-change (5-bar)
        obv_roc = (obv[i] - obv[i - 5]) / (abs(obv[i - 5]) + 1e-10) if i >= 5 else 0
        obv_n   = max(-1.0, min(1.0, obv_roc * 8))

        # MACD histogram normalised
        macd_n = max(-1.0, min(1.0, mh[i] / (price_range * 0.05 + 1e-10))) if mh[i] is not None else 0

        # Price × volume momentum (5-bar)
        pv = closes[i] * volumes[i]
        pv5 = closes[i - 5] * volumes[i - 5] if i >= 5 and volumes[i - 5] else pv
        pv_roc = (pv - pv5) / (pv5 + 1e-10) if pv5 else 0
        pv_n   = max(-1.0, min(1.0, pv_roc * 5))

        raw = (obv_n * 0.4) + (macd_n * 0.4) + (pv_n * 0.2)
        result[i] = round(raw * 100, 2)

    return result


def _mcdx_signal(mcdx_series):
    """Classify current MCDX state.  Returns (signal_str, value)."""
    vals = [v for v in mcdx_series[-6:] if v is not None]
    if not vals:
        return 'NEUTRAL', 0.0
    cur  = vals[-1]
    prev = vals[-2] if len(vals) >= 2 else cur

    pos_growing_3 = (len(vals) >= 3
                     and all(vals[-(3 - j)] < vals[-(2 - j)] for j in range(2))
                     and cur > 0)
    if pos_growing_3:
        return 'STRONG_BUY', cur
    if cur > 0 and prev <= 0:
        return 'BUY', cur          # just crossed positive
    if cur > 0 and cur > prev:
        return 'BUY', cur
    if cur > 0 and cur <= prev:
        return 'WARNING', cur      # positive but slowing
    if cur <= 0 and prev >= 0:
        return 'SELL', cur         # crossed negative
    if cur < -20:
        return 'SELL', cur
    return 'NEUTRAL', cur


# ── Signal 1: Trend Reversal Candle ──────────────────────────────────────────

def detect_trend_reversal_candle(closes, opens, highs, lows, volumes):
    n = len(closes)
    if n < 22:
        return {'detected': False, 'conditions_met': 0, 'conditions': {}}

    o = opens[-1] if opens and len(opens) == n else closes[-2]
    c, h, l, v = closes[-1], highs[-1], lows[-1], volumes[-1]
    rng = h - l
    if rng <= 0:
        return {'detected': False, 'conditions_met': 0, 'conditions': {}}

    body_low   = min(o, c)
    lower_wick = body_low - l
    close_pos  = (c - l) / rng
    avg20      = sum(volumes[-21:-1]) / 20 if n >= 21 else (sum(volumes[:-1]) / max(n - 1, 1))
    ema20      = _ema_val(closes[:-1], 20)

    cond = {
        'long_lower_wick':  lower_wick / rng > 0.60,
        'closes_upper_40':  close_pos > 0.60,
        'above_ema20':      bool(ema20 and c > ema20),
        'prev_3_bearish':   n >= 4 and all(closes[i] < closes[i - 1] for i in range(-4, -1)),
        'volume_surge':     avg20 > 0 and v / avg20 > 1.5,
    }
    met = sum(cond.values())
    return {
        'detected':          met == 5,
        'conditions_met':    met,
        'conditions':        cond,
        'lower_wick_pct':    round(lower_wick / rng * 100, 1),
        'close_position_pct': round(close_pos * 100, 1),
        'rvol':              round(v / avg20, 2) if avg20 else 0,
    }


# ── Signal 3: Accumulation Base ──────────────────────────────────────────────

def detect_accumulation_base(closes, highs, lows, volumes, lookback=20):
    n  = len(closes)
    lb = min(lookback, n)
    if lb < 5:
        return {'detected': False, 'conditions_met': 0, 'days': lb, 'conditions': {}}

    rc = closes[-lb:]; rh = highs[-lb:]; rl = lows[-lb:]; rv = volumes[-lb:]
    mid = lb // 2

    first_rng  = max(rh[:mid]) - min(rl[:mid]) if mid > 0 else 0
    second_rng = max(rh[mid:]) - min(rl[mid:])
    contracting = second_rng < first_rng * 0.85 if first_rng > 0 else False

    hl_count = sum(1 for i in range(1, lb) if rl[i] > rl[i - 1])
    higher_lows = hl_count >= lb // 3

    vol_first  = sum(rv[:mid]) / mid if mid > 0 else 0
    vol_second = sum(rv[mid:]) / (lb - mid) if lb - mid > 0 else 0
    vol_dec    = vol_second < vol_first * 0.80 if vol_first > 0 else False

    hist_highs = highs[-lb - 20:-lb] if n > lb + 20 else rh
    resistance = max(hist_highs)
    cur        = closes[-1]
    near_res   = resistance > cur and (resistance - cur) / cur < 0.10

    cond = {
        'range_contracting':  contracting,
        'higher_lows':        higher_lows,
        'volume_declining':   vol_dec,
        'near_resistance':    near_res,
        'enough_days':        lb >= 5,
    }
    met = sum(cond.values())
    return {
        'detected':       met >= 3,
        'conditions_met': met,
        'days':           lb,
        'conditions':     cond,
        'resistance':     round(resistance, 2) if near_res else None,
        'contraction_pct': round((1 - second_rng / first_rng) * 100, 1) if first_rng > 0 else 0,
    }


# ── Signal 4: Trend Reversal Confirmed ───────────────────────────────────────

def detect_trend_reversal_confirmed(closes, opens, highs, lows, volumes, mcdx_series=None):
    n = len(closes)
    if n < 30:
        return {'detected': False, 'conditions': {}}

    # Previous downtrend: majority of last 20 highs were lower
    h20 = highs[-21:-1]
    lower_highs = sum(1 for i in range(1, len(h20)) if h20[i] < h20[i - 1])
    prev_downtrend = lower_highs >= len(h20) // 2

    # Breaks above previous 10-day high
    prev_high = max(highs[-11:-1])
    cur       = closes[-1]
    breaks_above = cur > prev_high

    # MCDX positive
    if mcdx_series is None:
        mcdx_series = calc_mcdx_series(closes, volumes)
    _, mcdx_val = _mcdx_signal(mcdx_series)
    mcdx_pos = mcdx_val > 0

    # Volume surge
    avg20    = sum(volumes[-21:-1]) / 20 if n >= 21 else 1
    rvol     = volumes[-1] / avg20 if avg20 > 0 else 1
    vol_ok   = rvol > 2.0

    # Above EMA20 and EMA50
    e20 = _ema_val(closes, 20)
    e50 = _ema_val(closes, min(50, n))
    above = bool(e20 and cur > e20 and e50 and cur > e50)

    cond = {
        'prev_downtrend':     prev_downtrend,
        'breaks_above_high':  breaks_above,
        'mcdx_positive':      mcdx_pos,
        'volume_surge':       vol_ok,
        'above_both_emas':    above,
    }
    return {
        'detected':   all(cond.values()),
        'conditions': cond,
        'prev_high':  round(prev_high, 2),
        'rvol':       round(rvol, 2),
        'mcdx_value': round(mcdx_val, 1),
    }


# ── Signal 5: Breaking Out ────────────────────────────────────────────────────

def detect_breaking_out(closes, highs, lows, volumes, mcdx_series=None):
    n = len(closes)
    if n < 25:
        return {'detected': False, 'conditions': {}}

    cur          = closes[-1]
    resistance   = max(highs[-21:-1])
    breaks_res   = cur > resistance

    avg20 = sum(volumes[-21:-1]) / 20 if n >= 21 else 1
    rvol  = volumes[-1] / avg20 if avg20 > 0 else 1
    vol_ok = rvol > 2.0

    if mcdx_series is None:
        mcdx_series = calc_mcdx_series(closes, volumes)
    sig, mcdx_val = _mcdx_signal(mcdx_series)
    mcdx_ok = sig in ('BUY', 'STRONG_BUY') and mcdx_val > 0

    rsi = _rsi_val(closes) or 50
    rsi_ok = 50 <= rsi <= 75

    cond = {
        'breaks_resistance': breaks_res,
        'volume_surge':      vol_ok,
        'mcdx_accelerating': mcdx_ok,
        'rsi_in_zone':       rsi_ok,
    }
    met = sum(cond.values())
    return {
        'detected':   met >= 3,
        'conditions': cond,
        'resistance': round(resistance, 2),
        'rvol':       round(rvol, 2),
        'rsi':        round(rsi, 1),
        'mcdx_value': round(mcdx_val, 1),
    }


# ── Combined DC Pattern Score ─────────────────────────────────────────────────

def dc_pattern_score(closes, opens, highs, lows, volumes):
    """
    Combined Danny Cheng score 0–100.
    Returns dict with score, signals list, mcdx_series, details.
    """
    mcdx_s            = calc_mcdx_series(closes, volumes)
    mcdx_sig, mcdx_v  = _mcdx_signal(mcdx_s)

    raw     = 0
    signals = []
    details = {}

    # 1. Trend Reversal Candle (+25)
    trc = detect_trend_reversal_candle(closes, opens, highs, lows, volumes)
    details['trend_reversal_candle'] = trc
    if trc['detected']:
        raw += 25
        signals.append({'key': 'trc', 'label': '🔄 Trend Reversal Candle', 'score': 25, 'pass': True,
                        'detail': f"Lower wick {trc['lower_wick_pct']}% of range on {trc['rvol']}× volume"})
    else:
        signals.append({'key': 'trc', 'label': '🔄 Trend Reversal Candle', 'score': 0, 'pass': False,
                        'detail': f"{trc['conditions_met']}/5 conditions — long wick + above EMA20 + vol surge"})

    # 2. MCDX (+20 strong / +15 cross)
    details['mcdx'] = {'signal': mcdx_sig, 'value': round(mcdx_v, 1)}
    if mcdx_sig == 'STRONG_BUY':
        raw += 20
        signals.append({'key': 'mcdx', 'label': '📈 MCDX Momentum', 'score': 20, 'pass': True,
                        'detail': f"MCDX +{round(mcdx_v,1)} — positive and accelerating for 3+ bars"})
    elif mcdx_sig == 'BUY':
        raw += 15
        signals.append({'key': 'mcdx', 'label': '📈 MCDX Momentum', 'score': 15, 'pass': True,
                        'detail': f"MCDX +{round(mcdx_v,1)} — just crossed positive"})
    elif mcdx_sig == 'WARNING':
        signals.append({'key': 'mcdx', 'label': '⚠ MCDX Fading', 'score': 0, 'pass': False,
                        'detail': f"MCDX {round(mcdx_v,1)} — positive but momentum slowing"})
    else:
        signals.append({'key': 'mcdx', 'label': '📈 MCDX Momentum', 'score': 0, 'pass': False,
                        'detail': f"MCDX {round(mcdx_v,1)} — {'sell signal' if mcdx_sig=='SELL' else 'neutral'}"})

    # 3. Accumulation Base (+20 full / +10 partial)
    acc = detect_accumulation_base(closes, highs, lows, volumes)
    details['accumulation_base'] = acc
    if acc['conditions_met'] >= 5:
        raw += 20
        signals.append({'key': 'acc', 'label': '🏗 Accumulation Base', 'score': 20, 'pass': True,
                        'detail': f"{acc['days']}-day base, all 5 conditions — price range contracting with higher lows"})
    elif acc['conditions_met'] >= 3:
        raw += 10
        signals.append({'key': 'acc', 'label': '🏗 Accumulation Base', 'score': 10, 'pass': True,
                        'detail': f"{acc['days']}-day developing base, {acc['conditions_met']}/5 conditions"})
    else:
        signals.append({'key': 'acc', 'label': '🏗 Accumulation Base', 'score': 0, 'pass': False,
                        'detail': f"Only {acc['conditions_met']}/5 base conditions — no clear accumulation yet"})

    # 4. Trend Reversal Confirmed (+30)
    trc_conf = detect_trend_reversal_confirmed(closes, opens, highs, lows, volumes, mcdx_s)
    details['trend_reversal_confirmed'] = trc_conf
    if trc_conf['detected']:
        raw += 30
        signals.append({'key': 'trc_conf', 'label': '🚀 TREND REVERSAL CONFIRMED', 'score': 30, 'pass': True,
                        'detail': f"All 5 conditions met — previous downtrend broken, MCDX positive, volume {trc_conf['rvol']}×"})
    else:
        met = sum(trc_conf['conditions'].values())
        signals.append({'key': 'trc_conf', 'label': '🚀 Trend Reversal Confirmed', 'score': 0, 'pass': False,
                        'detail': f"{met}/5 conditions — need downtrend break + MCDX + 2× volume + above EMAs"})

    # 5. Breaking Out (+25)
    bo = detect_breaking_out(closes, highs, lows, volumes, mcdx_s)
    details['breaking_out'] = bo
    if bo['detected']:
        raw += 25
        signals.append({'key': 'bo', 'label': '🔥 BREAKING OUT', 'score': 25, 'pass': True,
                        'detail': f"Above ${bo['resistance']} resistance on {bo['rvol']}× volume, RSI {bo['rsi']}"})
    else:
        met = sum(bo['conditions'].values())
        signals.append({'key': 'bo', 'label': '🔥 Breaking Out', 'score': 0, 'pass': False,
                        'detail': f"{met}/4 breakout conditions — need resistance break + volume + MCDX + RSI"})

    # Normalise: max possible = 25+20+20+30+25 = 120
    score = min(100, round(raw / 120 * 100))

    if score >= 75:
        label, color = 'HIGH PROBABILITY SETUP', 'green'
    elif score >= 45:
        label, color = 'DEVELOPING SETUP', 'amber'
    else:
        label, color = 'NO CLEAR PATTERN', 'neutral'

    return {
        'score':       score,
        'raw':         raw,
        'label':       label,
        'color':       color,
        'signals':     signals,
        'details':     details,
        'mcdx_series': mcdx_s,
        'mcdx_signal': mcdx_sig,
        'mcdx_value':  round(mcdx_v, 1),
    }


# ── Historical signal markers (for chart overlay) ────────────────────────────

def detect_historical_signals(closes, opens, highs, lows, volumes, n_visible=90):
    """
    Fast O(n) scan for TRC and Breaking-Out markers over the last n_visible candles.
    Returns list of {index, type, price, emoji}.
    """
    n       = len(closes)
    mcdx_s  = calc_mcdx_series(closes, volumes)
    ema20_s = _ema_series(closes, 20)
    start   = max(22, n - n_visible)
    markers = []

    for i in range(start, n):
        idx = i - (n - n_visible)   # index within the visible window
        o   = opens[i] if opens and len(opens) == n else closes[i - 1]
        c, h, l, v = closes[i], highs[i], lows[i], volumes[i]
        rng = h - l
        if rng <= 0:
            continue

        avg_v = sum(volumes[max(0, i - 20):i]) / 20 if i >= 20 else (sum(volumes[:i]) / max(i, 1))
        ema20 = ema20_s[i]

        # ─ Trend Reversal Candle ─────────────────────────────────────────────
        body_low   = min(o, c)
        lower_wick = body_low - l
        close_pos  = (c - l) / rng
        prev_bear  = i >= 4 and all(closes[j] < closes[j - 1] for j in range(i - 3, i + 1))
        trc_ok = (lower_wick / rng > 0.60 and close_pos > 0.60
                  and bool(ema20 and c > ema20) and prev_bear
                  and avg_v > 0 and v / avg_v > 1.5)
        if trc_ok:
            markers.append({'index': idx, 'type': 'trc', 'price': round(c, 2), 'emoji': '🔄'})
            continue

        # ─ Breaking Out ───────────────────────────────────────────────────────
        if i >= 21:
            res20  = max(highs[i - 21:i])
            mcdx_v = mcdx_s[i]
            bo_ok  = (c > res20 and avg_v > 0 and v / avg_v > 2.0
                      and mcdx_v is not None and mcdx_v > 0)
            if bo_ok:
                markers.append({'index': idx, 'type': 'bo', 'price': round(c, 2), 'emoji': '🔥'})

    return markers
