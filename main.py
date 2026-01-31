import asyncio
import logging
import sys
from datetime import datetime
from aiogram import Bot, Dispatcher, F, types
from aiogram.enums import ChatAction
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove, BufferedInputFile
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from config import BOT_TOKEN, USERS
from gs_manager import GoogleSheetManager
import visuals

logging.basicConfig(level=logging.INFO)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
gs = GoogleSheetManager()
scheduler = AsyncIOScheduler()

# --- ГЛОБАЛЬНІ ЗМІННІ ДЛЯ КАТЕГОРІЙ ---
EXPENSE_CATS = []
INCOME_CATS = []


# --- СТАНИ (FSM) ---
class FinanceForm(StatesGroup):
    category = State()
    amount = State()
    description = State()
    quick_amount = State()
    quick_desc = State()
    edit_limit_cat = State()
    edit_limit_amount = State()


class CurrencyForm(StatesGroup):
    operation = State()  # Купив / Продав / Витратив / Отримав
    amount_usd = State()
    rate = State()
    description = State()


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
        [KeyboardButton(text="🇺🇸 Валюта"), KeyboardButton(text="🍰 Діаграма")],
        [KeyboardButton(text="📉 Звіт (Тиждень)"), KeyboardButton(text="🔔 Перевірити ліміти")],
        [KeyboardButton(text="⚙️ Змінити ліміт"), KeyboardButton(text="🔙 Назад")]
    ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)


def currency_kb():
    kb = [
        [KeyboardButton(text="📥 Купив $"), KeyboardButton(text="📤 Продав $")],
        [KeyboardButton(text="💰 Отримав $"), KeyboardButton(text="🛒 Витратив $")],  # <--- Нова кнопка тут
        [KeyboardButton(text="🔙 Назад")]
    ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)


def categories_kb(is_expense=True):
    cats = EXPENSE_CATS if is_expense else INCOME_CATS
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
    for c in EXPENSE_CATS:
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
    if message.from_user.id not in USERS: return
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
    await message.answer("🔄 Оновлюю налаштування і перезапускаюсь...")
    sys.exit(0)


# ================= ВАЛЮТА (ОНОВЛЕНО) =================
@dp.message(F.text == "🇺🇸 Валюта")
async def currency_menu(message: types.Message):
    await message.answer("💵 Операції з доларами:", reply_markup=currency_kb())


@dp.message(F.text.in_({"📥 Купив $", "📤 Продав $", "🛒 Витратив $", "💰 Отримав $"}))
async def curr_start(message: types.Message, state: FSMContext):
    op = message.text
    await state.update_data(op=op)
    await state.set_state(CurrencyForm.amount_usd)
    await message.answer("Скільки доларів? ($):", reply_markup=ReplyKeyboardRemove())


@dp.message(CurrencyForm.amount_usd)
async def curr_amount(message: types.Message, state: FSMContext):
    try:
        val = float(message.text.replace(',', '.'))
        await state.update_data(amount_usd=val)

        data = await state.get_data()
        # Для "Витратив" і "Отримав" курс не питаємо (він не впливає на грн)
        if data['op'] in ["🛒 Витратив $", "💰 Отримав $"]:
            await state.update_data(rate=0.0)
            await state.set_state(CurrencyForm.description)
            text_prompt = "На що витратив?" if data['op'] == "🛒 Витратив $" else "Від кого/за що отримав?"
            await message.answer(text_prompt)
        else:
            await state.set_state(CurrencyForm.rate)
            await message.answer("Який курс? (грн/$):")
    except:
        await message.answer("Число!")


@dp.message(CurrencyForm.rate)
async def curr_rate(message: types.Message, state: FSMContext):
    try:
        val = float(message.text.replace(',', '.'))
        await state.update_data(rate=val)
        await state.set_state(CurrencyForm.description)
        await message.answer("Коментар (необов'язково):")
    except:
        await message.answer("Число!")


@dp.message(CurrencyForm.description)
async def curr_save(message: types.Message, state: FSMContext):
    data = await state.get_data()
    usd = data['amount_usd']
    rate = data['rate']
    op = data['op']
    note = message.text
    who = USERS[message.from_user.id]
    date = datetime.now().strftime("%d.%m.%Y")

    uah_val = usd * rate

    await bot.send_chat_action(message.chat.id, ChatAction.TYPING)

    # 1. Визначаємо знак для сейфа (+ або -)
    usd_sign = usd if op in ["📥 Купив $", "💰 Отримав $"] else -usd

    # 2. Запис в аркуш "Валюта"
    gs.add_currency_transaction(date, op, usd_sign, rate, uah_val, note)

    # 3. Дублювання в основну таблицю (для історії руху гривні)
    msg = ""
    if op == "📥 Купив $":
        gs.add_transaction(date, "💵 Купівля валюти", uah_val, "Витрати", f"{usd}$ по {rate}", "Auto-Currency", who)
        msg = f"✅ Купив {usd}$ за {uah_val:.0f} грн.\nДодано в сейф."

    elif op == "📤 Продав $":
        gs.add_transaction(date, "🔁 Обмін валют", uah_val, "Дохід", f"Продав {usd}$ по {rate}", "Auto-Currency", who)
        msg = f"✅ Продав {usd}$ за {uah_val:.0f} грн.\nГривні зараховано."

    elif op == "💰 Отримав $":
        # Записуємо як дохід з 0 грн, щоб було в історії
        gs.add_transaction(date, "💵 Валютний дохід", 0, "Дохід", f"Отримав {usd}$ ({note})", "Auto-Currency", who)
        msg = f"✅ Отримав {usd}$ у сейф.\n(Гривня не змінилась)"

    else:  # Витратив $
        msg = f"✅ Витратив {usd}$ з сейфа.\n({note})"

    await message.answer(msg, reply_markup=main_kb())
    await state.clear()


# ================= СТАТИСТИКА =================
@dp.message(F.text == "📊 Статистика")
async def show_stats(message: types.Message):
    await bot.send_chat_action(message.chat.id, ChatAction.TYPING)
    stats = gs.get_month_stats()
    if not stats:
        await message.answer("❌ Помилка.")
        return
    text = (
        f"🏦 <b>Гаманець UAH:</b> {stats['total_wallet']:,.0f} грн\n"
        f"🇺🇸 <b>Гаманець USD:</b> {stats['usd_wallet']:,.0f} $\n"
        f"➖➖➖➖➖➖➖➖➖➖\n"
        f"📅 <b>{stats['month_name']} (Потік):</b>\n"
        f"📉 Витрати: {stats['expense']:,.0f} грн\n"
        f"📈 Дохід: {stats['income']:,.0f} грн\n"
        f"💰 Різниця: {stats['balance']:,.0f} грн\n"
        f"➖➖➖➖➖➖➖➖➖➖\n"
        f"🏆 <b>Топ категорій:</b>\n"
    )
    for cat, amount in stats['top_cats']:
        text += f"▫️ {cat}: {amount:,.0f} грн\n"
    await message.answer(text, parse_mode="HTML")


# ================= ЗВІТИ ТА ЛІМІТИ =================
@dp.message(F.text == "🍰 Діаграма")
async def send_chart(message: types.Message):
    if message.from_user.id not in USERS: return
    await bot.send_chat_action(message.chat.id, ChatAction.UPLOAD_PHOTO)
    stats = gs.get_month_stats()
    if not stats or not stats['categories_dict']:
        await message.answer("❌ Мало даних.")
        return
    img_buf = visuals.generate_pie_chart(stats['categories_dict'], title=f"Витрати: {stats['month_name']}")
    if img_buf:
        photo = BufferedInputFile(img_buf.read(), filename="chart.png")
        await message.answer_photo(photo, caption=f"Витрати за {stats['month_name']}")
    else:
        await message.answer("❌ Помилка.")


@dp.message(F.text == "📉 Звіт (Тиждень)")
async def report_week(message: types.Message):
    await bot.send_chat_action(message.chat.id, ChatAction.TYPING)
    stats = gs.get_week_stats()
    if not stats:
        await message.answer("❌ Немає даних.")
        return
    text = (
        f"📅 <b>Тижневий звіт</b>\n➖➖➖➖➖➖\n📉 Витрати: {stats['expense']:,.0f} грн\n📈 Дохід: {stats['income']:,.0f} грн\n➖➖➖➖➖➖\n🏆 <b>Топ:</b>\n")
    for cat, amount in stats['top_cats']: text += f"▫️ {cat}: {amount:,.0f} грн\n"
    await message.answer(text, parse_mode="HTML")


@dp.message(F.text == "🔔 Перевірити ліміти")
async def check_limits_manual(message: types.Message):
    await bot.send_chat_action(message.chat.id, ChatAction.TYPING)
    limits = gs.get_budget_limits()
    stats = gs.get_month_stats()
    if not limits:
        await message.answer("🤷‍♂️ План пустий.")
        return
    report = "👮‍♂️ <b>Бюджет на місяць:</b>\n\n"
    cats_spent = stats['categories_dict'] if stats else {}
    for cat, limit in limits.items():
        spent = cats_spent.get(cat, 0)
        percent = (spent / limit) * 100 if limit > 0 else 0
        icon = "🟢" if percent < 50 else "🟡" if percent < 85 else "🔴"
        report += f"{icon} <b>{cat}</b>: {spent:.0f} / {limit:.0f} ({percent:.0f}%)\n"
    await message.answer(report, parse_mode="HTML")


@dp.message(F.text == "⚙️ Змінити ліміт")
async def edit_limit_start(message: types.Message, state: FSMContext):
    await state.set_state(FinanceForm.edit_limit_cat)
    await message.answer("Обери категорію:", reply_markup=limits_edit_kb())


@dp.message(FinanceForm.edit_limit_cat)
async def edit_limit_cat_h(message: types.Message, state: FSMContext):
    if message.text == "🔙 Назад":
        await state.clear()
        await message.answer("Скасовано.", reply_markup=other_kb())
        return
    await state.update_data(category=message.text)
    await state.set_state(FinanceForm.edit_limit_amount)
    await message.answer("Новий ліміт:", reply_markup=ReplyKeyboardRemove())


@dp.message(FinanceForm.edit_limit_amount)
async def edit_limit_save(message: types.Message, state: FSMContext):
    try:
        val = float(message.text.replace(',', '.'))
        data = await state.get_data()
        await bot.send_chat_action(message.chat.id, ChatAction.TYPING)
        if gs.update_budget_limit(data['category'], val):
            await message.answer(f"✅ Ліміт {data['category']}: {val:.0f} грн", reply_markup=other_kb())
        else:
            await message.answer("❌ Помилка.", reply_markup=other_kb())
    except:
        await message.answer("Число!")
    await state.clear()


@dp.message(F.text == "↩️ Скасувати")
async def undo_last(message: types.Message):
    await bot.send_chat_action(message.chat.id, ChatAction.TYPING)
    res = gs.undo_last_transaction()
    if res:
        await message.answer(f"🗑 Видалено: {res['amount']} грн")
    else:
        await message.answer("❌ Помилка.")


# ================= СТАНДАРТНІ ОПЕРАЦІЇ =================
@dp.message(F.text == "⚡️ Швидка витрата")
async def quick_start(message: types.Message, state: FSMContext):
    await state.set_state(FinanceForm.quick_amount)
    await message.answer("Сума:", reply_markup=ReplyKeyboardRemove())


@dp.message(FinanceForm.quick_amount)
async def quick_h(message: types.Message, state: FSMContext):
    try:
        val = float(message.text.replace(',', '.'))
        await state.update_data(amount=val)
        await state.set_state(FinanceForm.quick_desc)
        await message.answer("На що?")
    except:
        await message.answer("Число!")


@dp.message(FinanceForm.quick_desc)
async def quick_s(message: types.Message, state: FSMContext):
    desc = message.text
    data = await state.get_data()
    who = USERS[message.from_user.id]
    await bot.send_chat_action(message.chat.id, ChatAction.TYPING)
    gs.add_transaction(datetime.now().strftime("%d.%m.%Y"), "⏳ Очікує уточнення", data['amount'], "Витрати", desc,
                       "Швидкий", who)
    await message.answer(f"✅ -{data['amount']} грн", reply_markup=main_kb())
    await state.clear()


@dp.message(F.text.in_({"💸 Витрата (Детально)", "💰 Дохід"}))
async def full_start(message: types.Message, state: FSMContext):
    is_exp = "Витрата" in message.text
    t_type = "Витрати" if is_exp else "Поповнення"
    await state.update_data(t_type=t_type)
    await state.set_state(FinanceForm.category)
    await message.answer("Категорія:", reply_markup=categories_kb(is_exp))


@dp.message(FinanceForm.category)
async def full_cat(message: types.Message, state: FSMContext):
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
    await bot.send_chat_action(message.chat.id, ChatAction.TYPING)
    gs.add_transaction(datetime.now().strftime("%d.%m.%Y"), data['category'], data['amount'], data['t_type'],
                       message.text, "Bot", who)
    if data['t_type'] == "Витрати":
        limits = gs.get_budget_limits()
        if data['category'] in limits:
            limit = limits[data['category']]
            stats = gs.get_month_stats()
            spent = stats['categories_dict'].get(data['category'], 0)
            if spent > limit: await message.answer(f"⚠️ Переліміт! {spent:.0f}/{limit:.0f}", parse_mode="HTML")
    await message.answer("✅ Записано!", reply_markup=main_kb())
    await state.clear()


async def evening_reminder():
    for uid in USERS:
        try:
            await bot.send_message(uid, "🌙 Не забудь записати витрати!")
        except:
            pass


async def main():
    global EXPENSE_CATS, INCOME_CATS
    print("📥 Loading categories...")
    EXPENSE_CATS, INCOME_CATS = gs.get_categories()
    print(f"✅ Loaded {len(EXPENSE_CATS)} expense cats.")
    scheduler.add_job(evening_reminder, 'cron', hour=21, minute=0)
    scheduler.start()
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())