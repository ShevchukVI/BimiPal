# keyboards/inline.py
# Всі Inline-клавіатури бота живуть тут.
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo


def generate_mono_keyboard(mono_id: str, cats) -> InlineKeyboardMarkup:
    """Клавіатура розбору транзакції Монобанку по категоріях (Inbox Zero)."""
    kb_rows, row = [], []
    for c in cats[:8]:
        row.append(InlineKeyboardButton(text=c['name'], callback_data=f"mcat:{mono_id}:{c['id']}"))
        if len(row) == 2:
            kb_rows.append(row)
            row = []
    if row:
        kb_rows.append(row)
    kb_rows.append([InlineKeyboardButton(text="⏳ На потім", callback_data=f"mltr:{mono_id}"),
                    InlineKeyboardButton(text="❌ Стерти", callback_data=f"mdel:{mono_id}")])
    return InlineKeyboardMarkup(inline_keyboard=kb_rows)


def next_unresolved_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➡️ Розібрати наступну", callback_data="mnext")]
    ])


def after_categorize_kb(mono_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✍️ Додати опис (коментар)", callback_data=f"mdsc:{mono_id}")],
        [InlineKeyboardButton(text="⏩ Готово (Пропустити)", callback_data="mdon")]
    ])


def open_app_kb(url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚀 Запустити BimiApp", web_app=WebAppInfo(url=url))]
    ])


def receipt_confirm_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Записати", callback_data="rcpt_save")],
        [InlineKeyboardButton(text="❌ Скасувати", callback_data="rcpt_cancel")]
    ])


def families_kb(fams) -> InlineKeyboardMarkup:
    """Список сімей користувача: кнопка на кожну + (для admin активної) кнопка управління."""
    kb = []
    for f in fams:
        label = f["name"]
        if f.get("role") == "admin":
            label += " 👑"
        if f.get("is_active"):
            label += " ✅"
        kb.append([InlineKeyboardButton(text=label, callback_data=f"fam:{f['family_id']}")])
    active = next((f for f in fams if f.get("is_active")), None)
    if active and active.get("role") == "admin":
        kb.append([InlineKeyboardButton(text="⚙️ Керувати сім'єю", callback_data="fam_manage")])
    return InlineKeyboardMarkup(inline_keyboard=kb)


def manage_family_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔗 Згенерувати запрошення", callback_data="fam_invite")],
        [InlineKeyboardButton(text="🔙 До сімей", callback_data="fam_list")],
    ])
