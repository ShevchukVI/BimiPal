#!/bin/bash

git config --global --add safe.directory /app

while true; do
    echo "-----------------------------------------"
    echo "[DEV] [Time: $(date)] Checking for updates from GitHub (dev branch)..."
    echo "-----------------------------------------"

    git fetch origin dev
    git checkout dev
    git pull origin dev

    pip install -q -r requirements.txt

    echo ""
    echo "[DEV] [Time: $(date)] Starting BimiPal DEV Bot..."
    echo "-----------------------------------------"

    python main.py

    echo ""
    echo "[DEV] [WARNING] Bot crashed or stopped! Restarting in 5 seconds..."
    sleep 5
done
