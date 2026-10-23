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
        url = f"{self.base_url}{endpoint}"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers or _API_HEADERS, timeout=5) as resp:
                    if resp.status == 200:
                        return await resp.json()
                    body = (await resp.text())[:200]
                    logger.error(f"API GET {url} -> HTTP {resp.status}: {body}")
        except Exception as e:
            logger.error(f"API GET {url} EXCEPTION {type(e).__name__}: {e}")
        return None

    async def _post(self, endpoint, payload, method="post", headers=None, timeout=5):
        url = f"{self.base_url}{endpoint}"
        try:
            async with aiohttp.ClientSession() as session:
                req = getattr(session, method)
                async with req(url, json=payload, headers=headers or _API_HEADERS, timeout=timeout) as resp:
                    if resp.status in (200, 201):
                        return await resp.json()
                    body = (await resp.text())[:200]
                    logger.error(f"API {method.upper()} {url} -> HTTP {resp.status}: {body}")
        except Exception as e:
            logger.error(f"API {method.upper()} {url} EXCEPTION {type(e).__name__}: {e}")
        return None

    async def _delete(self, endpoint, headers=None):
        url = f"{self.base_url}{endpoint}"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.delete(url, headers=headers or _API_HEADERS, timeout=5) as resp:
                    if resp.status in (200, 204):
                        return True
                    body = (await resp.text())[:200]
                    logger.error(f"API DELETE {url} -> HTTP {resp.status}: {body}")
        except Exception as e:
            logger.error(f"API DELETE {url} EXCEPTION {type(e).__name__}: {e}")
        return False

    # --- HOUSING («Житло»): reminders & outage sync are computed by the backend ---
    async def get_housing_reminders(self):
        return await self._get("/system/housing/reminders") or []

    async def ack_housing_reminders(self, items: list):
        return await self._post("/system/housing/reminders/ack", {"items": items})

    async def sync_bank_jars(self):
        # Monobank «банки» → goals in Bimi; transfers to own jars are not spending
        return await self._post("/system/housing/jars/sync", {}, timeout=90)

    async def sync_power_outages(self):
        # first run backfills the svitlobot channel history (several pages) — allow time
        return await self._post("/system/housing/outages/sync", {}, timeout=90)

    # --- CORE METHODS ---
    async def get_me(self, tg_id: int):
        return await self._get(f"/auth/me?tg_id={tg_id}")

    async def get_categories(self, family_id: int, cat_type: str = None):
        cats = await self._get(f"/families/{family_id}/categories")
        if not cats: return []
        if cat_type: return [c for c in cats if c['type'] == cat_type]
        return cats

    async def create_category(self, family_id: int, name: str, cat_type: str = "expense",
                              icon: str = "🗂️", color: str = "#7f8c8d"):
        return await self._post("/categories",
                                {"family_id": family_id, "icon": icon, "name": name,
                                 "color": color, "type": cat_type},
                                headers=_headers(x_family_id=family_id))

    async def add_transaction(self, family_id, user_id, cat_id, amount, t_type, title, account="Готівка", mono_id=None,
                              date_str=None, note=None, currency="UAH"):
        payload = {
            "family_id": family_id, "user_id": user_id, "category_id": cat_id,
            "amount": float(amount), "type": t_type, "title": title,
            "account": account, "mono_id": mono_id, "date": date_str or datetime.now().strftime("%Y-%m-%d"),
            "currency": currency or "UAH",
        }
        if note:
            payload["note"] = note
        return await self._post("/transactions", payload, headers=_headers(x_family_id=family_id))

    async def update_tx_by_mono(self, mono_id: str, category_id: int = None, note: str = None):
        payload = {}
        if category_id: payload["category_id"] = category_id
        if note: payload["note"] = note  # опис користувача — окремо від title (merchant)
        return await self._post(f"/transactions/by-mono/{mono_id}", payload, method="put")

    async def update_transaction(self, tx_id: int, category_id: int = None, note: str = None):
        """Оновлення транзакції за її id (для Inbox Zero pending, які можуть не мати mono_id)."""
        payload = {}
        if category_id is not None: payload["category_id"] = category_id
        if note: payload["note"] = note
        return await self._post(f"/transactions/{tx_id}", payload, method="put")

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
        """Генерує словник для створення PDF-звітів, згрупований ПО ВАЛЮТАХ.
        Повертає:
          income/expense/balance — тільки UAH (зворотна сумісність),
          currencies — {code: {"income": .., "expense": .., "balance": ..,
                               "grouped_categories": [{name, total, txs, top_txs}]}}
        """
        txs = await self._get(f"/families/{family_id}/transactions?limit=1000")
        if not txs: return None
        cats = await self.get_categories(family_id)
        cat_map = {c['id']: c['name'] for c in cats}

        # currency -> {income, expense, cats_dict}
        by_cur = {}

        for t in txs:
            try:
                if t.get('type') == "Переказ":
                    continue  # перекази між джерелами — не дохід/витрата у звітах
                if t.get('jar_id') is not None:
                    continue  # скарбнички — внутрішній рух, не дохід/витрата
                d = datetime.strptime(t['date'], "%Y-%m-%d")
                if d.year == year and d.month == month:
                    amt = t['amount']
                    cur = t.get('currency') or "UAH"
                    bucket = by_cur.setdefault(cur, {"income": 0.0, "expense": 0.0, "cats": {}})
                    cat_name = cat_map.get(t['category_id'], "Інше")
                    if t['type'] == "Поповнення":
                        bucket["income"] += amt
                    else:
                        bucket["expense"] += amt
                        cd = bucket["cats"].setdefault(cat_name, {'total': 0.0, 'txs': []})
                        cd['total'] += amt
                        cd['txs'].append({
                            "date": d.strftime("%d.%m.%Y"), "amount": amt,
                            "desc": t['title'],
                            "who": t.get('user_name') or "",
                            "currency": cur,
                        })
            except Exception:
                pass
        if not by_cur:
            return None

        currencies = {}
        for cur, b in by_cur.items():
            sorted_cats = sorted([{"name": k, "total": v['total'], "txs": v['txs']}
                                  for k, v in b["cats"].items()],
                                 key=lambda x: x['total'], reverse=True)
            for c in sorted_cats:
                c['top_txs'] = sorted(c['txs'], key=lambda x: x['amount'], reverse=True)[:3]
            currencies[cur] = {
                "income": round(b["income"], 2),
                "expense": round(b["expense"], 2),
                "balance": round(b["income"] - b["expense"], 2),
                "grouped_categories": sorted_cats,
            }

        # Зворотна сумісність: головні поля — UAH (або перша доступна валюта, якщо UAH немає)
        main = currencies.get("UAH") or next(iter(currencies.values()))
        return {"income": main["income"], "expense": main["expense"],
                "balance": main["balance"],
                "grouped_categories": main["grouped_categories"],
                "currencies": currencies}

    async def create_transfer(self, family_id: int, user_id: int, amount: float,
                              from_account: str, to_account: str):
        """Переказ між джерелами (Cash ↔ Bank). Пара зігнованих 'Переказ'-транзакцій,
        не впливає на доходи/витрати."""
        return await self._post("/transactions/transfer", {
            "family_id": family_id, "user_id": user_id, "amount": float(amount),
            "from_account": from_account, "to_account": to_account,
        }, headers=_headers(x_family_id=family_id))

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
