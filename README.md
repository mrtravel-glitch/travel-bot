# Sayohat boti (MVP, AI'siz) — Render + Neon uchun tayyor

## 1-bosqich: GitHub'ga yuklash

```bash
cd travel_bot
git init
git add .
git commit -m "travel bot MVP"
```

GitHub'da yangi repo yarating (masalan `travel-bot`), so'ng:

```bash
git remote add origin https://github.com/FOYDALANUVCHI/travel-bot.git
git branch -M main
git push -u origin main
```

## 2-bosqich: Neon'da baza yaratish

1. https://neon.tech — ro'yxatdan o'ting, yangi loyiha (project) yarating.
2. Dashboard'da **Connection string** ni nusxalang — bunday ko'rinishda bo'ladi:
   `postgresql://user:password@ep-xxxx.neon.tech/dbname?sslmode=require`
3. Buni keyingi bosqichda `DATABASE_URL` sifatida ishlatasiz.

## 3-bosqich: Telegram tokenini olish

@BotFather — `/newbot` — bot nomini bering — tokenni saqlab qo'ying.

## 4-bosqich: Render'da deploy qilish

1. https://render.com — GitHub akkauntingiz bilan kiring.
2. **New +** → **Web Service** → GitHub repo'ingizni tanlang (`travel-bot`).
3. Sozlamalar:
   - **Environment:** Python 3
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `python main.py`
   - **Instance Type:** Free
4. **Environment Variables** bo'limida qo'shing:
   - `BOT_TOKEN` = BotFather'dan olgan token
   - `DATABASE_URL` = Neon'dan olgan connection string
5. **Create Web Service** bosing. Bir necha daqiqadan so'ng bot ishga tushadi
   va sizga `https://travel-bot-xxxx.onrender.com` kabi manzil beradi.

## 5-bosqich: UptimeRobot bilan uyg'oq tutish

Render bepul tarifi 15 daqiqa so'rovsiz qolsa "uxlab qoladi". Buning oldini olish uchun:

1. https://uptimerobot.com — ro'yxatdan o'ting.
2. **Add New Monitor** → Monitor Type: **HTTP(s)**
3. URL: Render bergan manzil (masalan `https://travel-bot-xxxx.onrender.com`)
4. Monitoring Interval: **5 daqiqa**
5. Saqlang — endi UptimeRobot har 5 daqiqada botni "uyg'otib" turadi.

## Natija

- Bot 24/7 ishlab turadi (Render + UptimeRobot tufayli)
- Ma'lumotlar Neon'da saqlanadi — Render qayta ishga tushsa ham yo'qolmaydi
- Kodni yangilash uchun: o'zgartiring → `git push` → Render avtomatik qayta deploy qiladi

## Fayllar tuzilmasi

- `main.py` — botni va veb-serverni ishga tushiradi
- `web.py` — Render/UptimeRobot uchun kichik HTTP server
- `config.py` — token va DB sozlamalari (muhit o'zgaruvchilaridan o'qiydi)
- `database.py` — Postgres (Neon) bilan ishlash
- `states.py`, `keyboards.py`, `handlers.py` — bot mantig'i
- `Procfile` — Render uchun ishga tushirish buyrug'i

## Mavjud komandalar

`/start`, `/help`, `/trip_add`, `/trips`, `/trip`, `/diary_add`, `/diary`,
`/place_add`, `/places`, `/contact_add`, `/contacts`, `/expense_add`,
`/expenses`, `/stats`, `/cancel`
