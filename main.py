import asyncio
import logging
import sys
from datetime import datetime
from aiogram import Bot, Dispatcher, F, types
from aiogram.enums import ChatAction  # <--- НОВИЙ ІМПОРТ
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove, BufferedInputFile
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from config import BOT_TOKEN, USERS, EXPENSE_CATEGORIES, INCOME_CATEGORIES
from gs_manager import GoogleSheetManager
import visuals

logging.basicConfig(level=logging.INFO)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
gs = GoogleSheetManager()
scheduler = AsyncIOScheduler()


# --- СТАНИ ---
class FinanceForm(StatesGroup):
    category = State()
    amount = State()
    description = State()
    quick_amount = State()
    quick_desc = State()
    edit_limit_cat = State()
    edit_limit_amount = State()


# --- КЛАВІАТУРИ ---
def main_kb():
    kb = [
        [KeyboardButton(text="⚡️ Швидка витрата")],
        [KeyboardButton(text="💸 Витрата (Детально)"), KeyboardButton(text="💰 Дохід")],
        [KeyboardButton(text="📊 Статистика"), KeyboardButton(text="📂 Інше")]
    ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True, is_persistent=True)


def other_kb():
    kb = [
        [KeyboardButton(text="🍰 Діаграма витрат"), KeyboardButton(text="📉 Звіт (Тиждень)")],
        [KeyboardButton(text="↩️ Скасувати"), KeyboardButton(text="🔔 Перевірити ліміти")],
        [KeyboardButton(text="⚙️ Змінити ліміт"), KeyboardButton(text="🔙 Назад")]
    ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)


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


def limits_edit_kb():
    kb = []
    row = []
    for c in EXPENSE_CATEGORIES:
        row.append(KeyboardButton(text=c))
        if len(row) == 2:
            kb.append(row)
            row = []
    if row: kb.append(row)
    kb.append([KeyboardButton(text="🔙 Назад")])
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)


# --- START & MENU ---
@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    if message.from_user.id not in USERS:
        await message.answer("⛔️ Немає доступу.")
        return
    name = USERS[message.from_user.id]
    await message.answer(f"Привіт, {name}! 👋", reply_markup=main_kb())


@dp.message(F.text == "🔙 Назад", StateFilter("*"))
async def go_back(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("Головне меню", reply_markup=main_kb())


@dp.message(F.text == "📂 Інше")
async def show_other_menu(message: types.Message):
    await message.answer("Додаткові функції:", reply_markup=other_kb())


@dp.message(Command("restart"))
async def cmd_restart(message: types.Message):
    if message.from_user.id not in USERS: return
    await message.answer("🔄 Rebooting...")
    sys.exit(0)


# ================= ФУНКЦІОНАЛ "ІНШЕ" =================

@dp.message(F.text == "🍰 Діаграма витрат")
async def send_chart(message: types.Message):
    if message.from_user.id not in USERS: return
    # Показуємо статус "Відправляє фото"
    await bot.send_chat_action(message.chat.id, ChatAction.UPLOAD_PHOTO)

    stats = gs.get_month_stats()
    if not stats or not stats['categories_dict']:
        await message.answer("❌ Мало даних для діаграми.")
        return
    img_buf = visuals.generate_pie_chart(stats['categories_dict'], title=f"Витрати: {stats['month_name']}")
    if img_buf:
        photo = BufferedInputFile(img_buf.read(), filename="chart.png")
        await message.answer_photo(photo, caption=f"Витрати за {stats['month_name']}")
    else:
        await message.answer("❌ Помилка генерації.")


@dp.message(F.text == "📉 Звіт (Тиждень)")
async def report_week(message: types.Message):
    if message.from_user.id not in USERS: return
    # Показуємо статус "Друкує"
    await bot.send_chat_action(message.chat.id, ChatAction.TYPING)

    stats = gs.get_week_stats()
    if not stats:
        await message.answer("❌ Немає даних за тиждень.")
        return
    text = (
        f"📅 <b>Тижневий звіт</b>\n"
        f"➖➖➖➖➖➖➖➖➖➖\n"
        f"📉 Витрати: {stats['expense']:,.0f} грн\n"
        f"📈 Дохід: {stats['income']:,.0f} грн\n"
        f"➖➖➖➖➖➖➖➖➖➖\n"
        f"🏆 <b>Топ категорій:</b>\n"
    )
    for cat, amount in stats['top_cats']:
        text += f"▫️ {cat}: {amount:,.0f} грн\n"
    await message.answer(text, parse_mode="HTML")


@dp.message(F.text == "🔔 Перевірити ліміти")
async def check_limits_manual(message: types.Message):
    await bot.send_chat_action(message.chat.id, ChatAction.TYPING)
    limits = gs.get_budget_limits()
    stats = gs.get_month_stats()
    if not limits:
        await message.answer("🤷‍♂️ Аркуш 'Планування' порожній.")
        return
    report = "👮‍♂️ <b>Бюджет на місяць:</b>\n\n"
    cats_spent = stats['categories_dict'] if stats else {}
    for cat, limit in limits.items():
        spent = cats_spent.get(cat, 0)
        percent = (spent / limit) * 100 if limit > 0 else 0
        if percent < 50:
            icon = "🟢"
        elif percent < 85:
            icon = "🟡"
        else:
            icon = "🔴"
        report += f"{icon} <b>{cat}</b>: {spent:.0f} / {limit:.0f} ({percent:.0f}%)\n"
    await message.answer(report, parse_mode="HTML")


@dp.message(F.text == "⚙️ Змінити ліміт")
async def edit_limit_start(message: types.Message, state: FSMContext):
    if message.from_user.id not in USERS: return
    await state.set_state(FinanceForm.edit_limit_cat)
    await message.answer("Обери категорію для бюджету:", reply_markup=limits_edit_kb())


@dp.message(FinanceForm.edit_limit_cat)
async def edit_limit_cat_handler(message: types.Message, state: FSMContext):
    if message.text == "🔙 Назад":
        await state.clear()
        await message.answer("Скасовано.", reply_markup=other_kb())
        return
    await state.update_data(category=message.text)
    await state.set_state(FinanceForm.edit_limit_amount)
    await message.answer(f"Введи місячний ліміт для <b>{message.text}</b> (число):", parse_mode="HTML",
                         reply_markup=ReplyKeyboardRemove())


@dp.message(FinanceForm.edit_limit_amount)
async def edit_limit_save(message: types.Message, state: FSMContext):
    try:
        val = float(message.text.replace(',', '.'))
        data = await state.get_data()
        category = data['category']

        await bot.send_chat_action(message.chat.id, ChatAction.TYPING)

        success = gs.update_budget_limit(category, val)
        if success:
            await message.answer(f"✅ Ліміт для <b>{category}</b> встановлено: {val:.0f} грн", parse_mode="HTML",
                                 reply_markup=other_kb())
        else:
            await message.answer("❌ Помилка запису в таблицю.", reply_markup=other_kb())
    except ValueError:
        await message.answer("🔢 Введи коректне число.")
        return
    await state.clear()


@dp.message(F.text == "↩️ Скасувати")
async def undo_last(message: types.Message):
    if message.from_user.id not in USERS: return
    await bot.send_chat_action(message.chat.id, ChatAction.TYPING)
    result = gs.undo_last_transaction()
    if result:
        await message.answer(f"🗑 Видалено: {result['amount']} грн ({result['desc']})")
    else:
        await message.answer("❌ Помилка.")


@dp.message(F.text == "📊 Статистика")
async def show_stats(message: types.Message):
    # Показуємо статус "Друкує"
    await bot.send_chat_action(message.chat.id, ChatAction.TYPING)

    stats = gs.get_month_stats()
    if not stats:
        await message.answer("❌ Помилка.")
        return
    text = (
        f"📅 <b>{stats['month_name']}</b>\n"
        f"📉 Витрати: {stats['expense']:,.0f} грн\n"
        f"📈 Дохід: {stats['income']:,.0f} грн\n"
        f"💰 Баланс: {stats['balance']:,.0f} грн\n"
        f"➖➖➖➖➖\n"
    )
    for cat, amount in stats['top_cats']:
        text += f"▫️ {cat}: {amount:,.0f}\n"
    await message.answer(text, parse_mode="HTML")


async def evening_reminder():
    for user_id in USERS:
        try:
            await bot.send_message(user_id, "🌙 Привіт! Якщо були витрати, не забудь записати ✍️")
        except:
            pass


# ================= ВИТРАТИ (ЛОГІКА) =================
@dp.message(F.text == "⚡️ Швидка витрата", StateFilter("*"))
async def quick_start(message: types.Message, state: FSMContext):
    await state.clear()
    await state.set_state(FinanceForm.quick_amount)
    await message.answer("Сума (швидка):", reply_markup=ReplyKeyboardRemove())


@dp.message(FinanceForm.quick_amount)
async def quick_handler(message: types.Message, state: FSMContext):
    try:
        val = float(message.text.replace(',', '.'))
        await state.update_data(amount=val)
        await state.set_state(FinanceForm.quick_desc)
        await message.answer("На що?")
    except ValueError:
        await message.answer("Число!")


@dp.message(FinanceForm.quick_desc)
async def quick_save(message: types.Message, state: FSMContext):
    desc = message.text
    data = await state.get_data()
    category = "⏳ Очікує уточнення"
    who = USERS[message.from_user.id]

    await bot.send_chat_action(message.chat.id, ChatAction.TYPING)

    gs.add_transaction(datetime.now().strftime("%d.%m.%Y"), category, data['amount'], "Витрати", desc, "Швидкий", who)
    await message.answer(f"✅ -{data['amount']} грн", reply_markup=main_kb())
    await state.clear()


@dp.message(F.text.in_({"💸 Витрата (Детально)", "💰 Дохід"}), StateFilter("*"))
async def full_start(message: types.Message, state: FSMContext):
    is_expense = "Витрата" in message.text
    t_type = "Витрати" if is_expense else "Поповнення"
    await state.update_data(t_type=t_type)
    await state.set_state(FinanceForm.category)
    await message.answer("Категорія:", reply_markup=categories_kb(is_expense))


@dp.message(FinanceForm.category)
async def full_cat(message: types.Message, state: FSMContext):
    if message.text not in EXPENSE_CATEGORIES and message.text not in INCOME_CATEGORIES:
        return
    await state.update_data(category=message.text)
    await state.set_state(FinanceForm.amount)
    await message.answer("Сума:", reply_markup=ReplyKeyboardRemove())


@dp.message(FinanceForm.amount)
async def full_amt(message: types.Message, state: FSMContext):
    try:
        val = float(message.text.replace(',', '.'))
        await state.update_data(amount=val)
        await state.set_state(FinanceForm.description)
        await message.answer("Опис:")
    except:
        await message.answer("Число!")


@dp.message(FinanceForm.description)
async def full_save(message: types.Message, state: FSMContext):
    data = await state.get_data()
    who = USERS[message.from_user.id]

    # Показуємо, що бот працює
    await bot.send_chat_action(message.chat.id, ChatAction.TYPING)

    # 1. Записуємо в таблицю
    gs.add_transaction(
        datetime.now().strftime("%d.%m.%Y"), data['category'], data['amount'],
        data['t_type'], message.text, "Bot", who
    )

    # 2. ПЕРЕВІРКА ЛІМІТУ
    if data['t_type'] == "Витрати":
        limits = gs.get_budget_limits()
        if data['category'] in limits:
            limit_val = limits[data['category']]
            stats = gs.get_month_stats()
            spent = stats['categories_dict'].get(data['category'], 0)

            if spent > limit_val:
                await message.answer(f"⚠️ <b>УВАГА!</b> Переліміт по категорії {data['category']}!\n"
                                     f"Витрачено: {spent:.0f} / {limit_val:.0f} грн", parse_mode="HTML")
            elif spent > limit_val * 0.8:
                await message.answer(f"⚠️ Обережно, вичерпано 80% ліміту ({spent:.0f}/{limit_val:.0f})",
                                     parse_mode="HTML")

    await message.answer("✅ Записано!", reply_markup=main_kb())
    await state.clear()


async def main():
    scheduler.add_job(evening_reminder, 'cron', hour=21, minute=0)
    scheduler.start()
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())