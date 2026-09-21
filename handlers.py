import os
import re
import tempfile
from datetime import date

import aiohttp
import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery, InputMediaPhoto, FSInputFile

import database as db
import keyboards as kb
from states import (
    TripAdd, TripsNewCity, DiaryAdd, PlaceAdd, ContactAdd, ExpenseAdd, FileAdd, ManageEdit,
)

router = Router()

TYPE_NAMES = {"hotel": "🏨 Mehmonxona", "restaurant": "🍽 Restoran", "attraction": "🏛 Ko'rish joyi"}

WEATHER_CODES = {
    0: "☀️ Ochiq osmon", 1: "🌤 Deyarli ochiq", 2: "⛅ Qisman bulutli", 3: "☁️ Bulutli",
    45: "🌫 Tuman", 48: "🌫 Muzli tuman",
    51: "🌦 Yengil yomg'ir", 53: "🌦 Yomg'ir", 55: "🌧 Kuchli yomg'ir",
    61: "🌧 Yomg'ir", 63: "🌧 Yomg'ir", 65: "🌧 Kuchli yomg'ir",
    71: "🌨 Qor", 73: "🌨 Qor", 75: "❄️ Kuchli qor",
    80: "🌦 Jala", 81: "🌦 Jala", 82: "⛈ Kuchli jala",
    95: "⛈ Momaqaldiroq",
}

weather_cache = {}


def fmt_money(amount):
    return f"{amount:,.0f}".replace(",", " ")


MONEY_MULTIPLIERS = [
    (re.compile(r"mlrd|milliard|billion", re.IGNORECASE), 1_000_000_000),
    (re.compile(r"mln|million", re.IGNORECASE), 1_000_000),
    (re.compile(r"ming|k\b", re.IGNORECASE), 1_000),
]

BUDGET_PERIOD_LABELS = {"daily": "kunlik", "monthly": "oylik", "total": "umumiy"}


def parse_money(text):
    """'3000000', '3 mln', '500 ming', '1.5 mlrd' kabi kiritishlarni raqamga aylantiradi."""
    if not text:
        return None
    t = text.strip().lower()
    if not t:
        return None
    multiplier = 1
    for pattern, mult in MONEY_MULTIPLIERS:
        if pattern.search(t):
            multiplier = mult
            t = pattern.sub("", t)
            break
    t = t.replace(" ", "").replace(",", "")
    t = re.sub(r"[^0-9.\-]", "", t)
    if not t or t in ("-", "."):
        return None
    try:
        return float(t) * multiplier
    except ValueError:
        return None


def build_city_profile(country, city):
    emoji = "✅" if country["status"] == "visited" else "🎯"
    text = f"{emoji} <b>{country['name']}</b> — 🏙 {city['name']}"
    if country["notes"]:
        text += f"\n📝 {country['notes']}"

    places = db.get_places(city["id"])
    diary = db.get_diary(city["id"])
    contacts = db.get_contacts(city["id"])
    files = db.get_files(city["id"])
    city_summary = db.get_expense_summary(city["id"])
    city_total = sum(r["total"] for r in city_summary) if city_summary else 0
    country_total = db.get_country_expense_total(country["id"])

    text += (
        f"\n\n📍 Joylar: {len(places)}\n📔 Kundalik: {len(diary)}\n"
        f"👤 Kontaktlar: {len(contacts)}\n📎 Fayllar: {len(files)}\n"
        f"💰 Shu shahar xarajati: {fmt_money(city_total)} so'm\n"
        f"🌍 {country['name']} bo'yicha jami: {fmt_money(country_total)} so'm"
    )
    if country["budget"]:
        period = BUDGET_PERIOD_LABELS.get(country.get("budget_period") or "total", "umumiy")
        qoldiq = float(country["budget"]) - country_total
        holat = "✅" if qoldiq >= 0 else "⚠️"
        text += (
            f"\n🎯 Byudjet: {fmt_money(country['budget'])} so'm ({period})"
            f"\n{holat} Qoldiq: {fmt_money(qoldiq)} so'm"
        )
    return text


async def fetch_weather(city_name):
    timeout = aiohttp.ClientTimeout(total=10)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            geo_url = "https://geocoding-api.open-meteo.com/v1/search"
            async with session.get(geo_url, params={"name": city_name, "count": 1}) as resp:
                geo = await resp.json()
            results = geo.get("results")
            if not results:
                return None
            lat, lon = results[0]["latitude"], results[0]["longitude"]
            found_name = results[0]["name"]

            forecast_url = "https://api.open-meteo.com/v1/forecast"
            params = {"latitude": lat, "longitude": lon, "current_weather": "true"}
            async with session.get(forecast_url, params=params) as resp:
                data = await resp.json()
            cw = data.get("current_weather")
            if not cw:
                return None
            return {
                "city": found_name, "temp": cw["temperature"],
                "wind": cw["windspeed"], "code": cw["weathercode"],
            }
    except (aiohttp.ClientError, TimeoutError):
        return None


# ================= BASIC =================

@router.message(Command("start"))
async def cmd_start(message: Message):
    await message.answer(
        "👋 Salom! Men sizning shaxsiy sayohat botingizman.\n\n"
        "Davlat → Shahar → Joy tartibida saqlayman: har bir davlat ichida "
        "bir nechta shahar, har shaharda mehmonxona/restoran/ko'rish joylari, "
        "kundalik, kontaktlar, fayllar va xarajatlar bo'lishi mumkin.\n\n"
        "Boshlash uchun: /trip_add — yangi davlat qo'shing\n"
        "Barcha komandalar: /help"
    )


@router.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(
        "📋 <b>Komandalar</b>\n\n"
        "<b>Davlat / Shahar</b>\n"
        "/trip_add — yangi davlat qo'shish (+birinchi shahar)\n"
        "/trips — davlat va shahar tanlash (faol qilish uchun)\n"
        "/trip — hozirgi faol shahar haqida to'liq ma'lumot\n\n"
        "<b>Kundalik</b> (faol shaharga)\n"
        "/diary_add — yozuv qo'shish\n"
        "/diary — yozuvlarni ko'rish\n\n"
        "<b>Joylar</b>\n"
        "/place_add — joy qo'shish (davlat/shahar tanlash bilan)\n"
        "/places — joylarni ko'rish (davlat → shahar → tur)\n\n"
        "<b>Kontaktlar</b> (faol shaharga)\n"
        "/contact_add — kontakt qo'shish\n"
        "/contacts — kontaktlar ro'yxati\n\n"
        "<b>Xarajatlar</b> (faol shaharga)\n"
        "/expense_add — xarajat qo'shish\n"
        "/expenses — shahar + davlat bo'yicha hisobot\n\n"
        "<b>Fayllar</b> (faol shaharga)\n"
        "/file_add — chipta/hujjat saqlash\n"
        "/files — fayllarni ko'rish\n\n"
        "<b>Ob-havo</b>\n"
        "/weather — faol shahar uchun joriy ob-havo\n\n"
        "<b>Statistika</b>\n"
        "/stats — umumiy statistika\n"
        "/export — barcha ma'lumotlarni Excel fayl qilib olish\n\n"
        "<b>Boshqarish</b>\n"
        "/manage — davlat/shahar/joy/kontakt/kundalik/xarajat/faylni "
        "tahrirlash yoki o'chirish\n\n"
        "❌ /cancel — joriy amalni bekor qilish"
    )


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Bekor qilindi ❌")


async def require_active_city(message: Message):
    city = db.get_active_city(message.from_user.id)
    if not city:
        await message.answer(
            "Avval faol shaharni tanlang: /trips\nYoki yangi davlat qo'shing: /trip_add"
        )
        return None
    return city


# ================= TRIP_ADD (davlat + birinchi shahar) =================

@router.message(Command("trip_add"))
async def trip_add_start(message: Message, state: FSMContext):
    countries = db.get_countries(message.from_user.id)
    if countries:
        await state.set_state(TripAdd.select_country)
        await message.answer(
            "🌍 Qaysi davlat?", reply_markup=kb.country_select_kb(countries, prefix="tripadd_country")
        )
    else:
        await state.set_state(TripAdd.new_country_name)
        await message.answer("🌍 Davlat nomini kiriting (masalan: O'zbekiston):")


@router.callback_query(TripAdd.select_country, F.data.startswith("tripadd_country:"))
async def trip_add_select_country(callback: CallbackQuery, state: FSMContext):
    val = callback.data.split(":", 1)[1]
    if val == "new":
        await state.set_state(TripAdd.new_country_name)
        await callback.message.edit_text("🌍 Yangi davlat nomini kiriting:")
        await callback.answer()
        return
    country_id = int(val)
    await state.update_data(country_id=country_id)
    await _trip_ask_city(callback.message.edit_text, state, country_id)
    await callback.answer()


@router.message(TripAdd.new_country_name)
async def trip_add_new_country_name(message: Message, state: FSMContext):
    name = message.text.strip()
    existing = db.find_country_by_name(message.from_user.id, name)
    if existing:
        await state.update_data(country_id=existing["id"])
        await message.answer(f"ℹ️ \"{existing['name']}\" allaqachon mavjud, unga bog'landi.")
        await _trip_ask_city(message.answer, state, existing["id"])
        return
    await state.update_data(new_country_name=name)
    await state.set_state(TripAdd.status)
    await message.answer("Holati qanday?", reply_markup=kb.status_kb())


@router.callback_query(TripAdd.status, F.data.startswith("status:"))
async def trip_add_status(callback: CallbackQuery, state: FSMContext):
    status = callback.data.split(":")[1]
    await state.update_data(status=status)
    await state.set_state(TripAdd.budget)
    await callback.message.edit_text(
        "💰 Rejalashtirilgan byudjet? (masalan: 3000000, yoki \"3 mln\", \"500 ming\")",
        reply_markup=kb.skip_kb("skip_budget"),
    )
    await callback.answer()


@router.message(TripAdd.budget)
async def trip_add_budget(message: Message, state: FSMContext):
    budget = parse_money(message.text)
    if budget is None:
        await message.answer("Tushunmadim. Masalan: 3000000, \"3 mln\", \"500 ming\" — yoki tugmani bosing.")
        return
    await state.update_data(budget=budget)
    await state.set_state(TripAdd.budget_period)
    await message.answer("Bu byudjet qanday?", reply_markup=kb.budget_period_kb())


@router.callback_query(TripAdd.budget, F.data == "skip_budget")
async def trip_add_budget_skip(callback: CallbackQuery, state: FSMContext):
    await state.update_data(budget=None, budget_period=None)
    await state.set_state(TripAdd.notes)
    await callback.message.edit_text("Izoh qoldirmoqchimisiz?", reply_markup=kb.skip_kb("skip_trip_notes"))
    await callback.answer()


@router.callback_query(TripAdd.budget_period, F.data.startswith("bperiod:"))
async def trip_add_budget_period(callback: CallbackQuery, state: FSMContext):
    period = callback.data.split(":")[1]
    await state.update_data(budget_period=period)
    await state.set_state(TripAdd.notes)
    await callback.message.edit_text("Izoh qoldirmoqchimisiz?", reply_markup=kb.skip_kb("skip_trip_notes"))
    await callback.answer()


@router.message(TripAdd.notes)
async def trip_add_notes(message: Message, state: FSMContext):
    await _trip_add_finish(message.from_user.id, state, message.text.strip(), message.answer)


@router.callback_query(TripAdd.notes, F.data == "skip_trip_notes")
async def trip_add_notes_skip(callback: CallbackQuery, state: FSMContext):
    await _trip_add_finish(callback.from_user.id, state, None, callback.message.edit_text)
    await callback.answer()


async def _trip_add_finish(user_id, state, notes, answer_func):
    data = await state.get_data()
    country_id = db.add_country(
        user_id, data["new_country_name"], data["status"],
        data.get("budget"), data.get("budget_period"), notes,
    )
    await state.update_data(country_id=country_id)
    await _trip_ask_city(answer_func, state, country_id)


async def _trip_ask_city(answer_func, state: FSMContext, country_id):
    cities = db.get_cities(country_id)
    if cities:
        await state.set_state(TripAdd.select_city)
        await answer_func("🏙 Qaysi shahar?", reply_markup=kb.city_select_kb(cities, prefix="tripadd_city"))
    else:
        await state.set_state(TripAdd.new_city_name)
        await answer_func("🏙 Shahar nomini kiriting:")


@router.callback_query(TripAdd.select_city, F.data.startswith("tripadd_city:"))
async def trip_add_select_city(callback: CallbackQuery, state: FSMContext):
    val = callback.data.split(":", 1)[1]
    data = await state.get_data()
    country_id = data["country_id"]
    if val == "new":
        await state.set_state(TripAdd.new_city_name)
        await callback.message.edit_text("🏙 Yangi shahar nomini kiriting:")
        await callback.answer()
        return
    city_id = int(val)
    db.set_active(callback.from_user.id, country_id, city_id)
    country = db.get_country(country_id)
    city = db.get_city(city_id)
    await state.clear()
    await callback.message.edit_text(build_city_profile(country, city))
    await callback.answer()


@router.message(TripAdd.new_city_name)
async def trip_add_new_city_name(message: Message, state: FSMContext):
    data = await state.get_data()
    country_id = data["country_id"]
    name = message.text.strip()
    existing = db.find_city_by_name(country_id, name)
    prefix_msg = ""
    if existing:
        city_id = existing["id"]
        prefix_msg = "ℹ️ Bu shahar allaqachon mavjud, unga bog'landi.\n\n"
    else:
        city_id = db.add_city(country_id, name)
    db.set_active(message.from_user.id, country_id, city_id)
    country = db.get_country(country_id)
    city = db.get_city(city_id)
    await state.clear()
    await message.answer(prefix_msg + build_city_profile(country, city))


# ================= TRIPS (davlat + shahar tanlash) =================

@router.message(Command("trips"))
async def cmd_trips(message: Message):
    countries = db.get_countries(message.from_user.id)
    if not countries:
        await message.answer("Hali davlat yo'q. /trip_add orqali qo'shing.")
        return
    await message.answer(
        "🌍 Davlatni tanlang:", reply_markup=kb.country_select_kb(countries, prefix="trips_country", show_add=False)
    )


@router.callback_query(F.data.startswith("trips_country:"))
async def cb_trips_country(callback: CallbackQuery):
    country_id = int(callback.data.split(":")[1])
    cities = db.get_cities(country_id)
    await callback.message.edit_text(
        "🏙 Shaharni tanlang:", reply_markup=kb.city_select_kb(cities, prefix=f"trips_city:{country_id}")
    )
    await callback.answer()


@router.callback_query(F.data.startswith("trips_city:"))
async def cb_trips_city(callback: CallbackQuery, state: FSMContext):
    _, country_id_s, val = callback.data.split(":")
    country_id = int(country_id_s)
    if val == "new":
        await state.update_data(new_city_country_id=country_id)
        await state.set_state(TripsNewCity.name)
        await callback.message.edit_text("🏙 Yangi shahar nomini kiriting:")
        await callback.answer()
        return
    city_id = int(val)
    db.set_active(callback.from_user.id, country_id, city_id)
    country = db.get_country(country_id)
    city = db.get_city(city_id)
    await callback.message.edit_text(build_city_profile(country, city))
    await callback.answer()


@router.message(TripsNewCity.name)
async def trips_new_city_name(message: Message, state: FSMContext):
    data = await state.get_data()
    country_id = data["new_city_country_id"]
    city_id = db.add_city(country_id, message.text.strip())
    db.set_active(message.from_user.id, country_id, city_id)
    await state.clear()
    country = db.get_country(country_id)
    city = db.get_city(city_id)
    await message.answer(build_city_profile(country, city))


@router.message(Command("trip"))
async def cmd_trip(message: Message):
    city = await require_active_city(message)
    if not city:
        return
    country = db.get_country(city["country_id"])
    await message.answer(build_city_profile(country, city))


# ================= DIARY =================

@router.message(Command("diary_add"))
async def diary_add_start(message: Message, state: FSMContext):
    city = await require_active_city(message)
    if not city:
        return
    await state.set_state(DiaryAdd.text)
    await message.answer("📔 Yozuvingizni yuboring (matn, yoki rasm + izoh):")


@router.message(DiaryAdd.text, F.photo)
async def diary_add_photo(message: Message, state: FSMContext):
    city = db.get_active_city(message.from_user.id)
    db.add_diary(city["id"], str(date.today()), message.caption or "", message.photo[-1].file_id)
    await state.clear()
    await message.answer("✅ Kundalikka rasm bilan saqlandi")


@router.message(DiaryAdd.text)
async def diary_add_text(message: Message, state: FSMContext):
    city = db.get_active_city(message.from_user.id)
    db.add_diary(city["id"], str(date.today()), message.text, None)
    await state.clear()
    await message.answer("✅ Kundalikka saqlandi")


@router.message(Command("diary"))
async def cmd_diary(message: Message):
    city = await require_active_city(message)
    if not city:
        return
    entries = db.get_diary(city["id"])
    if not entries:
        await message.answer("Bu shahar uchun hali kundalik yozuvlari yo'q.")
        return
    for e in entries[:10]:
        caption = f"📅 {e['entry_date']}\n{e['text'] or ''}"
        if e["photo_file_id"]:
            await message.answer_photo(e["photo_file_id"], caption=caption)
        else:
            await message.answer(caption)


# ================= PLACE_ADD (davlat/shahar tanlash bilan) =================

@router.message(Command("place_add"))
async def place_add_start(message: Message, state: FSMContext):
    await state.set_state(PlaceAdd.name)
    await message.answer("📍 Joy nomini kiriting:")


@router.message(PlaceAdd.name)
async def place_add_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text.strip())
    countries = db.get_countries(message.from_user.id)
    if countries:
        await state.set_state(PlaceAdd.country)
        await message.answer("🌍 Qaysi davlat?", reply_markup=kb.country_select_kb(countries, prefix="padd_country"))
    else:
        await state.set_state(PlaceAdd.new_country_name)
        await message.answer("🌍 Davlat nomini kiriting (hali davlat qo'shilmagan):")


@router.callback_query(PlaceAdd.country, F.data.startswith("padd_country:"))
async def place_add_country_select(callback: CallbackQuery, state: FSMContext):
    val = callback.data.split(":", 1)[1]
    if val == "new":
        await state.set_state(PlaceAdd.new_country_name)
        await callback.message.edit_text("🌍 Yangi davlat nomini kiriting:")
        await callback.answer()
        return
    country_id = int(val)
    await state.update_data(country_id=country_id)
    await _place_add_ask_city(callback.message.edit_text, state, country_id)
    await callback.answer()


@router.message(PlaceAdd.new_country_name)
async def place_add_new_country_name(message: Message, state: FSMContext):
    name = message.text.strip()
    existing = db.find_country_by_name(message.from_user.id, name)
    if existing:
        await state.update_data(country_id=existing["id"])
        await message.answer(f"ℹ️ \"{existing['name']}\" allaqachon mavjud, unga bog'landi.")
        await _place_add_ask_city(message.answer, state, existing["id"])
        return
    await state.update_data(new_country_name=name)
    await state.set_state(PlaceAdd.new_country_status)
    await message.answer("Holati qanday?", reply_markup=kb.status_kb())


@router.callback_query(PlaceAdd.new_country_status, F.data.startswith("status:"))
async def place_add_new_country_status(callback: CallbackQuery, state: FSMContext):
    status = callback.data.split(":")[1]
    data = await state.get_data()
    country_id = db.add_country(callback.from_user.id, data["new_country_name"], status)
    await state.update_data(country_id=country_id)
    await _place_add_ask_city(callback.message.edit_text, state, country_id)
    await callback.answer()


async def _place_add_ask_city(answer_func, state: FSMContext, country_id):
    cities = db.get_cities(country_id)
    if cities:
        await state.set_state(PlaceAdd.city)
        await answer_func("🏙 Qaysi shahar?", reply_markup=kb.city_select_kb(cities, prefix="padd_city"))
    else:
        await state.set_state(PlaceAdd.new_city_name)
        await answer_func("🏙 Shahar nomini kiriting (bu davlatda hali shahar yo'q):")


@router.callback_query(PlaceAdd.city, F.data.startswith("padd_city:"))
async def place_add_city_select(callback: CallbackQuery, state: FSMContext):
    val = callback.data.split(":", 1)[1]
    if val == "new":
        await state.set_state(PlaceAdd.new_city_name)
        await callback.message.edit_text("🏙 Yangi shahar nomini kiriting:")
        await callback.answer()
        return
    city_id = int(val)
    await _place_after_city(city_id, state, callback.message.edit_text)
    await callback.answer()


@router.message(PlaceAdd.new_city_name)
async def place_add_new_city_name(message: Message, state: FSMContext):
    data = await state.get_data()
    country_id = data["country_id"]
    name = message.text.strip()
    existing = db.find_city_by_name(country_id, name)
    if existing:
        city_id = existing["id"]
        await message.answer("ℹ️ Bu shahar allaqachon mavjud, unga bog'landi.")
    else:
        city_id = db.add_city(country_id, name)
    await _place_after_city(city_id, state, message.answer)


async def _place_after_city(city_id, state: FSMContext, answer_func):
    data = await state.get_data()
    existing_place = db.find_place_by_name(city_id, data["name"])
    if existing_place:
        await state.clear()
        await answer_func("ℹ️ Bu nomli joy shu shaharda allaqachon mavjud:\n\n" + _place_line(existing_place))
        return
    await state.update_data(city_id=city_id)
    await state.set_state(PlaceAdd.type)
    await answer_func("Turi qanday?", reply_markup=kb.place_type_kb())


@router.callback_query(PlaceAdd.type, F.data.startswith("ptype:"))
async def place_add_type(callback: CallbackQuery, state: FSMContext):
    ptype = callback.data.split(":")[1]
    await state.update_data(type=ptype)
    if ptype == "restaurant":
        await state.set_state(PlaceAdd.halal)
        await callback.message.edit_text("🍽 Halolmi?", reply_markup=kb.yes_no_unknown_kb("halal"))
    else:
        await state.update_data(is_halal=None)
        await state.set_state(PlaceAdd.price)
        await callback.message.edit_text("💰 Narxi:", reply_markup=kb.skip_kb("skip_price"))
    await callback.answer()


@router.callback_query(PlaceAdd.halal, F.data.startswith("halal:"))
async def place_add_halal(callback: CallbackQuery, state: FSMContext):
    val = callback.data.split(":")[1]
    mapping = {"yes": True, "no": False, "unknown": None}
    await state.update_data(is_halal=mapping[val])
    await state.set_state(PlaceAdd.price)
    await callback.message.edit_text("💰 Narxi:", reply_markup=kb.skip_kb("skip_price"))
    await callback.answer()


@router.message(PlaceAdd.price)
async def place_add_price(message: Message, state: FSMContext):
    await state.update_data(price=message.text.strip())
    await state.set_state(PlaceAdd.rating)
    await message.answer("⭐ Baholang:", reply_markup=kb.rating_kb())


@router.callback_query(PlaceAdd.price, F.data == "skip_price")
async def place_add_price_skip(callback: CallbackQuery, state: FSMContext):
    await state.update_data(price=None)
    await state.set_state(PlaceAdd.rating)
    await callback.message.edit_text("⭐ Baholang:", reply_markup=kb.rating_kb())
    await callback.answer()


@router.callback_query(PlaceAdd.rating, F.data.startswith("rating:"))
async def place_add_rating(callback: CallbackQuery, state: FSMContext):
    val = callback.data.split(":")[1]
    rating = None if val == "skip" else int(val)
    await state.update_data(rating=rating)
    await state.set_state(PlaceAdd.location)
    await callback.message.edit_text(
        "📍 Manzilni yozing, yoki lokatsiya/joy (venue) yuboring:",
        reply_markup=kb.skip_kb("skip_location"),
    )
    await callback.answer()


PHOTOS_PROMPT = "📸 Rasm(lar) yuboring — bir nechtasini ketma-ket yuborishingiz mumkin. Tugagach tugmani bosing:"


async def _go_to_photos(state: FSMContext, answer_func):
    await state.update_data(photos=[])
    await state.set_state(PlaceAdd.photos)
    await answer_func(PHOTOS_PROMPT, reply_markup=kb.done_kb("photos_done"))


@router.message(PlaceAdd.location, F.location)
async def place_add_location_geo(message: Message, state: FSMContext):
    await state.update_data(address=None, latitude=message.location.latitude, longitude=message.location.longitude)
    await _go_to_photos(state, message.answer)


@router.message(PlaceAdd.location, F.venue)
async def place_add_location_venue(message: Message, state: FSMContext):
    v = message.venue
    await state.update_data(
        address=v.address or v.title, latitude=v.location.latitude, longitude=v.location.longitude
    )
    await _go_to_photos(state, message.answer)


@router.message(PlaceAdd.location, F.text)
async def place_add_location_text(message: Message, state: FSMContext):
    await state.update_data(address=message.text.strip(), latitude=None, longitude=None)
    await _go_to_photos(state, message.answer)


@router.callback_query(PlaceAdd.location, F.data == "skip_location")
async def place_add_location_skip(callback: CallbackQuery, state: FSMContext):
    await state.update_data(address=None, latitude=None, longitude=None)
    await _go_to_photos(state, callback.message.edit_text)
    await callback.answer()


@router.message(PlaceAdd.photos, F.photo)
async def place_add_photo(message: Message, state: FSMContext):
    data = await state.get_data()
    photos = data.get("photos", [])
    photos.append(message.photo[-1].file_id)
    await state.update_data(photos=photos)
    await message.answer(
        f"📸 Qabul qilindi ({len(photos)} ta). Yana yuboring yoki tugating:",
        reply_markup=kb.done_kb("photos_done"),
    )


@router.callback_query(PlaceAdd.photos, F.data == "photos_done")
async def place_add_photos_done(callback: CallbackQuery, state: FSMContext):
    await state.set_state(PlaceAdd.notes)
    await callback.message.edit_text("📝 Izoh:", reply_markup=kb.skip_kb("skip_place_notes"))
    await callback.answer()


@router.message(PlaceAdd.notes)
async def place_add_notes(message: Message, state: FSMContext):
    await _finish_place_add(state, message.text.strip(), message.answer)


@router.callback_query(PlaceAdd.notes, F.data == "skip_place_notes")
async def place_add_notes_skip(callback: CallbackQuery, state: FSMContext):
    await _finish_place_add(state, None, callback.message.edit_text)
    await callback.answer()


async def _finish_place_add(state, notes, answer_func):
    data = await state.get_data()
    place_id = db.add_place(
        data["city_id"], data["name"], data["type"], data.get("is_halal"),
        data.get("price"), data.get("rating"), data.get("address"),
        data.get("latitude"), data.get("longitude"), notes,
    )
    for photo_id in data.get("photos", []):
        db.add_place_photo(place_id, photo_id)
    await state.clear()
    photo_note = f", {len(data.get('photos', []))} ta rasm" if data.get("photos") else ""
    await answer_func(f"✅ Saqlandi: {data['name']} ({TYPE_NAMES.get(data['type'], data['type'])}{photo_note})")


# ================= PLACES (faol shahar) =================

def _place_line(p):
    emoji = {"hotel": "🏨", "restaurant": "🍽", "attraction": "🏛"}.get(p["type"], "📍")
    line = f"{emoji} <b>{p['name']}</b>"
    if p["type"] == "restaurant" and p["is_halal"] is not None:
        line += " ✅halol" if p["is_halal"] else " ❌nohalol"
    if p["price"]:
        line += f" — {p['price']}"
    if p["rating"]:
        line += " " + "⭐" * p["rating"]
    if p["address"]:
        line += f"\n📌 {p['address']}"
    if p["latitude"] and p["longitude"]:
        line += f"\n🗺 https://maps.google.com/?q={p['latitude']},{p['longitude']}"
    if p["notes"]:
        line += f"\n📝 {p['notes']}"
    return line


async def _send_place(target, p):
    line = _place_line(p)
    photos = db.get_place_photos(p["id"])
    if not photos:
        await target.answer(line)
    elif len(photos) == 1:
        await target.answer_photo(photos[0]["photo_file_id"], caption=line)
    else:
        media = [InputMediaPhoto(media=photos[0]["photo_file_id"], caption=line)]
        media += [InputMediaPhoto(media=ph["photo_file_id"]) for ph in photos[1:10]]
        await target.answer_media_group(media)


@router.message(Command("places"))
async def cmd_places(message: Message):
    countries = db.get_countries(message.from_user.id)
    if not countries:
        await message.answer("Hali davlat yo'q. /trip_add orqali qo'shing.")
        return
    await message.answer(
        "🌍 Qaysi davlat?", reply_markup=kb.country_select_kb(countries, prefix="places_country", show_add=False)
    )


@router.callback_query(F.data.startswith("places_country:"))
async def cb_places_country(callback: CallbackQuery):
    country_id = int(callback.data.split(":")[1])
    cities = db.get_cities(country_id)
    if not cities:
        await callback.message.edit_text("Bu davlatda hali shahar yo'q.")
        await callback.answer()
        return
    await callback.message.edit_text(
        "🏙 Qaysi shahar?", reply_markup=kb.city_select_kb(cities, prefix=f"places_city:{country_id}", show_add=False)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("places_city:"))
async def cb_places_city(callback: CallbackQuery):
    _, _country_id_s, city_id_s = callback.data.split(":")
    city_id = int(city_id_s)
    places = db.get_places(city_id)
    if not places:
        await callback.message.edit_text("Bu shaharda hali joylar yo'q.")
        await callback.answer()
        return
    city = db.get_city(city_id)
    await callback.message.edit_text(f"🏙 {city['name']} — qaysi turi?", reply_markup=kb.type_filter_kb(city_id))
    await callback.answer()


@router.callback_query(F.data.startswith("places_show:"))
async def cb_places_show(callback: CallbackQuery):
    _, city_id_s, ptype = callback.data.split(":")
    city_id = int(city_id_s)
    type_filter = None if ptype == "all" else ptype
    places = db.get_places(city_id, ptype=type_filter)
    await callback.answer()
    if not places:
        await callback.message.edit_text("Bu filtr bo'yicha joylar topilmadi.")
        return
    await callback.message.delete()
    for p in places:
        await _send_place(callback.message, p)


# ================= CONTACTS =================

@router.message(Command("contact_add"))
async def contact_add_start(message: Message, state: FSMContext):
    city = await require_active_city(message)
    if not city:
        return
    await state.set_state(ContactAdd.name)
    await message.answer("👤 Ism kiriting:")


@router.message(ContactAdd.name)
async def contact_add_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text.strip())
    await state.set_state(ContactAdd.contact_info)
    await message.answer("📞 Telefon/Telegram/Instagram:", reply_markup=kb.skip_kb("skip_contact_info"))


@router.message(ContactAdd.contact_info)
async def contact_add_info(message: Message, state: FSMContext):
    await state.update_data(contact_info=message.text.strip())
    await state.set_state(ContactAdd.notes)
    await message.answer("📝 Izoh (qayerda tanishdingiz va h.k.):", reply_markup=kb.skip_kb("skip_contact_notes"))


@router.callback_query(ContactAdd.contact_info, F.data == "skip_contact_info")
async def contact_add_info_skip(callback: CallbackQuery, state: FSMContext):
    await state.update_data(contact_info=None)
    await state.set_state(ContactAdd.notes)
    await callback.message.edit_text("📝 Izoh:", reply_markup=kb.skip_kb("skip_contact_notes"))
    await callback.answer()


@router.message(ContactAdd.notes)
async def contact_add_notes(message: Message, state: FSMContext):
    await _finish_contact_add(message.from_user.id, state, message.text.strip(), message.answer)


@router.callback_query(ContactAdd.notes, F.data == "skip_contact_notes")
async def contact_add_notes_skip(callback: CallbackQuery, state: FSMContext):
    await _finish_contact_add(callback.from_user.id, state, None, callback.message.edit_text)
    await callback.answer()


async def _finish_contact_add(user_id, state, notes, answer_func):
    data = await state.get_data()
    city = db.get_active_city(user_id)
    db.add_contact(city["id"], data["name"], data.get("contact_info"), notes)
    await state.clear()
    await answer_func(f"✅ Kontakt saqlandi: {data['name']}")


@router.message(Command("contacts"))
async def cmd_contacts(message: Message):
    city = await require_active_city(message)
    if not city:
        return
    contacts = db.get_contacts(city["id"])
    if not contacts:
        await message.answer("Bu shahar uchun hali kontaktlar yo'q.")
        return
    lines = []
    for c in contacts:
        line = f"👤 <b>{c['name']}</b>"
        if c["contact_info"]:
            line += f" — {c['contact_info']}"
        if c["notes"]:
            line += f"\n📝 {c['notes']}"
        lines.append(line)
    await message.answer("\n\n".join(lines))


# ================= EXPENSES =================

@router.message(Command("expense_add"))
async def expense_add_start(message: Message, state: FSMContext):
    city = await require_active_city(message)
    if not city:
        return
    await state.set_state(ExpenseAdd.category)
    await message.answer("💰 Kategoriyani tanlang:", reply_markup=kb.category_kb())


@router.callback_query(ExpenseAdd.category, F.data.startswith("cat:"))
async def expense_add_category(callback: CallbackQuery, state: FSMContext):
    category = callback.data.split(":", 1)[1]
    await state.update_data(category=category)
    await state.set_state(ExpenseAdd.amount)
    await callback.message.edit_text("Summani kiriting (masalan: 35000):")
    await callback.answer()


@router.message(ExpenseAdd.amount)
async def expense_add_amount(message: Message, state: FSMContext):
    amount = parse_money(message.text)
    if amount is None:
        await message.answer("Tushunmadim. Masalan: 35000, \"35 ming\" — qaytadan kiriting.")
        return
    await state.update_data(amount=amount)
    city = db.get_active_city(message.from_user.id)
    places = db.get_places(city["id"])
    if places:
        await state.set_state(ExpenseAdd.place)
        await message.answer("Qaysi joy bilan bog'liq?", reply_markup=kb.places_link_kb(places))
    else:
        await state.update_data(place_id=None)
        await state.set_state(ExpenseAdd.note)
        await message.answer("📝 Izoh:", reply_markup=kb.skip_kb("skip_expense_note"))


@router.callback_query(ExpenseAdd.place, F.data.startswith("link_place:"))
async def expense_add_place(callback: CallbackQuery, state: FSMContext):
    val = callback.data.split(":")[1]
    place_id = None if val == "none" else int(val)
    await state.update_data(place_id=place_id)
    await state.set_state(ExpenseAdd.note)
    await callback.message.edit_text("📝 Izoh:", reply_markup=kb.skip_kb("skip_expense_note"))
    await callback.answer()


@router.message(ExpenseAdd.note)
async def expense_add_note(message: Message, state: FSMContext):
    await _finish_expense_add(message.from_user.id, state, message.text.strip(), message.answer)


@router.callback_query(ExpenseAdd.note, F.data == "skip_expense_note")
async def expense_add_note_skip(callback: CallbackQuery, state: FSMContext):
    await _finish_expense_add(callback.from_user.id, state, None, callback.message.edit_text)
    await callback.answer()


async def _finish_expense_add(user_id, state, note, answer_func):
    data = await state.get_data()
    city = db.get_active_city(user_id)
    db.add_expense(
        city["id"], data["category"], data["amount"], "so'm", str(date.today()), data.get("place_id"), note
    )
    await state.clear()
    await answer_func(f"✅ Xarajat qo'shildi: {data['category']} — {fmt_money(data['amount'])} so'm")


@router.message(Command("expenses"))
async def cmd_expenses(message: Message):
    city = await require_active_city(message)
    if not city:
        return
    country = db.get_country(city["country_id"])
    summary = db.get_expense_summary(city["id"])
    country_total = db.get_country_expense_total(country["id"])
    if not summary and country_total == 0:
        await message.answer("Bu davlat uchun hali xarajat qo'shilmagan.")
        return
    lines = [f"💰 <b>{city['name']}</b>", "━━━━━━━━━━━━━━━"]
    city_total = 0
    if summary:
        for row in summary:
            city_total += row["total"]
            lines.append(f"{row['category']}: {fmt_money(row['total'])} {row['currency']}")
    else:
        lines.append("Bu shaharda hali xarajat yo'q.")
    lines.append("━━━━━━━━━━━━━━━")
    lines.append(f"💵 Shu shahar: {fmt_money(city_total)} so'm")
    lines.append(f"🌍 {country['name']} bo'yicha jami: {fmt_money(country_total)} so'm")
    if country["budget"]:
        period = BUDGET_PERIOD_LABELS.get(country.get("budget_period") or "total", "umumiy")
        qoldiq = float(country["budget"]) - country_total
        holat = "✅" if qoldiq >= 0 else "⚠️"
        lines.append(f"🎯 Byudjet: {fmt_money(country['budget'])} so'm ({period})")
        lines.append(f"{holat} Qoldiq: {fmt_money(qoldiq)} so'm")
    await message.answer("\n".join(lines))


# ================= FILES =================

@router.message(Command("file_add"))
async def file_add_start(message: Message, state: FSMContext):
    city = await require_active_city(message)
    if not city:
        return
    await state.set_state(FileAdd.file)
    await message.answer("📎 Faylni yuboring (chipta, viza, bron — hujjat yoki rasm sifatida):")


@router.message(FileAdd.file, F.document)
async def file_add_document(message: Message, state: FSMContext):
    await state.update_data(
        file_id=message.document.file_id, file_type="document", file_name=message.document.file_name
    )
    await state.set_state(FileAdd.notes)
    await message.answer("📝 Izoh (masalan: 'Aviachipta'):", reply_markup=kb.skip_kb("skip_file_notes"))


@router.message(FileAdd.file, F.photo)
async def file_add_photo(message: Message, state: FSMContext):
    await state.update_data(file_id=message.photo[-1].file_id, file_type="photo", file_name="rasm.jpg")
    await state.set_state(FileAdd.notes)
    await message.answer("📝 Izoh:", reply_markup=kb.skip_kb("skip_file_notes"))


@router.message(FileAdd.notes)
async def file_add_notes(message: Message, state: FSMContext):
    await _finish_file_add(message.from_user.id, state, message.text.strip(), message.answer)


@router.callback_query(FileAdd.notes, F.data == "skip_file_notes")
async def file_add_notes_skip(callback: CallbackQuery, state: FSMContext):
    await _finish_file_add(callback.from_user.id, state, None, callback.message.edit_text)
    await callback.answer()


async def _finish_file_add(user_id, state, notes, answer_func):
    data = await state.get_data()
    city = db.get_active_city(user_id)
    db.add_file(city["id"], data["file_id"], data["file_type"], data.get("file_name"), notes)
    await state.clear()
    await answer_func("✅ Fayl saqlandi")


@router.message(Command("files"))
async def cmd_files(message: Message):
    city = await require_active_city(message)
    if not city:
        return
    files = db.get_files(city["id"])
    if not files:
        await message.answer("Bu shahar uchun hali fayllar yo'q.")
        return
    for f in files:
        caption = f["file_name"] or "Fayl"
        if f["notes"]:
            caption += f"\n📝 {f['notes']}"
        if f["file_type"] == "photo":
            await message.answer_photo(f["file_id"], caption=caption)
        else:
            await message.answer_document(f["file_id"], caption=caption)


# ================= WEATHER =================

@router.message(Command("weather"))
async def cmd_weather(message: Message):
    city = await require_active_city(message)
    if not city:
        return
    country = db.get_country(city["country_id"])
    city_name = city["name"] or country["name"]
    result = await fetch_weather(city_name)
    if not result:
        await message.answer("Ob-havo topilmadi. Shahar nomini tekshiring yoki keyinroq urinib ko'ring.")
        return
    desc = WEATHER_CODES.get(result["code"], "🌡")
    text = (
        f"🌤 <b>{result['city']}</b>\n{desc}\n"
        f"🌡 Harorat: {result['temp']}°C\n💨 Shamol: {result['wind']} km/soat"
    )
    weather_cache[message.from_user.id] = text
    await message.answer(text, reply_markup=kb.weather_save_kb())


@router.callback_query(F.data == "save_weather")
async def cb_save_weather(callback: CallbackQuery):
    city = db.get_active_city(callback.from_user.id)
    text = weather_cache.get(callback.from_user.id)
    if city and text:
        db.add_diary(city["id"], str(date.today()), text, None)
        await callback.message.edit_text(text + "\n\n✅ Kundalikka saqlandi")
    await callback.answer()


# ================= STATS =================

@router.message(Command("stats"))
async def cmd_stats(message: Message):
    s = db.get_stats(message.from_user.id)
    text = (
        "📊 <b>Statistika</b>\n\n"
        f"✅ Borgan davlatlar: {s['visited_count']}\n"
        f"🎯 Wishlist: {s['wishlist_count']}\n"
        f"📍 Saqlangan joylar: {s['places_count']}\n"
        f"💵 Jami sarflangan: {fmt_money(s['total_spent'])} so'm"
    )
    if s["top_category"]:
        text += f"\n🔝 Eng ko'p sarflangan toifa: {s['top_category']['category']} ({fmt_money(s['top_category']['total'])})"
    if s["most_expensive"]:
        text += f"\n💸 Eng qimmat davlat: {s['most_expensive']['name']} ({fmt_money(s['most_expensive']['total'])} so'm)"
    if s["cheapest"]:
        text += f"\n💵 Eng arzon davlat: {s['cheapest']['name']} ({fmt_money(s['cheapest']['total'])} so'm)"
    await message.answer(text)


# ================= MANAGE (tahrirlash / o'chirish) =================

async def _show_country_menu(answer_func, country_id):
    country = db.get_country(country_id)
    emoji = "✅" if country["status"] == "visited" else "🎯"
    text = f"{emoji} <b>{country['name']}</b>"
    if country["budget"]:
        period = BUDGET_PERIOD_LABELS.get(country["budget_period"] or "total", "umumiy")
        text += f"\n🎯 Byudjet: {fmt_money(country['budget'])} so'm ({period})"
    if country["notes"]:
        text += f"\n📝 {country['notes']}"
    await answer_func(text, reply_markup=kb.manage_country_action_kb(country_id))


async def _show_city_menu(answer_func, city_id):
    city = db.get_city(city_id)
    await answer_func(f"🏙 <b>{city['name']}</b> — nima qilamiz?", reply_markup=kb.manage_city_action_kb(city_id))


async def _show_place_menu(answer_func, place_id):
    place = db.get_place(place_id)
    await answer_func(_place_line(place), reply_markup=kb.manage_place_action_kb(place_id))


async def _show_expense_menu(answer_func, expense_id):
    e = db.get_expense(expense_id)
    text = f"💰 {e['category']} — {fmt_money(e['amount'])} {e['currency']}"
    if e["note"]:
        text += f"\n📝 {e['note']}"
    await answer_func(text, reply_markup=kb.manage_expense_action_kb(expense_id))


async def _show_contact_menu(answer_func, contact_id):
    c = db.get_contact(contact_id)
    text = f"👤 <b>{c['name']}</b>"
    if c["contact_info"]:
        text += f"\n📞 {c['contact_info']}"
    if c["notes"]:
        text += f"\n📝 {c['notes']}"
    await answer_func(text, reply_markup=kb.manage_contact_action_kb(contact_id))


@router.message(Command("manage"))
async def cmd_manage(message: Message):
    countries = db.get_countries(message.from_user.id)
    if not countries:
        await message.answer("Hali davlat yo'q. /trip_add orqali qo'shing.")
        return
    await message.answer(
        "🌍 Qaysi davlatni boshqarasiz?",
        reply_markup=kb.country_select_kb(countries, prefix="mngc", show_add=False),
    )


# ---- Davlat ----

@router.callback_query(F.data.startswith("mngc:"))
async def cb_manage_country(callback: CallbackQuery):
    country_id = int(callback.data.split(":")[1])
    await _show_country_menu(callback.message.edit_text, country_id)
    await callback.answer()


@router.callback_query(F.data.startswith("mngc_name:"))
async def cb_manage_country_name(callback: CallbackQuery, state: FSMContext):
    country_id = int(callback.data.split(":")[1])
    await state.update_data(edit_kind="country_name", edit_id=country_id)
    await state.set_state(ManageEdit.text_input)
    await callback.message.edit_text("Yangi nomini kiriting:")
    await callback.answer()


@router.callback_query(F.data.startswith("mngc_status:"))
async def cb_manage_country_status(callback: CallbackQuery):
    country_id = int(callback.data.split(":")[1])
    await callback.message.edit_text("Yangi holatini tanlang:", reply_markup=kb.manage_status_kb(country_id))
    await callback.answer()


@router.callback_query(F.data.startswith("mngc_status_set:"))
async def cb_manage_country_status_set(callback: CallbackQuery):
    _, country_id_s, status = callback.data.split(":")
    country_id = int(country_id_s)
    db.update_country_status(country_id, status)
    await _show_country_menu(callback.message.edit_text, country_id)
    await callback.answer("✅ Holati yangilandi")


@router.callback_query(F.data.startswith("mngc_budget:"))
async def cb_manage_country_budget(callback: CallbackQuery, state: FSMContext):
    country_id = int(callback.data.split(":")[1])
    await state.update_data(edit_kind="country_budget", edit_id=country_id)
    await state.set_state(ManageEdit.text_input)
    await callback.message.edit_text("Yangi byudjet? (masalan: 3000000, \"3 mln\")")
    await callback.answer()


@router.callback_query(F.data.startswith("mngc_notes:"))
async def cb_manage_country_notes(callback: CallbackQuery, state: FSMContext):
    country_id = int(callback.data.split(":")[1])
    await state.update_data(edit_kind="country_notes", edit_id=country_id)
    await state.set_state(ManageEdit.text_input)
    await callback.message.edit_text("Yangi izohni kiriting:")
    await callback.answer()


@router.callback_query(F.data.startswith("mngc_cities:"))
async def cb_manage_country_cities(callback: CallbackQuery):
    country_id = int(callback.data.split(":")[1])
    cities = db.get_cities(country_id)
    if not cities:
        await callback.message.edit_text("Bu davlatda hali shahar yo'q.")
        await callback.answer()
        return
    await callback.message.edit_text(
        "🏙 Qaysi shahar?", reply_markup=kb.city_select_kb(cities, prefix="mngci", show_add=False)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("mngc_del:"))
async def cb_manage_country_del(callback: CallbackQuery):
    country_id = int(callback.data.split(":")[1])
    country = db.get_country(country_id)
    await callback.message.edit_text(
        f"⚠️ \"{country['name']}\" davlatini o'chirmoqchimisiz? Bu ichidagi BARCHA shahar, "
        "joy, kontakt, kundalik, xarajat va fayllarni ham o'chiradi!",
        reply_markup=kb.confirm_kb(f"mngc_delyes:{country_id}", f"mngc_delno:{country_id}"),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("mngc_delyes:"))
async def cb_manage_country_delyes(callback: CallbackQuery):
    country_id = int(callback.data.split(":")[1])
    db.delete_country(country_id)
    await callback.message.edit_text("🗑 Davlat va unga tegishli barcha ma'lumot o'chirildi.")
    await callback.answer()


@router.callback_query(F.data.startswith("mngc_delno:"))
async def cb_manage_country_delno(callback: CallbackQuery):
    country_id = int(callback.data.split(":")[1])
    await _show_country_menu(callback.message.edit_text, country_id)
    await callback.answer("Bekor qilindi")


# ---- Shahar ----

@router.callback_query(F.data.startswith("mngci:"))
async def cb_manage_city(callback: CallbackQuery):
    city_id = int(callback.data.split(":")[1])
    await _show_city_menu(callback.message.edit_text, city_id)
    await callback.answer()


@router.callback_query(F.data.startswith("mngci_name:"))
async def cb_manage_city_name(callback: CallbackQuery, state: FSMContext):
    city_id = int(callback.data.split(":")[1])
    await state.update_data(edit_kind="city_name", edit_id=city_id)
    await state.set_state(ManageEdit.text_input)
    await callback.message.edit_text("Yangi shahar nomini kiriting:")
    await callback.answer()


@router.callback_query(F.data.startswith("mngci_del:"))
async def cb_manage_city_del(callback: CallbackQuery):
    city_id = int(callback.data.split(":")[1])
    city = db.get_city(city_id)
    await callback.message.edit_text(
        f"⚠️ \"{city['name']}\" shaharni o'chirmoqchimisiz? Bu ichidagi barcha joy, kontakt, "
        "kundalik, xarajat va fayllarni ham o'chiradi!",
        reply_markup=kb.confirm_kb(f"mngci_delyes:{city_id}", f"mngci_delno:{city_id}"),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("mngci_delyes:"))
async def cb_manage_city_delyes(callback: CallbackQuery):
    city_id = int(callback.data.split(":")[1])
    db.delete_city(city_id)
    await callback.message.edit_text("🗑 Shahar va unga tegishli ma'lumot o'chirildi.")
    await callback.answer()


@router.callback_query(F.data.startswith("mngci_delno:"))
async def cb_manage_city_delno(callback: CallbackQuery):
    city_id = int(callback.data.split(":")[1])
    await _show_city_menu(callback.message.edit_text, city_id)
    await callback.answer("Bekor qilindi")


# ---- Joylar ----

@router.callback_query(F.data.startswith("mngp:"))
async def cb_manage_places_list(callback: CallbackQuery):
    city_id = int(callback.data.split(":")[1])
    places = db.get_places(city_id)
    if not places:
        await callback.message.edit_text("Bu shaharda hali joy yo'q.")
        await callback.answer()
        return
    type_emoji = {"hotel": "🏨", "restaurant": "🍽", "attraction": "🏛"}
    await callback.message.edit_text(
        "📍 Qaysi joy?",
        reply_markup=kb.manage_list_kb(
            places, prefix="mngp_view",
            label_func=lambda p: f"{type_emoji.get(p['type'], '📍')} {p['name']}",
        ),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("mngp_view:"))
async def cb_manage_place_view(callback: CallbackQuery):
    place_id = int(callback.data.split(":")[1])
    await _show_place_menu(callback.message.edit_text, place_id)
    await callback.answer()


@router.callback_query(F.data.startswith("mngp_price:"))
async def cb_manage_place_price(callback: CallbackQuery, state: FSMContext):
    place_id = int(callback.data.split(":")[1])
    await state.update_data(edit_kind="place_price", edit_id=place_id)
    await state.set_state(ManageEdit.text_input)
    await callback.message.edit_text("Yangi narxni kiriting:")
    await callback.answer()


@router.callback_query(F.data.startswith("mngp_rating:"))
async def cb_manage_place_rating(callback: CallbackQuery):
    place_id = int(callback.data.split(":")[1])
    await callback.message.edit_text("Yangi reyting:", reply_markup=kb.manage_rating_kb(place_id))
    await callback.answer()


@router.callback_query(F.data.startswith("mngp_rating_set:"))
async def cb_manage_place_rating_set(callback: CallbackQuery):
    _, place_id_s, val = callback.data.split(":")
    place_id = int(place_id_s)
    rating = None if val == "0" else int(val)
    db.update_place_rating(place_id, rating)
    await _show_place_menu(callback.message.edit_text, place_id)
    await callback.answer("✅ Reyting yangilandi")


@router.callback_query(F.data.startswith("mngp_notes:"))
async def cb_manage_place_notes(callback: CallbackQuery, state: FSMContext):
    place_id = int(callback.data.split(":")[1])
    await state.update_data(edit_kind="place_notes", edit_id=place_id)
    await state.set_state(ManageEdit.text_input)
    await callback.message.edit_text("Yangi izohni kiriting:")
    await callback.answer()


@router.callback_query(F.data.startswith("mngp_del:"))
async def cb_manage_place_del(callback: CallbackQuery):
    place_id = int(callback.data.split(":")[1])
    place = db.get_place(place_id)
    await callback.message.edit_text(
        f"⚠️ \"{place['name']}\"ni o'chirmoqchimisiz?",
        reply_markup=kb.confirm_kb(f"mngp_delyes:{place_id}", f"mngp_delno:{place_id}"),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("mngp_delyes:"))
async def cb_manage_place_delyes(callback: CallbackQuery):
    place_id = int(callback.data.split(":")[1])
    db.delete_place(place_id)
    await callback.message.edit_text("🗑 Joy o'chirildi.")
    await callback.answer()


@router.callback_query(F.data.startswith("mngp_delno:"))
async def cb_manage_place_delno(callback: CallbackQuery):
    place_id = int(callback.data.split(":")[1])
    await _show_place_menu(callback.message.edit_text, place_id)
    await callback.answer("Bekor qilindi")


# ---- Kontaktlar ----

@router.callback_query(F.data.startswith("mngk:"))
async def cb_manage_contacts_list(callback: CallbackQuery):
    city_id = int(callback.data.split(":")[1])
    contacts = db.get_contacts(city_id)
    if not contacts:
        await callback.message.edit_text("Bu shaharda hali kontakt yo'q.")
        await callback.answer()
        return
    await callback.message.edit_text(
        "👤 Qaysi kontakt?",
        reply_markup=kb.manage_list_kb(contacts, prefix="mngk_view", label_func=lambda c: c["name"]),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("mngk_view:"))
async def cb_manage_contact_view(callback: CallbackQuery):
    contact_id = int(callback.data.split(":")[1])
    await _show_contact_menu(callback.message.edit_text, contact_id)
    await callback.answer()


@router.callback_query(F.data.startswith("mngk_info:"))
async def cb_manage_contact_info(callback: CallbackQuery, state: FSMContext):
    contact_id = int(callback.data.split(":")[1])
    await state.update_data(edit_kind="contact_info", edit_id=contact_id)
    await state.set_state(ManageEdit.text_input)
    await callback.message.edit_text("Yangi ma'lumotni kiriting:")
    await callback.answer()


@router.callback_query(F.data.startswith("mngk_del:"))
async def cb_manage_contact_del(callback: CallbackQuery):
    contact_id = int(callback.data.split(":")[1])
    contact = db.get_contact(contact_id)
    await callback.message.edit_text(
        f"⚠️ \"{contact['name']}\"ni o'chirmoqchimisiz?",
        reply_markup=kb.confirm_kb(f"mngk_delyes:{contact_id}", f"mngk_delno:{contact_id}"),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("mngk_delyes:"))
async def cb_manage_contact_delyes(callback: CallbackQuery):
    contact_id = int(callback.data.split(":")[1])
    db.delete_contact(contact_id)
    await callback.message.edit_text("🗑 Kontakt o'chirildi.")
    await callback.answer()


@router.callback_query(F.data.startswith("mngk_delno:"))
async def cb_manage_contact_delno(callback: CallbackQuery):
    contact_id = int(callback.data.split(":")[1])
    await _show_contact_menu(callback.message.edit_text, contact_id)
    await callback.answer("Bekor qilindi")


# ---- Kundalik ----

@router.callback_query(F.data.startswith("mngd:"))
async def cb_manage_diary_list(callback: CallbackQuery):
    city_id = int(callback.data.split(":")[1])
    entries = db.get_diary(city_id)
    if not entries:
        await callback.message.edit_text("Bu shaharda hali kundalik yozuvi yo'q.")
        await callback.answer()
        return
    await callback.message.edit_text(
        "📔 Qaysi yozuv?",
        reply_markup=kb.manage_list_kb(
            entries, prefix="mngd_view",
            label_func=lambda d: f"{d['entry_date']} — {(d['text'] or '(rasm)')[:20]}",
        ),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("mngd_view:"))
async def cb_manage_diary_view(callback: CallbackQuery):
    diary_id = int(callback.data.split(":")[1])
    d = db.get_diary_entry(diary_id)
    text = f"📅 {d['entry_date']}\n{d['text'] or ''}"
    markup = kb.single_delete_kb(f"mngd_del:{diary_id}")
    if d["photo_file_id"]:
        await callback.message.answer_photo(d["photo_file_id"], caption=text, reply_markup=markup)
        await callback.message.delete()
    else:
        await callback.message.edit_text(text, reply_markup=markup)
    await callback.answer()


@router.callback_query(F.data.startswith("mngd_del:"))
async def cb_manage_diary_del(callback: CallbackQuery):
    diary_id = int(callback.data.split(":")[1])
    await callback.message.answer(
        "⚠️ Bu yozuvni o'chirmoqchimisiz?",
        reply_markup=kb.confirm_kb(f"mngd_delyes:{diary_id}", f"mngd_delno:{diary_id}"),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("mngd_delyes:"))
async def cb_manage_diary_delyes(callback: CallbackQuery):
    diary_id = int(callback.data.split(":")[1])
    db.delete_diary_entry(diary_id)
    await callback.message.answer("🗑 Yozuv o'chirildi.")
    await callback.answer()


@router.callback_query(F.data.startswith("mngd_delno:"))
async def cb_manage_diary_delno(callback: CallbackQuery):
    await callback.message.answer("Bekor qilindi")
    await callback.answer()


# ---- Xarajatlar ----

@router.callback_query(F.data.startswith("mnge:"))
async def cb_manage_expenses_list(callback: CallbackQuery):
    city_id = int(callback.data.split(":")[1])
    expenses = db.get_expenses(city_id)
    if not expenses:
        await callback.message.edit_text("Bu shaharda hali xarajat yo'q.")
        await callback.answer()
        return
    await callback.message.edit_text(
        "💰 Qaysi xarajat?",
        reply_markup=kb.manage_list_kb(
            expenses, prefix="mnge_view",
            label_func=lambda e: f"{e['category']} — {fmt_money(e['amount'])}",
        ),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("mnge_view:"))
async def cb_manage_expense_view(callback: CallbackQuery):
    expense_id = int(callback.data.split(":")[1])
    await _show_expense_menu(callback.message.edit_text, expense_id)
    await callback.answer()


@router.callback_query(F.data.startswith("mnge_amount:"))
async def cb_manage_expense_amount(callback: CallbackQuery, state: FSMContext):
    expense_id = int(callback.data.split(":")[1])
    await state.update_data(edit_kind="expense_amount", edit_id=expense_id)
    await state.set_state(ManageEdit.text_input)
    await callback.message.edit_text("Yangi summani kiriting:")
    await callback.answer()


@router.callback_query(F.data.startswith("mnge_note:"))
async def cb_manage_expense_note(callback: CallbackQuery, state: FSMContext):
    expense_id = int(callback.data.split(":")[1])
    await state.update_data(edit_kind="expense_note", edit_id=expense_id)
    await state.set_state(ManageEdit.text_input)
    await callback.message.edit_text("Yangi izohni kiriting:")
    await callback.answer()


@router.callback_query(F.data.startswith("mnge_del:"))
async def cb_manage_expense_del(callback: CallbackQuery):
    expense_id = int(callback.data.split(":")[1])
    await callback.message.edit_text(
        "⚠️ Bu xarajatni o'chirmoqchimisiz?",
        reply_markup=kb.confirm_kb(f"mnge_delyes:{expense_id}", f"mnge_delno:{expense_id}"),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("mnge_delyes:"))
async def cb_manage_expense_delyes(callback: CallbackQuery):
    expense_id = int(callback.data.split(":")[1])
    db.delete_expense(expense_id)
    await callback.message.edit_text("🗑 Xarajat o'chirildi.")
    await callback.answer()


@router.callback_query(F.data.startswith("mnge_delno:"))
async def cb_manage_expense_delno(callback: CallbackQuery):
    expense_id = int(callback.data.split(":")[1])
    await _show_expense_menu(callback.message.edit_text, expense_id)
    await callback.answer("Bekor qilindi")


# ---- Fayllar ----

@router.callback_query(F.data.startswith("mngf:"))
async def cb_manage_files_list(callback: CallbackQuery):
    city_id = int(callback.data.split(":")[1])
    files = db.get_files(city_id)
    if not files:
        await callback.message.edit_text("Bu shaharda hali fayl yo'q.")
        await callback.answer()
        return
    await callback.message.edit_text(
        "📎 Qaysi fayl?",
        reply_markup=kb.manage_list_kb(files, prefix="mngf_view", label_func=lambda f: f["file_name"] or "Fayl"),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("mngf_view:"))
async def cb_manage_file_view(callback: CallbackQuery):
    file_id = int(callback.data.split(":")[1])
    f = db.get_file(file_id)
    caption = f["file_name"] or "Fayl"
    if f["notes"]:
        caption += f"\n📝 {f['notes']}"
    markup = kb.single_delete_kb(f"mngf_del:{file_id}")
    if f["file_type"] == "photo":
        await callback.message.answer_photo(f["file_id"], caption=caption, reply_markup=markup)
    else:
        await callback.message.answer_document(f["file_id"], caption=caption, reply_markup=markup)
    await callback.answer()


@router.callback_query(F.data.startswith("mngf_del:"))
async def cb_manage_file_del(callback: CallbackQuery):
    file_id = int(callback.data.split(":")[1])
    await callback.message.answer(
        "⚠️ Bu faylni o'chirmoqchimisiz?",
        reply_markup=kb.confirm_kb(f"mngf_delyes:{file_id}", f"mngf_delno:{file_id}"),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("mngf_delyes:"))
async def cb_manage_file_delyes(callback: CallbackQuery):
    file_id = int(callback.data.split(":")[1])
    db.delete_file(file_id)
    await callback.message.answer("🗑 Fayl o'chirildi.")
    await callback.answer()


@router.callback_query(F.data.startswith("mngf_delno:"))
async def cb_manage_file_delno(callback: CallbackQuery):
    await callback.message.answer("Bekor qilindi")
    await callback.answer()


# ---- Tahrirlash uchun umumiy matn kiritish ----

@router.message(ManageEdit.text_input)
async def manage_edit_text(message: Message, state: FSMContext):
    data = await state.get_data()
    kind = data["edit_kind"]
    item_id = data["edit_id"]
    value = message.text.strip()

    if kind == "country_name":
        db.update_country_name(item_id, value)
        await state.clear()
        await _show_country_menu(message.answer, item_id)

    elif kind == "country_budget":
        budget = parse_money(value)
        if budget is None:
            await message.answer("Tushunmadim. Masalan: 3000000, \"3 mln\" — qaytadan kiriting.")
            return
        await state.update_data(new_budget=budget)
        await state.set_state(ManageEdit.budget_period)
        await message.answer("Bu byudjet qanday?", reply_markup=kb.budget_period_kb())

    elif kind == "country_notes":
        db.update_country_notes(item_id, value)
        await state.clear()
        await _show_country_menu(message.answer, item_id)

    elif kind == "city_name":
        db.update_city_name(item_id, value)
        await state.clear()
        await _show_city_menu(message.answer, item_id)

    elif kind == "place_price":
        db.update_place_price(item_id, value)
        await state.clear()
        await _show_place_menu(message.answer, item_id)

    elif kind == "place_notes":
        db.update_place_notes(item_id, value)
        await state.clear()
        await _show_place_menu(message.answer, item_id)

    elif kind == "expense_amount":
        amount = parse_money(value)
        if amount is None:
            await message.answer("Tushunmadim. Masalan: 35000, \"35 ming\" — qaytadan kiriting.")
            return
        db.update_expense_amount(item_id, amount)
        await state.clear()
        await _show_expense_menu(message.answer, item_id)

    elif kind == "expense_note":
        db.update_expense_note(item_id, value)
        await state.clear()
        await _show_expense_menu(message.answer, item_id)

    elif kind == "contact_info":
        db.update_contact_info(item_id, value)
        await state.clear()
        await _show_contact_menu(message.answer, item_id)


@router.callback_query(ManageEdit.budget_period, F.data.startswith("bperiod:"))
async def manage_edit_budget_period(callback: CallbackQuery, state: FSMContext):
    period = callback.data.split(":")[1]
    data = await state.get_data()
    country_id = data["edit_id"]
    db.update_country_budget(country_id, data["new_budget"], period)
    await state.clear()
    await _show_country_menu(callback.message.edit_text, country_id)
    await callback.answer("✅ Byudjet yangilandi")


# ================= EXPORT (Excel) =================

@router.message(Command("export"))
async def cmd_export(message: Message):
    user_id = message.from_user.id
    countries = db.export_countries(user_id)
    if not countries:
        await message.answer("Hali ma'lumot yo'q — eksport qilinadigan narsa yo'q.")
        return

    await message.answer("📊 Excel fayl tayyorlanmoqda...")

    wb = openpyxl.Workbook()
    header_font = Font(bold=True, color="FFFFFF", name="Arial")
    header_fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
    body_font = Font(name="Arial")

    def style_sheet(ws, wrap_cols=None, money_cols=None):
        wrap_cols = wrap_cols or set()
        money_cols = money_cols or set()
        for cell in ws[1]:
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = Alignment(horizontal="center", vertical="center")
        for row in ws.iter_rows(min_row=2):
            for cell in row:
                cell.font = body_font
                if cell.column_letter in wrap_cols:
                    cell.alignment = Alignment(wrap_text=True, vertical="top")
                if cell.column_letter in money_cols and cell.value is not None:
                    cell.number_format = "#,##0"
        for col in ws.columns:
            letter = col[0].column_letter
            if letter in wrap_cols:
                ws.column_dimensions[letter].width = 50
                continue
            length = max((len(str(c.value)) if c.value is not None else 0) for c in col)
            ws.column_dimensions[letter].width = min(max(length + 2, 10), 40)
        ws.freeze_panes = "A2"
        ws.row_dimensions[1].height = 20

    type_labels = {"hotel": "Mehmonxona", "restaurant": "Restoran", "attraction": "Ko'rish joyi"}

    ws = wb.active
    ws.title = "Davlatlar"
    ws.append(["Davlat", "Holati", "Byudjet", "Byudjet turi", "Shaharlar soni", "Jami xarajat"])
    for c in countries:
        status_label = "Borgan" if c["status"] == "visited" else "Bormoqchi"
        period = BUDGET_PERIOD_LABELS.get(c["budget_period"] or "total", "") if c["budget"] else ""
        ws.append([
            c["name"], status_label, float(c["budget"]) if c["budget"] else None,
            period, c["cities_count"], float(c["total_spent"]),
        ])
    style_sheet(ws, money_cols={"C", "F"})

    ws2 = wb.create_sheet("Shaharlar")
    ws2.append(["Davlat", "Shahar", "Joylar soni", "Jami xarajat"])
    for c in db.export_cities(user_id):
        ws2.append([c["country"], c["city"], c["places_count"], float(c["total_spent"])])
    style_sheet(ws2, money_cols={"D"})

    ws3 = wb.create_sheet("Joylar")
    ws3.append(["Davlat", "Shahar", "Nomi", "Turi", "Halol", "Narxi", "Reyting", "Manzil"])
    for p in db.export_places(user_id):
        halal = "" if p["is_halal"] is None else ("Ha" if p["is_halal"] else "Yo'q")
        ws3.append([
            p["country"], p["city"], p["name"], type_labels.get(p["type"], p["type"]),
            halal, p["price"], p["rating"], p["address"],
        ])
    style_sheet(ws3, wrap_cols={"H"})

    ws4 = wb.create_sheet("Xarajatlar")
    ws4.append(["Davlat", "Shahar", "Sana", "Kategoriya", "Summa", "Valyuta", "Izoh"])
    for e in db.export_expenses(user_id):
        ws4.append([e["country"], e["city"], e["expense_date"], e["category"], float(e["amount"]), e["currency"], e["note"]])
    style_sheet(ws4, wrap_cols={"G"}, money_cols={"E"})

    ws5 = wb.create_sheet("Kundalik")
    ws5.append(["Davlat", "Shahar", "Sana", "Yozuv"])
    for d in db.export_diary(user_id):
        ws5.append([d["country"], d["city"], d["entry_date"], d["text"]])
    style_sheet(ws5, wrap_cols={"D"})

    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
        wb.save(tmp.name)
        tmp_path = tmp.name

    try:
        await message.answer_document(FSInputFile(tmp_path, filename="sayohatlarim.xlsx"))
    finally:
        os.remove(tmp_path)


# ================= FALLBACK (eskirgan tugmalar uchun) =================
# Bu handler eng oxirida ro'yxatdan o'tadi, shu sababli faqat boshqa hech qanday
# handler mos kelmagan callacklarni "ushlaydi" (masalan, /cancel bosilgandan keyin
# yoki vaqt o'tib ketgan eski xabardagi tugma bosilganda).

@router.callback_query()
async def cb_fallback(callback: CallbackQuery):
    await callback.answer("⌛ Bu tugma endi faol emas. Kerakli komandani qaytadan yozing.", show_alert=True)
