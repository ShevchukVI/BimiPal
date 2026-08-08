# handlers/scratchpad.py
# Швидка нотатка в Чернетку: повідомлення з префіксом "📝" автоматично
# потрапляє в Scratchpad сім'ї (напр. «📝 М'ясо 500 грн»).
# ЗАРЕЄСТРОВАНО ОСТАННІМ у handlers/__init__.py — щоб FSM-хендлери
# (expenses, monobank) мали пріоритет під час активних станів.
from aiogram import F, types
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext

from services.api_client import api_client
from handlers import dp
from keyboards.reply import main_kb


@dp.message(F.text.startswith("📝"), StateFilter("*"))
async def quick_note(message: types.Message, state: FSMContext):
    content = message.text.lstrip("📝").strip()
    if not content:
        return await message.answer("✍️ Напиши текст після 📝, напр.: «📝 М'ясо 500 грн»")

    user_info = await api_client.get_me(message.from_user.id)
    if not user_info:
        return await message.answer("❌ Акаунт не знайдено. Введіть /start")

    await state.clear()
    if await api_client.create_note(user_info["current_active_family_id"], content):
        await message.answer("✅ Додано в чернетку", reply_markup=main_kb())
    else:
        await message.answer("❌ Помилка збереження нотатки.")
