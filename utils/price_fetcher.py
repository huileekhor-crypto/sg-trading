import time
import requests
from datetime import datetime, timezone, timedelta

SGT = timezone(timedelta(hours=8))


def _ts_sgt(ts):
    """Convert Unix UTC timestamp → SGT time string like '08:45 AM SGT'."""
    if not ts:
        return None
    try:
        return datetime.fromtimestamp(int(ts), tz=SGT).strftime('%I:%M %p SGT')
    except Exception:
        return None


def _ext_block(meta, prefix):
    """Extract pre or post market block from Yahoo Finance meta dict."""
    price = meta.get(f'{prefix}MarketPrice')
    if not price or price <= 0:
        return None
    change = meta.get(f'{prefix}MarketChange', 0) or 0
    pct    = meta.get(f'{prefix}MarketChangePercent', 0) or 0
    ts     = meta.get(f'{prefix}MarketTime')
    return {
        'price':      round(float(price), 2),
        'change':     round(float(change), 2),
        'change_pct': round(float(pct), 2),
        'time':       _ts_sgt(ts),
        'available':  True,
    }


def _candle_post_market(result, regular_ts, prev_close):
    """Extract the last after-hours close from candle data (after regular session end)."""
    try:
        timestamps = result.get('timestamp', [])
        closes     = result['indicators']['quote'][0].get('close', [])
        last_ts = last_c = None
        for ts, c in zip(timestamps, closes):
            if c and c > 0 and ts > regular_ts:
                last_ts, last_c = ts, c
        if not last_c:
            return None
        price  = round(float(last_c), 2)
        change = round(price - prev_close, 2)
        pct    = round((change / prev_close) * 100, 2) if prev_close else 0
        return {'price': price, 'change': change, 'change_pct': pct,
                'time': _ts_sgt(last_ts), 'available': True}
    except Exception:
        return None


def _candle_pre_market(result, regular_open_ts, prev_close):
    """Extract the last pre-market close — only candles in the 6h window before open."""
    try:
        timestamps = result.get('timestamp', [])
        closes     = result['indicators']['quote'][0].get('close', [])
        # Pre-market is 4:00 AM – 9:30 AM ET = 6 hours before regular open at most
        pre_start  = regular_open_ts - 21600
        last_ts = last_c = None
        for ts, c in zip(timestamps, closes):
            if c and c > 0 and pre_start <= ts < regular_open_ts:
                last_ts, last_c = ts, c
        if not last_c:
            return None
        price  = round(float(last_c), 2)
        change = round(price - prev_close, 2)
        pct    = round((change / prev_close) * 100, 2) if prev_close else 0
        return {'price': price, 'change': change, 'change_pct': pct,
                'time': _ts_sgt(last_ts), 'available': True}
    except Exception:
        return None


def get_live_price(ticker):
    try:
        # Use period1/period2 (24-hour window) so after-hours candles are included.
        # range=1d drops AH candles from Yahoo's response.
        now_ts   = int(time.time())
        period1  = now_ts - 86400
        url = (f'https://query1.finance.yahoo.com/v8/finance/chart/{ticker}'
               f'?period1={period1}&period2={now_ts}&interval=5m&includePrePost=true')
        headers = {'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json',
                   'Accept-Encoding': 'identity'}
        res    = requests.get(url, headers=headers, timeout=8)
        data   = res.json()
        result = data['chart']['result'][0]
        meta   = result['meta']

        price      = round(float(meta.get('regularMarketPrice', 0)), 2)
        prev_close = round(float(meta.get('previousClose', 0) or
                                 meta.get('chartPreviousClose', 0)), 2)
        change     = round(price - prev_close, 2)
        change_pct = round((change / prev_close) * 100, 2) if prev_close else 0

        now_sgt = datetime.now(SGT)

        # --- Extended hours from meta (preferred when present) ---
        pre_market  = _ext_block(meta, 'pre') or _ext_block(meta, 'prePre')
        post_market = _ext_block(meta, 'post')

        # --- Fallback: extract from candle data when meta omits them ---
        # This happens overnight when Yahoo strips postMarketPrice from meta.
        regular_ts = meta.get('regularMarketTime', 0)
        trading    = meta.get('currentTradingPeriod', {})
        reg_open   = trading.get('regular', {}).get('start', regular_ts)

        if post_market is None:
            post_market = _candle_post_market(result, regular_ts, prev_close)

        if pre_market is None:
            pm_candle = _candle_pre_market(result, reg_open, prev_close)
            # Only use if the candle is actually from today's pre-market window
            if pm_candle and pm_candle['price'] != price:
                pre_market = pm_candle

        # Determine market state — Yahoo omits marketState when market is overnight
        market_state = meta.get('marketState') or 'CLOSED'

        return {
            'price':         price,
            'change':        change,
            'change_pct':    change_pct,
            'volume':        meta.get('regularMarketVolume', 0),
            'high':          round(float(meta.get('regularMarketDayHigh', 0)), 2),
            'low':           round(float(meta.get('regularMarketDayLow', 0)), 2),
            'open':          round(float(meta.get('regularMarketOpen', 0)), 2),
            'prev_close':    prev_close,
            'market_status': market_state,
            'pre_market':    pre_market,
            'post_market':   post_market,
            'sgt_time':      now_sgt.strftime('%I:%M %p SGT'),
            'source':        'yahoo',
        }
    except Exception:
        return get_finnhub_fallback(ticker)


def get_finnhub_fallback(ticker):
    import finnhub
    from config import Config
    try:
        fc    = finnhub.Client(api_key=Config.FINNHUB_API_KEY)
        q     = fc.quote(ticker)
        price = round(q.get('c', 0), 2)
        prev  = round(q.get('pc', 0), 2)
        return {
            'price':         price,
            'change':        round(price - prev, 2),
            'change_pct':    round(((price - prev) / prev) * 100, 2) if prev else 0,
            'volume':        q.get('v', 0),
            'high':          round(q.get('h', 0), 2),
            'low':           round(q.get('l', 0), 2),
            'open':          round(q.get('o', 0), 2),
            'prev_close':    prev,
            'market_status': 'UNKNOWN',
            'pre_market':    None,
            'post_market':   None,
            'sgt_time':      datetime.now(SGT).strftime('%I:%M %p SGT'),
            'source':        'finnhub',
        }
    except Exception:
        return {'price': 0, 'error': 'Unavailable'}
