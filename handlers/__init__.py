# handlers package
# Спільні екземпляри бота та диспетчера живуть тут, щоб уникнути циклічних імпортів.
# main.py лише імпортує їх і стартує polling.
from aiogram import Bot, Dispatcher

from config import BOT_TOKEN

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

from handlers import base, expenses, families, monobank, smart_receipts, scratchpad  # noqa: E402,F401
