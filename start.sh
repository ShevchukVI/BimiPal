#!/bin/bash

# Додаємо папку як безпечну для git, щоб уникнути помилок прав доступу в Docker
git config --global --add safe.directory /app

while true; do
    echo "-----------------------------------------"
    echo "[Time: $(date)] Checking for updates from GitHub..."
    echo "-----------------------------------------"
    
    # Стягуємо оновлення
    git pull origin main
    
    # Оновлюємо залежності на випадок, якщо ви додали нові в requirements.txt
    pip install -q -r requirements.txt
    
    echo ""
    echo "[Time: $(date)] Starting BimiPal Bot..."
    echo "-----------------------------------------"
    
    # Запускаємо бота
    python main.py
    
    # Цей код виконається тільки якщо бот впаде або викличе sys.exit(0) через /update або /restart
    echo ""
    echo "[WARNING] Bot crashed or stopped! Restarting in 5 seconds..."
    sleep 5
done