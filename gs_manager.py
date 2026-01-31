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
        """
        Перетворює будь-яке сміття з таблиці (2 600,00 грн, 1.000$, тощо) у чистий float.
        """
        if isinstance(amount_str, (int, float)):
            return float(amount_str)

        # 1. Конвертуємо в рядок
        s = str(amount_str)

        # 2. Видаляємо нерозривні пробіли (\xa0) і звичайні пробіли
        # Це головна причина помилок у Google Sheets
        s = s.replace('\xa0', '').replace(' ', '')

        # 3. Видаляємо все, крім цифр, коми, крапки і мінуса
        s = re.sub(r'[^\d,.-]', '', s)

        # 4. Логіка роздільників
        # Якщо є і крапка і кома (напр. 1.000,50) -> видаляємо крапку (як роздільник тисяч)
        if '.' in s and ',' in s:
            s = s.replace('.', '')

        # 5. Міняємо кому на крапку (для Python)
        s = s.replace(',', '.')

        try:
            return float(s)
        except ValueError:
            # Якщо все ще не вийшло - повертаємо 0, але пишемо в лог
            # print(f"🔴 Failed clean: {amount_str} -> {s}")
            return 0.0

    # --- CATEGORIES ---
    def get_categories(self):
        try:
            sheet = self.client.open_by_key(SPREADSHEET_ID).worksheet("Налаштування")
            exp_raw = sheet.col_values(1)
            inc_raw = sheet.col_values(2)
            expense_cats = [x for x in exp_raw[1:] if x.strip()]
            income_cats = [x for x in inc_raw[1:] if x.strip()]
            if not expense_cats: expense_cats = ["Інше"]
            if not income_cats: income_cats = ["Дохід"]
            return expense_cats, income_cats
        except Exception as e:
            print(f"🔴 Error reading categories: {e}")
            return (["🛒 Продукти", "🏠 Оренда"], ["💰 Дохід"])

    # --- MAIN TRANSACTIONS ---
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

    def undo_last_transaction(self):
        try:
            sheet = self.client.open_by_key(SPREADSHEET_ID).worksheet(SHEET_NAME)
            row_values = sheet.row_values(3)
            if not row_values or row_values[0] == "Дата": return None
            sheet.delete_rows(3)
            return {"date": row_values[0], "category": row_values[1], "amount": row_values[2],
                    "desc": row_values[4] if len(row_values) > 4 else ""}
        except:
            return None

    # --- STATS ---
    def get_month_stats(self):
        try:
            sheet = self.client.open_by_key(SPREADSHEET_ID).worksheet(SHEET_NAME)
            all_values = sheet.get_all_values()
            if len(all_values) > 2:
                data_rows = all_values[2:]
            else:
                return None

            now = datetime.now()
            month_income = 0.0
            month_expense = 0.0
            total_wallet = 0.0
            month_categories = {}

            for row in data_rows:
                if not row or len(row) < 4 or not row[0]: continue
                try:
                    amount = self._clean_amount(row[2])
                    t_type = row[3].strip()
                    t_date = datetime.strptime(row[0], "%d.%m.%Y")

                    if t_type in ["Поповнення", "Дохід", "Доходи"]:
                        total_wallet += amount
                    else:
                        total_wallet -= amount

                    if t_date.month == now.month and t_date.year == now.year:
                        if t_type in ["Поповнення", "Дохід", "Доходи"]:
                            month_income += amount
                        else:
                            month_expense += amount
                            cat = row[1]
                            month_categories[cat] = month_categories.get(cat, 0) + amount
                except ValueError:
                    continue

            top_cats = sorted(month_categories.items(), key=lambda x: x[1], reverse=True)[:3]
            MONTHS_UA = {1: "Січень", 2: "Лютий", 3: "Березень", 4: "Квітень", 5: "Травень", 6: "Червень", 7: "Липень",
                         8: "Серпень", 9: "Вересень", 10: "Жовтень", 11: "Листопад", 12: "Грудень"}

            usd_balance = self.get_currency_balance()

            return {
                "income": month_income,
                "expense": month_expense,
                "balance": month_income - month_expense,
                "total_wallet": total_wallet,
                "usd_wallet": usd_balance,
                "top_cats": top_cats,
                "month_name": MONTHS_UA.get(now.month, "Цей місяць"),
                "categories_dict": month_categories
            }
        except Exception as e:
            print(f"🔴 Error stats: {e}")
            return None

    def get_week_stats(self):
        try:
            sheet = self.client.open_by_key(SPREADSHEET_ID).worksheet(SHEET_NAME)
            all_values = sheet.get_all_values()
            if len(all_values) <= 2: return None
            data_rows = all_values[2:]
            now = datetime.now()
            income = 0.0
            expense = 0.0
            categories = {}
            for row in data_rows:
                if not row or len(row) < 4 or not row[0]: continue
                try:
                    t_date = datetime.strptime(row[0], "%d.%m.%Y")
                except ValueError:
                    continue
                if 0 <= (now - t_date).days <= 7:
                    amount = self._clean_amount(row[2])
                    if row[3].strip() in ["Поповнення", "Дохід", "Доходи"]:
                        income += amount
                    else:
                        expense += amount
                        categories[row[1]] = categories.get(row[1], 0) + amount
            return {"income": income, "expense": expense,
                    "top_cats": sorted(categories.items(), key=lambda x: x[1], reverse=True)[:5]}
        except:
            return None

    # --- CURRENCY ---
    def add_currency_transaction(self, date, operation, amount_usd, rate, amount_uah, note):
        try:
            sheet = self.client.open_by_key(SPREADSHEET_ID).worksheet("Валюта")
            row = [date, operation, amount_usd, rate, amount_uah, note]
            sheet.append_row(row)
            return True
        except Exception as e:
            print(f"🔴 Error currency add: {e}")
            return False

    def get_currency_balance(self):
        try:
            sheet = self.client.open_by_key(SPREADSHEET_ID).worksheet("Валюта")
            col_usd = sheet.col_values(3)  # 3-й стовпчик
            total = 0.0
            for val in col_usd[1:]:
                total += self._clean_amount(val)
            return total
        except:
            return 0.0

    # --- LIMITS ---
    def get_budget_limits(self):
        try:
            sheet = self.client.open_by_key(SPREADSHEET_ID).worksheet("Планування")
            data = sheet.get_all_values()
            limits = {}
            for row in data[1:]:
                if len(row) >= 2 and row[0] and self._clean_amount(row[1]) > 0:
                    limits[row[0].strip()] = self._clean_amount(row[1])
            return limits
        except:
            return {}

    def update_budget_limit(self, category, new_amount):
        try:
            sheet = self.client.open_by_key(SPREADSHEET_ID).worksheet("Планування")
            try:
                cell = sheet.find(category)
                sheet.update_cell(cell.row, cell.col + 1, new_amount)
            except:
                sheet.append_row([category, new_amount])
            return True
        except:
            return False