from flask import Blueprint, jsonify
import anthropic
import json
import re
from datetime import datetime
from config import Config

intelligence_bp = Blueprint('intelligence', __name__)
_scan_cache = {}
SCAN_TTL = 1800  # 30 min

SECTOR_TICKERS = {
    'AI':           ['NVDA','MSFT','META','GOOGL','AMD','PLTR'],
    'Drone/Defence':['AVAV','KTOS','RCAT','UMAC','LHX'],
    'Quantum':      ['IONQ','QBTS','RGTI','QUBT','IBM'],
    'Semiconductor':['NVDA','AMD','MU','AVGO','TSM'],
    'Cloud':        ['MSFT','AMZN','GOOGL','SNOW','CRM'],
    'EV':           ['TSLA','RIVN','NIO','GM'],
    'Crypto':       ['COIN','MSTR','MARA','RIOT','CLSK'],
    'Energy':       ['XOM','CVX','NEE','FSLR'],
    'Finance':      ['JPM','GS','MS','BAC'],
    'Healthcare':   ['LLY','NVO','ABBV','JNJ'],
}

_TYPE_COLORS = {
    'policy':   'purple',
    'earnings': 'cyan',
    'sector':   'green',
    'analyst':  'blue',
    'macro':    'amber',
}


def _ac():
    return anthropic.Anthropic(api_key=Config.ANTHROPIC_API_KEY)


def _extract_json(text, container='object'):
    """Extract first JSON object or array from text."""
    pattern = r'\{[\s\S]*\}' if container == 'object' else r'\[[\s\S]*\]'
    m = re.search(pattern, text)
    if m:
        try:
            return json.loads(m.group())
        except Exception:
            pass
    return None


# ── Step 1: Catalyst Scanner ──────────────────────────────────────────────────

def _scan_catalysts():
    today = datetime.now().strftime('%B %d, %Y')
    prompt = (
        f"Today is {today}. Search the web for major market-moving events affecting US stocks RIGHT NOW. "
        "Find: government/White House/Trump policy changes, earnings surprises, sector moves >3%, "
        "analyst upgrades/downgrades (Goldman Sachs, JPMorgan, Morgan Stanley), Fed statements, "
        "and sector rotation signals. "
        "Return ONLY valid JSON (no markdown, no prose):\n"
        '{"catalysts":[{"type":"policy|earnings|sector|analyst|macro","headline":"text",'
        '"impact":"bullish|bearish","urgency":"immediate|days|weeks",'
        '"affected_sectors":["AI","Quantum",...],"affected_tickers":["NVDA",...],'
        '"confidence":0-100}],"market_summary":"one sentence overview"}'
    )
    try:
        msg = _ac().messages.create(
            model='claude-haiku-4-5-20251001',
            max_tokens=1800,
            tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 4}],
            messages=[{"role": "user", "content": prompt}]
        )
        text   = ''.join(b.text for b in msg.content if hasattr(b, 'text')).strip()
        result = _extract_json(text, 'object')
        if result and 'catalysts' in result:
            return result
    except Exception:
        pass
    return {'catalysts': [], 'market_summary': 'Catalyst scan unavailable'}


# ── Step 3: Score Candidates ──────────────────────────────────────────────────

def _collect_candidates(catalysts):
    """Build ticker → catalyst_score map from catalysts + sector map."""
    scores = {}
    for cat in catalysts:
        conf = float(cat.get('confidence', 50))
        for t in cat.get('affected_tickers', []):
            t = t.upper().strip()
            scores[t] = max(scores.get(t, 0), conf)
        for sector in cat.get('affected_sectors', []):
            for t in SECTOR_TICKERS.get(sector, []):
                scores[t] = max(scores.get(t, 0), conf * 0.65)
    # Always include top AI/semi names at floor score
    for t in SECTOR_TICKERS.get('AI', []) + SECTOR_TICKERS.get('Semiconductor', []):
        scores.setdefault(t, 25.0)
    return scores


def _score_candidates(catalysts):
    from routes.breakout import _score_ticker, _get_market_regime
    from routes.sentiment import _fetch_st, _score_stocktwits

    cat_scores = _collect_candidates(catalysts)
    is_bull, _, _ = _get_market_regime()

    # Phase 1: catalyst + breakout (no sentiment yet — faster)
    phase1 = []
    for ticker, cat_score in cat_scores.items():
        try:
            brk      = _score_ticker(ticker, is_bull)
            brk_score = brk['score'] if brk else 30
            phase1.append({
                'ticker':       ticker,
                'cat_score':    round(cat_score),
                'brk_score':    brk_score,
                'breakout_data':brk,
                'phase1':       round(cat_score * 0.4 + brk_score * 0.4),
            })
        except Exception:
            pass

    phase1.sort(key=lambda x: x['phase1'], reverse=True)
    top10 = phase1[:10]  # get sentiment only for top 10

    # Phase 2: add sentiment for top 10
    results = []
    for r in top10:
        try:
            st = _score_stocktwits(_fetch_st(r['ticker']))
            sent_score = min((st.get('score', 0) / 50.0) * 100, 100) if st else 50
        except Exception:
            sent_score = 50

        combined = round(r['cat_score'] * 0.4 + r['brk_score'] * 0.4 + sent_score * 0.2)
        results.append({
            'ticker':          r['ticker'],
            'combined_score':  combined,
            'catalyst_score':  r['cat_score'],
            'breakout_score':  r['brk_score'],
            'sentiment_score': round(sent_score),
            'breakout_data':   r['breakout_data'],
        })

    results.sort(key=lambda x: x['combined_score'], reverse=True)
    return results[:5]


# ── Step 4: Generate Verdicts ─────────────────────────────────────────────────

def _generate_verdicts(top5, catalysts, market_summary):
    stocks_txt = '\n'.join(
        f"{i+1}. {r['ticker']} — combined {r['combined_score']}/100 "
        f"(catalyst {r['catalyst_score']}, breakout {r['breakout_score']}, sentiment {r['sentiment_score']})"
        for i, r in enumerate(top5)
    )
    cat_txt = '; '.join(c.get('headline', '') for c in catalysts[:3]) or 'General market conditions'

    prompt = (
        f"Market: {market_summary}\nKey catalysts: {cat_txt}\n\nTop stocks:\n{stocks_txt}\n\n"
        "Write one verdict per stock. Return ONLY a JSON array:\n"
        '[{"ticker":"X","company":"Full Company Name",'
        '"alert_level":"STRONG BUY|BUY|WATCH",'
        '"why_now":"1-2 sentences — why catalyst makes this stock interesting NOW",'
        '"technical_status":"1 sentence — technical setup description",'
        '"time_horizon":"1-3 days|1-2 weeks|2-4 weeks",'
        '"risk_warning":"1 sentence — main downside risk",'
        '"action":"specific trade action step",'
        '"learning_note":"1 sentence — why this catalyst connects to this specific company"}]'
    )
    try:
        msg = _ac().messages.create(
            model='claude-haiku-4-5-20251001',
            max_tokens=1500,
            messages=[{"role": "user", "content": prompt}]
        )
        text   = msg.content[0].text.strip()
        result = _extract_json(text, 'array')
        if result:
            return result
    except Exception:
        pass
    return []


# ── Sector Heat Map ───────────────────────────────────────────────────────────

def _sector_heat(top5, catalysts):
    top_tickers     = {r['ticker'] for r in top5}
    catalyst_sectors = set()
    for cat in catalysts:
        for s in cat.get('affected_sectors', []):
            catalyst_sectors.add(s)

    heat = {}
    for sector, tickers in SECTOR_TICKERS.items():
        in_top5   = any(t in top_tickers for t in tickers)
        cat_hit   = sector in catalyst_sectors
        if in_top5 and cat_hit:
            heat[sector] = 'hot'
        elif in_top5 or cat_hit:
            heat[sector] = 'warm'
        else:
            heat[sector] = 'cold'
    return heat


# ── Email helper ──────────────────────────────────────────────────────────────

def _email_top_setups(setups):
    if not Config.EMAIL_SENDER or not Config.EMAIL_PASSWORD:
        return
    try:
        from models.alerts import get_active_recipients
        from utils.emailer import send_intelligence_email
        recipients = get_active_recipients()
        if recipients:
            strong = [s for s in setups if s['combined_score'] >= 80]
            if strong:
                send_intelligence_email(strong, recipients)
    except Exception:
        pass


# ── Core scan function (called by route + scheduler) ─────────────────────────

def run_intelligence_scan():
    from models.intelligence import save_scan

    now = datetime.now()

    catalysts    = []
    market_summary = ''
    try:
        cat_result   = _scan_catalysts()
        catalysts    = cat_result.get('catalysts', [])
        market_summary = cat_result.get('market_summary', '')
    except Exception:
        pass

    top5_scored = []
    try:
        top5_scored = _score_candidates(catalysts)
    except Exception:
        pass

    if not top5_scored:
        return None

    verdicts = []
    try:
        verdicts = _generate_verdicts(top5_scored, catalysts, market_summary)
    except Exception:
        pass

    # Merge scoring data + verdicts
    setups = []
    for i, scored in enumerate(top5_scored):
        v   = verdicts[i] if i < len(verdicts) else {}
        brk = scored.get('breakout_data') or {}

        cs = scored['combined_score']
        if cs >= 80:   alert_level = 'STRONG BUY'
        elif cs >= 65: alert_level = 'BUY'
        else:          alert_level = 'WATCH'

        setups.append({
            'ticker':          scored['ticker'],
            'company':         v.get('company', scored['ticker']),
            'combined_score':  cs,
            'catalyst_score':  scored['catalyst_score'],
            'breakout_score':  scored['breakout_score'],
            'sentiment_score': scored['sentiment_score'],
            'alert_level':     v.get('alert_level', alert_level) or alert_level,
            'why_now':         v.get('why_now', ''),
            'technical_status':v.get('technical_status', ''),
            'time_horizon':    v.get('time_horizon', '1-2 weeks'),
            'risk_warning':    v.get('risk_warning', ''),
            'action':          v.get('action', ''),
            'learning_note':   v.get('learning_note', ''),
            'entry':           brk.get('entry', '—'),
            'stop':            brk.get('stop',  '—'),
            'target':          brk.get('target','—'),
            'rr':              brk.get('rr', 0),
            'price':           brk.get('price', 0),
            'price_change':    brk.get('price_change', 0),
        })

    heat   = _sector_heat(top5_scored, catalysts)
    run_at = now.isoformat()
    save_scan(run_at, catalysts, setups, heat, market_summary)

    result = {
        'run_at':         run_at,
        'market_summary': market_summary,
        'catalysts':      catalysts,
        'setups':         setups,
        'sector_heat':    heat,
        'timestamp':      now.isoformat(),
        'type_colors':    _TYPE_COLORS,
    }
    _scan_cache['latest'] = {'data': result, 'ts': now}
    _email_top_setups(setups)
    return result


# ── Routes ────────────────────────────────────────────────────────────────────

@intelligence_bp.route('/intelligence/scan', methods=['GET'])
def get_scan():
    now    = datetime.now()
    cached = _scan_cache.get('latest')
    if cached and (now - cached['ts']).total_seconds() < SCAN_TTL:
        return jsonify(cached['data'])

    if not Config.ANTHROPIC_API_KEY:
        return jsonify({'error': 'ANTHROPIC_API_KEY not configured'}), 500

    try:
        result = run_intelligence_scan()
        if not result:
            return jsonify({'error': 'No setups found — markets may be closed or no major catalysts today'}), 404
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@intelligence_bp.route('/intelligence/latest', methods=['GET'])
def get_latest():
    cached = _scan_cache.get('latest')
    if cached:
        return jsonify(cached['data'])
    from models.intelligence import get_latest as db_latest
    row = db_latest()
    if row:
        return jsonify(row)
    return jsonify({'error': 'No intelligence scan yet — click Run Scan'}), 404
