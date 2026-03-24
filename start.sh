#!/usr/bin/env bash

echo "Installing dependencies..."
pip install -r requirements.txt

echo "Installing Playwright..."
playwright install chromium

echo "Starting FastAPI server..."
uvicorn api.server:app --host 0.0.0.0 --port $PORT
