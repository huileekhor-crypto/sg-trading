"""Claude-powered senior trader analysis."""

import os
import anthropic

def _get_client():
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        return None
    return anthropic.Anthropic(api_key=key)


def generate_analysis(ticker, analysis, settings):
    """
    Generate WHY BUY / WHY IT COULD FAIL / WHEN TO ENTER / EXIT STRATEGY / VERDICT.
    analysis: full dict from run_full_analysis()
    settings: {account_size, swing_risk, weekly_target}
    """
    client = _get_client()
    if not client:
        return _fallback(analysis)

    mode  = analysis.get("mode", "SWING")
    price = analysis.get("price", 0)
    score = analysis.get("score", 0)
    l     = analysis.get("layers", {})
    fund  = analysis.get("fundamentals", {})
    uw    = analysis.get("layers", {}).get("smart_money", {})
    setup = analysis.get("trade_setup", {})

    uw_notes = ", ".join(uw.get("notes", [])) or "No unusual activity detected"

    fund_str = (
        f"P/E: {fund.get('pe_ratio', 'N/A')}, "
        f"Revenue Growth: {_pct(fund.get('revenue_growth'))}, "
        f"Gross Margin: {_pct(fund.get('gross_margins'))}, "
        f"Market Cap: {_mcap(fund.get('market_cap'))}, "
        f"52wk range: ${fund.get('52wk_low', 'N/A')} - ${fund.get('52wk_high', 'N/A')}"
    )

    scores_str = (
        f"TREND {l.get('trend',{}).get('score',0)}/25 ({l.get('trend',{}).get('reasons',[''])[0]}), "
        f"MOMENTUM {l.get('momentum',{}).get('score',0)}/25 (RSI {l.get('momentum',{}).get('rsi','N/A')}), "
        f"VOLUME {l.get('volume',{}).get('score',0)}/20 ({l.get('volume',{}).get('reason','')}), "
        f"STRUCTURE {l.get('structure',{}).get('score',0)}/20 ({l.get('structure',{}).get('reason','')}), "
        f"CATALYST {l.get('catalyst',{}).get('score',0)}/10 ({l.get('catalyst',{}).get('reason','')}), "
        f"SMART MONEY {l.get('smart_money',{}).get('score',0)}/20 ({uw_notes})"
    )

    account = settings.get("account_size", 20000)
    risk    = settings.get("swing_risk", 2)
    weekly  = settings.get("weekly_target", 1500)

    stop   = setup.get("stop_swing" if mode == "SWING" else "stop_lt", 0)
    target = setup.get("target_swing" if mode == "SWING" else "target_lt", 0)

    prompt = f"""You are a senior Singapore-based swing and long-term trader with 15 years experience.
Account: ${account:,}, {mode} mode, {risk}% risk per swing trade.
Weekly target: ${weekly:,}.

Analyse {ticker} at LIVE ${price:.2f}.
Overall score: {score}/100 ({analysis.get('verdict', '')}).
6-layer breakdown: {scores_str}
Fundamentals: {fund_str}
Unusual Whales smart money: {uw_notes}
Proposed setup: Entry ${price:.2f}, Stop ${stop:.2f}, Target ${target:.2f}

Write a concise, honest analysis in this EXACT format (no headers, just the sections):

WHY BUY: [2-3 sentences. Specific price levels, technicals, catalyst, smart money. Only if there's a real case.]

WHY IT COULD FAIL: [2-3 sentences. Honest bear case. What would invalidate this setup.]

WHEN TO ENTER (SGT): [Specific. e.g. "Premarket above $X confirms, enter at open 9:30pm SGT" or "Wait for pullback to EMA20 at $X". If market is closed in Singapore say so.]

EXIT STRATEGY: [Mode-specific. {"SWING: tight stop $X (-5.8%), move to BE at +5%, take 1/3 at +15%, full exit at +20%" if mode == "SWING" else "LONG-TERM: hold thesis unless it breaks. Add on dips to $X. Stop at $X only if thesis broken."}]

VERDICT: [One direct sentence. "This is a BUY at current levels" or "WAIT for pullback to $X" or "AVOID — overextended/no catalyst/weak setup". Be honest even if it means WAIT or AVOID.]

Rules:
- All times in SGT (Singapore Time, UTC+8)
- Specific dollar amounts, not vague guidance
- Honest — say WAIT or AVOID when warranted
- No hype, no padding
- {"Emphasise timing and tight risk management." if mode == "SWING" else "Emphasise thesis durability and compounding potential."}"""

    try:
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=800,
            messages=[{"role": "user", "content": prompt}]
        )
        text = msg.content[0].text
        return _parse_response(text)
    except Exception as e:
        return _fallback(analysis, str(e))


def _parse_response(text):
    sections = {}
    current  = None
    buffer   = []
    keys = ["WHY BUY", "WHY IT COULD FAIL", "WHEN TO ENTER", "EXIT STRATEGY", "VERDICT"]

    for line in text.split("\n"):
        matched = False
        for k in keys:
            if line.startswith(k + ":") or line.startswith("**" + k):
                if current and buffer:
                    sections[current] = " ".join(buffer).strip()
                current = k
                rest = line.split(":", 1)[-1].strip().lstrip("*").strip()
                buffer = [rest] if rest else []
                matched = True
                break
        if not matched and current and line.strip():
            buffer.append(line.strip())

    if current and buffer:
        sections[current] = " ".join(buffer).strip()

    return {
        "why_buy":        sections.get("WHY BUY", ""),
        "why_fail":       sections.get("WHY IT COULD FAIL", ""),
        "when_to_enter":  sections.get("WHEN TO ENTER", ""),
        "exit_strategy":  sections.get("EXIT STRATEGY", ""),
        "verdict":        sections.get("VERDICT", ""),
        "raw":            text,
    }


def _fallback(analysis, error=""):
    score   = analysis.get("score", 0)
    verdict = analysis.get("verdict", "WAIT")
    return {
        "why_buy":       f"Score {score}/100 — {verdict}. Configure ANTHROPIC_API_KEY for detailed AI analysis.",
        "why_fail":      "AI analysis unavailable.",
        "when_to_enter": "Set ANTHROPIC_API_KEY for timing guidance.",
        "exit_strategy": "Set stops before entering any position.",
        "verdict":       f"{verdict} based on 6-layer quantitative score.",
        "raw":           error,
    }


def generate_journal_insight(trades):
    """Analyse trading history and return AI insights."""
    client = _get_client()
    if not client or not trades:
        return "Add more trades to unlock AI insights."

    wins  = [t for t in trades if t.get("pnl", 0) > 0]
    losses = [t for t in trades if t.get("pnl", 0) <= 0]
    win_rate = len(wins) / len(trades) * 100 if trades else 0

    summary = f"{len(trades)} trades, {win_rate:.0f}% win rate. "
    summary += f"Avg win: ${sum(t['pnl'] for t in wins)/len(wins):.0f}. " if wins else ""
    summary += f"Avg loss: ${abs(sum(t['pnl'] for t in losses)/len(losses)):.0f}. " if losses else ""

    swing_trades = [t for t in trades if t.get("mode") == "SWING"]
    lt_trades    = [t for t in trades if t.get("mode") == "LONG-TERM"]

    prompt = f"""You are a trading coach reviewing a Singapore-based trader's journal.
Trading stats: {summary}
Swing trades: {len(swing_trades)}, Long-term: {len(lt_trades)}.

Give 2-3 sentences of honest, specific, actionable insight about their trading patterns.
Focus on: what's working, what's not, one specific improvement.
Be direct. No fluff."""

    try:
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}]
        )
        return msg.content[0].text
    except Exception:
        return f"Win rate: {win_rate:.0f}%. Keep logging trades for pattern analysis."


def _pct(val):
    if val is None:
        return "N/A"
    return f"{val*100:.1f}%"


def _mcap(val):
    if val is None:
        return "N/A"
    if val >= 1e12:
        return f"${val/1e12:.1f}T"
    if val >= 1e9:
        return f"${val/1e9:.1f}B"
    return f"${val/1e6:.0f}M"
