import requests
from datetime import datetime


def get_live_price(ticker):
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
        headers = {'User-Agent': 'Mozilla/5.0',
                   'Accept': 'application/json'}
        res = requests.get(url, headers=headers, timeout=5)
        data = res.json()
        meta = data['chart']['result'][0]['meta']

        price      = round(meta.get('regularMarketPrice', 0), 2)
        prev_close = round(meta.get('previousClose', 0), 2)
        change     = round(price - prev_close, 2)
        change_pct = round((change / prev_close) * 100, 2) if prev_close else 0

        return {
            "price":         price,
            "change":        change,
            "change_pct":    change_pct,
            "volume":        meta.get('regularMarketVolume', 0),
            "high":          round(meta.get('regularMarketDayHigh', 0), 2),
            "low":           round(meta.get('regularMarketDayLow', 0), 2),
            "open":          round(meta.get('regularMarketOpen', 0), 2),
            "prev_close":    prev_close,
            "market_status": meta.get('marketState', 'CLOSED'),
            "source":        "yahoo",
        }
    except Exception:
        return get_finnhub_fallback(ticker)


def get_finnhub_fallback(ticker):
    import finnhub
    from config import Config
    try:
        fc = finnhub.Client(api_key=Config.FINNHUB_API_KEY)
        q  = fc.quote(ticker)
        price = round(q.get('c', 0), 2)
        prev  = round(q.get('pc', 0), 2)
        return {
            "price":         price,
            "change":        round(price - prev, 2),
            "change_pct":    round(((price - prev) / prev) * 100, 2) if prev else 0,
            "volume":        q.get('v', 0),
            "high":          round(q.get('h', 0), 2),
            "low":           round(q.get('l', 0), 2),
            "open":          round(q.get('o', 0), 2),
            "prev_close":    prev,
            "market_status": "UNKNOWN",
            "source":        "finnhub",
        }
    except Exception:
        return {"price": 0, "error": "Unavailable"}
