# Нагадування Bimi: «Житло» (показники, оплати, оренда), кредити й розстрочки; синхронізація відключень світла.
# Бот — тонкий клієнт: що і кому нагадати, вирішує бекенд (/system/housing/*).
import logging
from urllib.parse import urlencode, urlparse, urlunparse, parse_qsl

from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

from config import APP_URL
from services.api_client import api_client

logger = logging.getLogger(__name__)


def app_url(tab: str) -> str:
    """APP_URL з ?tab=… (Mini App відкриється одразу на потрібному екрані)."""
    u = urlparse(APP_URL)
    q = dict(parse_qsl(u.query))
    q["tab"] = tab
    return urlunparse(u._replace(query=urlencode(q)))


LABELS = {"readings": "📸 Внести показники", "housing": "🏡 Відкрити «Житло»", "payments": "💳 Кредити й підписки",
          "analytics": "📊 Аналітика"}


def housing_kb(tab: str) -> InlineKeyboardMarkup:
    label = LABELS.get(tab, LABELS["housing"])
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=label, web_app=WebAppInfo(url=app_url(tab)))]])


async def send_housing_reminders(bot: Bot):
    items = await api_client.get_housing_reminders()
    acks = []
    for it in items:
        tab = it.get("tab") or ("readings" if any(k.startswith("readings:") for k in it.get("keys", [])) else "housing")
        delivered = False
        for tg_id in it.get("tg_ids", []):
            try:
                await bot.send_message(tg_id, it["text"], reply_markup=housing_kb(tab))
                delivered = True
            except Exception as e:  # blocked bot / chat not found — не зупиняємо розсилку
                logger.warning("housing reminder to %s failed: %s", tg_id, type(e).__name__)
        if delivered:
            acks += [{"family_id": it["family_id"], "key": k} for k in it.get("keys", [])]
    if acks:
        await api_client.ack_housing_reminders(acks)
    if items:
        logger.info("housing reminders: %d families, %d keys acked", len(items), len(acks))


async def sync_power_outages():
    res = await api_client.sync_power_outages()
    if res:
        changed = sum(r.get("changed", 0) for r in res if isinstance(r, dict))
        if changed:
            logger.info("power outages synced: %s", res)
