# tests/test_quick_add_parser.py
# Regression-тести для parse_quick_add (Zero Friction «150 кава»).
# Запуск: pip install pytest && python -m pytest tests/ -q
#
# IMPORTANT: цей файл тримає САМОСТІЙНУ копію парсера, щоб тести працювали без
# залежностей aiogram. Якщо parse_quick_add змінюється в handlers/quick_add.py —
# синхронізуй сюди (або рефактори на спільний модуль у майбутньому).
import re

import pytest

CURRENCY_WORDS = {
    "грн": "UAH", "гривень": "UAH", "гривні": "UAH", "гривня": "UAH",
    "гривням": "UAH", "гривнею": "UAH", "гривен": "UAH", "uah": "UAH", "₴": "UAH",
    "usd": "USD", "дол": "USD", "долар": "USD", "долара": "USD", "$": "USD",
    "eur": "EUR", "євро": "EUR", "евро": "EUR", "€": "EUR",
}
UNIT_WORDS = {"г", "грам", "грамм", "кг", "мл", "л", "літр", "літри", "літрів", "см", "м",
              "метр", "метри", "шт", "штук", "штуки", "уп", "упаковка", "пачка", "пачки",
              "хв", "хвилин", "км", "сек"}
CASH_WORDS = {"готівка", "готівкою", "кеш", "кешем", "cash", "нал", "наличка"}

_NUM_RE = re.compile(r'^([+-]?)(\d+(?:[.,]\d{1,2})?)$')
_THOUSAND_RE = re.compile(r'^\d{3}$')


def _clean_word(tok: str) -> str:
    return tok.lower().strip('.,!?')


def parse_quick_add(text: str):
    tokens = text.split()
    if not tokens:
        return None

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

    cash_idx = {i for i, t in enumerate(tokens) if _clean_word(t) in CASH_WORDS}

    strong, weak = [], []
    for i, tok in enumerate(tokens):
        m = _NUM_RE.match(tok)
        if not m:
            continue
        nxt = _clean_word(tokens[i + 1]) if i + 1 < len(tokens) else ""
        if nxt in UNIT_WORDS:
            continue
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
        return None

    idx, sign, amount = chosen
    if amount <= 0 or amount > 10_000_000:
        return None

    skip = {idx} | cash_idx
    if idx + 1 < len(tokens) and _clean_word(tokens[idx + 1]) in CURRENCY_WORDS:
        skip.add(idx + 1)
    if idx - 1 >= 0 and _clean_word(tokens[idx - 1]) == "за":
        skip.add(idx - 1)
    title = " ".join(t for i, t in enumerate(tokens) if i not in skip).strip(' ,.-—')

    currency = "UAH"
    if idx + 1 < len(tokens):
        nxt = _clean_word(tokens[idx + 1])
        if nxt in CURRENCY_WORDS:
            currency = CURRENCY_WORDS[nxt]

    return {
        "amount": amount,
        "title": title,
        "t_type": "Поповнення" if sign == "+" else "Витрати",
        "account": "Готівка",
        "currency": currency,
    }


POSITIVE_CASES = [
    ("50 кава", 50.0, "кава", "Витрати"),
    ("50 грн кава", 50.0, "кава", "Витрати"),
    ("кава 50 грн", 50.0, "кава", "Витрати"),
    ("газ 800 грн", 800.0, "газ", "Витрати"),
    ("800 грн газ", 800.0, "газ", "Витрати"),
    ("150 гривень кава", 150.0, "кава", "Витрати"),
    ("кава за 150", 150.0, "кава", "Витрати"),
    ("купив каву за 150", 150.0, "купив каву", "Витрати"),
    ("+5000 зп", 5000.0, "зп", "Поповнення"),
    ("зп +5000", 5000.0, "зп", "Поповнення"),
    ("250 кава готівкою", 250.0, "кава", "Витрати"),
    ("100 000 зп", 100000.0, "зп", "Витрати"),
    ("+100 000 зп", 100000.0, "зп", "Поповнення"),
]

NEGATIVE_CASES = [
    "цибуля 200 г, морква 500 г",
    "2 піци і 3 соку",
    "привіт",
    "500 г борошна",
    "3 кг м'яса",
    "",
]


@pytest.mark.parametrize("text,amount,title,ttype", POSITIVE_CASES)
def test_positive(text, amount, title, ttype):
    r = parse_quick_add(text)
    assert r is not None, f"should parse: {text!r}"
    assert abs(r["amount"] - amount) < 0.01
    assert r["title"] == title
    assert r["t_type"] == ttype


CURRENCY_CASES = [
    ("150 таксі", "UAH"),
    ("150 грн кава", "UAH"),
    ("150 usd кава", "USD"),
    ("100 $ таксі", "USD"),
    ("кава за 50 €", "EUR"),
    ("5000 гривень зп", "UAH"),
    ("200 дол", "USD"),
    ("50 євро кава", "EUR"),
]


@pytest.mark.parametrize("text,currency", CURRENCY_CASES)
def test_currency_detection(text, currency):
    r = parse_quick_add(text)
    assert r is not None, f"should parse: {text!r}"
    assert r["currency"] == currency, f"{text!r}: got {r['currency']}, expected {currency}"


@pytest.mark.parametrize("text", NEGATIVE_CASES)
def test_negative(text):
    assert parse_quick_add(text) is None, f"should NOT parse: {text!r}"
