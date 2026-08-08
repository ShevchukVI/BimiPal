# handlers/base.py
# Базові команди: /start, /app, /restart, /update, SaaS-онбординг,
# навігація по меню та статистика.
import subprocess
import sys

from aiogram import F, types
from aiogram.enums import ChatAction
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from services.api_client import api_client
from config import APP_URL
from handlers import bot, dp
from handlers.monobank import fetch_mono_balance
from keyboards.inline import open_app_kb
from keyboards.reply import clean_category_name, main_kb, other_kb, remove_kb


class SaaSOnboarding(StatesGroup):
    family_name = State()


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
                "Спочатку створи свій простір через /start, потім приєднуйся за запрошенням.",
                reply_markup=main_kb())
        family = await api_client.join_family_via_code(user_info["id"], invite_code)
        if family:
            return await message.answer(f"🎉 Ти приєднався до сім'ї <b>{family['name']}</b>!",
                                        reply_markup=main_kb(), parse_mode="HTML")
        return await message.answer("❌ Невірний або застарілий код запрошення.")

    user_info = await api_client.get_me(user_id)
    if user_info:
        await message.answer(f"Привіт, {user_info['name']}! 👋", reply_markup=main_kb())
    else:
        text = "🏦 <b>Привіт! Я — Bimi.</b>\nТвій фінансовий помічник.\n\nЯк назвемо вашу сім'ю чи бюджет?"
        await state.set_state(SaaSOnboarding.family_name)
        await message.answer(text, parse_mode="HTML", reply_markup=remove_kb())


@dp.message(StateFilter(SaaSOnboarding.family_name))
async def saas_family_name(message: types.Message, state: FSMContext):
    family_name = message.text.strip()
    await bot.send_chat_action(message.chat.id, ChatAction.TYPING)

    invite_code = await api_client.register_saas_user(message.from_user.id, message.from_user.first_name, family_name)
    if invite_code:
        bot_info = await bot.get_me()
        invite_link = f"https://t.me/{bot_info.username}?start=join_{invite_code}"
        await message.answer(
            f"🎉 <b>Простір '{family_name}' створено!</b>\n\n"
            f"🔗 <b>Запрошення:</b>\n<code>{invite_link}</code>\n\n"
            "Токен Монобанку можна додати в BimiApp ⚙️",
            reply_markup=main_kb(), parse_mode="HTML"
        )
    else:
        await message.answer("❌ Помилка.")
    await state.clear()


@dp.message(F.text == "🔙 Назад", StateFilter("*"))
async def go_back(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("Головне меню", reply_markup=main_kb())


@dp.message(F.text == "📂 Інше", StateFilter("*"))
async def show_other_menu(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("Інструменти:", reply_markup=other_kb())


@dp.message(Command("restart"), StateFilter("*"))
async def cmd_restart(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("🔄 Перезапуск...")
    sys.exit(0)


@dp.message(Command("update"), StateFilter("*"))
async def cmd_update(message: types.Message, state: FSMContext):
    await state.clear()
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
        return await message.answer("❌ Акаунт не знайдено.")

    await bot.send_chat_action(message.chat.id, ChatAction.TYPING)
    active_family_id = user_info["current_active_family_id"]
    if not active_family_id:
        return await message.answer("❌ Немає активної сім'ї. Використай /families")
    stats = await api_client.get_stats(active_family_id)
    if not stats:
        return await message.answer("❌ Немає даних для статистики.")

    users = await api_client._get(f"/families/{active_family_id}/users")
    total_mono = 0
    mono_text = ""

    if users:
        for u in users:
            if u.get("has_mono_token") and u.get("tg_id"):
                bal = await fetch_mono_balance(u["tg_id"])
                total_mono += bal
                mono_text += f"👤 {u['name']}: {bal:,.0f} ₴\n"

    total_cash = stats['balance'] - total_mono

    text = (
        f"📊 <b>Бюджет (Цей місяць)</b>\n"
        f"📈 Дохід: {stats['income']:,.0f} ₴\n"
        f"📉 Витрати: {stats['expense']:,.0f} ₴\n"
        f"💰 Залишок: {stats['balance']:,.0f} ₴\n"
        f"➖➖➖➖➖➖\n"
    )
    if mono_text:
        text += f"💳 <b>Монобанк:</b>\n{mono_text}"
    text += f"💵 <b>Готівка:</b> {total_cash:,.0f} ₴\n➖➖➖➖➖➖\n🏆 <b>Топ витрат:</b>\n"

    for cat in stats['top_categories'][:5]:
        clean_name = clean_category_name(cat['name'])
        text += f"▫️ {clean_name}: {cat['amount']:,.0f} ₴\n"

    await message.answer(text.replace(",", " "), parse_mode="HTML")


def _progress_bar(balance: float, goal: float):
    """Повертає візуальний прогрес-бар (10 клітинок) та відсоток наповнення."""
    pct = min(balance / goal * 100, 100) if goal > 0 else 0.0
    filled = round(pct / 10)
    bar = "🟩" * filled + "⬜" * (10 - filled)
    return bar, pct


@dp.message(F.text == "🏦 Скарбнички", StateFilter("*"))
async def show_jars(message: types.Message, state: FSMContext):
    await state.clear()
    user_info = await api_client.get_me(message.from_user.id)
    if not user_info:
        return await message.answer("❌ Акаунт не знайдено.")

    await bot.send_chat_action(message.chat.id, ChatAction.TYPING)
    jars = await api_client.get_jars(user_info["current_active_family_id"])
    if not jars:
        return await message.answer("🏦 Немає цілей. Створи скарбничку в BimiApp!", reply_markup=main_kb())

    lines = ["🏦 <b>Скарбнички</b>"]
    for j in jars:
        bar, pct = _progress_bar(j.get("balance", 0), j.get("goal", 0))
        lines.append(
            f"\n💰 <b>{j['name']}</b>\n"
            f"   Баланс: {j['balance']:,.0f} ₴ з {j['goal']:,.0f} ₴\n"
            f"   {bar} {pct:.0f}%"
        )

    await message.answer("\n".join(lines).replace(",", " "), parse_mode="HTML", reply_markup=main_kb())


@dp.message(F.text == "🔔 Ліміти (В розробці)")
async def placeholder_features(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("🚧 Відкрийте застосунок BimiApp для доступу до цієї функції!", reply_markup=main_kb())
