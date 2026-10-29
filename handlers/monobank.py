# handlers/monobank.py
import asyncio
import logging
import time

from aiohttp import web

logger = logging.getLogger(__name__)

from aiogram import F, types
from aiogram.enums import ChatAction
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from services.api_client import api_client
from config import WEBHOOK_URL
from handlers import bot, dp
from keyboards.inline import after_categorize_kb, auto_done_keyboard, generate_mono_keyboard, next_unresolved_kb
from utils import esc

MONO_ACCOUNT_TO_USER = {}
MONO_BALANCES_CACHE = {}
PROCESSED_MONO_IDS = set()


class MonoCommentForm(StatesGroup):
    text = State()


async def _load_accounts_from_backend():
    """Завантажує banking-аккаунти з backend: external_account_id → tg_id.
    /banking/accounts повертає user_id (DB), тому з'єднуємо з /system/mono-tokens
    (user_id → tg_id), щоб вебхуки могли звертатися до /auth/me?tg_id=..."""
    accounts = await api_client._get("/banking/accounts")
    tokens = await api_client._get("/system/mono-tokens")
    tg_by_user = {t["user_id"]: t["tg_id"] for t in (tokens or [])}
    if accounts:
        MONO_ACCOUNT_TO_USER.clear()
        for a in accounts:
            tg_id = tg_by_user.get(a["user_id"])
            if tg_id:
                MONO_ACCOUNT_TO_USER[a["external_account_id"]] = tg_id


# ================= МОНОБАНК: НАЛАШТУВАННЯ ТА ВЕБХУКИ =================
async def setup_monobank():
    # Делегуємо синхронізацію backend'у (accounts + webhooks)
    results = await api_client._post(
        f"/banking/sync?webhook_url={WEBHOOK_URL}",
        [], method="post"
    )
    if not results:
        logger.warning("No Monobank tokens found — webhooks NOT registered")
        return

    # Оновлюємо локальний mapping з бази (external_account_id → tg_id)
    await _load_accounts_from_backend()
    if MONO_ACCOUNT_TO_USER:
        logger.info(f"Loaded {len(MONO_ACCOUNT_TO_USER)} bank accounts from backend")
    else:
        logger.warning("No bank accounts returned from backend")


async def fetch_mono_balance(tg_id: int):
    if tg_id not in MONO_BALANCES_CACHE:
        MONO_BALANCES_CACHE[tg_id] = {"time": 0, "balance": 0.0}
    now = time.time()
    if now - MONO_BALANCES_CACHE[tg_id]["time"] < 65:
        return MONO_BALANCES_CACHE[tg_id]["balance"]

    result = await api_client._get(f"/banking/balance/{tg_id}")
    if result and result.get("has_token"):
        bal = result["balance"]
        MONO_BALANCES_CACHE[tg_id] = {"time": now, "balance": bal}
        return bal
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
        if not tg_id or amount == 0:
            return
        is_expense = amount < 0
        real_amount = abs(amount)
        t_type = "Витрати" if is_expense else "Поповнення"
        cat_type = "expense" if is_expense else "income"
        icon = "📉" if is_expense else "📈"

        user_info = await api_client.get_me(tg_id)
        if not user_info:
            return

        all_cats = await api_client.get_categories(user_info["current_active_family_id"])
        pending_cat = next((c['id'] for c in all_cats if "Очікує" in c['name']), None)
        if not pending_cat:
            return

        family_id = user_info["current_active_family_id"]
        res = await api_client.add_transaction(family_id, user_info["id"], pending_cat, real_amount,
                                               t_type, f"❓ {desc}", "Монобанк", mono_id, mcc=statement.get("mcc"))
        if res and res.get("category_id") not in (None, pending_cat):
            # «Bimi розкладає сам»: бекенд уже поставив категорію (метро → транспорт) — лише повідомляємо
            cat = next((c for c in all_cats if c['id'] == res["category_id"]), None)
            what = "🤖 Bimi розклав" if res.get("auto_category") else "🔗 Пов'язано"
            try:
                await bot.send_message(tg_id,
                                       f"💳 <b>Нова {'витрата' if is_expense else 'виплата'}:</b>\n"
                                       f"{icon} {real_amount:.2f} ₴\n🛒 {esc(desc)}\n\n{what}: <b>{esc(cat['name'] if cat else '')}</b>",
                                       reply_markup=auto_done_keyboard(res["id"]), parse_mode="HTML")
            except Exception:
                pass
        elif res:
            # Категорії для клавіатури — тільки потрібного типу (витрати/доходи)
            cats = [c for c in all_cats if c['type'] == cat_type and "Очікує" not in c['name']]
            sug = await api_client.suggest_category(family_id, res["id"])
            hint = f"\n✨ <i>Bimi пропонує: {esc(sug.get('category_name', ''))} — {esc(sug.get('reason', ''))}</i>" if sug.get("category_id") else ""
            try:
                await bot.send_message(tg_id,
                                       f"💳 <b>Нова {'витрата' if is_expense else 'виплата'}:</b>\n"
                                       f"{icon} {real_amount:.2f} ₴\n🛒 {esc(desc)}{hint}\n\n<i>Обери категорію:</i>",
                                       reply_markup=generate_mono_keyboard(res["id"], cats, suggested=sug), parse_mode="HTML")
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
    cat_type = "income" if tx['type'] == "Поповнення" else "expense"
    cats = await api_client.get_categories(user_info["current_active_family_id"], cat_type)
    cats = [c for c in cats if "Очікує" not in c['name']]
    sign = "+" if tx['type'] == "Поповнення" else ""
    sug = await api_client.suggest_category(user_info["current_active_family_id"], tx["id"])
    hint = f"\n✨ <i>Bimi пропонує: {esc(sug.get('category_name', ''))} — {esc(sug.get('reason', ''))}</i>" if sug.get("category_id") else ""
    await bot.send_message(chat_id,
                           f"⏳ <b>Нерозібраних: {len(unresolved)}</b>\n"
                           f"📅 {tx['date']}\n💰 {sign}{tx['amount']} ₴\n🛒 {esc(tx['title'])}{hint}\n\n<i>Обери категорію:</i>",
                           reply_markup=generate_mono_keyboard(tx["id"], cats, suggested=sug), parse_mode="HTML")


@dp.message(F.text.startswith("🧹 Розібрати"), StateFilter("*"))
async def trigger_inbox_zero(message: types.Message):
    await send_next_unresolved(message.chat.id, message.from_user.id)


@dp.callback_query(F.data == "mnext")
async def trigger_next_unresolved_btn(call: types.CallbackQuery):
    try:
        await call.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await send_next_unresolved(call.message.chat.id, call.from_user.id)


@dp.callback_query(F.data.startswith("mall:"))
async def mono_show_all_cats(call: types.CallbackQuery):
    """Розгорнути повний список категорій для розбору транзакції."""
    try:
        tx_id = int(call.data.split(":")[1])
    except (ValueError, IndexError):
        return await call.answer("Помилка", show_alert=True)
    user_info = await api_client.get_me(call.from_user.id)
    if not user_info:
        return await call.answer("Акаунт не знайдено", show_alert=True)
    cats = await api_client.get_categories(user_info["current_active_family_id"])
    cats = [c for c in cats if "Очікує" not in c['name']]
    try:
        await call.message.edit_reply_markup(reply_markup=generate_mono_keyboard(tx_id, cats, expanded=True))
    except Exception:
        pass
    await call.answer()


@dp.callback_query(F.data.startswith("mcat:"))
async def mono_categorize(call: types.CallbackQuery):
    try:
        _, tx_id, cat_id = call.data.split(":", 2)
        tx_id, cat_id = int(tx_id), int(cat_id)
    except (ValueError, IndexError):
        return await call.message.edit_text("❌ Помилка розбору callback.")
    user_info = await api_client.get_me(call.from_user.id)
    cats = await api_client.get_categories(user_info["current_active_family_id"])
    cat = next((c for c in cats if c['id'] == cat_id), None)
    if not cat:
        return await call.message.edit_text("❌ Категорію не знайдено.")

    await call.message.edit_text(f"⏳ <i>Зберігаю в {esc(cat['name'])}...</i>", parse_mode="HTML")

    if await api_client.update_transaction(tx_id, category_id=cat_id):
        orig_text = call.message.text.replace("Обери категорію:", "").replace("Нерозібрана витрата:",
                                                                              "Нова витрата:").strip()
        await call.message.edit_text(
            f"{orig_text}\n\n✅ <b>Записано в:</b> {esc(cat['name'])}\n\n<i>Бажаєш додати деталі покупки?</i>",
            reply_markup=after_categorize_kb(tx_id), parse_mode="HTML")
    else:
        await call.message.edit_text("❌ Помилка оновлення транзакції. Спробуй ще раз.")


@dp.callback_query(F.data == "mdon")
async def mono_done(call: types.CallbackQuery):
    await call.message.edit_text(f"{call.message.text.replace('Бажаєш додати деталі покупки?', '').strip()}\n✅ Готово.",
                                 reply_markup=next_unresolved_kb(),
                                 parse_mode="HTML")


@dp.callback_query(F.data.startswith("mdsc:"))
async def mono_ask_desc(call: types.CallbackQuery, state: FSMContext):
    try:
        tx_id = int(call.data.split(":")[1])
    except (ValueError, IndexError):
        return await call.answer("Помилка", show_alert=True)
    await state.update_data(tx_id=tx_id, msg_id=call.message.message_id,
                            orig_text=call.message.text)
    await state.set_state(MonoCommentForm.text)
    await bot.send_message(call.message.chat.id, "✍️ Напиши свій коментар до цієї покупки текстом сюди:")
    await call.answer()


@dp.message(MonoCommentForm.text)
async def mono_save_desc(message: types.Message, state: FSMContext):
    data = await state.get_data()
    tx_id, msg_id, orig_text = data.get('tx_id'), data.get('msg_id'), data.get('orig_text', '')

    # P0-5: коментар користувача зберігаємо в note, а не перезаписуємо title (merchant).
    if tx_id and await api_client.update_transaction(tx_id, note=message.text.strip()):
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
    try:
        tx_id = int(call.data.split(":")[1])
    except (ValueError, IndexError):
        return await call.answer("Помилка", show_alert=True)
    if await api_client.delete_transaction(tx_id):
        await call.message.edit_text("🗑 Цю транзакцію стерто.", reply_markup=next_unresolved_kb())
    else:
        await call.message.edit_text("❌ Помилка видалення.")


@dp.callback_query(F.data.startswith("mltr:"))
async def mono_later(call: types.CallbackQuery):
    orig_text = call.message.text.replace("Обери категорію:", "").strip()
    await call.message.edit_text(f"{orig_text}\n\n⏳ <b>Відкладено на потім.</b>", reply_markup=next_unresolved_kb(),
                                 parse_mode="HTML")
