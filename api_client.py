import aiohttp
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


class BimiAPIClient:
    def __init__(self, base_url="https://bimif.vshevchuk.pp.ua"):
        # Оскільки бот і API працюють на одному сервері, звертаємося локально
        self.base_url = base_url
        self._users_cache = {}
        self._cats_cache = {}

    async def _get(self, endpoint):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{self.base_url}{endpoint}", timeout=3) as resp:
                    if resp.status == 200:
                        return await resp.json()
        except Exception as e:
            pass  # Ігноруємо помилки мережі, щоб бот не падав
        return None

    async def _post(self, endpoint, payload):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(f"{self.base_url}{endpoint}", json=payload, timeout=3) as resp:
                    if resp.status in (200, 201):
                        return await resp.json()
        except Exception as e:
            pass
        return None

    async def get_or_create_user(self, name):
        if name in self._users_cache:
            return self._users_cache[name]

        users = await self._get("/users")
        if users:
            for u in users:
                self._users_cache[u['name']] = u['id']
                if u['name'] == name: return u['id']

        # Якщо немає - створюємо
        new_user = await self._post("/users", {"name": name})
        if new_user:
            self._users_cache[name] = new_user['id']
            return new_user['id']
        return 1  # Fallback заглушка

    async def get_or_create_category(self, name, t_type):
        if name in self._cats_cache:
            return self._cats_cache[name]

        cats = await self._get("/categories")
        if cats:
            for c in cats:
                self._cats_cache[c['name']] = c['id']
                if c['name'] == name: return c['id']

        icon = name.split(" ")[0] if " " in name else "📁"
        new_cat = await self._post("/categories", {
            "icon": icon,
            "name": name,
            "color": "#3498DB",
            "type": t_type
        })
        if new_cat:
            self._cats_cache[name] = new_cat['id']
            return new_cat['id']
        return 1

    async def shadow_add_transaction(self, category_name, amount, t_type, title, note, who, account="Готівка",
                                     mono_id=None):
        """Тіньовий запис транзакції в FastAPI (БД)"""
        try:
            user_id = await self.get_or_create_user(who)
            cat_type = "expense" if t_type == "Витрати" else "income"
            cat_id = await self.get_or_create_category(category_name, cat_type)

            date_str = datetime.now().strftime("%Y-%m-%d")
            payload = {
                "user_id": user_id,
                "category_id": cat_id,
                "amount": float(amount),
                "type": t_type,
                "title": title,
                "note": note,
                "account": account,
                "date": date_str,
                "mono_id": mono_id
            }
            await self._post("/transactions", payload)
        except Exception as e:
            logger.error(f"Shadow Write Failed: {e}")


api_client = BimiAPIClient()