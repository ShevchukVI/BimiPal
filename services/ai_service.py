import base64
import json
import asyncio
import logging
from openai import AsyncOpenAI
from config import OPENROUTER_API_KEY, AI_TEXT_MODEL, AI_VISION_MODEL

logger = logging.getLogger(__name__)


class AIManager:
    def __init__(self):
        self.client = AsyncOpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=OPENROUTER_API_KEY,
        )

    async def _safe_request(self, messages, model, max_retries=2, temperature=0.1, max_tokens=2000):
        delay = 1
        for attempt in range(max_retries):
            try:
                response = await asyncio.wait_for(
                    self.client.chat.completions.create(
                        model=model,
                        messages=messages,
                        temperature=temperature,
                        max_tokens=max_tokens,
                    ),
                    timeout=30
                )
                if hasattr(response, 'choices') and len(response.choices) > 0:
                    return response.choices[0].message.content
                else:
                    logger.error("AI Error: Empty response from OpenRouter.")
                    return None
            except asyncio.TimeoutError:
                logger.error(f"AI Timeout (attempt {attempt + 1}/{max_retries})")
                if attempt >= max_retries - 1:
                    return None
                await asyncio.sleep(delay)
                delay *= 2
            except Exception as e:
                logger.error(f"AI Error (attempt {attempt + 1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(delay)
                    delay *= 2
                else:
                    return None

    async def parse_receipt_image(self, base64_image: str):
        if not OPENROUTER_API_KEY or len(OPENROUTER_API_KEY) < 10: return None

        prompt = """
        Ти геніальний фінансовий парсер. Твоє завдання — витягнути з фото чеку загальну суму ДО СПЛАТИ, назву магазину та список товарів.
        ОДРАЗУ переклади касові абревіатури на нормальну українську мову.

        ПРАВИЛА:
        1. Зрозумій товар і обов'язково додай до нього вагу/кількість згідно з чеком.
        2. Якщо вага менше 1 кг, переведи в грами: "760 г". Якщо більше — залишай в кг: "1,17 кг". 
        3. Якщо кількість у штуках, конвертуй у слова: "дві банки", "дві пачки".

        ПОВЕРНИ РЕЗУЛЬТАТ СУВОРО У ФОРМАТІ JSON без маркдауну:
        {"shop_name": "Фора", "total_amount": 718.09, "items": ["пляшка молока 2,5%", "куряче філе 1,17 кг", "огірки 1,1 кг"]}
        """

        messages = [
            {"role": "system", "content": prompt},
            {"role": "user", "content": [
                {"type": "text", "text": "Оброби цей чек:"},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}
            ]}
        ]

        raw_json_text = await self._safe_request(messages, AI_VISION_MODEL, temperature=0.1)
        if not raw_json_text: return None

        try:
            clean_json = raw_json_text.replace('```json', '').replace('```', '').strip()
            return json.loads(clean_json)
        except Exception as e:
            logger.error(f"Не вдалося спарсити JSON: {e}\nТекст: {raw_json_text}")
            return None

    async def generate_daily_insight(self, spent_amount, remaining_limit, transactions_text):
        if not OPENROUTER_API_KEY or len(OPENROUTER_API_KEY) < 10: return None
        if spent_amount == 0 and not transactions_text: return None

        # УНІВЕРСАЛЬНИЙ ПРОМПТ (Без особистих даних)
        system_prompt = """
        Роль: Ти — Bimi, строгий та лаконічний фінансовий тренер сімейного бюджету.
        Стиль: Технічно, по суті, без моралізаторства і психології. Жодних привітань.

        Твоє завдання — проаналізувати список витрат за сьогодні.
        1. Якщо бачиш "дрібниці" (кава, енергетики, солодощі) — вкажи, що це імпульсивні витрати, які гальмують накопичення.
        2. Якщо витрати тільки базові (продукти, комуналка) — похвали за дисципліну.
        3. Напиши рівно 2-3 речення. Жорсткий висновок.
        """

        user_content = f"Сьогодні витрачено: {spent_amount} грн.\nТранзакції:\n{transactions_text}"

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content}
        ]

        return await self._safe_request(messages, AI_TEXT_MODEL, temperature=0.7)


ai_manager = AIManager()
