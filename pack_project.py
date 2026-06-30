import os

# Список файлів, які ми хочемо "годувати" моделі
files_to_pack = [
    'main.py',
    'gs_manager.py',
    'reports.py',
    'visuals.py',
    'config.py'
]

output_file = 'project_context.txt'

with open(output_file, 'w', encoding='utf-8') as outfile:
    outfile.write("Ось повний код мого проєкту BimiPal. Враховуй структуру та логіку при наданні порад.\n\n")
    
    for filename in files_to_pack:
        if os.path.exists(filename):
            outfile.write(f"\n{'='*20}\nFILE: {filename}\n{'='*20}\n\n")
            with open(filename, 'r', encoding='utf-8') as infile:
                outfile.write(infile.read())
                outfile.write("\n")
        else:
            print(f"Файл {filename} не знайдено, пропускаємо.")

print(f"✅ Готово! Весь код зібрано у файл {output_file}")