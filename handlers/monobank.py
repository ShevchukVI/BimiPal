# handlers/monobank.py
# Інтеграція з Monobank: вебхуки, баланси, Inbox Zero (розбір "Очікує").
import asyncio
import time

import aiohttp
from aiohttp import web

from aiogram import F, types
from aiogram.enums import ChatAction
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from services.api_client import api_client
from config import WEBHOOK_URL
from handlers import bot, dp
from keyboards.inline import after_categorize_kb, generate_mono_keyboard, next_unresolved_kb

MONO_ACCOUNT_TO_USER = {}
MONO_BALANCES_CACHE = {}
PROCESSED_MONO_IDS = set()


class MonoCommentForm(StatesGroup):
    text = State()


# ================= МОНОБАНК: НАЛАШТУВАННЯ ТА ВЕБХУКИ =================
async def setup_monobank():
    tokens_data = await api_client._get("/system/mono-tokens")
    if not tokens_data:
        return

    for item in tokens_data:
        tg_id = item['tg_id']
        token = item['mono_token']
        async with aiohttp.ClientSession() as session:
            try:
                await session.post("https://api.monobank.ua/personal/webhook", headers={"X-Token": token},
                                   json={"webHookUrl": WEBHOOK_URL})
            except Exception:
                pass
            try:
                async with session.get("https://api.monobank.ua/personal/client-info",
                                       headers={"X-Token": token}) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        for acc in data.get("accounts", []):
                            MONO_ACCOUNT_TO_USER[acc["id"]] = tg_id
            except Exception:
                pass


async def fetch_mono_balance(tg_id: int):
    user_info = await api_client.get_me(tg_id)
    if not user_info or not user_info.get("has_mono_token"):
        return 0.0

    if tg_id not in MONO_BALANCES_CACHE:
        MONO_BALANCES_CACHE[tg_id] = {"time": 0, "balance": 0.0}
    now = time.time()
    if now - MONO_BALANCES_CACHE[tg_id]["time"] < 65:
        return MONO_BALANCES_CACHE[tg_id]["balance"]

    tokens_data = await api_client._get("/system/mono-tokens")
    token = next((t['mono_token'] for t in tokens_data if t['tg_id'] == tg_id), None) if tokens_data else None

    if not token:
        return 0.0

    async with aiohttp.ClientSession() as session:
        try:
            async with session.get("https://api.monobank.ua/personal/client-info", headers={"X-Token": token}) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    total_bal = sum(
                        (acc.get("balance", 0) - acc.get("creditLimit", 0)) for acc in data.get("accounts", [])) / 100.0
                    MONO_BALANCES_CACHE[tg_id] = {"time": now, "balance": total_bal}
                    return total_bal
        except Exception:
            pass
    return MONO_BALANCES_CACHE[tg_id]["balance"]


async def process_mono_webhook_background(data):
    if data.get("type") == "StatementItem":
        acc_id, statement = data["data"]["account"], data["data"]["statementItem"]
        mono_id = statement.get("id")
        if mono_id in PROCESSED_MONO_IDS:
            return
        PROCESSED_MONO_IDS.add(mono_id)
        if len(PROCESSED_MONO_IDS) > 5000:
            PROCESSED_MONO_IDS.clear()

        amount = statement.get("amount", 0) / 100.0
        desc = statement.get("description", "Без опису")
        if statement.get("comment"):
            desc += f" ({statement.get('comment')})"

        tg_id = MONO_ACCOUNT_TO_USER.get(acc_id)
        if tg_id and amount < 0:
            real_amount = abs(amount)
            user_info = await api_client.get_me(tg_id)
            if not user_info:
                return

            cats = await api_client.get_categories(user_info["current_active_family_id"])
            pending_cat = next((c['id'] for c in cats if "Очікує" in c['name']), None)
            if not pending_cat:
                return

            res = await api_client.add_transaction(user_info["current_active_family_id"], user_info["id"], pending_cat, real_amount,
                                                   "Витрати", f"❓ {desc}", "Монобанк", mono_id)
            if res:
                try:
                    await bot.send_message(tg_id,
                                           f"💳 <b>Нова витрата:</b>\n💰 {real_amount:.2f} ₴\n🛒 {desc}\n\n<i>Обери категорію:</i>",
                                           reply_markup=generate_mono_keyboard(mono_id, cats), parse_mode="HTML")
                except Exception:
                    pass


async def mono_webhook_get(request):
    return web.Response(text="OK", status=200)


async def mono_webhook_post(request):
    try:
        data = await request.json()
    except Exception:
        return web.Response(status=400)
    asyncio.create_task(process_mono_webhook_background(data))
    return web.Response(text="OK", status=200)


# ================= INBOX ZERO =================
async def send_next_unresolved(chat_id, tg_id):
    await bot.send_chat_action(chat_id, ChatAction.TYPING)
    user_info = await api_client.get_me(tg_id)
    if not user_info:
        return

    unresolved = await api_client.get_unresolved(user_info["current_active_family_id"], user_info["id"])
    if not unresolved:
        return await bot.send_message(chat_id, "🎉 <b>Все чисто!</b> Нерозібраних транзакцій немає.", parse_mode="HTML")

    tx = unresolved[0]
    cats = await api_client.get_categories(user_info["current_active_family_id"], "expense")
    await bot.send_message(chat_id,
                           f"⏳ <b>Нерозібрана витрата:</b>\n📅 {tx['date']}\n💰 {tx['amount']} ₴\n🛒 {tx['title']}\n\n<i>Обери категорію:</i>",
                           reply_markup=generate_mono_keyboard(tx["mono_id"], cats), parse_mode="HTML")


@dp.message(F.text == "🧹 Розібрати 'Очікує'", StateFilter("*"))
async def trigger_inbox_zero(message: types.Message):
    await send_next_unresolved(message.chat.id, message.from_user.id)


@dp.callback_query(F.data == "mnext")
async def trigger_next_unresolved_btn(call: types.CallbackQuery):
    try:
        await call.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await send_next_unresolved(call.message.chat.id, call.from_user.id)


@dp.callback_query(F.data.startswith("mcat:"))
async def mono_categorize(call: types.CallbackQuery):
    _, mono_id, cat_id = call.data.split(":", 2)
    user_info = await api_client.get_me(call.from_user.id)
    cats = await api_client.get_categories(user_info["current_active_family_id"])
    cat = next((c for c in cats if str(c['id']) == cat_id), None)
    if not cat:
        return await call.message.edit_text("❌ Категорію не знайдено.")

    await call.message.edit_text(f"⏳ <i>Зберігаю в {cat['name']}...</i>", parse_mode="HTML")

    if await api_client.update_tx_by_mono(mono_id, category_id=int(cat_id)):
        orig_text = call.message.text.replace("Обери категорію:", "").replace("Нерозібрана витрата:",
                                                                              "Нова витрата:").strip()
        await call.message.edit_text(
            f"{orig_text}\n\n✅ <b>Записано в:</b> {cat['name']}\n\n<i>Бажаєш додати деталі покупки?</i>",
            reply_markup=after_categorize_kb(mono_id), parse_mode="HTML")
    else:
        await call.message.edit_text("❌ Помилка оновлення таблиці.")


@dp.callback_query(F.data == "mdon")
async def mono_done(call: types.CallbackQuery):
    await call.message.edit_text(f"{call.message.text.replace('Бажаєш додати деталі покупки?', '').strip()}\n✅ Готово.",
                                 reply_markup=next_unresolved_kb(),
                                 parse_mode="HTML")


@dp.callback_query(F.data.startswith("mdsc:"))
async def mono_ask_desc(call: types.CallbackQuery, state: FSMContext):
    await state.update_data(mono_id=call.data.split(":")[1], msg_id=call.message.message_id,
                            orig_text=call.message.text)
    await state.set_state(MonoCommentForm.text)
    await bot.send_message(call.message.chat.id, "✍️ Напиши свій коментар до цієї покупки текстом сюди:")
    await call.answer()


@dp.message(MonoCommentForm.text)
async def mono_save_desc(message: types.Message, state: FSMContext):
    data = await state.get_data()
    mono_id, msg_id, orig_text = data.get('mono_id'), data.get('msg_id'), data.get('orig_text', '')

    new_title = f"{orig_text.split('🛒')[1].split('Обери')[0].strip()} | {message.text}"

    if await api_client.update_tx_by_mono(mono_id, note=new_title):
        await message.answer("✅ Твій коментар успішно додано!", reply_markup=next_unresolved_kb())
        try:
            await bot.edit_message_text(
                f"{orig_text.replace('Бажаєш додати деталі покупки?', '').strip()}\n💬 <i>{message.text}</i>",
                chat_id=message.chat.id, message_id=msg_id, parse_mode="HTML")
        except Exception:
            pass
    else:
        await message.answer("❌ Помилка збереження коментаря.")
    await state.clear()


@dp.callback_query(F.data.startswith("mdel:"))
async def mono_delete_tx(call: types.CallbackQuery):
    _, mono_id = call.data.split(":", 1)
    user_info = await api_client.get_me(call.from_user.id)
    if await api_client.delete_tx_by_mono(user_info["current_active_family_id"], mono_id):
        await call.message.edit_text("🗑 Цю транзакцію стерто.", reply_markup=next_unresolved_kb())
    else:
        await call.message.edit_text("❌ Помилка видалення.")


@dp.callback_query(F.data.startswith("mltr:"))
async def mono_later(call: types.CallbackQuery):
    orig_text = call.message.text.replace("Обери категорію:", "").strip()
    await call.message.edit_text(f"{orig_text}\n\n⏳ <b>Відкладено на потім.</b>", reply_markup=next_unresolved_kb(),
                                 parse_mode="HTML")
