# handlers/expenses.py
# Ручне додавання доходу/витрати через FSM (кнопки "💸 Витрата (Готівка)" / "💰 Дохід").
from datetime import datetime

from aiogram import F, types
from aiogram.enums import ChatAction
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from services.api_client import api_client
from handlers import bot, dp
from handlers.base import go_back
from keyboards.reply import categories_kb, clean_category_name, main_kb, remove_kb


class FinanceForm(StatesGroup):
    category_id, amount, description = State(), State(), State()


@dp.message(F.text.in_(["💸 Витрата (Готівка)", "💰 Дохід"]), StateFilter("*"))
async def add_tx_start(message: types.Message, state: FSMContext):
    await state.clear()
    user_info = await api_client.get_me(message.from_user.id)
    if not user_info:
        return await message.answer("❌ Акаунт не знайдено. Введіть /start")

    t_type = "Поповнення" if "Дохід" in message.text else "Витрати"
    cat_type = "income" if t_type == "Поповнення" else "expense"

    cats = await api_client.get_categories(user_info["current_active_family_id"], cat_type)
    if not cats:
        return await message.answer("❌ Немає категорій. Створіть їх у додатку.")

    await state.update_data(t_type=t_type, family_id=user_info["current_active_family_id"], user_id=user_info["id"], cats=cats)
    await state.set_state(FinanceForm.category_id)
    await message.answer("Оберіть категорію:", reply_markup=categories_kb(cats))


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
        return await message.answer("Оберіть категорію з меню!")

    await state.update_data(category_id=cat_id, category_name=message.text)
    await state.set_state(FinanceForm.amount)
    await message.answer("Введіть суму (числом):", reply_markup=remove_kb())


@dp.message(StateFilter(FinanceForm.amount))
async def add_tx_amount(message: types.Message, state: FSMContext):
    if message.text == "🔙 Назад":
        return await go_back(message, state)
    try:
        val = float(message.text.replace(',', '.'))
        await state.update_data(amount=val)
        await state.set_state(FinanceForm.description)
        await message.answer("✍️ Що купили (коментар):")
    except ValueError:
        await message.answer("🔢 Будь ласка, введи число.")


@dp.message(StateFilter(FinanceForm.description))
async def add_tx_save(message: types.Message, state: FSMContext):
    if message.text == "🔙 Назад":
        return await go_back(message, state)
    data = await state.get_data()
    await bot.send_chat_action(message.chat.id, ChatAction.TYPING)
    date_now = datetime.now().strftime("%Y-%m-%d")

    res = await api_client.add_transaction(data['family_id'], data['user_id'], data['category_id'], data['amount'],
                                           data['t_type'], message.text, "Готівка", None, date_now)
    if res:
        await message.answer(f"✅ Записано: {data['amount']} ₴ ({data['category_name']})", reply_markup=main_kb())
    else:
        await message.answer("❌ Помилка збереження.", reply_markup=main_kb())
    await state.clear()
