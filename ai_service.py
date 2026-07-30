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
        # Ініціалізуємо клієнт OpenAI, але направляємо його на сервери OpenRouter
        self.client = AsyncOpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=OPENROUTER_API_KEY,
        )

    async def _safe_request(self, messages, model, max_retries=3):
        """Внутрішня функція з exponential backoff для обробки помилок 429."""
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
                    delay *= 2  # 2s, 4s, 8s...
                else:
                    return None

    async def parse_receipt_image(self, base64_image: str):
        """Модуль А: Парсинг чеку (Vision). Повертає JSON словник або None."""
        if not OPENROUTER_API_KEY or len(OPENROUTER_API_KEY) < 10: return None

        system_prompt = """
        Ти фінансовий парсер. Твоє завдання витягнути з фото чеку інформацію і повернути її СУВОРО у форматі JSON без маркдауну та зайвого тексту.
        Формат:
        {
            "shop_name": "Назва магазину (Сільпо, АТБ тощо)",
            "total_amount": 105.50,
            "items": ["Молоко", "Хліб"]
        }
        Якщо щось не можеш прочитати, поверни null або порожній масив.
        """

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": [
                {"type": "text", "text": "Розпізнай цей чек."},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}
            ]}
        ]

        raw_response = await self._safe_request(messages, AI_VISION_MODEL)
        if not raw_response: return None

        # Парсимо JSON, обрізаючи можливі маркдаун блоки (```json ... ```)
        try:
            clean_json = re.sub(r'```json|```', '', raw_response).strip()
            return json.loads(clean_json)
        except Exception as e:
            logger.error(f"Не вдалося спарсити JSON від ШІ: {e}")
            return None

    async def generate_daily_insight(self, spent_amount, remaining_limit, transactions_text):
        """Модуль Б: Вечірня аналітика. Аналізує сьогоднішні витрати і дає коротку пораду."""
        if not OPENROUTER_API_KEY or len(OPENROUTER_API_KEY) < 10: return None
        if spent_amount == 0 and not transactions_text: return None

        system_prompt = """
        Ти дружній сімейний фінансовий радник Bimi. Твоя мета - допомогти Вадиму та Ані накопичити гроші на відпустку.
        Тобі дадуть список витрат за сьогодні і загальну суму.
        Твоє завдання: написати ОДИН короткий абзац (до 3 речень) живим тоном.
        Хвали за економію, жартуй, або м'яко попереджай, якщо гроші витрачаються занадто швидко на дурниці (наприклад, багато кави чи снеків).
        Без води, без привітань, просто відразу інсайт.
        """

        user_content = f"Сьогодні витрачено: {spent_amount} грн. Залишок до ліміту (якщо є): {remaining_limit}.\nСписок транзакцій:\n{transactions_text}"

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content}
        ]

        return await self._safe_request(messages, AI_TEXT_MODEL)


# Глобальний екземпляр для використання в інших файлах
ai_manager = AIManager()