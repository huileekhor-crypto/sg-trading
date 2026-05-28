import os
from dotenv import load_dotenv

# Load .env file for local development only
# On Azure, these come from Application Settings (never hardcode keys)
load_dotenv()

class Config:
    # -------------------------------------------------------
    # API KEYS — Set these in Azure Portal:
    # App Service → Configuration → Application Settings
    # -------------------------------------------------------
    FINNHUB_API_KEY   = os.environ.get("FINNHUB_API_KEY", "")
    ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

    # Email alerts — set in Azure Portal Application Settings
    EMAIL_SENDER    = os.environ.get("EMAIL_SENDER", "")
    EMAIL_PASSWORD  = os.environ.get("EMAIL_PASSWORD", "")
    EMAIL_SMTP_HOST = os.environ.get("EMAIL_SMTP_HOST", "smtp.gmail.com")
    EMAIL_SMTP_PORT = int(os.environ.get("EMAIL_SMTP_PORT", "587"))

    # App settings
    SCAN_HOUR_UTC   = 10   # 6pm SGT = 10:00 UTC
    SCAN_MINUTE_UTC = 0
    MAX_WATCHLIST   = 20

    @classmethod
    def validate(cls):
        missing = []
        if not cls.FINNHUB_API_KEY:
            missing.append("FINNHUB_API_KEY")
        if not cls.ANTHROPIC_API_KEY:
            missing.append("ANTHROPIC_API_KEY")
        if missing:
            print(f"⚠ Warning: Missing API keys: {', '.join(missing)}")
            print("  → Set them in Azure Portal: App Service → Configuration → Application Settings")
        return len(missing) == 0
