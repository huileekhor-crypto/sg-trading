import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from config import Config
from datetime import datetime

APP_URL = "https://sg-trading-hui.azurewebsites.net"


def _alert_html(stock):
    level       = stock.get('alert_level', 'IMMINENT')
    level_color = '#FF3D5A' if level == 'IMMINENT' else '#FFB300' if level == 'WATCH' else '#00E5FF'
    signals_rows = ''.join(
        f'<tr><td style="padding:3px 0;font-size:14px;color:#C8D8F0;font-family:Arial,sans-serif">&#10003; {s}</td></tr>'
        for s in stock.get('signals', [])
    )
    return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#08090C;font-family:Arial,Helvetica,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#08090C;padding:24px 0">
<tr><td align="center">
<table width="560" cellpadding="0" cellspacing="0" style="background:#0D0F14;border:1px solid #2A3348;border-radius:12px;overflow:hidden;max-width:560px">

  <!-- Header bar -->
  <tr><td style="background:{level_color};padding:4px 0"></td></tr>

  <!-- Top -->
  <tr><td style="padding:24px 28px 16px;border-bottom:1px solid #1F2535">
    <table width="100%" cellpadding="0" cellspacing="0">
      <tr>
        <td>
          <div style="font-family:'Courier New',Courier,monospace;font-size:11px;color:#5A6E88;letter-spacing:2px;text-transform:uppercase;margin-bottom:6px">SG&nbsp;Trading&nbsp;Dashboard</div>
          <div style="font-family:'Courier New',Courier,monospace;font-size:30px;font-weight:700;color:#C8D8F0;letter-spacing:-0.02em;line-height:1">{stock['ticker']}</div>
        </td>
        <td align="right" valign="middle" style="padding-left:16px;white-space:nowrap">
          <div style="display:inline-block;width:64px;height:64px;border-radius:50%;border:2px solid {level_color};background:rgba(255,61,90,0.1);text-align:center;line-height:60px;font-family:'Courier New',Courier,monospace;font-size:20px;font-weight:700;color:{level_color}">{stock['score']}</div>
          <div style="font-family:'Courier New',Courier,monospace;font-size:9px;color:{level_color};text-align:center;letter-spacing:1.5px;margin-top:4px;text-transform:uppercase">{level}</div>
        </td>
      </tr>
    </table>
  </td></tr>

  <!-- Price levels -->
  <tr><td style="padding:16px 28px;border-bottom:1px solid #1F2535">
    <div style="font-family:'Courier New',Courier,monospace;font-size:10px;color:#00E5FF;letter-spacing:2px;text-transform:uppercase;margin-bottom:12px">Price Levels</div>
    <table width="100%" cellpadding="0" cellspacing="0">
      <tr>
        <td style="padding:4px 0"><span style="font-family:'Courier New',Courier,monospace;font-size:11px;color:#8898B8;text-transform:uppercase;letter-spacing:1px">Current&nbsp;Price</span></td>
        <td align="right"><span style="font-family:'Courier New',Courier,monospace;font-size:15px;font-weight:700;color:#C8D8F0">${stock['price']}</span></td>
      </tr>
      <tr>
        <td style="padding:4px 0"><span style="font-family:'Courier New',Courier,monospace;font-size:11px;color:#448AFF;text-transform:uppercase;letter-spacing:1px">Entry&nbsp;Zone</span></td>
        <td align="right"><span style="font-family:'Courier New',Courier,monospace;font-size:15px;font-weight:700;color:#448AFF">{stock['entry']}</span></td>
      </tr>
      <tr>
        <td style="padding:4px 0"><span style="font-family:'Courier New',Courier,monospace;font-size:11px;color:#FF3D5A;text-transform:uppercase;letter-spacing:1px">Stop&nbsp;Loss</span></td>
        <td align="right"><span style="font-family:'Courier New',Courier,monospace;font-size:15px;font-weight:700;color:#FF3D5A">{stock['stop']}</span></td>
      </tr>
      <tr>
        <td style="padding:4px 0"><span style="font-family:'Courier New',Courier,monospace;font-size:11px;color:#00E676;text-transform:uppercase;letter-spacing:1px">Target</span></td>
        <td align="right"><span style="font-family:'Courier New',Courier,monospace;font-size:15px;font-weight:700;color:#00E676">{stock['target']}</span></td>
      </tr>
      <tr>
        <td style="padding:4px 0"><span style="font-family:'Courier New',Courier,monospace;font-size:11px;color:#5A6E88;text-transform:uppercase;letter-spacing:1px">Risk&nbsp;/&nbsp;Reward</span></td>
        <td align="right"><span style="font-family:'Courier New',Courier,monospace;font-size:15px;font-weight:700;color:#8898B8">{stock.get('rr', '—')}:1</span></td>
      </tr>
    </table>
  </td></tr>

  <!-- Signals -->
  <tr><td style="padding:16px 28px;border-bottom:1px solid #1F2535">
    <div style="font-family:'Courier New',Courier,monospace;font-size:10px;color:#00E5FF;letter-spacing:2px;text-transform:uppercase;margin-bottom:10px">Signals Triggered</div>
    <table cellpadding="0" cellspacing="0">{signals_rows}</table>
  </td></tr>

  <!-- Why -->
  <tr><td style="padding:16px 28px;border-bottom:1px solid #1F2535">
    <div style="font-family:'Courier New',Courier,monospace;font-size:10px;color:#00E5FF;letter-spacing:2px;text-transform:uppercase;margin-bottom:8px">Why This Setup</div>
    <div style="font-size:14px;color:#8898B8;line-height:1.7;font-style:italic">{stock.get('why', '')}</div>
  </td></tr>

  <!-- CTA -->
  <tr><td style="padding:20px 28px;text-align:center;border-bottom:1px solid #1F2535">
    <a href="{APP_URL}/dashboard" style="display:inline-block;background:#00E5FF;color:#08090C;font-family:'Courier New',Courier,monospace;font-size:12px;font-weight:700;letter-spacing:1.5px;text-decoration:none;padding:12px 32px;border-radius:8px;text-transform:uppercase">View Full Analysis &#8594;</a>
  </td></tr>

  <!-- Footer -->
  <tr><td style="padding:16px 28px;text-align:center">
    <div style="font-size:11px;color:#5A6E88;line-height:1.6">Not financial advice. Educational purposes only.<br>
    SG Trading Dashboard &middot; {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}</div>
  </td></tr>

</table>
</td></tr>
</table>
</body>
</html>"""


def _test_html():
    return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#08090C;font-family:Arial,Helvetica,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#08090C;padding:24px 0">
<tr><td align="center">
<table width="480" cellpadding="0" cellspacing="0" style="background:#0D0F14;border:1px solid #2A3348;border-radius:12px;overflow:hidden;max-width:480px">
  <tr><td style="background:#00E5FF;padding:3px 0"></td></tr>
  <tr><td style="padding:28px;text-align:center;border-bottom:1px solid #1F2535">
    <div style="font-family:'Courier New',Courier,monospace;font-size:24px;font-weight:700;color:#00E5FF">SG<span style="color:#C8D8F0">.</span>TRADING</div>
    <div style="font-family:'Courier New',Courier,monospace;font-size:10px;color:#5A6E88;letter-spacing:2px;margin-top:4px;text-transform:uppercase">Email Alert System</div>
  </td></tr>
  <tr><td style="padding:32px 28px;text-align:center">
    <div style="font-size:44px;margin-bottom:14px">&#10003;</div>
    <div style="font-size:18px;font-weight:700;color:#00E676;margin-bottom:10px;font-family:Arial,sans-serif">Test Successful</div>
    <div style="font-size:14px;color:#8898B8;line-height:1.7">Your email alerts are configured correctly.<br>You will receive breakout alerts (score 80+) when the scanner finds imminent setups.</div>
  </td></tr>
  <tr><td style="padding:16px 28px;text-align:center;border-top:1px solid #1F2535">
    <div style="font-size:11px;color:#5A6E88">{datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')} &middot; Not financial advice</div>
  </td></tr>
</table>
</td></tr>
</table>
</body>
</html>"""


def _send_one(subject, html, to_email, to_name=None):
    if not Config.EMAIL_SENDER or not Config.EMAIL_PASSWORD:
        return False, "EMAIL_SENDER / EMAIL_PASSWORD not configured in environment"
    try:
        msg            = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From']    = f"SG Trading \U0001f6a8 <{Config.EMAIL_SENDER}>"
        msg['To']      = f"{to_name} <{to_email}>" if to_name else to_email
        msg.attach(MIMEText(html, 'html', 'utf-8'))

        with smtplib.SMTP(Config.EMAIL_SMTP_HOST, Config.EMAIL_SMTP_PORT, timeout=15) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.login(Config.EMAIL_SENDER, Config.EMAIL_PASSWORD)
            smtp.sendmail(Config.EMAIL_SENDER, to_email, msg.as_string())
        return True, None
    except Exception as e:
        return False, str(e)


def send_breakout_alert(stock, recipients):
    """Send breakout alert email to a list of recipients.
    Returns (ok_count, [error_strings]).
    """
    subject = f"\U0001f6a8 Breakout Alert: ${stock['ticker']} — Score {stock['score']}/100"
    html    = _alert_html(stock)
    ok, errors = 0, []
    for r in recipients:
        success, err = _send_one(subject, html, r['email'], r.get('name') or None)
        if success:
            ok += 1
        else:
            errors.append(f"{r['email']}: {err}")
    return ok, errors


def send_intelligence_email(setups, recipients):
    """Email top Intelligence Engine setups (score >= 80) to recipients."""
    if not setups:
        return 0, []
    rows = ''.join(
        f'<tr style="border-bottom:1px solid #1F2535">'
        f'<td style="padding:10px 0;font-family:\'Courier New\',Courier,monospace;font-size:16px;font-weight:700;color:#C8D8F0">{s["ticker"]}</td>'
        f'<td style="padding:10px 0;font-family:\'Courier New\',Courier,monospace;font-size:12px;color:#FFB300">{s["alert_level"]}</td>'
        f'<td style="padding:10px 0;font-family:\'Courier New\',Courier,monospace;font-size:13px;font-weight:700;color:#00E5FF">{s["combined_score"]}/100</td>'
        f'<td style="padding:10px 0;font-size:13px;color:#8898B8">{s.get("why_now","")[:80]}…</td>'
        f'</tr>'
        for s in setups[:5]
    )
    html = f"""<!DOCTYPE html><html><head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#08090C;font-family:Arial,sans-serif">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#08090C;padding:24px 0">
<tr><td align="center">
<table width="600" cellpadding="0" cellspacing="0" style="background:#0D0F14;border:1px solid #2A3348;border-radius:12px;overflow:hidden;max-width:600px">
  <tr><td style="background:linear-gradient(90deg,#FF8C00,#FFB300);padding:4px 0"></td></tr>
  <tr><td style="padding:24px 28px;border-bottom:1px solid #1F2535">
    <div style="font-family:'Courier New',monospace;font-size:10px;color:#5A6E88;letter-spacing:2px;margin-bottom:6px">SG TRADING · INTELLIGENCE ENGINE</div>
    <div style="font-size:22px;font-weight:700;color:#C8D8F0">🧠 Today's Top Setups</div>
    <div style="font-size:13px;color:#8898B8;margin-top:4px">{datetime.utcnow().strftime('%B %d, %Y · %H:%M UTC')}</div>
  </td></tr>
  <tr><td style="padding:20px 28px">
    <table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse">{rows}</table>
  </td></tr>
  <tr><td style="padding:16px 28px;text-align:center;border-top:1px solid #1F2535">
    <a href="{APP_URL}/dashboard" style="display:inline-block;background:#FF8C00;color:#08090C;font-family:'Courier New',monospace;font-size:11px;font-weight:700;letter-spacing:1.5px;text-decoration:none;padding:10px 28px;border-radius:8px">VIEW INTELLIGENCE TAB →</a>
  </td></tr>
  <tr><td style="padding:14px 28px;text-align:center"><div style="font-size:11px;color:#5A6E88">Not financial advice · SG Trading Dashboard</div></td></tr>
</table></td></tr></table></body></html>"""
    subject = f"🧠 Intelligence: {len(setups)} Strong Setup{'s' if len(setups)!=1 else ''} — {datetime.utcnow().strftime('%b %d')}"
    ok, errors = 0, []
    for r in recipients:
        success, err = _send_one(subject, html, r['email'], r.get('name'))
        if success: ok += 1
        else: errors.append(f"{r['email']}: {err}")
    return ok, errors


def send_trump_mention_alert(mention, breakout, recipients):
    """Urgent email when Trump publicly mentions a stock ticker."""
    ticker  = mention.get('ticker', '?')
    context = mention.get('context', 'Public statement')
    source  = mention.get('source', 'News')
    price   = breakout.get('price', '—') if breakout else '—'
    score   = breakout.get('score', '—') if breakout else '—'
    entry   = breakout.get('entry', '—') if breakout else '—'
    stop    = breakout.get('stop',  '—') if breakout else '—'
    target  = breakout.get('target','—') if breakout else '—'

    html = f"""<!DOCTYPE html><html><head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#08090C;font-family:Arial,sans-serif">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#08090C;padding:24px 0">
<tr><td align="center">
<table width="560" cellpadding="0" cellspacing="0" style="background:#0D0F14;border:1px solid #FF3D30;border-radius:12px;overflow:hidden;max-width:560px">
  <tr><td style="background:linear-gradient(90deg,#FF3D30,#FF8C00);padding:4px 0"></td></tr>
  <tr><td style="padding:24px 28px;border-bottom:1px solid #1F2535">
    <div style="font-family:'Courier New',monospace;font-size:10px;color:#FF3D30;letter-spacing:2px;margin-bottom:6px">🔴 TRUMP MENTION ALERT</div>
    <div style="font-size:32px;font-weight:700;color:#C8D8F0;letter-spacing:-0.02em">${ticker}</div>
    <div style="font-size:13px;color:#FF8C00;margin-top:6px">Source: {source}</div>
  </td></tr>
  <tr><td style="padding:20px 28px;border-bottom:1px solid #1F2535">
    <div style="font-family:'Courier New',monospace;font-size:10px;color:#5A6E88;letter-spacing:1.5px;margin-bottom:8px">WHAT HE SAID</div>
    <div style="font-size:14px;color:#C8D8F0;font-style:italic;line-height:1.6">"{context}"</div>
  </td></tr>
  <tr><td style="padding:20px 28px;border-bottom:1px solid #1F2535">
    <div style="font-family:'Courier New',monospace;font-size:10px;color:#5A6E88;letter-spacing:1.5px;margin-bottom:12px">OUR ANALYSIS</div>
    <table width="100%" cellpadding="0" cellspacing="0">
      <tr><td style="padding:5px 0;font-family:'Courier New',monospace;font-size:11px;color:#8898B8">Current Price</td>
          <td align="right" style="font-family:'Courier New',monospace;font-size:13px;font-weight:700;color:#C8D8F0">${price}</td></tr>
      <tr><td style="padding:5px 0;font-family:'Courier New',monospace;font-size:11px;color:#8898B8">Breakout Score</td>
          <td align="right" style="font-family:'Courier New',monospace;font-size:13px;font-weight:700;color:#FFB300">{score}/100</td></tr>
      <tr><td style="padding:5px 0;font-family:'Courier New',monospace;font-size:11px;color:#448AFF">Entry Zone</td>
          <td align="right" style="font-family:'Courier New',monospace;font-size:13px;font-weight:700;color:#448AFF">{entry}</td></tr>
      <tr><td style="padding:5px 0;font-family:'Courier New',monospace;font-size:11px;color:#FF3D5A">Stop Loss</td>
          <td align="right" style="font-family:'Courier New',monospace;font-size:13px;font-weight:700;color:#FF3D5A">{stop}</td></tr>
      <tr><td style="padding:5px 0;font-family:'Courier New',monospace;font-size:11px;color:#00E676">Target</td>
          <td align="right" style="font-family:'Courier New',monospace;font-size:13px;font-weight:700;color:#00E676">{target}</td></tr>
    </table>
  </td></tr>
  <tr><td style="padding:16px 28px;background:#0A0C11;border-top:1px solid #1F2535">
    <div style="font-size:12px;color:#8898B8;line-height:1.6">⚡ <strong style="color:#FF8C00">Act fast</strong> — retail investors typically follow within hours of a Trump mention.</div>
  </td></tr>
  <tr><td style="padding:16px 28px;text-align:center">
    <a href="{APP_URL}/dashboard" style="display:inline-block;background:#FF3D30;color:#fff;font-family:'Courier New',monospace;font-size:11px;font-weight:700;letter-spacing:1.5px;text-decoration:none;padding:10px 28px;border-radius:8px">VIEW DASHBOARD →</a>
  </td></tr>
  <tr><td style="padding:12px 28px;text-align:center"><div style="font-size:10px;color:#5A6E88">Not financial advice · SG Trading Dashboard</div></td></tr>
</table></td></tr></table></body></html>"""

    subject = f"\U0001f534 URGENT: Trump mentioned ${ticker} — Score {score}/100"
    ok, errors = 0, []
    for r in recipients:
        success, err = _send_one(subject, html, r['email'], r.get('name'))
        if success: ok += 1
        else: errors.append(f"{r['email']}: {err}")
    return ok, errors


def send_test_email(to_email, to_name=None):
    """Send a configuration test email. Returns (success, error_or_None)."""
    return _send_one(
        "✅ SG Trading — Email Alert Test",
        _test_html(),
        to_email,
        to_name,
    )
