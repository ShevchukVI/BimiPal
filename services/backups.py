# services/backups.py
# Щоденний бекап бази даних: тягне .sql.gz дамп з BimiFinance (GET /system/backup,
# захищений X-API-Key), перевіряє розмір і відправляє адміну в Telegram.
import logging
from datetime import datetime

from aiogram import Bot
from aiogram.types import BufferedInputFile

from config import ADMIN_TELEGRAM_CHAT_ID
from services.api_client import api_client

logger = logging.getLogger(__name__)

MIN_BACKUP_SIZE = 1024  # 1 KB — порожній/битий дамп не відправляємо


async def run_daily_backup(bot: Bot) -> bool:
    """Завантажує і перевіряє дамп БД, надсилає його в адмін-чат. Повертає успіх."""
    chat_id = ADMIN_TELEGRAM_CHAT_ID
    if not chat_id:
        logger.warning("ADMIN_TELEGRAM_CHAT_ID не задано — бекап пропущено.")
        return False

    data = await api_client.get_backup()
    if not data:
        logger.error("Бекап: не вдалося завантажити дамп з бекенду.")
        return False
    if len(data) <= MIN_BACKUP_SIZE:
        logger.error(f"Бекап: дамп замалий ({len(data)} B) — скасовано.")
        return False

    now = datetime.now()
    filename = f"bimi_backup_{now.strftime('%Y%m%d_%H%M')}.sql.gz"
    caption = (
        f"🛟 <b>Щоденний бекап БД</b>\n"
        f"📦 {len(data) / 1024:.1f} KB\n"
        f"🕒 {now.strftime('%d.%m.%Y %H:%M')}"
    )
    try:
        await bot.send_document(
            chat_id=chat_id,
            document=BufferedInputFile(data, filename=filename),
            caption=caption,
            parse_mode="HTML",
        )
        logger.info(f"Бекап надіслано адміну: {filename} ({len(data)} B)")
        return True
    except Exception as e:
        logger.error(f"Бекап: помилка надсилання в Telegram: {e}")
        return False
