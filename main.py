import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand

from config import BOT_TOKEN
from database import init_db
from handlers import router
from web import start_web_server


BOT_COMMANDS = [
    ("trip_add", "🌍 Davlat/shahar qo'shish"),
    ("trips", "🏙 Davlat va shahar ma'lumoti"),
    ("budget", "🎯 Shahar byudjeti"),
    ("diary_add", "📔 Kundalik yozish"),
    ("diary", "📖 Kundalikni ko'rish"),
    ("place_add", "📍 Joy qo'shish"),
    ("places", "🗺 Joylarni ko'rish"),
    ("contact_add", "👤 Kontakt qo'shish"),
    ("contacts", "📇 Kontaktlar"),
    ("expense_add", "💰 Xarajat qo'shish"),
    ("expenses", "📊 Xarajatlar hisoboti"),
    ("file_add", "📎 Fayl saqlash"),
    ("files", "🗂 Fayllar"),
    ("weather", "🌤 Ob-havo"),
    ("weather_add", "📝 Ob-havo yozib qo'yish"),
    ("stats", "📈 Statistika"),
    ("help", "❓ Yordam"),
    ("cancel", "❌ Bekor qilish"),
]


async def main():
    logging.basicConfig(level=logging.INFO)
    init_db()

    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    dp.include_router(router)

    await bot.delete_webhook(drop_pending_updates=True)
    try:  # "/" bosilganda buyruqlar menyusi chiqadi — qo'lda yozib xato qilish shart emas
        await bot.set_my_commands([BotCommand(command=c, description=d) for c, d in BOT_COMMANDS])
    except Exception:
        logging.exception("Buyruqlar menyusini o'rnatib bo'lmadi")
    await start_web_server()  # Render portni kutadi + UptimeRobot shu yerga ping tashlaydi
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
