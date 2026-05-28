# SG Trading Dashboard — Azure Deployment Guide

## Step 1 — Add API Keys to Azure (do this first)

In Azure Portal:
1. Go to your Web App
2. Click "Configuration" (left sidebar)
3. Click "Application settings" tab
4. Click "+ New application setting" and add:

   Name:  FINNHUB_API_KEY
   Value: (your Finnhub key)

   Name:  ANTHROPIC_API_KEY
   Value: (your Anthropic key)

5. Click Save

Your keys are now stored securely — never in any code file.

---

## Step 2 — Deploy via Azure CLI

Install Azure CLI from: https://docs.microsoft.com/cli/azure/install-azure-cli

Then run these commands from inside the trading-dashboard folder:

```bash
az login
az webapp up \
  --name sg-trading-hui \
  --resource-group trading-dashboard \
  --runtime "PYTHON:3.11" \
  --sku B1
```

Replace sg-trading-hui with your actual app name.

---

## Step 3 — Set Startup Command in Azure

In Azure Portal:
1. Go to your Web App
2. Configuration → General settings
3. Startup Command: 
   gunicorn --bind=0.0.0.0:8000 --timeout=120 --workers=1 app:app
4. Save + Restart

---

## Step 4 — Verify it's running

Visit: https://sg-trading-hui.azurewebsites.net/health

Should return: {"status": "ok", "message": "Trading Dashboard is live"}

Then visit: https://sg-trading-hui.azurewebsites.net

Your dashboard is live!

---

## Costs (monthly estimate)
- App Service B1:    ~$13
- Finnhub free:      $0
- Anthropic API:     ~$5-10
- Total:             ~$18-23/month

---

## Auto Scan Schedule
The scheduler runs automatically at 10:00 UTC = 6:00pm SGT every day.
Results are cached and ready when you open the dashboard.

---

## Updating the app
After any code changes, redeploy with:
```bash
az webapp up --name sg-trading-hui --resource-group trading-dashboard
```

---

## Setting up Google OAuth

1. Go to console.cloud.google.com
2. Create a new project OR select existing
3. APIs & Services → Credentials → Create Credentials → OAuth Client ID
4. Application type: Web application
5. Authorised redirect URIs:
   https://sg-trading-hui.azurewebsites.net/auth/google/callback
   http://localhost:8000/auth/google/callback (for local testing)
6. Copy Client ID and Client Secret

7. In Azure Portal → Your Web App → Configuration → Add:
   GOOGLE_CLIENT_ID     = your-client-id
   GOOGLE_CLIENT_SECRET = your-client-secret
   GOOGLE_REDIRECT_URI  = https://sg-trading-hui.azurewebsites.net/auth/google/callback
   SECRET_KEY           = any-long-random-string-here

That's it — Google login works automatically.

---

## Local testing without Google

Set in your .env file:
GOOGLE_CLIENT_ID=test
The Google button will show an error message
Email/password signup still works fully locally

---

## Setting up Breakout Email Alerts

The dashboard sends HTML emails automatically when a stock scores 80+ (IMMINENT).
Uses Python's built-in `smtplib` — no extra packages needed.

### Option A — Gmail (recommended)

1. Enable 2-Factor Authentication on your Gmail account
2. Go to **Google Account → Security → App Passwords**
3. Generate a password for "Mail" / "Other"
4. Add these to Azure Portal → Your Web App → Configuration → Application Settings:

   ```
   EMAIL_SENDER    = your.address@gmail.com
   EMAIL_PASSWORD  = xxxx-xxxx-xxxx-xxxx   ← the App Password (not your Gmail password)
   ```
   (EMAIL_SMTP_HOST and EMAIL_SMTP_PORT default to smtp.gmail.com / 587)

### Option B — Any SMTP provider

   ```
   EMAIL_SENDER    = alerts@yourdomain.com
   EMAIL_SMTP_HOST = smtp.yourprovider.com
   EMAIL_SMTP_PORT = 587
   EMAIL_PASSWORD  = yourpassword
   ```

### After configuring

1. Save + Restart in Azure Portal
2. Open the dashboard → **🔔 Alerts** tab → scroll to **Email Alert Recipients**
3. Add recipient email addresses
4. Click **📧 Send Test** to verify delivery
5. Run the Breakout Scanner — IMMINENT results (80+) trigger emails automatically,
   with a 24-hour dedup so each ticker only alerts once per day
