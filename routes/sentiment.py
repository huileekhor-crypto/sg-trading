from flask import Blueprint, request, jsonify
import requests
import json
import re
from datetime import datetime, timedelta, timezone
import anthropic
from config import Config

sentiment_bp = Blueprint('sentiment', __name__)
_sentiment_cache = {}   # per-ticker StockTwits+AI result, 15 min
_claude_cache    = {}   # per-ticker Claude AI result,      30 min
_trending_cache  = {}   # global trending list,              5 min

SENTIMENT_TTL = 900
CLAUDE_TTL    = 1800
TRENDING_TTL  = 300

_ST_HEADERS = {
    'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                   'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36'),
    'Accept': 'application/json',
}


def _parse_dt(s):
    try:
        dt = datetime.fromisoformat(s)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _fetch_st(ticker):
    """Fetch last ~30 StockTwits messages for ticker."""
    # Strip exchange suffix for StockTwits (AAPL.SI → AAPL)
    t = ticker.split('.')[0]
    try:
        res = requests.get(
            f'https://api.stocktwits.com/api/2/streams/symbol/{t}.json',
            headers=_ST_HEADERS, timeout=6)
        if res.status_code == 200:
            return res.json()
    except Exception:
        pass
    return None


def _score_stocktwits(data):
    """Derive sentiment metrics + scores from StockTwits API response."""
    if not data:
        return None
    msgs = data.get('messages', [])
    if not msgs:
        return {
            'bullish_count': 0, 'bearish_count': 0,
            'total_tagged': 0, 'sentiment_ratio': 50,
            'recent_1h': 0, 'vol_spike': 0.0, 'trending': False,
            'sentiment_score': 0, 'volume_score': 0, 'score': 0,
            'emoji': '😐', 'label': 'No Data',
        }

    # Sentiment counts
    def _basic(m):
        s = m.get('sentiment')
        return (s or {}).get('basic') if isinstance(s, dict) else None

    bullish = sum(1 for m in msgs if _basic(m) == 'Bullish')
    bearish = sum(1 for m in msgs if _basic(m) == 'Bearish')
    tagged  = bullish + bearish
    ratio   = round(bullish / tagged * 100) if tagged else 50

    # Volume — count messages in last 1h vs estimated baseline
    now_utc = datetime.now(timezone.utc)
    recent_1h = sum(
        1 for m in msgs
        if (dt := _parse_dt(m.get('created_at', ''))) and
           (now_utc - dt).total_seconds() < 3600
    )
    BASELINE_HOURLY = 4.0
    vol_spike = round(recent_1h / BASELINE_HOURLY, 1)
    trending  = vol_spike >= 2.0

    # Volume score (0-20)
    if   vol_spike >= 3.0: vs = 20
    elif vol_spike >= 2.0: vs = 12
    elif vol_spike >= 1.5: vs = 6
    else:                  vs = 0

    # Sentiment score (0-30)
    if tagged >= 3:
        if   ratio >= 75: ss = 30
        elif ratio >= 60: ss = 20
        elif ratio >= 50: ss = 10
        else:             ss = 0
    else:
        ss = 0
    if trending:
        ss = min(ss + 10, 30)

    # Emoji + label
    if   tagged == 0:  emoji, label = '😐', 'No Data'
    elif ratio >= 80:  emoji, label = '🚀', 'Euphoric'
    elif ratio >= 70:  emoji, label = '🔥', 'Very Bullish'
    elif ratio >= 55:  emoji, label = '😊', 'Optimistic'
    elif ratio >= 40:  emoji, label = '😐', 'Neutral'
    else:              emoji, label = '😱', 'Fearful'

    return {
        'bullish_count':   bullish,
        'bearish_count':   bearish,
        'total_tagged':    tagged,
        'sentiment_ratio': ratio,
        'recent_1h':       recent_1h,
        'vol_spike':       vol_spike,
        'trending':        trending,
        'sentiment_score': ss,
        'volume_score':    vs,
        'score':           ss + vs,
        'emoji':           emoji,
        'label':           label,
    }


def _claude_sentiment(ticker):
    """One web-search call → structured sentiment JSON."""
    if not Config.ANTHROPIC_API_KEY:
        return None
    now = datetime.now()
    cached = _claude_cache.get(ticker)
    if cached and (now - cached['ts']).total_seconds() < CLAUDE_TTL:
        return cached['data']

    result = None
    try:
        ac = anthropic.Anthropic(api_key=Config.ANTHROPIC_API_KEY)
        msg = ac.messages.create(
            model='claude-haiku-4-5-20251001',
            max_tokens=300,
            tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 2}],
            messages=[{"role": "user", "content":
                f'Search for the latest social media and news sentiment about ${ticker} stock today. '
                'Look at Twitter/X posts, Reddit, and financial news headlines. '
                'Return ONLY a valid JSON object — no prose, no markdown, just the JSON:\n'
                '{"sentiment_score":0-100,"trend":"rising|falling|neutral",'
                '"influencer_buzz":true/false,"options_chatter":true/false,'
                '"fear_capitulation":true/false,"summary":"one sentence"}'
            }]
        )
        text = ''.join(b.text for b in msg.content if hasattr(b, 'text')).strip()
        m = re.search(r'\{[^{}]+\}', text, re.DOTALL)
        if m:
            result = json.loads(m.group())
    except Exception:
        pass

    _claude_cache[ticker] = {'data': result, 'ts': now}
    return result


@sentiment_bp.route('/sentiment/<ticker>', methods=['GET'])
def get_sentiment(ticker):
    ticker = ticker.upper().strip()
    now    = datetime.now()

    cached = _sentiment_cache.get(ticker)
    if cached and (now - cached['ts']).total_seconds() < SENTIMENT_TTL:
        return jsonify(cached['data'])

    st_data  = _fetch_st(ticker)
    st_score = _score_stocktwits(st_data)
    ai_data  = _claude_sentiment(ticker)

    # Bonus score for breakout integration
    bonus = 0
    contrarian = False
    if ai_data:
        cs = ai_data.get('sentiment_score', 50)
        if cs > 70:
            bonus += 20
        if ai_data.get('fear_capitulation') and (st_score or {}).get('sentiment_score', 0) > 0:
            contrarian = True
            bonus += 15

    result = {
        'ticker':       ticker,
        'stocktwits':   st_score,
        'ai':           ai_data,
        'breakout_bonus': bonus,
        'contrarian':   contrarian,
        'timestamp':    now.isoformat(),
    }
    _sentiment_cache[ticker] = {'data': result, 'ts': now}
    return jsonify(result)


@sentiment_bp.route('/sentiment/trending', methods=['GET'])
def get_trending():
    now    = datetime.now()
    cached = _trending_cache.get('all')
    if cached and (now - cached['ts']).total_seconds() < TRENDING_TTL:
        return jsonify(cached['data'])

    try:
        res = requests.get(
            'https://api.stocktwits.com/api/2/trending/symbols.json',
            headers=_ST_HEADERS, timeout=6)
        symbols = (res.json().get('symbols', [])[:5] if res.status_code == 200 else [])
    except Exception:
        symbols = []

    trending = []
    for sym in symbols:
        t = sym.get('symbol', '')
        if not t:
            continue
        st = _score_stocktwits(_fetch_st(t))
        trending.append({
            'ticker':          t,
            'title':           sym.get('title', t),
            'watchlist_count': sym.get('watchlist_count', 0),
            'sentiment':       st,
        })

    result = {'trending': trending, 'timestamp': now.isoformat()}
    _trending_cache['all'] = {'data': result, 'ts': now}
    return jsonify(result)
