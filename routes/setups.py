from flask import Blueprint, jsonify, render_template, request
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

from utils.unusual_whales import uw_iv_ranks, uw_days_to_earnings
# Reuse breakout's candle fetch + indicators — no new data deps.
from routes.breakout import _get_candles, _ema, _rsi
# REGIME CONSOLIDATION DEBT: there are two regime definitions in this codebase —
# the SPY-vs-EMA200 gate in breakout._get_market_regime() and the UW options-tide
# regime in Movers. Setups intentionally reuses Movers' smoothed tide regime so the
# two discovery tabs stay consistent. These should be unified into ONE canonical
# regime function later; importing _tide_regime here is the interim shared source.
from routes.movers import _tide_regime

setups_bp = Blueprint('setups', __name__)

# ─── Config — every threshold lives here (single source of truth) ────────────
SETUPS_CONFIG = {
    'PULLBACK_EMA_PCT':    3.0,   # within ±3% of a rising 20/50 EMA = pullback
    'NEAR_52W_PCT':        5.0,   # exclude names within 5% of 52w high (that's Breakout)
    'UP_TODAY_MAX_PCT':    4.0,   # exclude names already up >4% today (no longer resting)
    'RSI_MAX':             65,    # exclude RSI >65 (too hot for a setup)
    'RSI_PULLBACK_LO':     40,    # pullback RSI band low
    'RSI_PULLBACK_HI':     55,    # pullback RSI band high
    'ATR_CONTRACTION':     0.60,  # recent range < 60% of 20d avg range = coiled
    'EXPENSIVE_IV_RANK':   80,    # IV rank >80 = expensive / event-risk flag
    'MIN_RR':              2.0,   # flag any setup with R/R below this
    'EARNINGS_WARN_DAYS':  7,     # flag earnings within this many days
    'STOP_ATR_MULT':       1.5,   # stop = support - 1.5 * ATR
    'EMA_RISING_LOOKBACK': 5,     # bars back to judge if an EMA is rising
    'CACHE_TTL':           600,   # 10 min payload cache
}

# Default liquid swing universe (~40 names). Override per request with ?tickers=A,B,C
SETUPS_UNIVERSE = [
    'NVDA', 'MSFT', 'AAPL', 'AMZN', 'META', 'GOOGL', 'AVGO', 'AMD', 'TSM', 'ARM',
    'MU', 'QCOM', 'TXN', 'AMAT', 'LRCX', 'KLAC', 'ASML', 'ORCL', 'CRM', 'NOW',
    'ADBE', 'PANW', 'CRWD', 'SNOW', 'NFLX', 'TSLA', 'UBER', 'SHOP', 'PLTR', 'COIN',
    'JPM', 'GS', 'V', 'MA', 'COST', 'LLY', 'UNH', 'CAT', 'GE', 'DE',
]

_setups_cache = {}


def _atr(highs, lows, closes, period=14):
    trs = [max(highs[i] - lows[i],
               abs(highs[i] - closes[i - 1]),
               abs(lows[i] - closes[i - 1]))
           for i in range(1, len(closes))]
    if len(trs) < period:
        return None
    return sum(trs[-period:]) / period


def _analyse(ticker):
    """Price/structure-only setup detection. Returns:
      - setup dict (qualifies)
      - {'_skip': reason, 'ticker': t}  (data missing — reported, never fabricated)
      - None  (evaluated fine but not a setup)"""
    C = SETUPS_CONFIG
    candles = _get_candles(ticker, period='1y')
    if not candles or len(candles['c']) < 200:
        return {'_skip': 'insufficient price history (<200 bars)', 'ticker': ticker}

    closes, highs, lows, vols = candles['c'], candles['h'], candles['l'], candles['v']
    price = closes[-1]
    prev = closes[-2]
    pct_today = round((price - prev) / prev * 100, 2) if prev else 0.0

    ema20, ema50, ema200 = _ema(closes, 20), _ema(closes, 50), _ema(closes, 200)
    rsi = _rsi(closes)
    atr = _atr(highs, lows, closes)
    if None in (ema20, ema50, ema200, rsi, atr):
        return {'_skip': 'indicator computation failed', 'ticker': ticker}

    lb = C['EMA_RISING_LOOKBACK']
    ema20_prev = _ema(closes[:-lb], 20)
    ema50_prev = _ema(closes[:-lb], 50)
    ema20_rising = bool(ema20_prev and ema20 > ema20_prev)
    ema50_rising = bool(ema50_prev and ema50 > ema50_prev)

    # ── TREND GATE: only buy dips in confirmed uptrends ──────────────────────
    if not (price > ema50 and ema50 > ema200 and ema50_rising):
        return None

    high52 = max(highs[-252:]) if len(highs) >= 252 else max(highs)
    pct_from_high = round((high52 - price) / high52 * 100, 1) if high52 > 0 else 100.0

    # ── EXCLUSIONS: keep this the EARLY (resting) list ───────────────────────
    if pct_from_high <= C['NEAR_52W_PCT']:   # too close to highs → Breakout territory
        return None
    if pct_today > C['UP_TODAY_MAX_PCT']:    # running today → not resting
        return None
    if rsi > C['RSI_MAX']:                   # too hot
        return None

    dist20 = round((price - ema20) / ema20 * 100, 1)
    dist50 = round((price - ema50) / ema50 * 100, 1)

    # ── SETUP 1: PULLBACK to a rising 20/50 EMA with cooled RSI ──────────────
    pullback = (
        ((ema20_rising and abs(dist20) <= C['PULLBACK_EMA_PCT'])
         or (ema50_rising and abs(dist50) <= C['PULLBACK_EMA_PCT']))
        and C['RSI_PULLBACK_LO'] <= rsi <= C['RSI_PULLBACK_HI']
    )

    # ── SETUP 2: COILED — volatility contraction + volume drying ─────────────
    rng = [highs[i] - lows[i] for i in range(len(highs))]
    recent_avg = sum(rng[-5:]) / 5
    base_avg = sum(rng[-20:]) / 20
    contraction = (recent_avg / base_avg) if base_avg > 0 else 1.0
    vol_drying = (sum(vols[-5:]) / 5) < (sum(vols[-20:]) / 20) if len(vols) >= 20 else False
    coiled = contraction < C['ATR_CONTRACTION'] and vol_drying

    if not (pullback or coiled):
        return None

    tags = (['PULLBACK'] if pullback else []) + (['COILED'] if coiled else [])
    setup_label = 'BOTH' if len(tags) == 2 else tags[0]

    # ── PROPOSED PLAN — entry at support (alert level), ATR stop, prior-high target ──
    if pullback and ema20_rising and abs(dist20) <= C['PULLBACK_EMA_PCT']:
        support, support_lbl = ema20, '20 EMA'
    elif pullback and ema50_rising and abs(dist50) <= C['PULLBACK_EMA_PCT']:
        support, support_lbl = ema50, '50 EMA'
    else:
        support = ema20 if ema20_rising else ema50
        support_lbl = '20 EMA' if ema20_rising else '50 EMA'

    entry = round(support, 2)
    stop = round(support - C['STOP_ATR_MULT'] * atr, 2)
    target = round(high52, 2)
    risk, reward = entry - stop, target - entry
    rr = round(reward / risk, 2) if risk > 0 else 0.0
    rr_ok = rr >= C['MIN_RR']

    # ── Quality score (price-derived; UW penalties applied later) ────────────
    slope50 = ((ema50 - ema50_prev) / ema50_prev * 100) if ema50_prev else 0
    trend_score = min(30, 12 + max(0, slope50 * 6))
    dist_support_abs = min(abs(dist20), abs(dist50))
    setup_score = 0.0
    if pullback:
        rsi_fit = max(0.0, 1 - abs(rsi - 47.5) / 7.5)
        prox = 1 - min(dist_support_abs, C['PULLBACK_EMA_PCT']) / C['PULLBACK_EMA_PCT']
        setup_score = max(setup_score, 15 + 15 * prox + 10 * rsi_fit)
    if coiled:
        tight = 1 - min(contraction, C['ATR_CONTRACTION']) / C['ATR_CONTRACTION']
        setup_score = max(setup_score, 20 + 20 * tight)
    if pullback and coiled:
        setup_score += 5
    setup_score = min(45, setup_score)
    rr_score = min(25, max(0, (rr - 1) * 12.5))
    base_score = round(min(100, trend_score + setup_score + rr_score))

    why = []
    if pullback:
        why.append(f'Pulled back to {support_lbl} (RSI {rsi}) in a rising uptrend')
    if coiled:
        why.append(f'Range compressed to {round(contraction * 100)}% of 20d avg, volume drying')
    why.append(f'{pct_from_high}% below 52w high — room to run')

    return {
        'ticker': ticker, 'price': round(price, 2),
        'tags': tags, 'setup_label': setup_label,
        'dist20': dist20, 'dist50': dist50,
        'rsi': rsi, 'atr': round(atr, 2), 'atr_pct': round(atr / price * 100, 2),
        'ema20_rising': ema20_rising, 'ema50_rising': ema50_rising,
        'pct_from_high': pct_from_high, 'pct_today': pct_today,
        'support_lbl': support_lbl,
        'entry': entry, 'stop': stop, 'target': target, 'rr': rr, 'rr_ok': rr_ok,
        'score': base_score, 'why': ' · '.join(why),
        'iv_rank': 0, 'sector': '', 'earnings_days': None, 'flags': [],
    }


@setups_bp.route('/setups')
def setups_page():
    return render_template('setups.html', active='setups')


@setups_bp.route('/api/setups')
def api_setups():
    C = SETUPS_CONFIG
    force = request.args.get('force') == '1'
    tickers_arg = request.args.get('tickers', '')
    universe = ([t.strip().upper() for t in tickers_arg.split(',') if t.strip()]
                or SETUPS_UNIVERSE)

    cache_key = ','.join(sorted(universe))
    now = datetime.now()
    cached = _setups_cache.get(cache_key)
    if cached and not force and (now - cached['ts']).total_seconds() < C['CACHE_TTL']:
        return jsonify(cached['data'])

    reg = _tide_regime()  # shared smoothed UW tide regime (see consolidation note above)

    with ThreadPoolExecutor(max_workers=6) as ex:
        evaluated = list(ex.map(_analyse, universe))

    setups = [r for r in evaluated if r and '_skip' not in r]
    skipped = [{'ticker': r['ticker'], 'reason': r['_skip']}
               for r in evaluated if r and '_skip' in r]

    # ── Optional secondary confirm: IV rank (1 call) + earnings (qualifiers only) ──
    iv_map = uw_iv_ranks([s['ticker'] for s in setups]) if setups else {}

    def _earn(s):
        s['earnings_days'] = uw_days_to_earnings(s['ticker'])
        return s
    if setups:
        with ThreadPoolExecutor(max_workers=4) as ex:
            setups = list(ex.map(_earn, setups))

    for s in setups:
        info = iv_map.get(s['ticker'], {})
        s['iv_rank'] = info.get('iv_rank', 0)
        s['sector'] = info.get('sector', '')
        score = s['score']
        flags = []
        if s['iv_rank'] and s['iv_rank'] > C['EXPENSIVE_IV_RANK']:
            flags.append(f"IV rank {s['iv_rank']:.0f} — expensive, possible event near, caution")
            score -= 5
        ed = s['earnings_days']
        if ed is not None and ed <= C['EARNINGS_WARN_DAYS']:
            flags.append(f"Earnings in {ed}d — earnings risk, avoid or size down")
            score -= 8
        if not s['rr_ok']:
            flags.append(f"R/R {s['rr']} below {C['MIN_RR']:.0f} — weak reward, reconsider")
            score -= 10
        s['flags'] = flags
        s['score'] = max(0, score)

    setups.sort(key=lambda s: s['score'], reverse=True)

    payload = {
        'setups': setups,
        'skipped': skipped,
        'regime': reg['regime'],
        'tide_raw': reg['tide_raw'],
        'scanned': len(universe),
        'found': len(setups),
        'timestamp': now.isoformat(),
    }
    _setups_cache[cache_key] = {'data': payload, 'ts': now}
    return jsonify(payload)
