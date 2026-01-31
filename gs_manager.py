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

    def get_categories(self):
        """
        Зчитує списки категорій з аркуша 'Налаштування'.
        Повертає два списки: (expense_cats, income_cats)
        """
        try:
            sheet = self.client.open_by_key(SPREADSHEET_ID).worksheet("Налаштування")
            # col_values(1) - це стовпчик A (Витрати), col_values(2) - B (Доходи)
            exp_raw = sheet.col_values(1)
            inc_raw = sheet.col_values(2)

            # Прибираємо заголовки (перший рядок) і пусті клітинки
            # Якщо список порожній, повертаємо дефолтні
            expense_cats = [x for x in exp_raw[1:] if x.strip()]
            income_cats = [x for x in inc_raw[1:] if x.strip()]

            if not expense_cats: expense_cats = ["Інше"]
            if not income_cats: income_cats = ["Дохід"]

            return expense_cats, income_cats
        except Exception as e:
            print(f"🔴 Error reading categories: {e}")
            # Аварійний набір, якщо таблиця недоступна або аркуша немає
            return (["🛒 Продукти", "🏠 Оренда", "Інше"], ["💰 Дохід"])

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

            month_income = 0.0
            month_expense = 0.0
            total_wallet = 0.0  # Глобальний баланс
            month_categories = {}

            for row in data_rows:
                if not row or len(row) < 4 or not row[0]: continue
                try:
                    amount = self._clean_amount(row[2])
                    t_type = row[3].strip()
                    t_date = datetime.strptime(row[0], "%d.%m.%Y")

                    # --- ГЛОБАЛЬНИЙ БАЛАНС ---
                    if t_type in ["Поповнення", "Дохід", "Доходи"]:
                        total_wallet += amount
                    else:
                        total_wallet -= amount

                    # --- СТАТИСТИКА МІСЯЦЯ ---
                    if t_date.month == current_month and t_date.year == current_year:
                        if t_type in ["Поповнення", "Дохід", "Доходи"]:
                            month_income += amount
                        else:
                            month_expense += amount
                            cat = row[1]
                            month_categories[cat] = month_categories.get(cat, 0) + amount

                except ValueError:
                    continue

            top_cats = sorted(month_categories.items(), key=lambda x: x[1], reverse=True)[:3]

            MONTHS_UA = {
                1: "Січень", 2: "Лютий", 3: "Березень", 4: "Квітень",
                5: "Травень", 6: "Червень", 7: "Липень", 8: "Серпень",
                9: "Вересень", 10: "Жовтень", 11: "Листопад", 12: "Грудень"
            }

            return {
                "income": month_income,
                "expense": month_expense,
                "balance": month_income - month_expense,
                "total_wallet": total_wallet,  # <--- Нове поле
                "top_cats": top_cats,
                "month_name": MONTHS_UA.get(current_month, "Цей місяць"),
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
                delta = now - t_date
                if 0 <= delta.days <= 7:
                    amount = self._clean_amount(row[2])
                    t_type = row[3].strip()
                    if t_type in ["Поповнення", "Дохід", "Доходи"]:
                        income += amount
                    else:
                        expense += amount
                        cat = row[1]
                        categories[cat] = categories.get(cat, 0) + amount
            top_cats = sorted(categories.items(), key=lambda x: x[1], reverse=True)[:5]
            return {"income": income, "expense": expense, "top_cats": top_cats}
        except Exception as e:
            return None

    def get_budget_limits(self):
        try:
            sheet = self.client.open_by_key(SPREADSHEET_ID).worksheet("Планування")
            data = sheet.get_all_values()
            limits = {}
            for row in data[1:]:
                if len(row) >= 2 and row[0]:
                    amount = self._clean_amount(row[1])
                    if amount > 0: limits[row[0].strip()] = amount
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
        except Exception as e:
            print(f"🔴 Error limit: {e}")
            return False

    def undo_last_transaction(self):
        try:
            sheet = self.client.open_by_key(SPREADSHEET_ID).worksheet(SHEET_NAME)
            row_values = sheet.row_values(3)
            if not row_values or row_values[0] == "Дата": return None
            sheet.delete_rows(3)
            return {
                "date": row_values[0],
                "category": row_values[1],
                "amount": row_values[2],
                "desc": row_values[4] if len(row_values) > 4 else ""
            }
        except:
            return None