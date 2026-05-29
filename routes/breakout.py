from flask import Blueprint, request, jsonify
import yfinance as yf
from config import Config
from datetime import datetime, timedelta

breakout_bp = Blueprint('breakout', __name__)
_breakout_cache = {}
_candle_cache   = {}
_catalyst_cache = {}
CACHE_TTL     = 1800   # 30 min for scores
CANDLE_TTL    = 1800   # 30 min for price data
CATALYST_TTL  = 86400  # 24 h for earnings dates

TOP_MOMENTUM_STOCKS = [
    'NVDA', 'MSFT', 'META', 'GOOGL', 'AMZN', 'AAPL', 'TSM', 'AVGO',
    'AMD',  'IONQ', 'QBTS', 'RGTI',  'PLTR', 'MSTR', 'TSLA', 'CRM',
    'NFLX', 'ORCL', 'DELL', 'ARM',
]

SECTOR_MAP = {
    # Tech / Semiconductors → XLK
    'AAPL':'XLK','MSFT':'XLK','NVDA':'XLK','AMD':'XLK','INTC':'XLK',
    'AVGO':'XLK','QCOM':'XLK','TXN':'XLK','MU':'XLK','AMAT':'XLK',
    'CRM':'XLK','ORCL':'XLK','IBM':'XLK','TSM':'XLK','ARM':'XLK',
    'DELL':'XLK','HPQ':'XLK','ANET':'XLK','CDNS':'XLK','SNPS':'XLK',
    'IONQ':'XLK','QBTS':'XLK','RGTI':'XLK','QUBT':'XLK','ARQQ':'XLK',
    'PLTR':'XLK','MSTR':'XLK','SHOP':'XLK','RBLX':'XLK','ROKU':'XLK',
    # Communication → XLC
    'GOOGL':'XLC','GOOG':'XLC','META':'XLC','NFLX':'XLC','SNAP':'XLC',
    'UBER':'XLC','LYFT':'XLC','TWTR':'XLC',
    # Consumer Discretionary → XLY
    'AMZN':'XLY','TSLA':'XLY','HD':'XLY','LOW':'XLY','NKE':'XLY',
    'SBUX':'XLY','MCD':'XLY','BABA':'XLY',
    # Finance → XLF
    'JPM':'XLF','GS':'XLF','MS':'XLF','BAC':'XLF','WFC':'XLF',
    'BLK':'XLF','COIN':'XLF','SQ':'XLF','PYPL':'XLF','V':'XLF','MA':'XLF',
    # Healthcare → XLV
    'JNJ':'XLV','PFE':'XLV','UNH':'XLV','ABBV':'XLV','MRK':'XLV',
    # Energy → XLE
    'XOM':'XLE','CVX':'XLE','SLB':'XLE','COP':'XLE',
}
MAX_RAW = 165  # 15+15+10+10+25+20+20+20+15+15


def _get_candles(ticker, days=260):
    now    = datetime.now()
    cached = _candle_cache.get(ticker)
    if cached and (now - cached['ts']).total_seconds() < CANDLE_TTL:
        return cached['data']
    end   = now
    start = end - timedelta(days=days)
    df = yf.download(ticker, start=start.strftime('%Y-%m-%d'),
                     end=end.strftime('%Y-%m-%d'), progress=False, auto_adjust=True)
    if df.empty:
        _candle_cache[ticker] = {'data': None, 'ts': now}
        return None
    if hasattr(df.columns, 'levels'):
        df.columns = df.columns.droplevel(1)
    data = {
        'c': df['Close'].tolist(),
        'h': df['High'].tolist(),
        'l': df['Low'].tolist(),
        'v': df['Volume'].tolist(),
    }
    _candle_cache[ticker] = {'data': data, 'ts': now}
    return data


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


def _get_market_regime():
    candles = _get_candles('SPY', days=260)
    if not candles or len(candles['c']) < 200:
        return True, 0, 0
    spy_price  = candles['c'][-1]
    spy_ema200 = _ema(candles['c'], 200)
    is_bull    = spy_price > spy_ema200 if spy_ema200 else True
    return is_bull, round(spy_price, 2), round(spy_ema200 or 0, 2)


def _sig_sector(ticker):
    etf     = SECTOR_MAP.get(ticker, 'SPY')
    candles = _get_candles(etf, days=60)
    if not candles or len(candles['c']) < 21:
        return 0, etf, f'{etf} data unavailable'
    ema20 = _ema(candles['c'], 20)
    price = candles['c'][-1]
    if ema20 and price > ema20:
        return 15, etf, f'{etf} above 20 EMA (${round(ema20,2)}) — sector in uptrend'
    return 0, etf, f'{etf} below 20 EMA (${round(ema20 or 0,2)}) — sector under pressure'


def _sig_catalyst(ticker):
    now    = datetime.now()
    cached = _catalyst_cache.get(ticker)
    if cached and (now - cached['ts']).total_seconds() < CATALYST_TTL:
        return cached['data']
    result = (0, 'Earnings data unavailable')
    if Config.FINNHUB_API_KEY:
        try:
            import finnhub
            fc  = finnhub.Client(api_key=Config.FINNHUB_API_KEY)
            cal = fc.earnings_calendar(
                _from=now.strftime('%Y-%m-%d'),
                to=(now + timedelta(days=46)).strftime('%Y-%m-%d'),
                symbol=ticker, international=False
            ) or {}
            items = cal.get('earningsCalendar', [])
            if items:
                date_str  = items[0].get('date', '')
                dt        = datetime.strptime(date_str, '%Y-%m-%d')
                days_away = (dt.date() - now.date()).days
                if days_away <= 1:
                    result = (0, f'Earnings in {days_away}d — too close, elevated risk')
                elif 7 <= days_away <= 21:
                    result = (15, f'Earnings in {days_away}d — ideal catalyst window (7-21d)')
                elif 22 <= days_away <= 45:
                    result = (8, f'Earnings in {days_away}d — upcoming catalyst on horizon')
                else:
                    result = (0, f'Earnings in {days_away}d — outside catalyst window')
            else:
                result = (0, 'No earnings in next 45 days')
        except Exception:
            pass
    _catalyst_cache[ticker] = {'data': result, 'ts': now}
    return result


def _score_ticker(ticker, is_bull=True):
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

    sigs = []  # list of {name, score, max, pass, explanation}

    avg20 = sum(volumes[-21:-1]) / 20 if len(volumes) >= 21 else (sum(volumes[:-1]) / max(len(volumes)-1, 1))

    # ── 1. Volume Contraction (0-15) ─────────────────────────────────────
    s = 0
    recent_v = volumes[-5:]
    dec      = sum(1 for i in range(1, len(recent_v)) if recent_v[i] < recent_v[i-1])
    if dec >= 3: s += 10
    elif dec >= 2: s += 5
    if avg20 > 0 and volumes[-1] / avg20 < 0.5: s += 5
    s = min(s, 15)
    if dec >= 3:
        ex = f'Volume declining {dec} days — energy coiling for release'
    elif dec >= 2:
        ex = f'Volume declining {dec} days — early contraction forming'
    elif s > 0:
        ex = 'Volume quiet below 20-day avg — low-key accumulation'
    else:
        ex = 'Volume not contracting — no coiling signal yet'
    sigs.append({'name':'Volume Contraction','score':s,'max':15,'pass':s>=8,'explanation':ex})

    # ── 2. Bollinger Band Squeeze (0-15) ──────────────────────────────────
    s = 0; ex = 'Insufficient data for BB squeeze'
    if len(closes) >= 40:
        def _bbw(c20):
            sm = sum(c20)/20
            st = (sum((p-sm)**2 for p in c20)/20)**0.5
            return (4*st)/sm if sm>0 else 0
        cur_w  = _bbw(closes[-20:])
        hist_w = [_bbw(closes[i-20:i]) for i in range(20, len(closes)-1)]
        if hist_w:
            avg_w = sum(hist_w)/len(hist_w)
            pct   = cur_w/avg_w if avg_w>0 else 1
            if   pct < 0.40: s=15; ex=f'BB width at {round(pct*100)}% of avg — extreme squeeze, breakout imminent'
            elif pct < 0.60: s=10; ex=f'BB width at {round(pct*100)}% of avg — tight squeeze building'
            elif pct < 0.75: s= 5; ex=f'BB width at {round(pct*100)}% of avg — bands narrowing'
            else:             ex=f'BB width at {round(pct*100)}% of avg — no meaningful squeeze'
    sigs.append({'name':'BB Squeeze','score':s,'max':15,'pass':s>=8,'explanation':ex})

    # ── 3. RSI Launch Zone (0-10) ─────────────────────────────────────────
    rsi = _rsi(closes)
    s   = 0
    if rsi is None:
        ex = 'RSI unavailable'
    elif 45 <= rsi <= 65:
        s=10; ex=f'RSI {rsi} — ideal pre-breakout zone (45-65)'
    elif (35<=rsi<45) or (65<rsi<=75):
        s=5;  ex=f'RSI {rsi} — acceptable but not ideal launch zone'
    elif rsi > 75:
        ex = f'RSI {rsi} — overbought, breakout risk of reversal'
    else:
        ex = f'RSI {rsi} — oversold, price may need more base building'
    sigs.append({'name':'RSI Launch Zone','score':s,'max':10,'pass':s==10,'explanation':ex})

    # ── 4. Higher Lows (0-10) ─────────────────────────────────────────────
    s = 0
    rl = lows[-6:] if len(lows)>=6 else lows
    hl = 0
    for i in range(1, len(rl)):
        hl = hl+1 if rl[i]>rl[i-1] else 0
    if hl>=3: s=10; ex=f'{hl} consecutive higher lows — buyers stepping in at higher prices'
    elif hl>=2: s=5; ex=f'{hl} consecutive higher lows — early demand structure forming'
    else: ex='No higher lows pattern — structure not yet established'
    sigs.append({'name':'Higher Lows','score':s,'max':10,'pass':s>=5,'explanation':ex})

    # ── 5. RVOL — Relative Volume (0-25) ──────────────────────────────────
    s = 0
    if avg20 > 0:
        rvol = volumes[-1] / avg20
        if   rvol >= 3.0: s=25; ex=f'RVOL {round(rvol,1)}× — massive surge, strong institutional buying'
        elif rvol >= 2.0: s=15; ex=f'RVOL {round(rvol,1)}× — well above average, accumulation signal'
        elif rvol >= 1.5: s= 8; ex=f'RVOL {round(rvol,1)}× — above average, buying interest noted'
        else:             ex= f'RVOL {round(rvol,1)}× — below threshold, no volume confirmation'
    else:
        rvol=1.0; ex='Volume data unavailable'
    sigs.append({'name':'RVOL','score':s,'max':25,'pass':s>=8,'explanation':ex})

    # ── 6. On Balance Volume (0-20) ───────────────────────────────────────
    s = 0; ex='Insufficient data for OBV'
    if len(closes) >= 11:
        obv=[0]
        for i in range(1,len(closes)):
            if   closes[i]>closes[i-1]: obv.append(obv[-1]+volumes[i])
            elif closes[i]<closes[i-1]: obv.append(obv[-1]-volumes[i])
            else:                        obv.append(obv[-1])
        obv10   = obv[-10:]
        p10     = closes[-10:]
        obv_chg = (obv10[-1]-obv10[0])/(abs(obv10[0])+1e-10)
        p_chg10 = (p10[-1]-p10[0])/p10[0] if p10[0]>0 else 0
        if obv_chg>0.01 and abs(p_chg10)<0.02:
            s=20; ex='OBV rising while price flat — stealth accumulation, smart money loading'
        elif obv_chg>0.01:
            s=10; ex='OBV rising with price — volume confirming the uptrend'
        else:
            ex='OBV declining — distribution, not an ideal setup'
    sigs.append({'name':'OBV Trend','score':s,'max':20,'pass':s>=10,'explanation':ex})

    # ── 7. 52-Week High Proximity (0-20) ──────────────────────────────────
    high52       = max(highs[-252:]) if len(highs)>=252 else max(highs)
    pct_from_high = round(((high52-price)/high52)*100,1) if high52>0 else 100
    if   pct_from_high<=1:  s=20; ex=f'Within {pct_from_high}% of 52-wk high — at breakout resistance'
    elif pct_from_high<=3:  s=15; ex=f'{pct_from_high}% from 52-wk high — approaching key resistance'
    elif pct_from_high<=5:  s=10; ex=f'{pct_from_high}% from 52-wk high — within striking distance'
    elif pct_from_high<=10: s= 5; ex=f'{pct_from_high}% from 52-wk high — building base below resistance'
    else:                   s= 0; ex=f'{pct_from_high}% from 52-wk high — too far from breakout level'
    sigs.append({'name':'52-Wk High Proximity','score':s,'max':20,'pass':s>=10,'explanation':ex})

    # ── 8. Pocket Pivot (0-20) ────────────────────────────────────────────
    s = 0; ex='Insufficient data for pocket pivot'
    if len(closes) >= 12:
        down_vols   = [volumes[i] for i in range(-11,-1) if closes[i]<closes[i-1]]
        max_down_v  = max(down_vols) if down_vols else 0
        pp_vol      = volumes[-1] > max_down_v if max_down_v>0 else False
        today_range = highs[-1] - lows[-1]
        pp_pos      = (closes[-1] - lows[-1]) > today_range*0.5 if today_range>0 else False
        if pp_vol and pp_pos:
            s=20; ex='Volume exceeds all down-day vols and close in upper range — textbook pocket pivot'
        elif pp_vol:
            s=10; ex='Volume clears down-day highs but close in lower half of range'
        elif pp_pos:
            s=10; ex='Close in upper range but volume below down-day threshold'
        else:
            ex='No pocket pivot — volume and close position not qualifying'
    sigs.append({'name':'Pocket Pivot','score':s,'max':20,'pass':s>=10,'explanation':ex})

    # ── 9. Sector Momentum (0-15) ─────────────────────────────────────────
    sec_score, etf_name, sec_ex = _sig_sector(ticker)
    sigs.append({'name':f'Sector ({etf_name})','score':sec_score,'max':15,
                 'pass':sec_score>=15,'explanation':sec_ex})

    # ── 10. Catalyst Proximity (0-15) ─────────────────────────────────────
    cat_score, cat_ex = _sig_catalyst(ticker)
    sigs.append({'name':'Catalyst Window','score':cat_score,'max':15,
                 'pass':cat_score>=8,'explanation':cat_ex})

    # ── Normalise + Regime Multiplier ─────────────────────────────────────
    raw_total  = sum(sg['score'] for sg in sigs)
    regime_m   = 1.0 if is_bull else 0.65
    normalized = min(100, round((raw_total / MAX_RAW) * 100 * regime_m))

    if normalized < 50:
        return None

    if   normalized >= 80: level,color,emoji,label = 'IMMINENT','red',  '🚨','IMMINENT BREAKOUT'
    elif normalized >= 65: level,color,emoji,label = 'WATCH',   'amber','⚠', 'HIGH PROBABILITY'
    else:                  level,color,emoji,label = 'RADAR',   'cyan', '👁','DEVELOPING SETUP'

    # ATR-based levels
    trs    = [max(highs[i]-lows[i], abs(highs[i]-closes[i-1]), abs(lows[i]-closes[i-1]))
              for i in range(1,len(closes))]
    atr    = round(sum(trs[-14:])/14,4) if len(trs)>=14 else price*0.025
    entry  = round(price,2)
    stop   = round(price-1.5*atr,2)
    target = round(price+3.0*atr,2)
    rr     = round((target-entry)/(entry-stop),1) if entry!=stop else 0

    top3 = sorted(sigs, key=lambda x: x['score'], reverse=True)[:3]
    why  = ' | '.join(sg['explanation'] for sg in top3 if sg['score']>0) or \
           'Multiple signals aligning for a potential breakout.'

    return {
        'ticker':         ticker,
        'score':          normalized,
        'raw_score':      raw_total,
        'alert_level':    level,
        'alert_label':    label,
        'alert_color':    color,
        'alert_emoji':    emoji,
        'price':          round(price,2),
        'price_change':   pct_chg,
        'pct_from_high':  pct_from_high,
        'market_regime':  'BULL' if is_bull else 'BEAR',
        'regime_mult':    regime_m,
        'signal_details': sigs,
        'signals':        [sg['name'] for sg in sigs if sg['pass']],  # compat
        'score_breakdown': {                                            # compat
            'volume': sigs[0]['score'], 'price': sigs[1]['score'],
            'rsi':    sigs[2]['score'], 'structure': sigs[3]['score'],
        },
        'entry': f'${entry}', 'stop': f'${stop}', 'target': f'${target}',
        'rr': rr, 'rsi': rsi, 'why': why,
    }


def _scan_list(tickers, is_bull=True):
    now     = datetime.now()
    results = []
    for ticker in tickers:
        cached = _breakout_cache.get(ticker)
        if cached and (now - cached['ts']).total_seconds() < CACHE_TTL:
            if cached['data']:
                results.append(cached['data'])
            continue
        try:
            r = _score_ticker(ticker, is_bull)
            _breakout_cache[ticker] = {'data': r, 'ts': now}
            if r:
                results.append(r)
        except Exception:
            pass
    results.sort(key=lambda x: x['score'], reverse=True)

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
            pass
    return results


@breakout_bp.route('/breakout/scan', methods=['POST'])
def scan_breakouts():
    body    = request.get_json() or {}
    tickers = [t.upper().strip() for t in body.get('tickers', []) if t.strip()]
    if not tickers:
        return jsonify({'error': 'No tickers provided'}), 400
    tickers = tickers[:30]
    is_bull, spy_price, spy_ema200 = _get_market_regime()
    results = _scan_list(tickers, is_bull)
    return jsonify({
        'results':      results,
        'scanned':      len(tickers),
        'found':        len(results),
        'market_regime': 'BULL' if is_bull else 'BEAR',
        'spy_price':    spy_price,
        'spy_ema200':   spy_ema200,
        'timestamp':    datetime.now().isoformat(),
    })


@breakout_bp.route('/breakout/top', methods=['GET'])
def top_breakouts():
    is_bull, spy_price, spy_ema200 = _get_market_regime()
    results = _scan_list(TOP_MOMENTUM_STOCKS, is_bull)
    return jsonify({
        'results':      results[:5],
        'scanned':      len(TOP_MOMENTUM_STOCKS),
        'found':        len(results),
        'market_regime': 'BULL' if is_bull else 'BEAR',
        'spy_price':    spy_price,
        'spy_ema200':   spy_ema200,
        'timestamp':    datetime.now().isoformat(),
    })
