import aiohttp
import logging
from datetime import datetime

from config import API_BASE_URL, BOT_API_KEY

logger = logging.getLogger(__name__)

_API_HEADERS = {"X-API-Key": BOT_API_KEY}


def _headers(x_user_id=None, x_family_id=None):
    """Базові заголовки + (опціонально) контекст користувача/сім'ї для бекенду."""
    h = dict(_API_HEADERS)
    if x_user_id:
        h["X-User-Id"] = str(x_user_id)
    if x_family_id:
        h["X-Family-Id"] = str(x_family_id)
    return h


class BimiAPIClient:
    def __init__(self, base_url=API_BASE_URL):
        self.base_url = base_url

    async def _get(self, endpoint, headers=None):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{self.base_url}{endpoint}", headers=headers or _API_HEADERS, timeout=5) as resp:
                    if resp.status == 200: return await resp.json()
        except Exception as e:
            logger.error(f"API GET Error {endpoint}: {e}")
        return None

    async def _post(self, endpoint, payload, method="post", headers=None):
        try:
            async with aiohttp.ClientSession() as session:
                req = getattr(session, method)
                async with req(f"{self.base_url}{endpoint}", json=payload, headers=headers or _API_HEADERS, timeout=5) as resp:
                    if resp.status in (200, 201): return await resp.json()
        except Exception as e:
            logger.error(f"API POST Error {endpoint}: {e}")
        return None

    async def _delete(self, endpoint, headers=None):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.delete(f"{self.base_url}{endpoint}", headers=headers or _API_HEADERS, timeout=5) as resp:
                    return resp.status in (200, 204)
        except Exception:
            pass
        return False

    # --- CORE METHODS ---
    async def get_me(self, tg_id: int):
        return await self._get(f"/auth/me?tg_id={tg_id}")

    async def get_categories(self, family_id: int, cat_type: str = None):
        cats = await self._get(f"/families/{family_id}/categories")
        if not cats: return []
        if cat_type: return [c for c in cats if c['type'] == cat_type]
        return cats

    async def add_transaction(self, family_id, user_id, cat_id, amount, t_type, title, account="Готівка", mono_id=None,
                              date_str=None):
        payload = {
            "family_id": family_id, "user_id": user_id, "category_id": cat_id,
            "amount": float(amount), "type": t_type, "title": title,
            "account": account, "mono_id": mono_id, "date": date_str or datetime.now().strftime("%Y-%m-%d")
        }
        return await self._post("/transactions", payload, headers=_headers(x_family_id=family_id))

    async def update_tx_by_mono(self, mono_id: str, category_id: int = None, note: str = None):
        payload = {}
        if category_id: payload["category_id"] = category_id
        if note: payload["title"] = note
        return await self._post(f"/transactions/by-mono/{mono_id}", payload, method="put")

    async def delete_tx_by_mono(self, family_id: int, mono_id: str):
        txs = await self._get(f"/families/{family_id}/transactions?limit=100")
        if not txs: return False
        tx = next((t for t in txs if t.get('mono_id') == mono_id), None)
        if tx: return await self._delete(f"/transactions/{tx['id']}")
        return False

    async def delete_transaction(self, tx_id: int):
        return await self._delete(f"/transactions/{tx_id}")

    async def get_stats(self, family_id: int):
        return await self._get(f"/families/{family_id}/stats")

    # --- JARS (Скарбнички) ---
    async def get_jars(self, family_id: int):
        return await self._get(f"/families/{family_id}/jars")

    # --- NOTES (Чернетка / Scratchpad) ---
    async def create_note(self, family_id: int, content: str):
        return await self._post("/notes", {"family_id": family_id, "content": content},
                                headers=_headers(x_family_id=family_id))

    # --- BACKUP (Бекап БД для Telegram) ---
    async def get_backup(self):
        """Завантажує .sql.gz дамп БД з BimiFinance (для щоденного бекапу)."""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{self.base_url}/system/backup", headers=_API_HEADERS, timeout=120) as resp:
                    if resp.status == 200:
                        return await resp.read()
        except Exception as e:
            logger.error(f"API Backup Error: {e}")
        return None

    # --- MULTI-FAMILY (M2M) ---
    async def get_my_families(self, user_id: int):
        """Список сімей користувача: [{family_id, name, role, is_active}, ...]."""
        return await self._get("/users/me/families", headers=_headers(x_user_id=user_id))

    async def set_active_family(self, user_id: int, family_id: int):
        """Перемикає активну сім'ю користувача. Повертає UserOut або None."""
        return await self._post("/users/me/active-family", {"family_id": family_id}, method="patch",
                                headers=_headers(x_user_id=user_id))

    async def generate_invite(self, user_id: int, family_id: int = None):
        """Генерує новий invite_code для сім'ї (admin). Повертає FamilyOut або None."""
        return await self._post("/families/invite", {}, headers=_headers(x_user_id=user_id, x_family_id=family_id))

    async def join_family_via_code(self, user_id: int, invite_code: str):
        """Приєднує користувача до сім'ї за invite_code. Повертає FamilyOut або None."""
        return await self._post("/families/join", {"invite_code": invite_code},
                                headers=_headers(x_user_id=user_id))

    # --- INBOX ZERO & DAILY SUMMARY ---
    async def get_unresolved(self, family_id: int, user_id: int):
        cats = await self.get_categories(family_id)
        pending_cat = next((c for c in cats if "Очікує" in c['name']), None)
        if not pending_cat: return []
        txs = await self._get(f"/families/{family_id}/transactions?limit=100")
        if not txs: return []
        return [t for t in txs if t['category_id'] == pending_cat['id'] and t['user_id'] == user_id]

    async def get_daily_summary(self, family_id: int):
        """Збирає статистику для вечірнього AI-звіту напряму з SQL"""
        txs = await self._get(f"/families/{family_id}/transactions?limit=100")
        if not txs: return {"spent": 0, "unresolved": 0, "transactions_text": ""}

        today_str = datetime.now().strftime("%Y-%m-%d")
        spent, unresolved = 0, 0
        texts = []
        cats = await self.get_categories(family_id)
        cat_map = {c['id']: c['name'] for c in cats}

        for t in txs:
            if t['date'] != today_str: continue
            cat_name = cat_map.get(t['category_id'], "Інше")
            if "Очікує" in cat_name:
                unresolved += 1
            elif t['type'] == "Витрати" and "Переказ" not in cat_name:
                spent += t['amount']
                texts.append(f"- {cat_name}: {t['amount']} ₴ ({t['title']})")

        return {"spent": spent, "unresolved": unresolved, "transactions_text": "\n".join(texts)}

    # --- HISTORY & REPORTS (Заміна Гугл Таблиць) ---
    async def get_transactions_page(self, family_id: int, page: int, page_size: int = 5):
        skip = (page - 1) * page_size
        txs = await self._get(f"/families/{family_id}/transactions?skip={skip}&limit={page_size}")
        if not txs: return []
        cats = await self.get_categories(family_id)
        cat_map = {c['id']: c['name'] for c in cats}
        history = []
        for t in txs:
            d_str = datetime.strptime(t['date'], "%Y-%m-%d").strftime("%d.%m.%Y")
            history.append({
                "id": t['id'], "date": d_str, "amount": t['amount'],
                "category": cat_map.get(t['category_id'], "Інше"),
                "desc": t['title'], "who": ""
            })
        return history

    async def get_month_history_sql(self, family_id: int, year: int, month: int):
        """Генерує словник для створення PDF-звітів (раніше робилось через GS)"""
        txs = await self._get(f"/families/{family_id}/transactions?limit=1000")
        if not txs: return None
        income, expense = 0.0, 0.0
        cats_dict = {}
        cats = await self.get_categories(family_id)
        cat_map = {c['id']: c['name'] for c in cats}

        for t in txs:
            try:
                d = datetime.strptime(t['date'], "%Y-%m-%d")
                if d.year == year and d.month == month:
                    amt = t['amount']
                    cat_name = cat_map.get(t['category_id'], "Інше")
                    if t['type'] == "Поповнення":
                        income += amt
                    else:
                        expense += amt
                        if cat_name not in cats_dict: cats_dict[cat_name] = {'total': 0.0, 'txs': []}
                        cats_dict[cat_name]['total'] += amt
                        cats_dict[cat_name]['txs'].append({
                            "date": d.strftime("%d.%m.%Y"), "amount": amt, "desc": t['title'], "who": ""
                        })
            except Exception:
                pass
        if income == 0 and expense == 0: return None

        sorted_cats = sorted([{"name": k, "total": v['total'], "txs": v['txs']} for k, v in cats_dict.items()],
                             key=lambda x: x['total'], reverse=True)
        for c in sorted_cats: c['top_txs'] = sorted(c['txs'], key=lambda x: x['amount'], reverse=True)[:3]
        return {"income": income, "expense": expense, "balance": income - expense, "grouped_categories": sorted_cats}

    async def add_transfer(self, family_id: int, user_id: int, amount: float, note: str, from_who: str, to_who: str):
        cats = await self.get_categories(family_id)
        trans_cat = next((c['id'] for c in cats if "Переказ" in c['name']), None)
        if not trans_cat: return False
        date_str = datetime.now().strftime("%Y-%m-%d")
        await self.add_transaction(family_id, user_id, trans_cat, amount, "Витрати", f"Переказ -> {to_who} ({note})",
                                   date_str=date_str)
        await self.add_transaction(family_id, user_id, trans_cat, amount, "Поповнення",
                                   f"Отримано <- {from_who} ({note})", date_str=date_str)
        return True

    # --- SAAS ONBOARDING ---
    async def register_saas_user(self, tg_id: int, name: str, family_name: str, mono_token: str = None):
        new_f = await self._post("/families", {"name": family_name, "mono_token": mono_token})
        if new_f:
            family_id = new_f["id"]
            await self._post("/users", {"family_id": family_id, "name": name, "tg_id": tg_id})
            await self._post("/categories",
                             {"family_id": family_id, "icon": "❓", "name": "Очікує", "color": "#95a5a6",
                              "type": "expense"}, headers=_headers(x_family_id=family_id))
            await self._post("/categories",
                             {"family_id": family_id, "icon": "🔄", "name": "Переказ", "color": "#3498db",
                              "type": "expense"}, headers=_headers(x_family_id=family_id))
            return new_f["invite_code"]
        return None

    async def get_family_by_invite(self, invite_code: str):
        return await self._get(f"/families/by-invite/{invite_code}")


api_client = BimiAPIClient()
