# keyboards/reply.py
# Всі Reply-клавіатури бота живуть тут (main.py тримає лише точку входу).
import re

from aiogram.types import KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove


def clean_category_name(name: str) -> str:
    """Прибирає провідні емодзі/небуквенні символи з назви категорії для кнопок."""
    return re.sub(r'^[^\w\s]+', '', name).strip()


def main_kb(pending: int = 0) -> ReplyKeyboardMarkup:
    """Головне меню. Якщо є нерозібрані Monobank-транзакції — додаємо рядок Inbox Zero."""
    rows = [
        [KeyboardButton(text="💸 Витрата"), KeyboardButton(text="💰 Дохід")],
        [KeyboardButton(text="📊 Статистика"), KeyboardButton(text="📂 Інше")],
    ]
    if pending > 0:
        rows.append([KeyboardButton(text=f"🧹 Розібрати ({pending})")])
    rows.append([KeyboardButton(text="📱 Відкрити BimiApp")])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def other_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="🧹 Розібрати"), KeyboardButton(text="🏦 Скарбнички")],
        [KeyboardButton(text="👨👩👧 Сім'я"), KeyboardButton(text="💳 Монобанк")],
        [KeyboardButton(text="📄 Звіт")],
        [KeyboardButton(text="🔙 Назад")]
    ], resize_keyboard=True)


def categories_kb(cats) -> ReplyKeyboardMarkup:
    """Клавіатура вибору категорії (по 2 на ряд) для ручного додавання транзакції."""
    kb_rows, row = [], []
    for c in cats:
        row.append(KeyboardButton(text=clean_category_name(c['name'])))
        if len(row) == 2:
            kb_rows.append(row)
            row = []
    if row:
        kb_rows.append(row)
    kb_rows.append([KeyboardButton(text="🔙 Назад")])
    return ReplyKeyboardMarkup(keyboard=kb_rows, resize_keyboard=True)


def description_kb() -> ReplyKeyboardMarkup:
    """Крок опису транзакції: опис можна пропустити (тоді title = назва категорії)."""
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="⏭ Пропустити")],
        [KeyboardButton(text="🔙 Назад")]
    ], resize_keyboard=True)


def remove_kb() -> ReplyKeyboardRemove:
    return ReplyKeyboardRemove()
