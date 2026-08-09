# handlers/quick_add.py
# Zero Friction: користувач просто пише «150 такси» або «+5000 зарплата» —
# бот пропонує категорію інлайн-кнопками і записує транзакцію в один дотик.
# ЗАРЕЄСТРОВАНО ОСТАННІМ у handlers/__init__.py — щоб FSM-хендлери
# (expenses, monobank) та scratchpad (📝) мали пріоритет.
import re

from aiogram import F, types
from aiogram.enums import ChatAction
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from services.api_client import api_client
from handlers import bot, dp
from keyboards.inline import quick_add_kb, quick_add_undo_kb

# «150 такси», «+5000 зп», «-99.50 кава», «150»
QUICK_RE = re.compile(r'^([+-]?)\s*(\d+(?:[.,]\d{1,2})?)\s*(.{0,120}?)\s*$', re.S)

MAX_QUICK_AMOUNT = 10_000_000


class QuickAddForm(StatesGroup):
    category = State()


@dp.message(F.text.regexp(QUICK_RE), StateFilter("*"))
async def quick_add_start(message: types.Message, state: FSMContext):
    # Поточний FSM-стан (якщо є) обробляють хендлери вище — сюди потрапляємо
    # лише коли жоден з них не спрацював.
    await state.clear()
    m = QUICK_RE.match(message.text)
    sign, raw_amount, title = m.group(1), m.group(2), m.group(3)
    try:
        amount = float(raw_amount.replace(',', '.'))
    except ValueError:
        return
    if amount <= 0 or amount > MAX_QUICK_AMOUNT:
        return await message.answer("🔢 Сума має бути від 0.01 до 10 000 000.")

    user_info = await api_client.get_me(message.from_user.id)
    if not user_info:
        return await message.answer("❌ Акаунт не знайдено. Введи /start")
    family_id = user_info.get("current_active_family_id")
    if not family_id:
        return await message.answer("❌ Немає активної сім'ї. Використай /families")

    t_type = "Поповнення" if sign == "+" else "Витрати"
    cat_type = "income" if t_type == "Поповнення" else "expense"
    cats = await api_client.get_categories(family_id, cat_type)
    cats = [c for c in cats if "Очікує" not in c['name']]
    if not cats:
        return await message.answer("❌ Немає категорій. Створи їх у 📱 BimiApp.")

    await state.update_data(amount=amount, title=title, t_type=t_type,
                            family_id=family_id, user_id=user_info["id"], cats=cats)
    await state.set_state(QuickAddForm.category)

    icon = "📈" if t_type == "Поповнення" else "📉"
    desc = f" — «{title}»" if title else ""
    await message.answer(
        f"{icon} <b>{amount:,.2f} ₴</b>{desc}\nОбери категорію:".replace(",", " "),
        reply_markup=quick_add_kb(cats), parse_mode="HTML")


@dp.callback_query(F.data.startswith("qa:"), StateFilter(QuickAddForm.category))
async def quick_add_save(call: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    cats = data.get("cats", [])
    try:
        cat = cats[int(call.data.split(":")[1])]
    except (ValueError, IndexError):
        return await call.answer("Категорію не знайдено", show_alert=True)

    await bot.send_chat_action(call.message.chat.id, ChatAction.TYPING)
    title = data["title"] or cat["name"]
    res = await api_client.add_transaction(data["family_id"], data["user_id"], cat["id"],
                                           data["amount"], data["t_type"], title, "Готівка")
    await state.clear()
    if res:
        await call.message.edit_text(
            f"✅ <b>{data['amount']:,.2f} ₴</b> → {cat['name']}\n"
            f"📝 {title}".replace(",", " "),
            reply_markup=quick_add_undo_kb(res["id"]), parse_mode="HTML")
    else:
        await call.message.edit_text("❌ Помилка збереження. Спробуй ще раз.")


@dp.callback_query(F.data == "qac", StateFilter(QuickAddForm.category))
async def quick_add_cancel(call: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.edit_text("🚫 Скасовано.")


@dp.callback_query(F.data.startswith("qa:"))
@dp.callback_query(F.data == "qac")
async def quick_add_stale(call: types.CallbackQuery, state: FSMContext):
    """Fallback: FSM-стан втрачено (перезапуск бота) — старі кнопки не мертві."""
    if await state.get_state() is not None:
        return  # активний стан обробляють хендлери вище
    await call.answer("Ця сесія застаріла. Напиши суму ще раз 🙂", show_alert=True)


@dp.callback_query(F.data.startswith("qu:"))
async def quick_add_undo(call: types.CallbackQuery):
    try:
        tx_id = int(call.data.split(":")[1])
    except (ValueError, IndexError):
        return await call.answer("Помилка", show_alert=True)
    if await api_client.delete_transaction(tx_id):
        await call.message.edit_text(f"↩️ <s>{call.message.text}</s>\n<b>Запис скасовано.</b>",
                                     parse_mode="HTML")
    else:
        await call.answer("Не вдалося скасувати", show_alert=True)
