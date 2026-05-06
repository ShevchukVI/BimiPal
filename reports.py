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


def clean_text(text):
    if not text: return ""
    return re.sub(r'[^\w\s,.-]', '', str(text)).strip()


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


def generate_monthly_report(data, month_name, year):
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4

    draw_header(c, width, height, month_name, year)

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

    draw_card(40, "ЗАГАЛЬНИЙ ДОХІД", f"{data['income']:,.0f} грн", "#27AE60")
    draw_card(40 + card_width + gap, "ЗАГАЛЬНІ ВИТРАТИ", f"{data['expense']:,.0f} грн", "#C0392B")
    bal_color = "#2980B9" if data['balance'] >= 0 else "#C0392B"
    draw_card(40 + (card_width + gap) * 2, "ЗАЛИШОК (Net)", f"{data['balance']:,.0f} грн", bal_color)

    y -= 40

    # Генеруємо та малюємо гістограму
    chart_data = {cat['name']: cat['total'] for cat in data['grouped_categories']}
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
    c.drawString(40, y, "📋 Деталізація витрат (ТОП-3 транзакції)")
    y -= 25

    total_expense = data['expense'] if data['expense'] > 0 else 1

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

    # 1. Секція ТОП-3 по категоріях
    for cat_data in data['grouped_categories']:
        y -= 10  # Відступ перед новою категорією
        y = check_page_break(c, y, width, height, month_name, year, required_space=80)

        cat_name = clean_text(cat_data['name'])
        cat_sum = cat_data['total']
        pct = (cat_sum / total_expense) * 100

        # Малюємо прямокутник категорії
        c.setFillColor(colors.HexColor("#34495E"))
        c.rect(40, y, 515, 22, stroke=0, fill=1)
        c.setFillColor(colors.white)
        c.setFont(FONT_NAME, 11)
        # Центруємо текст всередині 22px прямокутника (y + 7)
        c.drawString(45, y + 7, f" {cat_name}")
        c.drawRightString(545, y + 7, f"{cat_sum:,.0f} грн ({pct:.1f}%)")
        y -= 15  # Відступ після прямокутника

        for tx in cat_data['txs']:
            # Збираємо всі транзакції для фінального списку
            tx_copy = tx.copy()
            tx_copy['cat_name'] = cat_name
            all_txs_for_later.append(tx_copy)

        for tx in cat_data['top_txs']:
            date = tx['date'][:-5]
            desc_text = clean_text(tx['desc'])
            if not desc_text: desc_text = "Без опису"

            amt = f"{tx['amount']:,.0f} грн"
            who_raw = clean_text(tx['who'])
            who = who_raw[:10] if who_raw else "?"
            amount_text = f"{who} | {amt}"

            p = Paragraph(desc_text, desc_style)
            w, h = p.wrapOn(c, 360, 0)

            y = check_page_break(c, y, width, height, month_name, year, required_space=h + 25)

            c.setFillColor(colors.HexColor("#7F8C8D"))
            c.setFont(FONT_NAME, 9)
            c.drawString(45, y - 10, date)

            c.setFillColor(colors.black)
            c.drawRightString(545, y - 10, amount_text)

            p.drawOn(c, 85, y - h)
            y -= (h + 15)  # Більший відступ після кожної транзакції

    # 2. Секція "Всі транзакції хронологічно"
    y = check_page_break(c, y, width, height, month_name, year, required_space=120)
    y -= 30
    c.setFont(FONT_NAME, 14)
    c.setFillColor(colors.HexColor("#2C3E50"))
    c.drawString(40, y, "📝 Всі транзакції за місяць (Хронологія)")
    y -= 25

    # Сортуємо транзакції за днем (перші 2 символи дати)
    all_txs_sorted = sorted(all_txs_for_later, key=lambda x: int(x['date'][:2]))

    for tx in all_txs_sorted:
        date = tx['date'][:-5]
        desc_text = clean_text(tx['desc'])
        if not desc_text: desc_text = "Без опису"
        cat_tag = f"[{tx['cat_name'][:15]}] "

        amt = f"{tx['amount']:,.0f} грн"
        who_raw = clean_text(tx['who'])
        who = who_raw[:10] if who_raw else "?"
        amount_text = f"{who} | {amt}"

        # Об'єднуємо категорію та опис
        p = Paragraph(f"<b>{cat_tag}</b>{desc_text}", desc_style)
        w, h = p.wrapOn(c, 360, 0)

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