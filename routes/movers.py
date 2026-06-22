from flask import Blueprint, jsonify, render_template, request
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from collections import Counter

from utils.unusual_whales import (uw_movers_screener, get_market_regime,
                                  get_sector_flow, get_top_flow)
# Reuse breakout's candle fetch + EMA for extension/52w-high — no new data deps.
from routes.breakout import _get_candles, _ema

# NOTE: This codebase now has TWO regime sources — the SPY-vs-EMA200 price gate
# in breakout._get_market_regime(), and the UW options-tide regime used here
# (get_market_regime). Movers intentionally uses the UW tide. These should be
# consolidated into ONE canonical regime function later (tech-debt).

movers_bp = Blueprint('movers', __name__)

# ─── Config — thresholds + screener size (single source of truth) ────────────
MOVERS_CONFIG = {
    'SCREENER_LIMIT':      20,    # how many movers to pull from UW
    'WATCHABLE_EXT_PCT':   5.0,   # within ±5% of a RISING 20-day EMA = WATCHABLE
    'CHASE_EXT_PCT':       8.0,   # >8% above 20-day EMA = CHASE RISK
    'NEAR_52W_PCT':        2.0,   # within 2% of 52w high = CHASE RISK
    'EXPENSIVE_IV_RANK':   80.0,  # CHASE RISK + IV rank >80 = EXTENDED + EXPENSIVE
    'EMA_RISING_LOOKBACK': 5,     # bars back used to judge if the 20-day is rising
    'CACHE_TTL':           300,   # 5 min payload cache
    'REGIME_PERSIST_SEC':  2700,  # tide must hold ~45 min before banner flips (anti-flicker)
}

# Punchy one-line theme read per dominant UW sector.
_THEME_PHRASES = {
    'Technology':             ('chips/AI-infra', 'AI-semiconductor melt-up'),
    'Communication Services': ('mega-cap internet/media', 'communications-led move'),
    'Consumer Cyclical':      ('consumer/retail names', 'risk-on consumer bid'),
    'Consumer Defensive':     ('defensive staples', 'defensive rotation'),
    'Energy':                 ('oil & gas', 'energy/commodity surge'),
    'Financial Services':     ('banks/financials', 'financials-led move'),
    'Healthcare':             ('biotech/healthcare', 'healthcare/biotech pop'),
    'Industrials':            ('industrials', 'industrials-led move'),
    'Basic Materials':        ('materials/miners', 'materials/commodity surge'),
    'Real Estate':            ('REITs/real estate', 'rate-sensitive REIT bid'),
    'Utilities':              ('utilities', 'defensive utility bid'),
}

_movers_cache = {}
# Smoothing buffer for the tide regime so a transient bearish tick can't flip the banner.
_regime_state = {'effective': None, 'pending': None, 'pending_since': None}


def _tide_regime():
    """UW market-tide regime → RISK_OFF / RISK_ON / NEUTRAL, smoothed.
    BULLISH→RISK_ON (no banner), BEARISH→RISK_OFF (banner), NEUTRAL→neutral.
    A new reading must PERSIST for REGIME_PERSIST_SEC before it becomes the
    effective regime shown — avoids intraday flicker on raw ticks. Sampled each
    time the (5-min-cached) payload is rebuilt."""
    try:
        tide = get_market_regime()
    except Exception:
        tide = None
    raw = (tide or {}).get('regime', 'NEUTRAL')
    available = bool((tide or {}).get('available'))
    mapped = {'BULLISH': 'RISK_ON', 'BEARISH': 'RISK_OFF'}.get(raw, 'NEUTRAL')
    if not available:
        mapped = 'NEUTRAL'   # never raise a false RISK_OFF on missing data

    now = datetime.now()
    st = _regime_state
    if st['effective'] is None or mapped == st['effective']:
        st['effective'] = st['effective'] or mapped
        st['pending'] = None
        st['pending_since'] = None
    else:
        if st['pending'] != mapped:
            st['pending'] = mapped
            st['pending_since'] = now
        elif (now - st['pending_since']).total_seconds() >= MOVERS_CONFIG['REGIME_PERSIST_SEC']:
            st['effective'] = mapped
            st['pending'] = None
            st['pending_since'] = None

    return {
        'regime': st['effective'],
        'tide_raw': raw,
        'tide_summary': (tide or {}).get('summary', ''),
        'available': available,
        'pending': st['pending'],
    }


def _state(m):
    """Derive STATE tag. Returns (key, label, color, sort_rank).
    Inverted sort: WATCHABLE(0) calm names on top, CHASE/EXPENSIVE last."""
    ext = m['extension_pct']
    chase = ext > MOVERS_CONFIG['CHASE_EXT_PCT'] or m['near_52w_high']
    if chase and m['iv_rank'] > MOVERS_CONFIG['EXPENSIVE_IV_RANK']:
        return ('EXTENDED_EXPENSIVE', 'EXTENDED + EXPENSIVE', 'red', 3)
    if chase:
        return ('CHASE_RISK', 'CHASE RISK', 'red', 2)
    if (m['perc_change'] > 0 and m['ema20_rising']
            and abs(ext) <= MOVERS_CONFIG['WATCHABLE_EXT_PCT']):
        return ('WATCHABLE', 'WATCHABLE', 'green', 0)
    return ('NEUTRAL', 'NEUTRAL', 'gray', 1)


def _enrich(m):
    """Add extension, 20-day-rising flag, 52w-high proximity from candles."""
    candles = _get_candles(m['ticker'])
    if not candles or len(candles['c']) < 22:
        return None
    closes, highs = candles['c'], candles['h']
    price = closes[-1]
    prev = closes[-2] if len(closes) > 1 else price
    # Gainers already carry screener perc_change; flow rows get a candle-derived one.
    m.setdefault('perc_change', round((price - prev) / prev * 100, 2) if prev else 0.0)

    ema20 = _ema(closes, 20)
    if not ema20:
        return None
    lb = MOVERS_CONFIG['EMA_RISING_LOOKBACK']
    ema20_prev = _ema(closes[:-lb], 20) if len(closes) > 20 + lb else None
    extension_pct = round((price - ema20) / ema20 * 100, 1)

    high52 = max(highs[-252:]) if len(highs) >= 252 else max(highs)
    pct_from_high = round((high52 - price) / high52 * 100, 1) if high52 > 0 else 100.0

    m.update({
        'price': round(price, 2),
        'ema20': round(ema20, 2),
        'ema20_rising': bool(ema20_prev and ema20 > ema20_prev),
        'extension_pct': extension_pct,
        'pct_from_high': pct_from_high,
        'near_52w_high': pct_from_high <= MOVERS_CONFIG['NEAR_52W_PCT'],
    })
    key, label, color, rank = _state(m)
    m.update({'state': key, 'state_label': label, 'state_color': color, '_rank': rank})
    return m


def _theme_summary(movers):
    """Group movers by sector → counts string + dominant-theme headline."""
    counts = Counter(m['sector'] for m in movers if m['sector'])
    total = len(movers)
    if not counts:
        return {'counts_str': '—', 'headline': 'No sector data available.', 'groups': []}

    counts_str = ' · '.join(f'{s}: {c}' for s, c in counts.most_common())
    top_sector, top_count = counts.most_common(1)[0]
    bucket, phrase = _THEME_PHRASES.get(
        top_sector, (top_sector.lower(), f'{top_sector}-led move'))
    if top_count >= max(3, round(total * 0.35)):
        headline = f'{phrase} — {top_count} of {total} movers are {bucket}.'
    else:
        headline = 'Mixed tape — no single sector dominates.'
    return {'counts_str': counts_str, 'headline': headline,
            'groups': [{'sector': s, 'count': c} for s, c in counts.most_common()]}


def _sector_read(sector_flow):
    """One-line rotation read from the sector strip, e.g.
    'Leadership: Technology + Energy · Laggards: Healthcare'."""
    rows = [s for s in (sector_flow or []) if s.get('ticker') != 'SPY']
    rows.sort(key=lambda s: s.get('chg_pct', 0), reverse=True)
    leaders = [s['name'] for s in rows if s.get('chg_pct', 0) > 0.3][:2]
    laggards = [s['name'] for s in rows if s.get('chg_pct', 0) < -0.3][-2:]
    parts = []
    if leaders:
        parts.append('Leadership: ' + ' + '.join(leaders))
    if laggards:
        parts.append('Laggards: ' + ', '.join(reversed(laggards)))
    return ' · '.join(parts) or 'Sectors mixed — no clear leadership today'


def _enrich_flow(item):
    """Apply Movers' extension/state tagging to a performance-flow row so it
    never reads as a buy-list. Falls back to NEUTRAL if candles are unavailable
    (the row is still shown — flow data is independent of candles)."""
    enriched = _enrich(dict(item))
    if enriched:
        return enriched
    item = dict(item)
    item.update({'extension_pct': None, 'ema20_rising': False, 'pct_from_high': None,
                 'near_52w_high': False, 'state': 'NEUTRAL', 'state_label': 'NEUTRAL',
                 'state_color': 'gray', '_rank': 1})
    return item


@movers_bp.route('/movers')
def movers_page():
    return render_template('movers.html', active='movers')


@movers_bp.route('/api/movers')
def api_movers():
    force = request.args.get('force') == '1'
    now = datetime.now()
    cached = _movers_cache.get('payload')
    if cached and not force and (now - cached['ts']).total_seconds() < MOVERS_CONFIG['CACHE_TTL']:
        return jsonify(cached['data'])

    reg = _tide_regime()

    # ── Section 3: top % gainers (existing) ──────────────────────────────────
    raw = uw_movers_screener(MOVERS_CONFIG['SCREENER_LIMIT'])
    with ThreadPoolExecutor(max_workers=6) as ex:
        enriched = [m for m in ex.map(_enrich, raw) if m] if raw else []
    enriched.sort(key=lambda m: (m['_rank'], m['extension_pct']))
    theme = _theme_summary(enriched)

    # ── Sections 1+2: relocated from Scan (same cached UW functions) ─────────
    try:
        sector_flow = get_sector_flow()
    except Exception:
        sector_flow = []
    try:
        perf_raw = get_top_flow(limit=15)
    except Exception:
        perf_raw = []
    with ThreadPoolExecutor(max_workers=6) as ex:
        perf_flow = list(ex.map(_enrich_flow, perf_raw)) if perf_raw else []

    if not enriched and not sector_flow and not perf_flow:
        return jsonify({'error': 'UW data unavailable — check API key', 'movers': [],
                        'theme': None, 'sector_flow': [], 'perf_flow': [], 'sector_read': ''})

    payload = {
        'sector_flow': sector_flow,
        'sector_read': _sector_read(sector_flow),
        'perf_flow': perf_flow,
        'movers': enriched,
        'theme': theme,
        'regime': reg['regime'],            # RISK_OFF / RISK_ON / NEUTRAL (smoothed)
        'tide_raw': reg['tide_raw'],         # raw BULLISH/NEUTRAL/BEARISH this tick
        'tide_summary': reg['tide_summary'],
        'regime_available': reg['available'],
        'count': len(enriched),
        'timestamp': now.isoformat(),
    }
    _movers_cache['payload'] = {'data': payload, 'ts': now}
    return jsonify(payload)
