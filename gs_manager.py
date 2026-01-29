import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
import re  # Додали бібліотеку для регулярних виразів
from config import SPREADSHEET_ID, SHEET_NAME


class GoogleSheetManager:
    def __init__(self):
        self.scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        self.creds_file = "service_account.json"
        self.authenticate()

    def authenticate(self):
        self.creds = ServiceAccountCredentials.from_json_keyfile_name(self.creds_file, self.scope)
        self.client = gspread.authorize(self.creds)

    def _clean_amount(self, amount_str):
        """
        Розумна очистка суми.
        Перетворює: " 10,00 грн. ", "1 500.50", "120 грн" -> на чистий float
        """
        if isinstance(amount_str, (int, float)):
            return float(amount_str)

        # Перетворюємо в рядок
        s = str(amount_str)

        # 1. Видаляємо все, що НЕ є цифрою, комою або крапкою (букви, пробіли, символи валют)
        # re.sub(r'[^\d,.]', '', s) залишить тільки цифри і роздільники
        s = re.sub(r'[^\d,.]', '', s)

        # 2. Замінюємо кому на крапку
        s = s.replace(',', '.')

        # 3. Видаляємо зайві крапки в кінці (якщо лишилися після 'грн.')
        s = s.rstrip('.')

        # 4. Пробуємо перетворити
        try:
            return float(s)
        except ValueError:
            return 0.0

    def add_transaction(self, date, category, amount, t_type, item_name, note, who):
        try:
            sheet = self.client.open_by_key(SPREADSHEET_ID).worksheet(SHEET_NAME)
            row = [date, category, amount, t_type, item_name, note, who]
            sheet.insert_row(row, 3)
            return True
        except Exception as e:
            print(f"🔴 Error adding: {e}")
            try:
                self.authenticate()
                sheet = self.client.open_by_key(SPREADSHEET_ID).worksheet(SHEET_NAME)
                sheet.insert_row(row, 3)
                return True
            except:
                return False

    def get_month_stats(self):
        """Рахує статистику за ПОТОЧНИЙ місяць"""
        try:
            sheet = self.client.open_by_key(SPREADSHEET_ID).worksheet(SHEET_NAME)
            all_values = sheet.get_all_values()

            # Пропускаємо перші 2 рядки (заголовки і інпут)
            if len(all_values) > 2:
                data_rows = all_values[2:]
            else:
                return None  # Таблиця порожня

            now = datetime.now()
            current_month = now.month
            current_year = now.year

            income = 0.0
            expense = 0.0
            categories = {}

            for row in data_rows:
                # Перевірка на цілісність рядка (мінімум 4 стовпці: Дата, Кат, Сума, Тип)
                if not row or len(row) < 4 or not row[0]:
                    continue

                try:
                    # Пробуємо дату
                    t_date = datetime.strptime(row[0], "%d.%m.%Y")
                except ValueError:
                    continue  # Пропускаємо рядки з кривою датою

                # Якщо поточний місяць
                if t_date.month == current_month and t_date.year == current_year:
                    amount = self._clean_amount(row[2])  # Парсимо суму
                    t_type = row[3].strip()

                    # Враховуємо "Доходи" і "Поповнення"
                    if t_type in ["Поповнення", "Дохід", "Доходи"]:
                        income += amount
                    else:
                        expense += amount
                        cat = row[1]
                        categories[cat] = categories.get(cat, 0) + amount

            top_cats = sorted(categories.items(), key=lambda x: x[1], reverse=True)[:3]

            return {
                "income": income,
                "expense": expense,
                "balance": income - expense,
                "top_cats": top_cats,
                "month_name": now.strftime("%B")
            }

        except Exception as e:
            print(f"🔴 Error stats: {e}")
            return None