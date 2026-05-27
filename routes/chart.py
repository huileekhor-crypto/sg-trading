from flask import Blueprint, request, jsonify
import yfinance as yf
from config import Config
from datetime import datetime, timedelta

chart_bp = Blueprint('chart', __name__)

def get_ohlcv(ticker, days=120):
    """Fetch OHLCV history via yfinance (free, no API key needed)."""
    end   = datetime.now()
    start = end - timedelta(days=days)
    df = yf.download(ticker, start=start.strftime('%Y-%m-%d'),
                     end=end.strftime('%Y-%m-%d'), progress=False, auto_adjust=True)
    if df.empty:
        return None
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
        return [None] * len(prices)
    k = 2 / (period + 1)
    ema_val = sum(prices[:period]) / period
    result = [None] * (period - 1) + [round(ema_val, 4)]
    for price in prices[period:]:
        ema_val = price * k + ema_val * (1 - k)
        result.append(round(ema_val, 4))
    return result

def calculate_rsi_series(prices, period=14):
    result = [None] * len(prices)
    if len(prices) < period + 1:
        return result
    for i in range(period, len(prices)):
        gains = [max(prices[j] - prices[j-1], 0) for j in range(i-period+1, i+1)]
        losses = [max(prices[j-1] - prices[j], 0) for j in range(i-period+1, i+1)]
        avg_gain = sum(gains) / period
        avg_loss = sum(losses) / period
        if avg_loss == 0:
            result[i] = 100.0
        else:
            rs = avg_gain / avg_loss
            result[i] = round(100 - (100 / (1 + rs)), 1)
    return result

def calculate_bollinger_series(prices, period=20):
    upper, mid, lower = [], [], []
    for i in range(len(prices)):
        if i < period - 1:
            upper.append(None); mid.append(None); lower.append(None)
        else:
            window = prices[i-period+1:i+1]
            sma = sum(window) / period
            variance = sum((p - sma) ** 2 for p in window) / period
            std = variance ** 0.5
            upper.append(round(sma + 2*std, 4))
            mid.append(round(sma, 4))
            lower.append(round(sma - 2*std, 4))
    return upper, mid, lower

def calculate_macd_series(prices):
    if len(prices) < 26:
        return [None]*len(prices), [None]*len(prices), [None]*len(prices)
    
    def ema_series(data, period):
        k = 2 / (period + 1)
        result = [None] * (period - 1)
        ema_val = sum(data[:period]) / period
        result.append(round(ema_val, 4))
        for p in data[period:]:
            ema_val = p * k + ema_val * (1 - k)
            result.append(round(ema_val, 4))
        return result

    ema12 = ema_series(prices, 12)
    ema26 = ema_series(prices, 26)
    macd_line = [round(a - b, 4) if a and b else None for a, b in zip(ema12, ema26)]
    
    valid = [(i, v) for i, v in enumerate(macd_line) if v is not None]
    signal_line = [None] * len(prices)
    if len(valid) >= 9:
        vals = [v for _, v in valid]
        k = 2 / 10
        sig = sum(vals[:9]) / 9
        start_idx = valid[8][0]
        signal_line[start_idx] = round(sig, 4)
        for j in range(9, len(valid)):
            sig = vals[j] * k + sig * (1 - k)
            signal_line[valid[j][0]] = round(sig, 4)
    
    histogram = [round(m - s, 4) if m and s else None for m, s in zip(macd_line, signal_line)]
    return macd_line, signal_line, histogram

def detect_squeeze(bb_upper, bb_lower, bb_mid, lookback=20):
    """Detect Bollinger Band squeeze — bands narrowing"""
    if not all(bb_upper[-lookback:]) or not all(bb_lower[-lookback:]):
        return False, 0
    
    widths = [u - l for u, l in zip(bb_upper[-lookback:], bb_lower[-lookback:]) if u and l]
    if not widths:
        return False, 0
    
    current_width = widths[-1]
    avg_width = sum(widths) / len(widths)
    min_width = min(widths)
    
    is_squeeze = current_width <= avg_width * 0.75
    squeeze_pct = round((1 - current_width / avg_width) * 100, 1)
    return is_squeeze, squeeze_pct

def detect_volume_accumulation(volumes, lookback=10):
    """Detect quiet volume accumulation — above avg volume without big price moves"""
    if len(volumes) < lookback + 20:
        return False, 0
    avg_vol = sum(volumes[-30:-lookback]) / (30 - lookback)
    recent_vols = volumes[-lookback:]
    above_avg_days = sum(1 for v in recent_vols if v > avg_vol)
    accum_score = round((above_avg_days / lookback) * 100, 0)
    is_accumulating = above_avg_days >= lookback * 0.6
    return is_accumulating, int(accum_score)

def find_resistance(highs, closes, lookback=30):
    """Find nearest resistance level above current price"""
    current = closes[-1]
    recent_highs = highs[-lookback:]
    potential_resistance = [h for h in recent_highs if h > current * 1.01]
    if not potential_resistance:
        return None
    return round(min(potential_resistance), 2)

@chart_bp.route('/chart/<ticker>', methods=['GET'])
def get_chart_data(ticker):
    ticker = ticker.upper().strip()

    try:
        candles = get_ohlcv(ticker)

        if not candles:
            return jsonify({"error": f"No chart data for {ticker}"}), 404

        full_closes = candles['c']
        full_highs  = candles['h']
        full_vols   = candles['v']

        # Take last 60 days for display
        n = min(60, len(full_closes))
        closes     = full_closes[-n:]
        highs      = full_highs[-n:]
        lows       = candles['l'][-n:]
        opens      = candles['o'][-n:]
        volumes    = full_vols[-n:]
        timestamps = candles['t'][-n:]

        dates = [datetime.fromtimestamp(t).strftime('%b %d') for t in timestamps]

        ema20 = calculate_ema(closes, 20)[-n:]
        ema50 = calculate_ema(closes, min(50, n))[-n:]
        rsi   = calculate_rsi_series(closes)[-n:]
        bb_upper, bb_mid, bb_lower = calculate_bollinger_series(closes)
        bb_upper = bb_upper[-n:]
        bb_mid   = bb_mid[-n:]
        bb_lower = bb_lower[-n:]
        macd_line, signal_line, histogram = calculate_macd_series(closes)
        macd_line  = macd_line[-n:]
        signal_line= signal_line[-n:]
        histogram  = histogram[-n:]

        # Pre-breakout detection (uses full 120-day history)
        
        full_bb_upper, _, full_bb_lower = calculate_bollinger_series(full_closes)
        full_bb_mid = [(u+l)/2 if u and l else None for u,l in zip(full_bb_upper, full_bb_lower)]
        
        is_squeeze,  squeeze_pct   = detect_squeeze(full_bb_upper, full_bb_lower, full_bb_mid)
        is_accum,    accum_score   = detect_volume_accumulation(full_vols)
        resistance   = find_resistance(full_highs, full_closes)
        current_price = closes[-1]
        
        near_resistance = resistance and (resistance - current_price) / current_price < 0.05
        
        # Current indicator values
        current_rsi  = next((v for v in reversed(rsi) if v), None)
        current_macd = next((v for v in reversed(macd_line) if v), None)
        current_hist = next((v for v in reversed(histogram) if v), None)
        
        rsi_building = current_rsi and 40 < current_rsi < 60
        macd_turning = current_hist and current_hist > 0 and histogram[-2] and histogram[-2] < current_hist

        # Score pre-breakout probability
        signals_count = sum([is_squeeze, is_accum, near_resistance or False, rsi_building or False, macd_turning or False])
        prebreakout_score = signals_count * 20

        # Plain English explanation
        explanations = []
        
        if is_squeeze:
            explanations.append({
                "signal": "🔍 BOLLINGER SQUEEZE",
                "color": "cyan",
                "short": f"Bands {squeeze_pct}% narrower than average",
                "explain": "The price has been trading in an unusually tight range. Think of it like a coiled spring — the longer it compresses, the bigger the eventual move. This doesn't tell you which direction, but a breakout is building. Watch for a volume surge to signal the direction."
            })
        
        if is_accum:
            explanations.append({
                "signal": "📦 VOLUME ACCUMULATION",
                "color": "green",
                "short": f"{accum_score}% of recent days above average volume",
                "explain": "Volume has been quietly above average without a big price move. This is often smart money or institutions slowly building a position — buying without pushing the price up dramatically. Retail traders usually miss this. It precedes many breakouts by days to weeks."
            })
        
        if near_resistance and resistance:
            pct_away = round((resistance - current_price) / current_price * 100, 1)
            explanations.append({
                "signal": "🚪 AT KEY RESISTANCE",
                "color": "amber",
                "short": f"${resistance} resistance only {pct_away}% away",
                "explain": f"Price is sitting just below ${resistance}, a level where sellers have previously stepped in. If price breaks above this with strong volume, it often triggers a powerful move higher as short sellers cover and momentum buyers pile in. This is your trigger level to watch."
            })
        
        if rsi_building:
            explanations.append({
                "signal": "⚡ RSI IN LAUNCH ZONE",
                "color": "green",
                "short": f"RSI at {current_rsi} — not overbought, room to run",
                "explain": f"RSI at {current_rsi} means momentum is building but hasn't reached the danger zone (70+) yet. This is the ideal RSI range for a breakout entry — the stock has room to move significantly higher before getting stretched. If RSI was already at 75+, the easy money would be gone."
            })
        
        if macd_turning:
            explanations.append({
                "signal": "📈 MACD TURNING UP",
                "color": "green",
                "short": "Momentum shifting positive",
                "explain": "The MACD histogram is growing — meaning the gap between the fast and slow moving averages is expanding upward. This is an early sign that buying momentum is accelerating. It often precedes the price breakout by a few days, giving you a window to position before the move."
            })

        if not explanations:
            explanations.append({
                "signal": "⏸ NO PRE-BREAKOUT SIGNAL",
                "color": "neutral",
                "short": "Waiting for setup to develop",
                "explain": "The key pre-breakout conditions haven't aligned yet. No Bollinger squeeze, no accumulation volume, not near a key resistance level. This doesn't mean the stock is bad — it means the timing isn't right. Add to watchlist and check again in a few days."
            })

        return jsonify({
            "ticker":   ticker,
            "dates":    dates,
            "candles": {
                "open":  [round(x,2) for x in opens],
                "high":  [round(x,2) for x in highs],
                "low":   [round(x,2) for x in lows],
                "close": [round(x,2) for x in closes],
            },
            "volume":      [int(v) for v in volumes],
            "indicators": {
                "ema20":       ema20,
                "ema50":       ema50,
                "bb_upper":    bb_upper,
                "bb_mid":      bb_mid,
                "bb_lower":    bb_lower,
                "rsi":         rsi,
                "macd_line":   macd_line,
                "signal_line": signal_line,
                "histogram":   histogram,
            },
            "prebreakout": {
                "score":           prebreakout_score,
                "is_squeeze":      is_squeeze,
                "squeeze_pct":     squeeze_pct,
                "is_accumulating": is_accum,
                "accum_score":     accum_score,
                "near_resistance": near_resistance or False,
                "resistance":      resistance,
                "rsi_building":    rsi_building or False,
                "macd_turning":    macd_turning or False,
                "signals_count":   signals_count,
            },
            "explanations": explanations,
            "current_price": current_price,
            "timestamp": datetime.now().isoformat()
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500
