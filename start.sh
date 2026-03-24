#!/usr/bin/env bash

echo "Installing dependencies..."
pip install -r requirements.txt

echo "Installing Playwright..."
playwright install chromium

echo "Starting app..."
python main.py
