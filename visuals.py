import matplotlib

matplotlib.use('Agg')  # <--- ВАЖЛИВО: Вимикає GUI, щоб не було помилок у потоках
import matplotlib.pyplot as plt
import io
import re


def generate_pie_chart(data_dict, title="Витрати"):
    if not data_dict: return None

    clean_data = {}
    for cat, val in data_dict.items():
        clean_name = re.sub(r'[^\w\s]', '', cat).strip()
        if not clean_name: clean_name = cat
        clean_data[clean_name] = clean_data.get(clean_name, 0) + val

    total = sum(clean_data.values())
    if total == 0: return None

    sorted_data = sorted(clean_data.items(), key=lambda x: x[1])

    labels = [item[0] for item in sorted_data]
    sizes = [item[1] for item in sorted_data]

    fig_height = max(6, len(labels) * 0.4)
    fig, ax = plt.subplots(figsize=(10, fig_height))

    # Додаємо жорсткий відступ зліва для довгих назв категорій
    plt.subplots_adjust(left=0.25, right=0.95)

    bars = ax.barh(labels, sizes, color='#3498DB', edgecolor='none')

    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.spines['bottom'].set_visible(False)
    ax.xaxis.set_visible(False)

    for bar in bars:
        width = bar.get_width()
        percentage = (width / total) * 100
        label_text = f" {width:,.0f} грн ({percentage:.1f}%)"
        ax.text(width, bar.get_y() + bar.get_height() / 2, label_text,
                va='center', ha='left', fontsize=10, color='#2C3E50', fontweight='bold')

    plt.title(title, fontsize=14, fontweight='bold', color='#2C3E50', pad=20)

    buf = io.BytesIO()
    plt.savefig(buf, format='png', bbox_inches='tight', transparent=True)
    buf.seek(0)
    plt.close()

    return buf