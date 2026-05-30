"""Backtest — validate 6-layer SWING strategy on historical data."""

from flask import Blueprint, jsonify, request, render_template
from utils.prices import get_candles
from utils.analysis_engine import _ema, _rsi, _atr, layer1_trend, layer2_momentum, layer3_volume, layer4_structure

backtest_bp = Blueprint("backtest", __name__)

SWING_TICKERS = [
    "NVDA", "AMD", "MU", "MSFT", "META", "GOOGL", "AAPL", "AMZN",
    "TSLA", "AVGO", "CRM", "NOW", "DDOG", "CRWD", "PLTR", "SNOW",
    "NBIS", "SMCI", "MRVL", "ARM",
]


@backtest_bp.route("/backtest")
def backtest_page():
    return render_template("backtest.html")


@backtest_bp.route("/api/backtest/run")
def run_backtest():
    tickers  = request.args.getlist("tickers") or SWING_TICKERS[:10]
    min_score = int(request.args.get("min_score", 85))
    stop_pct  = float(request.args.get("stop_pct", 6))
    target_pct = float(request.args.get("target_pct", 20))
    max_days   = int(request.args.get("max_days", 20))

    all_trades = []
    errors     = []

    for ticker in tickers[:15]:
        try:
            candles = get_candles(ticker, days=730)  # ~2 years
            if len(candles) < 220:
                continue
            closes = [c["c"] for c in candles]
            trades = _backtest_ticker(
                ticker, candles, closes, min_score, stop_pct, target_pct, max_days
            )
            all_trades.extend(trades)
        except Exception as e:
            errors.append(f"{ticker}: {e}")

    if not all_trades:
        return jsonify({
            "trades": [], "summary": {}, "errors": errors,
            "message": "No trades found — try lower min_score"
        })

    wins   = [t for t in all_trades if t["outcome"] == "WIN"]
    losses = [t for t in all_trades if t["outcome"] == "LOSS"]
    total_pnl = sum(t["pnl_pct"] for t in all_trades)
    gross_win  = sum(t["pnl_pct"] for t in wins)
    gross_loss = abs(sum(t["pnl_pct"] for t in losses))

    summary = {
        "total_trades":   len(all_trades),
        "wins":           len(wins),
        "losses":         len(losses),
        "win_rate":       round(len(wins) / len(all_trades) * 100, 1),
        "avg_win_pct":    round(gross_win / len(wins), 2) if wins else 0,
        "avg_loss_pct":   round(gross_loss / len(losses), 2) if losses else 0,
        "profit_factor":  round(gross_win / gross_loss, 2) if gross_loss else 0,
        "total_return_pct": round(total_pnl, 2),
        "max_drawdown":   _max_drawdown(all_trades),
        "tickers_tested": len(tickers),
        "params": {
            "min_score":  min_score,
            "stop_pct":   stop_pct,
            "target_pct": target_pct,
            "max_days":   max_days,
        }
    }

    return jsonify({
        "summary": summary,
        "trades":  all_trades[-50:],  # last 50 trades for display
        "errors":  errors,
    })


def _backtest_ticker(ticker, candles, closes, min_score, stop_pct, target_pct, max_days):
    trades = []
    i = 210  # start after EMA200 warms up

    while i < len(candles) - max_days - 1:
        window  = closes[:i + 1]
        vol_today = candles[i]["v"]

        ema20  = _ema(window, 20)
        ema50  = _ema(window, 50)
        ema200 = _ema(window, 200)
        rsi    = _rsi(window, 14)
        price  = closes[i]

        l1 = layer1_trend(price, ema20, ema50, ema200)
        l2 = layer2_momentum(rsi)
        l3 = layer3_volume(vol_today, candles[:i + 1])
        l4 = layer4_structure(price, ema20)

        partial = l1["score"] + l2["score"] + l3["score"] + l4["score"]
        score4  = round(partial / 90 * 100)

        if score4 >= min_score:
            entry  = price
            stop   = round(entry * (1 - stop_pct / 100), 2)
            target = round(entry * (1 + target_pct / 100), 2)

            outcome, exit_price, hold_days = "TIME", entry, max_days
            for j in range(1, max_days + 1):
                if i + j >= len(candles):
                    break
                c = candles[i + j]
                if c["l"] <= stop:
                    outcome, exit_price, hold_days = "LOSS", stop, j
                    break
                if c["h"] >= target:
                    outcome, exit_price, hold_days = "WIN", target, j
                    break
            else:
                exit_price = closes[min(i + max_days, len(closes) - 1)]
                outcome    = "WIN" if exit_price > entry else "LOSS"

            pnl_pct = round((exit_price - entry) / entry * 100, 2)
            trades.append({
                "ticker":     ticker,
                "entry_date": candles[i]["t"],
                "entry":      round(entry, 2),
                "exit":       round(exit_price, 2),
                "stop":       stop,
                "target":     target,
                "score":      score4,
                "rsi":        rsi,
                "hold_days":  hold_days,
                "outcome":    outcome,
                "pnl_pct":   pnl_pct,
            })
            i += hold_days + 1  # skip ahead after trade exits
        else:
            i += 1

    return trades


def _max_drawdown(trades):
    if not trades:
        return 0
    cumulative = 0
    peak = 0
    max_dd = 0
    for t in sorted(trades, key=lambda x: x.get("entry_date", 0)):
        cumulative += t["pnl_pct"]
        peak = max(peak, cumulative)
        drawdown = peak - cumulative
        max_dd = max(max_dd, drawdown)
    return round(max_dd, 2)
