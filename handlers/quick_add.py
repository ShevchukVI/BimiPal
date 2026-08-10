# handlers/quick_add.py
# Zero Friction: користувач просто пише «150 такси», «кава 150 грн» або «+5000 зп» —
# бот пропонує категорію інлайн-кнопками і записує транзакцію в один дотик.
# ЗАРЕЄСТРОВАНО ОСТАННІМ у handlers/__init__.py — щоб FSM-хендлери
# (expenses, monobank) та scratchpad (📝) мали пріоритет.
import re

from aiogram import F, types
from aiogram.enums import ChatAction
from aiogram.filters import BaseFilter, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from services.api_client import api_client
from handlers import bot, dp
from keyboards.inline import quick_add_kb, quick_add_undo_kb
from utils import esc, fmt_amount

# --- Парсер природної мови для швидких транзакцій ---
# Підтримка: «150 кава», «кава 150», «кава 150 грн», «150 грн кава», «газ 800 грн»,
# «800 газ», «+5000 зп», «зп +5000», «150 гривень кава», «кава за 150», «купив каву за 150»,
# «100 000 зп» (роздільник тисяч), «250 кава готівкою».
# ВІДМОВА: «цибуля 200 г, морква 500 г» — це опис (грами), а не транзакція.

CURRENCY_WORDS = {"грн", "гривень", "гривні", "гривня", "гривням", "гривнею", "гривен", "uah", "₴"}
UNIT_WORDS = {"г", "грам", "грамм", "кг", "мл", "л", "літр", "літри", "літрів", "см", "м",
              "метр", "метри", "шт", "штук", "штуки", "уп", "упаковка", "пачка", "пачки",
              "хв", "хвилин", "км", "сек"}
CASH_WORDS = {"готівка", "готівкою", "кеш", "кешем", "cash", "нал", "наличка"}

_NUM_RE = re.compile(r'^([+-]?)(\d+(?:[.,]\d{1,2})?)$')
_THOUSAND_RE = re.compile(r'^\d{3}$')
MAX_QUICK_AMOUNT = 10_000_000


def _clean_word(tok: str) -> str:
    return tok.lower().strip('.,!?')


def parse_quick_add(text: str):
    """Повертає dict(amount, title, t_type, account) або None, якщо суму
    неможливо визначити однозначно (тоді бот мовчить — це, ймовірно, опис/нотатка)."""
    tokens = text.split()
    if not tokens:
        return None

    # 1) Злиття розділених пробілом тисяч: «100 000» → «100000»
    merged = []
    i = 0
    while i < len(tokens):
        if _NUM_RE.match(tokens[i]) and '.' not in tokens[i] and ',' not in tokens[i]:
            j = i
            val = tokens[i]
            while j + 1 < len(tokens) and _THOUSAND_RE.match(tokens[j + 1]):
                val += tokens[j + 1]
                j += 1
            merged.append(val)
            i = j + 1
        else:
            merged.append(tokens[i])
            i += 1
    tokens = merged

    # 2) Маркер готівки — вирізаємо з тексту (account за замовчуванням і так Готівка)
    cash_idx = {i for i, t in enumerate(tokens) if _clean_word(t) in CASH_WORDS}

    # 3) Кандидати в суму
    strong, weak = [], []  # (index, sign, amount)
    for i, tok in enumerate(tokens):
        m = _NUM_RE.match(tok)
        if not m:
            continue
        nxt = _clean_word(tokens[i + 1]) if i + 1 < len(tokens) else ""
        if nxt in UNIT_WORDS:
            continue  # кількість/вага, не гроші
        try:
            amount = float(m.group(2).replace(',', '.'))
        except ValueError:
            continue
        entry = (i, m.group(1), amount)
        if nxt in CURRENCY_WORDS:
            strong.append(entry)
        else:
            weak.append(entry)

    if len(strong) == 1:
        chosen = strong[0]
    elif not strong and len(weak) == 1:
        chosen = weak[0]
    else:
        return None  # 0 або 2+ кандидатів — негативна впевненість, не парсимо

    idx, sign, amount = chosen
    if amount <= 0 or amount > MAX_QUICK_AMOUNT:
        return None

    # 4) Title: все, крім суми, валютного слова, маркера готівки та «за» перед сумою
    skip = {idx} | cash_idx
    if idx + 1 < len(tokens) and _clean_word(tokens[idx + 1]) in CURRENCY_WORDS:
        skip.add(idx + 1)
    if idx - 1 >= 0 and _clean_word(tokens[idx - 1]) == "за":
        skip.add(idx - 1)
    title = " ".join(t for i, t in enumerate(tokens) if i not in skip).strip(' ,.-—')

    return {
        "amount": amount,
        "title": title,
        "t_type": "Поповнення" if sign == "+" else "Витрати",
        "account": "Готівка",
    }


class QuickAddForm(StatesGroup):
    category = State()
    new_cat_name = State()


class QuickAddTextFilter(BaseFilter):
    """Пропускає лише текст, схожий на швидку транзакцію («150 кава»).
    НЕ спрацьовує під час введення назви нової категорії та для команд/нотаток —
    такі повідомлення провалюються до інших хендлерів."""
    async def __call__(self, message: types.Message, state: FSMContext) -> bool:
        if await state.get_state() == QuickAddForm.new_cat_name.state:
            return False
        t = message.text or ""
        if not t or t.startswith(("/", "📝")):
            return False
        return parse_quick_add(t) is not None


@dp.message(QuickAddTextFilter(), StateFilter("*"))
async def quick_add_start(message: types.Message, state: FSMContext):
    parsed = parse_quick_add(message.text)
    if not parsed:
        return  # не схоже на транзакцію — ігноруємо (може, це просто текст)

    await state.clear()
    user_info = await api_client.get_me(message.from_user.id)
    if not user_info:
        return await message.answer("❌ Акаунт не знайдено. Введи /start")
    family_id = user_info.get("current_active_family_id")
    if not family_id:
        return await message.answer("❌ Немає активної сім'ї. Використай /families")

    cat_type = "income" if parsed["t_type"] == "Поповнення" else "expense"
    cats = await api_client.get_categories(family_id, cat_type)
    cats = [c for c in cats if "Очікує" not in c['name']]
    if not cats:
        return await message.answer("❌ Немає категорій. Створи їх у 📱 BimiApp.")

    await state.update_data(amount=parsed["amount"], title=parsed["title"],
                            t_type=parsed["t_type"], account=parsed["account"],
                            family_id=family_id, user_id=user_info["id"],
                            cats=cats, cat_type=cat_type)
    await state.set_state(QuickAddForm.category)

    icon = "📈" if parsed["t_type"] == "Поповнення" else "📉"
    desc = f" — «{esc(parsed['title'])}»" if parsed["title"] else ""
    await message.answer(
        f"{icon} <b>{fmt_amount(parsed['amount'])} ₴</b>{desc}\nОбери категорію:",
        reply_markup=quick_add_kb(cats), parse_mode="HTML")


@dp.callback_query(F.data.startswith("qa:"), StateFilter(QuickAddForm.category))
async def quick_add_save(call: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    cats = data.get("cats", [])
    try:
        cat = cats[int(call.data.split(":")[1])]
    except (ValueError, IndexError):
        return await call.answer("Категорію не знайдено", show_alert=True)
    await _save_quick(call, state, data, cat)


@dp.callback_query(F.data == "qaall", StateFilter(QuickAddForm.category))
async def quick_add_all_cats(call: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    await call.message.edit_reply_markup(reply_markup=quick_add_kb(data.get("cats", []), expanded=True))
    await call.answer()


@dp.callback_query(F.data == "qanew", StateFilter(QuickAddForm.category))
async def quick_add_new_cat(call: types.CallbackQuery, state: FSMContext):
    await state.set_state(QuickAddForm.new_cat_name)
    await call.message.answer("✍️ Напиши назву нової категорії (наприклад: «🐶 Тварини»):")
    await call.answer()


@dp.message(StateFilter(QuickAddForm.new_cat_name))
async def quick_add_create_cat(message: types.Message, state: FSMContext):
    name = (message.text or "").strip()
    if not name or len(name) > 40:
        return await message.answer("✍️ Назва категорії — до 40 символів. Спробуй ще:")
    data = await state.get_data()
    cat = await api_client.create_category(data["family_id"], name, data.get("cat_type", "expense"))
    if not cat:
        await state.set_state(QuickAddForm.category)
        return await message.answer("❌ Не вдалося створити категорію. Обери зі списку:",
                                    reply_markup=quick_add_kb(data.get("cats", []), expanded=True))
    # Повертаємося до збереження з новою категорією
    fake_call_message = await message.answer("⏳ Зберігаю...")
    await _save_quick_direct(message, fake_call_message, state, data, cat)


async def _save_quick(call: types.CallbackQuery, state: FSMContext, data: dict, cat: dict):
    """Збереження через callback (редагуємо повідомлення з кнопками)."""
    await bot.send_chat_action(call.message.chat.id, ChatAction.TYPING)
    await state.clear()
    title = data["title"] or cat["name"]
    res = await api_client.add_transaction(data["family_id"], data["user_id"], cat["id"],
                                           data["amount"], data["t_type"], title, data["account"])
    if res:
        await call.message.edit_text(
            f"✅ <b>{fmt_amount(data['amount'])} ₴</b> → {esc(cat['name'])}\n"
            f"📝 {esc(title)}",
            reply_markup=quick_add_undo_kb(res["id"]), parse_mode="HTML")
    else:
        await call.message.edit_text("❌ Помилка збереження. Спробуй ще раз.")


async def _save_quick_direct(message: types.Message, tmp_msg: types.Message,
                             state: FSMContext, data: dict, cat: dict):
    """Збереження після створення нової категорії (відповідь новим повідомленням)."""
    await state.clear()
    title = data["title"] or cat["name"]
    res = await api_client.add_transaction(data["family_id"], data["user_id"], cat["id"],
                                           data["amount"], data["t_type"], title, data["account"])
    await tmp_msg.delete()
    if res:
        await message.answer(
            f"✅ Категорію «{esc(cat['name'])}» створено.\n"
            f"<b>{fmt_amount(data['amount'])} ₴</b> → {esc(cat['name'])}\n📝 {esc(title)}",
            reply_markup=quick_add_undo_kb(res["id"]), parse_mode="HTML")
    else:
        await message.answer("❌ Помилка збереження. Спробуй ще раз.")


@dp.callback_query(F.data == "qac", StateFilter(QuickAddForm.category))
async def quick_add_cancel(call: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.edit_text("🚫 Скасовано.")


@dp.callback_query(F.data.startswith("qa:"))
@dp.callback_query(F.data.in_(["qac", "qaall", "qanew"]))
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
        await call.message.edit_text(f"↩️ <s>{esc(call.message.text)}</s>\n<b>Запис скасовано.</b>",
                                     parse_mode="HTML")
    else:
        await call.answer("Не вдалося скасувати", show_alert=True)
