import matplotlib.pyplot as plt
import io
import re


def generate_pie_chart(data_dict, title="Витрати"):
    """
    Малює діаграму з легендою збоку, щоб не було налізання тексту.
    """
    if not data_dict:
        return None

    # 1. Очистка назв від емодзі (лишаємо текст)
    clean_data = {}
    for cat, val in data_dict.items():
        # Видаляємо спецсимволи, лишаємо букви, цифри, пробіли
        clean_name = re.sub(r'[^\w\s]', '', cat).strip()
        # Якщо після очистки порожньо (був тільки смайлик), повертаємо оригінал
        if not clean_name: clean_name = cat
        clean_data[clean_name] = clean_data.get(clean_name, 0) + val

    # 2. Сортування та групування "Іншого"
    total = sum(clean_data.values())
    labels = []
    sizes = []

    # Сортуємо від найбільшого
    sorted_data = sorted(clean_data.items(), key=lambda x: x[1], reverse=True)

    other_sum = 0
    # Якщо категорій більше 9, хвіст кидаємо в "Інше"
    limit_items = 9

    for i, (cat, amount) in enumerate(sorted_data):
        if i < limit_items:
            labels.append(cat)
            sizes.append(amount)
        else:
            other_sum += amount

    if other_sum > 0:
        labels.append("Інше")
        sizes.append(other_sum)

    # 3. Налаштування графіку
    # Робимо картинку широкою, щоб влізла легенда збоку (10x6 дюймів)
    fig, ax = plt.subplots(figsize=(10, 6))

    # Використовуємо палітру кольорів 'tab20' (там багато контрастних кольорів)
    cmap = plt.get_cmap("tab20")
    colors = cmap(range(len(sizes)))

    # Малюємо пиріг
    wedges, texts, autotexts = ax.pie(
        sizes,
        labels=None,  # Вимикаємо підписи на самому колі
        autopct='%1.1f%%',
        startangle=140,
        colors=colors,
        pctdistance=0.85,  # Відсотки ближче до краю
        wedgeprops=dict(width=0.5)  # Робимо "пончик" (так сучасніше)
    )

    # Налаштовуємо текст відсотків
    for autotext in autotexts:
        autotext.set_color('black')
        autotext.set_fontsize(9)
        # Якщо шматочок дуже малий (<2%), ховаємо відсоток на графіку
        try:
            val = float(autotext.get_text().strip('%'))
            if val < 2:
                autotext.set_text('')
        except:
            pass

    # 4. Створюємо красиву легенду збоку
    # Формат: "Категорія - 1200 грн (25.5%)"
    legend_labels = []
    for cat, amount in zip(labels, sizes):
        percent = (amount / total) * 100
        legend_labels.append(f"{cat} — {amount:,.0f} грн ({percent:.1f}%)")

    # Додаємо легенду праворуч
    ax.legend(
        wedges,
        legend_labels,
        title="Категорії",
        loc="center left",
        bbox_to_anchor=(1, 0, 0.5, 1)  # Виносимо легенду за межі кола вправо
    )

    plt.title(title, fontsize=14, fontweight='bold')
    plt.tight_layout()  # Автоматично підганяє розміри, щоб нічого не обрізало

    # Зберігаємо
    buf = io.BytesIO()
    plt.savefig(buf, format='png', bbox_inches='tight')  # bbox_inches='tight' обрізає зайві білі поля
    buf.seek(0)
    plt.close()

    return buf