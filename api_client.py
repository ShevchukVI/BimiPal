import aiohttp
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


class BimiAPIClient:
    def __init__(self, base_url="https://bimif.vshevchuk.pp.ua"):
        self.base_url = base_url
        self._cache = {
            "family_id": None,
            "users": {},
            "cats": {}
        }

    async def _get(self, endpoint):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{self.base_url}{endpoint}", timeout=3) as resp:
                    if resp.status == 200:
                        return await resp.json()
        except Exception:
            pass
        return None

    async def _post(self, endpoint, payload):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(f"{self.base_url}{endpoint}", json=payload, timeout=3) as resp:
                    if resp.status in (200, 201):
                        return await resp.json()
        except Exception:
            pass
        return None

    # --- SaaS МЕТОДИ ---
    async def check_user_registered(self, tg_id: int):
        """Перевіряє, чи зареєстрований користувач у SaaS базі"""
        user = await self._get(f"/users/by-tg/{tg_id}")
        return user is not None

    async def register_saas_user(self, tg_id: int, name: str, family_name: str, mono_token: str = None):
        """Створює нову сім'ю та користувача для SaaS"""
        new_f = await self._post("/families", {"name": family_name, "mono_token": mono_token})
        if new_f:
            await self._post("/users", {"family_id": new_f["id"], "name": name, "tg_id": tg_id})
            return True
        return False

    # --- LEGACY SHADOW WRITE МЕТОДИ (Для Вадима та Ані) ---
    async def get_or_create_family(self, name="Шевчуки"):
        if self._cache["family_id"]: return self._cache["family_id"]
        fams = await self._get("/families")
        if fams:
            for f in fams:
                if f["name"] == name:
                    self._cache["family_id"] = f["id"]
                    return f["id"]
        new_f = await self._post("/families", {"name": name})
        if new_f:
            self._cache["family_id"] = new_f["id"]
            return new_f["id"]
        return 1

    async def get_or_create_user(self, family_id, name):
        if name in self._cache["users"]: return self._cache["users"][name]
        users = await self._get(f"/families/{family_id}/users")
        if users:
            for u in users:
                self._cache["users"][u['name']] = u['id']
                if u['name'] == name: return u['id']
        new_u = await self._post("/users", {"family_id": family_id, "name": name})
        if new_u:
            self._cache["users"][name] = new_u['id']
            return new_u['id']
        return 1

    async def get_or_create_category(self, family_id, name, t_type):
        if name in self._cache["cats"]: return self._cache["cats"][name]
        cats = await self._get(f"/families/{family_id}/categories")
        if cats:
            for c in cats:
                self._cache["cats"][c['name']] = c['id']
                if c['name'] == name: return c['id']
        icon = name.split(" ")[0] if " " in name else "📁"
        new_c = await self._post("/categories", {"family_id": family_id, "icon": icon, "name": name, "color": "#3498DB",
                                                 "type": t_type})
        if new_c:
            self._cache["cats"][name] = new_c['id']
            return new_c['id']
        return 1

    async def shadow_add_transaction(self, category_name, amount, t_type, title, note, who, account="Готівка",
                                     mono_id=None):
        try:
            family_id = await self.get_or_create_family()
            user_id = await self.get_or_create_user(family_id, who)
            cat_type = "expense" if t_type == "Витрати" else "income"
            cat_id = await self.get_or_create_category(family_id, category_name, cat_type)

            payload = {
                "family_id": family_id,
                "user_id": user_id,
                "category_id": cat_id,
                "amount": float(amount),
                "type": t_type,
                "title": title,
                "note": note,
                "account": account,
                "date": datetime.now().strftime("%Y-%m-%d"),
                "mono_id": mono_id
            }
            await self._post("/transactions", payload)
        except Exception as e:
            logger.error(f"Shadow Write Failed: {e}")


api_client = BimiAPIClient()