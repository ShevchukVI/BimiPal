import gspread
from oauth2client.service_account import ServiceAccountCredentials
from config import SPREADSHEET_ID, SHEET_NAME


class GoogleSheetManager:
    def __init__(self):
        self.scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        self.creds_file = "service_account.json"
        self.authenticate()

    def authenticate(self):
        """Окрема функція для авторизації"""
        self.creds = ServiceAccountCredentials.from_json_keyfile_name(self.creds_file, self.scope)
        self.client = gspread.authorize(self.creds)

    def add_transaction(self, date, category, amount, t_type, item_name, note, who):
        try:
            # ❌ self.client.login() -- ЦЕЙ РЯДОК МИ ПРИБРАЛИ, БО ВІН ВИКЛИКАВ ПОМИЛКУ

            # Відкриваємо таблицю
            sheet = self.client.open_by_key(SPREADSHEET_ID).worksheet(SHEET_NAME)

            row = [
                date,  # A
                category,  # B
                amount,  # C
                t_type,  # D
                item_name,  # E
                note,  # F
                who  # G
            ]

            sheet.insert_row(row, 3)
            return True

        except gspread.exceptions.APIError as e:
            # Якщо токен протух (буває раз на годину/день), пробуємо перепідключитися
            print(f"🔄 Оновлення токену... Помилка: {e}")
            try:
                self.authenticate()
                sheet = self.client.open_by_key(SPREADSHEET_ID).worksheet(SHEET_NAME)
                sheet.insert_row(row, 3)
                return True
            except Exception as e2:
                print(f"🔴 Критична помилка після реконекту: {e2}")
                return False

        except Exception as e:
            print(f"🔴 ПОМИЛКА Google Sheets: {e}")
            return False