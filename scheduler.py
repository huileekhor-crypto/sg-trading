from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from datetime import datetime
import requests
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

scheduler = BackgroundScheduler()

def run_morning_scan():
    """
    Auto morning scan — runs at 6:00pm SGT (10:00 UTC) every day
    Scans US, Asia, and Crypto markets
    Results cached in memory (upgrade to Cosmos DB in Phase 2)
    """
    logger.info(f"🔍 Auto scan started at {datetime.now().isoformat()} UTC")
    regions = ['US', 'Asia', 'Crypto']

    for region in regions:
        try:
            # Call our own scanner endpoint
            response = requests.get(
                f'http://localhost:8000/api/scanner?region={region}&force=true',
                timeout=60
            )
            if response.status_code == 200:
                logger.info(f"✅ {region} scan complete")
            else:
                logger.warning(f"⚠ {region} scan returned {response.status_code}")
        except Exception as e:
            logger.error(f"❌ {region} scan failed: {str(e)}")

    logger.info("✅ All morning scans complete — results ready for review")


def check_price_alerts():
    """Check active price alerts every 5 minutes using Finnhub quotes."""
    try:
        from models.alerts import get_active_alerts, fire_alert
        from config import Config
        import finnhub
    except Exception as e:
        logger.error(f"❌ Alert check import error: {e}")
        return

    if not Config.FINNHUB_API_KEY:
        return

    alerts = get_active_alerts()
    if not alerts:
        return

    fc = finnhub.Client(api_key=Config.FINNHUB_API_KEY)

    # Batch by ticker to minimise API calls
    by_ticker = {}
    for a in alerts:
        by_ticker.setdefault(a['ticker'], []).append(a)

    fired_count = 0
    for ticker, ticker_alerts in by_ticker.items():
        try:
            quote = fc.quote(ticker)
            price = quote.get('c', 0)
            if not price:
                continue
            for a in ticker_alerts:
                triggered = (
                    (a['condition'] == 'above' and price >= a['target']) or
                    (a['condition'] == 'below' and price <= a['target'])
                )
                if triggered:
                    fire_alert(a['id'], price)
                    fired_count += 1
                    logger.info(f"🔔 Alert fired: {ticker} {a['condition']} ${a['target']} — current ${price:.2f}")
        except Exception as e:
            logger.warning(f"⚠ Alert check failed for {ticker}: {e}")

    if fired_count:
        logger.info(f"🔔 {fired_count} alert(s) fired")


def run_intelligence_scan():
    """Auto-run Intelligence Engine at 6:00pm SGT (10:00 UTC)."""
    logger.info(f"🧠 Intelligence scan started at {datetime.now().isoformat()} UTC")
    try:
        from routes.intelligence import run_intelligence_scan as _scan
        result = _scan()
        if result:
            count = len(result.get('setups', []))
            logger.info(f"✅ Intelligence scan complete — {count} setup(s) found")
        else:
            logger.warning("⚠ Intelligence scan returned no setups")
    except Exception as e:
        logger.error(f"❌ Intelligence scan failed: {e}")


def check_trump_mentions():
    """Every 2 hours: fetch latest Trump mentions → breakout scan → urgent email if score > 60."""
    logger.info(f"🔴 Trump mention check started at {datetime.now().isoformat()}")
    try:
        from utils.trump_cache import get_mentions, get_new_mentions
        get_mentions()                          # refresh cache (30-min TTL auto-handled)
        new_tickers = get_new_mentions()        # only newly appeared tickers
        if not new_tickers:
            logger.info("🔴 Trump mentions: no new tickers since last check")
            return

        from routes.breakout import _score_ticker, _get_market_regime
        from utils.trump_cache import get_mentions as _gm
        from models.alerts import get_active_recipients
        from utils.emailer import send_trump_mention_alert

        is_bull, _, _ = _get_market_regime()
        mentions_data = _gm()
        mention_map   = {m['ticker'].upper(): m for m in mentions_data.get('mentions', [])}
        recipients    = get_active_recipients()

        for ticker in new_tickers:
            logger.info(f"🔴 New Trump mention: {ticker}")
            try:
                brk = _score_ticker(ticker, is_bull)
                if brk and brk['score'] >= 60 and recipients:
                    mention = mention_map.get(ticker, {'ticker': ticker, 'context': '', 'source': 'News'})
                    send_trump_mention_alert(mention, brk, recipients)
                    logger.info(f"📧 Trump mention email sent for {ticker} (score {brk['score']})")
            except Exception as e:
                logger.warning(f"⚠ Trump mention scan failed for {ticker}: {e}")
    except Exception as e:
        logger.error(f"❌ Trump mention check failed: {e}")


def start_scheduler():
    """Start the background scheduler"""
    # Run every day at 10:00 UTC = 6:00pm SGT
    scheduler.add_job(
        run_morning_scan,
        CronTrigger(hour=10, minute=0, timezone='UTC'),
        id='morning_scan',
        name='Daily Morning Scan (6pm SGT)',
        replace_existing=True
    )

    # Intelligence Engine — runs at 10:05 UTC (after market scan)
    scheduler.add_job(
        run_intelligence_scan,
        CronTrigger(hour=10, minute=5, timezone='UTC'),
        id='intelligence_scan',
        name='Intelligence Engine (6:05pm SGT)',
        replace_existing=True
    )

    scheduler.add_job(
        check_price_alerts,
        IntervalTrigger(minutes=5),
        id='price_alerts',
        name='Price Alert Check (every 5 min)',
        replace_existing=True
    )

    scheduler.add_job(
        check_trump_mentions,
        IntervalTrigger(hours=2),
        id='trump_mentions',
        name='Trump Mention Check (every 2 hours)',
        replace_existing=True
    )

    scheduler.start()
    logger.info("⏰ Scheduler started — daily scan at 6:00pm SGT (10:00 UTC), alerts every 5 min")
