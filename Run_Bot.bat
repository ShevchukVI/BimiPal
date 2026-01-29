@echo off
title BimiPal Bot Watchdog
cd /d "%~dp0"

:loop
echo -----------------------------------------
echo [Time: %time%] Checking for updates...
echo -----------------------------------------

:: 1. Стягуємо оновлення з GitHub (тільки якщо є інтернет)
git pull origin main

echo.
echo [Time: %time%] Starting BimiPal Bot...
echo -----------------------------------------

:: 2. Активуємо venv і запускаємо бота
call venv\Scripts\activate
python main.py

:: 3. Якщо бот впав — чекаємо 10 сек і перезапускаємо
echo.
echo [WARNING] Bot crashed or stopped! Restarting in 10 seconds...
timeout /t 10
goto loop