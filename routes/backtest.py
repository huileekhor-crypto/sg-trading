"""Backtest — walk-forward validation of the 6-layer SWING strategy.

Look-ahead bias notes (displayed in UI):
  L1 TREND:       EMA20/50/200 on closes[0..T] only               — CLEAN
  L2 MOMENTUM:    RSI/MACD/ROC on closes[0..T] only               — CLEAN
  L3 VOLUME:      day-T volume vs avg of days T-20..T-1            — CLEAN
  L4 STRUCTURE:   price vs EMA20 at close of day T                 — CLEAN
  L5 CATALYST:    historical news not archived; scored 0 always    — CONSERVATIVE BIAS
  L6 SMART MONEY: UW API is real-time only; scored 0 always        — CONSERVATIVE BIAS
  ENTRY:          simulated at day T+1 OPEN                        — CLEAN
  STOP/TARGET:    resolved against day T+1..T+N highs/lows         — CLEAN
  REGIME:         SPY EMA200 computed on SPY closes[0..T]          — CLEAN
"""

import datetime
from flask import Blueprint, jsonify, request, render_template
from utils.prices import get_candles
from utils.analysis_engine import (
    _ema, _rsi, _atr,
    layer1_trend, layer2_momentum, layer3_volume, layer4_structure,
)

backtest_bp = Blueprint("backtest", __name__)

# ── Configurable defaults ──────────────────────────────────────────────────────
DEFAULT_TICKERS = [
    "NVDA", "AMD", "MU", "MSFT", "META", "GOOGL", "AAPL", "AMZN",
    "TSLA", "AVGO", "CRM", "NOW", "DDOG", "CRWD", "PLTR", "SNOW",
    "NBIS", "SMCI", "MRVL", "ARM",
]
DEFAULT_PERIOD_DAYS = 730   # ~2 years daily candles
DEFAULT_MIN_SCORE   = 70    # 0-100, normalised against L1-L4 max only
DEFAULT_MAX_HOLD    = 20    # trading days before time-stop
DEFAULT_SLIPPAGE    = 0.001 # 0.10% per side (buy + sell)
DEFAULT_ACCOUNT     = 20_000.0

WARMUP_BARS = 210           # minimum bars before the first signal (EMA200 needs 200)
RISK_PCT    = 0.01          # 1% account risk per trade (fixed rule)
MIN_SAMPLE  = 30            # below this: show red "SAMPLE TOO SMALL" banner

# SWING mode weights — mirror run_full_analysis() exactly
_W = dict(trend=1.0, mom=1.2, vol=1.0, struct=1.2, cat=0.8, sm=1.2)
# Max achievable with L1-L4 only (L5/L6 = 0 in backtest)
_MAX_4L = 25 * _W["trend"] + 25 * _W["mom"] + 20 * _W["vol"] + 20 * _W["struct"]  # 99.0

# ATR multipliers — mirror live trade_setup in run_full_analysis()
ATR_STOP   = 1.5
ATR_TARGET = 3.0


# ── Routes ─────────────────────────────────────────────────────────────────────

@backtest_bp.route("/backtest")
def backtest_page():
    return render_template("backtest.html")


@backtest_bp.route("/api/backtest/run")
def run_backtest():
    # Parse params
    raw_tickers = request.args.get("tickers", "")
    tickers = [t.strip().upper() for t in raw_tickers.split(",") if t.strip()] or DEFAULT_TICKERS
    tickers = tickers[:20]  # cap to avoid long waits

    period    = int(request.args.get("period_days", DEFAULT_PERIOD_DAYS))
    min_score = int(request.args.get("min_score",   DEFAULT_MIN_SCORE))
    max_hold  = int(request.args.get("max_days",    DEFAULT_MAX_HOLD))
    slip      = float(request.args.get("slippage",  DEFAULT_SLIPPAGE))
    acct      = float(request.args.get("account",   DEFAULT_ACCOUNT))
    do_split  = request.args.get("split", "true").lower() == "true"

    # SPY for regime tagging — fetch once
    spy_candles = _safe_candles("SPY", period + 250)

    all_trades, skipped, errors = [], [], []

    for ticker in tickers:
        try:
            candles = get_candles(ticker, days=period + 250)
            if not candles or len(candles) < WARMUP_BARS + 5:
                skipped.append(f"{ticker}: only {len(candles) if candles else 0} bars (need {WARMUP_BARS + 5})")
                continue
            trades = _walk_forward(ticker, candles, spy_candles, min_score, max_hold, slip, acct)
            all_trades.extend(trades)
        except Exception as exc:
            errors.append(f"{ticker}: {exc}")

    all_trades.sort(key=lambda t: t["entry_ts"])

    summary      = _summary(all_trades, acct, full=True)
    regime_bdown = _regime_breakdown(all_trades, acct)
    is_oos       = _split_summary(all_trades, acct) if do_split else None
    equity_curve = _equity_curve(all_trades, acct)
    verdict      = _plain_verdict(summary, len(tickers), period)

    return jsonify({
        "summary":      summary,
        "regime":       regime_bdown,
        "is_oos":       is_oos,
        "equity_curve": equity_curve,
        "verdict":      verdict,
        "trades":       all_trades[-150:],
        "total_trades": len(all_trades),
        "skipped":      skipped,
        "errors":       errors,
        "params": {
            "tickers":    tickers,
            "period_days":period,
            "min_score":  min_score,
            "max_days":   max_hold,
            "slippage":   slip,
            "account":    acct,
        },
    })


# ── Core walk-forward engine ───────────────────────────────────────────────────

def _walk_forward(ticker, candles, spy_candles, min_score, max_hold, slip, acct):
    """Emit one trade record per signal. Entry at T+1 open, ATR-based levels."""
    trades = []
    closes = [c["c"] for c in candles]
    n = len(candles)

    # Build SPY lookup: unix-ts → index (for regime tagging without look-ahead)
    spy_ts_idx = {c["t"]: i for i, c in enumerate(spy_candles)}

    i = WARMUP_BARS  # start after indicators warm up

    while i < n - max_hold - 2:
        score, ema20, rsi, atr = _score_at(candles, closes, i)

        if score >= min_score:
            entry_bar = i + 1
            if entry_bar >= n:
                break

            raw_entry = candles[entry_bar]["o"]
            if not raw_entry or raw_entry <= 0:
                i += 1
                continue

            # Apply buy slippage (we pay a bit more)
            entry = raw_entry * (1 + slip)

            # ATR-based stop and target (exact same multipliers as live system)
            if atr and atr > 0:
                stop   = entry - ATR_STOP   * atr
                target = entry + ATR_TARGET * atr
            else:
                stop   = entry * 0.94   # fallback 6%
                target = entry * 1.20   # fallback 20%

            stop   = round(stop,   4)
            target = round(target, 4)

            if stop >= entry or target <= entry:
                i += 1
                continue

            risk_per_share = entry - stop
            shares = (acct * RISK_PCT) / risk_per_share

            # Resolve: check daily H/L from entry_bar onward
            # Stop evaluated before target (conservative) on same bar
            outcome, exit_px, hold_days, exit_type = _resolve(
                candles, entry_bar, entry, stop, target, max_hold, n
            )

            # Sell slippage (we receive a bit less)
            exit_px_net = exit_px * (1 - slip)

            r_mult      = round((exit_px_net - entry) / risk_per_share, 3)
            pnl_dollar  = round(shares * (exit_px_net - entry), 2)
            pnl_pct     = round((exit_px_net - entry) / entry * 100, 3)

            # Regime: look up SPY bar closest to signal day i (not entry day)
            spy_idx = _spy_index(spy_candles, spy_ts_idx, candles[i]["t"])
            regime  = _regime(spy_candles, spy_idx)

            trades.append({
                "ticker":      ticker,
                "entry_ts":    candles[entry_bar]["t"],
                "entry_date":  _date(candles[entry_bar]["t"]),
                "signal_date": _date(candles[i]["t"]),
                "entry":       round(entry, 2),
                "exit":        round(exit_px_net, 2),
                "stop":        round(stop, 2),
                "target":      round(target, 2),
                "atr":         round(atr, 3) if atr else None,
                "score":       score,
                "rsi":         round(rsi, 1) if rsi else None,
                "hold_days":   hold_days,
                "outcome":     outcome,
                "exit_type":   exit_type,
                "r_mult":      r_mult,
                "pnl_pct":     pnl_pct,
                "pnl_dollar":  pnl_dollar,
                "regime":      regime,
                "shares":      round(shares, 1),
            })
            i = entry_bar + hold_days + 1   # skip past the trade
        else:
            i += 1

    return trades


def _score_at(candles, closes, i):
    """
    4-layer score at bar i using only closes[0..i] — no look-ahead.
    Normalised to 0-100 against L1-L4 max (= _MAX_4L weighted points).
    L5 and L6 are not scored (not available historically).
    """
    window    = closes[: i + 1]
    vol_today = candles[i]["v"]
    price     = closes[i]

    ema20  = _ema(window, 20)  if len(window) >= 20  else None
    ema50  = _ema(window, 50)  if len(window) >= 50  else None
    ema200 = _ema(window, 200) if len(window) >= 200 else None
    rsi    = _rsi(window, 14)  if len(window) >= 15  else None
    atr    = _atr(candles[: i + 1], 14) if i >= 14 else None

    l1 = layer1_trend(price, ema20, ema50, ema200)
    l2 = layer2_momentum(rsi, window)
    l3 = layer3_volume(vol_today, candles[: i + 1])
    l4 = layer4_structure(price, ema20)

    raw = (
        l1["score"] * _W["trend"]
        + l2["score"] * _W["mom"]
        + l3["score"] * _W["vol"]
        + l4["score"] * _W["struct"]
    )
    score = round(min(raw / _MAX_4L * 100, 100))
    return score, ema20, rsi, atr


def _resolve(candles, entry_bar, entry, stop, target, max_hold, n):
    """
    Scan daily bars from entry_bar forward.
    Stop evaluated before target (conservative) when both fire on the same bar.
    Returns (outcome, exit_price, hold_days, exit_type).
    """
    for j in range(max_hold + 1):
        k = entry_bar + j
        if k >= n:
            # Ran out of data — exit at last known close
            return "TIME", candles[n - 1]["c"], j, "DATA_END"
        c = candles[k]
        if c["l"] <= stop:
            return "LOSS", stop, j, "STOP"
        if c["h"] >= target:
            return "WIN", target, j, "TARGET"

    # Time stop: exit at close of last bar
    close_px = candles[min(entry_bar + max_hold, n - 1)]["c"]
    outcome  = "WIN" if close_px > entry else "LOSS"
    return outcome, close_px, max_hold, "TIME"


# ── Regime tagging ─────────────────────────────────────────────────────────────

def _spy_index(spy_candles, spy_ts_idx, target_ts):
    """Return SPY bar index <= target_ts (no look-ahead)."""
    if target_ts in spy_ts_idx:
        return spy_ts_idx[target_ts]
    # Walk backward to find the nearest earlier SPY bar
    for c in reversed(spy_candles):
        if c["t"] <= target_ts:
            return spy_ts_idx.get(c["t"], len(spy_candles) - 1)
    return 0


def _regime(spy_candles, idx):
    """RISK_ON / RISK_OFF / NEUTRAL based on SPY EMA200 at bar idx."""
    if not spy_candles or idx < 200:
        return "NEUTRAL"
    closes = [c["c"] for c in spy_candles[: idx + 1]]
    ema200 = _ema(closes, 200)
    ema50  = _ema(closes, 50)
    if ema200 is None:
        return "NEUTRAL"
    price = closes[-1]
    if price >= ema200 and (ema50 is None or price >= ema50):
        return "RISK_ON"
    if price < ema200:
        return "RISK_OFF"
    return "NEUTRAL"


# ── Metrics ────────────────────────────────────────────────────────────────────

def _summary(trades, acct, full=True):
    n = len(trades)
    if n == 0:
        return {"total_trades": 0, "insufficient": True}

    wins   = [t for t in trades if t["outcome"] == "WIN"]
    losses = [t for t in trades if t["outcome"] == "LOSS"]
    times  = [t for t in trades if t["exit_type"] == "TIME"]

    win_r_vals  = [t["r_mult"] for t in wins]
    loss_r_vals = [abs(t["r_mult"]) for t in losses]

    avg_win_r  = round(sum(win_r_vals)  / len(win_r_vals),  3) if win_r_vals  else 0.0
    avg_loss_r = round(sum(loss_r_vals) / len(loss_r_vals), 3) if loss_r_vals else 0.0
    expectancy = round(sum(t["r_mult"] for t in trades) / n, 3)

    gross_win  = sum(t["pnl_dollar"] for t in wins)
    gross_loss = abs(sum(t["pnl_dollar"] for t in losses))
    pf = round(gross_win / gross_loss, 2) if gross_loss > 0 else (99.0 if gross_win > 0 else 0.0)

    # Longest losing streak (count TIME exits that lost as losses)
    longest_streak, cur = 0, 0
    for t in trades:
        if t["r_mult"] < 0:
            cur += 1
            longest_streak = max(longest_streak, cur)
        else:
            cur = 0

    result = {
        "total_trades":      n,
        "wins":              len(wins),
        "losses":            len(losses),
        "time_exits":        len(times),
        "win_rate":          round(len(wins) / n * 100, 1),
        "avg_win_r":         avg_win_r,
        "avg_loss_r":        avg_loss_r,
        "expectancy_r":      expectancy,
        "profit_factor":     pf,
        "total_pnl_dollar":  round(sum(t["pnl_dollar"] for t in trades), 2),
        "longest_loss_streak": longest_streak,
        "insufficient":      n < MIN_SAMPLE,
    }
    if full:
        result["max_drawdown_pct"] = _max_drawdown(trades, acct)
    return result


def _max_drawdown(trades, acct):
    equity, peak, max_dd = acct, acct, 0.0
    for t in trades:
        equity += t["pnl_dollar"]
        peak    = max(peak, equity)
        dd      = (peak - equity) / peak * 100
        max_dd  = max(max_dd, dd)
    return round(max_dd, 2)


def _regime_breakdown(trades, acct):
    out = {}
    for regime in ("RISK_ON", "RISK_OFF", "NEUTRAL"):
        sub = [t for t in trades if t.get("regime") == regime]
        if sub:
            out[regime] = _summary(sub, acct, full=False)
    return out


def _split_summary(trades, acct):
    if len(trades) < 2:
        return None
    mid_ts = (trades[0]["entry_ts"] + trades[-1]["entry_ts"]) / 2
    in_s   = [t for t in trades if t["entry_ts"] <= mid_ts]
    oos    = [t for t in trades if t["entry_ts"] >  mid_ts]
    return {
        "in_sample":     _summary(in_s,  acct, full=False),
        "out_of_sample": _summary(oos,   acct, full=False),
    }


def _equity_curve(trades, acct):
    curve   = [{"date": "start", "equity": round(acct, 2)}]
    equity  = acct
    for t in trades:
        equity += t["pnl_dollar"]
        curve.append({"date": t["entry_date"], "equity": round(equity, 2)})
    return curve


# ── Plain-English verdict ──────────────────────────────────────────────────────

def _plain_verdict(s, n_tickers, period_days):
    if s.get("total_trades", 0) == 0:
        return "No trades fired at this threshold — lower min_score or add more tickers."
    if s.get("insufficient"):
        return (
            f"Only {s['total_trades']} trades — sample too small to draw conclusions. "
            "Lower the min_score threshold or add more tickers to generate at least 30 trades."
        )
    years = round(period_days / 365, 1)
    exp   = s.get("expectancy_r", 0)
    pf    = s.get("profit_factor", 0)
    wr    = s.get("win_rate", 0)
    n     = s["total_trades"]
    dd    = s.get("max_drawdown_pct", 0)

    if exp > 0.2 and pf >= 1.5:
        edge = "Positive expectancy"
        call = "tentative edge present"
    elif exp > 0:
        edge = "Marginally positive expectancy"
        call = "weak edge — needs more data or tighter entry"
    else:
        edge = "Negative expectancy"
        call = "no proven edge yet — do NOT size up"

    return (
        f"{edge} ({exp:+.2f}R/trade) over {n} trades across {n_tickers} tickers "
        f"and {years} years (win rate {wr}%, PF {pf}, max DD {dd}%) — {call}. "
        f"NOTE: L5/L6 not available historically; live scores will be higher, "
        f"which should increase trade frequency. "
        f"WARNING: tweaking the strategy to improve these numbers is curve-fitting — "
        f"the real test is forward performance on new data."
    )


# ── Helpers ────────────────────────────────────────────────────────────────────

def _safe_candles(ticker, days):
    try:
        return get_candles(ticker, days=days) or []
    except Exception:
        return []


def _date(ts):
    return datetime.datetime.utcfromtimestamp(ts).strftime("%Y-%m-%d")
