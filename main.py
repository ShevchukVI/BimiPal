import asyncio
import logging
import sys
import html
import subprocess
from datetime import datetime
from functools import partial

import aiohttp
from aiohttp import web

from aiogram import Bot, Dispatcher, F, types
from aiogram.enums import ChatAction
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove,
    BufferedInputFile, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# Твої модулі
import reports
import visuals
from config import BOT_TOKEN, USERS, MONO_TOKENS, WEBHOOK_URL
from gs_manager import GoogleSheetManager

# --- НАЛАШТУВАННЯ ---
logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
gs = GoogleSheetManager()
scheduler = AsyncIOScheduler()

# Глобальний кеш
CACHE = {
    "expense_cats": [],
    "income_cats": [],
    "pending_reminders": {}
}

MONO_ACCOUNT_TO_USER = {}  # Карта: id_картки -> id_користувача_в_телеграм


# --- СТАНИ (FSM) ---
class FinanceForm(StatesGroup):
    category = State()
    amount = State()
    description = State()
    edit_limit_cat = State()
    edit_limit_amount = State()

class QuickEditForm(StatesGroup):
    new_amount = State()

class CurrencyForm(StatesGroup):
    operation = State()
    amount_usd = State()
    rate = State()
    description = State()

class ReportForm(StatesGroup):
    year = State()
    month = State()

class TransferForm(StatesGroup):
    direction = State()
    amount = State()
    description = State()

class MonoCommentForm(StatesGroup):
    text = State()


# --- ДОПОМІЖНІ ФУНКЦІЇ (ОПТИМІЗАЦІЯ) ---
async def run_sync(func, *args, **kwargs):
    """Запускає блокуючі операції (Google Sheets) в окремому потоці."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, partial(func, *args, **kwargs))

def get_keyboard(items, row_width=2, is_persistent=True, back_btn=False):
    """Генератор клавіатур"""
    kb = []
    row = []
    for item in items:
        text = item if isinstance(item, str) else item.text
        row.append(KeyboardButton(text=text))
        if len(row) == row_width:
            kb.append(row)
            row = []
    if row: kb.append(row)
    if back_btn: kb.append([KeyboardButton(text="🔙 Назад")])
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True, is_persistent=is_persistent)


# --- КЛАВІАТУРИ ---
def main_kb():
    return get_keyboard([
        "⚡️ Швидкі витрати",
        "💸 Витрата (Детально)", "💰 Дохід",
        "📊 Статистика", "📂 Інше"
    ], row_width=2)

def quick_kb():
    return get_keyboard([
        "☕️ Кава (60)", "⚡️ Енергетик (45)", "🚇 Метро (8)",
        "🔙 Назад"
    ], row_width=2)

def other_kb():
    return get_keyboard([
        "📜 Історія", "💸 Переказ",
        "🇺🇸 Валюта", "📄 Архів звітів",
        "📉 Звіт (Тиждень)", "🍰 Діаграма",
        "🔔 Перевірити ліміти", "⚙️ Змінити ліміт"
    ], row_width=2, is_persistent=True, back_btn=True)

def currency_kb():
    return get_keyboard([
        "📥 Купив $", "📤 Продав $",
        "💰 Отримав $", "🛒 Витратив $"
    ], row_width=2, is_persistent=True, back_btn=True)

def categories_kb(is_expense=True):
    cats = CACHE["expense_cats"] if is_expense else CACHE["income_cats"]
    if not cats: return get_keyboard([], back_btn=True)
    return get_keyboard(cats, back_btn=True)

def limits_edit_kb():
    cats = CACHE["expense_cats"]
    if not cats: return get_keyboard([], back_btn=True)
    return get_keyboard(cats, back_btn=True)

def quick_edit_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✏️ Змінити суму", callback_data="qa_edit"),
            InlineKeyboardButton(text="🗑 Відмінити", callback_data="qa_cancel")
        ]
    ])

def generate_mono_keyboard(mono_id, user_id):
    """Клавіатура вибору категорії для Автопілота (безпечна для Телеграму)"""
    cats = CACHE.get("expense_cats", [])
    kb_rows = []
    row = []
    
    # Використовуємо індекс замість назви, щоб не пробити ліміт 64 байти
    for idx, cat in enumerate(cats[:8]):
        row.append(InlineKeyboardButton(text=cat, callback_data=f"mcat:{mono_id}:{idx}"))
        if len(row) == 2:
            kb_rows.append(row)
            row = []
    if row: kb_rows.append(row)
    
    # Додаємо кнопку переказу для партнера
    user_name = USERS.get(user_id, "")
    partner = "Аня" if user_name == "Вадим" else "Вадим"
    if user_name:
        kb_rows.append([InlineKeyboardButton(text=f"🔄 Це переказ для {partner}", callback_data=f"mtrn:{mono_id}")])
    
    # Кнопки "На потім" та "Стерти"
    kb_rows.append([
        InlineKeyboardButton(text="⏳ На потім", callback_data=f"mltr:{mono_id}"),
        InlineKeyboardButton(text="❌ Стерти", callback_data=f"mdel:{mono_id}")
    ])
    return InlineKeyboardMarkup(inline_keyboard=kb_rows)


# ================= МОНОБАНК: ВЕБ-СЕРВЕР ТА АПІ =================
async def setup_monobank():
    """Автоматично підключає Webhook і дізнається ID карток."""
    for user_name, token in MONO_TOKENS.items():
        if not token or len(token) < 10: continue
        
        user_id = next((uid for uid, uname in USERS.items() if uname == user_name), None)
        if not user_id: continue

        async with aiohttp.ClientSession() as session:
            headers = {"X-Token": token}
            # 1. Оновлюємо Webhook URL у банку
            try:
                async with session.post("https://api.monobank.ua/personal/webhook", headers=headers, json={"webHookUrl": WEBHOOK_URL}) as resp:
                    if resp.status == 200:
                        print(f"✅ Webhook активовано для: {user_name}")
                    else:
                        print(f"❌ Помилка Webhook ({user_name}): {await resp.text()}")
            except Exception as e:
                print(f"🔴 Помилка мережі Mono: {e}")

            # 2. Дізнаємось ID рахунків, щоб знати, чия це картка
            try:
                async with session.get("https://api.monobank.ua/personal/client-info", headers=headers) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        for acc in data.get("accounts", []):
                            MONO_ACCOUNT_TO_USER[acc["id"]] = user_id
                        print(f"✅ Знайдено {len(data.get('accounts', []))} рахунків для {user_name}")
            except Exception as e:
                print(f"🔴 Помилка отримання карток: {e}")


async def mono_webhook_get(request):
    """Монобанк відправляє сюди GET-запит, щоб перевірити, чи ми живі."""
    return web.Response(text="OK", status=200)


async def mono_webhook_post(request):
    """Сюди прилітають транзакції."""
    try:
        data = await request.json()
    except Exception:
        return web.Response(status=400)

    if data.get("type") == "StatementItem":
        acc_id = data["data"]["account"]
        statement = data["data"]["statementItem"]
        
        amount = statement.get("amount", 0) / 100.0  # З копійок у гривні
        desc = statement.get("description", "Без опису")
        
        # Додаємо коментар до опису, якщо він є
        comment = statement.get("comment")
        if comment:
            desc = f"{desc} ({comment})"
            
        mono_id = statement.get("id")
        user_id = MONO_ACCOUNT_TO_USER.get(acc_id)
        
        # Обробляємо ТІЛЬКИ витрати (amount < 0).
        if user_id and amount < 0:
            real_amount = abs(amount)
            date_now = datetime.now().strftime("%d.%m.%Y")
            who = USERS.get(user_id, "Unknown")
            note_with_id = f"mono_{mono_id}"
            
            # Записуємо в базу з категорією "Очікує"
            success = await run_sync(
                gs.add_transaction,
                date_now, "❓ Очікує", real_amount, "Витрати", desc, note_with_id, who
            )
            
            if success:
                text = f"💳 <b>Нова витрата:</b>\n💰 {real_amount:.2f} грн\n🛒 {desc}\n\n<i>Обери категорію:</i>"
                kb = generate_mono_keyboard(mono_id, user_id)
                try:
                    await bot.send_message(user_id, text, reply_markup=kb, parse_mode="HTML")
                except Exception as e:
                    print(f"🔴 Помилка відправки в ТГ: {e}")

    return web.Response(text="OK", status=200)


# ================= ХЕНДЛЕРИ КНОПОК МОНОБАНКУ =================

@dp.callback_query(F.data.startswith("mcat:"))
async def mono_categorize(call: types.CallbackQuery):
    _, mono_id, cat_idx = call.data.split(":", 2)
    
    try:
        cat = CACHE["expense_cats"][int(cat_idx)]
    except:
        return await call.message.edit_text("❌ Категорію не знайдено.")

    await call.message.edit_text(f"⏳ <i>Зберігаю в {cat}...</i>", parse_mode="HTML")
    
    success = await run_sync(gs.update_transaction_category_by_mono_id, f"mono_{mono_id}", cat)
    if success:
        orig_text = call.message.text.replace("Обери категорію:", "").strip()
        
        # Пропонуємо додати свій коментар
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✍️ Додати опис (коментар)", callback_data=f"mdsc:{mono_id}")],
            [InlineKeyboardButton(text="⏩ Готово (Пропустити)", callback_data="mdon")]
        ])
        await call.message.edit_text(f"{orig_text}\n\n✅ <b>Записано в:</b> {cat}\n\n<i>Бажаєш додати деталі покупки?</i>", reply_markup=kb, parse_mode="HTML")
    else:
        await call.message.edit_text("❌ Помилка оновлення таблиці.")


@dp.callback_query(F.data == "mdon")
async def mono_done(call: types.CallbackQuery):
    text = call.message.text.replace("Бажаєш додати деталі покупки?", "").strip()
    await call.message.edit_text(f"{text}\n✅ Готово.", parse_mode="HTML")


@dp.callback_query(F.data.startswith("mdsc:"))
async def mono_ask_desc(call: types.CallbackQuery, state: FSMContext):
    mono_id = call.data.split(":")[1]
    await state.update_data(mono_id=mono_id, msg_id=call.message.message_id, orig_text=call.message.text)
    await state.set_state(MonoCommentForm.text)
    await bot.send_message(call.message.chat.id, "✍️ Напиши свій коментар до цієї покупки текстовим повідомленням сюди:")
    await call.answer()


@dp.message(MonoCommentForm.text)
async def mono_save_desc(message: types.Message, state: FSMContext):
    data = await state.get_data()
    mono_id = data.get('mono_id')
    msg_id = data.get('msg_id')
    orig_text = data.get('orig_text', '')
    
    await bot.send_chat_action(message.chat.id, ChatAction.TYPING)
    
    success = await run_sync(gs.append_desc_by_mono_id, f"mono_{mono_id}", message.text)
    if success:
        await message.answer("✅ Твій коментар успішно додано!")
        
        # Оновлюємо старе повідомлення, щоб воно виглядало гарно
        clean_text = orig_text.replace("Бажаєш додати деталі покупки?", "").strip()
        try:
            await bot.edit_message_text(f"{clean_text}\n💬 <i>{message.text}</i>", chat_id=message.chat.id, message_id=msg_id, parse_mode="HTML")
        except:
            pass
    else:
        await message.answer("❌ Помилка збереження коментаря.")
        
    await state.clear()


@dp.callback_query(F.data.startswith("mtrn:"))
async def mono_transfer(call: types.CallbackQuery):
    _, mono_id = call.data.split(":", 1)
    user_name = USERS.get(call.from_user.id)
    partner = "Аня" if user_name == "Вадим" else "Вадим"
    
    await call.message.edit_text(f"⏳ <i>Оформлюю як переказ для {partner}...</i>", parse_mode="HTML")
    
    success = await run_sync(gs.convert_mono_to_transfer, f"mono_{mono_id}", user_name, partner)
    if success:
        orig_text = call.message.text.replace("Обери категорію:", "").strip()
        await call.message.edit_text(f"{orig_text}\n\n✅ <b>Оформлено як переказ:</b> {user_name} ➡️ {partner}", parse_mode="HTML")
    else:
        await call.message.edit_text("❌ Помилка запису переказу.")


@dp.callback_query(F.data.startswith("mltr:"))
async def mono_later(call: types.CallbackQuery):
    orig_text = call.message.text.replace("Обери категорію:", "").strip()
    await call.message.edit_text(f"{orig_text}\n\n⏳ <b>Відкладено на потім.</b>", parse_mode="HTML")


@dp.callback_query(F.data.startswith("mdel:"))
async def mono_delete_tx(call: types.CallbackQuery):
    _, mono_id = call.data.split(":", 1)
    await call.message.edit_text("⏳ <i>Стираю...</i>", parse_mode="HTML")
    
    success = await run_sync(gs.delete_transaction_by_mono_id, f"mono_{mono_id}")
    if success:
        await call.message.edit_text("🗑 Цю транзакцію стерто. Її немає в бюджеті.")
    else:
        await call.message.edit_text("❌ Помилка видалення.")


# ================= СТАНДАРТНІ КОМАНДИ БОТА =================
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

@dp.message(F.text == "📂 Інше", StateFilter("*"))
async def show_other_menu(message: types.Message):
    await message.answer("Інструменти:", reply_markup=other_kb())

@dp.message(Command("restart"))
async def cmd_restart(message: types.Message):
    if message.from_user.id not in USERS: return
    await message.answer("🔄 Перезапуск...")
    sys.exit(0)

@dp.message(Command("update"))
async def cmd_update(message: types.Message):
    if message.from_user.id not in USERS: return
    await message.answer("🔄 Завантажую оновлення з GitHub...")
    try:
        process = subprocess.Popen(["git", "pull", "origin", "main"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        out, err = process.communicate()
        await message.answer(f"✅ Результат оновлення:\n<pre>{html.escape(out)}</pre>\nЗастосовую зміни та перезапускаюсь...", parse_mode="HTML")
    except Exception as e:
        await message.answer(f"❌ Помилка оновлення: {e}")
    finally:
        sys.exit(0)


# ================= ЗАГАЛЬНА ЛОГІКА ВВОДУ ЧИСЕЛ =================
async def validate_amount(message: types.Message, state: FSMContext, next_state: State, data_key: str, next_text: str):
    """Універсальний валідатор чисел"""
    try:
        val = float(message.text.replace(',', '.'))
        await state.update_data({data_key: val})
        await state.set_state(next_state)
        await message.answer(next_text)
    except ValueError:
        await message.answer("🔢 Будь ласка, введи число (можна з комою).")


# ================= ВИТРАТИ / ДОХОДИ =================
@dp.message(F.text.in_({"💸 Витрата (Детально)", "💰 Дохід"}), StateFilter("*"))
async def full_start(message: types.Message, state: FSMContext):
    await state.clear()
    is_expense = "Витрата" in message.text
    t_type = "Витрати" if is_expense else "Поповнення"

    if not CACHE["expense_cats"]:
        exp, inc = await run_sync(gs.get_categories)
        CACHE["expense_cats"] = exp
        CACHE["income_cats"] = inc

    await state.update_data(t_type=t_type)
    await state.set_state(FinanceForm.category)
    await message.answer("Категорія:", reply_markup=categories_kb(is_expense))

@dp.message(FinanceForm.category)
async def full_cat(message: types.Message, state: FSMContext):
    await state.update_data(category=message.text)
    await state.set_state(FinanceForm.amount)
    await message.answer("Сума:", reply_markup=ReplyKeyboardRemove())

@dp.message(FinanceForm.amount)
async def full_amt(message: types.Message, state: FSMContext):
    await validate_amount(message, state, FinanceForm.description, "amount", "✍️ Опис / Коментар:")

@dp.message(FinanceForm.description)
async def full_save(message: types.Message, state: FSMContext):
    data = await state.get_data()
    who = USERS.get(message.from_user.id, "Unknown")

    await bot.send_chat_action(message.chat.id, ChatAction.TYPING)

    await run_sync(
        gs.add_transaction,
        datetime.now().strftime("%d.%m.%Y"),
        data['category'],
        data['amount'],
        data['t_type'],
        message.text,
        "Bot",
        who
    )

    alert = ""
    if data['t_type'] == "Витрати":
        limits = await run_sync(gs.get_budget_limits)
        if data['category'] in limits:
            limit = limits[data['category']]
            stats = await run_sync(gs.get_month_stats)
            spent = stats['categories_dict'].get(data['category'], 0)
            if spent > limit:
                alert = f"\n⚠️ <b>Переліміт!</b> {spent:.0f} / {limit:.0f}"

    await message.answer(f"✅ Записано: {data['amount']} грн ({data['category']}){alert}", reply_markup=main_kb(), parse_mode="HTML")
    await state.clear()


# ================= ШВИДКІ ВИТРАТИ (ПІДМЕНЮ) =================
@dp.message(F.text == "⚡️ Швидкі витрати")
async def quick_menu(message: types.Message):
    await message.answer("Обери швидку витрату:", reply_markup=quick_kb())

@dp.message(F.text.in_(["☕️ Кава (60)", "⚡️ Енергетик (45)", "🚇 Метро (8)"]))
async def handle_quick_action(message: types.Message):
    text = message.text
    if "Кава" in text:
        amount, cat, desc = 60, "☕ Щоденні дрібниці", "Кава (Швидкий запис)"
    elif "Енергетик" in text:
        amount, cat, desc = 45, "☕ Щоденні дрібниці", "Енергетик (Швидкий запис)"
    else:
        amount, cat, desc = 8, "🚆 Громад. транспорт", "Метро (Швидкий запис)"

    who = USERS.get(message.from_user.id, "Unknown")
    date_now = datetime.now().strftime("%d.%m.%Y")

    await bot.send_chat_action(message.chat.id, ChatAction.TYPING)
    res = await run_sync(gs.add_transaction, date_now, cat, amount, "Витрати", desc, "QuickAction", who)

    if res:
        await message.answer(
            f"✅ Швидко записано: <b>{amount} грн</b> ({cat})\n<i>Якщо сума інша — натисни кнопку нижче.</i>",
            parse_mode="HTML",
            reply_markup=quick_edit_kb()
        )
    else:
        await message.answer("❌ Помилка запису.", reply_markup=quick_kb())

@dp.callback_query(F.data == "qa_cancel")
async def qa_cancel(call: types.CallbackQuery):
    res = await run_sync(gs.undo_last_transaction)
    if res:
        await call.message.edit_text(f"❌ Запис на {res['amount']} скасовано.")
    else:
        await call.answer("Помилка видалення", show_alert=True)

@dp.callback_query(F.data == "qa_edit")
async def qa_edit_start(call: types.CallbackQuery, state: FSMContext):
    await state.set_state(QuickEditForm.new_amount)
    await call.message.edit_text("✏️ Введи реальну суму (тільки число):")

@dp.message(QuickEditForm.new_amount)
async def qa_edit_finish(message: types.Message, state: FSMContext):
    try:
        new_amt = float(message.text.replace(',', '.'))
    except ValueError:
        return await message.answer("❌ Це не число. Спробуй ще раз.")

    await bot.send_chat_action(message.chat.id, ChatAction.TYPING)
    res = await run_sync(gs.update_last_transaction_amount, new_amt)

    if res:
        await message.answer(f"✅ Суму успішно змінено на <b>{new_amt} грн</b>!", parse_mode="HTML")
    else:
        await message.answer("❌ Помилка оновлення таблиці.")
    await state.clear()


# ================= ПЕРЕКАЗИ =================
@dp.message(F.text == "💸 Переказ", StateFilter("*"))
async def transfer_start(message: types.Message, state: FSMContext):
    await state.clear()
    kb = [
        [KeyboardButton(text="🧔‍♂️ Вадим ➡️ 👩‍🦰 Аня")],
        [KeyboardButton(text="👩‍🦰 Аня ➡️ 🧔‍♂️ Вадим")],
        [KeyboardButton(text="🔙 Назад")]
    ]
    await state.set_state(TransferForm.direction)
    await message.answer("Хто і кому передає кошти?",
                         reply_markup=ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True))

@dp.message(TransferForm.direction)
async def transfer_dir(message: types.Message, state: FSMContext):
    if "Вадим ➡️" in message.text:
        await state.update_data(from_who="Вадим", to_who="Аня")
    elif "Аня ➡️" in message.text:
        await state.update_data(from_who="Аня", to_who="Вадим")
    else:
        return await message.answer("Обери кнопку.")

    await state.set_state(TransferForm.amount)
    await message.answer("Яку суму переказуємо?", reply_markup=ReplyKeyboardRemove())

@dp.message(TransferForm.amount)
async def transfer_amt(message: types.Message, state: FSMContext):
    await validate_amount(message, state, TransferForm.description, "amount", "Коментар (наприклад: 'На каву'):")

@dp.message(TransferForm.description)
async def transfer_save(message: types.Message, state: FSMContext):
    data = await state.get_data()
    note = message.text
    await bot.send_chat_action(message.chat.id, ChatAction.TYPING)

    res = await run_sync(gs.add_transfer, data['amount'], note, data['from_who'], data['to_who'])

    if res:
        await message.answer(
            f"✅ <b>Успішно!</b>\n"
            f"📤 {data['from_who']}: -{data['amount']} грн\n"
            f"📥 {data['to_who']}: +{data['amount']} грн\n"
            f"💬 <i>{note}</i>",
            reply_markup=main_kb(),
            parse_mode="HTML"
        )
    else:
        await message.answer("❌ Помилка запису.", reply_markup=main_kb())
    await state.clear()


# ================= ІСТОРІЯ (Pagination + Delete Confirm) =================
@dp.message(F.text == "📜 Історія", StateFilter("*"))
async def show_history(message: types.Message, state: FSMContext):
    await state.clear()
    await render_history(message, page=1)

async def render_history(message: types.Message, page=1, is_edit=False):
    await bot.send_chat_action(message.chat.id, ChatAction.TYPING)
    PAGE_SIZE = 5
    last_txs = await run_sync(gs.get_last_transactions, page, PAGE_SIZE)

    if not last_txs and page == 1:
        text = "📭 Історія порожня."
        if is_edit:
            await message.edit_text(text)
        else:
            await message.answer(text)
        return

    text = f"📜 <b>Історія (Стор. {page})</b>\n\n"
    buttons = []

    for tx in last_txs:
        safe_cat = html.escape(str(tx['category']))
        safe_desc = html.escape(str(tx['desc']))
        who_icon = "🧔‍♂️" if "Вадим" in str(tx['who']) else "👩‍🦰" if "Аня" in str(tx['who']) else "🤖"

        text += f"▫️ {tx['date']} | {safe_cat}: <b>{tx['amount']}</b> {who_icon}\n"
        if safe_desc: text += f"   <i>({safe_desc})</i>\n"

        buttons.append(
            InlineKeyboardButton(text=f"🗑 Вид. ({tx['amount']})", callback_data=f"ask_del:{tx['id']}:{page}"))
        text += "➖➖➖➖➖➖\n"

    nav_row = []
    if page > 1:
        nav_row.append(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"hist_page:{page - 1}"))
    if len(last_txs) == PAGE_SIZE:
        nav_row.append(InlineKeyboardButton(text="Вперед ➡️", callback_data=f"hist_page:{page + 1}"))

    kb_rows = [buttons[i:i + 2] for i in range(0, len(buttons), 2)]
    if nav_row: kb_rows.append(nav_row)
    kb_rows.append([InlineKeyboardButton(text="🔄 Оновити", callback_data=f"hist_page:{page}")])

    markup = InlineKeyboardMarkup(inline_keyboard=kb_rows)

    if is_edit:
        try: await message.edit_text(text, reply_markup=markup, parse_mode="HTML")
        except: pass
    else:
        await message.answer(text, reply_markup=markup, parse_mode="HTML")

@dp.callback_query(F.data.startswith("hist_page:"))
async def history_nav(callback: CallbackQuery):
    page = int(callback.data.split(":")[1])
    await render_history(callback.message, page=page, is_edit=True)
    await callback.answer()

@dp.callback_query(F.data.startswith("ask_del:"))
async def ask_delete(callback: CallbackQuery):
    _, tx_id, page = callback.data.split(":")

    text = "⚠️ <b>Ви справді хочете видалити цей запис?</b>\nЦе неможливо скасувати."
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Так", callback_data=f"do_del:{tx_id}:{page}"),
            InlineKeyboardButton(text="❌ Ні", callback_data=f"hist_page:{page}")
        ]
    ])
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")

@dp.callback_query(F.data.startswith("do_del:"))
async def perform_delete(callback: CallbackQuery):
    _, tx_id, page = callback.data.split(":")

    if await run_sync(gs.delete_transaction_by_row, int(tx_id)):
        await callback.answer("✅ Видалено")
        await render_history(callback.message, page=int(page), is_edit=True)
    else:
        await callback.answer("❌ Помилка видалення", show_alert=True)
        await render_history(callback.message, page=int(page), is_edit=True)


# ================= АРХІВ ЗВІТІВ =================
@dp.message(F.text == "📄 Архів звітів", StateFilter("*"))
async def report_start(message: types.Message, state: FSMContext):
    await state.clear()
    years_kb = [[KeyboardButton(text="2025"), KeyboardButton(text="2026")], [KeyboardButton(text="🔙 Назад")]]
    await state.set_state(ReportForm.year)
    await message.answer("Обери рік:", reply_markup=ReplyKeyboardMarkup(keyboard=years_kb, resize_keyboard=True))

@dp.message(ReportForm.year)
async def report_year(message: types.Message, state: FSMContext):
    if message.text == "🔙 Назад":
        await state.clear()
        return await message.answer("Меню", reply_markup=other_kb())
    try:
        await state.update_data(year=int(message.text))
        months_kb = [
            [KeyboardButton(text="Січень"), KeyboardButton(text="Лютий"), KeyboardButton(text="Березень")],
            [KeyboardButton(text="Квітень"), KeyboardButton(text="Травень"), KeyboardButton(text="Червень")],
            [KeyboardButton(text="Липень"), KeyboardButton(text="Серпень"), KeyboardButton(text="Вересень")],
            [KeyboardButton(text="Жовтень"), KeyboardButton(text="Листопад"), KeyboardButton(text="Грудень")],
            [KeyboardButton(text="🔙 Назад")]
        ]
        await state.set_state(ReportForm.month)
        await message.answer("Обери місяць:", reply_markup=ReplyKeyboardMarkup(keyboard=months_kb, resize_keyboard=True))
    except:
        await message.answer("Цифрами!")

@dp.message(ReportForm.month)
async def report_month(message: types.Message, state: FSMContext):
    if message.text == "🔙 Назад":
        await state.set_state(ReportForm.year)
        return await message.answer("Рік:")

    month_map = {"Січень": 1, "Лютий": 2, "Березень": 3, "Квітень": 4, "Травень": 5, "Червень": 6, "Липень": 7,
                 "Серпень": 8, "Вересень": 9, "Жовтень": 10, "Листопад": 11, "Грудень": 12}
    if message.text not in month_map:
        return await message.answer("Обери кнопку")

    data_state = await state.get_data()
    year = data_state['year']
    month = month_map[message.text]

    await message.answer(f"⏳ Звіт за {message.text} {year}...", reply_markup=other_kb())
    await bot.send_chat_action(message.chat.id, ChatAction.UPLOAD_DOCUMENT)

    data = await run_sync(gs.get_month_history, month, year)

    if not data:
        return await message.answer("❌ Немає даних")

    try:
        pdf = await run_sync(reports.generate_monthly_report, data, message.text, year)
        filename = f"Report_{message.text}_{year}.pdf"
        await message.answer_document(BufferedInputFile(pdf.read(), filename=filename),
                                      caption=f"📊 Звіт за <b>{message.text} {year}</b> готовий!", parse_mode="HTML")
    except Exception as e:
        await message.answer(f"❌ Помилка: {e}")

    await state.clear()


# ================= ВАЛЮТА =================
@dp.message(F.text == "🇺🇸 Валюта", StateFilter("*"))
async def curr_menu(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("Меню валюти:", reply_markup=currency_kb())

@dp.message(F.text.in_({"📥 Купив $", "📤 Продав $", "🛒 Витратив $", "💰 Отримав $"}), StateFilter("*"))
async def curr_start(message: types.Message, state: FSMContext):
    op = message.text
    await state.update_data(op=op)
    await state.set_state(CurrencyForm.amount_usd)
    await message.answer("Скільки доларів? ($):", reply_markup=ReplyKeyboardRemove())

@dp.message(CurrencyForm.amount_usd)
async def curr_amount(message: types.Message, state: FSMContext):
    await validate_amount(message, state, CurrencyForm.rate, "amount_usd", "Який курс? (грн/$):")

@dp.message(CurrencyForm.rate)
async def curr_rate(message: types.Message, state: FSMContext):
    await validate_amount(message, state, CurrencyForm.description, "rate", "Коментар (необов'язково):")

@dp.message(CurrencyForm.description)
async def curr_save(message: types.Message, state: FSMContext):
    data = await state.get_data()
    usd = data['amount_usd']
    rate = data['rate']
    op = data['op']
    note = message.text
    who = USERS.get(message.from_user.id, "Unknown")
    date = datetime.now().strftime("%d.%m.%Y")
    uah_val = usd * rate

    await bot.send_chat_action(message.chat.id, ChatAction.TYPING)

    usd_sign = usd if op in ["📥 Купив $", "💰 Отримав $"] else -usd
    await run_sync(gs.add_currency_transaction, date, op, usd_sign, rate, uah_val, note)

    msg = "✅ Операцію збережено."
    if op == "📥 Купив $":
        await run_sync(gs.add_transaction, date, "💵 Купівля валюти", uah_val, "Витрати", f"{usd}$ по {rate}", "Auto-Currency", who)
        msg = f"✅ Купив {usd}$ за {uah_val:.0f} грн.\nДодано в сейф."
    elif op == "📤 Продав $":
        await run_sync(gs.add_transaction, date, "🔁 Обмін валют", uah_val, "Поповнення", f"Продав {usd}$ по {rate}", "Auto-Currency", who)
        msg = f"✅ Продав {usd}$ за {uah_val:.0f} грн.\nГривні зараховано."

    await message.answer(msg, reply_markup=main_kb())
    await state.clear()


# ================= СТАТИСТИКА / ЛІМІТИ / ДІАГРАМИ =================
@dp.message(F.text == "📊 Статистика", StateFilter("*"))
async def show_stats(message: types.Message, state: FSMContext):
    await state.clear()
    await bot.send_chat_action(message.chat.id, ChatAction.TYPING)
    stats = await run_sync(gs.get_month_stats)
    if not stats: return await message.answer("❌ Помилка")

    text = (f"🧔‍♂️ <b>Вадим:</b> {stats['wallet_vadym']:,.0f}\n"
            f"👩‍🦰 <b>Аня:</b> {stats['wallet_anya']:,.0f}\n"
            f"🏦 <b>Разом:</b> {stats['total_wallet']:,.0f} грн\n"
            f"🇺🇸 <b>Сейф:</b> {stats['usd_wallet']:,.0f} $\n"
            f"➖➖➖➖➖➖\n📅 <b>{stats['month_name']}</b>:\n"
            f"📉 Витрати: {stats['expense']:,.0f}\n"
            f"📈 Дохід: {stats['income']:,.0f}\n"
            f"💰 Баланс: {stats['balance']:,.0f}\n"
            f"➖➖➖➖➖➖\n🏆 <b>Топ:</b>\n")
    for cat, amt in stats['top_cats']: text += f"▫️ {cat}: {amt:,.0f}\n"
    await message.answer(text, parse_mode="HTML")

@dp.message(F.text == "🍰 Діаграма", StateFilter("*"))
async def send_chart(message: types.Message):
    await bot.send_chat_action(message.chat.id, ChatAction.UPLOAD_PHOTO)
    stats = await run_sync(gs.get_month_stats)
    if not stats or not stats['categories_dict']: return await message.answer("❌ Мало даних.")

    img_buf = await run_sync(visuals.generate_pie_chart, stats['categories_dict'], title=f"Витрати: {stats['month_name']}")
    if img_buf:
        photo = BufferedInputFile(img_buf.read(), filename="chart.png")
        await message.answer_photo(photo, caption=f"Витрати за {stats['month_name']}")
    else:
        await message.answer("❌ Помилка.")

@dp.message(F.text == "📉 Звіт (Тиждень)", StateFilter("*"))
async def report_week(message: types.Message):
    await bot.send_chat_action(message.chat.id, ChatAction.TYPING)
    stats = await run_sync(gs.get_week_stats)
    if not stats: return await message.answer("❌ Немає даних.")
    text = (f"📅 <b>Тижневий звіт</b>\n➖➖➖➖➖➖\n📉 Витрати: {stats['expense']:,.0f} грн\n📈 Дохід: {stats['income']:,.0f} грн\n➖➖➖➖➖➖\n🏆 <b>Топ:</b>\n")
    for cat, amount in stats['top_cats']: text += f"▫️ {cat}: {amount:,.0f} грн\n"
    await message.answer(text, parse_mode="HTML")

@dp.message(F.text == "🔔 Перевірити ліміти", StateFilter("*"))
async def check_limits(message: types.Message, state: FSMContext):
    await state.clear()
    await bot.send_chat_action(message.chat.id, ChatAction.TYPING)
    limits = await run_sync(gs.get_budget_limits)
    stats = await run_sync(gs.get_month_stats)
    if not limits: return await message.answer("🤷‍♂️ Лімітів немає")

    text = "👮‍♂️ <b>Ліміти:</b>\n"
    for cat, limit in limits.items():
        spent = stats['categories_dict'].get(cat, 0)
        pct = (spent / limit) * 100
        icon = "🟢" if pct < 50 else "🟡" if pct < 85 else "🔴"
        text += f"{icon} {cat}: {spent:.0f} / {limit:.0f} ({pct:.0f}%)\n"
    await message.answer(text, parse_mode="HTML")


# --- ЗМІНА ЛІМІТУ ---
@dp.message(F.text == "⚙️ Змінити ліміт", StateFilter("*"))
async def edit_limit_start(message: types.Message, state: FSMContext):
    await state.clear()
    await state.set_state(FinanceForm.edit_limit_cat)
    await message.answer("Обери категорію:", reply_markup=limits_edit_kb())

@dp.message(FinanceForm.edit_limit_cat)
async def edit_limit_cat(message: types.Message, state: FSMContext):
    await state.update_data(category=message.text)
    await state.set_state(FinanceForm.edit_limit_amount)
    await message.answer("Новий ліміт:", reply_markup=ReplyKeyboardRemove())

@dp.message(FinanceForm.edit_limit_amount)
async def edit_limit_save(message: types.Message, state: FSMContext):
    try:
        val = float(message.text.replace(',', '.'))
        data = await state.get_data()
        await bot.send_chat_action(message.chat.id, ChatAction.TYPING)
        if await run_sync(gs.update_budget_limit, data['category'], val):
            await message.answer(f"✅ Ліміт {data['category']}: {val:.0f} грн", reply_markup=other_kb())
        else:
            await message.answer("❌ Помилка", reply_markup=other_kb())
    except:
        await message.answer("Число!")
    await state.clear()


# ================= ФОНОВІ ЗАВДАННЯ =================
async def check_daily_reminders():
    reminders = await run_sync(gs.get_due_reminders)
    if not reminders: return

    for item in reminders:
        row_idx = str(item['row_idx'])
        CACHE["pending_reminders"][row_idx] = item
        text = (f"🔔 <b>Нагадування!</b>\nПлатіж: {item['name']}\nСума: {item['amount']} грн")
        kb = InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="✅ Сплатити", callback_data=f"pay_rem:{row_idx}")]])
        for uid in USERS:
            try:
                await bot.send_message(uid, text, reply_markup=kb, parse_mode="HTML")
            except:
                pass

@dp.callback_query(F.data.startswith("pay_rem:"))
async def pay_reminder(callback: CallbackQuery):
    row_idx = callback.data.split(":")[1]
    item = CACHE["pending_reminders"].get(row_idx)
    if not item:
        reminders = await run_sync(gs.get_due_reminders)
        item = next((r for r in reminders if str(r['row_idx']) == row_idx), None)
    if not item: return await callback.answer("❌ Вже сплачено", show_alert=True)

    await callback.message.edit_text(f"{callback.message.text}\n\n⏳ <i>Сплачую...</i>", parse_mode="HTML")
    who = USERS.get(callback.from_user.id, "Bot")
    date_now = datetime.now().strftime("%d.%m.%Y")
    await asyncio.gather(
        run_sync(gs.add_transaction, date_now, item['category'], item['amount'], "Витрати", item['name'],
                 "Auto-Reminder", who),
        run_sync(gs.update_reminder_payment, item['row_idx'], date_now)
    )
    await callback.message.edit_text(f"✅ <b>Сплачено!</b>\n▫️ {item['name']}", parse_mode="HTML")


# ================= STARTUP =================
async def on_startup():
    print("🚀 Запуск Телеграм-бота...")
    exp, inc = await run_sync(gs.get_categories)
    CACHE["expense_cats"] = exp
    CACHE["income_cats"] = inc
    
    # Запуск автопілота Mono
    asyncio.create_task(setup_monobank())
    
    scheduler.add_job(check_daily_reminders, 'cron', hour=9, minute=0)
    scheduler.add_job(partial(send_broadcast, "🌙 Не забудь записати витрати!"), 'cron', hour=21, minute=0)
    scheduler.start()
    await bot.delete_webhook(drop_pending_updates=True)

async def send_broadcast(text):
    for uid in USERS:
        try:
            await bot.send_message(uid, text)
        except:
            pass


async def start_web_server():
    """Запускає веб-сервер для прослуховування вебхуків Монобанку."""
    app = web.Application()
    app.router.add_get('/webhook', mono_webhook_get)
    app.router.add_post('/webhook', mono_webhook_post)
    
    runner = web.AppRunner(app)
    await runner.setup()
    # 0.0.0.0 означає, що сервер приймає підключення звідусіль (через Cloudflare)
    site = web.TCPSite(runner, '0.0.0.0', 18080)
    await site.start()
    print("🌐 Web-сервер Монобанку запущено на порту 18080!")

async def main():
    dp.startup.register(on_startup)
    
    # 1. Запускаємо веб-сервер у фоні
    await start_web_server()
    
    # 2. Запускаємо бота
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())