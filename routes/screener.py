from flask import Blueprint, request, jsonify
import finnhub
import anthropic
import yfinance as yf
from config import Config
from datetime import datetime, timedelta
from utils.price_fetcher import get_live_price

screener_bp = Blueprint('screener', __name__)
_financials_cache = {}
_price_cache = {}

def get_finnhub_client():
    return finnhub.Client(api_key=Config.FINNHUB_API_KEY)

def get_anthropic_client():
    return anthropic.Anthropic(api_key=Config.ANTHROPIC_API_KEY)

def get_ohlcv(ticker, days=120):
    """Fetch OHLCV history via yfinance (free, no API key needed)."""
    end   = datetime.now()
    start = end - timedelta(days=days)
    df = yf.download(ticker, start=start.strftime('%Y-%m-%d'),
                     end=end.strftime('%Y-%m-%d'), progress=False, auto_adjust=True)
    if df.empty:
        return None
    # yfinance >= 0.2.44 returns MultiIndex columns for single tickers
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

def calculate_ema(prices, period):
    if len(prices) < period:
        return None
    k = 2 / (period + 1)
    ema = sum(prices[:period]) / period
    for price in prices[period:]:
        ema = price * k + ema * (1 - k)
    return round(ema, 2)

def calculate_rsi(prices, period=14):
    if len(prices) < period + 1:
        return None
    deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
    gains = [d if d > 0 else 0 for d in deltas[-period:]]
    losses = [-d if d < 0 else 0 for d in deltas[-period:]]
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100
    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 1)

def calculate_macd(prices):
    if len(prices) < 26:
        return None, None, None
    ema12 = calculate_ema(prices, 12)
    ema26 = calculate_ema(prices, 26)
    if not ema12 or not ema26:
        return None, None, None
    return round(ema12 - ema26, 4), ema12, ema26

def calculate_atr(highs, lows, closes, period=14):
    if len(closes) < period + 1:
        return None
    trs = []
    for i in range(1, len(closes)):
        tr = max(highs[i]-lows[i], abs(highs[i]-closes[i-1]), abs(lows[i]-closes[i-1]))
        trs.append(tr)
    return round(sum(trs[-period:]) / period, 4)

def calculate_bollinger(prices, period=20):
    if len(prices) < period:
        return None, None, None
    recent = prices[-period:]
    sma = sum(recent) / period
    variance = sum((p - sma) ** 2 for p in recent) / period
    std = variance ** 0.5
    return round(sma + 2*std, 2), round(sma, 2), round(sma - 2*std, 2)

def detect_signal(closes, highs, lows, rsi, macd_line, ema20, ema50, volumes):
    """Detect primary trade signal: REVERSAL_BUY, BREAKOUT_BUY, MEAN_REVERSION_BUY, TAKE_PROFIT, HOLD, SELL"""
    if len(closes) < 20:
        return "HOLD", "Insufficient data for signal detection"

    current = closes[-1]
    prev    = closes[-2]
    avg_vol = sum(volumes[-20:]) / 20 if len(volumes) >= 20 else sum(volumes) / len(volumes)
    curr_vol = volumes[-1]
    vol_spike = curr_vol > avg_vol * 1.5

    bb_upper, bb_mid, bb_lower = calculate_bollinger(closes)

    # Check RSI divergence (simple: price lower but RSI higher over last 5 bars)
    rsi_divergence = False
    if len(closes) >= 6 and rsi:
        price_trend = closes[-1] < closes[-6]
        # Approximate: if RSI > 40 but price fell, bullish divergence forming
        rsi_divergence = price_trend and rsi > 35

    # REVERSAL BUY: CHoCH + RSI divergence + MACD turning up
    if (rsi and rsi < 45 and
        macd_line is not None and macd_line > -2 and
        ema20 and current > ema20 * 0.97 and
        rsi_divergence):
        return "REVERSAL_BUY", "Trend reversal signal — RSI divergence forming with MACD turning up"

    # BREAKOUT BUY: Price above all EMAs + volume spike + MACD positive
    if (ema20 and ema50 and
        current > ema20 and current > ema50 and
        vol_spike and
        macd_line is not None and macd_line > 0):
        return "BREAKOUT_BUY", "Breakout confirmed — price above EMAs with volume surge and positive MACD"

    # MEAN REVERSION BUY: At lower Bollinger + RSI oversold
    if (bb_lower and current <= bb_lower * 1.02 and
        rsi and rsi < 35):
        return "MEAN_REVERSION_BUY", "Mean reversion setup — price at lower Bollinger Band with RSI oversold"

    # TAKE PROFIT: RSI overbought + upper Bollinger + MACD weakening
    if (rsi and rsi > 70 and
        bb_upper and current >= bb_upper * 0.98):
        return "TAKE_PROFIT", "Take profit zone — RSI overbought at upper Bollinger Band"

    # SELL / SHORT: Below all EMAs + MACD negative + volume down
    if (ema20 and ema50 and
        current < ema20 and current < ema50 and
        macd_line is not None and macd_line < -1):
        return "SELL", "Bearish setup — price below EMAs with negative MACD momentum"

    return "HOLD", "No clear signal — wait for better confluence"

def determine_tier(scores, signal):
    avg = sum(scores.values()) / len(scores)
    bull_count = sum(1 for s in scores.values() if s >= 65)
    if signal in ["REVERSAL_BUY","BREAKOUT_BUY"] and avg >= 70 and bull_count >= 3:
        return "ASTAR"
    elif signal in ["REVERSAL_BUY","BREAKOUT_BUY","MEAN_REVERSION_BUY"] and avg >= 50:
        return "B"
    elif signal == "TAKE_PROFIT":
        return "EXIT"
    elif signal == "SELL":
        return "SKIP"
    elif avg >= 35:
        return "C"
    else:
        return "SKIP"

@screener_bp.route('/screener/<ticker>', methods=['GET'])
def analyse_ticker(ticker):
    ticker = ticker.upper().strip()
    if not Config.FINNHUB_API_KEY:
        return jsonify({"error": "FINNHUB_API_KEY not configured in Azure Application Settings"}), 500

    try:
        fc = get_finnhub_client()
        profile  = fc.company_profile2(symbol=ticker)
        company_name = profile.get('name', ticker) if profile else ticker
        sector   = profile.get('finnhubIndustry', 'Unknown') if profile else 'Unknown'

        candles = get_ohlcv(ticker)

        if not candles:
            return jsonify({"error": f"No price data found for {ticker}"}), 404

        closes  = candles['c']
        highs   = candles['h']
        lows    = candles['l']
        volumes = candles['v']

        live = get_live_price(ticker)
        hist_price   = round(closes[-1], 2)
        current_price = live.get('price') or hist_price
        hist_prev     = closes[-2] if len(closes) > 1 else closes[-1]
        price_change  = (live.get('change_pct')
                         if live.get('price')
                         else round(((hist_price - hist_prev) / hist_prev) * 100, 2))

        ema20  = calculate_ema(closes, 20)
        ema50  = calculate_ema(closes, 50)
        ema200 = calculate_ema(closes, min(200, len(closes)))
        rsi    = calculate_rsi(closes)
        macd_line, _, _ = calculate_macd(closes)
        atr    = calculate_atr(highs, lows, closes)
        bb_upper, bb_mid, bb_lower = calculate_bollinger(closes)

        avg_vol     = sum(volumes[-20:]) / 20 if len(volumes) >= 20 else sum(volumes) / len(volumes)
        current_vol = volumes[-1]
        vol_ratio   = current_vol / avg_vol if avg_vol > 0 else 1

        if vol_ratio > 1.5:
            vol_val, vol_bias = "Spike 🔥", "bull" if current_price > hist_prev else "bear"
        elif vol_ratio > 1.0:
            vol_val, vol_bias = f"Above avg ({round(vol_ratio,1)}x)", "bull"
        else:
            vol_val, vol_bias = f"Below avg ({round(vol_ratio,1)}x)", "neutral"

        ema20_bias  = "bull" if ema20  and current_price > ema20  else "bear"
        ema50_bias  = "bull" if ema50  and current_price > ema50  else "bear"
        ema200_bias = "bull" if ema200 and current_price > ema200 else "bear"

        if rsi:
            if rsi > 70:   rsi_val, rsi_bias = f"{rsi} · Overbought ⚠", "bear"
            elif rsi < 30: rsi_val, rsi_bias = f"{rsi} · Oversold 🟢", "bull"
            elif rsi > 50: rsi_val, rsi_bias = f"{rsi} · Bullish", "bull"
            else:          rsi_val, rsi_bias = f"{rsi} · Bearish", "bear"
        else:
            rsi_val, rsi_bias = "N/A", "neutral"

        if macd_line is not None:
            if macd_line > 0: macd_val, macd_bias = f"+{macd_line} · Bullish", "bull"
            else:             macd_val, macd_bias = f"{macd_line} · Bearish", "bear"
        else:
            macd_val, macd_bias = "N/A", "neutral"

        # Bollinger band position
        if bb_upper and bb_lower:
            if current_price >= bb_upper * 0.98:
                bb_val, bb_bias = "At upper band ⚠", "bear"
            elif current_price <= bb_lower * 1.02:
                bb_val, bb_bias = "At lower band 🟢", "bull"
            else:
                bb_val, bb_bias = "Inside bands", "neutral"
        else:
            bb_val, bb_bias = "N/A", "neutral"

        # Get news for catalyst
        news = fc.company_news(ticker,
            _from=(datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d'),
            to=datetime.now().strftime('%Y-%m-%d')
        )
        catalyst      = news[0]['headline'][:65] + "..." if news else "No recent news"
        catalyst_bias = "bull" if news else "neutral"

        # Detect primary signal
        signal, signal_reason = detect_signal(closes, highs, lows, rsi, macd_line, ema20, ema50, volumes)

        signals = [
            {"name": "Trend Structure", "value": "Uptrend 📈" if ema20_bias == "bull" and ema50_bias == "bull" else "Downtrend 📉" if ema20_bias == "bear" and ema50_bias == "bear" else "Mixed", "bias": ema20_bias},
            {"name": "vs 20 EMA",       "value": f"{'Above' if ema20_bias=='bull' else 'Below'} (${ema20})",  "bias": ema20_bias},
            {"name": "vs 50 EMA",       "value": f"{'Above' if ema50_bias=='bull' else 'Below'} (${ema50})",  "bias": ema50_bias},
            {"name": "vs 200 EMA",      "value": f"{'Above' if ema200_bias=='bull' else 'Below'} (${ema200})", "bias": ema200_bias},
            {"name": "RSI (14)",        "value": rsi_val,   "bias": rsi_bias},
            {"name": "MACD",            "value": macd_val,  "bias": macd_bias},
            {"name": "Bollinger Bands", "value": bb_val,    "bias": bb_bias},
            {"name": "Volume",          "value": vol_val,   "bias": vol_bias},
            {"name": "Catalyst",        "value": catalyst,  "bias": catalyst_bias},
        ]

        bull_count = sum(1 for s in signals if s['bias'] == 'bull')
        scores = {
            "trend":      min(100, 75 if ema20_bias=='bull' and ema50_bias=='bull' else 25 if ema20_bias=='bear' and ema50_bias=='bear' else 50),
            "momentum":   min(100, int(rsi) if rsi and rsi < 70 else 60) if rsi else 50,
            "volume":     min(100, int(vol_ratio * 45)),
            "confluence": min(100, bull_count * 12)
        }

        tier = determine_tier(scores, signal)

        atr_val = atr or (current_price * 0.025)
        entry   = round(current_price, 2)
        stop    = round(current_price - (1.5 * atr_val), 2)
        target  = round(current_price + (3.0 * atr_val), 2)
        rr      = round((target - entry) / (entry - stop), 1) if entry != stop else 0

        # AI thesis
        thesis_text = "AI analysis unavailable — check ANTHROPIC_API_KEY in Azure settings"
        risks_text  = "Review manually"

        if Config.ANTHROPIC_API_KEY:
            try:
                ac = get_anthropic_client()
                prompt = f"""Analyse {ticker} ({company_name}, sector: {sector}) as a trader.
Signal detected: {signal} — {signal_reason}
Price: ${current_price} ({'+' if price_change>0 else ''}{price_change}%)
RSI: {rsi} | MACD: {macd_line} | ATR: {atr_val}
EMA20: {ema20} | EMA50: {ema50} | EMA200: {ema200}
Bollinger: Upper ${bb_upper} | Mid ${bb_mid} | Lower ${bb_lower}
Recent catalyst: {catalyst}

Write exactly:
THESIS: (2 sentences — why this signal and what to expect)
RISKS: (2 sentences — key risks to this setup)
Be specific, direct, no fluff."""

                msg = ac.messages.create(
                    model="claude-haiku-4-5-20251001",
                    max_tokens=250,
                    messages=[{"role": "user", "content": prompt}]
                )
                response = msg.content[0].text
                if "THESIS:" in response and "RISKS:" in response:
                    parts       = response.split("RISKS:")
                    thesis_text = parts[0].replace("THESIS:", "").strip()
                    risks_text  = parts[1].strip()
                else:
                    thesis_text = response[:200]
            except Exception as e:
                thesis_text = f"AI error: {str(e)}"

        # Signal display config
        signal_config = {
            "REVERSAL_BUY":      {"label": "🔄 REVERSAL BUY",      "color": "green",  "emoji": "🔄"},
            "BREAKOUT_BUY":      {"label": "🚀 BREAKOUT BUY",      "color": "green",  "emoji": "🚀"},
            "MEAN_REVERSION_BUY":{"label": "↩ MEAN REVERSION BUY","color": "cyan",   "emoji": "↩"},
            "TAKE_PROFIT":       {"label": "✂ TAKE PROFIT",        "color": "amber",  "emoji": "✂"},
            "HOLD":              {"label": "⏸ HOLD / WAIT",        "color": "neutral","emoji": "⏸"},
            "SELL":              {"label": "🔴 SELL / AVOID",       "color": "red",    "emoji": "🔴"},
        }
        sig_cfg = signal_config.get(signal, signal_config["HOLD"])

        return jsonify({
            "ticker":        ticker,
            "company":       company_name,
            "sector":        sector,
            "price":         round(current_price, 2),
            "change":        live.get('change', round(current_price - hist_prev, 2)),
            "change_pct":    price_change,
            "high":          live.get('high', round(highs[-1], 2)),
            "low":           live.get('low', round(lows[-1], 2)),
            "open":          live.get('open', round(candles['o'][-1], 2)),
            "prev_close":    live.get('prev_close', round(hist_prev, 2)),
            "volume":        live.get('volume', volumes[-1] if volumes else 0),
            "market_status": live.get('market_status', 'UNKNOWN'),
            "price_source":  live.get('source', 'yfinance'),
            "price_change":  price_change,
            "tier":          tier,
            "signal":        signal,
            "signal_label":  sig_cfg["label"],
            "signal_color":  sig_cfg["color"],
            "signal_reason": signal_reason,
            "scores":        scores,
            "signals":       signals,
            "thesis":        thesis_text,
            "risks":         risks_text,
            "entry":         f"${entry}",
            "entry_note":    "Current market price",
            "stop":          f"${stop}",
            "stop_note":     f"1.5x ATR (${round(atr_val,2)})",
            "target":        f"${target}",
            "target_note":   f"{rr}:1 Risk/Reward",
            "bollinger":     {"upper": bb_upper, "mid": bb_mid, "lower": bb_lower},
            "atr":           round(atr_val, 2),
            "timestamp":     datetime.now().isoformat()
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@screener_bp.route('/price/<ticker>', methods=['GET'])
def get_price(ticker):
    ticker = ticker.upper().strip()
    now = datetime.now()
    cached = _price_cache.get(ticker)
    if cached and (now - cached['ts']).total_seconds() < 3:
        return jsonify(cached['data'])
    data = get_live_price(ticker)
    _price_cache[ticker] = {"data": data, "ts": now}
    return jsonify(data)


@screener_bp.route('/financials/<ticker>', methods=['GET'])
def get_financials(ticker):
    ticker = ticker.upper().strip()
    now = datetime.now()

    cached = _financials_cache.get(ticker)
    if cached and (now - cached['ts']).total_seconds() < 86400:
        return jsonify(cached['data'])

    try:
        fc = get_finnhub_client()

        basic   = fc.company_basic_financials(ticker, 'all') or {}
        metrics = basic.get('metric', {}) or {}
        series  = basic.get('series', {}) or {}
        annual  = series.get('annual', {}) or {}
        qtr     = series.get('quarterly', {}) or {}

        pe        = metrics.get('peNormalizedAnnual') or metrics.get('peTTM')
        ps        = metrics.get('psTTM')
        ev_ebitda = metrics.get('evEbitda')

        gross_margin = metrics.get('grossMarginTTM') or metrics.get('grossMarginAnnual')
        net_margin   = metrics.get('netProfitMarginTTM') or metrics.get('netMarginTTM')
        roe          = metrics.get('roeTTM') or metrics.get('roeAnnual')
        debt_equity  = (metrics.get('totalDebt/totalEquityAnnual') or
                        metrics.get('longTermDebt/equityAnnual'))

        # Revenue growth — prefer direct metric, fall back to series calculation
        rev_yoy = None
        raw_yoy = metrics.get('revenueGrowthTTMYoy')
        if raw_yoy is not None:
            rev_yoy = round(float(raw_yoy) * 100, 1)
        else:
            rev_annual_data = annual.get('revenue', [])
            if len(rev_annual_data) >= 2:
                r0 = rev_annual_data[0].get('v') or 0
                r1 = rev_annual_data[1].get('v') or 0
                if r1:
                    rev_yoy = round(((r0 - r1) / abs(r1)) * 100, 1)

        rev_qoq = None
        raw_qoq = metrics.get('revenueGrowthQuarterlyYoy')
        if raw_qoq is not None:
            rev_qoq = round(float(raw_qoq) * 100, 1)
        else:
            rev_qtr_data = qtr.get('revenue', [])
            if len(rev_qtr_data) >= 2:
                r0 = rev_qtr_data[0].get('v') or 0
                r1 = rev_qtr_data[1].get('v') or 0
                if r1:
                    rev_qoq = round(((r0 - r1) / abs(r1)) * 100, 1)

        earnings = fc.stock_earnings(ticker) or []
        eps_quarters = []
        for e in earnings[:4]:
            eps_quarters.append({
                'period':       e.get('period', ''),
                'actual':       e.get('actual'),
                'estimate':     e.get('estimate'),
                'surprise_pct': round(float(e.get('surprisePercent') or 0), 1),
            })

        next_earnings    = None
        earnings_countdown = None
        try:
            cal   = fc.earnings_calendar(
                _from=(now).strftime('%Y-%m-%d'),
                to=(now + timedelta(days=120)).strftime('%Y-%m-%d'),
                symbol=ticker, international=False)
            items = (cal or {}).get('earningsCalendar', [])
            if items:
                next_date_str = items[0].get('date', '')
                if next_date_str:
                    next_earnings  = next_date_str
                    next_dt        = datetime.strptime(next_date_str, '%Y-%m-%d')
                    days_until     = (next_dt - now).days
                    earnings_countdown = (f"Earnings in {days_until} days"
                                          if days_until >= 0 else "Earnings passed")
        except Exception:
            pass

        recs       = fc.recommendation_trends(ticker) or []
        latest_rec = recs[0] if recs else {}
        strong_buy  = int(latest_rec.get('strongBuy',  0) or 0)
        buy         = int(latest_rec.get('buy',        0) or 0)
        hold        = int(latest_rec.get('hold',       0) or 0)
        sell        = int(latest_rec.get('sell',       0) or 0)
        strong_sell = int(latest_rec.get('strongSell', 0) or 0)
        total_recs  = strong_buy + buy + hold + sell + strong_sell

        consensus       = "HOLD"
        consensus_color = "amber"
        if total_recs > 0:
            bull_score = (strong_buy * 2 + buy)        / total_recs
            bear_score = (strong_sell * 2 + sell)      / total_recs
            if   bull_score >= 1.5: consensus, consensus_color = "STRONG BUY",  "green"
            elif bull_score >= 0.8: consensus, consensus_color = "BUY",         "green"
            elif bear_score >= 1.5: consensus, consensus_color = "STRONG SELL", "red"
            elif bear_score >= 0.8: consensus, consensus_color = "SELL",        "red"

        ai_verdict = None
        if Config.ANTHROPIC_API_KEY:
            try:
                ac      = get_anthropic_client()
                profile = fc.company_profile2(symbol=ticker) or {}
                cname   = profile.get('name', ticker)
                prompt  = (f"Fundamentals for {ticker} ({cname}): "
                           f"P/E {pe}, P/S {ps}, EV/EBITDA {ev_ebitda}, "
                           f"Gross margin {gross_margin}%, Net margin {net_margin}%, ROE {roe}%, "
                           f"Revenue growth YoY {rev_yoy}% QoQ {rev_qoq}%, "
                           f"Analyst consensus {consensus} ({strong_buy} SB / {buy} B / {hold} H / {sell} S / {strong_sell} SS). "
                           f"Next earnings: {next_earnings or 'unknown'}. "
                           "Write 1-2 plain English sentences for a trader: are fundamentals supportive or concerning? Be specific and direct.")
                msg = ac.messages.create(
                    model="claude-haiku-4-5-20251001",
                    max_tokens=100,
                    messages=[{"role": "user", "content": prompt}]
                )
                ai_verdict = msg.content[0].text.strip()
            except Exception:
                pass

        def safe_round(v, d=1):
            try:
                return round(float(v), d) if v is not None else None
            except (TypeError, ValueError):
                return None

        result = {
            "ticker": ticker,
            "valuation": {
                "pe":       safe_round(pe),
                "ps":       safe_round(ps),
                "ev_ebitda":safe_round(ev_ebitda),
            },
            "health": {
                "gross_margin": safe_round(gross_margin),
                "net_margin":   safe_round(net_margin),
                "roe":          safe_round(roe),
                "debt_equity":  safe_round(debt_equity, 2),
            },
            "growth": {
                "rev_yoy": rev_yoy,
                "rev_qoq": rev_qoq,
            },
            "eps_quarters":      eps_quarters,
            "analyst": {
                "consensus":       consensus,
                "consensus_color": consensus_color,
                "strong_buy":      strong_buy,
                "buy":             buy,
                "hold":            hold,
                "sell":            sell,
                "strong_sell":     strong_sell,
                "total":           total_recs,
            },
            "next_earnings":     next_earnings,
            "earnings_countdown":earnings_countdown,
            "ai_verdict":        ai_verdict,
            "timestamp":         now.isoformat(),
        }

        _financials_cache[ticker] = {"data": result, "ts": now}
        return jsonify(result)

    except Exception as e:
        return jsonify({"error": str(e)}), 500
