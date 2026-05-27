#!/bin/bash
# Azure App Service startup script
pip install --quiet --no-cache-dir --prefer-binary -r requirements.txt
gunicorn --bind=0.0.0.0:8000 --timeout=120 --workers=1 app:app
