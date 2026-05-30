"""APScheduler — daily 6pm SGT (10:00 UTC) scan."""

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from config import Config

_scheduler = None


def start_scheduler():
    global _scheduler
    if _scheduler is not None:
        return

    _scheduler = BackgroundScheduler(timezone="UTC")
    _scheduler.add_job(
        func=_daily_scan,
        trigger=CronTrigger(hour=Config.SCAN_HOUR_UTC, minute=Config.SCAN_MINUTE_UTC),
        id="daily_scan",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    _scheduler.start()
    print(f"✓ Scheduler started — daily scan at {Config.SCAN_HOUR_UTC:02d}:{Config.SCAN_MINUTE_UTC:02d} UTC (6pm SGT)")


def _daily_scan():
    try:
        from routes.scanner import run_scan_job
        print("⏰ Scheduler triggered daily scan")
        run_scan_job()
    except Exception as e:
        print(f"Scheduled scan error: {e}")
