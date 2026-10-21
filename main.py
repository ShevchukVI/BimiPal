# main.py — легка точка входу.
# Уся логіка живих хендлерів винесена в handlers/ (Clean Architecture).
# Цей файл лише: збирає диспетчер, стартує polling, aiohttp-сервер для вебхуків
# Монобанку та планує щоденний бекап БД.
import asyncio
import logging

from aiohttp import web
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from handlers import bot, dp
from handlers.monobank import mono_webhook_get, mono_webhook_post, setup_monobank
from services.backups import run_daily_backup
from services.housing import send_housing_reminders, sync_power_outages

logging.basicConfig(level=logging.INFO)

scheduler = AsyncIOScheduler()


async def evening_summary_broadcast():
    # Заглушка до переробки
    pass


async def scheduled_backup():
    """Щоденний бекап БД о 03:00 — дамп йде адміну в Telegram."""
    await run_daily_backup(bot)


async def scheduled_housing_reminders():
    """«Житло»: показники / оплати / оренда — раз на день, бекенд дедуплікує."""
    await send_housing_reminders(bot)


async def on_startup():
    print("🚀 Запуск Телеграм-бота (SQL-ONLY VERSION)...")
    asyncio.create_task(setup_monobank())
    scheduler.add_job(scheduled_backup, 'cron', hour=3, minute=0)
    scheduler.add_job(scheduled_housing_reminders, 'cron', hour=10, minute=0, timezone='Europe/Kyiv')
    scheduler.add_job(sync_power_outages, 'interval', minutes=10, max_instances=1, coalesce=True)
    scheduler.start()
    await bot.delete_webhook(drop_pending_updates=True)


async def start_web_server():
    app = web.Application()
    app.router.add_get('/webhook', mono_webhook_get)
    app.router.add_post('/webhook', mono_webhook_post)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', 18080)
    await site.start()
    print("🌐 Web-сервер Монобанку запущено!")


async def main():
    dp.startup.register(on_startup)
    await start_web_server()
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
