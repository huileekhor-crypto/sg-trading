from flask import Blueprint, request, jsonify, session
import finnhub
import yfinance as yf
from config import Config
from datetime import datetime, timedelta

earnings_bp = Blueprint('earnings', __name__)
_calendar_cache = {}
_ticker_cache = {}

TOP_MOVERS = [
    'AAPL', 'MSFT', 'NVDA', 'META', 'AMZN', 'GOOGL', 'TSLA',
    'AMD',  'NFLX', 'CRM',  'SHOP', 'SNAP', 'UBER',  'COIN',
    'RBLX', 'SQ',   'PYPL', 'ROKU', 'JPM',  'BABA',
]


def _fc():
    return finnhub.Client(api_key=Config.FINNHUB_API_KEY)


def _beat_rate(history):
    valid = [(e.get('actual'), e.get('estimate')) for e in history
             if e.get('actual') is not None and e.get('estimate') is not None]
    if not valid:
        return None, 0
    beats = sum(1 for a, e in valid if a >= e)
    return round(beats / len(valid) * 100), len(valid)


def _hour_label(h):
    if not h:
        return 'TBD'
    h = h.lower()
    if h == 'bmo':
        return 'BMO'
    if h in ('amc', 'afc'):
        return 'AMC'
    return 'TBD'


def _when_label(days, hour):
    if days < 0:
        return None
    if days == 0:
        return f'Tonight ({hour})' if hour == 'AMC' else f'Today ({hour})'
    if days == 1:
        return f'Tomorrow ({hour})'
    return f'In {days} days'


@earnings_bp.route('/earnings/calendar', methods=['GET'])
def get_calendar():
    user_id = str(session.get('user_id', 'guest'))
    now = datetime.now()

    # Watchlist from query param (frontend localStorage) + server-side store
    wl_param = request.args.get('watchlist', '')
    user_wl = [t.strip().upper() for t in wl_param.split(',') if t.strip()] if wl_param else []
    try:
        from routes.watchlist import watchlist_store
        server_wl = watchlist_store.get(user_id, {}).get('user', [])
    except Exception:
        server_wl = []
    user_wl = list(dict.fromkeys(user_wl + server_wl))

    all_tickers = set(user_wl + TOP_MOVERS)

    cache_key = f"{user_id}_{','.join(sorted(user_wl))}"
    cached = _calendar_cache.get(cache_key)
    if cached and (now - cached['ts']).total_seconds() < 21600:
        return jsonify(cached['data'])

    try:
        fc = _fc()
        date_from = now.strftime('%Y-%m-%d')
        date_to   = (now + timedelta(days=30)).strftime('%Y-%m-%d')

        # Try bulk calendar first, fall back to per-ticker calls
        items = []
        try:
            cal   = fc.earnings_calendar(_from=date_from, to=date_to, symbol='', international=False) or {}
            items = cal.get('earningsCalendar', [])
        except Exception:
            pass

        if not items:
            for t in list(all_tickers)[:20]:
                try:
                    c = fc.earnings_calendar(_from=date_from, to=date_to, symbol=t, international=False) or {}
                    items.extend(c.get('earningsCalendar', []))
                except Exception:
                    pass

        # Filter to tracked tickers and dedupe
        seen, relevant = set(), []
        for item in items:
            sym = item.get('symbol', '')
            if sym not in all_tickers:
                continue
            key = f"{sym}_{item.get('date')}"
            if key not in seen:
                seen.add(key)
                relevant.append(item)

        # Fetch EPS history for watchlist tickers (beat rate)
        beat_cache = {}
        for ticker in user_wl[:8]:
            try:
                beat_cache[ticker] = fc.stock_earnings(ticker) or []
            except Exception:
                beat_cache[ticker] = []

        # Build event list
        events = []
        for item in relevant:
            ticker   = item.get('symbol', '')
            date_str = item.get('date', '')
            if not date_str:
                continue
            try:
                event_dt  = datetime.strptime(date_str, '%Y-%m-%d')
                days_until = (event_dt.date() - now.date()).days
            except Exception:
                continue
            if days_until < 0:
                continue

            hour       = _hour_label(item.get('hour', ''))
            when_label = _when_label(days_until, hour)
            if when_label is None:
                continue

            in_wl  = ticker in user_wl
            hist   = beat_cache.get(ticker, [])
            beat_rate, beat_count = _beat_rate(hist)

            if beat_rate is None:
                beat_color = 'neutral'
            elif beat_rate >= 60:
                beat_color = 'green'
            elif beat_rate <= 40:
                beat_color = 'red'
            else:
                beat_color = 'amber'

            prev_eps = hist[0].get('actual') if hist else None
            eps_est  = item.get('epsEstimate')
            rev_est  = item.get('revenueEstimate')

            events.append({
                'ticker':      ticker,
                'date':        date_str,
                'day_of_week': event_dt.strftime('%A'),
                'hour':        hour,
                'when_label':  when_label,
                'days_until':  days_until,
                'eps_estimate': round(eps_est, 2) if eps_est is not None else None,
                'eps_prev':     round(prev_eps, 2) if prev_eps is not None else None,
                'rev_estimate': rev_est,
                'beat_rate':    beat_rate,
                'beat_count':   beat_count,
                'beat_color':   beat_color,
                'in_watchlist': in_wl,
            })

        events.sort(key=lambda x: (0 if x['in_watchlist'] else 1, x['days_until'], x['ticker']))

        result = {
            'events':         events,
            'user_watchlist': user_wl,
            'date_from':      date_from,
            'date_to':        date_to,
            'timestamp':      now.isoformat(),
        }
        _calendar_cache[cache_key] = {'data': result, 'ts': now}
        return jsonify(result)

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@earnings_bp.route('/earnings/ticker/<ticker>', methods=['GET'])
def get_ticker_earnings(ticker):
    ticker = ticker.upper().strip()
    now    = datetime.now()

    cached = _ticker_cache.get(ticker)
    if cached and (now - cached['ts']).total_seconds() < 21600:
        return jsonify(cached['data'])

    try:
        fc = _fc()
        try:
            history = fc.stock_earnings(ticker) or []
        except Exception:
            history = []

        quarters = []
        for e in history[:8]:
            date_str  = e.get('period', '')
            price_move = None

            if date_str:
                try:
                    dt   = datetime.strptime(date_str, '%Y-%m-%d')
                    pre  = (dt - timedelta(days=1)).strftime('%Y-%m-%d')
                    post = (dt + timedelta(days=3)).strftime('%Y-%m-%d')
                    df   = yf.download(ticker, start=pre, end=post, progress=False, auto_adjust=True)
                    if not df.empty and len(df) >= 2:
                        if hasattr(df.columns, 'levels'):
                            df.columns = df.columns.droplevel(1)
                        closes = df['Close'].tolist()
                        if len(closes) >= 2:
                            price_move = round(((closes[-1] - closes[0]) / closes[0]) * 100, 2)
                except Exception:
                    pass

            actual   = e.get('actual')
            estimate = e.get('estimate')
            if actual is not None and estimate is not None:
                beat = 'beat' if actual > estimate * 1.01 else 'miss' if actual < estimate * 0.99 else 'inline'
            else:
                beat = None

            quarters.append({
                'period':       date_str,
                'quarter':      e.get('quarter'),
                'year':         e.get('year'),
                'actual':       actual,
                'estimate':     estimate,
                'surprise_pct': round(float(e.get('surprisePercent') or 0), 2),
                'beat':         beat,
                'price_move':   price_move,
            })

        beat_rate, _ = _beat_rate(history[:8])
        moves        = [abs(q['price_move']) for q in quarters if q['price_move'] is not None]
        avg_move     = round(sum(moves) / len(moves), 1) if moves else None

        result = {
            'ticker':    ticker,
            'quarters':  quarters,
            'beat_rate': beat_rate,
            'avg_move':  avg_move,
        }
        _ticker_cache[ticker] = {'data': result, 'ts': now}
        return jsonify(result)

    except Exception as e:
        return jsonify({'error': str(e)}), 500
