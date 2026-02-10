import matplotlib
matplotlib.use('Agg') # <--- ВАЖЛИВО: Вимикає GUI, щоб не було помилок у потоках
import matplotlib.pyplot as plt
import io
import re

def generate_pie_chart(data_dict, title="Витрати"):
    """Малює діаграму з легендою збоку."""
    if not data_dict: return None

    clean_data = {}
    for cat, val in data_dict.items():
        clean_name = re.sub(r'[^\w\s]', '', cat).strip()
        if not clean_name: clean_name = cat
        clean_data[clean_name] = clean_data.get(clean_name, 0) + val

    total = sum(clean_data.values())
    labels = []
    sizes = []
    sorted_data = sorted(clean_data.items(), key=lambda x: x[1], reverse=True)

    other_sum = 0
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

    fig, ax = plt.subplots(figsize=(10, 6))
    cmap = plt.get_cmap("tab20")
    colors = cmap(range(len(sizes)))

    wedges, texts, autotexts = ax.pie(
        sizes, labels=None, autopct='%1.1f%%', startangle=140,
        colors=colors, pctdistance=0.85, wedgeprops=dict(width=0.5)
    )

    for autotext in autotexts:
        autotext.set_color('black')
        autotext.set_fontsize(9)
        try:
            if float(autotext.get_text().strip('%')) < 2: autotext.set_text('')
        except: pass

    legend_labels = []
    for cat, amount in zip(labels, sizes):
        percent = (amount / total) * 100
        legend_labels.append(f"{cat} — {amount:,.0f} грн ({percent:.1f}%)")

    ax.legend(wedges, legend_labels, title="Категорії", loc="center left", bbox_to_anchor=(1, 0, 0.5, 1))
    plt.title(title, fontsize=14, fontweight='bold')
    plt.tight_layout()

    buf = io.BytesIO()
    plt.savefig(buf, format='png', bbox_inches='tight')
    buf.seek(0)
    plt.close()
    return buf