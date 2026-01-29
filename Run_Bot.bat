@echo off
title BimiPal Bot Watchdog
:: Переходимо в папку скрипта (на випадок запуску від імені адміна)
cd /d "%~dp0"

:loop
echo -----------------------------------------
echo [Time: %time%] Starting BimiPal Bot...
echo -----------------------------------------

:: Активуємо venv і запускаємо бота
call venv\Scripts\activate
python main.py

:: Якщо бот впав або закрився, чекаємо 10 секунд і перезапускаємо
echo.
echo [WARNING] Bot crashed or stopped! Restarting in 10 seconds...
timeout /t 10
goto loop