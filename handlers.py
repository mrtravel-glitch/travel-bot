from datetime import date

import aiohttp
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery, InputMediaPhoto

import database as db
import keyboards as kb
from states import TripAdd, DiaryAdd, PlaceAdd, ContactAdd, ExpenseAdd, FileAdd

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

# Foydalanuvchi oxirgi ob-havo natijasini vaqtincha saqlab turish (kundalikka saqlash tugmasi uchun)
weather_cache = {}


def fmt_money(amount):
    return f"{amount:,.0f}".replace(",", " ")


def build_trip_profile(trip):
    emoji = "✅" if trip["status"] == "visited" else "🎯"
    text = f"{emoji} <b>{trip['country']}</b>"
    if trip["city"]:
        text += f", {trip['city']}"
    if trip["notes"]:
        text += f"\n📝 {trip['notes']}"

    places = db.get_places(trip["id"])
    diary = db.get_diary(trip["id"])
    contacts = db.get_contacts(trip["id"])
    files = db.get_files(trip["id"])
    summary = db.get_expense_summary(trip["id"])
    total = sum(r["total"] for r in summary) if summary else 0

    text += (
        f"\n\n📍 Joylar: {len(places)}\n📔 Kundalik: {len(diary)}\n"
        f"👤 Kontaktlar: {len(contacts)}\n📎 Fayllar: {len(files)}\n"
        f"💰 Jami xarajat: {fmt_money(total)} so'm"
    )
    if trip["budget"]:
        qoldiq = float(trip["budget"]) - float(total)
        holat = "✅" if qoldiq >= 0 else "⚠️"
        text += (
            f"\n🎯 Byudjet: {fmt_money(trip['budget'])} so'm"
            f"\n{holat} Qoldiq: {fmt_money(qoldiq)} so'm"
        )
    return text


async def fetch_weather(city):
    timeout = aiohttp.ClientTimeout(total=10)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            geo_url = "https://geocoding-api.open-meteo.com/v1/search"
            async with session.get(geo_url, params={"name": city, "count": 1}) as resp:
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
        "Borgan va bormoqchi bo'lgan davlatlaringizni, kundaligingizni, "
        "joylar, kontaktlar, fayllar va xarajatlaringizni saqlab boraman.\n\n"
        "Boshlash uchun: /trip_add — yangi safar qo'shing\n"
        "Barcha komandalar: /help"
    )


@router.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(
        "📋 <b>Komandalar</b>\n\n"
        "<b>Safarlar</b>\n"
        "/trip_add — yangi davlat/safar qo'shish (byudjet bilan)\n"
        "/trips — barcha safarlar, faolini tanlash (to'liq ma'lumot bilan)\n"
        "/trip — hozirgi faol safar haqida to'liq ma'lumot\n\n"
        "<b>Kundalik</b>\n"
        "/diary_add — yozuv qo'shish (matn yoki rasm+izoh)\n"
        "/diary — yozuvlarni ko'rish\n\n"
        "<b>Joylar</b>\n"
        "/place_add — mehmonxona/restoran/joy qo'shish (lokatsiya+rasm bilan)\n"
        "/places — joylar ro'yxati\n\n"
        "<b>Kontaktlar</b>\n"
        "/contact_add — kontakt qo'shish\n"
        "/contacts — kontaktlar ro'yxati\n\n"
        "<b>Xarajatlar</b>\n"
        "/expense_add — xarajat qo'shish (joyga bog'lash bilan)\n"
        "/expenses — faol safar bo'yicha hisobot\n\n"
        "<b>Fayllar</b>\n"
        "/file_add — chipta/hujjat/bron faylini saqlash\n"
        "/files — saqlangan fayllarni ko'rish\n\n"
        "<b>Ob-havo</b>\n"
        "/weather — faol safar shahri uchun joriy ob-havo\n\n"
        "<b>Statistika</b>\n"
        "/stats — umumiy statistika\n\n"
        "❌ /cancel — joriy amalni bekor qilish"
    )


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Bekor qilindi ❌")


async def require_active_trip(message: Message):
    trip = db.get_active_trip(message.from_user.id)
    if not trip:
        await message.answer(
            "Avval faol safarni tanlang: /trips\nYoki yangi safar qo'shing: /trip_add"
        )
        return None
    return trip


# ================= TRIPS =================

@router.message(Command("trip_add"))
async def trip_add_start(message: Message, state: FSMContext):
    await state.set_state(TripAdd.country)
    await message.answer("🌍 Davlat nomini kiriting (masalan: O'zbekiston):")


@router.message(TripAdd.country)
async def trip_add_country(message: Message, state: FSMContext):
    await state.update_data(country=message.text.strip())
    await state.set_state(TripAdd.city)
    await message.answer("🏙 Shahar nomini kiriting:", reply_markup=kb.skip_kb("skip_city"))


@router.message(TripAdd.city)
async def trip_add_city(message: Message, state: FSMContext):
    await state.update_data(city=message.text.strip())
    await state.set_state(TripAdd.status)
    await message.answer("Safar holati qanday?", reply_markup=kb.status_kb())


@router.callback_query(TripAdd.city, F.data == "skip_city")
async def trip_add_city_skip(callback: CallbackQuery, state: FSMContext):
    await state.update_data(city=None)
    await state.set_state(TripAdd.status)
    await callback.message.edit_text("Safar holati qanday?", reply_markup=kb.status_kb())
    await callback.answer()


@router.callback_query(TripAdd.status, F.data.startswith("status:"))
async def trip_add_status(callback: CallbackQuery, state: FSMContext):
    status = callback.data.split(":")[1]
    await state.update_data(status=status)
    await state.set_state(TripAdd.budget)
    await callback.message.edit_text(
        "💰 Rejalashtirilgan byudjet (so'mda, masalan 3000000):",
        reply_markup=kb.skip_kb("skip_budget"),
    )
    await callback.answer()


@router.message(TripAdd.budget)
async def trip_add_budget(message: Message, state: FSMContext):
    text = message.text.strip().replace(" ", "").replace(",", "")
    try:
        budget = float(text)
    except ValueError:
        await message.answer("Iltimos, faqat raqam kiriting, yoki tugmani bosing.")
        return
    await state.update_data(budget=budget)
    await state.set_state(TripAdd.notes)
    await message.answer("Izoh qoldirmoqchimisiz?", reply_markup=kb.skip_kb("skip_trip_notes"))


@router.callback_query(TripAdd.budget, F.data == "skip_budget")
async def trip_add_budget_skip(callback: CallbackQuery, state: FSMContext):
    await state.update_data(budget=None)
    await state.set_state(TripAdd.notes)
    await callback.message.edit_text("Izoh qoldirmoqchimisiz?", reply_markup=kb.skip_kb("skip_trip_notes"))
    await callback.answer()


@router.message(TripAdd.notes)
async def trip_add_notes(message: Message, state: FSMContext):
    await _finish_trip_add(message.from_user.id, state, message.text.strip(), message.answer)


@router.callback_query(TripAdd.notes, F.data == "skip_trip_notes")
async def trip_add_notes_skip(callback: CallbackQuery, state: FSMContext):
    await _finish_trip_add(callback.from_user.id, state, None, callback.message.edit_text)
    await callback.answer()


async def _finish_trip_add(user_id, state, notes, answer_func):
    data = await state.get_data()
    trip_id = db.add_trip(
        user_id=user_id, country=data["country"], city=data.get("city"),
        status=data["status"], budget=data.get("budget"), notes=notes,
    )
    db.set_active_trip(user_id, trip_id)
    await state.clear()
    emoji = "✅" if data["status"] == "visited" else "🎯"
    label = data["country"] + (f", {data['city']}" if data.get("city") else "")
    await answer_func(f"{emoji} Saqlandi: {label}\nBu endi sizning faol safaringiz.")


@router.message(Command("trips"))
async def cmd_trips(message: Message):
    trips = db.get_trips(message.from_user.id)
    if not trips:
        await message.answer("Hali safarlar yo'q. /trip_add orqali qo'shing.")
        return
    await message.answer("Safarni tanlang:", reply_markup=kb.trips_kb(trips))


@router.callback_query(F.data.startswith("select_trip:"))
async def cb_select_trip(callback: CallbackQuery):
    trip_id = int(callback.data.split(":")[1])
    db.set_active_trip(callback.from_user.id, trip_id)
    trip = db.get_trip(trip_id)
    await callback.message.edit_text(build_trip_profile(trip))
    await callback.answer()


@router.message(Command("trip"))
async def cmd_trip(message: Message):
    trip = await require_active_trip(message)
    if not trip:
        return
    await message.answer(build_trip_profile(trip))


# ================= DIARY =================

@router.message(Command("diary_add"))
async def diary_add_start(message: Message, state: FSMContext):
    trip = await require_active_trip(message)
    if not trip:
        return
    await state.set_state(DiaryAdd.text)
    await message.answer("📔 Yozuvingizni yuboring (matn, yoki rasm + izoh):")


@router.message(DiaryAdd.text, F.photo)
async def diary_add_photo(message: Message, state: FSMContext):
    trip = db.get_active_trip(message.from_user.id)
    db.add_diary(trip["id"], str(date.today()), message.caption or "", message.photo[-1].file_id)
    await state.clear()
    await message.answer("✅ Kundalikka rasm bilan saqlandi")


@router.message(DiaryAdd.text)
async def diary_add_text(message: Message, state: FSMContext):
    trip = db.get_active_trip(message.from_user.id)
    db.add_diary(trip["id"], str(date.today()), message.text, None)
    await state.clear()
    await message.answer("✅ Kundalikka saqlandi")


@router.message(Command("diary"))
async def cmd_diary(message: Message):
    trip = await require_active_trip(message)
    if not trip:
        return
    entries = db.get_diary(trip["id"])
    if not entries:
        await message.answer("Bu safar uchun hali kundalik yozuvlari yo'q.")
        return
    for e in entries[:10]:
        caption = f"📅 {e['entry_date']}\n{e['text'] or ''}"
        if e["photo_file_id"]:
            await message.answer_photo(e["photo_file_id"], caption=caption)
        else:
            await message.answer(caption)


# ================= PLACES =================

@router.message(Command("place_add"))
async def place_add_start(message: Message, state: FSMContext):
    trip = await require_active_trip(message)
    if not trip:
        return
    await state.set_state(PlaceAdd.name)
    await message.answer("📍 Joy nomini kiriting:")


@router.message(PlaceAdd.name)
async def place_add_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text.strip())
    await state.set_state(PlaceAdd.city)
    trip = db.get_active_trip(message.from_user.id)
    default_city = trip["city"] or "shahar belgilanmagan"
    await message.answer(
        f"🏙 Qaysi shahar uchun? (o'tkazib yuborsangiz — {default_city})",
        reply_markup=kb.skip_kb("skip_place_city"),
    )


@router.message(PlaceAdd.city)
async def place_add_city(message: Message, state: FSMContext):
    await state.update_data(city=message.text.strip())
    await state.set_state(PlaceAdd.type)
    await message.answer("Turi qanday?", reply_markup=kb.place_type_kb())


@router.callback_query(PlaceAdd.city, F.data == "skip_place_city")
async def place_add_city_skip(callback: CallbackQuery, state: FSMContext):
    trip = db.get_active_trip(callback.from_user.id)
    await state.update_data(city=trip["city"])
    await state.set_state(PlaceAdd.type)
    await callback.message.edit_text("Turi qanday?", reply_markup=kb.place_type_kb())
    await callback.answer()


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
    await _finish_place_add(message.from_user.id, state, message.text.strip(), message.answer)


@router.callback_query(PlaceAdd.notes, F.data == "skip_place_notes")
async def place_add_notes_skip(callback: CallbackQuery, state: FSMContext):
    await _finish_place_add(callback.from_user.id, state, None, callback.message.edit_text)
    await callback.answer()


async def _finish_place_add(user_id, state, notes, answer_func):
    data = await state.get_data()
    trip = db.get_active_trip(user_id)
    place_id = db.add_place(
        trip["id"], data["name"], data["type"], data.get("city"), data.get("is_halal"),
        data.get("price"), data.get("rating"), data.get("address"),
        data.get("latitude"), data.get("longitude"), notes,
    )
    for photo_id in data.get("photos", []):
        db.add_place_photo(place_id, photo_id)
    await state.clear()
    photo_note = f", {len(data.get('photos', []))} ta rasm" if data.get("photos") else ""
    await answer_func(f"✅ Saqlandi: {data['name']} ({TYPE_NAMES.get(data['type'], data['type'])}{photo_note})")


def _place_line(p):
    emoji = {"hotel": "🏨", "restaurant": "🍽", "attraction": "🏛"}.get(p["type"], "📍")
    line = f"{emoji} <b>{p['name']}</b>"
    if p["city"]:
        line += f" — {p['city']}"
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


async def _send_place(bot_message_target, p):
    line = _place_line(p)
    photos = db.get_place_photos(p["id"])
    if not photos:
        await bot_message_target.answer(line)
    elif len(photos) == 1:
        await bot_message_target.answer_photo(photos[0]["photo_file_id"], caption=line)
    else:
        media = [InputMediaPhoto(media=photos[0]["photo_file_id"], caption=line)]
        media += [InputMediaPhoto(media=ph["photo_file_id"]) for ph in photos[1:10]]
        await bot_message_target.answer_media_group(media)


@router.message(Command("places"))
async def cmd_places(message: Message):
    trip = await require_active_trip(message)
    if not trip:
        return
    places = db.get_places(trip["id"])
    if not places:
        await message.answer("Bu safar uchun hali joylar qo'shilmagan.")
        return
    cities = db.get_trip_cities(trip["id"])
    if len(cities) > 1:
        await message.answer("Qaysi shahar?", reply_markup=kb.city_filter_kb(cities))
    else:
        city = cities[0] if cities else "all"
        await message.answer("Qaysi turi?", reply_markup=kb.type_filter_kb(city))


@router.callback_query(F.data.startswith("places_city:"))
async def cb_places_city(callback: CallbackQuery):
    city = callback.data.split(":", 1)[1]
    await callback.message.edit_text("Qaysi turi?", reply_markup=kb.type_filter_kb(city))
    await callback.answer()


@router.callback_query(F.data.startswith("places_show:"))
async def cb_places_show(callback: CallbackQuery):
    _, city, ptype = callback.data.split(":", 2)
    trip = db.get_active_trip(callback.from_user.id)
    city_filter = None if city == "all" else city
    type_filter = None if ptype == "all" else ptype
    places = db.get_places(trip["id"], city=city_filter, ptype=type_filter)
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
    trip = await require_active_trip(message)
    if not trip:
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
    trip = db.get_active_trip(user_id)
    db.add_contact(trip["id"], data["name"], data.get("contact_info"), notes)
    await state.clear()
    await answer_func(f"✅ Kontakt saqlandi: {data['name']}")


@router.message(Command("contacts"))
async def cmd_contacts(message: Message):
    trip = await require_active_trip(message)
    if not trip:
        return
    contacts = db.get_contacts(trip["id"])
    if not contacts:
        await message.answer("Bu safar uchun hali kontaktlar yo'q.")
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
    trip = await require_active_trip(message)
    if not trip:
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
    text = message.text.strip().replace(" ", "").replace(",", "")
    try:
        amount = float(text)
    except ValueError:
        await message.answer("Iltimos, faqat raqam kiriting (masalan: 35000)")
        return
    await state.update_data(amount=amount)
    trip = db.get_active_trip(message.from_user.id)
    places = db.get_places(trip["id"])
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
    trip = db.get_active_trip(user_id)
    db.add_expense(
        trip["id"], data["category"], data["amount"], "so'm", str(date.today()), data.get("place_id"), note
    )
    await state.clear()
    await answer_func(f"✅ Xarajat qo'shildi: {data['category']} — {fmt_money(data['amount'])} so'm")


@router.message(Command("expenses"))
async def cmd_expenses(message: Message):
    trip = await require_active_trip(message)
    if not trip:
        return
    summary = db.get_expense_summary(trip["id"])
    if not summary:
        await message.answer("Bu safar uchun hali xarajat qo'shilmagan.")
        return
    lines = [f"💰 <b>{trip['country']} xarajatlari</b>", "━━━━━━━━━━━━━━━"]
    total = 0
    for row in summary:
        total += row["total"]
        lines.append(f"{row['category']}: {fmt_money(row['total'])} {row['currency']}")
    lines.append("━━━━━━━━━━━━━━━")
    lines.append(f"💵 JAMI: {fmt_money(total)} so'm")
    if trip["budget"]:
        qoldiq = float(trip["budget"]) - float(total)
        holat = "✅" if qoldiq >= 0 else "⚠️"
        lines.append(f"🎯 Byudjet: {fmt_money(trip['budget'])} so'm")
        lines.append(f"{holat} Qoldiq: {fmt_money(qoldiq)} so'm")
    await message.answer("\n".join(lines))


# ================= FILES =================

@router.message(Command("file_add"))
async def file_add_start(message: Message, state: FSMContext):
    trip = await require_active_trip(message)
    if not trip:
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
    trip = db.get_active_trip(user_id)
    db.add_file(trip["id"], data["file_id"], data["file_type"], data.get("file_name"), notes)
    await state.clear()
    await answer_func("✅ Fayl saqlandi")


@router.message(Command("files"))
async def cmd_files(message: Message):
    trip = await require_active_trip(message)
    if not trip:
        return
    files = db.get_files(trip["id"])
    if not files:
        await message.answer("Bu safar uchun hali fayllar yo'q.")
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
    trip = await require_active_trip(message)
    if not trip:
        return
    city = trip["city"] or trip["country"]
    result = await fetch_weather(city)
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
    trip = db.get_active_trip(callback.from_user.id)
    text = weather_cache.get(callback.from_user.id)
    if trip and text:
        db.add_diary(trip["id"], str(date.today()), text, None)
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
        me = s["most_expensive"]
        label = me["country"] + (f", {me['city']}" if me["city"] else "")
        text += f"\n💸 Eng qimmat safar: {label} ({fmt_money(me['total'])} so'm)"
    if s["cheapest"]:
        c = s["cheapest"]
        label = c["country"] + (f", {c['city']}" if c["city"] else "")
        text += f"\n💵 Eng arzon safar: {label} ({fmt_money(c['total'])} so'm)"
    await message.answer(text)
