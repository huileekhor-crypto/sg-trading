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


def get_live_price(ticker):
    try:
        # prePost=true returns extended-hours fields in meta
        url = (f'https://query1.finance.yahoo.com/v8/finance/chart/{ticker}'
               f'?prePost=true&interval=1m&range=1d')
        headers = {'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json'}
        res  = requests.get(url, headers=headers, timeout=6)
        data = res.json()
        meta = data['chart']['result'][0]['meta']

        price      = round(float(meta.get('regularMarketPrice', 0)), 2)
        prev_close = round(float(meta.get('previousClose', 0) or
                                 meta.get('chartPreviousClose', 0)), 2)
        change     = round(price - prev_close, 2)
        change_pct = round((change / prev_close) * 100, 2) if prev_close else 0

        now_sgt = datetime.now(SGT)

        return {
            # Regular session
            'price':         price,
            'change':        change,
            'change_pct':    change_pct,
            'volume':        meta.get('regularMarketVolume', 0),
            'high':          round(float(meta.get('regularMarketDayHigh', 0)), 2),
            'low':           round(float(meta.get('regularMarketDayLow', 0)), 2),
            'open':          round(float(meta.get('regularMarketOpen', 0)), 2),
            'prev_close':    prev_close,
            'market_status': meta.get('marketState', 'CLOSED'),
            # Extended hours (try 'pre'/'prePre' and 'post')
            'pre_market':    _ext_block(meta, 'pre') or _ext_block(meta, 'prePre'),
            'post_market':   _ext_block(meta, 'post'),
            # SGT context
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
