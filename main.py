import asyncio
import logging
from datetime import datetime
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove

from config import BOT_TOKEN, USERS, EXPENSE_CATEGORIES, INCOME_CATEGORIES
from gs_manager import GoogleSheetManager

# Логування
logging.basicConfig(level=logging.INFO)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
gs = GoogleSheetManager()


# --- СТАНИ ---
class FinanceForm(StatesGroup):
    category = State()
    amount = State()
    description = State()

    quick_amount = State()
    quick_desc = State()


# --- КЛАВІАТУРИ ---
def main_kb():
    kb = [
        [KeyboardButton(text="⚡️ Швидка витрата")],
        [KeyboardButton(text="💸 Витрата (Детально)"), KeyboardButton(text="💰 Дохід")]
    ]
    # is_persistent=True тримає меню завжди відкритим, input_field_placeholder - підказка
    return ReplyKeyboardMarkup(
        keyboard=kb,
        resize_keyboard=True,
        is_persistent=True,
        input_field_placeholder="Обери дію..."
    )


def categories_kb(is_expense=True):
    cats = EXPENSE_CATEGORIES if is_expense else INCOME_CATEGORIES
    kb = []
    row = []
    for c in cats:
        row.append(KeyboardButton(text=c))
        if len(row) == 2:
            kb.append(row)
            row = []
    if row: kb.append(row)
    kb.append([KeyboardButton(text="🔙 Назад")])
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True, is_persistent=True)


# --- START ---
@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()  # Очищаємо стан на випадок рестарту
    if message.from_user.id not in USERS:
        await message.answer("⛔️ Немає доступу.")
        return
    name = USERS[message.from_user.id]
    await message.answer(f"Привіт, {name}! 👋\nФінанси готові до запису.", reply_markup=main_kb())


# --- ГЛОБАЛЬНІ КНОПКИ (Працюють у будь-якому стані) ---

@dp.message(F.text == "🔙 Назад", StateFilter("*"))
async def go_back(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("Головне меню", reply_markup=main_kb())


# ================= ШВИДКА ВИТРАТА =================

# StateFilter('*') означає: навіть якщо бот чекає число, а ти тицьнув кнопку - спрацює кнопка
@dp.message(F.text == "⚡️ Швидка витрата", StateFilter("*"))
async def quick_start(message: types.Message, state: FSMContext):
    if message.from_user.id not in USERS: return
    await state.clear()  # Скидаємо все, що було до цього
    await state.set_state(FinanceForm.quick_amount)
    await message.answer("Введи суму (швидка):", reply_markup=ReplyKeyboardRemove())


@dp.message(FinanceForm.quick_amount)
async def quick_amount_handler(message: types.Message, state: FSMContext):
    # Тут перевіряємо, чи не натиснув юзер кнопку меню, якої тут не має бути, але про всяк випадок
    if message.text in ["⚡️ Швидка витрата", "💰 Дохід", "💸 Витрата (Детально)"]:
        await message.answer("Спершу заверши введення або натисни /start для скидання.")
        return

    try:
        val = float(message.text.replace(',', '.'))
        await state.update_data(amount=val)
        await state.set_state(FinanceForm.quick_desc)
        await message.answer("На що витрачено? (Коротко):")
    except ValueError:
        await message.answer("🔢 Введи просто число (наприклад 50).")


@dp.message(FinanceForm.quick_desc)
async def quick_desc_handler(message: types.Message, state: FSMContext):
    desc = message.text
    data = await state.get_data()
    who = USERS[message.from_user.id]

    # ⬇️ ЗМІНЕНО: Категорія за замовчуванням
    category = "⏳ Очікує уточнення"

    msg = await message.answer("⏳ Записую...")

    success = gs.add_transaction(
        date=datetime.now().strftime("%d.%m.%Y"),
        category=category,
        amount=data['amount'],
        t_type="Витрати",  # ⬇️ ЗМІНЕНО: Було "Витрата", стало "Витрати"
        item_name=desc,
        note="Швидкий запис",
        who=who
    )

    if success:
        await msg.edit_text(
            f"✅ <b>-{data['amount']} грн</b> ({desc})\n"
            f"Категорія: {category}",
            parse_mode="HTML"
        )
        await message.answer("Готово!", reply_markup=main_kb())
    else:
        await msg.edit_text("❌ Помилка запису в таблицю.")
    await state.clear()


# ================= ДЕТАЛЬНИЙ ЗАПИС =================

@dp.message(F.text.in_({"💸 Витрата (Детально)", "💰 Дохід"}), StateFilter("*"))
async def full_start(message: types.Message, state: FSMContext):
    if message.from_user.id not in USERS: return
    await state.clear()  # Скидаємо попередні стани

    is_expense = "Витрата" in message.text
    # ⬇️ ЗМІНЕНО: Правильні назви типів як у CSV
    t_type = "Витрати" if is_expense else "Поповнення"

    await state.update_data(t_type=t_type)
    await state.set_state(FinanceForm.category)
    await message.answer("Обери категорію:", reply_markup=categories_kb(is_expense))


@dp.message(FinanceForm.category)
async def full_cat(message: types.Message, state: FSMContext):
    # Захист: якщо юзер вводить текст, якого немає в кнопках (окрім Назад)
    # Хоча тут можна дозволити і свої категорії, але поки строго по кнопках
    if message.text not in EXPENSE_CATEGORIES and message.text not in INCOME_CATEGORIES:
        await message.answer("⚠️ Будь ласка, обери категорію з меню або натисни '🔙 Назад'")
        return

    await state.update_data(category=message.text)
    await state.set_state(FinanceForm.amount)
    await message.answer("Сума:", reply_markup=ReplyKeyboardRemove())


@dp.message(FinanceForm.amount)
async def full_amount(message: types.Message, state: FSMContext):
    try:
        val = float(message.text.replace(',', '.'))
        await state.update_data(amount=val)
        await state.set_state(FinanceForm.description)
        await message.answer("Опис (що саме?):")
    except ValueError:
        await message.answer("🔢 Потрібне число.")


@dp.message(FinanceForm.description)
async def full_desc(message: types.Message, state: FSMContext):
    desc = message.text
    data = await state.get_data()
    who = USERS[message.from_user.id]

    msg = await message.answer("⏳ ...")

    success = gs.add_transaction(
        date=datetime.now().strftime("%d.%m.%Y"),
        category=data['category'],
        amount=data['amount'],
        t_type=data['t_type'],
        item_name=desc,
        note="Telegram",
        who=who
    )

    emoji = "📉" if data['t_type'] == "Витрати" else "📈"

    if success:
        await msg.edit_text(
            f"{emoji} {data['category']}\n"
            f"💵 <b>{data['amount']} грн</b>\n"
            f"🛒 {desc}\n"
            f"👤 {who}",
            parse_mode="HTML"
        )
    else:
        await msg.edit_text("❌ Помилка таблиці.")

    await state.clear()
    await message.answer("Головне меню", reply_markup=main_kb())


async def main():
    # Видаляємо вебхуки, якщо були, і запускаємо
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())