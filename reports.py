from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib import colors
from reportlab.platypus import Paragraph
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
import matplotlib

matplotlib.use('Agg')
import io
import os
import re
import visuals

# Змінили на Montserrat!
FONT_FILE = 'Montserrat-Regular.ttf'
FONT_NAME = 'Montserrat'

try:
    if os.path.exists(FONT_FILE):
        pdfmetrics.registerFont(TTFont(FONT_NAME, FONT_FILE))
    else:
        FONT_NAME = 'Helvetica'
except:
    FONT_NAME = 'Helvetica'


# Емодзі та інші символи, яких немає в PDF-шрифті — прибираємо перед малюванням.
_EMOJI_RE = re.compile(
    "[\U0001F000-\U0001FAFF"
    "\U00002600-\U000027BF"
    "\U0001F1E6-\U0001F1FF"
    "\U00002B00-\U00002BFF"
    "\U0000FE00-\U0000FE0F"
    "\U00002190-\U000021FF"
    "\U00002300-\U000023FF]"
)


def clean_text(text):
    if not text: return ""
    # 1) прибираємо емодзі
    t = _EMOJI_RE.sub('', str(text))
    # 2) прибираємо все, що не буква/цифра/пробіл/пунктуація, але ЗБЕРІГАЄМО апостроф
    t = re.sub(r"[^\w\s,.\-']", '', t)
    return t.strip()


def draw_header(c, width, height, month_name, year):
    c.setFillColor(colors.HexColor("#2C3E50"))
    c.rect(0, height - 100, width, 100, stroke=0, fill=1)
    c.setFillColor(colors.white)
    c.setFont(FONT_NAME, 26)
    c.drawString(40, height - 50, f"Фінансовий звіт: {month_name} {year}")
    c.setFont(FONT_NAME, 10)
    c.drawRightString(width - 40, height - 50, "BimiPal Finance Bot")


def check_page_break(c, current_y, width, height, month_name, year, required_space=50):
    if current_y < required_space:
        c.showPage()
        draw_header(c, width, height, month_name, year)
        return height - 130
    return current_y


CURRENCY_SYMBOLS = {"UAH": "грн", "USD": "$", "EUR": "€"}


def _fmt_amt(amount, currency):
    sym = CURRENCY_SYMBOLS.get(currency, currency)
    return f"{amount:,.0f} {sym}"


def generate_monthly_report(data, month_name, year):
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4

    draw_header(c, width, height, month_name, year)

    # Керенки: data["currencies"] — {code: {income, expense, balance, grouped_categories}}
    currencies = data.get("currencies") or {"UAH": data}
    cur_codes = sorted(currencies.keys())

    y = height - 140
    card_width = 155
    card_height = 50
    gap = 20

    def draw_card(x, title, value, color_hex):
        c.setFillColor(colors.HexColor("#ECF0F1"))
        c.roundRect(x, y, card_width, card_height, 4, stroke=0, fill=1)
        c.setFillColor(colors.HexColor("#7F8C8D"))
        c.setFont(FONT_NAME, 9)
        c.drawString(x + 10, y + 30, title)
        c.setFillColor(colors.HexColor(color_hex))
        c.setFont(FONT_NAME, 14)
        c.drawString(x + 10, y + 10, value)

    # Перший рядок карток — головна валюта
    main_cur = cur_codes[0]
    main = currencies[main_cur]
    draw_card(40, f"ДОХІД ({main_cur})", _fmt_amt(main['income'], main_cur), "#27AE60")
    draw_card(40 + card_width + gap, f"ВИТРАТИ ({main_cur})", _fmt_amt(main['expense'], main_cur), "#C0392B")
    bal_color = "#2980B9" if main['balance'] >= 0 else "#C0392B"
    draw_card(40 + (card_width + gap) * 2, f"ЗАЛИШОК ({main_cur})", _fmt_amt(main['balance'], main_cur), bal_color)

    # Додаткові валюти — своїм рядком, щоб НЕ міксувати
    if len(cur_codes) > 1:
        y -= 60
        for cur in cur_codes[1:]:
            cdata = currencies[cur]
            draw_card(40, f"ДОХІД ({cur})", _fmt_amt(cdata['income'], cur), "#27AE60")
            draw_card(40 + card_width + gap, f"ВИТРАТИ ({cur})", _fmt_amt(cdata['expense'], cur), "#C0392B")
            bcol = "#2980B9" if cdata['balance'] >= 0 else "#C0392B"
            draw_card(40 + (card_width + gap) * 2, f"ЗАЛИШОК ({cur})", _fmt_amt(cdata['balance'], cur), bcol)
            y -= 60

    y -= 40

    styles = getSampleStyleSheet()
    desc_style = ParagraphStyle(
        'DescStyle',
        parent=styles['Normal'],
        fontName=FONT_NAME,
        fontSize=9,
        textColor=colors.black,
        leading=12
    )

    all_txs_for_later = []

    # ПЕРША ВАЛЮТА: діаграма + категорії (як раніше, з символом валюти)
    def render_currency_section(cur, cdata):
        nonlocal y
        chart_data = {cat['name']: cat['total'] for cat in cdata['grouped_categories']}
        if chart_data:
            chart_buf = visuals.generate_pie_chart(chart_data, title="")
            if chart_buf:
                from reportlab.lib.utils import ImageReader
                img = ImageReader(chart_buf)
                img_width = 450
                fig_height = max(6, len(chart_data) * 0.4)
                img_height = (img_width / 10) * fig_height
                if img_height > 400:
                    img_height = 400
                y = check_page_break(c, y, width, height, month_name, year, required_space=img_height + 20)
                y -= img_height
                c.drawImage(img, (width - img_width) / 2, y, width=img_width, height=img_height, mask='auto')
                y -= 30

        y = check_page_break(c, y, width, height, month_name, year, required_space=100)
        c.setFont(FONT_NAME, 14)
        c.setFillColor(colors.HexColor("#2C3E50"))
        c.drawString(40, y, f"📋 Деталізація витрат ({cur}) — ТОП-3 транзакції")
        y -= 25

        total_expense = cdata['expense'] if cdata['expense'] > 0 else 1

        for cat_data in cdata['grouped_categories']:
            y -= 10
            y = check_page_break(c, y, width, height, month_name, year, required_space=80)
            cat_name = clean_text(cat_data['name'])
            cat_sum = cat_data['total']
            pct = (cat_sum / total_expense) * 100

            c.setFillColor(colors.HexColor("#34495E"))
            c.rect(40, y, 515, 22, stroke=0, fill=1)
            c.setFillColor(colors.white)
            c.setFont(FONT_NAME, 11)
            c.drawString(45, y + 7, f" {cat_name}")
            c.drawRightString(545, y + 7, f"{_fmt_amt(cat_sum, cur)} ({pct:.1f}%)")
            y -= 15

            for tx in cat_data['txs']:
                tx_copy = tx.copy()
                tx_copy['cat_name'] = cat_name
                all_txs_for_later.append(tx_copy)

            for tx in cat_data['top_txs']:
                date = tx['date'][:-5]
                desc_text = clean_text(tx['desc'])
                if not desc_text:
                    desc_text = "Без опису"
                amt = _fmt_amt(tx['amount'], cur)
                who_raw = clean_text(tx['who'])
                who = who_raw[:10] if who_raw else "?"
                amount_text = f"{who} | {amt}"
                p = Paragraph(desc_text, desc_style)
                _, h = p.wrapOn(c, 360, 0)
                y = check_page_break(c, y, width, height, month_name, year, required_space=h + 25)
                c.setFillColor(colors.HexColor("#7F8C8D"))
                c.setFont(FONT_NAME, 9)
                c.drawString(45, y - 10, date)
                c.setFillColor(colors.black)
                c.drawRightString(545, y - 10, amount_text)
                p.drawOn(c, 85, y - h)
                y -= (h + 15)

    # Малюємо секції для КОЖНОЇ валюти окремо
    for cur in cur_codes:
        if cur != cur_codes[0]:
            y = check_page_break(c, y, width, height, month_name, year, required_space=140)
            y -= 40
        render_currency_section(cur, currencies[cur])

    # Хронологія: сортуємо всі транзакції, позначаємо валюту
    y = check_page_break(c, y, width, height, month_name, year, required_space=120)
    y -= 30
    c.setFont(FONT_NAME, 14)
    c.setFillColor(colors.HexColor("#2C3E50"))
    c.drawString(40, y, "📝 Всі транзакції за місяць (Хронологія)")
    y -= 25

    all_txs_sorted = sorted(all_txs_for_later, key=lambda x: int(x['date'][:2]))
    for tx in all_txs_sorted:
        date = tx['date'][:-5]
        desc_text = clean_text(tx['desc'])
        if not desc_text:
            desc_text = "Без опису"
        cat_tag = f"[{tx['cat_name'][:15]}] "
        cur = tx.get('currency') or "UAH"
        amt = _fmt_amt(tx['amount'], cur)
        who_raw = clean_text(tx['who'])
        who = who_raw[:10] if who_raw else "?"
        amount_text = f"{who} | {amt}"

        p = Paragraph(f"<b>{cat_tag}</b>{desc_text}", desc_style)
        _, h = p.wrapOn(c, 360, 0)
        y = check_page_break(c, y, width, height, month_name, year, required_space=h + 20)
        c.setFillColor(colors.HexColor("#7F8C8D"))
        c.setFont(FONT_NAME, 9)
        c.drawString(45, y - 10, date)
        c.setFillColor(colors.black)
        c.drawRightString(545, y - 10, amount_text)
        p.drawOn(c, 85, y - h)
        y -= (h + 10)

    c.save()
    buffer.seek(0)
    return buffer