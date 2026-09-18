import os

BOT_TOKEN = os.environ.get("BOT_TOKEN", "PUT_YOUR_TOKEN_HERE")

# Neon (yoki boshqa Postgres) ulanish satri
DATABASE_URL = os.environ.get("DATABASE_URL", "")

# Ixtiyoriy: ob-havo uchun. https://openweathermap.org/api dan bepul kalit oling.
# Agar bo'sh qoldirsangiz, ob-havo funksiyasi shunchaki o'chirilgan holda ishlaydi.
OPENWEATHER_API_KEY = os.environ.get("OPENWEATHER_API_KEY", "")
