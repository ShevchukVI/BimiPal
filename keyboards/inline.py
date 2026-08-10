# keyboards/inline.py
# Всі Inline-клавіатури бота живуть тут.
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo


def generate_mono_keyboard(tx_id, cats) -> InlineKeyboardMarkup:
    """Клавіатура розбору транзакції по категоріях (Inbox Zero).
    Ключ — transaction id (не mono_id): pending можуть бути без mono_id (чеки, seed)."""
    kb_rows, row = [], []
    for c in cats[:8]:
        row.append(InlineKeyboardButton(text=c['name'], callback_data=f"mcat:{tx_id}:{c['id']}"))
        if len(row) == 2:
            kb_rows.append(row)
            row = []
    if row:
        kb_rows.append(row)
    kb_rows.append([InlineKeyboardButton(text="⏳ На потім", callback_data=f"mltr:{tx_id}"),
                    InlineKeyboardButton(text="❌ Стерти", callback_data=f"mdel:{tx_id}")])
    return InlineKeyboardMarkup(inline_keyboard=kb_rows)


def next_unresolved_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➡️ Розібрати наступну", callback_data="mnext")]
    ])


def after_categorize_kb(tx_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✍️ Додати опис (коментар)", callback_data=f"mdsc:{tx_id}")],
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


def quick_add_kb(cats, expanded: bool = False) -> InlineKeyboardMarkup:
    """Категорії для швидкого додавання («150 такси»). callback — індекс у списку.
    Без expanded: максимум 6 категорій + кнопка «Всі категорії». Завжди є «➕ Нова категорія»."""
    shown = cats if expanded else cats[:6]
    kb_rows, row = [], []
    for i, c in enumerate(shown):
        row.append(InlineKeyboardButton(text=c['name'], callback_data=f"qa:{i}"))
        if len(row) == 2:
            kb_rows.append(row)
            row = []
    if row:
        kb_rows.append(row)
    if not expanded and len(cats) > 6:
        kb_rows.append([InlineKeyboardButton(text=f"📂 Всі категорії ({len(cats)})", callback_data="qaall")])
    kb_rows.append([InlineKeyboardButton(text="➕ Нова категорія", callback_data="qanew")])
    kb_rows.append([InlineKeyboardButton(text="❌ Скасувати", callback_data="qac")])
    return InlineKeyboardMarkup(inline_keyboard=kb_rows)


def quick_add_undo_kb(tx_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="↩️ Скасувати запис", callback_data=f"qu:{tx_id}")]
    ])
