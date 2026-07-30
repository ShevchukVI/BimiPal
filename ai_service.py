import base64
import json
import asyncio
import logging
import re
from openai import AsyncOpenAI
from config import OPENROUTER_API_KEY, AI_TEXT_MODEL, AI_VISION_MODEL

logger = logging.getLogger(__name__)


class AIManager:
    def __init__(self):
        self.client = AsyncOpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=OPENROUTER_API_KEY,
        )

    async def _safe_request(self, messages, model, max_retries=2, temperature=0.1):
        """Базова функція для виклику ШІ з обробкою помилок."""
        delay = 1
        for attempt in range(max_retries):
            try:
                response = await self.client.chat.completions.create(
                    model=model,
                    messages=messages,
                    temperature=temperature
                )

                if hasattr(response, 'choices') and len(response.choices) > 0:
                    return response.choices[0].message.content
                else:
                    logger.error("ШІ Помилка: Порожня відповідь.")
                    return None
            except Exception as e:
                logger.error(f"ШІ Помилка (Спроба {attempt + 1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(delay)
                    delay *= 2
                else:
                    return None

    async def parse_receipt_image(self, base64_image: str):
        """Пайплайн з двох кроків: 1. Очі (Vision) -> 2. Перекладач (Text)."""
        if not OPENROUTER_API_KEY or len(OPENROUTER_API_KEY) < 10: return None

        # КРОК 1: VISION - витягуємо назви та кількість/вагу
        vision_prompt = """
        Витягни з фото чеку текст і поверни СУВОРО у форматі JSON без маркдауну. 
        ОБОВ'ЯЗКОВО ЗВЕРТАЙ УВАГУ НА КІЛЬКІСТЬ ТА ВАГУ товару (знаходиться під назвою або поруч, наприклад 1.176, 0.760, 2.000).
        Додавай цю вагу/кількість до початку назви товару. Суму бери ту, що ДО СПЛАТИ.
        Формат: {"shop_name": "Фора", "total_amount": 718.09, "items": ["1.000 шт Мол870Гал", "0.760 кг БананКг", "2.000 шт Паст70Чумак", "1.176 кг КурячеКгФілеОхол"]}
        """
        vision_messages = [
            {"role": "system", "content": vision_prompt},
            {"role": "user", "content": [
                {"type": "text", "text": "Розпізнай чек:"},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}
            ]}
        ]

        raw_json_text = await self._safe_request(vision_messages, AI_VISION_MODEL)
        if not raw_json_text: return None

        # КРОК 2: TEXT - перекладаємо у стиль користувача з урахуванням грамівок
        translator_prompt = """
        Ти геніальний лінгвіст-аналітик. Тобі дадуть JSON зі списком покупок (сирі касові назви + кількість/вага). 
        Твоє завдання — перекласти їх на нормальну українську мову у заданому стилі.

        ПРАВИЛА:
        1. Зрозумій товар і обов'язково додай до нього вагу/кількість згідно з вхідними даними.
        2. Якщо вага менше 1 кг (наприклад, 0.760 кг), переведи в грами: "760 г". Якщо більше — залишай в кг: "1,17 кг".
        3. Якщо кількість у штуках (2.000 шт), конвертуй у слова: "дві банки", "дві пляшки", "дві пачки".

        ПРИКЛАДИ ПЕРЕКЛАДУ (ТВІЙ ОРІЄНТИР):
        - "1.000 шт Мол870ГалУкраїн2,5%" -> "пляшка молока 2,5%"
        - "0.760 кг БананКг" -> "банани 760 г"
        - "1.176 кг КурячеКгФілеОхол" -> "куряче філе 1,17 кг"
        - "1.100 кг ОгірокКгВітчТепл" -> "огірки 1,1 кг"
        - "2.000 шт Кук400KwidzЦукрКонс" -> "дві банки кукурудзи"
        - "1.000 шт Салат75ПучСвіжБебМік" -> "упаковка салат бебі мікс"
        - "2.000 шт Паст70ЧумакТомПірам" -> "дві пірамідки пасти томатної"

        ПОВЕРНИ ТІЛЬКИ ОНОВЛЕНИЙ JSON, без маркдауну, без пояснень! Збережи shop_name і total_amount.
        """

        text_messages = [
            {"role": "system", "content": translator_prompt},
            {"role": "user", "content": f"Ось сирий JSON:\n{raw_json_text}"}
        ]

        translated_json_text = await self._safe_request(text_messages, AI_TEXT_MODEL, temperature=0.1)
        if not translated_json_text:
            translated_json_text = raw_json_text

        try:
            clean_json = translated_json_text.replace('```json', '').replace('```', '').strip()
            return json.loads(clean_json)
        except Exception as e:
            logger.error(f"Не вдалося спарсити JSON після перекладу: {e}\nТекст: {translated_json_text}")
            return None

    async def generate_daily_insight(self, spent_amount, remaining_limit, transactions_text):
        """Вечірня аналітика за правилами фінансового тренера."""
        if not OPENROUTER_API_KEY or len(OPENROUTER_API_KEY) < 10: return None
        if spent_amount == 0 and not transactions_text: return None

        system_prompt = """
        Роль: Ти — Бімі (Bimi), фінансовий тренер та аналітик сімейного бюджету. Твоє завдання — тримати фінансову дисципліну, попереджати касові розриви та керувати накопиченнями, дозволяючи контрольовані витрати на розваги.
        Стиль: Лаконічно, технічно, виключно по суті, без "води" та моралізаторства. Показуй прогрес цифрами. Давай чіткі вказівки.
        Табу: Жодних психологічних ярликів, привітань чи прощань. Не згадуй роботу.

        Контекст (Доходи): Вадим (~45 000 грн, транші на початку, всередині та наприкінці місяця). Аня (~$700, 1-го числа).
        Поточні зобов'язання (Вадим): Телевізор (2300 грн), 3D-принтер (1500 грн), Оренда (3500 грн), Комуналка (~2000 грн), Підписки (~650 грн).
        Пріоритетність цілей:
        1. Курси манікюру (Аня): ~30 000 грн.
        2. Відпустка: накопичується паралельно.
        3. Консоль + GTA 6: 20-25к (листопад).

        Правила: "Щоденні дрібниці" (кава, енергетики) — головний індикатор імпульсивних витрат.

        ЗАВДАННЯ: 
        Користувач надасть суму витрат за сьогодні та список транзакцій. 
        Напиши 1 короткий абзац (2-3 речення). Зроби жорсткий висновок: похвали за відсутність "Щоденних дрібниць" АБО попередь про ризик дефіциту до наступного траншу зарплати. Роби прив'язку до глобальних цілей (Курси/Відпустка/GTA).
        """

        user_content = f"Сьогодні витрачено: {spent_amount} грн.\nТранзакції:\n{transactions_text}"

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content}
        ]

        return await self._safe_request(messages, AI_TEXT_MODEL, temperature=0.7)


ai_manager = AIManager()