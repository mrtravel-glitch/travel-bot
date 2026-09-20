import re
from datetime import date
from html import escape

import aiohttp
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery, InputMediaPhoto

import database as db
import keyboards as kb
from states import Pick, TripAdd, TripsNewCity, DiaryAdd, PlaceAdd, ContactAdd, ExpenseAdd, FileAdd

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
        "/trips — davlat va shahar tanlab, to'liq ma'lumotni ko'rish\n\n"
        "<b>Kundalik</b> (davlat/shahar so'raladi)\n"
        "/diary_add — yozuv qo'shish\n"
        "/diary — yozuvlarni ko'rish\n\n"
        "<b>Joylar</b>\n"
        "/place_add — joy qo'shish (davlat/shahar tanlash bilan)\n"
        "/places — joylarni ko'rish (turi bo'yicha filtr)\n\n"
        "<b>Kontaktlar</b> (davlat/shahar so'raladi)\n"
        "/contact_add — kontakt qo'shish\n"
        "/contacts — kontaktlar ro'yxati\n\n"
        "<b>Xarajatlar</b> (davlat/shahar so'raladi)\n"
        "/expense_add — xarajat qo'shish\n"
        "/expenses — shahar + davlat bo'yicha hisobot\n\n"
        "<b>Fayllar</b> (davlat/shahar so'raladi)\n"
        "/file_add — chipta/hujjat saqlash\n"
        "/files — fayllarni ko'rish\n\n"
        "<b>Ob-havo</b>\n"
        "/weather — tanlangan shahar uchun joriy ob-havo\n\n"
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

ADD_PURPOSES = {"diary_add", "contact_add", "file_add", "expense_add"}


async def _reply(target, text, edit, **kwargs):
    """edit=True bo'lsa tugmali xabarni tahrirlaydi, aks holda yangi xabar yuboradi."""
    if edit:
        await target.edit_text(text, **kwargs)
    else:
        await target.answer(text, **kwargs)


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
    country = db.get_country(int(val))
    if not country or country["user_id"] != callback.from_user.id:
        await callback.answer("Davlat topilmadi", show_alert=True)
        return
    await callback.answer()
    await _pick_ask_city(callback.message, state, country["id"], edit=True)


@router.message(Pick.new_country_name, F.text, ~F.text.startswith("/"))
async def pick_new_country_name(message: Message, state: FSMContext):
    name = message.text.strip()
    existing = db.find_country_by_name(message.from_user.id, name)
    if existing:
        await message.answer(f"ℹ️ \"{existing['name']}\" allaqachon mavjud, unga bog'landi.")
        await _pick_ask_city(message, state, existing["id"], edit=False)
        return
    await state.update_data(new_country_name=name)
    await state.set_state(Pick.new_country_status)
    await message.answer("Holati qanday?", reply_markup=kb.status_kb())


@router.callback_query(Pick.new_country_status, F.data.startswith("status:"))
async def pick_new_country_status(callback: CallbackQuery, state: FSMContext):
    status = callback.data.split(":")[1]
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
    city = db.get_city(int(val))
    if not city or city["country_id"] != data.get("country_id"):
        await callback.answer("Shahar topilmadi", show_alert=True)
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
    where = escape(f"{country['name']} — {city['name']}")

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
    country = db.get_country(country_id)
    city = db.get_city(city_id)
    await callback.message.edit_text(build_city_profile(country, city))
    await callback.answer()


@router.message(TripsNewCity.name)
async def trips_new_city_name(message: Message, state: FSMContext):
    data = await state.get_data()
    country_id = data["new_city_country_id"]
    city_id = db.add_city(country_id, message.text.strip())
    await state.clear()
    country = db.get_country(country_id)
    city = db.get_city(city_id)
    await message.answer(build_city_profile(country, city))


@router.message(Command("trip"))
async def cmd_trip(message: Message):
    # Eski /trip endi /trips bilan bir xil ishlaydi
    await cmd_trips(message)


# ================= DIARY =================

@router.message(Command("diary_add"))
async def diary_add_start(message: Message, state: FSMContext):
    await _start_pick(message, state, "diary_add")


@router.message(DiaryAdd.text, F.photo)
async def diary_add_photo(message: Message, state: FSMContext):
    data = await state.get_data()
    db.add_diary(data["city_id"], str(date.today()), message.caption or "", message.photo[-1].file_id)
    await state.clear()
    await message.answer("✅ Kundalikka rasm bilan saqlandi")


@router.message(DiaryAdd.text)
async def diary_add_text(message: Message, state: FSMContext):
    data = await state.get_data()
    db.add_diary(data["city_id"], str(date.today()), message.text, None)
    await state.clear()
    await message.answer("✅ Kundalikka saqlandi")


@router.message(Command("diary"))
async def cmd_diary(message: Message, state: FSMContext):
    await _start_pick(message, state, "diary")


async def _show_diary(target, city_id, where, edit):
    entries = db.get_diary(city_id)
    if not entries:
        await _reply(target, f"📔 {where}\nBu shahar uchun hali kundalik yozuvlari yo'q.", edit)
        return
    await _reply(target, f"📔 {where} — kundalik", edit)
    for e in entries[:10]:
        caption = f"📅 {e['entry_date']}\n{e['text'] or ''}"
        if e["photo_file_id"]:
            await target.answer_photo(e["photo_file_id"], caption=caption)
        else:
            await target.answer(caption)


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
    await _start_pick(message, state, "contact_add")


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
    db.add_contact(data["city_id"], data["name"], data.get("contact_info"), notes)
    await state.clear()
    await answer_func(f"✅ Kontakt saqlandi: {data['name']}")


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
        line = f"👤 <b>{c['name']}</b>"
        if c["contact_info"]:
            line += f" — {c['contact_info']}"
        if c["notes"]:
            line += f"\n📝 {c['notes']}"
        lines.append(line)
    await _reply(target, f"👤 {where}\n\n" + "\n\n".join(lines), edit)


# ================= EXPENSES =================

@router.message(Command("expense_add"))
async def expense_add_start(message: Message, state: FSMContext):
    await _start_pick(message, state, "expense_add")


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
    data = await state.get_data()
    places = db.get_places(data["city_id"])
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
    db.add_expense(
        data["city_id"], data["category"], data["amount"], "so'm", str(date.today()), data.get("place_id"), note
    )
    await state.clear()
    await answer_func(f"✅ Xarajat qo'shildi: {data['category']} — {fmt_money(data['amount'])} so'm")


@router.message(Command("expenses"))
async def cmd_expenses(message: Message, state: FSMContext):
    await _start_pick(message, state, "expenses")


def _expenses_text(city, country):
    summary = db.get_expense_summary(city["id"])
    country_total = db.get_country_expense_total(country["id"])
    if not summary and country_total == 0:
        return "Bu davlat uchun hali xarajat qo'shilmagan."
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


@router.message(FileAdd.notes)
async def file_add_notes(message: Message, state: FSMContext):
    await _finish_file_add(message.from_user.id, state, message.text.strip(), message.answer)


@router.callback_query(FileAdd.notes, F.data == "skip_file_notes")
async def file_add_notes_skip(callback: CallbackQuery, state: FSMContext):
    await _finish_file_add(callback.from_user.id, state, None, callback.message.edit_text)
    await callback.answer()


async def _finish_file_add(user_id, state, notes, answer_func):
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
    await _reply(target, f"📎 {where} — fayllar", edit)
    for f in files:
        caption = f["file_name"] or "Fayl"
        if f["notes"]:
            caption += f"\n📝 {f['notes']}"
        if f["file_type"] == "photo":
            await target.answer_photo(f["file_id"], caption=caption)
        else:
            await target.answer_document(f["file_id"], caption=caption)


# ================= WEATHER =================

@router.message(Command("weather"))
async def cmd_weather(message: Message, state: FSMContext):
    await _start_pick(message, state, "weather")


async def _show_weather(target, user_id, city, country, edit):
    city_name = city["name"] or country["name"]
    result = await fetch_weather(city_name)
    if not result:
        await _reply(target, "Ob-havo topilmadi. Shahar nomini tekshiring yoki keyinroq urinib ko'ring.", edit)
        return
    desc = WEATHER_CODES.get(result["code"], "🌡")
    text = (
        f"🌤 <b>{result['city']}</b>\n{desc}\n"
        f"🌡 Harorat: {result['temp']}°C\n💨 Shamol: {result['wind']} km/soat"
    )
    weather_cache[user_id] = {"text": text, "city_id": city["id"]}
    await _reply(target, text, edit, reply_markup=kb.weather_save_kb())


@router.callback_query(F.data == "save_weather")
async def cb_save_weather(callback: CallbackQuery):
    cached = weather_cache.get(callback.from_user.id)
    if cached:
        db.add_diary(cached["city_id"], str(date.today()), cached["text"], None)
        await callback.message.edit_text(cached["text"] + "\n\n✅ Kundalikka saqlandi")
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
