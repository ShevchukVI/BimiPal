import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
import re
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
        if isinstance(amount_str, (int, float)):
            return float(amount_str)
        s = str(amount_str)
        s = re.sub(r'[^\d,.]', '', s)
        s = s.replace(',', '.')
        s = s.rstrip('.')
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
        try:
            sheet = self.client.open_by_key(SPREADSHEET_ID).worksheet(SHEET_NAME)
            all_values = sheet.get_all_values()

            if len(all_values) > 2:
                data_rows = all_values[2:]
            else:
                return None

            now = datetime.now()
            current_month = now.month
            current_year = now.year

            income = 0.0
            expense = 0.0
            categories = {}

            for row in data_rows:
                if not row or len(row) < 4 or not row[0]: continue
                try:
                    t_date = datetime.strptime(row[0], "%d.%m.%Y")
                except ValueError:
                    continue

                if t_date.month == current_month and t_date.year == current_year:
                    amount = self._clean_amount(row[2])
                    t_type = row[3].strip()
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

    def undo_last_transaction(self):
        """Видаляє останній доданий рядок (це завжди рядок №3)"""
        try:
            sheet = self.client.open_by_key(SPREADSHEET_ID).worksheet(SHEET_NAME)

            # Отримуємо дані рядка, щоб показати юзеру, що видалили
            # Рядок 3 (в gspread індексація з 1)
            row_values = sheet.row_values(3)

            # Перевірка: чи не видаляємо ми заголовок (якщо таблиця порожня)
            if not row_values or row_values[0] == "Дата":
                return None

            # Видаляємо рядок 3
            sheet.delete_rows(3)

            # Повертаємо інфу про те, що видалили
            return {
                "date": row_values[0],
                "category": row_values[1],
                "amount": row_values[2],
                "desc": row_values[4] if len(row_values) > 4 else ""
            }
        except Exception as e:
            print(f"🔴 Error undo: {e}")
            return None