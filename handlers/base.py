# handlers/base.py
# Базові команди: /start, /app, /restart, /update, SaaS-онбординг,
# навігація по меню та статистика.
import asyncio
import subprocess
import sys

from aiogram import F, types
from aiogram.enums import ChatAction
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from services.api_client import api_client, _headers
import config
from config import ADMIN_TG_IDS, APP_URL
from handlers import bot, dp
from handlers.monobank import fetch_mono_balance
from keyboards.inline import open_app_kb
from keyboards.reply import clean_category_name, main_kb, other_kb, remove_kb
from utils import esc


class SaaSOnboarding(StatesGroup):
    family_name = State()


async def _pending_count(user_info: dict) -> int:
    """Кількість нерозібраних Monobank-транзакцій користувача (для бейджа в меню)."""
    family_id = user_info.get("current_active_family_id")
    if not family_id:
        return 0
    unresolved = await api_client.get_unresolved(family_id, user_info["id"])
    return len(unresolved) if unresolved else 0


async def _send_main_menu(message: types.Message, user_info: dict, text: str = None):
    """Надіслати головне меню з актуальним лічильником Inbox Zero."""
    pending = await _pending_count(user_info)
    await message.answer(text or "Головне меню", reply_markup=main_kb(pending), parse_mode="HTML")


@dp.message(CommandStart(), StateFilter("*"))
async def cmd_start(message: types.Message, state: FSMContext, command: Command):
    await state.clear()
    user_id = message.from_user.id
    args = command.args

    if args and (args.startswith("join_") or args.startswith("invite_")):
        invite_code = args.split("_", 1)[1]
        user_info = await api_client.get_me(user_id)
        if not user_info:
            return await message.answer(
                "👋 Це запрошення до сім'ї!\n\nСпочатку створи свій простір — натисни /start без посилання, "
                "а потім перейди за запрошенням ще раз.")
        family = await api_client.join_family_via_code(user_info["id"], invite_code)
        if family:
            return await _send_main_menu(
                message, user_info,
                f"🎉 <b>Ти приєднався до сім'ї «{esc(family['name'])}»!</b>\n\n"
                "Тепер ваші витрати та статистика — спільні. Почни з кнопки «💸 Витрата» "
                "або просто напиши сюди щось на кшталт «150 таксі».")
        return await message.answer(
            "❌ <b>Невірний або застарілий код запрошення.</b>\n"
            "Попроси адміна сім'ї згенерувати нове посилання.", parse_mode="HTML")

    user_info = await api_client.get_me(user_id)
    if user_info:
        family_id = user_info.get("current_active_family_id")
        if not family_id:
            return await message.answer("❌ Немає активної сім'ї. Перевір /families")
        stats, pending = await asyncio.gather(
            api_client.get_stats(family_id), _pending_count(user_info))
        text = f"👋 <b>З поверненням, {esc(user_info['name'])}!</b>\n"
        if stats and (stats["income"] or stats["expense"]):
            text += (f"\n📉 Витрати цього місяця: <b>{stats['expense']:,.0f} ₴</b>"
                     f"\n📈 Дохід: <b>{stats['income']:,.0f} ₴</b>").replace(",", " ")
        if pending:
            text += f"\n🧹 Очікує розбору: <b>{pending}</b>"
        text += "\n\n💡 Швидка дія: просто напиши «150 таксі» — і я запишу витрату."
        return await _send_main_menu(message, user_info, text)

    text = (
        "🏦 <b>Привіт! Я — Bimi, твій фінансовий помічник.</b>\n\n"
        "Що я вмію:\n"
        "▫️ <b>Швидкі витрати</b> — просто напиши «150 таксі»\n"
        "▫️ <b>Monobank</b> — автоматично підтягую операції по картці\n"
        "▫️ <b>Чеки з фото</b> — сфоткай чек, я розпізнаю суму й товари\n"
        "▫️ <b>Сімейний бюджет</b> — спільні витрати з партнером/родиною\n"
        "▫️ <b>Звіти та статистика</b> — куди йдуть гроші, одним поглядом\n\n"
        "Почнімо: <b>як назвемо ваш бюджет?</b>\n"
        "<i>Наприклад: «Сім'я Шевченків», «Наш дім», «Особистий».</i>")
    await state.set_state(SaaSOnboarding.family_name)
    await message.answer(text, parse_mode="HTML", reply_markup=remove_kb())


@dp.message(StateFilter(SaaSOnboarding.family_name))
async def saas_family_name(message: types.Message, state: FSMContext):
    family_name = (message.text or "").strip()
    if not family_name or len(family_name) > 60:
        return await message.answer("✍️ Напиши назву бюджету (до 60 символів):")
    await bot.send_chat_action(message.chat.id, ChatAction.TYPING)

    invite_code = await api_client.register_saas_user(message.from_user.id, message.from_user.first_name, family_name)
    if invite_code:
        bot_info = await bot.get_me()
        invite_link = f"https://t.me/{bot_info.username}?start=join_{invite_code}"
        await message.answer(
            f"🎉 <b>Простір «{family_name}» створено!</b>\n\n"
            f"🔗 <b>Запроси партнера/родину за посиланням:</b>\n<code>{invite_link}</code>\n\n"
            "<b>Що далі?</b>\n"
            "1️⃣ Напиши «150 таксі» — побачиш, як швидко додаються витрати\n"
            "2️⃣ Підключи Monobank у розділі «📂 Інше» → «💳 Монобанк»\n"
            "3️⃣ Сфоткай чек — я сам розпізнаю суму й товари\n"
            "4️⃣ Відкрий 📱 BimiApp для детальної статистики",
            reply_markup=main_kb(), parse_mode="HTML"
        )
    else:
        await message.answer("❌ Щось пішло не так. Спробуй /start ще раз.")
    await state.clear()


@dp.message(F.text == "🔙 Назад", StateFilter("*"))
async def go_back(message: types.Message, state: FSMContext):
    await state.clear()
    user_info = await api_client.get_me(message.from_user.id)
    if user_info:
        return await _send_main_menu(message, user_info)
    await message.answer("Головне меню", reply_markup=main_kb())


@dp.message(F.text == "📂 Інше", StateFilter("*"))
async def show_other_menu(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "🧰 <b>Інструменти</b>\n\n"
        "🧹 <b>Розібрати</b> — розподіли нерозібрані Monobank-витрати по категоріях\n"
        "🏦 <b>Скарбнички</b> — цілі, на які відкладаєш гроші\n"
        "👨👩👧 <b>Сім'я</b> — спільний бюджет, учасники, запрошення\n"
        "💳 <b>Монобанк</b> — підключення, токен, баланс\n"
        "📄 <b>Звіт</b> — PDF-звіт за поточний місяць\n\n"
        "<i>Оберіть потрібний інструмент нижче:</i>",
        reply_markup=other_kb(), parse_mode="HTML")


def _is_admin(message: types.Message) -> bool:
    return bool(ADMIN_TG_IDS) and message.from_user.id in ADMIN_TG_IDS


@dp.message(Command("restart"), StateFilter("*"))
async def cmd_restart(message: types.Message, state: FSMContext):
    await state.clear()
    if not _is_admin(message):
        return  # Мовчки ігноруємо: команда лише для адміна
    await message.answer("🔄 Перезапуск...")
    sys.exit(0)


@dp.message(F.text == "💳 Монобанк", StateFilter("*"))
async def monobank_menu(message: types.Message, state: FSMContext):
    await state.clear()
    user_info = await api_client.get_me(message.from_user.id)
    if not user_info:
        return await message.answer("❌ Спочатку створи профіль через /start")
    has_token = user_info.get("has_mono_token", False)
    if has_token:
        bal = await fetch_mono_balance(message.from_user.id)
        await message.answer(
            f"💳 <b>Monobank підключено</b>\n"
            f"💰 Загальний баланс: <b>{bal:,.0f} ₴</b>\n\n"
            "Кожна нова операція по картці автоматично з'являється тут —\n"
            "лише обери їй категорію у «🧹 Розібрати».\n\n"
            "Команди:\n"
            "▫️ /monoset ТОКЕН — оновити токен\n"
            "▫️ /monosync — синхронізувати рахунки".replace(",", " "),
            parse_mode="HTML", reply_markup=main_kb()
        )
    else:
        await message.answer(
            "💳 <b>Підключи Monobank — і операції приходитимуть автоматично:</b>\n\n"
            "1️⃣ Відкрий <a href='https://api.monobank.ua'>api.monobank.ua</a>\n"
            "2️⃣ Скопіюй персональний токен\n"
            "3️⃣ Надішли його сюди командою:\n<code>/monoset ТВІЙ_ТОКЕН</code>\n\n"
            "<i>🔐 Токен зберігається у зашифрованому вигляді, а повідомлення з ним "
            "я одразу видаляю з чату.</i>",
            parse_mode="HTML", disable_web_page_preview=True
        )


@dp.message(Command("monoset"), StateFilter("*"))
async def cmd_monoset(message: types.Message, state: FSMContext, command: Command):
    await state.clear()
    token_raw = command.args.strip() if command.args else ""
    if not token_raw:
        return await message.answer(
            "💳 <b>Як підключити Monobank:</b>\n\n"
            "1️⃣ Відкрий <a href='https://api.monobank.ua'>api.monobank.ua</a>\n"
            "2️⃣ Скопіюй персональний токен\n"
            "3️⃣ Надішли його сюди командою:\n<code>/monoset ТВІЙ_ТОКЕН</code>",
            parse_mode="HTML", disable_web_page_preview=True
        )
    user_info = await api_client.get_me(message.from_user.id)
    if not user_info:
        return await message.answer("❌ Спочатку створи профіль через /start")
    res = await api_client._post(
        f"/users/me/token",
        {"mono_token": token_raw},
        method="put",
        headers=_headers(x_user_id=user_info["id"])
    )
    # Одразу видаляємо повідомлення з токеном, щоб він не лишався в історії чату.
    try:
        await bot.delete_message(message.chat.id, message.message_id)
    except Exception:
        pass
    if res:
        await message.answer(
            "✅ <b>Токен збережено!</b> (повідомлення з токеном видалено з чату)\n"
            "Синхронізую рахунки...",
            reply_markup=main_kb(), parse_mode="HTML")
        from handlers.monobank import setup_monobank
        await setup_monobank()
    else:
        await message.answer(
            "❌ Не вдалося зберегти токен.\nСпробуй ще раз або додай його в 📱 BimiApp (⚙️ Меню).",
            reply_markup=main_kb())


@dp.message(Command("monosync"), StateFilter("*"))
async def cmd_monosync(message: types.Message, state: FSMContext):
    await state.clear()
    msg = await message.answer("🔄 Синхронізація Monobank...")
    results = await api_client._post(f"/banking/sync?webhook_url={config.WEBHOOK_URL}", [], method="post")
    if results is None:
        return await msg.edit_text("❌ Помилка синхронізації. Спробуй пізніше.")
    if not results:
        return await msg.edit_text(
            "💳 Monobank ще не підключено.\nДодай токен: /monoset ТОКЕН")

    lines = ["💳 <b>Результат синхронізації:</b>"]
    for r in results:
        user_info = await api_client.get_me(r["tg_id"])
        name = user_info["name"] if user_info else f"User {r['tg_id']}"
        if r.get("error"):
            lines.append(f"❌ {name}: {r['error']}")
        elif r["accounts_synced"] == 0:
            lines.append(f"⚠️ {name}: Monobank не повернув жодного рахунку")
        else:
            lines.append(f"✅ {name}: {r['accounts_synced']} рахунків синхронізовано")

    # Reload accounts
    from handlers.monobank import _load_accounts_from_backend
    await _load_accounts_from_backend()

    await msg.edit_text("\n".join(lines), parse_mode="HTML")


@dp.message(Command("update"), StateFilter("*"))
async def cmd_update(message: types.Message, state: FSMContext):
    await state.clear()
    if not _is_admin(message):
        return  # Мовчки ігноруємо: команда лише для адміна
    await message.answer("🔄 Оновлення...")
    subprocess.Popen(["git", "pull", "origin", "main"])
    sys.exit(0)


@dp.message(F.text == "📱 Відкрити BimiApp", StateFilter("*"))
@dp.message(Command("app"), StateFilter("*"))
async def open_mini_app(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("Твій фінансовий простір:", reply_markup=open_app_kb(APP_URL))


@dp.message(F.text == "📊 Статистика", StateFilter("*"))
async def show_stats(message: types.Message, state: FSMContext):
    await state.clear()
    user_info = await api_client.get_me(message.from_user.id)
    if not user_info:
        return await message.answer("❌ Акаунт не знайдено. Введи /start")

    await bot.send_chat_action(message.chat.id, ChatAction.TYPING)
    active_family_id = user_info["current_active_family_id"]
    if not active_family_id:
        return await message.answer("❌ Немає активної сім'ї. Використай /families")
    stats = await api_client.get_stats(active_family_id)
    if not stats:
        return await message.answer(
            "📭 Поки немає даних.\nДодай першу витрату — просто напиши «150 таксі».",
            reply_markup=main_kb())

    users = await api_client._get(f"/families/{active_family_id}/users")
    mono_text = ""
    if users:
        for u in users:
            if u.get("has_mono_token") and u.get("tg_id"):
                bal = await fetch_mono_balance(u["tg_id"])
                mono_text += f"▫️ {esc(u['name'])}: {bal:,.0f} ₴\n"

    pending = await _pending_count(user_info)

    # --- Місячні дохід/витрати по валютах (by_currency) ---
    by_cur = stats.get("by_currency") or {}
    # Fallback: якщо by_currency порожній — старі поля (UAH)
    if not by_cur:
        by_cur = {"UAH": {"income": stats.get("income", 0), "expense": stats.get("expense", 0)}}

    def _money(v, cur):
        sym = {"UAH": "₴", "USD": "$", "EUR": "€"}.get(cur, cur)
        return f"{v:,.0f} {sym}".replace(",", " ")

    text = f"📊 <b>Цей місяць</b>\n"
    for cur, v in sorted(by_cur.items()):
        text += (f"▫️ <b>{cur}</b>  📈 {_money(v.get('income', 0), cur)}"
                 f"  📉 {_money(v.get('expense', 0), cur)}"
                 f"  💰 {_money(v.get('income', 0) - v.get('expense', 0), cur)}\n")
    text += f"➖➖➖➖➖➖\n"

    # --- Готівка по валютах (cash_by_currency) ---
    cash_cur = stats.get("cash_by_currency")
    if cash_cur:
        parts = " | ".join(f"{_money(c['balance'], c['currency'])}" for c in cash_cur)
        text += f"💵 <b>Готівка:</b> {parts}\n➖➖➖➖➖➖\n"
    elif stats.get("balances", {}).get("Готівка") is not None:
        text += f"💵 <b>Готівка:</b> {_money(stats['balances']['Готівка'], 'UAH')}\n➖➖➖➖➖➖\n"
    if mono_text:
        text += f"💳 <b>Баланс Monobank:</b>\n{mono_text}➖➖➖➖➖➖\n"
    if pending:
        text += f"🧹 Очікує розбору: <b>{pending}</b> — натисни «🧹 Розібрати»\n➖➖➖➖➖➖\n"
    if stats['top_categories']:
        text += "🏆 <b>Топ витрат:</b>\n"
        for cat in stats['top_categories'][:5]:
            clean_name = clean_category_name(cat['name'])
            text += f"▫️ {esc(clean_name)}: {cat['amount']:,.0f} ₴\n"
    else:
        text += "🏆 Категорій з витратами цього місяця ще немає.\n"

    await message.answer(text.replace(",", " "), parse_mode="HTML",
                         reply_markup=main_kb(pending))


@dp.message(F.text == "🏦 Скарбнички", StateFilter("*"))
async def show_jars(message: types.Message, state: FSMContext):
    await state.clear()
    user_info = await api_client.get_me(message.from_user.id)
    if not user_info:
        return await message.answer("❌ Акаунт не знайдено. Введи /start")

    await bot.send_chat_action(message.chat.id, ChatAction.TYPING)
    jars = await api_client.get_jars(user_info["current_active_family_id"])
    if not jars:
        return await message.answer(
            "🏦 <b>Скарбничок поки немає.</b>\nСтвори першу ціль у 📱 BimiApp (вкладка «Цілі») — "
            "наприклад, «Відпустка» або «Нова машина».",
            reply_markup=main_kb(), parse_mode="HTML")

    def _progress_bar(balance: float, goal: float):
        pct = min(balance / goal * 100, 100) if goal > 0 else 0.0
        filled = round(pct / 10)
        return "🟩" * filled + "⬜" * (10 - filled), pct

    lines = ["🏦 <b>Скарбнички</b>"]
    for j in jars:
        bar, pct = _progress_bar(j.get("balance", 0), j.get("goal", 0))
        lines.append(
            f"\n💰 <b>{j['name']}</b>\n"
            f"   Баланс: {j['balance']:,.0f} ₴ з {j['goal']:,.0f} ₴\n"
            f"   {bar} {pct:.0f}%"
        )

    await message.answer("\n".join(lines).replace(",", " "), parse_mode="HTML", reply_markup=main_kb())
