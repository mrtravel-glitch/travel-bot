import asyncio
import logging
import re
from datetime import date, datetime, timedelta, timezone
from html import escape
from urllib.parse import quote

import aiohttp
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery, InputMediaPhoto

import database as db
import keyboards as kb
from states import (
    Pick, BudgetSet, TripAdd, TripsNewCity, DiaryAdd, PlaceAdd, ContactAdd, ExpenseAdd, FileAdd, WeatherAdd,
)

log = logging.getLogger(__name__)
router = Router()

TYPE_NAMES = {"hotel": "🏨 Mehmonxona", "restaurant": "🍽 Restoran", "attraction": "🏛 Ko'rish joyi"}

WEATHER_CODES = {
    0: "☀️ Ochiq osmon", 1: "🌤 Deyarli ochiq", 2: "⛅ Qisman bulutli", 3: "☁️ Bulutli",
    45: "🌫 Tuman", 48: "🌫 Muzli tuman",
    51: "🌦 Yengil yomg'ir", 53: "🌦 Yomg'ir", 55: "🌧 Kuchli yomg'ir",
    56: "🌧 Muzlovchi yomg'ir", 57: "🌧 Muzlovchi yomg'ir",
    61: "🌧 Yomg'ir", 63: "🌧 Yomg'ir", 65: "🌧 Kuchli yomg'ir",
    66: "🌧 Muzlovchi yomg'ir", 67: "🌧 Muzlovchi yomg'ir",
    71: "🌨 Qor", 73: "🌨 Qor", 75: "❄️ Kuchli qor", 77: "🌨 Qor donalari",
    80: "🌦 Jala", 81: "🌦 Jala", 82: "⛈ Kuchli jala",
    85: "🌨 Qor", 86: "❄️ Kuchli qor",
    95: "⛈ Momaqaldiroq", 96: "⛈ Do'lli momaqaldiroq", 99: "⛈ Do'lli momaqaldiroq",
}

# (foydalanuvchi, shahar) -> oxirgi olingan ob-havo (yozuvga saqlash tugmasi uchun)
weather_cache = {}

SEP = "━━━━━━━━━━━━━━━"
VALID_STATUSES = ("visited", "wishlist")


# ================= YORDAMCHI FUNKSIYALAR =================

def esc(value):
    """Foydalanuvchi matnini HTML xabar uchun xavfsiz qiladi (< > & belgilari xabarni buzmasin)."""
    return escape(str(value), quote=False) if value is not None else ""


def cut(text, limit):
    text = str(text)
    return text if len(text) <= limit else text[: limit - 1] + "…"


# Server UTC da ishlaydi, sana esa O'zbekiston vaqti (UTC+5) bo'yicha olinadi
UZ_TZ = timezone(timedelta(hours=5))


def today():
    return datetime.now(UZ_TZ).date()


UZ_MONTHS = [
    "yanvar", "fevral", "mart", "aprel", "may", "iyun",
    "iyul", "avgust", "sentabr", "oktabr", "noyabr", "dekabr",
]


def fmt_date(value):
    """'2026-09-20' -> '20 sentabr 2026'"""
    try:
        d = date.fromisoformat(str(value))
    except ValueError:
        return esc(value)
    return f"{d.day} {UZ_MONTHS[d.month - 1]} {d.year}"


def short_date(value):
    """'2026-09-20' -> '20.09'"""
    try:
        return date.fromisoformat(str(value)).strftime("%d.%m")
    except ValueError:
        return esc(value)


def parse_date(text):
    """'15.09.2026', '15.09', '15/09/26', '2026-09-15' kabi kiritishlarni sanaga aylantiradi."""
    t = (text or "").strip().replace("/", ".").replace("-", ".")
    try:
        m = re.fullmatch(r"(\d{1,2})\.(\d{1,2})(?:\.(\d{2}|\d{4}))?", t)
        if m:
            d, mo, y = m.groups()
            y = int(y) if y else today().year
            if y < 100:
                y += 2000
            return date(y, int(mo), int(d))
        m = re.fullmatch(r"(\d{4})\.(\d{1,2})\.(\d{1,2})", t)
        if m:
            y, mo, d = m.groups()
            return date(int(y), int(mo), int(d))
    except ValueError:
        return None
    return None


# ---------- Pul va valyuta ----------

CURRENCY_SYMBOLS = {"UZS": "so'm", "USD": "$", "EUR": "€"}
CURRENCY_ALIASES = {
    "som": "UZS", "so'm": "UZS", "sum": "UZS", "uzs": "UZS",
    "$": "USD", "usd": "USD", "dollar": "USD",
    "€": "EUR", "eur": "EUR", "euro": "EUR", "evro": "EUR",
}


def normalize_currency(text):
    """'usd', '$', 'evro', 'try' -> 'USD', 'USD', 'EUR', 'TRY'. Tushunilmasa None."""
    t = (text or "").strip().lower().replace("’", "'").replace("ʻ", "'").replace("‘", "'")
    if not t:
        return None
    if t in CURRENCY_ALIASES:
        return CURRENCY_ALIASES[t]
    if re.fullmatch(r"[a-z]{2,5}", t):
        return t.upper()
    return None


def cur_sym(code):
    code = code or "UZS"
    return CURRENCY_SYMBOLS.get(code, code)


def fmt_money(amount):
    amount = float(amount)
    if abs(amount - round(amount)) < 0.005:
        return f"{amount:,.0f}".replace(",", " ")
    return f"{amount:,.2f}".replace(",", " ")


def fmt_num(value):
    """24.0 -> '24', 24.5 -> '24.5'"""
    return f"{float(value):.1f}".rstrip("0").rstrip(".")


def fmt_amount(amount, code):
    return f"{fmt_money(amount)} {cur_sym(code)}"


CURRENCY_ORDER = {"UZS": 0, "USD": 1, "EUR": 2}


def currency_key(code):
    return (CURRENCY_ORDER.get(code, 3), code)


def sort_by_currency(rows):
    """So'm, dollar, evro birinchi; qolganlari alifbo bo'yicha. Valyuta ichidagi tartib saqlanadi."""
    return sorted(rows, key=lambda r: currency_key(r["currency"]))


def fmt_totals(rows):
    """[{'currency': 'UZS', 'total': 3000000}, {'currency': 'USD', 'total': 250}] -> '3 000 000 so'm + 250 $'"""
    parts = [fmt_amount(r["total"], r["currency"]) for r in sort_by_currency(rows) if r["total"]]
    return " + ".join(parts) if parts else fmt_amount(0, "UZS")


MONEY_MULTIPLIERS = [
    (re.compile(r"mlrd|milliard|billion", re.IGNORECASE), 1_000_000_000),
    (re.compile(r"mln|million", re.IGNORECASE), 1_000_000),
    (re.compile(r"ming|k\b", re.IGNORECASE), 1_000),
]

BUDGET_PERIOD_LABELS = {"daily": "kunlik", "monthly": "oylik", "total": "umumiy"}


def parse_money(text):
    """'3000000', '3 mln', '500 ming', '1.5 mlrd', '1,5 mln', '12,50' kabi kiritishlarni raqamga aylantiradi."""
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
    t = t.replace(" ", "")
    if re.fullmatch(r"\d+,\d{1,2}", t):  # "1,5" -> o'nlik kasr; "3,000,000" -> minglik ajratgich
        t = t.replace(",", ".")
    t = t.replace(",", "")
    t = re.sub(r"[^0-9.\-]", "", t)
    if not t or t in ("-", "."):
        return None
    try:
        return float(t) * multiplier
    except ValueError:
        return None


def parse_temp(text):
    t = (text or "").strip().lower()
    for junk in ("°c", "°", "c", " "):
        t = t.replace(junk, "")
    t = t.replace(",", ".")
    try:
        v = float(t)
    except ValueError:
        return None
    return v if -90 <= v <= 60 else None


# ---------- Egalik tekshiruvi (begona ID'lardan himoya) ----------

def _int(val):
    try:
        return int(val)
    except (TypeError, ValueError):
        return None


def own_country(user_id, val):
    cid = _int(val)
    return db.get_country_owned(user_id, cid) if cid is not None else None


def own_city(user_id, val, country_id=None):
    cid = _int(val)
    if cid is None:
        return None
    city = db.get_city_owned(user_id, cid)
    if city and country_id is not None and city["country_id"] != country_id:
        return None
    return city


def own_place(user_id, val, city_id=None):
    pid = _int(val)
    if pid is None:
        return None
    place = db.get_place_owned(user_id, pid)
    if place and city_id is not None and place["city_id"] != city_id:
        return None
    return place


NOT_FOUND = "Topilmadi"


# ---------- Byudjet va profil ----------

def _budget_lines(city, city_totals):
    """Shahar byudjeti va qoldig'i (faqat shu shahar xarajatlari hisobga olinadi)."""
    if not city["budget"]:
        return []
    bcur = city.get("budget_currency") or "UZS"
    spent = {r["currency"]: float(r["total"]) for r in city_totals}
    period = BUDGET_PERIOD_LABELS.get(city.get("budget_period") or "total", "umumiy")
    qoldiq = float(city["budget"]) - spent.get(bcur, 0)
    holat = "✅" if qoldiq >= 0 else "⚠️"
    lines = [
        f"🎯 Byudjet: {fmt_amount(city['budget'], bcur)} ({period})",
        f"{holat} Qoldiq: {fmt_amount(qoldiq, bcur)}",
    ]
    others = [r for r in city_totals if r["currency"] != bcur]
    if others:
        lines.append(f"ℹ️ Boshqa valyutadagi xarajatlar byudjetga hisoblanmagan: {fmt_totals(others)}")
    return lines


def build_city_profile(country, city):
    emoji = "✅" if country["status"] == "visited" else "🎯"
    text = f"{emoji} <b>{esc(country['name'])}</b> — 🏙 {esc(city['name'])}"
    if country["notes"]:
        text += f"\n📝 {esc(country['notes'])}"

    places = db.get_places(city["id"])
    diary = db.get_diary(city["id"])
    contacts = db.get_contacts(city["id"])
    files = db.get_files(city["id"])
    city_totals = db.get_city_expense_totals(city["id"])
    country_totals = db.get_country_expense_totals(country["id"])

    text += (
        f"\n\n📍 Joylar: {len(places)}\n📔 Kundalik: {len(diary)}\n"
        f"👤 Kontaktlar: {len(contacts)}\n📎 Fayllar: {len(files)}\n"
        f"💰 Shu shahar xarajati: {fmt_totals(city_totals)}\n"
        f"🌍 {esc(country['name'])} bo'yicha jami: {fmt_totals(country_totals)}"
    )
    budget = _budget_lines(city, city_totals)
    if budget:
        text += "\n" + "\n".join(budget)
    return text


GEO_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
WEATHER_ERRORS = (aiohttp.ClientError, asyncio.TimeoutError, TimeoutError, ValueError, KeyError, IndexError, TypeError)


async def _fetch_open_meteo(session, city_name):
    async with session.get(
        GEO_URL, params={"name": city_name, "count": 5, "language": "en", "format": "json"}
    ) as resp:
        geo = await resp.json(content_type=None)
    results = geo.get("results") if isinstance(geo, dict) else None
    if not results:
        return None
    place = max(results, key=lambda r: r.get("population") or 0)  # eng katta mos shahar
    params = {"latitude": place["latitude"], "longitude": place["longitude"], "current_weather": "true"}
    async with session.get(FORECAST_URL, params=params) as resp:
        data = await resp.json(content_type=None)
    cw = data.get("current_weather")
    if not cw:
        return None
    return {"city": place["name"], "temp": cw["temperature"], "wind": cw["windspeed"], "code": cw["weathercode"]}


async def _fetch_wttr(session, city_name):
    """Zaxira manba: Open-Meteo shaharni topa olmasa yoki ishlamasa."""
    async with session.get(
        "https://wttr.in/" + quote(city_name), params={"format": "j1"}, headers={"User-Agent": "travel-bot/1.0"}
    ) as resp:
        data = await resp.json(content_type=None)
    cur = data["current_condition"][0]
    areas = data.get("nearest_area") or [{}]
    area = (areas[0].get("areaName") or [{}])[0].get("value") or city_name
    return {
        "city": area, "temp": float(cur["temp_C"]), "wind": float(cur["windspeedKmph"]),
        "code": None, "desc": "🌡 " + cur["weatherDesc"][0]["value"],
    }


async def fetch_weather(city_name):
    """(natija, sabab) qaytaradi. sabab: None | 'notfound' | 'network'."""
    timeout = aiohttp.ClientTimeout(total=8)
    network_error = False
    async with aiohttp.ClientSession(timeout=timeout) as session:
        for source, func in (("open-meteo", _fetch_open_meteo), ("wttr.in", _fetch_wttr)):
            try:
                result = await func(session, city_name)
                if result:
                    return result, None
            except WEATHER_ERRORS as e:
                log.warning("Ob-havo (%s) xatosi: %r", source, e)
                network_error = True
    return None, ("network" if network_error else "notfound")


async def _reply(target, text, edit, **kwargs):
    """edit=True bo'lsa tugmali xabarni tahrirlaydi, aks holda yangi xabar yuboradi."""
    if edit:
        await target.edit_text(text, **kwargs)
    else:
        await target.answer(text, **kwargs)


def _answerer(target, edit):
    async def send(text, **kwargs):
        await _reply(target, text, edit, **kwargs)
    return send


# ================= BASIC =================

@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "👋 Salom! Men sizning shaxsiy sayohat botingizman.\n\n"
        "Davlat → Shahar → Joy tartibida saqlayman: har bir davlat ichida "
        "bir nechta shahar, har shaharda mehmonxona/restoran/ko'rish joylari, "
        "kundalik, kontaktlar, fayllar, xarajatlar va ob-havo yozuvlari bo'lishi mumkin.\n\n"
        "Boshlash uchun: /trip_add — yangi davlat qo'shing\n"
        "Barcha komandalar: /help"
    )


@router.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(
        "📋 <b>Komandalar</b>\n\n"
        "<b>Davlat / Shahar</b>\n"
        "/trip_add — yangi davlat/shahar qo'shish\n"
        "/trips — davlat va shahar tanlab, to'liq ma'lumotni ko'rish\n"
        "/budget — shahar byudjetini belgilash/o'zgartirish\n\n"
        "<b>Kundalik</b> (davlat/shahar so'raladi)\n"
        "/diary_add — yozuv qo'shish\n"
        "/diary — yozuvlarni ko'rish\n\n"
        "<b>Joylar</b>\n"
        "/place_add — joy qo'shish (davlat/shahar tanlash bilan)\n"
        "/places — joylarni ko'rish (turi bo'yicha filtr)\n\n"
        "<b>Kontaktlar</b> (davlat/shahar so'raladi)\n"
        "/contact_add — kontakt qo'shish\n"
        "/contacts — kontaktlar ro'yxati\n\n"
        "<b>Xarajatlar</b> (davlat/shahar so'raladi, valyutani tanlaysiz)\n"
        "/expense_add — xarajat qo'shish\n"
        "/expenses — hisobot va oxirgi xarajatlar\n\n"
        "<b>Fayllar</b> (davlat/shahar so'raladi)\n"
        "/file_add — chipta/hujjat saqlash\n"
        "/files — fayllarni ko'rish\n\n"
        "<b>Ob-havo</b> (davlat/shahar so'raladi)\n"
        "/weather — hozirgi ob-havo + yozib qo'yilganlar\n"
        "/weather_add — qaysi kuni qanday havo bo'lganini yozib qo'yish\n\n"
        "<b>Statistika</b>\n"
        "/stats — umumiy statistika\n\n"
        "❌ /cancel — joriy amalni bekor qilish"
    )


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Bekor qilindi ❌")


# ================= UMUMIY DAVLAT/SHAHAR TANLASH =================
# Kundalik, kontakt, fayl, xarajat va ob-havo buyruqlari shu yerdan o'tadi:
# davlat -> shahar tanlanadi (qo'shish buyruqlarida yangisini ham qo'shish mumkin),
# so'ng tanlangan shaharga qarab tegishli amal bajariladi.

ADD_PURPOSES = {"diary_add", "contact_add", "file_add", "expense_add", "weather_add", "budget_set"}


async def _start_pick(message: Message, state: FSMContext, purpose: str):
    await state.clear()
    allow_new = purpose in ADD_PURPOSES
    await state.update_data(purpose=purpose, allow_new=allow_new)
    countries = db.get_countries(message.from_user.id)
    if countries:
        await state.set_state(Pick.country)
        await message.answer(
            "🌍 Qaysi davlat?",
            reply_markup=kb.country_select_kb(countries, prefix="pick_country", show_add=allow_new),
        )
    elif allow_new:
        await state.set_state(Pick.new_country_name)
        await message.answer("🌍 Davlat nomini kiriting (hali davlat qo'shilmagan):")
    else:
        await state.clear()
        await message.answer("Hali davlat yo'q. /trip_add orqali qo'shing.")


@router.callback_query(Pick.country, F.data.startswith("pick_country:"))
async def pick_country_select(callback: CallbackQuery, state: FSMContext):
    val = callback.data.split(":", 1)[1]
    if val == "new":
        await state.set_state(Pick.new_country_name)
        await callback.message.edit_text("🌍 Yangi davlat nomini kiriting:")
        await callback.answer()
        return
    country = own_country(callback.from_user.id, val)
    if not country:
        await callback.answer(NOT_FOUND, show_alert=True)
        return
    await callback.answer()
    await _pick_ask_city(callback.message, state, country["id"], edit=True)


@router.message(Pick.new_country_name, F.text, ~F.text.startswith("/"))
async def pick_new_country_name(message: Message, state: FSMContext):
    name = message.text.strip()
    existing = db.find_country_by_name(message.from_user.id, name)
    if existing:
        await message.answer(f"ℹ️ \"{esc(existing['name'])}\" allaqachon mavjud, unga bog'landi.")
        await _pick_ask_city(message, state, existing["id"], edit=False)
        return
    await state.update_data(new_country_name=name)
    await state.set_state(Pick.new_country_status)
    await message.answer("Holati qanday?", reply_markup=kb.status_kb())


@router.callback_query(Pick.new_country_status, F.data.startswith("status:"))
async def pick_new_country_status(callback: CallbackQuery, state: FSMContext):
    status = callback.data.split(":")[1]
    if status not in VALID_STATUSES:
        await callback.answer()
        return
    data = await state.get_data()
    country_id = db.add_country(callback.from_user.id, data["new_country_name"], status)
    await callback.answer()
    await _pick_ask_city(callback.message, state, country_id, edit=True)


async def _pick_ask_city(target, state: FSMContext, country_id, edit):
    data = await state.get_data()
    allow_new = data.get("allow_new", False)
    await state.update_data(country_id=country_id)
    cities = db.get_cities(country_id)
    if cities:
        await state.set_state(Pick.city)
        await _reply(
            target, "🏙 Qaysi shahar?", edit,
            reply_markup=kb.city_select_kb(cities, prefix="pick_city", show_add=allow_new),
        )
    elif allow_new:
        await state.set_state(Pick.new_city_name)
        await _reply(target, "🏙 Shahar nomini kiriting (bu davlatda hali shahar yo'q):", edit)
    else:
        await state.clear()
        await _reply(target, "Bu davlatda hali shahar yo'q.", edit)


@router.callback_query(Pick.city, F.data.startswith("pick_city:"))
async def pick_city_select(callback: CallbackQuery, state: FSMContext):
    val = callback.data.split(":", 1)[1]
    if val == "new":
        await state.set_state(Pick.new_city_name)
        await callback.message.edit_text("🏙 Yangi shahar nomini kiriting:")
        await callback.answer()
        return
    data = await state.get_data()
    city = own_city(callback.from_user.id, val, data.get("country_id"))
    if not city:
        await callback.answer(NOT_FOUND, show_alert=True)
        return
    await callback.answer()
    await _pick_done(callback.message, state, callback.from_user.id, city["id"], edit=True)


@router.message(Pick.new_city_name, F.text, ~F.text.startswith("/"))
async def pick_new_city_name(message: Message, state: FSMContext):
    data = await state.get_data()
    country_id = data["country_id"]
    name = message.text.strip()
    existing = db.find_city_by_name(country_id, name)
    if existing:
        city_id = existing["id"]
        await message.answer("ℹ️ Bu shahar allaqachon mavjud, unga bog'landi.")
    else:
        city_id = db.add_city(country_id, name)
    await _pick_done(message, state, message.from_user.id, city_id, edit=False)


async def _pick_done(target, state: FSMContext, user_id, city_id, edit):
    """Shahar tanlandi — endi qaysi buyruqdan kelganiga qarab davom etamiz."""
    data = await state.get_data()
    purpose = data["purpose"]
    city = db.get_city(city_id)
    country = db.get_country(city["country_id"])
    where = esc(f"{country['name']} — {city['name']}")

    # --- qo'shish buyruqlari: tanlangan shahar ID'si FSM ichida saqlanadi ---
    if purpose == "diary_add":
        await state.update_data(city_id=city_id)
        await state.set_state(DiaryAdd.text)
        await _reply(target, f"📔 {where}\nYozuvingizni yuboring (matn, yoki rasm + izoh):", edit)
    elif purpose == "contact_add":
        await state.update_data(city_id=city_id)
        await state.set_state(ContactAdd.name)
        await _reply(target, f"👤 {where}\nIsm kiriting:", edit)
    elif purpose == "file_add":
        await state.update_data(city_id=city_id)
        await state.set_state(FileAdd.file)
        await _reply(
            target, f"📎 {where}\nFaylni yuboring (chipta, viza, bron — hujjat yoki rasm sifatida):", edit
        )
    elif purpose == "expense_add":
        await state.update_data(city_id=city_id)
        await state.set_state(ExpenseAdd.category)
        await _reply(target, f"💰 {where}\nKategoriyani tanlang:", edit, reply_markup=kb.category_kb())
    elif purpose == "budget_set":
        await _budget_start(_answerer(target, edit), state, city_id, from_new_city=False)
    elif purpose == "weather_add":
        await state.update_data(city_id=city_id)
        await state.set_state(WeatherAdd.date)
        await _reply(
            target, f"🌤 {where}\nQaysi kunning ob-havosini yozmoqchisiz?", edit,
            reply_markup=kb.weather_date_kb(),
        )

    # --- ko'rish buyruqlari: natijani chiqarib, holatni tozalaymiz ---
    else:
        await state.clear()
        if purpose == "diary":
            await _show_diary(target, city_id, where, edit)
        elif purpose == "contacts":
            await _show_contacts(target, city_id, where, edit)
        elif purpose == "files":
            await _show_files(target, city_id, where, edit)
        elif purpose == "expenses":
            await _reply(target, _expenses_text(city, country), edit)
        elif purpose == "weather":
            await _show_weather(target, user_id, city, country, edit)


# ================= TRIP_ADD (davlat + birinchi shahar) =================

@router.message(Command("trip_add"))
async def trip_add_start(message: Message, state: FSMContext):
    await state.clear()
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
    country = own_country(callback.from_user.id, val)
    if not country:
        await callback.answer(NOT_FOUND, show_alert=True)
        return
    await state.update_data(country_id=country["id"])
    await _trip_ask_city(callback.message.edit_text, state, country["id"])
    await callback.answer()


@router.message(TripAdd.new_country_name, F.text, ~F.text.startswith("/"))
async def trip_add_new_country_name(message: Message, state: FSMContext):
    name = message.text.strip()
    existing = db.find_country_by_name(message.from_user.id, name)
    if existing:
        await state.update_data(country_id=existing["id"])
        await message.answer(f"ℹ️ \"{esc(existing['name'])}\" allaqachon mavjud, unga bog'landi.")
        await _trip_ask_city(message.answer, state, existing["id"])
        return
    await state.update_data(new_country_name=name)
    await state.set_state(TripAdd.status)
    await message.answer("Holati qanday?", reply_markup=kb.status_kb())


@router.callback_query(TripAdd.status, F.data.startswith("status:"))
async def trip_add_status(callback: CallbackQuery, state: FSMContext):
    status = callback.data.split(":")[1]
    if status not in VALID_STATUSES:
        await callback.answer()
        return
    await state.update_data(status=status)
    await state.set_state(TripAdd.notes)
    await callback.message.edit_text(
        "Davlat haqida izoh qoldirmoqchimisiz?", reply_markup=kb.skip_kb("skip_trip_notes")
    )
    await callback.answer()


@router.message(TripAdd.notes, F.text, ~F.text.startswith("/"))
async def trip_add_notes(message: Message, state: FSMContext):
    await _trip_add_finish(message.from_user.id, state, message.text.strip(), message.answer)


@router.callback_query(TripAdd.notes, F.data == "skip_trip_notes")
async def trip_add_notes_skip(callback: CallbackQuery, state: FSMContext):
    await _trip_add_finish(callback.from_user.id, state, None, callback.message.edit_text)
    await callback.answer()


async def _trip_add_finish(user_id, state, notes, answer_func):
    data = await state.get_data()
    country_id = db.add_country(user_id, data["new_country_name"], data["status"], notes)
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
    city = own_city(callback.from_user.id, val, country_id)
    if not city:
        await callback.answer(NOT_FOUND, show_alert=True)
        return
    country = db.get_country(country_id)
    await state.clear()
    await callback.message.edit_text(build_city_profile(country, city))
    await callback.answer()


@router.message(TripAdd.new_city_name, F.text, ~F.text.startswith("/"))
async def trip_add_new_city_name(message: Message, state: FSMContext):
    data = await state.get_data()
    country_id = data["country_id"]
    name = message.text.strip()
    existing = db.find_city_by_name(country_id, name)
    if existing:
        country = db.get_country(country_id)
        await state.clear()
        await message.answer("ℹ️ Bu shahar allaqachon mavjud, unga bog'landi.\n\n" + build_city_profile(country, existing))
        return
    city_id = db.add_city(country_id, name)
    await _budget_start(message.answer, state, city_id, from_new_city=True)


# ================= BYUDJET (har bir shahar uchun alohida) =================

@router.message(Command("budget", "byudjet"))
async def cmd_budget(message: Message, state: FSMContext):
    await _start_pick(message, state, "budget_set")


async def _budget_start(answer_func, state: FSMContext, city_id, from_new_city):
    city = db.get_city(city_id)
    country = db.get_country(city["country_id"])
    where = esc(f"{country['name']} — {city['name']}")
    await state.update_data(city_id=city_id)
    await state.set_state(BudgetSet.amount)
    hint = "masalan: 3000000, \"3 mln\", \"500\""
    markup = None
    if city["budget"]:
        period = BUDGET_PERIOD_LABELS.get(city.get("budget_period") or "total", "umumiy")
        text = (
            f"💰 {where}\n🎯 Hozirgi byudjet: {fmt_amount(city['budget'], city.get('budget_currency'))} ({period})\n"
            f"Yangi byudjetni kiriting ({hint}):"
        )
        markup = kb.budget_clear_kb()
    else:
        text = f"💰 {where}\nShu shahar uchun byudjet? ({hint})"
        if from_new_city:
            markup = kb.skip_kb("skip_budget")
        if country["budget"]:
            text += (
                f"\n\nℹ️ Bu davlat uchun eski byudjet bor: {fmt_amount(country['budget'], country.get('budget_currency'))}. "
                "Endi byudjet har bir shaharga alohida belgilanadi."
            )
    await answer_func(text, reply_markup=markup)


async def _budget_show_profile(answer_func, state: FSMContext, city_id, prefix=""):
    city = db.get_city(city_id)
    country = db.get_country(city["country_id"])
    await state.clear()
    await answer_func(prefix + build_city_profile(country, city))


@router.message(BudgetSet.amount, F.text, ~F.text.startswith("/"))
async def budget_amount(message: Message, state: FSMContext):
    budget = parse_money(message.text)
    if budget is None or budget <= 0:
        await message.answer("Tushunmadim. Masalan: 3000000, \"3 mln\", \"500\" — qaytadan kiriting.")
        return
    await state.update_data(budget=budget)
    await state.set_state(BudgetSet.currency)
    await message.answer("💱 Byudjet qaysi valyutada?", reply_markup=kb.currency_kb())


@router.callback_query(BudgetSet.amount, F.data == "skip_budget")
async def budget_skip(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    await _budget_show_profile(callback.message.edit_text, state, data["city_id"])
    await callback.answer()


@router.callback_query(BudgetSet.amount, F.data == "budget_clear")
async def budget_clear(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    db.set_city_budget(data["city_id"], None, None, None)
    await _budget_show_profile(callback.message.edit_text, state, data["city_id"], "🗑 Byudjet olib tashlandi\n\n")
    await callback.answer()


async def _budget_ask_period(answer_func, state: FSMContext):
    await state.set_state(BudgetSet.period)
    await answer_func("Bu byudjet qanday?", reply_markup=kb.budget_period_kb())


@router.callback_query(BudgetSet.currency, F.data.startswith("cur:"))
async def budget_currency(callback: CallbackQuery, state: FSMContext):
    val = callback.data.split(":", 1)[1]
    if val == "other":
        await state.set_state(BudgetSet.currency_other)
        await callback.message.edit_text("✏️ Valyuta nomini yozing (masalan: EUR, TRY, AED, RUB):")
        await callback.answer()
        return
    if val not in CURRENCY_SYMBOLS:
        await callback.answer()
        return
    await state.update_data(budget_currency=val)
    await _budget_ask_period(callback.message.edit_text, state)
    await callback.answer()


@router.message(BudgetSet.currency_other, F.text, ~F.text.startswith("/"))
async def budget_currency_other(message: Message, state: FSMContext):
    code = normalize_currency(message.text)
    if not code:
        await message.answer("Tushunmadim. 2–5 ta harfli kod yozing, masalan: EUR, TRY, AED, RUB.")
        return
    await state.update_data(budget_currency=code)
    await _budget_ask_period(message.answer, state)


@router.callback_query(BudgetSet.period, F.data.startswith("bperiod:"))
async def budget_period(callback: CallbackQuery, state: FSMContext):
    period = callback.data.split(":")[1]
    if period not in BUDGET_PERIOD_LABELS:
        await callback.answer()
        return
    data = await state.get_data()
    db.set_city_budget(data["city_id"], data["budget"], data.get("budget_currency") or "UZS", period)
    await _budget_show_profile(callback.message.edit_text, state, data["city_id"], "✅ Byudjet saqlandi\n\n")
    await callback.answer()


# ================= TRIPS (davlat + shahar tanlash) =================

@router.message(Command("trips"))
async def cmd_trips(message: Message, state: FSMContext):
    await state.clear()
    countries = db.get_countries(message.from_user.id)
    if not countries:
        await message.answer("Hali davlat yo'q. /trip_add orqali qo'shing.")
        return
    await message.answer(
        "🌍 Davlatni tanlang:", reply_markup=kb.country_select_kb(countries, prefix="trips_country", show_add=False)
    )


@router.message(Command("trip"))
async def cmd_trip(message: Message, state: FSMContext):
    # Eski /trip endi /trips bilan bir xil ishlaydi
    await cmd_trips(message, state)


@router.callback_query(F.data.startswith("trips_country:"))
async def cb_trips_country(callback: CallbackQuery):
    country = own_country(callback.from_user.id, callback.data.split(":")[1])
    if not country:
        await callback.answer(NOT_FOUND, show_alert=True)
        return
    cities = db.get_cities(country["id"])
    await callback.message.edit_text(
        "🏙 Shaharni tanlang:", reply_markup=kb.city_select_kb(cities, prefix=f"trips_city:{country['id']}")
    )
    await callback.answer()


@router.callback_query(F.data.startswith("trips_city:"))
async def cb_trips_city(callback: CallbackQuery, state: FSMContext):
    parts = callback.data.split(":")
    if len(parts) != 3:
        await callback.answer()
        return
    _, country_id_s, val = parts
    country = own_country(callback.from_user.id, country_id_s)
    if not country:
        await callback.answer(NOT_FOUND, show_alert=True)
        return
    if val == "new":
        await state.clear()
        await state.update_data(new_city_country_id=country["id"])
        await state.set_state(TripsNewCity.name)
        await callback.message.edit_text("🏙 Yangi shahar nomini kiriting:")
        await callback.answer()
        return
    city = own_city(callback.from_user.id, val, country["id"])
    if not city:
        await callback.answer(NOT_FOUND, show_alert=True)
        return
    await callback.message.edit_text(build_city_profile(country, city))
    await callback.answer()


@router.message(TripsNewCity.name, F.text, ~F.text.startswith("/"))
async def trips_new_city_name(message: Message, state: FSMContext):
    data = await state.get_data()
    country_id = data["new_city_country_id"]
    name = message.text.strip()
    existing = db.find_city_by_name(country_id, name)
    if existing:
        await state.clear()
        country = db.get_country(country_id)
        await message.answer("ℹ️ Bu shahar allaqachon mavjud.\n\n" + build_city_profile(country, existing))
        return
    city_id = db.add_city(country_id, name)
    await state.clear()
    await _budget_start(message.answer, state, city_id, from_new_city=True)


# ================= PLACE_ADD (davlat/shahar tanlash bilan) =================

@router.message(Command("place_add"))
async def place_add_start(message: Message, state: FSMContext):
    await state.clear()
    await state.set_state(PlaceAdd.name)
    await message.answer("📍 Joy nomini kiriting:")


@router.message(PlaceAdd.name, F.text, ~F.text.startswith("/"))
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
    country = own_country(callback.from_user.id, val)
    if not country:
        await callback.answer(NOT_FOUND, show_alert=True)
        return
    await state.update_data(country_id=country["id"])
    await _place_add_ask_city(callback.message.edit_text, state, country["id"])
    await callback.answer()


@router.message(PlaceAdd.new_country_name, F.text, ~F.text.startswith("/"))
async def place_add_new_country_name(message: Message, state: FSMContext):
    name = message.text.strip()
    existing = db.find_country_by_name(message.from_user.id, name)
    if existing:
        await state.update_data(country_id=existing["id"])
        await message.answer(f"ℹ️ \"{esc(existing['name'])}\" allaqachon mavjud, unga bog'landi.")
        await _place_add_ask_city(message.answer, state, existing["id"])
        return
    await state.update_data(new_country_name=name)
    await state.set_state(PlaceAdd.new_country_status)
    await message.answer("Holati qanday?", reply_markup=kb.status_kb())


@router.callback_query(PlaceAdd.new_country_status, F.data.startswith("status:"))
async def place_add_new_country_status(callback: CallbackQuery, state: FSMContext):
    status = callback.data.split(":")[1]
    if status not in VALID_STATUSES:
        await callback.answer()
        return
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
    data = await state.get_data()
    city = own_city(callback.from_user.id, val, data.get("country_id"))
    if not city:
        await callback.answer(NOT_FOUND, show_alert=True)
        return
    await _place_after_city(city["id"], state, callback.message.edit_text)
    await callback.answer()


@router.message(PlaceAdd.new_city_name, F.text, ~F.text.startswith("/"))
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
    if ptype not in TYPE_NAMES:
        await callback.answer()
        return
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
    if val not in mapping:
        await callback.answer()
        return
    await state.update_data(is_halal=mapping[val])
    await state.set_state(PlaceAdd.price)
    await callback.message.edit_text("💰 Narxi:", reply_markup=kb.skip_kb("skip_price"))
    await callback.answer()


@router.message(PlaceAdd.price, F.text, ~F.text.startswith("/"))
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
    if val == "skip":
        rating = None
    elif val in ("1", "2", "3", "4", "5"):
        rating = int(val)
    else:
        await callback.answer()
        return
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


@router.message(PlaceAdd.location, F.text, ~F.text.startswith("/"))
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


@router.message(PlaceAdd.notes, F.text, ~F.text.startswith("/"))
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
    await answer_func(f"✅ Saqlandi: {esc(data['name'])} ({TYPE_NAMES.get(data['type'], data['type'])}{photo_note})")


# ================= PLACES (davlat -> shahar -> tur) =================

def _place_line(p):
    emoji = {"hotel": "🏨", "restaurant": "🍽", "attraction": "🏛"}.get(p["type"], "📍")
    line = f"{emoji} <b>{esc(p['name'])}</b>"
    if p["type"] == "restaurant" and p["is_halal"] is not None:
        line += " ✅halol" if p["is_halal"] else " ❌nohalol"
    if p["price"]:
        line += f" — {esc(p['price'])}"
    if p["rating"]:
        line += " " + "⭐" * p["rating"]
    if p["address"]:
        line += f"\n📌 {esc(p['address'])}"
    if p["latitude"] and p["longitude"]:
        line += f"\n🗺 https://maps.google.com/?q={p['latitude']},{p['longitude']}"
    if p["notes"]:
        line += f"\n📝 {esc(p['notes'])}"
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
async def cmd_places(message: Message, state: FSMContext):
    await state.clear()
    countries = db.get_countries(message.from_user.id)
    if not countries:
        await message.answer("Hali davlat yo'q. /trip_add orqali qo'shing.")
        return
    await message.answer(
        "🌍 Qaysi davlat?", reply_markup=kb.country_select_kb(countries, prefix="places_country", show_add=False)
    )


@router.callback_query(F.data.startswith("places_country:"))
async def cb_places_country(callback: CallbackQuery):
    country = own_country(callback.from_user.id, callback.data.split(":")[1])
    if not country:
        await callback.answer(NOT_FOUND, show_alert=True)
        return
    cities = db.get_cities(country["id"])
    if not cities:
        await callback.message.edit_text("Bu davlatda hali shahar yo'q.")
        await callback.answer()
        return
    await callback.message.edit_text(
        "🏙 Qaysi shahar?", reply_markup=kb.city_select_kb(cities, prefix=f"places_city:{country['id']}", show_add=False)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("places_city:"))
async def cb_places_city(callback: CallbackQuery):
    parts = callback.data.split(":")
    if len(parts) != 3:
        await callback.answer()
        return
    country = own_country(callback.from_user.id, parts[1])
    city = own_city(callback.from_user.id, parts[2], country["id"] if country else None)
    if not country or not city:
        await callback.answer(NOT_FOUND, show_alert=True)
        return
    places = db.get_places(city["id"])
    if not places:
        await callback.message.edit_text("Bu shaharda hali joylar yo'q.")
        await callback.answer()
        return
    await callback.message.edit_text(
        f"🏙 {esc(city['name'])} — qaysi turi?", reply_markup=kb.type_filter_kb(city["id"])
    )
    await callback.answer()


@router.callback_query(F.data.startswith("places_show:"))
async def cb_places_show(callback: CallbackQuery):
    parts = callback.data.split(":")
    if len(parts) != 3:
        await callback.answer()
        return
    city = own_city(callback.from_user.id, parts[1])
    ptype = parts[2]
    if not city:
        await callback.answer(NOT_FOUND, show_alert=True)
        return
    if ptype != "all" and ptype not in TYPE_NAMES:
        await callback.answer()
        return
    type_filter = None if ptype == "all" else ptype
    places = db.get_places(city["id"], ptype=type_filter)
    await callback.answer()
    if not places:
        await callback.message.edit_text("Bu filtr bo'yicha joylar topilmadi.")
        return
    await callback.message.delete()
    for p in places:
        await _send_place(callback.message, p)


# ================= DIARY =================

@router.message(Command("diary_add", "dairy_add", "kundalik_add"))
async def diary_add_start(message: Message, state: FSMContext):
    await _start_pick(message, state, "diary_add")


@router.message(DiaryAdd.text, F.photo)
async def diary_add_photo(message: Message, state: FSMContext):
    data = await state.get_data()
    db.add_diary(data["city_id"], str(today()), message.caption or "", message.photo[-1].file_id)
    await state.clear()
    await message.answer("✅ Kundalikka rasm bilan saqlandi")


@router.message(DiaryAdd.text, F.text, ~F.text.startswith("/"))
async def diary_add_text(message: Message, state: FSMContext):
    data = await state.get_data()
    db.add_diary(data["city_id"], str(today()), message.text, None)
    await state.clear()
    await message.answer("✅ Kundalikka saqlandi")


@router.message(Command("diary", "dairy", "kundalik"))
async def cmd_diary(message: Message, state: FSMContext):
    await _start_pick(message, state, "diary")


def _diary_text(raw):
    raw = raw or ""
    # Eski versiyada "Kundalikka saqlash" ob-havoni <b> belgilari bilan saqlagan; faqat shularni tozalaymiz
    if raw.startswith("🌤 <b>"):
        raw = raw.replace("<b>", "").replace("</b>", "")
    return esc(raw)


async def _show_diary(target, city_id, where, edit):
    entries = db.get_diary(city_id)
    if not entries:
        await _reply(target, f"📔 {where}\nBu shahar uchun hali kundalik yozuvlari yo'q.", edit)
        return
    shown = entries[:10]
    header = f"📔 <b>{where}</b>\n📚 Jami yozuvlar: {len(entries)}"
    if len(entries) > len(shown):
        header += f" (oxirgi {len(shown)} tasi ko'rsatildi)"
    await _reply(target, header, edit)
    for e in shown:
        body = _diary_text(e["text"])
        card = f"📅 <b>{fmt_date(e['entry_date'])}</b>"
        if body.strip():
            card += f"\n{SEP}\n{body}"
        if e["photo_file_id"]:
            if len(card) <= 1000:
                await target.answer_photo(e["photo_file_id"], caption=card)
            else:  # rasm izohi 1024 belgidan oshmasligi kerak
                await target.answer_photo(e["photo_file_id"], caption=f"📅 <b>{fmt_date(e['entry_date'])}</b>")
                await target.answer(card)
        else:
            await target.answer(card)


# ================= CONTACTS =================

@router.message(Command("contact_add"))
async def contact_add_start(message: Message, state: FSMContext):
    await _start_pick(message, state, "contact_add")


@router.message(ContactAdd.name, F.text, ~F.text.startswith("/"))
async def contact_add_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text.strip())
    await state.set_state(ContactAdd.contact_info)
    await message.answer("📞 Telefon/Telegram/Instagram:", reply_markup=kb.skip_kb("skip_contact_info"))


@router.message(ContactAdd.contact_info, F.text, ~F.text.startswith("/"))
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


@router.message(ContactAdd.notes, F.text, ~F.text.startswith("/"))
async def contact_add_notes(message: Message, state: FSMContext):
    await _finish_contact_add(state, message.text.strip(), message.answer)


@router.callback_query(ContactAdd.notes, F.data == "skip_contact_notes")
async def contact_add_notes_skip(callback: CallbackQuery, state: FSMContext):
    await _finish_contact_add(state, None, callback.message.edit_text)
    await callback.answer()


async def _finish_contact_add(state, notes, answer_func):
    data = await state.get_data()
    db.add_contact(data["city_id"], data["name"], data.get("contact_info"), notes)
    await state.clear()
    await answer_func(f"✅ Kontakt saqlandi: {esc(data['name'])}")


@router.message(Command("contacts"))
async def cmd_contacts(message: Message, state: FSMContext):
    await _start_pick(message, state, "contacts")


async def _show_contacts(target, city_id, where, edit):
    contacts = db.get_contacts(city_id)
    if not contacts:
        await _reply(target, f"👤 {where}\nBu shahar uchun hali kontaktlar yo'q.", edit)
        return
    lines = []
    for c in contacts:
        line = f"👤 <b>{esc(c['name'])}</b>"
        if c["contact_info"]:
            line += f" — {esc(c['contact_info'])}"
        if c["notes"]:
            line += f"\n📝 {esc(c['notes'])}"
        lines.append(line)
    await _reply(target, f"👤 <b>{where}</b>\n{SEP}\n" + "\n\n".join(lines), edit)


# ================= EXPENSES =================

@router.message(Command("expense_add"))
async def expense_add_start(message: Message, state: FSMContext):
    await _start_pick(message, state, "expense_add")


@router.callback_query(ExpenseAdd.category, F.data.startswith("cat:"))
async def expense_add_category(callback: CallbackQuery, state: FSMContext):
    category = callback.data.split(":", 1)[1]
    if category not in kb.EXPENSE_CATEGORIES:
        await callback.answer()
        return
    await state.update_data(category=category)
    await state.set_state(ExpenseAdd.amount)
    await callback.message.edit_text(
        f"{esc(category)}\nSummani kiriting (masalan: 35000, \"35 ming\", \"1.5 mln\", \"12,50\"):"
    )
    await callback.answer()


@router.message(ExpenseAdd.amount, F.text, ~F.text.startswith("/"))
async def expense_add_amount(message: Message, state: FSMContext):
    amount = parse_money(message.text)
    if amount is None or amount <= 0:
        await message.answer("Tushunmadim. Masalan: 35000, \"35 ming\", \"12,50\" — qaytadan kiriting.")
        return
    await state.update_data(amount=amount)
    await state.set_state(ExpenseAdd.currency)
    await message.answer(f"💱 {fmt_money(amount)} — qaysi valyutada?", reply_markup=kb.currency_kb())


async def _expense_after_currency(answer_func, state: FSMContext):
    data = await state.get_data()
    places = db.get_places(data["city_id"])
    if places:
        await state.set_state(ExpenseAdd.place)
        await answer_func("Qaysi joy bilan bog'liq?", reply_markup=kb.places_link_kb(places))
    else:
        await state.update_data(place_id=None)
        await state.set_state(ExpenseAdd.note)
        await answer_func("📝 Izoh:", reply_markup=kb.skip_kb("skip_expense_note"))


@router.callback_query(ExpenseAdd.currency, F.data.startswith("cur:"))
async def expense_add_currency(callback: CallbackQuery, state: FSMContext):
    val = callback.data.split(":", 1)[1]
    if val == "other":
        await state.set_state(ExpenseAdd.currency_other)
        await callback.message.edit_text("✏️ Valyuta nomini yozing (masalan: EUR, TRY, AED, RUB):")
        await callback.answer()
        return
    if val not in CURRENCY_SYMBOLS:
        await callback.answer()
        return
    await state.update_data(currency=val)
    await _expense_after_currency(callback.message.edit_text, state)
    await callback.answer()


@router.message(ExpenseAdd.currency_other, F.text, ~F.text.startswith("/"))
async def expense_add_currency_other(message: Message, state: FSMContext):
    code = normalize_currency(message.text)
    if not code:
        await message.answer("Tushunmadim. 2–5 ta harfli kod yozing, masalan: EUR, TRY, AED, RUB.")
        return
    await state.update_data(currency=code)
    await _expense_after_currency(message.answer, state)


@router.callback_query(ExpenseAdd.place, F.data.startswith("link_place:"))
async def expense_add_place(callback: CallbackQuery, state: FSMContext):
    val = callback.data.split(":")[1]
    if val == "none":
        place_id = None
    else:
        data = await state.get_data()
        place = own_place(callback.from_user.id, val, data.get("city_id"))
        if not place:
            await callback.answer(NOT_FOUND, show_alert=True)
            return
        place_id = place["id"]
    await state.update_data(place_id=place_id)
    await state.set_state(ExpenseAdd.note)
    await callback.message.edit_text("📝 Izoh:", reply_markup=kb.skip_kb("skip_expense_note"))
    await callback.answer()


@router.message(ExpenseAdd.note, F.text, ~F.text.startswith("/"))
async def expense_add_note(message: Message, state: FSMContext):
    await _finish_expense_add(state, message.text.strip(), message.answer)


@router.callback_query(ExpenseAdd.note, F.data == "skip_expense_note")
async def expense_add_note_skip(callback: CallbackQuery, state: FSMContext):
    await _finish_expense_add(state, None, callback.message.edit_text)
    await callback.answer()


async def _finish_expense_add(state, note, answer_func):
    data = await state.get_data()
    currency = data.get("currency") or "UZS"
    db.add_expense(
        data["city_id"], data["category"], data["amount"], currency,
        str(today()), data.get("place_id"), note,
    )
    await state.clear()
    await answer_func(f"✅ Xarajat qo'shildi: {esc(data['category'])} — {fmt_amount(data['amount'], currency)}")


@router.message(Command("expenses"))
async def cmd_expenses(message: Message, state: FSMContext):
    await _start_pick(message, state, "expenses")


def _expenses_text(city, country):
    summary = db.get_expense_summary(city["id"])
    country_totals = db.get_country_expense_totals(country["id"])
    if not summary and not country_totals:
        lines = ["Bu davlat uchun hali xarajat qo'shilmagan."]
        lines += _budget_lines(city, [])
        return "\n".join(lines)
    city_totals = db.get_city_expense_totals(city["id"])

    lines = [f"💰 <b>{esc(city['name'])}</b> — xarajatlar", SEP]
    if summary:
        for row in sort_by_currency(summary):
            lines.append(f"{esc(row['category'])}: {fmt_amount(row['total'], row['currency'])}")
    else:
        lines.append("Bu shaharda hali xarajat yo'q.")
    lines += [
        SEP,
        f"💵 Shu shahar: {fmt_totals(city_totals)}",
        f"🌍 {esc(country['name'])} bo'yicha jami: {fmt_totals(country_totals)}",
    ]
    lines += _budget_lines(city, city_totals)

    recent = db.get_expenses(city["id"], limit=11)
    if recent:
        lines += [SEP, "📋 <b>Oxirgi xarajatlar</b>"]
        for e in recent[:10]:
            line = (
                f"• {short_date(e['expense_date'])} · {esc(e['category'])} — "
                f"<b>{fmt_amount(e['amount'], e['currency'])}</b>"
            )
            extra = []
            if e["place_name"]:
                extra.append(f"📍 {esc(e['place_name'])}")
            if e["note"]:
                extra.append(f"📝 {esc(cut(e['note'], 120))}")
            if extra:
                line += "\n   " + " · ".join(extra)
            lines.append(line)
        if len(recent) > 10:
            lines.append("… (faqat oxirgi 10 ta xarajat ko'rsatildi)")
    return "\n".join(lines)


# ================= FILES =================

@router.message(Command("file_add"))
async def file_add_start(message: Message, state: FSMContext):
    await _start_pick(message, state, "file_add")


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


@router.message(FileAdd.notes, F.text, ~F.text.startswith("/"))
async def file_add_notes(message: Message, state: FSMContext):
    await _finish_file_add(state, message.text.strip(), message.answer)


@router.callback_query(FileAdd.notes, F.data == "skip_file_notes")
async def file_add_notes_skip(callback: CallbackQuery, state: FSMContext):
    await _finish_file_add(state, None, callback.message.edit_text)
    await callback.answer()


async def _finish_file_add(state, notes, answer_func):
    data = await state.get_data()
    db.add_file(data["city_id"], data["file_id"], data["file_type"], data.get("file_name"), notes)
    await state.clear()
    await answer_func("✅ Fayl saqlandi")


@router.message(Command("files"))
async def cmd_files(message: Message, state: FSMContext):
    await _start_pick(message, state, "files")


async def _show_files(target, city_id, where, edit):
    files = db.get_files(city_id)
    if not files:
        await _reply(target, f"📎 {where}\nBu shahar uchun hali fayllar yo'q.", edit)
        return
    await _reply(target, f"📎 <b>{where}</b>\n📚 Jami fayllar: {len(files)}", edit)
    for f in files:
        caption = esc(f["file_name"]) or "Fayl"
        if f["notes"]:
            caption += f"\n📝 {esc(f['notes'])}"
        if f["file_type"] == "photo":
            await target.answer_photo(f["file_id"], caption=caption)
        else:
            await target.answer_document(f["file_id"], caption=caption)


# ================= WEATHER =================

@router.message(Command("weather", "wether", "wheather", "obhavo"))
async def cmd_weather(message: Message, state: FSMContext):
    await _start_pick(message, state, "weather")


def _weather_record_lines(records):
    lines = [SEP]
    if not records:
        lines.append("📋 Yozib qo'yilgan ob-havo yo'q. Qo'shish: /weather_add")
        return lines
    lines.append("📋 <b>Yozib qo'yilgan ob-havo</b>")
    for r in records:
        line = f"📅 {fmt_date(r['log_date'])} — {esc(r['weather_type'])}"
        if r["temp"] is not None:
            line += f", 🌡 {fmt_num(r['temp'])}°C"
        if r["note"]:
            line += f"\n   📝 {esc(cut(r['note'], 120))}"
        lines.append(line)
    return lines


async def _show_weather(target, user_id, city, country, edit):
    city_name = city["name"] or country["name"]
    result, reason = await fetch_weather(city_name)
    keyboard = None
    if result:
        if result.get("code") is not None:
            desc = WEATHER_CODES.get(result["code"], "🌡 Ob-havo")
        else:
            desc = result.get("desc") or "🌡 Ob-havo"
        lines = [
            f"🌤 <b>{esc(result['city'])}</b> — hozir",
            desc,
            f"🌡 {fmt_num(result['temp'])}°C · 💨 {fmt_num(result['wind'])} km/soat",
        ]
        keyboard = kb.weather_save_kb(city["id"])
    else:
        if reason == "notfound":
            why = "Shahar topilmadi. Nomini lotin harflarida, inglizcha yozib ko'ring (masalan: Dubai, Istanbul)."
        else:
            why = "Ob-havo xizmatiga ulanib bo'lmadi. Keyinroq urinib ko'ring."
        lines = [f"🌤 <b>{esc(city['name'])}</b>", f"⚠️ {why}"]
    lines += _weather_record_lines(db.get_weather_log(city["id"], limit=10))
    text = "\n".join(lines)
    if result:
        weather_cache[(user_id, city["id"])] = {
            "text": text, "condition": desc, "temp": result["temp"], "wind": result["wind"],
        }
    await _reply(target, text, edit, reply_markup=keyboard)


@router.callback_query(F.data.startswith("save_weather:"))
async def cb_save_weather(callback: CallbackQuery):
    city = own_city(callback.from_user.id, callback.data.split(":", 1)[1])
    if not city:
        await callback.answer(NOT_FOUND, show_alert=True)
        return
    cached = weather_cache.get((callback.from_user.id, city["id"]))
    if not cached:
        await callback.answer("Ob-havo eskirgan, /weather ni qaytadan bosing", show_alert=True)
        return
    db.add_weather(
        city["id"], str(today()), cached["condition"], cached["temp"], f"Shamol: {fmt_num(cached['wind'])} km/soat"
    )
    await callback.message.edit_text(cached["text"] + "\n\n✅ Ob-havo yozuviga saqlandi")
    await callback.answer()


@router.message(Command("weather_add", "wether_add", "wheather_add", "obhavo_add"))
async def weather_add_start(message: Message, state: FSMContext):
    await _start_pick(message, state, "weather_add")


async def _weather_ask_condition(answer_func, state: FSMContext):
    await state.set_state(WeatherAdd.condition)
    await answer_func("Havo qanday edi?", reply_markup=kb.weather_cond_kb())


@router.callback_query(WeatherAdd.date, F.data.startswith("wdate:"))
async def weather_add_date(callback: CallbackQuery, state: FSMContext):
    val = callback.data.split(":", 1)[1]
    if val == "other":
        await state.set_state(WeatherAdd.date_custom)
        await callback.message.edit_text("📅 Sanani yozing (masalan: 15.09.2026 yoki 15.09):")
        await callback.answer()
        return
    if val == "today":
        d = today()
    elif val == "yesterday":
        d = today() - timedelta(days=1)
    else:
        await callback.answer()
        return
    await state.update_data(log_date=d.isoformat())
    await _weather_ask_condition(callback.message.edit_text, state)
    await callback.answer()


@router.message(WeatherAdd.date_custom, F.text, ~F.text.startswith("/"))
async def weather_add_date_custom(message: Message, state: FSMContext):
    d = parse_date(message.text)
    if not d:
        await message.answer("Sanani tushunmadim. Masalan: 15.09.2026 yoki 15.09")
        return
    if d > today():
        await message.answer("Kelajak sanasini yozib bo'lmaydi. Boshqa sana kiriting:")
        return
    await state.update_data(log_date=d.isoformat())
    await _weather_ask_condition(message.answer, state)


@router.callback_query(WeatherAdd.condition, F.data.startswith("wcond:"))
async def weather_add_condition(callback: CallbackQuery, state: FSMContext):
    label = kb.WEATHER_CONDITIONS.get(callback.data.split(":", 1)[1])
    if not label:
        await callback.answer()
        return
    await state.update_data(condition=label)
    await state.set_state(WeatherAdd.temp)
    await callback.message.edit_text(
        f"{label}\n🌡 Harorat (°C)? Masalan: 24 yoki -3", reply_markup=kb.skip_kb("skip_wtemp")
    )
    await callback.answer()


@router.message(WeatherAdd.temp, F.text, ~F.text.startswith("/"))
async def weather_add_temp(message: Message, state: FSMContext):
    temp = parse_temp(message.text)
    if temp is None:
        await message.answer("Tushunmadim. Masalan: 24 yoki -3 — yoki tugmani bosing.")
        return
    await state.update_data(temp=temp)
    await state.set_state(WeatherAdd.note)
    await message.answer("📝 Izoh (masalan: 'shamol kuchli edi'):", reply_markup=kb.skip_kb("skip_wnote"))


@router.callback_query(WeatherAdd.temp, F.data == "skip_wtemp")
async def weather_add_temp_skip(callback: CallbackQuery, state: FSMContext):
    await state.update_data(temp=None)
    await state.set_state(WeatherAdd.note)
    await callback.message.edit_text("📝 Izoh (masalan: 'shamol kuchli edi'):", reply_markup=kb.skip_kb("skip_wnote"))
    await callback.answer()


@router.message(WeatherAdd.note, F.text, ~F.text.startswith("/"))
async def weather_add_note(message: Message, state: FSMContext):
    await _finish_weather_add(state, message.text.strip(), message.answer)


@router.callback_query(WeatherAdd.note, F.data == "skip_wnote")
async def weather_add_note_skip(callback: CallbackQuery, state: FSMContext):
    await _finish_weather_add(state, None, callback.message.edit_text)
    await callback.answer()


async def _finish_weather_add(state, note, answer_func):
    data = await state.get_data()
    city = db.get_city(data["city_id"])
    country = db.get_country(city["country_id"])
    db.add_weather(data["city_id"], data["log_date"], data["condition"], data.get("temp"), note)
    await state.clear()
    text = f"✅ Ob-havo yozildi\n📅 {fmt_date(data['log_date'])} — {esc(data['condition'])}"
    if data.get("temp") is not None:
        text += f", 🌡 {fmt_num(data['temp'])}°C"
    if note:
        text += f"\n📝 {esc(note)}"
    text += f"\n🏙 {esc(country['name'])} — {esc(city['name'])}"
    await answer_func(text)


# ================= STATS =================

@router.message(Command("stats"))
async def cmd_stats(message: Message, state: FSMContext):
    await state.clear()
    s = db.get_stats(message.from_user.id)
    lines = [
        "📊 <b>Statistika</b>",
        "",
        f"✅ Borgan davlatlar: {s['visited_count']}",
        f"🎯 Wishlist: {s['wishlist_count']}",
        f"📍 Saqlangan joylar: {s['places_count']}",
        "",
    ]
    if not s["totals"]:
        lines.append("💵 Hali xarajat qo'shilmagan.")
    else:
        lines.append("💵 <b>Jami sarflangan</b>")
        for r in sort_by_currency(s["totals"]):
            lines.append(f"• {fmt_amount(r['total'], r['currency'])}")

        best = {}
        for r in s["by_category"]:
            cur = r["currency"]
            if cur not in best or r["total"] > best[cur]["total"]:
                best[cur] = r
        lines += ["", "🔝 <b>Eng ko'p sarflangan toifa</b>"]
        for r in sort_by_currency(best.values()):
            lines.append(f"• {esc(r['category'])}: {fmt_amount(r['total'], r['currency'])}")

        by_cur = {}
        for r in s["by_country"]:
            by_cur.setdefault(r["currency"], []).append(r)
        country_lines = []
        for cur, rows in sorted(by_cur.items(), key=lambda kv: currency_key(kv[0])):
            if len(rows) < 2:  # solishtirish uchun kamida 2 ta davlat kerak
                continue
            hi = max(rows, key=lambda x: x["total"])
            lo = min(rows, key=lambda x: x["total"])
            country_lines.append(f"💸 Eng qimmat ({cur_sym(cur)}): {esc(hi['name'])} — {fmt_amount(hi['total'], cur)}")
            country_lines.append(f"💵 Eng arzon ({cur_sym(cur)}): {esc(lo['name'])} — {fmt_amount(lo['total'], cur)}")
        if country_lines:
            lines += [""] + country_lines
    await message.answer("\n".join(lines))


# ================= XATOLIKLAR =================

async def on_error(event):
    """Handler ichida xato bo'lsa, jim qolmaydi: logga yozadi va foydalanuvchiga sababini ko'rsatadi."""
    exc = event.exception
    upd = event.update
    if type(exc).__name__ == "TelegramBadRequest" and "message is not modified" in str(exc):
        if upd.callback_query:
            try:
                await upd.callback_query.answer()
            except Exception:
                pass
        return True
    log.error("Handler xatosi", exc_info=exc)
    text = (
        f"⚠️ Xatolik yuz berdi:\n<code>{esc(type(exc).__name__)}: {esc(cut(exc, 300))}</code>\n\n"
        "Qaytadan urinib ko'ring yoki /cancel bosing."
    )
    try:
        if upd.message:
            await upd.message.answer(text)
        elif upd.callback_query:
            await upd.callback_query.answer()
            if upd.callback_query.message:
                await upd.callback_query.message.answer(text)
    except Exception:
        log.exception("Xato haqida xabar yuborib bo'lmadi")
    return True


router.errors.register(on_error)
