# 📂 BIMIPAL PROJECT CARD (v6.0 "SaaS Transition & Dual-Write")

**Мета:** Безшовний перехід від персонального бота на Google Sheets до масштабованої SaaS-платформи на базі Telegram Mini Apps та PostgreSQL, зберігаючи повну працездатність старого функціоналу для поточних користувачів.

### 🛠 Технічний стек (Current State)
* **Мова:** Python 3.12+ (aiogram 3.x, асинхронність).
* **База даних (Legacy):** Google Sheets API (gspread).
* **База даних (New):** PostgreSQL (через мікросервіс BimiFinance).
* **Інтеграції:** Monobank Personal API (Webhooks) через `aiohttp`.
* **Штучний Інтелект:** OpenRouter API (openai lib). Моделі: `openrouter/free` (Аналітика), `google/gemma-4-26b-a4b-it:free` (Парсинг фото).
* **Архітектура:** Strangler Fig Pattern (Тіньове дублювання даних через `api_client.py`).

---

### 🗺 BIMIPAL PROJECT ROADMAP (v6.0)

**✅ Етап 1 & 2: Автопілот, Smart Receipts, Inbox Zero (Завершено)**
* Інтеграція Monobank, AI-Парсер чеків, AI Інсайти, вечірні звіти.

**✅ Етап 3: Фундамент SaaS та Мікросервіси (Завершено)**
* [x] Піднято окремий мікросервіс BimiFinance (FastAPI + PostgreSQL + React).
* [x] Реалізовано "Тіньовий запис" (Shadow Write): бот паралельно пише дані і в Google Sheets, і в нову SQL БД.
* [x] Додано сутність `Family` (Сім'ї) для ізоляції даних користувачів.

**🚀 Етап 4: Public Onboarding & Telegram Mini App (В процесі)**
* [ ] **Zero-Friction Onboarding:** Нові користувачі можуть зареєструвати сім'ю через `/start`, налаштувати Monobank токен та отримати доступ до Mini App без втручання в код.
* [ ] **Legacy Protection:** Поточні користувачі (Вадим та Аня) продовжують працювати через старі кнопки та Google Sheets без жодних змін.
* [ ] **BimiApp (Frontend):** Розробка повноцінного UI всередині Telegram (графіки, свайпи, управління скарбничками).
* [ ] **Мігратор:** Скрипт для одноразового перенесення всієї історії з Google Sheets у PostgreSQL.