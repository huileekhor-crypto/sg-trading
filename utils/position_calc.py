"""Position sizing and trade setup calculations."""


def calc_position(price, stop, target, account_size, risk_pct, mode="SWING"):
    """
    Returns shares, cost, max_loss, potential_gain, r_r, position_pct.
    Risk-based for SWING; conviction-based for LONG-TERM.
    """
    if not price or not stop or price <= stop:
        return {}

    risk_per_share = price - stop
    if risk_per_share <= 0:
        return {}

    if mode == "SWING":
        max_loss_dollars = account_size * risk_pct / 100
        shares = int(max_loss_dollars / risk_per_share)
    else:
        # LONG-TERM: size as % of account (default 7.5%)
        position_dollars = account_size * risk_pct / 100
        shares = int(position_dollars / price)

    if shares <= 0:
        return {}

    cost          = round(shares * price, 2)
    max_loss      = round(shares * risk_per_share, 2)
    potential_gain = round(shares * (target - price), 2) if target else 0
    position_pct  = round(cost / account_size * 100, 1)
    r_r           = round((target - price) / risk_per_share, 2) if target and target > price else 0

    return {
        "shares":          shares,
        "cost":            cost,
        "max_loss":        max_loss,
        "potential_gain":  potential_gain,
        "position_pct":    position_pct,
        "r_r":             r_r,
        "risk_per_share":  round(risk_per_share, 2),
    }


def calc_swing_setup(price, atr, account_size=20000, risk_pct=2.0):
    """Standard swing setup: 1.5×ATR stop, 3×ATR target."""
    if not atr:
        stop   = round(price * 0.94, 2)
        target = round(price * 1.20, 2)
    else:
        stop   = round(price - 1.5 * atr, 2)
        target = round(price + 3.0 * atr, 2)
    pos = calc_position(price, stop, target, account_size, risk_pct, "SWING")
    return {"entry": price, "stop": stop, "target": target, **pos}


def calc_lt_setup(price, atr, account_size=20000, position_pct=7.5):
    """Long-term setup: wider stop (3×ATR), big target (8×ATR)."""
    if not atr:
        stop   = round(price * 0.83, 2)
        target = round(price * 1.75, 2)
    else:
        stop   = round(price - 3.0 * atr, 2)
        target = round(price + 8.0 * atr, 2)
    pos = calc_position(price, stop, target, account_size, position_pct, "LONG-TERM")
    return {"entry": price, "stop": stop, "target": target, **pos}


def position_health(entry, current_price, stop, target, mode):
    """Return management signals for an open position."""
    if not entry or entry == 0:
        return {}
    pnl_pct = (current_price - entry) / entry * 100
    signals = []

    if current_price <= stop:
        signals.append({"type": "EXIT", "msg": "Stop hit — EXIT NOW. No hoping.", "color": "red"})
    elif mode == "SWING":
        if pnl_pct >= 15:
            signals.append({"type": "PROFIT", "msg": f"Up {pnl_pct:.1f}% — take 1/3 profit, move stop to BE", "color": "green"})
        elif pnl_pct >= 5:
            signals.append({"type": "TRAIL", "msg": f"Up {pnl_pct:.1f}% — move stop to breakeven", "color": "green"})
        elif pnl_pct <= -3:
            signals.append({"type": "WARN", "msg": f"Down {abs(pnl_pct):.1f}% — watch stop closely", "color": "orange"})
    else:  # LONG-TERM
        if pnl_pct >= 50:
            signals.append({"type": "REVIEW", "msg": f"Up {pnl_pct:.1f}% — review thesis, trim if over-positioned", "color": "green"})
        elif pnl_pct <= -15:
            signals.append({"type": "THESIS", "msg": f"Down {abs(pnl_pct):.1f}% — is thesis still intact?", "color": "orange"})

    return {
        "pnl_pct":    round(pnl_pct, 2),
        "pnl_dollars": round((current_price - entry), 2),
        "signals":     signals,
    }
