from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib import colors
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import io
import re
import os

# --- НАЛАШТУВАННЯ ШРИФТІВ ---
FONT_FILE = 'arial.ttf'
FONT_NAME = 'Arial'

# 1. Реєструємо шрифт для PDF
try:
    if os.path.exists(FONT_FILE):
        pdfmetrics.registerFont(TTFont(FONT_NAME, FONT_FILE))
    else:
        FONT_NAME = 'Helvetica'
except:
    FONT_NAME = 'Helvetica'

# 2. Реєструємо шрифт для Діаграм
try:
    if os.path.exists(FONT_FILE):
        fm.fontManager.addfont(FONT_FILE)
        plt.rcParams['font.family'] = FONT_NAME
except:
    pass


def clean_text(text):
    """Видаляє емодзі та спецсимволи (лишає букви, цифри, пунктуацію)."""
    if not text: return ""
    # Дозволяємо букви, цифри, пробіли, базові знаки. Все інше (емодзі) - видаляємо.
    return re.sub(r'[^\w\s,.-]', '', str(text)).strip()


def draw_header(c, width, height, month_name, year):
    # Темно-синій банер
    c.setFillColor(colors.HexColor("#2C3E50"))
    c.rect(0, height - 120, width, 120, stroke=0, fill=1)

    # Заголовок
    c.setFillColor(colors.white)
    c.setFont(FONT_NAME, 30)
    c.drawString(50, height - 60, "Фінансовий звіт")

    # Підзаголовок (Дата)
    c.setFont(FONT_NAME, 18)
    c.setFillColor(colors.HexColor("#BDC3C7"))
    c.drawString(50, height - 90, f"{month_name} {year}")

    # Лого
    c.setFont(FONT_NAME, 10)
    c.drawRightString(width - 50, height - 60, "BimiPal Finance Bot 🤖")


def generate_monthly_report(data, month_name, year):
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4

    draw_header(c, width, height, month_name, year)

    # --- БЛОК 1: КАРТКИ (Summary) ---
    y_cards = height - 190
    card_width = 155
    card_height = 60
    gap = 20

    def draw_card(x, title, value, color_hex):
        c.setFillColor(colors.HexColor("#ECF0F1"))
        c.roundRect(x, y_cards, card_width, card_height, 6, stroke=0, fill=1)
        c.setFillColor(colors.HexColor("#7F8C8D"))
        c.setFont(FONT_NAME, 9)
        c.drawString(x + 15, y_cards + 35, title)
        c.setFillColor(colors.HexColor(color_hex))
        c.setFont(FONT_NAME, 16)
        c.drawString(x + 15, y_cards + 15, value)

    draw_card(50, "ЗАГАЛЬНИЙ ДОХІД", f"{data['income']:,.0f} грн", "#27AE60")
    draw_card(50 + card_width + gap, "ЗАГАЛЬНІ ВИТРАТИ", f"{data['expense']:,.0f} грн", "#C0392B")

    bal_color = "#2980B9" if data['balance'] >= 0 else "#C0392B"
    draw_card(50 + (card_width + gap) * 2, "ЗАЛИШОК (Net)", f"{data['balance']:,.0f} грн", bal_color)

    # --- БЛОК 2: ДІАГРАМА (Круглий Donut Chart) ---
    if data['categories']:
        sorted_cats = sorted(data['categories'].items(), key=lambda x: x[1], reverse=True)

        # Чистимо назви категорій
        labels = [clean_text(k) for k, v in sorted_cats[:6]]
        sizes = [v for k, v in sorted_cats[:6]]

        others = sum([v for k, v in sorted_cats[6:]])
        if others > 0:
            labels.append("Інше")
            sizes.append(others)

        # ВИПРАВЛЕНО: Квадратна фігура (6x6 дюймів)
        fig, ax = plt.subplots(figsize=(6, 6))

        wedges, texts, autotexts = ax.pie(
            sizes, labels=labels, autopct='%1.1f%%',
            startangle=90, pctdistance=0.85,
            textprops={'fontsize': 10}
        )

        centre_circle = plt.Circle((0, 0), 0.70, fc='white')
        fig.gca().add_artist(centre_circle)

        ax.axis('equal')
        plt.title(f"Структура витрат", fontsize=14, pad=20)

        img_buf = io.BytesIO()
        plt.savefig(img_buf, format='png', bbox_inches='tight', transparent=True)
        plt.close()
        img_buf.seek(0)

        from reportlab.lib.utils import ImageReader
        img = ImageReader(img_buf)

        # ВИПРАВЛЕНО: Вставляємо в КВАДРАТНУ область (350x350), щоб не плющило
        # Центруємо по горизонталі: (width - 350) / 2 = (595 - 350) / 2 ≈ 122
        c.drawImage(img, 122, height - 560, width=350, height=350, mask='auto')

    # --- БЛОК 3: ТАБЛИЦЯ (Зебра) ---
    y_table = height - 580
    c.setFont(FONT_NAME, 14)
    c.setFillColor(colors.HexColor("#2C3E50"))
    c.drawString(50, y_table, "🏆 ТОП-10 Витрат")

    y_table -= 30

    # Заголовок
    c.setFillColor(colors.HexColor("#BDC3C7"))
    c.rect(50, y_table - 5, 495, 20, stroke=0, fill=1)

    c.setFillColor(colors.black)
    c.setFont(FONT_NAME, 9)
    c.drawString(60, y_table, "ДАТА")
    c.drawString(110, y_table, "КАТЕГОРІЯ")
    c.drawString(230, y_table, "ОПИС")
    c.drawString(430, y_table, "СУМА")
    c.drawString(500, y_table, "ХТО")

    y_table -= 20

    for i, item in enumerate(data['top_10']):
        if item['type'] not in ["Витрати", "Витрата"]: continue

        if i % 2 == 0:
            c.setFillColor(colors.HexColor("#F9F9F9"))
            c.rect(50, y_table - 5, 495, 15, stroke=0, fill=1)

        c.setFillColor(colors.black)

        date = item['date'][:-5]
        cat = clean_text(item['cat'])[:20]
        desc = clean_text(item['desc'])
        desc = desc[:35] + "..." if len(desc) > 35 else desc
        amt = f"-{item['amount']:,.0f}"

        # ВИПРАВЛЕНО: Прибрав [:3], тепер пише повне ім'я (або до 10 символів про всяк випадок)
        who = clean_text(item['who'])[:10]

        c.drawString(60, y_table, date)
        c.drawString(110, y_table, cat)
        c.drawString(230, y_table, desc)
        c.drawString(430, y_table, amt)
        c.drawString(500, y_table, who)

        y_table -= 15
        if y_table < 50: break

    c.save()
    buffer.seek(0)
    return buffer