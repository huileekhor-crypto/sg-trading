"""
Shared Trump portfolio + mention cache.
Imported by both routes/breakout.py and routes/intelligence.py — no circular deps.
"""
import re, json
from datetime import datetime
from config import Config

# ── Hardcoded fallback (Q1 2026 OGE Form 278-T) ──────────────────────────────
FALLBACK_PORTFOLIO = {
    'NVDA': {'action':'buy','size':'large', 'company':'Nvidia'},
    'AVGO': {'action':'buy','size':'large', 'company':'Broadcom'},
    'ORCL': {'action':'buy','size':'large', 'company':'Oracle'},
    'NOW':  {'action':'buy','size':'large', 'company':'ServiceNow'},
    'ADBE': {'action':'buy','size':'large', 'company':'Adobe'},
    'MSFT': {'action':'buy','size':'large', 'company':'Microsoft'},
    'AMZN': {'action':'buy','size':'large', 'company':'Amazon'},
    'TXN':  {'action':'buy','size':'large', 'company':'Texas Instruments'},
    'DELL': {'action':'buy','size':'large', 'company':'Dell Technologies'},
    'MSI':  {'action':'buy','size':'large', 'company':'Motorola Solutions'},
    'AAPL': {'action':'buy','size':'large', 'company':'Apple'},
    'PLTR': {'action':'buy','size':'large', 'company':'Palantir'},
    'WDAY': {'action':'buy','size':'large', 'company':'Workday'},
    'NFLX': {'action':'buy','size':'medium','company':'Netflix'},
    'CMCSA':{'action':'buy','size':'medium','company':'Comcast'},
    'META': {'action':'sell','size':'large','company':'Meta'},
}

# ── Cache state ───────────────────────────────────────────────────────────────
_portfolio_cache = {'data': None, 'ts': None, 'tickers': set()}
_PORTFOLIO_TTL   = 21600   # 6 hours

_mentions_cache  = {'data': None, 'ts': None,
                    'tickers_today': set(), 'prev_tickers': set()}
_MENTIONS_TTL    = 1800    # 30 minutes


# ── Helpers ───────────────────────────────────────────────────────────────────

def _ac():
    import anthropic
    return anthropic.Anthropic(api_key=Config.ANTHROPIC_API_KEY)


def _extract_json(text, container='object'):
    pattern = r'\{[\s\S]*\}' if container == 'object' else r'\[[\s\S]*\]'
    m = re.search(pattern, text)
    if m:
        try:
            return json.loads(m.group())
        except Exception:
            pass
    return None


# ── Portfolio ─────────────────────────────────────────────────────────────────

def fetch_portfolio_live():
    """Claude web_search → trumpstocktracker.com → holdings JSON."""
    if not Config.ANTHROPIC_API_KEY:
        return None
    today = datetime.now().strftime('%B %d, %Y')
    prompt = (
        f"Today is {today}. Search trumpstocktracker.com for Trump's most recent "
        "stock holdings and trades disclosed in his OGE financial filings. "
        "Return ONLY valid JSON (no markdown, no prose):\n"
        '{"holdings":[{"ticker":"NVDA","company":"Nvidia","action":"buy",'
        '"value_range":"$1M-$5M","date":"Q1 2026","count":3}],'
        '"last_updated":"Q1 2026","total_transactions":3848}'
    )
    try:
        msg = _ac().messages.create(
            model='claude-haiku-4-5-20251001', max_tokens=1500,
            tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 3}],
            messages=[{"role": "user", "content": prompt}]
        )
        text = ''.join(b.text for b in msg.content if hasattr(b, 'text')).strip()
        result = _extract_json(text, 'object')
        if result and isinstance(result.get('holdings'), list) and result['holdings']:
            return result
    except Exception:
        pass
    return None


def get_portfolio():
    """Return portfolio data, auto-refreshing every 6 hours."""
    now = datetime.now()
    if (_portfolio_cache['ts']
            and (now - _portfolio_cache['ts']).total_seconds() < _PORTFOLIO_TTL
            and _portfolio_cache['data']):
        return _portfolio_cache['data']

    live = fetch_portfolio_live()
    if live and live.get('holdings'):
        tickers = {h['ticker'].upper() for h in live['holdings']
                   if str(h.get('action','')).lower() == 'buy'}
        live['source'] = 'live'
        _portfolio_cache.update({'data': live, 'ts': now, 'tickers': tickers})
        return live

    # Fallback
    holdings = [
        {'ticker': t, 'company': v['company'], 'action': v['action'],
         'value_range': 'disclosed', 'date': 'Q1 2026', 'count': 1}
        for t, v in FALLBACK_PORTFOLIO.items()
    ]
    fallback = {'holdings': holdings, 'last_updated': 'Q1 2026',
                'total_transactions': 3848, 'source': 'fallback'}
    tickers  = {t for t, v in FALLBACK_PORTFOLIO.items() if v['action'] == 'buy'}
    _portfolio_cache.update({'data': fallback, 'ts': now, 'tickers': tickers})
    return fallback


def get_portfolio_tickers():
    """Set of tickers currently held (buy side)."""
    if not _portfolio_cache['tickers']:
        get_portfolio()
    return _portfolio_cache['tickers'] or {t for t, v in FALLBACK_PORTFOLIO.items() if v['action'] == 'buy'}


# ── Mentions ──────────────────────────────────────────────────────────────────

def fetch_mentions_live():
    """Claude web_search → trumptrack.app → today's stock mentions JSON."""
    if not Config.ANTHROPIC_API_KEY:
        return None
    today = datetime.now().strftime('%B %d, %Y')
    prompt = (
        f"Today is {today}. Search trumptrack.app for Trump's most recent public "
        "mentions of stock tickers or companies in the past 24-48 hours. "
        "Include Truth Social posts, White House statements, and news appearances. "
        "Return ONLY valid JSON (no markdown, no prose):\n"
        '{"mentions":[{"ticker":"DELL","company":"Dell Technologies",'
        '"context":"what he said or did about this company",'
        '"source":"Truth Social|White House|News","date":"today",'
        '"sentiment":"positive|negative|neutral"}],'
        '"tone_today":"brief summary of his market tone today"}'
    )
    try:
        msg = _ac().messages.create(
            model='claude-haiku-4-5-20251001', max_tokens=1000,
            tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 3}],
            messages=[{"role": "user", "content": prompt}]
        )
        text   = ''.join(b.text for b in msg.content if hasattr(b, 'text')).strip()
        result = _extract_json(text, 'object')
        if result and isinstance(result.get('mentions'), list):
            return result
    except Exception:
        pass
    return None


def get_mentions():
    """Return today's mentions, auto-refreshing every 30 minutes."""
    now = datetime.now()
    if (_mentions_cache['ts']
            and (now - _mentions_cache['ts']).total_seconds() < _MENTIONS_TTL
            and _mentions_cache['data']):
        return _mentions_cache['data']

    live = fetch_mentions_live()
    if live and 'mentions' in live:
        tickers = {m['ticker'].upper() for m in live['mentions'] if m.get('ticker')}
        prev    = _mentions_cache.get('tickers_today', set())
        live['source']       = 'live'
        live['last_updated'] = now.strftime('%I:%M %p SGT')
        _mentions_cache.update({
            'data': live, 'ts': now,
            'tickers_today': tickers, 'prev_tickers': prev,
        })
        return live

    empty = {'mentions': [], 'tone_today': 'No mentions data available',
             'last_updated': 'unavailable', 'source': 'unavailable'}
    _mentions_cache.update({'data': empty, 'ts': now, 'tickers_today': set()})
    return empty


def get_mention_tickers_today():
    """Set of tickers Trump mentioned today."""
    return _mentions_cache.get('tickers_today', set())


def get_new_mentions():
    """Tickers newly added since the previous cache fill — for the scheduler."""
    return (_mentions_cache.get('tickers_today', set())
            - _mentions_cache.get('prev_tickers', set()))
