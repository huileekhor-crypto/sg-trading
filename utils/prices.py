import requests
import time
import os

_price_cache = {}  # {ticker: {data, ts}}
PRICE_TTL = 8      # seconds

def get_live_price(ticker):
    """Yahoo Finance live price — includes pre/post market."""
    key = f"price:{ticker}"
    now = time.time()
    if key in _price_cache and now - _price_cache[key]['ts'] < PRICE_TTL:
        return _price_cache[key]['data']

    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
        r = requests.get(url, params={"prePost": "true", "interval": "1m", "range": "1d"},
                         headers={"User-Agent": "Mozilla/5.0"}, timeout=5)
        d = r.json()
        meta = d["chart"]["result"][0]["meta"]
        price = meta.get("regularMarketPrice") or meta.get("previousClose", 0)
        prev  = meta.get("chartPreviousClose") or meta.get("previousClose", price)
        pre_price  = meta.get("preMarketPrice")
        post_price = meta.get("postMarketPrice")
        mkt_state  = meta.get("marketState", "CLOSED")  # REGULAR, PRE, POST, CLOSED

        change     = price - prev
        change_pct = (change / prev * 100) if prev else 0

        result = {
            "ticker":      ticker,
            "price":       round(price, 2),
            "prev_close":  round(prev, 2),
            "change":      round(change, 2),
            "change_pct":  round(change_pct, 2),
            "pre_price":   round(pre_price, 2) if pre_price else None,
            "post_price":  round(post_price, 2) if post_price else None,
            "market_state": mkt_state,
            "currency":    meta.get("currency", "USD"),
            "volume":      meta.get("regularMarketVolume", 0),
        }
        _price_cache[key] = {"data": result, "ts": now}
        return result
    except Exception:
        return {"ticker": ticker, "price": 0, "change": 0, "change_pct": 0,
                "prev_close": 0, "pre_price": None, "post_price": None,
                "market_state": "CLOSED", "volume": 0, "error": True}


_candle_cache = {}
CANDLE_TTL = 300  # 5 min

def get_candles(ticker, days=300):
    """Daily OHLCV candles — yfinance primary, Finnhub fallback.
    Returns list of {t, o, h, l, c, v} sorted oldest-first."""
    key = f"candles:{ticker}:{days}"
    now = time.time()
    if key in _candle_cache and now - _candle_cache[key]['ts'] < CANDLE_TTL:
        return _candle_cache[key]['data']

    # Primary: yfinance handles Yahoo auth automatically, free, full history
    try:
        import yfinance as yf
        period = "2y" if days >= 500 else "1y" if days >= 250 else "6mo"
        hist = yf.Ticker(ticker).history(period=period)
        if not hist.empty:
            candles = [
                {
                    "t": int(ts.timestamp()),
                    "o": round(float(row.Open),  4),
                    "h": round(float(row.High),  4),
                    "l": round(float(row.Low),   4),
                    "c": round(float(row.Close), 4),
                    "v": int(row.Volume),
                }
                for ts, row in hist.iterrows()
            ]
            _candle_cache[key] = {"data": candles, "ts": now}
            return candles
    except Exception:
        pass

    # Fallback: Finnhub (free tier may 403, but worth trying)
    finnhub_key = os.environ.get("FINNHUB_API_KEY", "")
    if finnhub_key:
        try:
            end   = int(now)
            start = end - days * 86400
            r = requests.get("https://finnhub.io/api/v1/stock/candle", params={
                "symbol": ticker, "resolution": "D",
                "from": start, "to": end, "token": finnhub_key
            }, timeout=10)
            d = r.json()
            if d.get("s") == "ok" and d.get("c"):
                candles = [
                    {"t": d["t"][i], "o": d["o"][i], "h": d["h"][i],
                     "l": d["l"][i], "c": d["c"][i], "v": d["v"][i]}
                    for i in range(len(d["c"]))
                ]
                _candle_cache[key] = {"data": candles, "ts": now}
                return candles
        except Exception:
            pass

    return []


_fund_cache = {}
FUND_TTL = 3600  # 1 hour

def get_fundamentals(ticker):
    """Fundamentals via yfinance — P/E, revenue growth, margins, 52wk."""
    key = f"fund:{ticker}"
    now = time.time()
    if key in _fund_cache and now - _fund_cache[key]['ts'] < FUND_TTL:
        return _fund_cache[key]['data']

    try:
        import yfinance as yf
        info = yf.Ticker(ticker).info
        result = {
            "pe_ratio":        info.get("trailingPE"),
            "forward_pe":      info.get("forwardPE"),
            "peg":             info.get("pegRatio"),
            "revenue_growth":  info.get("revenueGrowth"),
            "earnings_growth": info.get("earningsGrowth"),
            "gross_margins":   info.get("grossMargins"),
            "profit_margins":  info.get("profitMargins"),
            "market_cap":      info.get("marketCap"),
            "52wk_high":       info.get("fiftyTwoWeekHigh"),
            "52wk_low":        info.get("fiftyTwoWeekLow"),
            "short_float":     info.get("shortPercentOfFloat"),
            "beta":            info.get("beta"),
            "sector":          info.get("sector", ""),
            "industry":        info.get("industry", ""),
            "name":            info.get("longName", ticker),
        }
        _fund_cache[key] = {"data": result, "ts": now}
        return result
    except Exception:
        return {}


def get_news(ticker, count=5):
    """Finnhub company news — last 7 days."""
    finnhub_key = os.environ.get("FINNHUB_API_KEY", "")
    if not finnhub_key:
        return []
    try:
        import datetime
        to_date   = datetime.date.today().isoformat()
        from_date = (datetime.date.today() - datetime.timedelta(days=7)).isoformat()
        url = "https://finnhub.io/api/v1/company-news"
        r = requests.get(url, params={
            "symbol": ticker, "from": from_date, "to": to_date, "token": finnhub_key
        }, timeout=8)
        news = r.json()
        if isinstance(news, list):
            return news[:count]
        return []
    except Exception:
        return []
