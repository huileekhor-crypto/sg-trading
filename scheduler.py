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

    scheduler.add_job(
        check_price_alerts,
        IntervalTrigger(minutes=5),
        id='price_alerts',
        name='Price Alert Check (every 5 min)',
        replace_existing=True
    )

    scheduler.start()
    logger.info("⏰ Scheduler started — daily scan at 6:00pm SGT (10:00 UTC), alerts every 5 min")
