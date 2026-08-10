# handlers/expenses.py
# Ручне додавання доходу/витрати через FSM (кнопки "💸 Витрата" / "💰 Дохід").
from datetime import datetime

from aiogram import F, types
from aiogram.enums import ChatAction
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from services.api_client import api_client
from handlers import bot, dp
from handlers.base import go_back
from keyboards.reply import categories_kb, clean_category_name, description_kb, main_kb, remove_kb


class FinanceForm(StatesGroup):
    category_id, amount, description = State(), State(), State()


# "💸 Витрата (Готівка)" — legacy-текст старої клавіатури, лишаємо для сумісності.
@dp.message(F.text.in_(["💸 Витрата", "💸 Витрата (Готівка)", "💰 Дохід"]), StateFilter("*"))
async def add_tx_start(message: types.Message, state: FSMContext):
    await state.clear()
    user_info = await api_client.get_me(message.from_user.id)
    if not user_info:
        return await message.answer("❌ Акаунт не знайдено. Введи /start")

    t_type = "Поповнення" if "Дохід" in message.text else "Витрати"
    cat_type = "income" if t_type == "Поповнення" else "expense"

    cats = await api_client.get_categories(user_info["current_active_family_id"], cat_type)
    # "Очікує" — службова категорія для Inbox Zero, не пропонуємо її вручну
    cats = [c for c in cats if "Очікує" not in c['name']]
    if not cats:
        return await message.answer(
            "❌ Немає категорій. Створи їх у 📱 BimiApp.", reply_markup=main_kb())

    await state.update_data(t_type=t_type, family_id=user_info["current_active_family_id"], user_id=user_info["id"], cats=cats)
    await state.set_state(FinanceForm.category_id)
    hint = "💡 Або просто напиши «150 таксі» — без кнопок."
    await message.answer(f"Обери категорію:\n\n{hint}", reply_markup=categories_kb(cats))


@dp.message(StateFilter(FinanceForm.category_id))
async def add_tx_cat(message: types.Message, state: FSMContext):
    if message.text == "🔙 Назад":
        return await go_back(message, state)
    data = await state.get_data()
    cat_id = None
    for c in data['cats']:
        if clean_category_name(c['name']) == message.text:
            cat_id = c['id']
            break

    if not cat_id:
        return await message.answer("👇 Обери категорію з меню нижче або натисни «🔙 Назад»:")

    await state.update_data(category_id=cat_id, category_name=message.text)
    await state.set_state(FinanceForm.amount)
    await message.answer(f"💸 <b>{message.text}</b>\nВведи суму (числом):",
                         reply_markup=remove_kb(), parse_mode="HTML")


@dp.message(StateFilter(FinanceForm.amount))
async def add_tx_amount(message: types.Message, state: FSMContext):
    if message.text == "🔙 Назад":
        return await go_back(message, state)
    try:
        val = float(message.text.replace(',', '.').replace(' ', ''))
        if val <= 0:
            raise ValueError
    except (ValueError, AttributeError):
        return await message.answer("🔢 Введи додатне число, наприклад: 150 або 99.50")
    await state.update_data(amount=val)
    await state.set_state(FinanceForm.description)
    await message.answer("✍️ Коментар (що купили) — або пропусти:", reply_markup=description_kb())


@dp.message(StateFilter(FinanceForm.description))
async def add_tx_save(message: types.Message, state: FSMContext):
    if message.text == "🔙 Назад":
        return await go_back(message, state)
    data = await state.get_data()
    await bot.send_chat_action(message.chat.id, ChatAction.TYPING)
    date_now = datetime.now().strftime("%Y-%m-%d")
    title = data['category_name'] if message.text == "⏭ Пропустити" else message.text

    res = await api_client.add_transaction(data['family_id'], data['user_id'], data['category_id'], data['amount'],
                                           data['t_type'], title, "Готівка", None, date_now)
    await state.clear()
    if res:
        icon = "📈" if data['t_type'] == "Поповнення" else "📉"
        await message.answer(
            f"✅ {icon} <b>{data['amount']:,.2f} ₴</b> — {data['category_name']}".replace(",", " "),
            reply_markup=main_kb(), parse_mode="HTML")
    else:
        await message.answer("❌ Помилка збереження. Спробуй ще раз.", reply_markup=main_kb())
