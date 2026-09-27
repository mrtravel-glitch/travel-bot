import os
import json
import hmac
import hashlib
from urllib.parse import parse_qsl

from aiohttp import web

from config import BOT_TOKEN
import database as db


# ---------- Telegram WebApp initData tekshiruvi ----------

def validate_init_data(init_data: str, bot_token: str):
    """Telegram yuborgan initData haqiqiyligini tekshiradi.
    To'g'ri bo'lsa dict (user, auth_date, ...) qaytaradi, aks holda None."""
    try:
        parsed = dict(parse_qsl(init_data, strict_parsing=True))
    except ValueError:
        return None
    received_hash = parsed.pop("hash", None)
    if not received_hash:
        return None
    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(parsed.items()))
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    calculated_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calculated_hash, received_hash):
        return None
    return parsed


def get_user_id(request) -> int | None:
    init_data = request.headers.get("X-Telegram-Init-Data", "")
    parsed = validate_init_data(init_data, BOT_TOKEN)
    if not parsed:
        return None
    user = json.loads(parsed.get("user", "{}"))
    return user.get("id")


def auth_required(handler):
    async def wrapper(request):
        user_id = get_user_id(request)
        if user_id is None:
            return web.json_response({"error": "unauthorized"}, status=401)
        request["user_id"] = user_id
        return await handler(request)
    return wrapper


# ---------- Oddiy ping (Render/UptimeRobot uchun, o'zgarmadi) ----------

async def handle_ping(request):
    return web.Response(text="Bot ishlayapti ✅")


# ---------- API: umumiy holat ----------

@auth_required
async def api_overview(request):
    user_id = request["user_id"]
    stats = db.get_stats(user_id)
    countries = db.get_countries(user_id)
    result = []
    for c in countries:
        cities = db.get_cities(c["id"])
        city_list = []
        for city in cities:
            trips = db.get_trips(city["id"])
            city_list.append({**city, "trips": trips})
        result.append({**c, "cities": city_list})
    return web.json_response({"stats": stats, "countries": result})


# ---------- API: bitta safar detali ----------

@auth_required
async def api_trip_detail(request):
    trip_id = int(request.match_info["trip_id"])
    trip = db.get_trip(trip_id)
    if not trip:
        return web.json_response({"error": "not_found"}, status=404)
    city = db.get_city(trip["city_id"])
    country = db.get_country(city["country_id"])
    # xavfsizlik: bu safar shu foydalanuvchiga tegishli ekanini tekshirish
    if country["user_id"] != request["user_id"]:
        return web.json_response({"error": "forbidden"}, status=403)

    return web.json_response({
        "trip": trip,
        "city": city,
        "country": country,
        "expenses": db.get_expenses(trip_id),
        "expense_totals": db.get_expense_totals_by_currency(trip_id),
        "diary": db.get_diary(trip_id),
        "contacts": db.get_contacts(trip_id),
        "files": db.get_files(trip_id),
        "weather": db.get_weather_notes(trip_id),
        "places": db.get_places(trip["city_id"]),
    })


# ---------- API: xarajat qo'shish ----------

@auth_required
async def api_add_expense(request):
    trip_id = int(request.match_info["trip_id"])
    trip = db.get_trip(trip_id)
    if not trip:
        return web.json_response({"error": "not_found"}, status=404)
    city = db.get_city(trip["city_id"])
    country = db.get_country(city["country_id"])
    if country["user_id"] != request["user_id"]:
        return web.json_response({"error": "forbidden"}, status=403)

    body = await request.json()
    row = db.add_expense(
        trip_id,
        body.get("category", "boshqa"),
        body["amount"],
        body.get("currency", "UZS"),
        body.get("date", ""),
        body.get("note", ""),
    )
    return web.json_response({"ok": True, "expense": row})


# ---------- API: kundalik yozuv qo'shish ----------

@auth_required
async def api_add_diary(request):
    trip_id = int(request.match_info["trip_id"])
    trip = db.get_trip(trip_id)
    if not trip:
        return web.json_response({"error": "not_found"}, status=404)
    city = db.get_city(trip["city_id"])
    country = db.get_country(city["country_id"])
    if country["user_id"] != request["user_id"]:
        return web.json_response({"error": "forbidden"}, status=403)

    body = await request.json()
    row = db.add_diary(trip_id, body.get("date", ""), body.get("text", ""))
    return web.json_response({"ok": True, "diary": row})


# ---------- Mini App sahifasi (frontend shu yerda, alohida fayl shart emas) ----------

async def handle_app(request):
    return web.FileResponse(os.path.join(os.path.dirname(__file__), "static", "app.html"))


async def start_web_server():
    app = web.Application()
    app.router.add_get("/", handle_ping)
    app.router.add_get("/app", handle_app)
    app.router.add_get("/api/overview", api_overview)
    app.router.add_get("/api/trip/{trip_id}", api_trip_detail)
    app.router.add_post("/api/trip/{trip_id}/expense", api_add_expense)
    app.router.add_post("/api/trip/{trip_id}/diary", api_add_diary)
    static_dir = os.path.join(os.path.dirname(__file__), "static")
    app.router.add_static("/static/", static_dir)

    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
