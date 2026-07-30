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

    async def _safe_request(self, messages, model, max_retries=3):
        delay = 2
        for attempt in range(max_retries):
            try:
                response = await self.client.chat.completions.create(
                    model=model,
                    messages=messages,
                    temperature=0.3
                )
                return response.choices[0].message.content
            except Exception as e:
                logger.error(f"ШІ Помилка (Спроба {attempt + 1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(delay)
                    delay *= 2
                else:
                    return None

    async def parse_receipt_image(self, base64_image: str):
        if not OPENROUTER_API_KEY or len(OPENROUTER_API_KEY) < 10: return None
        system_prompt = """Ти парсер чеків. Твоє завдання витягнути інформацію і повернути її СУВОРО у форматі JSON без маркдауну та зайвого тексту. Формат: {"shop_name": "Назва", "total_amount": 105.50, "items": ["Молоко", "Хліб"]}"""
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": [
                {"type": "text", "text": "Розпізнай цей чек і видай JSON."},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}
            ]}
        ]
        raw_response = await self._safe_request(messages, AI_VISION_MODEL)
        if not raw_response: return None
        try:
            clean_json = re.sub(r'```json|```', '', raw_response).strip()
            return json.loads(clean_json)
        except:
            return None

    async def generate_daily_insight(self, spent_amount, remaining_limit, transactions_text):
        if not OPENROUTER_API_KEY or len(OPENROUTER_API_KEY) < 10: return None
        if spent_amount == 0 and not transactions_text: return None

        system_prompt = """
        Роль: Ти — Бімі (Bimi), фінансовий тренер та аналітик сімейного бюджету. Твоє завдання — тримати фінансову дисципліну, попереджати касові розриви та керувати накопиченнями.
        Стиль: Лаконічно, технічно, виключно по суті, без "води" та моралізаторства. Показуй прогрес цифрами. Давай чіткі вказівки. Жодних привітань.

        Контекст: Вадим має дохід ~45к (асинхронно). Обов'язкові платежі: ТБ (2300), 3D-принтер (1500), Оренда (3500), Комуналка (~2000), Підписки (~650). 
        Аня має ~$700 1-го числа.
        Цілі: 1. Курси манікюру (Аня) ~30к. 2. Відпустка. 3. GTA 6 + консоль (20-25к, орієнтир листопад).

        Тобі дають список витрат за сьогодні. Дай жорсткий, короткий (2-3 речення) аналіз: чи є ризик касового розриву, або вказівку, скільки відкласти на цілі. Жорстко критикуй імпульсивні "Щоденні дрібниці", якщо їх багато.
        """
        user_content = f"Витрачено сьогодні: {spent_amount} грн. Транзакції:\n{transactions_text}"
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content}
        ]
        return await self._safe_request(messages, AI_TEXT_MODEL)


ai_manager = AIManager()