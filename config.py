import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    FINNHUB_API_KEY   = os.environ.get("FINNHUB_API_KEY", "")
    ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
    UW_API_KEY        = os.environ.get("UW_API_KEY", "")

    EMAIL_SENDER    = os.environ.get("EMAIL_SENDER", "")
    EMAIL_PASSWORD  = os.environ.get("EMAIL_PASSWORD", "")
    EMAIL_SMTP_HOST = os.environ.get("EMAIL_SMTP_HOST", "smtp.gmail.com")
    EMAIL_SMTP_PORT = int(os.environ.get("EMAIL_SMTP_PORT", "587"))

    # 6pm SGT = 10:00 UTC
    SCAN_HOUR_UTC   = 10
    SCAN_MINUTE_UTC = 0

    # Account defaults (overridden per user in settings)
    DEFAULT_ACCOUNT_SIZE  = 20000
    DEFAULT_SWING_RISK    = 2.0
    DEFAULT_LT_POSITION   = 7.5
    DEFAULT_WEEKLY_TARGET = 1500
