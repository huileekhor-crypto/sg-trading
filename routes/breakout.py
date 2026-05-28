from flask import Blueprint, request, jsonify
import yfinance as yf
from config import Config
from datetime import datetime, timedelta

breakout_bp = Blueprint('breakout', __name__)
_breakout_cache = {}
CACHE_TTL = 1800  # 30 minutes

TOP_MOMENTUM_STOCKS = [
    'NVDA', 'MSFT', 'META', 'GOOGL', 'AMZN', 'AAPL', 'TSM', 'AVGO',
    'AMD', 'IONQ', 'QBTS', 'RGTI', 'PLTR', 'MSTR', 'TSLA', 'CRM',
    'NFLX', 'ORCL', 'DELL', 'ARM',
]


def _get_candles(ticker, days=260):
    end   = datetime.now()
    start = end - timedelta(days=days)
    df = yf.download(ticker, start=start.strftime('%Y-%m-%d'),
                     end=end.strftime('%Y-%m-%d'), progress=False, auto_adjust=True)
    if df.empty:
        return None
    if hasattr(df.columns, 'levels'):
        df.columns = df.columns.droplevel(1)
    return {
        'c': df['Close'].tolist(),
        'h': df['High'].tolist(),
        'l': df['Low'].tolist(),
        'v': df['Volume'].tolist(),
    }


def _ema(prices, period):
    if len(prices) < period:
        return None
    k   = 2 / (period + 1)
    val = sum(prices[:period]) / period
    for p in prices[period:]:
        val = p * k + val * (1 - k)
    return round(val, 4)


def _rsi(prices, period=14):
    if len(prices) < period + 1:
        return None
    deltas = [prices[i] - prices[i - 1] for i in range(1, len(prices))]
    gains  = [d if d > 0 else 0 for d in deltas[-period:]]
    losses = [-d if d < 0 else 0 for d in deltas[-period:]]
    ag, al = sum(gains) / period, sum(losses) / period
    if al == 0:
        return 100.0
    return round(100 - 100 / (1 + ag / al), 1)


def _score_ticker(ticker):
    candles = _get_candles(ticker)
    if not candles or len(candles['c']) < 22:
        return None

    closes  = candles['c']
    highs   = candles['h']
    lows    = candles['l']
    volumes = candles['v']
    price   = closes[-1]
    prev    = closes[-2] if len(closes) > 1 else price
    pct_chg = round(((price - prev) / prev) * 100, 2)

    signals = []

    # ── 1. Volume Contraction Score (0-30) ──────────────────────────────
    vol_score = 0
    avg20     = sum(volumes[-20:]) / 20

    recent_v = volumes[-5:]
    dec_days  = sum(1 for i in range(1, len(recent_v)) if recent_v[i] < recent_v[i - 1])
    if dec_days >= 3:
        vol_score += 15
        signals.append(f'Volume declining {dec_days} days')
    elif dec_days >= 2:
        vol_score += 8

    if avg20 > 0:
        ratio = volumes[-1] / avg20
        if ratio < 0.5:
            vol_score += 15
            signals.append(f'Vol {round(ratio*100)}% of 20-day avg')
        elif ratio < 0.75:
            vol_score += 8

    vol_score = min(vol_score, 30)

    # ── 2. Price Tightening Score (0-30) ────────────────────────────────
    price_score = 0
    ranges5 = [highs[i] - lows[i] for i in range(-5, 0) if abs(i) <= len(highs)]

    if len(ranges5) >= 3:
        tightening = sum(1 for i in range(1, len(ranges5)) if ranges5[i] < ranges5[i - 1])
        if tightening >= 3:
            price_score += 15
            signals.append('Range tightening 3+ days')
        elif tightening >= 2:
            price_score += 8
            signals.append('Range tightening')

    high52 = max(highs[-252:]) if len(highs) >= 252 else max(highs)
    pct_from_high = round(((high52 - price) / high52) * 100, 1) if high52 > 0 else 100
    if pct_from_high <= 3:
        price_score += 15
        signals.append(f'Within {pct_from_high}% of 52wk high')
    elif pct_from_high <= 8:
        price_score += 8
        signals.append(f'{pct_from_high}% from 52wk high')

    price_score = min(price_score, 30)

    # ── 3. RSI Launch Zone Score (0-20) ─────────────────────────────────
    rsi       = _rsi(closes)
    rsi_score = 0
    if rsi is not None:
        if 45 <= rsi <= 65:
            rsi_score = 20
            signals.append(f'RSI {rsi} — launch zone')
        elif (35 <= rsi < 45) or (65 < rsi <= 75):
            rsi_score = 10

    # ── 4. Structure Score (0-20) ────────────────────────────────────────
    struct_score = 0
    recent_lows  = lows[-5:] if len(lows) >= 5 else lows
    if len(recent_lows) >= 3 and all(recent_lows[i] > recent_lows[i - 1] for i in range(1, len(recent_lows))):
        struct_score += 10
        signals.append('Higher lows forming')

    ema50 = _ema(closes, 50)
    if ema50 and price > ema50:
        struct_score += 10
        signals.append(f'Above 50 EMA (${round(ema50, 2)})')

    total = vol_score + price_score + rsi_score + struct_score
    if total < 40:
        return None

    # Alert level
    if total >= 80:
        level, color, emoji = 'IMMINENT', 'red',  '🚨'
    elif total >= 60:
        level, color, emoji = 'WATCH',    'amber', '⚠'
    else:
        level, color, emoji = 'RADAR',    'cyan',  '👁'

    # Entry / stop / target via ATR
    trs    = [max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
              for i in range(1, len(closes))]
    atr    = round(sum(trs[-14:]) / 14, 4) if len(trs) >= 14 else price * 0.025
    entry  = round(price, 2)
    stop   = round(price - 1.5 * atr, 2)
    target = round(price + 3.0 * atr, 2)
    rr     = round((target - entry) / (entry - stop), 1) if entry != stop else 0

    # Plain-English explanation
    why_parts = []
    if vol_score >= 15:
        why_parts.append('volume contracting — the stock is coiling' if dec_days >= 3
                         else 'unusually quiet volume below 20-day average')
    if price_score >= 15:
        if pct_from_high <= 3:
            why_parts.append(f'price pressing within {pct_from_high}% of 52-week high')
        elif tightening >= 3 if 'tightening' in locals() else False:
            why_parts.append('daily range tightening for 3+ consecutive days')
    if rsi_score == 20:
        why_parts.append(f'RSI at {rsi} is in the ideal pre-breakout zone (45-65)')
    if 'Higher lows forming' in signals:
        why_parts.append('higher lows show buyers stepping in at higher prices')

    if not why_parts and signals:
        why_parts = [s.lower() for s in signals[:2]]
    why = '. '.join(p.capitalize() for p in why_parts[:2]).rstrip('.') + '.' if why_parts else \
          'Multiple technical signals aligning for a potential breakout.'

    return {
        'ticker':     ticker,
        'score':      total,
        'alert_level':level,
        'alert_color':color,
        'alert_emoji':emoji,
        'price':      round(price, 2),
        'price_change':pct_chg,
        'pct_from_high':pct_from_high,
        'signals':    signals,
        'score_breakdown': {
            'volume':    vol_score,
            'price':     price_score,
            'rsi':       rsi_score,
            'structure': struct_score,
        },
        'entry':  f'${entry}',
        'stop':   f'${stop}',
        'target': f'${target}',
        'rr':     rr,
        'rsi':    rsi,
        'why':    why,
    }


def _scan_list(tickers):
    now     = datetime.now()
    results = []
    for ticker in tickers:
        cached = _breakout_cache.get(ticker)
        if cached and (now - cached['ts']).total_seconds() < CACHE_TTL:
            if cached['data']:
                results.append(cached['data'])
            continue
        try:
            r = _score_ticker(ticker)
            _breakout_cache[ticker] = {'data': r, 'ts': now}
            if r:
                results.append(r)
        except Exception:
            pass
    results.sort(key=lambda x: x['score'], reverse=True)

    # Fire email alerts for any IMMINENT result not sent in the last 24 h
    if Config.EMAIL_SENDER and Config.EMAIL_PASSWORD:
        try:
            from utils.emailer import send_breakout_alert
            from models.alerts import get_active_recipients, was_recently_alerted, mark_alerted
            recipients = get_active_recipients()
            if recipients:
                for stock in results:
                    if stock['score'] >= 80 and not was_recently_alerted(stock['ticker']):
                        send_breakout_alert(stock, recipients)
                        mark_alerted(stock['ticker'])
        except Exception:
            pass  # Never let email failure break the scan response

    return results


@breakout_bp.route('/breakout/scan', methods=['POST'])
def scan_breakouts():
    body    = request.get_json() or {}
    tickers = [t.upper().strip() for t in body.get('tickers', []) if t.strip()]
    if not tickers:
        return jsonify({'error': 'No tickers provided'}), 400
    tickers = tickers[:30]

    results = _scan_list(tickers)
    return jsonify({
        'results':   results,
        'scanned':   len(tickers),
        'found':     len(results),
        'timestamp': datetime.now().isoformat(),
    })


@breakout_bp.route('/breakout/top', methods=['GET'])
def top_breakouts():
    results = _scan_list(TOP_MOMENTUM_STOCKS)
    return jsonify({
        'results':   results[:5],
        'scanned':   len(TOP_MOMENTUM_STOCKS),
        'found':     len(results),
        'timestamp': datetime.now().isoformat(),
    })
