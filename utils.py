# utils.py — дрібні спільні хелпери бота.
from html import escape as _html_escape


def esc(s) -> str:
    """Екранування user-provided тексту для Telegram HTML parse_mode.
    Екранує лише &, <, > (quote=False — апострофи/лапки лишаються як є).
    Використовувати для ВСІХ даних від користувача/банку (імена, назви, описи),
    які вставляються в HTML-повідомлення."""
    return _html_escape(str(s), quote=False)


def fmt_amount(value: float) -> str:
    """1 234.50 ₴ — форматування сум з пробілом як роздільником тисяч."""
    return f"{value:,.2f}".replace(",", " ")
