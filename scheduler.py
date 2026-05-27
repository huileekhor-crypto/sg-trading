from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
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

    scheduler.start()
    logger.info("⏰ Scheduler started — daily scan at 6:00pm SGT (10:00 UTC)")
