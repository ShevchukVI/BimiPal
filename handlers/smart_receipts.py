# handlers/smart_receipts.py
# ШІ-розбір фото чеків: користувач надсилає фото → Vision-модель повертає
# магазин, суму та список товарів → бот пропонує записати як "Очікує"
# (далі користувач розбирає його через Inbox Zero).
import base64
import io
import logging

from aiogram import F, types
from aiogram.enums import ChatAction
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from services.api_client import api_client
from handlers import bot, dp
from keyboards.inline import receipt_confirm_kb

logger = logging.getLogger(__name__)

MAX_IMAGE_BYTES = 5 * 1024 * 1024  # 5 MB limit

try:
    from services.ai_service import ai_manager
except ImportError:
    ai_manager = None


class ReceiptForm(StatesGroup):
    confirm_cat_id = State()


@dp.message(F.photo, StateFilter("*"))
async def receipt_photo(message: types.Message, state: FSMContext):
    if ai_manager is None:
        return await message.answer("❌ AI-сервіс недоступний.")
    await state.clear()
    await bot.send_chat_action(message.chat.id, ChatAction.TYPING)

    photo = message.photo[-1]
    if photo.file_size and photo.file_size > MAX_IMAGE_BYTES:
        return await message.answer("❌ Зображення занадто велике (макс. 5 MB). Надішли менше фото.")
    buf = io.BytesIO()
    await bot.download(photo, destination=buf)
    image_size = buf.tell()
    if image_size > MAX_IMAGE_BYTES:
        return await message.answer("❌ Зображення занадто велике після завантаження. Стисни та спробуй ще.")
    base64_image = base64.b64encode(buf.getvalue()).decode()

    parsed = await ai_manager.parse_receipt_image(base64_image)
    if not parsed:
        return await message.answer("❌ Не вдалося розпізнати чек. Спробуй чіткіше фото.")

    shop = parsed.get("shop_name", "Магазин")
    total = parsed.get("total_amount", 0)
    items = parsed.get("items", []) or []
    items_text = "\n".join(f"• {i}" for i in items[:15]) or "Без позицій"

    await state.update_data(receipt=parsed)
    await message.answer(
        f"🧾 <b>{shop}</b>\n💰 <b>{total:.2f} ₴</b>\n\n<i>Товари:</i>\n{items_text}\n\nЗаписати цю покупку?",
        parse_mode="HTML", reply_markup=receipt_confirm_kb())


@dp.callback_query(F.data == "rcpt_save")
async def receipt_save(call: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    parsed = data.get("receipt")
    user_info = await api_client.get_me(call.from_user.id)
    if not parsed or not user_info:
        await state.clear()
        return await call.message.edit_text("❌ Щось пішло не так. Спробуй ще раз.")

    cats = await api_client.get_categories(user_info["current_active_family_id"])
    pending_cat = next((c['id'] for c in cats if "Очікує" in c['name']), None)
    if not pending_cat:
        await state.clear()
        return await call.message.edit_text("❌ Категорія 'Очікує' не знайдена.")

    shop = parsed.get("shop_name", "Магазин")
    total = parsed.get("total_amount", 0)
    items = parsed.get("items", []) or []
    title = f"🧾 {shop}: " + ", ".join(str(i) for i in items[:6])

    res = await api_client.add_transaction(user_info["current_active_family_id"], user_info["id"], pending_cat, total,
                                           "Витрати", title, "Готівка")
    if res:
        await call.message.edit_text(
            f"✅ <b>Чек записано ({total:.2f} ₴)</b>\n\nОбери йому категорію через «🧹 Розібрати» в головному меню.",
            parse_mode="HTML")
    else:
        await call.message.edit_text("❌ Помилка збереження чека.")
    await state.clear()


@dp.callback_query(F.data == "rcpt_cancel")
async def receipt_cancel(call: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.edit_text("🚫 Чек скасовано.")
