from flask import Blueprint, request, jsonify
import yfinance as yf
from config import Config
from datetime import datetime, timedelta
from utils.dc_patterns import dc_pattern_score, calc_mcdx_series, detect_historical_signals

chart_bp = Blueprint('chart', __name__)
_chart_cache    = {}   # (ticker, tf) → data,  1 h TTL
_analysis_cache = {}   # ticker       → text,  1 h TTL
CHART_TTL = 3600


# ── OHLCV fetch + resamplers ──────────────────────────────────────────────────

def _fetch(ticker, days=120):
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
        'o': df['Open'].tolist(),
        'v': df['Volume'].tolist(),
        't': [int(ts.timestamp()) for ts in df.index.to_pydatetime()],
    }


def _resample(raw, period):
    """Group daily candles into weekly (period=5) or monthly (period=21) bars."""
    c,h,l,o,v,t = raw['c'],raw['h'],raw['l'],raw['o'],raw['v'],raw['t']
    rc,rh,rl,ro,rv,rt = [],[],[],[],[],[]
    n = len(c)
    i = 0
    while i < n:
        e = min(i+period, n)
        rc.append(c[e-1]); rh.append(max(h[i:e])); rl.append(min(l[i:e]))
        ro.append(o[i]);    rv.append(sum(v[i:e])); rt.append(t[e-1])
        i = e
    return {'c':rc,'h':rh,'l':rl,'o':ro,'v':rv,'t':rt}


# ── Indicator series ──────────────────────────────────────────────────────────

def _ema_s(prices, period):
    if len(prices) < period:
        return [None]*len(prices)
    k   = 2/(period+1)
    val = sum(prices[:period])/period
    out = [None]*(period-1) + [round(val,4)]
    for p in prices[period:]:
        val = p*k + val*(1-k)
        out.append(round(val,4))
    return out

def _rsi_s(prices, period=14):
    out = [None]*len(prices)
    if len(prices) < period+1:
        return out
    for i in range(period, len(prices)):
        g = [max(prices[j]-prices[j-1],0) for j in range(i-period+1,i+1)]
        ls = [max(prices[j-1]-prices[j],0) for j in range(i-period+1,i+1)]
        ag,al = sum(g)/period, sum(ls)/period
        out[i] = 100.0 if al==0 else round(100-100/(1+ag/al),1)
    return out

def _bb_s(prices, period=20):
    up,md,dn = [],[],[]
    for i in range(len(prices)):
        if i < period-1:
            up.append(None); md.append(None); dn.append(None)
        else:
            w   = prices[i-period+1:i+1]
            sma = sum(w)/period
            std = (sum((p-sma)**2 for p in w)/period)**0.5
            up.append(round(sma+2*std,4)); md.append(round(sma,4)); dn.append(round(sma-2*std,4))
    return up,md,dn

def _macd_s(prices):
    n = len(prices)
    if n < 26:
        return [None]*n,[None]*n,[None]*n
    def es(data, p):
        k=2/(p+1); r=[None]*(p-1); v=sum(data[:p])/p; r.append(round(v,4))
        for x in data[p:]: v=x*k+v*(1-k); r.append(round(v,4))
        return r
    e12=es(prices,12); e26=es(prices,26)
    ml=[round(a-b,4) if a and b else None for a,b in zip(e12,e26)]
    valid=[(i,v) for i,v in enumerate(ml) if v is not None]
    sl=[None]*n
    if len(valid)>=9:
        vals=[v for _,v in valid]; k=2/10; sig=sum(vals[:9])/9
        sl[valid[8][0]]=round(sig,4)
        for j in range(9,len(valid)):
            sig=vals[j]*k+sig*(1-k); sl[valid[j][0]]=round(sig,4)
    ht=[round(m-s,4) if m and s else None for m,s in zip(ml,sl)]
    return ml,sl,ht


# ── Key Level Detection ───────────────────────────────────────────────────────

def detect_key_levels(closes, highs, lows):
    current = closes[-1]
    n       = len(closes)
    tol     = current * 0.005   # 0.5% cluster tolerance

    # Local extrema (windows of 2)
    loc_max = [highs[i] for i in range(1, n-1)
               if highs[i] >= highs[i-1] and highs[i] >= highs[i+1]]
    loc_min = [lows[i]  for i in range(1, n-1)
               if lows[i] <= lows[i-1] and lows[i] <= lows[i+1]]

    def cluster(prices, level_type, min_t=2):
        out, used = [], [False]*len(prices)
        for i, p in enumerate(prices):
            if used[i]: continue
            grp = [p]
            for j, q in enumerate(prices):
                if i!=j and not used[j] and abs(p-q)<=tol:
                    grp.append(q); used[j]=True
            used[i]=True
            if len(grp) >= min_t:
                avg = sum(grp)/len(grp)
                s   = 'strong' if len(grp)>=4 else 'moderate' if len(grp)>=3 else 'weak'
                out.append({'price':round(avg,2),'type':level_type,'strength':s,'touches':len(grp)})
        return out

    res = cluster([h for h in loc_max if h > current], 'resistance')
    sup = cluster([l for l in loc_min if l < current], 'support')

    # Previous week & month extremes
    all_existing = res + sup
    def add_if_new(price, label, lt):
        if not any(abs(x['price']-price)<=tol for x in all_existing):
            tgt = res if lt=='resistance' else sup
            tgt.append({'price':round(price,2),'type':lt,'strength':'weak','touches':1,'label':label})

    if n >= 10:
        add_if_new(max(highs[-10:-5]),'Prev Wk H','resistance' if max(highs[-10:-5])>current else 'support')
        add_if_new(min(lows[-10:-5]), 'Prev Wk L','support'    if min(lows[-10:-5])<current  else 'resistance')
    if n >= 40:
        add_if_new(max(highs[-40:-20]),'Prev Mo H','resistance' if max(highs[-40:-20])>current else 'support')
        add_if_new(min(lows[-40:-20]), 'Prev Mo L','support'    if min(lows[-40:-20])<current  else 'resistance')

    # Round numbers
    for step in [1,5,10,25,50,100,250,500]:
        base = int(current/step)*step
        for rn in [base-step, base, base+step, base+2*step]:
            if current*0.85 < rn < current*1.18 and rn>0:
                if not any(abs(x['price']-rn)<=rn*0.008 for x in all_existing):
                    lt = 'resistance' if rn>current else 'support'
                    tgt = res if lt=='resistance' else sup
                    tgt.append({'price':float(rn),'type':lt,'strength':'weak','touches':0,'round_number':True})

    res.sort(key=lambda x: x['price'])
    sup.sort(key=lambda x: x['price'], reverse=True)
    return (res[:4] + sup[:4])


# ── Trend Analysis ────────────────────────────────────────────────────────────

def analyze_trend(closes, period=60):
    n      = min(period, len(closes))
    prices = closes[-n:]
    xm     = (n-1)/2
    ym     = sum(prices)/n
    ssxy   = sum((i-xm)*(p-ym) for i,p in enumerate(prices))
    ssxx   = sum((i-xm)**2    for i  in range(n))
    slope  = ssxy/ssxx if ssxx else 0
    intcpt = ym - slope*xm
    y_pred = [slope*i+intcpt for i in range(n)]
    ss_res = sum((y-yp)**2 for y,yp in zip(prices,y_pred))
    ss_tot = sum((y-ym)**2  for y   in prices) or 1
    r2     = max(0, 1-ss_res/ss_tot)
    slope_pct = (slope*n/prices[0])*100 if prices[0] else 0
    if   slope_pct >  5 and r2>0.25: direction='uptrend'
    elif slope_pct < -5 and r2>0.25: direction='downtrend'
    else:                             direction='sideways'
    strength = 'strong' if r2>0.65 else 'moderate' if r2>0.35 else 'weak'
    return {
        'direction': direction,
        'strength':  strength,
        'slope_pct': round(slope_pct,1),
        'r_squared': round(r2,2),
        'trend_start': round(intcpt,2),
        'trend_end':   round(slope*(n-1)+intcpt,2),
    }


# ── Pattern Recognition ───────────────────────────────────────────────────────

def detect_pattern(closes, highs, lows, volumes):
    n = len(closes)
    if n < 30:
        return None
    cur = closes[-1]

    # ── Bull Flag ──────────────────────────────────────────────────────────────
    def bull_flag():
        for ps in range(8,16):
            if ps+10 > n: continue
            pl = min(lows[-(ps+10):-10])
            ph = max(highs[-(ps+10):-10])
            if (ph-pl)/pl*100 < 8: continue
            fh, fl = max(highs[-10:]), min(lows[-10:])
            if (fh-fl)/fl*100 < 6:
                return {'pattern':'Bull Flag','confidence':min(88,int((ph-pl)/pl*500)),
                        'breakout_level':round(fh*1.002,2),
                        'target':round(fh+(ph-pl),2),
                        'invalidation_level':round(fl*0.99,2),
                        'description':f'Sharp rally + {round((fh-fl)/fl*100,1)}% tight flag consolidation'}
        return None

    # ── VCP ────────────────────────────────────────────────────────────────────
    def vcp():
        if n < 45: return None
        seg = 12
        contractions = []
        for i in range(3):
            s = -(i+1)*seg; e = -i*seg if i else n
            contractions.append((max(highs[s:e])-min(lows[s:e]))/min(lows[s:e])*100)
        c0,c1,c2 = contractions  # c0=recent, c2=oldest
        if c2>c1>c0 and c2>8 and c0<c2*0.55:
            rl = max(highs[-35:])
            return {'pattern':'VCP','confidence':76,
                    'breakout_level':round(rl*1.002,2),
                    'target':round(rl+(rl-min(lows[-35:])),2),
                    'invalidation_level':round(min(lows[-12:])*0.98,2),
                    'description':f'3-stage contraction: {round(c2,1)}%→{round(c1,1)}%→{round(c0,1)}%'}
        return None

    # ── Cup & Handle ───────────────────────────────────────────────────────────
    def cup_handle():
        if n < 55: return None
        lr = max(highs[-55:-35])
        cb = min(lows[-45:-12])
        rr = max(highs[-18:])
        depth = (lr-cb)/lr*100
        rim   = abs(lr-rr)/lr*100
        if 10<depth<42 and rim<12:
            hl = min(lows[-12:])
            if (rr-hl)/(rr-cb)*100 < 45:
                return {'pattern':'Cup & Handle','confidence':72,
                        'breakout_level':round(rr*1.002,2),
                        'target':round(rr+(rr-cb),2),
                        'invalidation_level':round(hl*0.98,2),
                        'description':f'Cup depth {round(depth,1)}%, rims ~${round(lr,2)}'}
        return None

    # ── Double Bottom ──────────────────────────────────────────────────────────
    def double_bottom():
        if n < 30: return None
        h   = n//2
        b1  = min(lows[:h]); b2 = min(lows[h:])
        neck = max(highs[h//2:h+h//2])
        if abs(b1-b2)/b1 < 0.04:
            return {'pattern':'Double Bottom','confidence':68,
                    'breakout_level':round(neck,2),
                    'target':round(neck+(neck-min(b1,b2)),2),
                    'invalidation_level':round(min(b1,b2)*0.98,2),
                    'description':f'Twin lows ~${round((b1+b2)/2,2)}, neckline ${round(neck,2)}'}
        return None

    # ── Flat Base ──────────────────────────────────────────────────────────────
    def flat_base():
        if n < 25: return None
        fh, fl = max(highs[-25:]), min(lows[-25:])
        rng = (fh-fl)/fl*100
        if rng < 10:
            return {'pattern':'Flat Base','confidence':62,
                    'breakout_level':round(fh*1.002,2),
                    'target':round(fh+(fh-fl)*2,2),
                    'invalidation_level':round(fl*0.98,2),
                    'description':f'Only {round(rng,1)}% range over 5 weeks — coiled energy'}
        return None

    for fn in [bull_flag, vcp, cup_handle, double_bottom, flat_base]:
        r = fn()
        if r: return r
    return None


# ── Volume Profile ────────────────────────────────────────────────────────────

def volume_profile(closes, highs, lows, volumes, buckets=20):
    pmin, pmax = min(lows), max(highs)
    rng = pmax-pmin
    if rng <= 0: return []
    bsz     = rng/buckets
    profile = [0.0]*buckets
    for i in range(len(closes)):
        h,l,v = highs[i],lows[i],volumes[i]
        cr = h-l or 1e-6
        for b in range(buckets):
            bl,bh = pmin+b*bsz, pmin+(b+1)*bsz
            ov = min(h,bh)-max(l,bl)
            if ov>0: profile[b] += (ov/cr)*v
    mx = max(profile) or 1
    return [{'price':round(pmin+(b+0.5)*bsz,2),'pct':round(profile[b]/mx*100,1)} for b in range(buckets)]


# ── Pre-breakout helpers (kept from v1) ───────────────────────────────────────

def _squeeze(bbu, bbl, lookback=20):
    ws = [u-l for u,l in zip(bbu[-lookback:],bbl[-lookback:]) if u and l]
    if not ws: return False,0
    cw = ws[-1]; aw = sum(ws)/len(ws)
    return cw<=aw*0.75, round((1-cw/aw)*100,1)

def _accum(vols, lookback=10):
    if len(vols)<lookback+20: return False,0
    avg = sum(vols[-30:-lookback])/(30-lookback)
    ab  = sum(1 for v in vols[-lookback:] if v>avg)
    return ab>=lookback*0.6, int(ab/lookback*100)

def _resist(highs, closes, lookback=30):
    cur = closes[-1]
    pot = [h for h in highs[-lookback:] if h>cur*1.01]
    return round(min(pot),2) if pot else None


# ── Claude AI Analysis ────────────────────────────────────────────────────────

def _ai_analysis(ticker, current_price, trend, pattern, key_levels, rsi_val):
    if not Config.ANTHROPIC_API_KEY:
        return None
    now = datetime.now()
    cached = _analysis_cache.get(ticker)
    if cached and (now-cached['ts']).total_seconds() < CHART_TTL:
        return cached['data']
    try:
        import anthropic
        ac   = anthropic.Anthropic(api_key=Config.ANTHROPIC_API_KEY)
        res  = [l for l in key_levels if l['type']=='resistance'][:2]
        sup  = [l for l in key_levels if l['type']=='support'][:2]
        rtxt = ', '.join(f"${l['price']} ({l['strength']}, {l['touches']} touches)" for l in res) or 'none nearby'
        stxt = ', '.join(f"${l['price']} ({l['strength']}, {l['touches']} touches)" for l in sup) or 'none nearby'
        ptxt = f"{pattern['pattern']} — {pattern['description']}" if pattern else 'no clear pattern'
        prompt = (
            f"Write a professional chart analysis for {ticker} at ${current_price}.\n\n"
            f"Chart facts:\n"
            f"- Trend (60 days): {trend['direction']} ({trend['strength']}, {trend['slope_pct']}% slope)\n"
            f"- RSI: {rsi_val}\n"
            f"- Key resistance: {rtxt}\n"
            f"- Key support: {stxt}\n"
            f"- Chart pattern: {ptxt}\n\n"
            "Write EXACTLY 3 short paragraphs for someone learning to trade. No jargon. Use specific $ levels.\n\n"
            "Para 1 (2-3 sentences): Big picture trend — where is this stock? Uptrend/downtrend/basing?\n"
            "Para 2 (2-3 sentences): Current setup — what is happening now? What pattern is forming?\n"
            "Para 3 (2-3 sentences): What to watch — specific price levels and conditions. What confirms a buy? What signals danger?\n\n"
            "Plain English only. Specific numbers. No bullet points."
        )
        msg  = ac.messages.create(
            model='claude-haiku-4-5-20251001', max_tokens=500,
            messages=[{"role":"user","content":prompt}]
        )
        text = msg.content[0].text.strip()
        _analysis_cache[ticker] = {'data':text,'ts':now}
        return text
    except Exception:
        return None


# ── Routes ────────────────────────────────────────────────────────────────────

@chart_bp.route('/chart/<ticker>', methods=['GET'])
def get_chart_data(ticker):
    ticker = ticker.upper().strip()
    tf     = request.args.get('tf', '1D')  # 1D | 1W | 1M
    now    = datetime.now()

    cache_key = f"{ticker}_{tf}"
    cached = _chart_cache.get(cache_key)
    if cached and (now-cached['ts']).total_seconds() < CHART_TTL:
        return jsonify(cached['data'])

    try:
        # Fetch raw data
        days = {'1D':130,'1W':420,'1M':760}.get(tf,130)
        raw  = _fetch(ticker, days)
        if not raw:
            return jsonify({"error":f"No chart data for {ticker}"}),404

        # Resample
        if tf=='1W': raw = _resample(raw,5)
        elif tf=='1M': raw = _resample(raw,21)

        c,h,l,o,v,t = raw['c'],raw['h'],raw['l'],raw['o'],raw['v'],raw['t']
        n = min(90 if tf=='1D' else 60 if tf=='1W' else 36, len(c))
        c,h,l,o,v,t = c[-n:],h[-n:],l[-n:],o[-n:],v[-n:],t[-n:]

        if tf=='1D':
            dates = [datetime.fromtimestamp(ts).strftime('%b %d') for ts in t]
        elif tf=='1W':
            dates = [datetime.fromtimestamp(ts).strftime('%b %d') for ts in t]
        else:
            dates = [datetime.fromtimestamp(ts).strftime('%b %Y') for ts in t]

        ema20 = _ema_s(c,20)
        ema50 = _ema_s(c,min(50,n))
        rsi   = _rsi_s(c)
        bbu,bbm,bbl = _bb_s(c)
        ml,sl,ht = _macd_s(c)

        # Full-history signals (pre-breakout)
        fc  = raw['c']; fh=raw['h']; fl=raw['l']; fo=raw['o']; fv=raw['v']
        fbbu,_,fbbl = _bb_s(fc)
        fbm         = [(u+lo)/2 if u and lo else None for u,lo in zip(fbbu,fbbl)]
        is_sq,sq_p  = _squeeze(fbbu,fbbl)
        is_ac,ac_s  = _accum(fv)
        resist      = _resist(fh,fc)
        cur         = c[-1]
        nr          = resist and (resist-cur)/cur<0.05
        crsi        = next((v for v in reversed(rsi) if v),None)
        cmacd       = next((v for v in reversed(ht) if v),None)
        cmacd_prev  = next((v for v in reversed(ht[:-1]) if v),None)
        rsi_bld     = crsi and 40<crsi<60
        macd_turn   = cmacd and cmacd>0 and cmacd_prev and cmacd_prev<cmacd
        sig_count   = sum([is_sq,is_ac,bool(nr),bool(rsi_bld),bool(macd_turn)])

        # Professional analysis
        key_levels   = detect_key_levels(c,h,l)
        trend        = analyze_trend(c)
        pattern      = detect_pattern(c,h,l,v)
        vol_prof     = volume_profile(c,h,l,v)

        # Danny Cheng pattern score + MCDX series
        try:
            dc       = dc_pattern_score(fc, fo, fh, fl, fv)
            mcdx_all = dc['mcdx_series']
            # Trim MCDX to match visible window
            mcdx_vis = mcdx_all[-n:] if len(mcdx_all) >= n else mcdx_all
        except Exception:
            dc       = None
            mcdx_vis = [None] * n

        # Historical signal markers on visible window
        try:
            hist_signals = detect_historical_signals(fc, fo, fh, fl, fv, n_visible=n)
        except Exception:
            hist_signals = []

        # Pre-breakout explanations (kept for backward compat)
        explanations = []
        if is_sq:   explanations.append({"signal":"🔍 BOLLINGER SQUEEZE","color":"cyan","short":f"Bands {sq_p}% narrower than avg","explain":"Price coiled in tight range — breakout building. Volume surge signals direction."})
        if is_ac:   explanations.append({"signal":"📦 VOLUME ACCUMULATION","color":"green","short":f"{ac_s}% of recent days above avg volume","explain":"Quiet above-avg volume without big price moves — institutions slowly loading."})
        if nr and resist: explanations.append({"signal":"🚪 AT KEY RESISTANCE","color":"amber","short":f"${resist} only {round((resist-cur)/cur*100,1)}% away","explain":f"${resist} is where sellers previously stepped in. Break with volume triggers a powerful move."})
        if rsi_bld: explanations.append({"signal":"⚡ RSI IN LAUNCH ZONE","color":"green","short":f"RSI {crsi} — not overbought, room to run","explain":f"RSI {crsi}: momentum building but not stretched. Ideal zone for breakout entry."})
        if macd_turn: explanations.append({"signal":"📈 MACD TURNING UP","color":"green","short":"Momentum shifting positive","explain":"MACD histogram growing — buying momentum accelerating, often precedes price breakout."})
        if not explanations: explanations.append({"signal":"⏸ NO PRE-BREAKOUT SIGNAL","color":"neutral","short":"Waiting for setup","explain":"Key conditions haven't aligned yet. Add to watchlist and check again."})

        result = {
            "ticker": ticker,
            "timeframe": tf,
            "dates": dates,
            "candles": {"open":[round(x,2) for x in o],"high":[round(x,2) for x in h],
                        "low":[round(x,2) for x in l],"close":[round(x,2) for x in c]},
            "volume": [int(x) for x in v],
            "indicators": {"ema20":ema20,"ema50":ema50,"bb_upper":bbu,"bb_mid":bbm,"bb_lower":bbl,
                           "rsi":rsi,"macd_line":ml,"signal_line":sl,"histogram":ht,
                           "mcdx": mcdx_vis},
            "key_levels":  key_levels,
            "trend":       trend,
            "pattern":     pattern,
            "volume_profile": vol_prof,
            "dc_patterns": {
                "score":       dc['score']       if dc else 0,
                "label":       dc['label']       if dc else 'NO DATA',
                "color":       dc['color']       if dc else 'neutral',
                "signals":     dc['signals']     if dc else [],
                "mcdx_signal": dc['mcdx_signal'] if dc else 'NEUTRAL',
                "mcdx_value":  dc['mcdx_value']  if dc else 0,
            } if dc else None,
            "historical_signals": hist_signals,
            "prebreakout": {"score":sig_count*20,"is_squeeze":is_sq,"squeeze_pct":sq_p,
                            "is_accumulating":is_ac,"accum_score":ac_s,
                            "near_resistance":bool(nr),"resistance":resist,
                            "rsi_building":bool(rsi_bld),"macd_turning":bool(macd_turn),
                            "signals_count":sig_count},
            "explanations": explanations,
            "current_price": round(cur,2),
            "timestamp": now.isoformat(),
        }
        _chart_cache[cache_key] = {'data':result,'ts':now}
        return jsonify(result)

    except Exception as e:
        return jsonify({"error":str(e)}),500


@chart_bp.route('/chart/<ticker>/analysis', methods=['GET'])
def get_chart_analysis(ticker):
    ticker = ticker.upper().strip()
    # Fetch from main cache first to reuse computed data
    cached_chart = _chart_cache.get(f"{ticker}_1D")
    if cached_chart:
        d = cached_chart['data']
        rsi_val = next((v for v in reversed(d['indicators']['rsi']) if v), None)
        text = _ai_analysis(ticker, d['current_price'], d['trend'],
                            d['pattern'], d['key_levels'], rsi_val)
    else:
        text = None
    if not text:
        return jsonify({'error':'Analysis not ready — load chart first'}), 404
    return jsonify({'ticker':ticker,'analysis':text,'timestamp':datetime.now().isoformat()})
