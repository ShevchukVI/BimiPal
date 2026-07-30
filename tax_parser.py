import aiohttp
import logging

logger = logging.getLogger(__name__)

async def fetch_tax_receipt(fn_number: str):
    """Шукає чек на сайті ДПС (cabinet.tax.gov.ua) за його Фіскальним Номером (ФН)."""
    
    # URL для пошуку відкритого чека в ДПС
    url = f"https://cabinet.tax.gov.ua/cashregs/api/check/find?fn={fn_number}"
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=5) as response:
                if response.status == 200:
                    data = await response.json()
                    
                    # Перевіряємо, чи ДПС повернула товари
                    if "goods" in data and data["goods"]:
                        items = []
                        total = 0.0
                        
                        for item in data["goods"]:
                            name = item.get("name", "Невідомий товар")
                            # У ДПС суми вказані в копійках, ділимо на 100
                            price = item.get("cost", 0) / 100.0
                            items.append(f"{name} ({price} грн)")
                            total += price
                            
                        return {
                            "shop_name": data.get("companyName", "Невідомий магазин"),
                            "total_amount": total,
                            "items": items
                        }
                    else:
                        return None
                else:
                    logger.warning(f"ДПС повернула статус {response.status} для чека {fn_number}")
                    return None
    except Exception as e:
        logger.error(f"Помилка парсингу ДПС чека: {e}")
        return None