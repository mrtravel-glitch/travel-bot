import os
import json
from decimal import Decimal
from datetime import date, datetime

from aiohttp import web

import database as db


# ---------- JSON: Postgres NUMERIC/TIMESTAMP ni JSON'ga o'girish ----------

def _json_default(obj):
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    raise TypeError(f"Not JSON serializable: {obj!r}")


def json_response(data, status=200):
    return web.json_response(
        data, status=status, dumps=lambda d: json.dumps(d, default=_json_default)
    )


# ---------- Token orqali autentifikatsiya ----------

def get_user_id(request):
    token = request.query.get("token", "")
    if not token:
        return None
    return db.get_user_id_by_token(token)


def auth_required(handler):
    async def wrapper(request):
        user_id = get_user_id(request)
        if user_id is None:
            return json_response({"error": "unauthorized"}, status=401)
        request["user_id"] = user_id
        return await handler(request)
    return wrapper


def owns_country(user_id, country_id):
    c = db.get_country(country_id)
    return bool(c and c["user_id"] == user_id)


def owns_city(user_id, city_id):
    city = db.get_city(city_id)
    return bool(city and owns_country(user_id, city["country_id"]))


def owns_trip(user_id, trip_id):
    trip = db.get_trip(trip_id)
    return bool(trip and owns_city(user_id, trip["city_id"]))


# ---------- Ping (Render/UptimeRobot uchun) ----------

async def handle_ping(request):
    return web.Response(text="Bot ishlayapti ✅")


async def preflight(request):
    return web.Response()


# ---------- Umumiy holat ----------

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
    return json_response({"stats": stats, "countries": result})


@auth_required
async def api_add_country(request):
    body = await request.json()
    name = (body.get("name") or "").strip()
    if not name:
        return json_response({"error": "name_required"}, status=400)
    row = db.add_country(request["user_id"], name)
    return json_response({"ok": True, "country": row})


@auth_required
async def api_add_city(request):
    body = await request.json()
    country_id = int(body.get("country_id", 0))
    name = (body.get("name") or "").strip()
    if not name or not owns_country(request["user_id"], country_id):
        return json_response({"error": "invalid"}, status=400)
    row = db.add_city(country_id, name)
    return json_response({"ok": True, "city": row})


@auth_required
async def api_add_trip(request):
    body = await request.json()
    city_id = int(body.get("city_id", 0))
    if not owns_city(request["user_id"], city_id):
        return json_response({"error": "invalid"}, status=400)
    row = db.add_trip(
        city_id=city_id,
        status=body.get("status", "wishlist"),
        note=body.get("note"),
        budget_amount=body.get("budget_amount"),
        budget_currency=body.get("budget_currency"),
        city_currency=body.get("city_currency"),
        exchange_rate=body.get("exchange_rate"),
    )
    return json_response({"ok": True, "trip": row})


# ---------- Bitta safar detali ----------

@auth_required
async def api_trip_detail(request):
    trip_id = int(request.match_info["trip_id"])
    if not owns_trip(request["user_id"], trip_id):
        return json_response({"error": "forbidden"}, status=403)
    trip = db.get_trip(trip_id)
    city = db.get_city(trip["city_id"])
    country = db.get_country(city["country_id"])
    return json_response({
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


@auth_required
async def api_add_expense(request):
    trip_id = int(request.match_info["trip_id"])
    if not owns_trip(request["user_id"], trip_id):
        return json_response({"error": "forbidden"}, status=403)
    body = await request.json()
    row = db.add_expense(
        trip_id,
        body.get("category", "boshqa"),
        body["amount"],
        body.get("currency", "UZS"),
        body.get("date", ""),
        body.get("note", ""),
    )
    return json_response({"ok": True, "expense": row})


@auth_required
async def api_add_diary(request):
    trip_id = int(request.match_info["trip_id"])
    if not owns_trip(request["user_id"], trip_id):
        return json_response({"error": "forbidden"}, status=403)
    body = await request.json()
    row = db.add_diary(trip_id, body.get("date", ""), body.get("text", ""))
    return json_response({"ok": True, "diary": row})


@auth_required
async def api_add_place(request):
    trip_id = int(request.match_info["trip_id"])
    if not owns_trip(request["user_id"], trip_id):
        return json_response({"error": "forbidden"}, status=403)
    trip = db.get_trip(trip_id)
    body = await request.json()
    row = db.add_place(
        city_id=trip["city_id"],
        name=body.get("name", ""),
        ptype=body.get("type", "boshqa"),
        is_halal=body.get("is_halal"),
        price=body.get("price"),
        rating=body.get("rating"),
        address=body.get("address"),
        latitude=None,
        longitude=None,
        notes=body.get("notes"),
    )
    return json_response({"ok": True, "place": row})


@auth_required
async def api_add_contact(request):
    trip_id = int(request.match_info["trip_id"])
    if not owns_trip(request["user_id"], trip_id):
        return json_response({"error": "forbidden"}, status=403)
    body = await request.json()
    row = db.add_contact(trip_id, body.get("name", ""), body.get("contact_info"), body.get("notes"))
    return json_response({"ok": True, "contact": row})


@auth_required
async def api_add_weather(request):
    trip_id = int(request.match_info["trip_id"])
    if not owns_trip(request["user_id"], trip_id):
        return json_response({"error": "forbidden"}, status=403)
    body = await request.json()
    row = db.add_weather_note(trip_id, body.get("date", ""), body.get("conditions"), body.get("custom_text"))
    return json_response({"ok": True, "weather": row})

# ---------- Xarita: koordinata va rasmlar ----------
@auth_required
async def api_city_coords(request):
    city_id = int(request.match_info["city_id"])
    if not owns_city(request["user_id"], city_id):
        return json_response({"error": "forbidden"}, status=403)
    body = await request.json()
    db.update_city_coords(city_id, body.get("latitude"), body.get("longitude"))
    return json_response({"ok": True})

@auth_required
async def api_city_photo(request):
    city_id = int(request.match_info["city_id"])
    if not owns_city(request["user_id"], city_id):
        return json_response({"error": "forbidden"}, status=403)
    body = await request.json()
    db.update_city_photo(city_id, body.get("photo"))
    return json_response({"ok": True})

@auth_required
async def api_country_photo(request):
    country_id = int(request.match_info["country_id"])
    if not owns_country(request["user_id"], country_id):
        return json_response({"error": "forbidden"}, status=403)
    body = await request.json()
    db.update_country_photo(country_id, body.get("photo"))
    return json_response({"ok": True})
# ---------- CORS middleware ----------

@web.middleware
async def cors_middleware(request, handler):
    if request.method == "OPTIONS":
        resp = web.Response()
    else:
        try:
            resp = await handler(request)
        except web.HTTPException as ex:
            resp = ex
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return resp


async def start_web_server():
    app = web.Application(middlewares=[cors_middleware], client_max_size=8 * 1024 * 1024)
    app.router.add_get("/", handle_ping)

    app.router.add_get("/api/overview", api_overview)
    app.router.add_post("/api/country", api_add_country)
    app.router.add_post("/api/city", api_add_city)
    app.router.add_post("/api/trip", api_add_trip)
    app.router.add_get("/api/trip/{trip_id}", api_trip_detail)
    app.router.add_post("/api/trip/{trip_id}/expense", api_add_expense)
    app.router.add_post("/api/trip/{trip_id}/diary", api_add_diary)
    app.router.add_post("/api/trip/{trip_id}/place", api_add_place)
    app.router.add_post("/api/trip/{trip_id}/contact", api_add_contact)
    app.router.add_post("/api/trip/{trip_id}/weather", api_add_weather)
    app.router.add_post("/api/city/{city_id}/coords", api_city_coords)
app.router.add_post("/api/city/{city_id}/photo", api_city_photo)
app.router.add_post("/api/country/{country_id}/photo", api_country_photo)

    for path in ["/api/country", "/api/city", "/api/trip"]:
        app.router.add_route("OPTIONS", path, preflight)
    for path in ["/api/city/{city_id}/coords", "/api/city/{city_id}/photo", "/api/country/{country_id}/photo"]:
        app.router.add_route("OPTIONS", path, preflight)
    for sub in ["expense", "diary", "place", "contact", "weather"]:
        app.router.add_route("OPTIONS", "/api/trip/{trip_id}/" + sub, preflight)

    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
