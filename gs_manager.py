import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, timedelta
import calendar
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
        """Чистить формат чисел (пробіли, коми, валюти)."""
        if isinstance(amount_str, (int, float)): return float(amount_str)
        s = str(amount_str).replace('\xa0', '').replace(' ', '')
        s = re.sub(r'[^\d,.-]', '', s)
        if '.' in s and ',' in s: s = s.replace('.', '')
        s = s.replace(',', '.')
        try:
            return float(s)
        except ValueError:
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
            return (["🛒 Продукти"], ["💰 Дохід"])

    def get_month_history(self, month, year):
        """Витягує всі транзакції за конкретний місяць і рік для звіту."""
        try:
            sheet = self.client.open_by_key(SPREADSHEET_ID).worksheet(SHEET_NAME)
            all_values = sheet.get_all_values()
            if len(all_values) <= 2: return None
            data_rows = all_values[2:]

            history = []
            categories = {}
            income = 0.0
            expense = 0.0

            for row in data_rows:
                if not row or len(row) < 4: continue
                try:
                    # row[0] - Date, row[1] - Cat, row[2] - Amount, row[3] - Type, row[4] - Desc, row[6] - Who
                    t_date = datetime.strptime(row[0], "%d.%m.%Y")
                    if t_date.month == month and t_date.year == year:
                        amount = self._clean_amount(row[2])
                        t_type = row[3].strip()

                        # Збираємо статистику
                        if t_type in ["Поповнення", "Дохід", "Доходи"]:
                            income += amount
                        else:
                            expense += amount
                            cat = row[1]
                            categories[cat] = categories.get(cat, 0) + amount

                        # Зберігаємо транзакцію для списку
                        history.append({
                            "date": row[0],
                            "cat": row[1],
                            "amount": amount,
                            "type": t_type,
                            "desc": row[4] if len(row) > 4 else "",
                            "who": row[6] if len(row) > 6 else ""
                        })
                except ValueError:
                    continue

            # Сортуємо транзакції за сумою (від найбільшої) для ТОП-10
            top_transactions = sorted(history, key=lambda x: x['amount'], reverse=True)

            return {
                "income": income,
                "expense": expense,
                "balance": income - expense,
                "categories": categories,
                "transactions": top_transactions,  # Весь список
                "top_10": top_transactions[:10]  # Тільки топ-10
            }
        except Exception as e:
            print(f"🔴 Error history: {e}")
            return None

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

            # --- НОВЕ: Окремі гаманці ---
            wallet_vadym = 0.0
            wallet_anya = 0.0

            month_categories = {}

            for row in data_rows:
                if not row or len(row) < 4 or not row[0]: continue
                try:
                    amount = self._clean_amount(row[2])
                    t_type = row[3].strip()
                    who = row[6].strip() if len(row) > 6 else ""  # Беремо ім'я

                    t_date = datetime.strptime(row[0], "%d.%m.%Y")

                    # 1. Рахуємо Глобальний Гаманець
                    if t_type in ["Поповнення", "Дохід", "Доходи"]:
                        total_wallet += amount
                        # Розподіляємо по людях
                        if "Вадим" in who:
                            wallet_vadym += amount
                        elif "Аня" in who:
                            wallet_anya += amount
                    else:
                        total_wallet -= amount
                        # Розподіляємо по людях
                        if "Вадим" in who:
                            wallet_vadym -= amount
                        elif "Аня" in who:
                            wallet_anya -= amount

                    # 2. Рахуємо статистику за ПОТОЧНИЙ місяць
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

                # Повертаємо нові значення
                "wallet_vadym": wallet_vadym,
                "wallet_anya": wallet_anya,

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
            col_usd = sheet.col_values(3)
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

    # --- REMINDERS (SMART) ---
    def get_due_reminders(self):
        """Перевіряє, що треба оплатити (З урахуванням завчасної оплати)."""
        try:
            sheet = self.client.open_by_key(SPREADSHEET_ID).worksheet("Нагадування")
            all_values = sheet.get_all_values()
            if len(all_values) < 2: return []

            data_rows = all_values[1:]
            due_items = []
            now = datetime.now()

            for i, row in enumerate(data_rows):
                if len(row) < 4: continue

                name = row[0]
                try:
                    day_to_pay = int(row[1])
                except:
                    continue

                try:
                    amount = self._clean_amount(row[2])
                except:
                    amount = 0.0

                category = row[3]
                last_paid_str = row[4] if len(row) > 4 else ""

                # --- ЛОГІКА ПЕРЕВІРКИ ---
                # 1. Розбираємо дату останньої оплати
                last_paid_date = None
                if last_paid_str:
                    try:
                        last_paid_date = datetime.strptime(last_paid_str, "%d.%m.%Y")
                    except:
                        pass

                # 2. Визначаємо дедлайн у ЦЬОМУ місяці
                try:
                    this_month_due_date = datetime(now.year, now.month, day_to_pay)
                except ValueError:
                    last_day = calendar.monthrange(now.year, now.month)[1]
                    this_month_due_date = datetime(now.year, now.month, last_day)

                # 3. Чи оплачено?
                is_paid = False
                if last_paid_date:
                    # Або платили в цьому місяці
                    if last_paid_date.month == now.month and last_paid_date.year == now.year:
                        is_paid = True
                    # Або платили завчасно (за 5 днів до дедлайну)
                    else:
                        early_window = this_month_due_date - timedelta(days=5)
                        if last_paid_date >= early_window:
                            is_paid = True

                if is_paid: continue

                # 4. Настав час?
                if now.day >= day_to_pay:
                    due_items.append({
                        "row_idx": i + 2,  # +2 бо i з 0 і є заголовок
                        "name": name,
                        "amount": amount,
                        "category": category
                    })
            return due_items
        except Exception as e:
            print(f"🔴 Error reminders: {e}")
            return []

    def update_reminder_payment(self, row_idx, date_str):
        try:
            sheet = self.client.open_by_key(SPREADSHEET_ID).worksheet("Нагадування")
            sheet.update_cell(row_idx, 5, date_str)
            return True
        except:
            return False