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

    # --- TRANSACTIONS ---
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

    def add_transfer(self, amount, note, from_who, to_who):
        """Створює транзакцію переказу між балансами."""
        try:
            sheet = self.client.open_by_key(SPREADSHEET_ID).worksheet(SHEET_NAME)
            date_now = datetime.now().strftime("%d.%m.%Y")
            row_out = [date_now, "🔄 Переказ", amount, "Витрати", f"Переказ -> {to_who}", note, from_who]
            row_in = [date_now, "🔄 Переказ", amount, "Поповнення", f"Отримано <- {from_who}", note, to_who]

            sheet.insert_row(row_in, 3)
            sheet.insert_row(row_out, 3)
            return True
        except Exception as e:
            print(f"🔴 Error transfer: {e}")
            return False

    def undo_last_transaction(self):
        try:
            sheet = self.client.open_by_key(SPREADSHEET_ID).worksheet(SHEET_NAME)
            row_values = sheet.row_values(3)
            if not row_values or row_values[0] == "Дата": return None
            sheet.delete_rows(3)
            return {"date": row_values[0], "category": row_values[1], "amount": row_values[2]}
        except:
            return None

    # --- HISTORY CONTROL (v3.3) ---
    def get_last_transactions(self, page=1, page_size=5):
        """Повертає історію з пагінацією."""
        try:
            sheet = self.client.open_by_key(SPREADSHEET_ID).worksheet(SHEET_NAME)
            start_row = 3 + (page - 1) * page_size
            end_row = start_row + page_size - 1

            rows = sheet.get_values(f"A{start_row}:G{end_row}")

            history = []
            for i, row in enumerate(rows):
                row_idx = start_row + i
                if not row or len(row) < 3: continue

                history.append({
                    "id": row_idx,
                    "date": row[0],
                    "category": row[1],
                    "amount": self._clean_amount(row[2]),
                    "desc": row[4] if len(row) > 4 else "",
                    "who": row[6] if len(row) > 6 else ""
                })
            return history
        except Exception as e:
            print(f"🔴 Error history: {e}")
            return []

    def delete_transaction_by_row(self, row_idx):
        """Видаляє конкретний рядок з таблиці."""
        try:
            sheet = self.client.open_by_key(SPREADSHEET_ID).worksheet(SHEET_NAME)
            sheet.delete_rows(int(row_idx))
            return True
        except Exception as e:
            print(f"🔴 Error delete: {e}")
            return False

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
            wallet_vadym = 0.0
            wallet_anya = 0.0
            month_categories = {}

            for row in data_rows:
                if not row or len(row) < 4 or not row[0]: continue
                try:
                    amount = self._clean_amount(row[2])
                    t_type = row[3].strip()
                    cat = row[1].strip()
                    who = row[6].strip() if len(row) > 6 else ""
                    t_date = datetime.strptime(row[0].strip(), "%d.%m.%Y")

                    # 🛡 БРОНЯ: перевіряємо і тип, і саму назву категорії
                    is_income = t_type in ["Поповнення", "Дохід", "Доходи"] or "Доход" in cat or "Поповнення" in cat

                    if is_income:
                        total_wallet += amount
                        if "Вадим" in who:
                            wallet_vadym += amount
                        elif "Аня" in who:
                            wallet_anya += amount
                    else:
                        total_wallet -= amount
                        if "Вадим" in who:
                            wallet_vadym -= amount
                        elif "Аня" in who:
                            wallet_anya -= amount

                    if t_date.month == now.month and t_date.year == now.year:
                        if is_income:
                            month_income += amount
                        else:
                            month_expense += amount
                            month_categories[cat] = month_categories.get(cat, 0) + amount
                except Exception:
                    # БРОНЯ: Якщо рядок "зламаний", просто пропускаємо його і йдемо далі
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
                    t_date = datetime.strptime(row[0].strip(), "%d.%m.%Y")
                    if 0 <= (now - t_date).days <= 7:
                        amount = self._clean_amount(row[2])
                        t_type = row[3].strip()
                        cat = row[1].strip()

                        is_income = t_type in ["Поповнення", "Дохід", "Доходи"] or "Доход" in cat or "Поповнення" in cat

                        if is_income:
                            income += amount
                        else:
                            expense += amount
                            categories[cat] = categories.get(cat, 0) + amount
                except Exception:
                    continue
            return {"income": income, "expense": expense,
                    "top_cats": sorted(categories.items(), key=lambda x: x[1], reverse=True)[:5]}
        except:
            return None

    # --- REPORTS (PDF) ---
    def get_month_history(self, month, year):
        try:
            sheet = self.client.open_by_key(SPREADSHEET_ID).worksheet(SHEET_NAME)
            all_values = sheet.get_all_values()
            if len(all_values) <= 2: return None
            data_rows = all_values[2:]

            income = 0.0
            expense = 0.0
            categories_dict = {}

            for row in data_rows:
                if not row or len(row) < 4: continue
                try:
                    t_date = datetime.strptime(row[0].strip(), "%d.%m.%Y")
                    if t_date.month == month and t_date.year == year:
                        amount = self._clean_amount(row[2])
                        t_type = row[3].strip()
                        cat = row[1].strip()
                        desc = row[4].strip() if len(row) > 4 else ""
                        who = row[6].strip() if len(row) > 6 else ""

                        is_income = t_type in ["Поповнення", "Дохід", "Доходи"] or "Доход" in cat or "Поповнення" in cat

                        if is_income:
                            income += amount
                        else:
                            expense += amount
                            if cat not in categories_dict:
                                categories_dict[cat] = {'total': 0.0, 'txs': []}

                            categories_dict[cat]['total'] += amount
                            categories_dict[cat]['txs'].append({
                                "date": row[0], "amount": amount, "desc": desc, "who": who
                            })
                except Exception:
                    # БРОНЯ: ігнор рядків, які неможливо обробити
                    continue

            if expense == 0 and income == 0:
                return None

            # Групування та сортування категорій і ТОП-3 транзакцій
            sorted_cats = sorted(
                [{"name": k, "total": v['total'], "txs": v['txs']} for k, v in categories_dict.items()],
                key=lambda x: x['total'],
                reverse=True
            )

            for cat in sorted_cats:
                cat['top_txs'] = sorted(cat['txs'], key=lambda x: x['amount'], reverse=True)[:3]

            return {
                "income": income,
                "expense": expense,
                "balance": income - expense,
                "grouped_categories": sorted_cats
            }
        except Exception as e:
            print(f"🔴 Error history: {e}")
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

                last_paid_date = None
                if last_paid_str:
                    try:
                        last_paid_date = datetime.strptime(last_paid_str, "%d.%m.%Y")
                    except:
                        pass

                try:
                    this_month_due_date = datetime(now.year, now.month, day_to_pay)
                except ValueError:
                    last_day = calendar.monthrange(now.year, now.month)[1]
                    this_month_due_date = datetime(now.year, now.month, last_day)

                is_paid = False
                if last_paid_date:
                    if last_paid_date.month == now.month and last_paid_date.year == now.year:
                        is_paid = True
                    else:
                        early_window = this_month_due_date - timedelta(days=5)
                        if last_paid_date >= early_window: is_paid = True
                if is_paid: continue

                if now.day >= day_to_pay:
                    due_items.append({"row_idx": i + 2, "name": name, "amount": amount, "category": category})
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