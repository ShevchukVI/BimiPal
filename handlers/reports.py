import io
import csv
from datetime import datetime

from aiogram import F, types
from aiogram.filters import Command, StateFilter
from aiogram.enums import ChatAction
from aiogram.types import BufferedInputFile

from services.api_client import api_client
from handlers import bot, dp
from handlers.base import go_back
from keyboards.reply import main_kb
from reports import generate_monthly_report


MONTHS_UA = {
    1: "Січень", 2: "Лютий", 3: "Березень", 4: "Квітень",
    5: "Травень", 6: "Червень", 7: "Липень", 8: "Серпень",
    9: "Вересень", 10: "Жовтень", 11: "Листопад", 12: "Грудень"
}


@dp.message(Command("report"), StateFilter("*"))
@dp.message(F.text == "📄 Звіт", StateFilter("*"))
async def cmd_report(message: types.Message, state):
    await state.clear()
    user_info = await api_client.get_me(message.from_user.id)
    if not user_info:
        return await message.answer("❌ Акаунт не знайдено. Введіть /start")
    family_id = user_info.get("current_active_family_id")
    if not family_id:
        return await message.answer("❌ Немає активної сім'ї.")

    now = datetime.now()
    await bot.send_chat_action(message.chat.id, ChatAction.UPLOAD_DOCUMENT)

    data = await api_client.get_month_history_sql(family_id, now.year, now.month)
    if not data or data.get("income", 0) == 0 and data.get("expense", 0) == 0:
        return await message.answer(
            "📭 У цьому місяці ще немає транзакцій.\n"
            "Додай витрати або доходи через 💸 Витрата чи 💰 Дохід.",
            reply_markup=main_kb()
        )

    try:
        pdf_buffer = generate_monthly_report(data, MONTHS_UA[now.month], now.year)
        filename = f"Bimi_Report_{now.year}_{now.month:02d}.pdf"
        doc = BufferedInputFile(pdf_buffer.read(), filename=filename)
        await message.answer_document(doc, caption=f"📊 Звіт за {MONTHS_UA[now.month]} {now.year}")
    except Exception as e:
        await message.answer(f"❌ Помилка генерації звіту: {e}", reply_markup=main_kb())


@dp.message(Command("export"), StateFilter("*"))
async def cmd_export_csv(message: types.Message, state):
    await state.clear()
    user_info = await api_client.get_me(message.from_user.id)
    if not user_info:
        return await message.answer("❌ Акаунт не знайдено.")
    family_id = user_info.get("current_active_family_id")
    if not family_id:
        return await message.answer("❌ Немає активної сім'ї.")

    await bot.send_chat_action(message.chat.id, ChatAction.UPLOAD_DOCUMENT)

    txs = await api_client._get(f"/families/{family_id}/transactions?limit=1000")
    if not txs:
        return await message.answer("📭 Немає транзакцій для експорту.")

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Дата", "Тип", "Сума", "Категорія", "Опис", "Рахунок", "Monobank ID"])
    cats = await api_client.get_categories(family_id)
    cat_map = {c["id"]: c["name"] for c in cats}

    for t in txs:
        writer.writerow([
            t.get("date", ""),
            t.get("type", ""),
            t.get("amount", ""),
            cat_map.get(t.get("category_id"), "Інше"),
            t.get("title", ""),
            t.get("account", ""),
            t.get("mono_id", "")
        ])

    output.seek(0)
    data_bytes = output.getvalue().encode("utf-8-sig")
    now = datetime.now()
    doc = BufferedInputFile(data_bytes, filename=f"Bimi_Export_{now.strftime('%Y%m%d')}.csv")
    await message.answer_document(doc, caption=f"📁 Експорт транзакцій ({len(txs)} записів)")
