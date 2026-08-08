# handlers/families.py
# Multi-family (M2M): /families меню, перемикання активної сім'ї,
# меню управління (admin) та генерація invite-посилання.
from aiogram import F, types
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext

from services.api_client import api_client
from handlers import bot, dp
from keyboards.inline import families_kb, manage_family_kb
from keyboards.reply import main_kb


@dp.message(F.text == "👨👩👧 Сім'я", StateFilter("*"))
@dp.message(Command("families"), StateFilter("*"))
async def show_families(message: types.Message, state: FSMContext):
    await state.clear()
    user_info = await api_client.get_me(message.from_user.id)
    if not user_info:
        return await message.answer("❌ Акаунт не знайдено. Введіть /start")
    fams = await api_client.get_my_families(user_info["id"])
    if not fams:
        return await message.answer("Ти ще не в жодній сім'ї. Створи простір через /start", reply_markup=main_kb())
    await message.answer("👨‍👩‍👧 <b>Твої сім'ї</b>\nОберіть сім'ю (✅ — активна):",
                         reply_markup=families_kb(fams), parse_mode="HTML")


@dp.callback_query(F.data.startswith("fam:"))
async def switch_family(call: types.CallbackQuery):
    try:
        family_id = int(call.data.split(":")[1])
    except (ValueError, IndexError):
        return await call.answer("Помилка", show_alert=True)
    user_info = await api_client.get_me(call.from_user.id)
    if not user_info:
        return await call.answer("Акаунт не знайдено", show_alert=True)
    res = await api_client.set_active_family(user_info["id"], family_id)
    if not res:
        return await call.answer("Не вдалося перемкнути сім'ю", show_alert=True)
    fams = await api_client.get_my_families(user_info["id"])
    active = next((f for f in fams if f.get("is_active")), None)
    name = active["name"] if active else f"ID {family_id}"
    await call.message.edit_text(f"✅ Active family switched to: <b>{name}</b>",
                                 reply_markup=families_kb(fams), parse_mode="HTML")


@dp.callback_query(F.data == "fam_list")
async def families_list_back(call: types.CallbackQuery):
    user_info = await api_client.get_me(call.from_user.id)
    if not user_info:
        return await call.answer("Акаунт не знайдено", show_alert=True)
    fams = await api_client.get_my_families(user_info["id"])
    await call.message.edit_text("👨‍👩‍👧 <b>Твої сім'ї</b>", reply_markup=families_kb(fams), parse_mode="HTML")


@dp.callback_query(F.data == "fam_manage")
async def manage_family(call: types.CallbackQuery):
    user_info = await api_client.get_me(call.from_user.id)
    if not user_info:
        return await call.answer("Акаунт не знайдено", show_alert=True)
    fams = await api_client.get_my_families(user_info["id"])
    active = next((f for f in fams if f.get("is_active")), None)
    if not active or active.get("role") != "admin":
        return await call.answer("Тільки адмін сім'ї може керувати", show_alert=True)
    await call.message.edit_text(f"⚙️ <b>Управління сім'єю</b>: {active['name']}",
                                 reply_markup=manage_family_kb(), parse_mode="HTML")


@dp.callback_query(F.data == "fam_invite")
async def generate_invite_link(call: types.CallbackQuery):
    user_info = await api_client.get_me(call.from_user.id)
    if not user_info:
        return await call.answer("Акаунт не знайдено", show_alert=True)
    fams = await api_client.get_my_families(user_info["id"])
    active = next((f for f in fams if f.get("is_active")), None)
    if not active or active.get("role") != "admin":
        return await call.answer("Тільки адмін", show_alert=True)
    res = await api_client.generate_invite(user_info["id"], active["family_id"])
    if not res:
        return await call.answer("Помилка генерації запрошення", show_alert=True)
    bot_info = await bot.get_me()
    link = f"https://t.me/{bot_info.username}?start={res['invite_code']}"
    await call.message.edit_text(f"🔗 <b>Запрошення до сім'ї:</b>\n<code>{link}</code>",
                                 reply_markup=manage_family_kb(), parse_mode="HTML")
