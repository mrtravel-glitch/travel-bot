import re
from datetime import date

import openpyxl
from openpyxl.styles import Font

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery, FSInputFile

import database as db
import keyboards as kb
from states import TripAdd, PlaceAdd, ContactAdd, ExpenseAdd, FileAdd, WeatherAdd, DiaryAdd, ManageEdit

router = Router()

TYPE_LABELS = dict(kb.PLACE_TYPES)
CATEGORY_LABELS = dict(kb.CATEGORIES)
WEATHER_LABELS = dict(kb.WEATHER_OPTIONS)


# ================= UMUMIY YORDAMCHI FUNKSIYALAR =================

def fmt_money(amount):
    if amount is None:
        return "—"
    amount = float(amount)
    if amount == int(amount):
        s = f"{int(amount):,}"
    else:
        s = f"{amount:,.2f}"
    return s.replace(",", " ")


def parse_number(text):
    if not text:
        return None
    t = text.strip().replace(" ", "")
    t = t.replace(",", ".")
    t = re.sub(r"[^0-9.\-]", "", t)
    if not t or t in ("-", "."):
        return None
    try:
        return float(t)
    except ValueError:
        return None


def norm(text):
    return re.sub(r"\s+", " ", (text or "").strip()).lower()


def get_uid(event):
    return event.from_user.id


async def reply(event, text, markup=None):
    """Message bo'lsa yangi xabar, CallbackQuery bo'lsa mavjud xabarni tahrirlaydi."""
    if isinstance(event, CallbackQuery):
        try:
            await event.message.edit_text(text, reply_markup=markup)
        except Exception:
            await event.message.answer(text, reply_markup=markup)
    else:
        await event.answer(text, reply_markup=markup)


async def send_new(event, text, markup=None):
    """Har doim yangi xabar yuboradi (masalan rasm/fayl bilan birga bo'lganda)."""
    if isinstance(event, CallbackQuery):
        await event.message.answer(text, reply_markup=markup)
    else:
        await event.answer(text, reply_markup=markup)


CANCEL_ONLY = kb.nav_only_kb(back=False, cancel=True)


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
        "<b>Davlat / Shahar / Safar</b>\n"
        "/trip_add — yangi davlat/shahar/safar qo'shish (byudjet bilan)\n"
        "/trips — davlat, shahar va safar tanlash (faol qilish uchun)\n"
        "/trip — hozirgi faol safar haqida to'liq ma'lumot\n\n"
        "<b>Kundalik</b>\n"
        "/diary_add — yozuv qo'shish\n"
        "/diary — yozuvlarni ko'rish\n\n"
        "<b>Joylar</b>\n"
        "/place_add — joy qo'shish (davlat/shahar tanlash bilan)\n"
        "/places — joylarni ko'rish (davlat → shahar → tur)\n\n"
        "<b>Kontaktlar</b>\n"
        "/contact_add — kontakt qo'shish\n"
        "/contacts — kontaktlar ro'yxati\n\n"
        "<b>Xarajatlar</b>\n"
        "/expense_add — xarajat qo'shish\n"
        "/expenses — safar bo'yicha hisobot\n\n"
        "<b>Fayllar</b>\n"
        "/file_add — chipta/hujjat saqlash\n"
        "/files — fayllarni ko'rish\n\n"
        "<b>Ob-havo</b> (qo'lda belgilanadi)\n"
        "/weather_add — ob-havoni yozib qo'yish\n"
        "/weather — yozuvlarni ko'rish\n\n"
        "<b>Statistika</b>\n"
        "/stats — umumiy statistika\n"
        "/export — barcha ma'lumotlarni Excel fayl qilib olish\n\n"
        "<b>Boshqarish</b>\n"
        "/manage — davlat/shahar/safar/joy/kontakt/kundalik/xarajat/faylni "
        "tahrirlash yoki o'chirish"
    )


@router.callback_query(F.data == "nav:cancel")
async def nav_cancel(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await reply(callback, "Bekor qilindi ❌")
    await callback.answer()


# ================= UMUMIY: DAVLAT → SHAHAR → SAFAR TANLASH =================
# Bir nechta flow (place_add, contact_add, expense_add, file_add, weather_add,
# diary_add, trips, va ko'rish komandalari) bir xil "davlat -> shahar -> safar"
# zanjiridan foydalanadi. Callback prefikslari: PA, CA, EA, FA, WA, DA, TR, PL,
# CV, EV, FV, WV.

ON_TRIP_CHOSEN = {}   # prefix -> async fn(event, state, trip)
ON_CITY_CHOSEN = {}   # faqat trip bosqichi bo'lmagan oqimlar uchun (PL): fn(event, state, city)
CITY_DIRECT = {"PL"}  # bu prefikslar shahardan keyin to'g'ridan-to'g'ri davom etadi (safarsiz)


async def send_country_list(event, prefix, user_id, title="🌍 Davlatni tanlang:"):
    countries = db.get_countries(user_id)
    if not countries:
        await reply(event, "Hali davlat qo'shilmagan. Avval /trip_add orqali davlat va shahar qo'shing.")
        return
    markup = kb.country_select_kb(countries, f"{prefix}_CO", show_add=False, back=False)
    await reply(event, title, markup)


async def send_city_list(event, prefix, country_id):
    country = db.get_country(country_id)
    cities = db.get_cities(country_id)
    if not cities:
        b = kb.InlineKeyboardBuilder()
        b.button(text="⬅️ Orqaga", callback_data=f"{prefix}_BACKCO")
        b.adjust(1)
        await reply(event, f"🌍 {country['name']} da hali shahar yo'q. Avval /trip_add orqali qo'shing.", b.as_markup())
        return
    b = kb.InlineKeyboardBuilder()
    for c in cities:
        b.button(text=f"🏙 {c['name']}", callback_data=f"{prefix}_CI:{c['id']}")
    b.button(text="⬅️ Orqaga", callback_data=f"{prefix}_BACKCO")
    b.adjust(1)
    await reply(event, f"🌍 {country['name']}\n🏙 Shaharni tanlang:", b.as_markup())


async def send_trip_list(event, state, prefix, city_id):
    trips = db.get_trips(city_id)
    city = db.get_city(city_id)
    if not trips:
        b = kb.InlineKeyboardBuilder()
        country = db.get_country(city["country_id"])
        b.button(text="⬅️ Orqaga", callback_data=f"{prefix}_BACKCI:{country['id']}")
        b.adjust(1)
        await reply(event, f"🏙 {city['name']} uchun hali safar yo'q. Avval /trip_add orqali qo'shing.", b.as_markup())
        return
    if len(trips) == 1:
        handler = ON_TRIP_CHOSEN[prefix]
        await handler(event, state, trips[0])
        return
    labels = {}
    for i, t in enumerate(trips, 1):
        d = f" ({t['note'][:20]})" if t.get("note") else ""
        labels[t["id"]] = f"{i}-safar{d}"
    b = kb.InlineKeyboardBuilder()
    country = db.get_country(city["country_id"])
    for i, t in enumerate(trips, 1):
        emoji = "✅" if t["status"] == "visited" else "🎯"
        b.button(text=f"{emoji} {labels[t['id']]}", callback_data=f"{prefix}_TR:{t['id']}")
    b.button(text="⬅️ Orqaga", callback_data=f"{prefix}_BACKCI:{country['id']}")
    b.adjust(1)
    await reply(event, f"🏙 {city['name']}\n🧳 Safarni tanlang:", b.as_markup())


@router.callback_query(F.data.regexp(r"^([A-Z]{2})_CO:(\d+)$"))
async def generic_select_country(callback: CallbackQuery, state: FSMContext):
    prefix, val = callback.data.split("_CO:", 1)
    country_id = int(val)
    await send_city_list(callback, prefix, country_id)
    await callback.answer()


@router.callback_query(F.data.regexp(r"^([A-Z]{2})_CI:(\d+)$"))
async def generic_select_city(callback: CallbackQuery, state: FSMContext):
    prefix, val = callback.data.split("_CI:", 1)
    city_id = int(val)
    if prefix in CITY_DIRECT:
        city = db.get_city(city_id)
        await ON_CITY_CHOSEN[prefix](callback, state, city)
    else:
        await send_trip_list(callback, state, prefix, city_id)
    await callback.answer()


@router.callback_query(F.data.regexp(r"^([A-Z]{2})_TR:(\d+)$"))
async def generic_select_trip(callback: CallbackQuery, state: FSMContext):
    prefix, val = callback.data.split("_TR:", 1)
    trip_id = int(val)
    trip = db.get_trip(trip_id)
    await ON_TRIP_CHOSEN[prefix](callback, state, trip)
    await callback.answer()


@router.callback_query(F.data.regexp(r"^([A-Z]{2})_BACKCO$"))
async def generic_back_co(callback: CallbackQuery, state: FSMContext):
    prefix = callback.data.replace("_BACKCO", "")
    await send_country_list(callback, prefix, get_uid(callback))
    await callback.answer()


@router.callback_query(F.data.regexp(r"^([A-Z]{2})_BACKCI:(\d+)$"))
async def generic_back_ci(callback: CallbackQuery, state: FSMContext):
    prefix, val = callback.data.split("_BACKCI:", 1)
    await send_city_list(callback, prefix, int(val))
    await callback.answer()


# ================= MOLIYA HISOB-KITOBI =================

def get_trip_finance(trip):
    totals = db.get_expense_totals_by_currency(trip["id"])
    tmap = {r["currency"]: float(r["total"]) for r in totals}
    budget_cur = trip["budget_currency"]
    city_cur = trip["city_currency"]
    rate = float(trip["exchange_rate"]) if trip["exchange_rate"] else None
    budget_amt = float(trip["budget_amount"]) if trip["budget_amount"] is not None else None

    same = budget_cur and city_cur and budget_cur == city_cur
    result = {
        "tmap": tmap, "budget_cur": budget_cur, "city_cur": city_cur,
        "budget_amt": budget_amt, "rate": rate, "same": same,
    }
    if not budget_cur or not city_cur:
        result.update(total_budget_cur=None, total_city_cur=None, remaining_budget_cur=None,
                       remaining_city_cur=None, rate_known=False)
        return result

    if same:
        total = tmap.get(budget_cur, 0)
        remaining = (budget_amt - total) if budget_amt is not None else None
        result.update(total_budget_cur=total, total_city_cur=total,
                       remaining_budget_cur=remaining, remaining_city_cur=remaining, rate_known=True)
        return result

    amt_budget = tmap.get(budget_cur, 0)
    amt_city = tmap.get(city_cur, 0)
    if rate:
        total_budget_cur = amt_budget + (amt_city / rate)
        total_city_cur = amt_city + (amt_budget * rate)
        remaining_budget_cur = (budget_amt - total_budget_cur) if budget_amt is not None else None
        remaining_city_cur = (remaining_budget_cur * rate) if remaining_budget_cur is not None else None
        result.update(total_budget_cur=total_budget_cur, total_city_cur=total_city_cur,
                       remaining_budget_cur=remaining_budget_cur, remaining_city_cur=remaining_city_cur,
                       rate_known=True)
    else:
        result.update(total_budget_cur=None, total_city_cur=None, remaining_budget_cur=None,
                       remaining_city_cur=None, rate_known=False)
    return result


def fmt_finance_block(trip):
    f = get_trip_finance(trip)
    lines = []
    if f["budget_amt"] is not None:
        lines.append(f"🎯 Byudjet: {fmt_money(f['budget_amt'])} {f['budget_cur']}")
    if not f["same"] and f["city_cur"]:
        if f["rate"]:
            lines.append(f"💱 Kurs: 1 {f['budget_cur']} = {fmt_money(f['rate'])} {f['city_cur']}")
        else:
            lines.append("💱 Kurs: kiritilmagan")
    tmap = f["tmap"]
    if tmap:
        parts = [f"{fmt_money(v)} {c}" for c, v in tmap.items()]
        lines.append("💰 Xarajat: " + " + ".join(parts))
    else:
        lines.append("💰 Xarajat: 0")
    if f["budget_amt"] is not None:
        if f["rate_known"]:
            rem = f["remaining_budget_cur"]
            rem_city = f["remaining_city_cur"]
            if rem >= 0:
                lines.append(f"✅ Qoldiq: {fmt_money(rem)} {f['budget_cur']}")
                if not f["same"]:
                    lines.append(f"✅ Qoldiq ({f['city_cur']}da): {fmt_money(rem_city)} {f['city_cur']}")
            else:
                lines.append(f"⚠️ Byudjetdan oshdi: {fmt_money(-rem)} {f['budget_cur']}")
                if not f["same"]:
                    lines.append(f"⚠️ Oshgani ({f['city_cur']}da): {fmt_money(-rem_city)} {f['city_cur']}")
        else:
            lines.append("⚠️ Qoldiqni hisoblash uchun kurs kiritilmagan (/expense_add orqali kiritishingiz mumkin)")
    return "\n".join(lines)


def build_trip_card_text(trip, city, country):
    emoji = "✅" if trip["status"] == "visited" else "🎯"
    text = f"{emoji} <b>{country['name']}</b> — 🏙 {city['name']}"
    if trip.get("note"):
        text += f"\n📝 {trip['note']}"

    places = db.get_places(city["id"])
    counts = {}
    for p in places:
        counts[p["type"]] = counts.get(p["type"], 0) + 1
    if counts:
        parts = [f"{TYPE_LABELS.get(t, '📌 ' + t)}: {n}" for t, n in counts.items()]
        text += "\n\n📍 Joylar — " + ", ".join(parts)
    else:
        text += "\n\n📍 Joylar: 0"

    diary = db.get_diary(trip["id"])
    contacts = db.get_contacts(trip["id"])
    files = db.get_files(trip["id"])
    weather = db.get_weather_notes(trip["id"])
    text += (
        f"\n📔 Kundalik: {len(diary)}\n👤 Kontaktlar: {len(contacts)}\n"
        f"📎 Fayllar: {len(files)}\n🌤 Ob-havo yozuvlari: {len(weather)}"
    )
    text += "\n\n" + fmt_finance_block(trip)
    return text


async def show_trip_card(event, trip):
    city = db.get_city(trip["city_id"])
    country = db.get_country(city["country_id"])
    text = build_trip_card_text(trip, city, country)
    await reply(event, text, kb.trip_card_kb(trip["id"]))


# ================= /trip_add =================

@router.message(Command("trip_add"))
async def trip_add_start(message: Message, state: FSMContext):
    await state.clear()
    await state.set_state(TripAdd.select_country)
    countries = db.get_countries(message.from_user.id)
    await message.answer("🌍 Davlatni tanlang yoki yangisini qo'shing:",
                          reply_markup=kb.country_select_kb(countries, "TAD_CO", show_add=True, back=False))


@router.callback_query(TripAdd.select_country, F.data.startswith("TAD_CO:"))
async def tad_country_chosen(callback: CallbackQuery, state: FSMContext):
    val = callback.data.split("TAD_CO:", 1)[1]
    if val == "new":
        await state.set_state(TripAdd.new_country_name)
        await reply(callback, "✏️ Yangi davlat nomini yozing:", CANCEL_ONLY)
        await callback.answer()
        return
    country = db.get_country(int(val))
    await state.update_data(country_id=country["id"], country_name=country["name"])
    await tad_show_city_step(callback, state)
    await callback.answer()


@router.message(TripAdd.new_country_name)
async def tad_new_country_name(message: Message, state: FSMContext):
    name = message.text.strip() if message.text else ""
    if not name:
        await message.answer("Iltimos, davlat nomini matn ko'rinishida yozing:", reply_markup=CANCEL_ONLY)
        return
    existing = db.find_country_by_name(message.from_user.id, name)
    if existing:
        country = existing
    else:
        country = db.add_country(message.from_user.id, name)
    await state.update_data(country_id=country["id"], country_name=country["name"])
    await tad_show_city_step(message, state)


async def tad_show_city_step(event, state: FSMContext):
    data = await state.get_data()
    await state.set_state(TripAdd.select_city)
    cities = db.get_cities(data["country_id"])
    b = kb.InlineKeyboardBuilder()
    for c in cities:
        b.button(text=f"🏙 {c['name']}", callback_data=f"TAD_CI:{c['id']}")
    b.button(text="➕ Yangi shahar qo'shish", callback_data="TAD_CI:new")
    b.button(text="⬅️ Orqaga", callback_data="TAD_BACKCO")
    b.adjust(1)
    await reply(event, f"🌍 {data['country_name']}\n🏙 Shaharni tanlang yoki yangisini qo'shing:", b.as_markup())


@router.callback_query(TripAdd.select_city, F.data == "TAD_BACKCO")
async def tad_back_to_country(callback: CallbackQuery, state: FSMContext):
    await state.set_state(TripAdd.select_country)
    countries = db.get_countries(get_uid(callback))
    await reply(callback, "🌍 Davlatni tanlang yoki yangisini qo'shing:",
                kb.country_select_kb(countries, "TAD_CO", show_add=True, back=False))
    await callback.answer()


@router.callback_query(TripAdd.select_city, F.data.startswith("TAD_CI:"))
async def tad_city_chosen(callback: CallbackQuery, state: FSMContext):
    val = callback.data.split("TAD_CI:", 1)[1]
    data = await state.get_data()
    if val == "new":
        await state.set_state(TripAdd.new_city_name)
        await reply(callback, "✏️ Yangi shahar nomini yozing:", CANCEL_ONLY)
        await callback.answer()
        return
    city = db.get_city(int(val))
    await state.update_data(city_id=city["id"], city_name=city["name"], city_is_new=False)
    await tad_show_status_step(callback, state)
    await callback.answer()


@router.message(TripAdd.new_city_name)
async def tad_new_city_name(message: Message, state: FSMContext):
    name = message.text.strip() if message.text else ""
    if not name:
        await message.answer("Iltimos, shahar nomini matn ko'rinishida yozing:", reply_markup=CANCEL_ONLY)
        return
    data = await state.get_data()
    existing = db.find_city_by_name(data["country_id"], name)
    if existing:
        await message.answer(
            f"⚠️ Bu shahar ({existing['name']}) {data['country_name']} ro'yxatida allaqachon bor.\n"
            "Boshqa nom kiriting:",
            reply_markup=CANCEL_ONLY,
        )
        return
    city = db.add_city(data["country_id"], name)
    await state.update_data(city_id=city["id"], city_name=city["name"], city_is_new=True)
    await tad_show_status_step(message, state)


async def tad_show_status_step(event, state: FSMContext):
    await state.set_state(TripAdd.status)
    data = await state.get_data()
    await reply(event, f"🏙 {data['city_name']}\nBu yerga borganmisiz yoki bormoqchimisiz?",
                kb.status_kb(back_cb="TAD_BACKCI"))


@router.callback_query(TripAdd.status, F.data == "TAD_BACKCI")
async def tad_back_to_city(callback: CallbackQuery, state: FSMContext):
    await tad_show_city_step(callback, state)
    await callback.answer()


@router.callback_query(TripAdd.status, F.data.startswith("status:"))
async def tad_status_chosen(callback: CallbackQuery, state: FSMContext):
    status = callback.data.split("status:", 1)[1]
    await state.update_data(status=status)
    await tad_show_budget_currency_step(callback, state)
    await callback.answer()


async def tad_show_budget_currency_step(event, state: FSMContext):
    await state.set_state(TripAdd.budget_currency)
    await reply(event, "💰 Byudjetni qaysi valyutada rejalashtiryapsiz?",
                kb.currency_kb("TADBUDCUR", back_cb="TAD_BACKSTATUS"))


@router.callback_query(TripAdd.budget_currency, F.data == "TAD_BACKSTATUS")
async def tad_back_to_status(callback: CallbackQuery, state: FSMContext):
    await tad_show_status_step(callback, state)
    await callback.answer()


@router.callback_query(TripAdd.budget_currency, F.data.startswith("TADBUDCUR:"))
async def tad_budget_currency_chosen(callback: CallbackQuery, state: FSMContext):
    val = callback.data.split("TADBUDCUR:", 1)[1]
    if val == "custom":
        await state.set_state(TripAdd.budget_currency_custom)
        await reply(callback, "✏️ Valyuta nomini yozing (masalan: fung, rubl):", CANCEL_ONLY)
        await callback.answer()
        return
    await state.update_data(budget_currency=val)
    await tad_show_budget_amount_step(callback, state)
    await callback.answer()


@router.message(TripAdd.budget_currency_custom)
async def tad_budget_currency_custom(message: Message, state: FSMContext):
    val = message.text.strip() if message.text else ""
    if not val:
        await message.answer("Valyuta nomini matn ko'rinishida yozing:", reply_markup=CANCEL_ONLY)
        return
    await state.update_data(budget_currency=val)
    await tad_show_budget_amount_step(message, state)


async def tad_show_budget_amount_step(event, state: FSMContext):
    await state.set_state(TripAdd.budget_amount)
    data = await state.get_data()
    await reply(event, f"💰 Necha {data['budget_currency']} byudjet ajratmoqchisiz? (faqat son kiriting)",
                CANCEL_ONLY)


@router.message(TripAdd.budget_amount)
async def tad_budget_amount(message: Message, state: FSMContext):
    val = parse_number(message.text)
    if val is None:
        await message.answer("Iltimos, faqat son kiriting (masalan: 1000):", reply_markup=CANCEL_ONLY)
        return
    await state.update_data(budget_amount=val)
    await tad_show_city_currency_step(message, state)


async def tad_show_city_currency_step(event, state: FSMContext):
    await state.set_state(TripAdd.city_currency)
    data = await state.get_data()
    await reply(event, f"💱 {data['city_name']} da asosan qaysi valyuta ishlatiladi (milliy valyuta)?",
                kb.currency_kb("TADCITYCUR", back_cb="TAD_BACKBUDCUR"))


@router.callback_query(TripAdd.city_currency, F.data == "TAD_BACKBUDCUR")
async def tad_back_to_budcur(callback: CallbackQuery, state: FSMContext):
    await tad_show_budget_currency_step(callback, state)
    await callback.answer()


async def tad_after_city_currency(event, state: FSMContext, value):
    data = await state.get_data()
    await state.update_data(city_currency=value)
    if value == data["budget_currency"]:
        await state.update_data(exchange_rate=None)
        await tad_show_note_step(event, state)
    else:
        await tad_show_rate_step(event, state)


@router.callback_query(TripAdd.city_currency, F.data.startswith("TADCITYCUR:"))
async def tad_city_currency_chosen(callback: CallbackQuery, state: FSMContext):
    val = callback.data.split("TADCITYCUR:", 1)[1]
    if val == "custom":
        await state.set_state(TripAdd.city_currency_custom)
        await reply(callback, "✏️ Valyuta nomini yozing:", CANCEL_ONLY)
        await callback.answer()
        return
    await tad_after_city_currency(callback, state, val)
    await callback.answer()


@router.message(TripAdd.city_currency_custom)
async def tad_city_currency_custom(message: Message, state: FSMContext):
    val = message.text.strip() if message.text else ""
    if not val:
        await message.answer("Valyuta nomini matn ko'rinishida yozing:", reply_markup=CANCEL_ONLY)
        return
    await tad_after_city_currency(message, state, val)


async def tad_show_rate_step(event, state: FSMContext):
    await state.set_state(TripAdd.exchange_rate)
    data = await state.get_data()
    text = (
        f"💱 Hozirgi kunda 1 {data['budget_currency']} necha {data['city_currency']}?\n"
        f"(masalan: 1 {data['budget_currency']} = 7 {data['city_currency']})\n\n"
        f"Buni kiritganingizdan so'ng xarajatlarni {data['city_currency']}da yozing, "
        "hisob-kitob oson bo'ladi."
    )
    await reply(event, text, kb.later_kb("TADRATE_LATER", back_cb="TAD_BACKCITYCUR"))


@router.callback_query(TripAdd.exchange_rate, F.data == "TAD_BACKCITYCUR")
async def tad_back_to_citycur(callback: CallbackQuery, state: FSMContext):
    await tad_show_city_currency_step(callback, state)
    await callback.answer()


@router.callback_query(TripAdd.exchange_rate, F.data == "TADRATE_LATER")
async def tad_rate_later(callback: CallbackQuery, state: FSMContext):
    await state.update_data(exchange_rate=None)
    await tad_show_note_step(callback, state)
    await callback.answer()


@router.message(TripAdd.exchange_rate)
async def tad_rate_input(message: Message, state: FSMContext):
    val = parse_number(message.text)
    if val is None or val <= 0:
        await message.answer("Iltimos, faqat musbat son kiriting (masalan: 7):", reply_markup=CANCEL_ONLY)
        return
    await state.update_data(exchange_rate=val)
    await tad_show_note_step(message, state)


async def tad_show_note_step(event, state: FSMContext):
    await state.set_state(TripAdd.note)
    await reply(event, "📝 Izoh yozing (masalan borgan yil/oy/sana) yoki o'tkazib yuboring:",
                kb.skip_kb("TAD_NOTE_SKIP", back_cb="TAD_BACKRATE"))


@router.callback_query(TripAdd.note, F.data == "TAD_BACKRATE")
async def tad_back_to_rate(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    if data.get("budget_currency") == data.get("city_currency"):
        await tad_show_city_currency_step(callback, state)
    else:
        await tad_show_rate_step(callback, state)
    await callback.answer()


@router.callback_query(TripAdd.note, F.data == "TAD_NOTE_SKIP")
async def tad_note_skip(callback: CallbackQuery, state: FSMContext):
    await tad_finish(callback, state, note=None)
    await callback.answer()


@router.message(TripAdd.note)
async def tad_note_input(message: Message, state: FSMContext):
    await tad_finish(message, state, note=message.text.strip() if message.text else None)


async def tad_finish(event, state: FSMContext, note):
    data = await state.get_data()
    trip = db.add_trip(
        city_id=data["city_id"], status=data["status"], note=note,
        budget_amount=data.get("budget_amount"), budget_currency=data.get("budget_currency"),
        city_currency=data.get("city_currency"), exchange_rate=data.get("exchange_rate"),
    )
    db.set_active_trip(get_uid(event), trip["id"])
    await state.clear()
    await send_new(event, "✅ Safar saqlandi va faol qilindi!")
    await show_trip_card(event, trip)


# ================= /trips va /trip =================

@router.message(Command("trips"))
async def cmd_trips(message: Message, state: FSMContext):
    await state.clear()
    await send_country_list(message, "TR", message.from_user.id, "🌍 Davlatni tanlang:")


async def on_trip_chosen_TR(event, state, trip):
    db.set_active_trip(get_uid(event), trip["id"])
    await send_new(event, "✅ Faol safar tanlandi!")
    await show_trip_card(event, trip)


ON_TRIP_CHOSEN["TR"] = on_trip_chosen_TR


@router.message(Command("trip"))
async def cmd_trip(message: Message):
    trip = db.get_active_trip(message.from_user.id)
    if not trip:
        await message.answer("Avval faol safarni tanlang: /trips\nYoki yangi safar qo'shing: /trip_add")
        return
    await show_trip_card(message, trip)


# ---- Trip kartochkasidagi tugmalar (tc_*) ----

@router.callback_query(F.data.regexp(r"^tc_(places|place_add|contacts|contact_add|expenses|expense_add|files|file_add|weather|weather_add|diary|diary_add):(\d+)$"))
async def trip_card_button(callback: CallbackQuery, state: FSMContext):
    action, trip_id = callback.data.split(":")
    action = action.replace("tc_", "")
    trip = db.get_trip(int(trip_id))
    db.set_active_trip(get_uid(callback), trip["id"])
    await callback.answer()
    if action == "places":
        city = db.get_city(trip["city_id"])
        await show_places_for_city(callback, city)
    elif action == "place_add":
        await state.clear()
        await pa_after_trip_selected(callback, state, trip)
    elif action == "contacts":
        await cv_after_trip_selected(callback, state, trip)
    elif action == "contact_add":
        await state.clear()
        await ca_after_trip_selected(callback, state, trip)
    elif action == "expenses":
        await ev_after_trip_selected(callback, state, trip)
    elif action == "expense_add":
        await ea_after_trip_selected(callback, state, trip)
    elif action == "files":
        await fv_after_trip_selected(callback, state, trip)
    elif action == "file_add":
        await state.clear()
        await fa_after_trip_selected(callback, state, trip)
    elif action == "weather":
        await wv_after_trip_selected(callback, state, trip)
    elif action == "weather_add":
        await state.clear()
        await wa_after_trip_selected(callback, state, trip)
    elif action == "diary":
        await dv_after_trip_selected(callback, state, trip)
    elif action == "diary_add":
        await state.clear()
        await da_after_trip_selected(callback, state, trip)


# ================= /place_add =================

@router.message(Command("place_add"))
async def cmd_place_add(message: Message, state: FSMContext):
    await state.clear()
    await send_country_list(message, "PA", message.from_user.id, "📍 Joy qo'shish uchun davlatni tanlang:")


async def pa_after_trip_selected(event, state: FSMContext, trip):
    await state.set_state(PlaceAdd.type)
    await state.update_data(trip_id=trip["id"], city_id=trip["city_id"])
    await pa_show_type_step(event, state)


ON_TRIP_CHOSEN["PA"] = pa_after_trip_selected


async def pa_show_type_step(event, state: FSMContext):
    await state.set_state(PlaceAdd.type)
    data = await state.get_data()
    city = db.get_city(data["city_id"])
    back_cb = f"PA_BACKCI:{city['country_id']}"
    await reply(event, "📍 Joy turini tanlang:", kb.place_type_kb("PA_TYPE", back_cb=back_cb))


@router.callback_query(F.data == "PA_BACKTYPE")
async def pa_back_type(callback: CallbackQuery, state: FSMContext):
    await pa_show_type_step(callback, state)
    await callback.answer()


@router.callback_query(PlaceAdd.type, F.data.startswith("PA_TYPE:"))
async def pa_type_chosen(callback: CallbackQuery, state: FSMContext):
    val = callback.data.split("PA_TYPE:", 1)[1]
    if val == "other":
        await state.set_state(PlaceAdd.type_custom)
        await reply(callback, "✏️ Joy turini yozing (masalan: bozor, plyaj):", CANCEL_ONLY)
        await callback.answer()
        return
    await state.update_data(ptype=val)
    if val == "restaurant":
        await pa_show_halal_step(callback, state)
    else:
        await pa_show_name_step(callback, state)
    await callback.answer()


@router.message(PlaceAdd.type_custom)
async def pa_type_custom(message: Message, state: FSMContext):
    val = message.text.strip() if message.text else ""
    if not val:
        await message.answer("Joy turini matn ko'rinishida yozing:", reply_markup=CANCEL_ONLY)
        return
    await state.update_data(ptype=val)
    await pa_show_name_step(message, state)


async def pa_show_halal_step(event, state: FSMContext):
    await state.set_state(PlaceAdd.halal)
    await reply(event, "🍽 Bu restoran halolmi?", kb.yes_no_unknown_kb("PA_HALAL", back_cb="PA_BACKTYPE"))


@router.callback_query(F.data == "PA_BACKHALAL")
async def pa_back_halal(callback: CallbackQuery, state: FSMContext):
    await pa_show_halal_step(callback, state)
    await callback.answer()


@router.callback_query(PlaceAdd.halal, F.data.startswith("PA_HALAL:"))
async def pa_halal_chosen(callback: CallbackQuery, state: FSMContext):
    val = callback.data.split("PA_HALAL:", 1)[1]
    await state.update_data(is_halal=val)
    await pa_show_name_step(callback, state)
    await callback.answer()


async def pa_show_name_step(event, state: FSMContext):
    await state.set_state(PlaceAdd.name)
    await reply(event, "✏️ Joy nomini yozing:", CANCEL_ONLY)


@router.message(PlaceAdd.name)
async def pa_name_input(message: Message, state: FSMContext):
    name = message.text.strip() if message.text else ""
    if not name:
        await message.answer("Joy nomini matn ko'rinishida yozing:", reply_markup=CANCEL_ONLY)
        return
    await state.update_data(name=name)
    await pa_show_price_step(message, state)


async def pa_show_price_step(event, state: FSMContext):
    await state.set_state(PlaceAdd.price)
    data = await state.get_data()
    back_cb = "PA_BACKHALAL" if data.get("ptype") == "restaurant" else "PA_BACKTYPE"
    await reply(event, "💵 Narxini milliy (shahar) valyutasida yozing yoki o'tkazib yuboring:",
                kb.skip_kb("PA_PRICE_SKIP", back_cb=back_cb))


@router.callback_query(F.data == "PA_BACKPRICE")
async def pa_back_price(callback: CallbackQuery, state: FSMContext):
    await pa_show_price_step(callback, state)
    await callback.answer()


@router.callback_query(PlaceAdd.price, F.data == "PA_PRICE_SKIP")
async def pa_price_skip(callback: CallbackQuery, state: FSMContext):
    await state.update_data(price=None)
    await pa_show_rating_step(callback, state)
    await callback.answer()


@router.message(PlaceAdd.price)
async def pa_price_input(message: Message, state: FSMContext):
    await state.update_data(price=message.text.strip() if message.text else None)
    await pa_show_rating_step(message, state)


async def pa_show_rating_step(event, state: FSMContext):
    await state.set_state(PlaceAdd.rating)
    await reply(event, "⭐ Baholang yoki o'tkazib yuboring:", kb.rating_kb("PA_RATING", back_cb="PA_BACKPRICE"))


@router.callback_query(F.data == "PA_BACKRATING")
async def pa_back_rating(callback: CallbackQuery, state: FSMContext):
    await pa_show_rating_step(callback, state)
    await callback.answer()


@router.callback_query(PlaceAdd.rating, F.data.startswith("PA_RATING:"))
async def pa_rating_chosen(callback: CallbackQuery, state: FSMContext):
    val = callback.data.split("PA_RATING:", 1)[1]
    await state.update_data(rating=None if val == "skip" else int(val))
    await pa_show_address_step(callback, state)
    await callback.answer()


async def pa_show_address_step(event, state: FSMContext):
    await state.set_state(PlaceAdd.address)
    await reply(event, "📍 Manzilini yozing yoki o'tkazib yuboring:",
                kb.skip_kb("PA_ADDR_SKIP", back_cb="PA_BACKRATING"))


@router.callback_query(F.data == "PA_BACKADDR")
async def pa_back_addr(callback: CallbackQuery, state: FSMContext):
    await pa_show_address_step(callback, state)
    await callback.answer()


@router.callback_query(PlaceAdd.address, F.data == "PA_ADDR_SKIP")
async def pa_addr_skip(callback: CallbackQuery, state: FSMContext):
    await state.update_data(address=None)
    await pa_show_photos_step(callback, state)
    await callback.answer()


@router.message(PlaceAdd.address)
async def pa_addr_input(message: Message, state: FSMContext):
    await state.update_data(address=message.text.strip() if message.text else None)
    await pa_show_photos_step(message, state)


async def pa_show_photos_step(event, state: FSMContext):
    await state.set_state(PlaceAdd.photos)
    await state.update_data(photos=[])
    await reply(
        event,
        "📷 Rasm(lar) yuboring (bir nechtasi mumkin). Tugagach yoki umuman yubormasdan "
        "pastdagi tugmani bosing:",
        kb.done_kb("PA_PHOTOS_DONE", back=True, back_cb="PA_BACKADDR"),
    )


@router.callback_query(F.data == "PA_BACKPHOTOS")
async def pa_back_photos(callback: CallbackQuery, state: FSMContext):
    await pa_show_photos_step(callback, state)
    await callback.answer()


@router.message(PlaceAdd.photos, F.photo)
async def pa_photo_received(message: Message, state: FSMContext):
    data = await state.get_data()
    photos = data.get("photos", [])
    photos.append(message.photo[-1].file_id)
    await state.update_data(photos=photos)
    await message.answer(
        f"📷 Qabul qilindi ({len(photos)} ta). Yana yuborishingiz mumkin yoki tugmani bosing:",
        reply_markup=kb.done_kb("PA_PHOTOS_DONE", back=True, back_cb="PA_BACKADDR"),
    )


@router.callback_query(PlaceAdd.photos, F.data == "PA_PHOTOS_DONE")
async def pa_photos_done(callback: CallbackQuery, state: FSMContext):
    await pa_show_notes_step(callback, state)
    await callback.answer()


async def pa_show_notes_step(event, state: FSMContext):
    await state.set_state(PlaceAdd.notes)
    await reply(event, "📝 Izoh yozing yoki o'tkazib yuboring:",
                kb.skip_kb("PA_NOTES_SKIP", back_cb="PA_BACKPHOTOS"))


@router.callback_query(F.data == "PA_BACKNOTES")
async def pa_back_notes(callback: CallbackQuery, state: FSMContext):
    await pa_show_notes_step(callback, state)
    await callback.answer()


@router.callback_query(PlaceAdd.notes, F.data == "PA_NOTES_SKIP")
async def pa_notes_skip(callback: CallbackQuery, state: FSMContext):
    await pa_finish(callback, state, notes=None)
    await callback.answer()


@router.message(PlaceAdd.notes)
async def pa_notes_input(message: Message, state: FSMContext):
    await pa_finish(message, state, notes=message.text.strip() if message.text else None)


async def pa_finish(event, state: FSMContext, notes):
    data = await state.get_data()
    place = db.add_place(
        city_id=data["city_id"], name=data["name"], ptype=data["ptype"],
        is_halal=data.get("is_halal"), price=data.get("price"), rating=data.get("rating"),
        address=data.get("address"), latitude=None, longitude=None, notes=notes,
    )
    for file_id in data.get("photos", []):
        db.add_place_photo(place["id"], file_id)
    trip = db.get_trip(data["trip_id"])
    await state.clear()
    await send_new(event, f"✅ Joy saqlandi: {place['name']}")
    await show_trip_card(event, trip)


# ================= /places =================

@router.message(Command("places"))
async def cmd_places(message: Message, state: FSMContext):
    await state.clear()
    await send_country_list(message, "PL", message.from_user.id, "🌍 Davlatni tanlang:")


async def show_places_for_city(event, city):
    types = db.get_place_types(city["id"])
    if not types:
        b = kb.InlineKeyboardBuilder()
        b.button(text="⬅️ Orqaga", callback_data=f"PL_BACKCI:{city['country_id']}")
        b.adjust(1)
        await reply(event, f"🏙 {city['name']} da hali joy yo'q.", b.as_markup())
        return
    await reply(event, f"🏙 {city['name']}\n📍 Turini tanlang:",
                kb.type_filter_kb(city["id"], types, back_cb=f"PL_BACKCI:{city['country_id']}"))


ON_CITY_CHOSEN["PL"] = show_places_for_city


def format_place(p):
    labels = dict(kb.PLACE_TYPES)
    text = f"📍 <b>{p['name']}</b> — {labels.get(p['type'], '📌 ' + p['type'])}"
    if p.get("is_halal"):
        halal_map = {"yes": "✅ Halol", "no": "❌ Halol emas", "unknown": "🤷 Noma'lum"}
        text += f"\n🍽 Halollik: {halal_map.get(p['is_halal'], p['is_halal'])}"
    if p.get("price"):
        text += f"\n💵 Narx: {p['price']}"
    if p.get("rating"):
        text += f"\n⭐ Baho: {'⭐' * p['rating']}"
    if p.get("address"):
        text += f"\n📌 Manzil: {p['address']}"
    if p.get("notes"):
        text += f"\n📝 {p['notes']}"
    return text


@router.callback_query(F.data.regexp(r"^places_show:(\d+):(.+)$"))
async def places_show(callback: CallbackQuery, state: FSMContext):
    _, city_id, ptype = callback.data.split(":")
    city_id = int(city_id)
    city = db.get_city(city_id)
    places = db.get_places(city_id, ptype if ptype != "all" else None)
    if not places:
        await callback.answer("Bu turdagi joy topilmadi", show_alert=True)
        return
    b = kb.InlineKeyboardBuilder()
    b.button(text="⬅️ Orqaga", callback_data=f"PL_BACKTYPES:{city_id}")
    b.adjust(1)
    await reply(callback, f"🏙 {city['name']} — topilgan joylar: {len(places)}", b.as_markup())
    for p in places:
        photos = db.get_place_photos(p["id"])
        text = format_place(p)
        if photos:
            await callback.message.answer_photo(photos[0]["photo_file_id"], caption=text)
            for extra in photos[1:]:
                await callback.message.answer_photo(extra["photo_file_id"])
        else:
            await callback.message.answer(text)
    await callback.answer()


@router.callback_query(F.data.regexp(r"^PL_BACKTYPES:(\d+)$"))
async def pl_back_types(callback: CallbackQuery, state: FSMContext):
    city_id = int(callback.data.split(":")[1])
    city = db.get_city(city_id)
    await show_places_for_city(callback, city)
    await callback.answer()


# ================= /contact_add va /contacts =================

@router.message(Command("contact_add"))
async def cmd_contact_add(message: Message, state: FSMContext):
    await state.clear()
    await send_country_list(message, "CA", message.from_user.id, "🌍 Davlatni tanlang:")


async def ca_after_trip_selected(event, state: FSMContext, trip):
    await state.set_state(ContactAdd.name)
    await state.update_data(trip_id=trip["id"])
    await reply(event, "✏️ Kontakt ismini yozing:", CANCEL_ONLY)


ON_TRIP_CHOSEN["CA"] = ca_after_trip_selected


@router.message(ContactAdd.name)
async def ca_name_input(message: Message, state: FSMContext):
    name = message.text.strip() if message.text else ""
    if not name:
        await message.answer("Ism kiriting:", reply_markup=CANCEL_ONLY)
        return
    await state.update_data(name=name)
    await state.set_state(ContactAdd.contact_info)
    await message.answer("📞 Aloqa ma'lumotini yozing (telefon, username va h.k.):", reply_markup=CANCEL_ONLY)


@router.message(ContactAdd.contact_info)
async def ca_info_input(message: Message, state: FSMContext):
    info = message.text.strip() if message.text else ""
    await state.update_data(contact_info=info)
    data = await state.get_data()
    trip = db.get_trip(data["trip_id"])
    city = db.get_city(trip["city_id"])
    await state.set_state(ContactAdd.notes)
    await message.answer("📝 Izoh yozing yoki o'tkazib yuboring:",
                          reply_markup=kb.skip_kb("CA_NOTES_SKIP", back_cb=f"CA_BACKCI:{city['country_id']}"))


@router.callback_query(ContactAdd.notes, F.data == "CA_NOTES_SKIP")
async def ca_notes_skip(callback: CallbackQuery, state: FSMContext):
    await ca_finish(callback, state, notes=None)
    await callback.answer()


@router.message(ContactAdd.notes)
async def ca_notes_input(message: Message, state: FSMContext):
    await ca_finish(message, state, notes=message.text.strip() if message.text else None)


async def ca_finish(event, state: FSMContext, notes):
    data = await state.get_data()
    contact = db.add_contact(data["trip_id"], data["name"], data.get("contact_info"), notes)
    trip = db.get_trip(data["trip_id"])
    await state.clear()
    await send_new(event, f"✅ Kontakt saqlandi: {contact['name']}")
    await show_trip_card(event, trip)


@router.message(Command("contacts"))
async def cmd_contacts(message: Message, state: FSMContext):
    await state.clear()
    await send_country_list(message, "CV", message.from_user.id, "🌍 Davlatni tanlang:")


async def cv_after_trip_selected(event, state: FSMContext, trip):
    contacts = db.get_contacts(trip["id"])
    city = db.get_city(trip["city_id"])
    if not contacts:
        await reply(event, f"🏙 {city['name']} — bu safarga hali kontakt qo'shilmagan.")
        return
    lines = [f"👤 Kontaktlar — {city['name']}:\n"]
    for c in contacts:
        lines.append(f"• <b>{c['name']}</b>" + (f" — {c['contact_info']}" if c["contact_info"] else ""))
        if c.get("notes"):
            lines.append(f"  📝 {c['notes']}")
    await reply(event, "\n".join(lines))


ON_TRIP_CHOSEN["CV"] = cv_after_trip_selected


# ================= /expense_add =================

@router.message(Command("expense_add"))
async def cmd_expense_add(message: Message, state: FSMContext):
    await state.clear()
    await send_country_list(message, "EA", message.from_user.id, "🌍 Davlatni tanlang:")


async def ea_after_trip_selected(event, state: FSMContext, trip):
    await state.update_data(trip_id=trip["id"])
    if not trip["budget_currency"] or not trip["city_currency"]:
        await state.set_state(ExpenseAdd.setup_budget_currency)
        await reply(
            event,
            "⚠️ Bu safar uchun byudjet valyutasi hali kiritilmagan.\n💰 Byudjet valyutasini tanlang:",
            kb.currency_kb("EASETBUDCUR", back=False),
        )
        return
    if trip["budget_currency"] != trip["city_currency"] and not trip["exchange_rate"]:
        await state.set_state(ExpenseAdd.setup_exchange_rate)
        await reply(
            event,
            f"⚠️ Bu safar uchun kurs hali kiritilmagan.\n"
            f"Hozirgi kunda 1 {trip['budget_currency']} necha {trip['city_currency']}? "
            f"(masalan: 1 {trip['budget_currency']} = 7 {trip['city_currency']})",
            CANCEL_ONLY,
        )
        return
    await ea_show_category_step(event, state)


ON_TRIP_CHOSEN["EA"] = ea_after_trip_selected


@router.callback_query(ExpenseAdd.setup_budget_currency, F.data.startswith("EASETBUDCUR:"))
async def ea_setup_budcur(callback: CallbackQuery, state: FSMContext):
    val = callback.data.split("EASETBUDCUR:", 1)[1]
    if val == "custom":
        await state.set_state(ExpenseAdd.setup_budget_currency)
        await state.update_data(_awaiting_budcur_custom=True)
        await reply(callback, "✏️ Valyuta nomini yozing:", CANCEL_ONLY)
        await callback.answer()
        return
    await state.update_data(setup_budget_currency=val)
    await state.set_state(ExpenseAdd.setup_budget_amount)
    await reply(callback, f"💰 Necha {val} byudjet ajratmoqchisiz? (faqat son kiriting)", CANCEL_ONLY)
    await callback.answer()


@router.message(ExpenseAdd.setup_budget_currency)
async def ea_setup_budcur_custom(message: Message, state: FSMContext):
    val = message.text.strip() if message.text else ""
    if not val:
        await message.answer("Valyuta nomini matn ko'rinishida yozing:", reply_markup=CANCEL_ONLY)
        return
    await state.update_data(setup_budget_currency=val)
    await state.set_state(ExpenseAdd.setup_budget_amount)
    await message.answer(f"💰 Necha {val} byudjet ajratmoqchisiz? (faqat son kiriting)", reply_markup=CANCEL_ONLY)


@router.message(ExpenseAdd.setup_budget_amount)
async def ea_setup_budamt(message: Message, state: FSMContext):
    val = parse_number(message.text)
    if val is None:
        await message.answer("Faqat son kiriting:", reply_markup=CANCEL_ONLY)
        return
    await state.update_data(setup_budget_amount=val)
    await state.set_state(ExpenseAdd.setup_city_currency)
    data = await state.get_data()
    trip = db.get_trip(data["trip_id"])
    city = db.get_city(trip["city_id"])
    await message.answer(f"💱 {city['name']} da asosan qaysi valyuta ishlatiladi?",
                          reply_markup=kb.currency_kb("EASETCITYCUR", back=False))


@router.callback_query(ExpenseAdd.setup_city_currency, F.data.startswith("EASETCITYCUR:"))
async def ea_setup_citycur(callback: CallbackQuery, state: FSMContext):
    val = callback.data.split("EASETCITYCUR:", 1)[1]
    if val == "custom":
        await state.update_data(_awaiting_citycur_custom=True)
        await reply(callback, "✏️ Valyuta nomini yozing:", CANCEL_ONLY)
        await callback.answer()
        return
    await ea_setup_after_citycur(callback, state, val)
    await callback.answer()


@router.message(ExpenseAdd.setup_city_currency)
async def ea_setup_citycur_custom(message: Message, state: FSMContext):
    val = message.text.strip() if message.text else ""
    if not val:
        await message.answer("Valyuta nomini matn ko'rinishida yozing:", reply_markup=CANCEL_ONLY)
        return
    await ea_setup_after_citycur(message, state, val)


async def ea_setup_after_citycur(event, state: FSMContext, city_currency):
    data = await state.get_data()
    db.update_trip_budget(data["trip_id"], data["setup_budget_amount"], data["setup_budget_currency"])
    db.update_trip_city_currency(data["trip_id"], city_currency)
    if city_currency == data["setup_budget_currency"]:
        trip = db.get_trip(data["trip_id"])
        await ea_show_category_step(event, state)
    else:
        await state.set_state(ExpenseAdd.setup_exchange_rate)
        await reply(
            event,
            f"💱 Hozirgi kunda 1 {data['setup_budget_currency']} necha {city_currency}? "
            f"(masalan: 1 {data['setup_budget_currency']} = 7 {city_currency})",
            CANCEL_ONLY,
        )


@router.message(ExpenseAdd.setup_exchange_rate)
async def ea_setup_rate(message: Message, state: FSMContext):
    val = parse_number(message.text)
    if val is None or val <= 0:
        await message.answer("Faqat musbat son kiriting (masalan: 7):", reply_markup=CANCEL_ONLY)
        return
    data = await state.get_data()
    db.update_trip_exchange_rate(data["trip_id"], val)
    await ea_show_category_step(message, state)


async def ea_show_category_step(event, state: FSMContext):
    await state.set_state(ExpenseAdd.category)
    data = await state.get_data()
    trip = db.get_trip(data["trip_id"])
    city = db.get_city(trip["city_id"])
    await reply(event, "🧾 Kategoriyani tanlang:",
                kb.category_kb("EA_CAT", back_cb=f"EA_BACKCI:{city['country_id']}"))


@router.callback_query(ExpenseAdd.category, F.data.startswith("EA_CAT:"))
async def ea_category_chosen(callback: CallbackQuery, state: FSMContext):
    val = callback.data.split("EA_CAT:", 1)[1]
    await state.update_data(category=val)
    await ea_show_currency_step(callback, state)
    await callback.answer()


async def ea_show_currency_step(event, state: FSMContext):
    await state.set_state(ExpenseAdd.currency)
    data = await state.get_data()
    trip = db.get_trip(data["trip_id"])
    await reply(event, "💱 Qaysi valyutada kiritasiz?",
                kb.expense_currency_kb(trip["budget_currency"], trip["city_currency"], "EA_CUR",
                                        back_cb="EA_BACKCAT"))


@router.callback_query(F.data == "EA_BACKCAT")
async def ea_back_cat(callback: CallbackQuery, state: FSMContext):
    await ea_show_category_step(callback, state)
    await callback.answer()


@router.callback_query(ExpenseAdd.currency, F.data.startswith("EA_CUR:"))
async def ea_currency_chosen(callback: CallbackQuery, state: FSMContext):
    currency = callback.data.split("EA_CUR:", 1)[1]
    await state.update_data(currency=currency)
    await state.set_state(ExpenseAdd.amount)
    await reply(callback, f"💵 Faqat {currency} valyutasida summani kiriting (faqat son):", CANCEL_ONLY)
    await callback.answer()


@router.message(ExpenseAdd.amount)
async def ea_amount_input(message: Message, state: FSMContext):
    val = parse_number(message.text)
    if val is None:
        await message.answer("Iltimos, faqat son kiriting:", reply_markup=CANCEL_ONLY)
        return
    await state.update_data(amount=val)
    data = await state.get_data()
    await state.set_state(ExpenseAdd.note)
    await message.answer("📝 Izoh yozing yoki o'tkazib yuboring:",
                          reply_markup=kb.skip_kb("EA_NOTE_SKIP", back_cb="EA_BACKCUR"))


@router.callback_query(F.data == "EA_BACKCUR")
async def ea_back_cur(callback: CallbackQuery, state: FSMContext):
    await ea_show_currency_step(callback, state)
    await callback.answer()


@router.callback_query(ExpenseAdd.note, F.data == "EA_NOTE_SKIP")
async def ea_note_skip(callback: CallbackQuery, state: FSMContext):
    await ea_finish(callback, state, note=None)
    await callback.answer()


@router.message(ExpenseAdd.note)
async def ea_note_input(message: Message, state: FSMContext):
    await ea_finish(message, state, note=message.text.strip() if message.text else None)


async def ea_finish(event, state: FSMContext, note):
    data = await state.get_data()
    db.add_expense(data["trip_id"], data["category"], data["amount"], data["currency"],
                    date.today().isoformat(), note)
    trip = db.get_trip(data["trip_id"])
    await state.clear()
    await send_new(event, "✅ Xarajat saqlandi!")
    await show_trip_card(event, trip)


# ================= /expenses =================

@router.message(Command("expenses"))
async def cmd_expenses(message: Message, state: FSMContext):
    await state.clear()
    await send_country_list(message, "EV", message.from_user.id, "🌍 Davlatni tanlang:")


async def ev_after_trip_selected(event, state: FSMContext, trip):
    city = db.get_city(trip["city_id"])
    summary = db.get_expense_summary(trip["id"])
    lines = [f"💰 Xarajatlar — {city['name']}:\n"]
    if not summary:
        lines.append("Hali xarajat kiritilmagan.")
    else:
        by_cat = {}
        for r in summary:
            by_cat.setdefault(r["category"], []).append((r["currency"], float(r["total"])))
        for cat, entries in by_cat.items():
            label = CATEGORY_LABELS.get(cat, cat)
            parts = [f"{fmt_money(v)} {c}" for c, v in entries]
            lines.append(f"{label}: " + " + ".join(parts))
    lines.append("")
    lines.append(fmt_finance_block(trip))
    await reply(event, "\n".join(lines))


ON_TRIP_CHOSEN["EV"] = ev_after_trip_selected


# ================= /file_add va /files =================

@router.message(Command("file_add"))
async def cmd_file_add(message: Message, state: FSMContext):
    await state.clear()
    await send_country_list(message, "FA", message.from_user.id, "🌍 Davlatni tanlang:")


async def fa_after_trip_selected(event, state: FSMContext, trip):
    await state.set_state(FileAdd.file)
    await state.update_data(trip_id=trip["id"])
    await reply(event, "📎 Faylni (hujjat yoki rasm) yuboring:", CANCEL_ONLY)


ON_TRIP_CHOSEN["FA"] = fa_after_trip_selected


@router.message(FileAdd.file, F.document | F.photo)
async def fa_file_received(message: Message, state: FSMContext):
    if message.document:
        file_id = message.document.file_id
        file_type = "document"
        file_name = message.document.file_name
    else:
        file_id = message.photo[-1].file_id
        file_type = "photo"
        file_name = None
    await state.update_data(file_id=file_id, file_type=file_type, file_name=file_name)
    data = await state.get_data()
    trip = db.get_trip(data["trip_id"])
    city = db.get_city(trip["city_id"])
    await state.set_state(FileAdd.notes)
    await message.answer("📝 Izoh yozing yoki o'tkazib yuboring:",
                          reply_markup=kb.skip_kb("FA_NOTES_SKIP", back_cb=f"FA_BACKCI:{city['country_id']}"))


@router.message(FileAdd.file)
async def fa_file_wrong(message: Message, state: FSMContext):
    await message.answer("Iltimos, fayl yoki rasm yuboring:", reply_markup=CANCEL_ONLY)


@router.callback_query(FileAdd.notes, F.data == "FA_NOTES_SKIP")
async def fa_notes_skip(callback: CallbackQuery, state: FSMContext):
    await fa_finish(callback, state, notes=None)
    await callback.answer()


@router.message(FileAdd.notes)
async def fa_notes_input(message: Message, state: FSMContext):
    await fa_finish(message, state, notes=message.text.strip() if message.text else None)


async def fa_finish(event, state: FSMContext, notes):
    data = await state.get_data()
    db.add_file(data["trip_id"], data["file_id"], data["file_type"], data.get("file_name"), notes)
    trip = db.get_trip(data["trip_id"])
    await state.clear()
    await send_new(event, "✅ Fayl saqlandi!")
    await show_trip_card(event, trip)


@router.message(Command("files"))
async def cmd_files(message: Message, state: FSMContext):
    await state.clear()
    await send_country_list(message, "FV", message.from_user.id, "🌍 Davlatni tanlang:")


async def fv_after_trip_selected(event, state: FSMContext, trip):
    files = db.get_files(trip["id"])
    city = db.get_city(trip["city_id"])
    if not files:
        await reply(event, f"🏙 {city['name']} — bu safarga hali fayl qo'shilmagan.")
        return
    await reply(event, f"📎 Fayllar — {city['name']} ({len(files)} ta):")
    for f in files:
        caption = f.get("notes") or f.get("file_name") or "Fayl"
        if f["file_type"] == "photo":
            await event.message.answer_photo(f["file_id"], caption=caption) if isinstance(event, CallbackQuery) else await event.answer_photo(f["file_id"], caption=caption)
        else:
            if isinstance(event, CallbackQuery):
                await event.message.answer_document(f["file_id"], caption=caption)
            else:
                await event.answer_document(f["file_id"], caption=caption)


ON_TRIP_CHOSEN["FV"] = fv_after_trip_selected


# ================= /weather_add va /weather =================

@router.message(Command("weather_add"))
async def cmd_weather_add(message: Message, state: FSMContext):
    await state.clear()
    await send_country_list(message, "WA", message.from_user.id, "🌍 Davlatni tanlang:")


async def wa_after_trip_selected(event, state: FSMContext, trip):
    await state.set_state(WeatherAdd.conditions)
    city = db.get_city(trip["city_id"])
    await state.update_data(trip_id=trip["id"], selected=[], _wa_country_id=city["country_id"])
    await reply(event, "🌤 Ob-havo holatini tanlang (bir nechtasi mumkin):",
                kb.weather_kb([], back_cb=f"WA_BACKCI:{city['country_id']}"))


ON_TRIP_CHOSEN["WA"] = wa_after_trip_selected


@router.callback_query(WeatherAdd.conditions, F.data.startswith("wopt:"))
async def wa_option(callback: CallbackQuery, state: FSMContext):
    val = callback.data.split("wopt:", 1)[1]
    data = await state.get_data()
    selected = data.get("selected", [])
    if val == "custom":
        await state.set_state(WeatherAdd.custom_text)
        await reply(callback, "✏️ O'zingiz yozing:", CANCEL_ONLY)
        await callback.answer()
        return
    if val == "done":
        await wa_finish(callback, state)
        await callback.answer()
        return
    if val in selected:
        selected.remove(val)
    else:
        selected.append(val)
    await state.update_data(selected=selected)
    await reply(callback, "🌤 Ob-havo holatini tanlang (bir nechtasi mumkin):",
                kb.weather_kb(selected, back_cb=f"WA_BACKCI:{data.get('_wa_country_id')}"))
    await callback.answer()


@router.message(WeatherAdd.custom_text)
async def wa_custom_text(message: Message, state: FSMContext):
    text = message.text.strip() if message.text else ""
    if not text:
        await message.answer("Matn kiriting:", reply_markup=CANCEL_ONLY)
        return
    data = await state.get_data()
    custom = data.get("custom_texts", [])
    custom.append(text)
    await state.update_data(custom_texts=custom)
    await state.set_state(WeatherAdd.conditions)
    await message.answer("🌤 Ob-havo holatini tanlang (bir nechtasi mumkin):",
                          reply_markup=kb.weather_kb(data.get("selected", []),
                                                      back_cb=f"WA_BACKCI:{data.get('_wa_country_id')}"))


async def wa_finish(event, state: FSMContext):
    data = await state.get_data()
    selected = data.get("selected", [])
    custom_texts = data.get("custom_texts", [])
    if not selected and not custom_texts:
        await callback_answer_alert(event, "Kamida bitta variant tanlang yoki matn yozing.")
        return
    labels = [WEATHER_LABELS.get(s, s) for s in selected]
    conditions = ", ".join(labels)
    custom_text = ", ".join(custom_texts) if custom_texts else None
    db.add_weather_note(data["trip_id"], date.today().isoformat(), conditions, custom_text)
    trip = db.get_trip(data["trip_id"])
    await state.clear()
    await send_new(event, "✅ Ob-havo saqlandi!")
    await show_trip_card(event, trip)


async def callback_answer_alert(event, text):
    if isinstance(event, CallbackQuery):
        await event.answer(text, show_alert=True)
    else:
        await event.answer(text)


@router.message(Command("weather"))
async def cmd_weather(message: Message, state: FSMContext):
    await state.clear()
    await send_country_list(message, "WV", message.from_user.id, "🌍 Davlatni tanlang:")


async def wv_after_trip_selected(event, state: FSMContext, trip):
    notes = db.get_weather_notes(trip["id"])
    city = db.get_city(trip["city_id"])
    if not notes:
        await reply(event, f"🏙 {city['name']} — bu safarga hali ob-havo yozuvi yo'q.")
        return
    lines = [f"🌤 Ob-havo — {city['name']}:\n"]
    for n in notes:
        parts = []
        if n.get("conditions"):
            parts.append(n["conditions"])
        if n.get("custom_text"):
            parts.append(n["custom_text"])
        lines.append(f"• {n['entry_date']}: " + (", ".join(parts) if parts else "—"))
    await reply(event, "\n".join(lines))


ON_TRIP_CHOSEN["WV"] = wv_after_trip_selected


# ================= /diary_add va /diary =================

@router.message(Command("diary_add"))
async def cmd_diary_add(message: Message, state: FSMContext):
    await state.clear()
    await send_country_list(message, "DA", message.from_user.id, "🌍 Davlatni tanlang:")


async def da_after_trip_selected(event, state: FSMContext, trip):
    await state.set_state(DiaryAdd.text)
    await state.update_data(trip_id=trip["id"])
    await reply(event, "📔 Kundalik matnini yozing:", CANCEL_ONLY)


ON_TRIP_CHOSEN["DA"] = da_after_trip_selected


@router.message(DiaryAdd.text)
async def da_text_input(message: Message, state: FSMContext):
    text = message.text.strip() if message.text else ""
    if not text:
        await message.answer("Matn kiriting:", reply_markup=CANCEL_ONLY)
        return
    data = await state.get_data()
    db.add_diary(data["trip_id"], date.today().isoformat(), text)
    trip = db.get_trip(data["trip_id"])
    await state.clear()
    await message.answer("✅ Kundalik yozuvi saqlandi!")
    await show_trip_card(message, trip)


@router.message(Command("diary"))
async def cmd_diary(message: Message, state: FSMContext):
    await state.clear()
    await send_country_list(message, "DV", message.from_user.id, "🌍 Davlatni tanlang:")


async def dv_after_trip_selected(event, state: FSMContext, trip):
    entries = db.get_diary(trip["id"])
    city = db.get_city(trip["city_id"])
    if not entries:
        await reply(event, f"🏙 {city['name']} — bu safarga hali kundalik yozuvi yo'q.")
        return
    lines = [f"📔 Kundalik — {city['name']}:\n"]
    for e in entries:
        lines.append(f"• {e['entry_date']}: {e['text']}")
    await reply(event, "\n".join(lines))


ON_TRIP_CHOSEN["DV"] = dv_after_trip_selected


# ================= /stats =================

@router.message(Command("stats"))
async def cmd_stats(message: Message):
    user_id = message.from_user.id
    base = db.get_stats(user_id)
    trips = db.get_all_trips_for_user(user_id)

    lines = ["📈 <b>Statistika</b>\n"]
    lines.append(f"🌍 Davlatlar: {base['countries']}")
    lines.append(f"🏙 Shaharlar: {base['cities']}")
    lines.append(f"🧳 Safarlar: {base['trips']} (✅ {base['visited_trips']} borgan, 🎯 {base['wishlist_trips']} bormoqchi)")

    # Valyuta bo'yicha jami xarajat
    currency_totals = {}
    place_counts = {}
    activity_counts = {}
    category_totals = {}
    best_trip, best_pct = None, None
    worst_trip, worst_pct = None, None

    for t in trips:
        expenses = db.get_expenses(t["id"])
        for e in expenses:
            currency_totals[e["currency"]] = currency_totals.get(e["currency"], 0) + float(e["amount"])
            key = (e["category"], e["currency"])
            category_totals[key] = category_totals.get(key, 0) + float(e["amount"])

        city_key = f"{t['country_name']} — {t['city_name']}"
        n_contacts = len(db.get_contacts(t["id"]))
        n_diary = len(db.get_diary(t["id"]))
        n_files = len(db.get_files(t["id"]))
        activity_counts[city_key] = activity_counts.get(city_key, 0) + n_contacts + n_diary + n_files

        f = get_trip_finance(t)
        if f["budget_amt"] and f["rate_known"] and f["remaining_budget_cur"] is not None:
            pct = f["remaining_budget_cur"] / f["budget_amt"] * 100
            if best_pct is None or pct > best_pct:
                best_pct, best_trip = pct, (t, f)
            if worst_pct is None or pct < worst_pct:
                worst_pct, worst_trip = pct, (t, f)

    for city in db.export_cities(user_id):
        places = db.get_places(city["id"])
        key = f"{city['country_name']} — {city['name']}"
        place_counts[key] = place_counts.get(key, 0) + len(places)
        activity_counts[key] = activity_counts.get(key, 0) + len(places)

    if currency_totals:
        parts = [f"{fmt_money(v)} {c}" for c, v in currency_totals.items()]
        lines.append("\n💰 Jami xarajat: " + " + ".join(parts))
    else:
        lines.append("\n💰 Jami xarajat: 0")

    if best_trip:
        t, f = best_trip
        lines.append(f"\n🏆 Eng tejamli safar: {t['country_name']} — {t['city_name']} "
                      f"(qoldiq {best_pct:.0f}% byudjetdan)")
    if worst_trip and worst_trip != best_trip:
        t, f = worst_trip
        status_word = "oshgan" if worst_pct < 0 else "qoldiq"
        lines.append(f"⚠️ Eng ko'p sarflangan safar: {t['country_name']} — {t['city_name']} "
                      f"({status_word} {abs(worst_pct):.0f}% byudjetdan)")

    if activity_counts:
        top_city = max(activity_counts, key=activity_counts.get)
        if activity_counts[top_city] > 0:
            lines.append(f"\n🏙 Eng faol shahar: {top_city} ({activity_counts[top_city]} ta yozuv)")

    if category_totals:
        lines.append("\n🧾 Kategoriya bo'yicha xarajat:")
        by_cat = {}
        for (cat, cur), total in category_totals.items():
            by_cat.setdefault(cat, []).append((cur, total))
        for cat, entries in by_cat.items():
            label = CATEGORY_LABELS.get(cat, cat)
            parts = [f"{fmt_money(v)} {c}" for c, v in entries]
            lines.append(f"• {label}: " + " + ".join(parts))

    await message.answer("\n".join(lines))


# ================= /export =================

@router.message(Command("export"))
async def cmd_export(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("📦 Qanday eksport qilamiz?", reply_markup=kb.export_scope_kb())


@router.callback_query(F.data == "EX_BACKSCOPE")
async def export_back_scope(callback: CallbackQuery, state: FSMContext):
    await reply(callback, "📦 Qanday eksport qilamiz?", kb.export_scope_kb())
    await callback.answer()


@router.callback_query(F.data.startswith("exp_scope:"))
async def export_scope_chosen(callback: CallbackQuery, state: FSMContext):
    scope = callback.data.split(":", 1)[1]
    if scope == "all":
        await generate_and_send_export(callback, get_uid(callback))
        await callback.answer()
        return
    countries = db.get_countries(get_uid(callback))
    if not countries:
        await callback.answer("Hali davlat yo'q", show_alert=True)
        return
    b = kb.InlineKeyboardBuilder()
    for c in countries:
        b.button(text=f"🌍 {c['name']}", callback_data=f"EXCO:{scope}:{c['id']}")
    b.button(text="⬅️ Orqaga", callback_data="EX_BACKSCOPE")
    b.adjust(1)
    await reply(callback, "🌍 Davlatni tanlang:", b.as_markup())
    await callback.answer()


@router.callback_query(F.data.startswith("EX_BACKCO:"))
async def export_back_co(callback: CallbackQuery, state: FSMContext):
    scope = callback.data.split(":", 1)[1]
    countries = db.get_countries(get_uid(callback))
    b = kb.InlineKeyboardBuilder()
    for c in countries:
        b.button(text=f"🌍 {c['name']}", callback_data=f"EXCO:{scope}:{c['id']}")
    b.button(text="⬅️ Orqaga", callback_data="EX_BACKSCOPE")
    b.adjust(1)
    await reply(callback, "🌍 Davlatni tanlang:", b.as_markup())
    await callback.answer()


@router.callback_query(F.data.regexp(r"^EXCO:(country|city|trip):(\d+)$"))
async def export_country_chosen(callback: CallbackQuery, state: FSMContext):
    _, scope, country_id = callback.data.split(":")
    country_id = int(country_id)
    if scope == "country":
        await generate_and_send_export(callback, get_uid(callback), country_id=country_id)
        await callback.answer()
        return
    cities = db.get_cities(country_id)
    if not cities:
        await callback.answer("Bu davlatda shahar yo'q", show_alert=True)
        return
    b = kb.InlineKeyboardBuilder()
    for c in cities:
        b.button(text=f"🏙 {c['name']}", callback_data=f"EXCI:{scope}:{c['id']}")
    b.button(text="⬅️ Orqaga", callback_data=f"EX_BACKCO:{scope}")
    b.adjust(1)
    await reply(callback, "🏙 Shaharni tanlang:", b.as_markup())
    await callback.answer()


@router.callback_query(F.data.startswith("EX_BACKCI:"))
async def export_back_ci(callback: CallbackQuery, state: FSMContext):
    country_id = int(callback.data.split(":", 1)[1])
    cities = db.get_cities(country_id)
    b = kb.InlineKeyboardBuilder()
    for c in cities:
        b.button(text=f"🏙 {c['name']}", callback_data=f"EXCI:trip:{c['id']}")
    b.button(text="⬅️ Orqaga", callback_data="EX_BACKCO:trip")
    b.adjust(1)
    await reply(callback, "🏙 Shaharni tanlang:", b.as_markup())
    await callback.answer()


@router.callback_query(F.data.regexp(r"^EXCI:(city|trip):(\d+)$"))
async def export_city_chosen(callback: CallbackQuery, state: FSMContext):
    _, scope, city_id = callback.data.split(":")
    city_id = int(city_id)
    if scope == "city":
        await generate_and_send_export(callback, get_uid(callback), city_id=city_id)
        await callback.answer()
        return
    trips = db.get_trips(city_id)
    if not trips:
        await callback.answer("Bu shaharda safar yo'q", show_alert=True)
        return
    city = db.get_city(city_id)
    b = kb.InlineKeyboardBuilder()
    for i, t in enumerate(trips, 1):
        emoji = "✅" if t["status"] == "visited" else "🎯"
        b.button(text=f"{emoji} {i}-safar", callback_data=f"EXTR:{t['id']}")
    b.button(text="⬅️ Orqaga", callback_data=f"EX_BACKCI:{city['country_id']}")
    b.adjust(1)
    await reply(callback, "🧳 Safarni tanlang:", b.as_markup())
    await callback.answer()


@router.callback_query(F.data.regexp(r"^EXTR:(\d+)$"))
async def export_trip_chosen(callback: CallbackQuery, state: FSMContext):
    trip_id = int(callback.data.split(":")[1])
    await generate_and_send_export(callback, get_uid(callback), trip_id=trip_id)
    await callback.answer()


def write_sheet(wb, title, headers, rows):
    ws = wb.create_sheet(title)
    for j, h in enumerate(headers):
        cell = ws.cell(row=2, column=2 + j, value=h)
        cell.font = Font(bold=True)
    for i, row in enumerate(rows):
        for j, val in enumerate(row):
            ws.cell(row=3 + i, column=2 + j, value=val)
    return ws


async def generate_and_send_export(event, user_id, country_id=None, city_id=None, trip_id=None):
    wb = openpyxl.Workbook()
    wb.remove(wb.active)

    if country_id is None and city_id is None and trip_id is None:
        countries = db.export_countries(user_id)
        if countries:
            write_sheet(wb, "Davlatlar", ["Nomi"], [[c["name"]] for c in countries])
        cities = db.export_cities(user_id)
        if cities:
            write_sheet(wb, "Shaharlar", ["Davlat", "Shahar"],
                        [[c["country_name"], c["name"]] for c in cities])

    trips = db.export_trips(user_id, country_id, city_id, trip_id)
    if trips:
        rows = []
        for t in trips:
            f = get_trip_finance(t)
            rows.append([
                t["country_name"], t["city_name"],
                "Borgan" if t["status"] == "visited" else "Bormoqchi",
                t.get("note") or "",
                fmt_money(t["budget_amount"]) if t["budget_amount"] is not None else "",
                t.get("budget_currency") or "", t.get("city_currency") or "",
                fmt_money(t["exchange_rate"]) if t["exchange_rate"] else "",
                fmt_money(f["total_budget_cur"]) if f["total_budget_cur"] is not None else "",
                fmt_money(f["remaining_budget_cur"]) if f["remaining_budget_cur"] is not None else "",
            ])
        write_sheet(wb, "Safarlar",
                    ["Davlat", "Shahar", "Holat", "Izoh", "Byudjet", "Byudjet valyutasi",
                     "Shahar valyutasi", "Kurs", "Jami xarajat", "Qoldiq"], rows)

    place_city_id = city_id
    if trip_id and not place_city_id:
        place_city_id = db.get_trip(trip_id)["city_id"]
    places = db.export_places(user_id, country_id, place_city_id)
    if places:
        rows = [[p["country_name"], p["city_name"], TYPE_LABELS.get(p["type"], p["type"]), p["name"],
                  p.get("price") or "", p.get("rating") or "", p.get("address") or "", p.get("notes") or ""]
                 for p in places]
        write_sheet(wb, "Joylar", ["Davlat", "Shahar", "Turi", "Nomi", "Narx", "Baho", "Manzil", "Izoh"], rows)

    contacts = db.export_contacts(user_id, country_id, city_id, trip_id)
    if contacts:
        rows = [[c["country_name"], c["city_name"], c["name"], c.get("contact_info") or "", c.get("notes") or ""]
                 for c in contacts]
        write_sheet(wb, "Kontaktlar", ["Davlat", "Shahar", "Ism", "Aloqa", "Izoh"], rows)

    expenses = db.export_expenses(user_id, country_id, city_id, trip_id)
    if expenses:
        rows = [[e["country_name"], e["city_name"], CATEGORY_LABELS.get(e["category"], e["category"]),
                  fmt_money(e["amount"]), e["currency"], e.get("expense_date") or "", e.get("note") or ""]
                 for e in expenses]
        write_sheet(wb, "Xarajatlar", ["Davlat", "Shahar", "Kategoriya", "Summa", "Valyuta", "Sana", "Izoh"], rows)

    diary = db.export_diary(user_id, country_id, city_id, trip_id)
    if diary:
        rows = [[d["country_name"], d["city_name"], d.get("entry_date") or "", d.get("text") or ""] for d in diary]
        write_sheet(wb, "Kundalik", ["Davlat", "Shahar", "Sana", "Matn"], rows)

    weather = db.export_weather(user_id, country_id, city_id, trip_id)
    if weather:
        rows = [[w["country_name"], w["city_name"], w.get("entry_date") or "", w.get("conditions") or "",
                  w.get("custom_text") or ""] for w in weather]
        write_sheet(wb, "Ob-havo", ["Davlat", "Shahar", "Sana", "Holat", "Qo'shimcha"], rows)

    files = db.export_files(user_id, country_id, city_id, trip_id)
    if files:
        rows = [[f["country_name"], f["city_name"], f.get("file_name") or "", f.get("file_type") or "",
                  f.get("notes") or ""] for f in files]
        write_sheet(wb, "Fayllar", ["Davlat", "Shahar", "Fayl nomi", "Turi", "Izoh"], rows)

    if not wb.sheetnames:
        await reply(event, "Eksport qilish uchun ma'lumot topilmadi.")
        return

    path = f"/tmp/export_{user_id}_{date.today().isoformat()}.xlsx"
    wb.save(path)
    doc = FSInputFile(path)
    if isinstance(event, CallbackQuery):
        await event.message.answer_document(doc, caption="📦 Eksport tayyor!")
    else:
        await event.answer_document(doc, caption="📦 Eksport tayyor!")


# ================= /manage =================

MANAGE_RENDERERS = {}


async def push_m(state: FSMContext, kind, **kwargs):
    data = await state.get_data()
    stack = data.get("_mstack", [])
    stack.append({"kind": kind, **kwargs})
    await state.update_data(_mstack=stack)


async def goto_m(event, state: FSMContext, kind, **kwargs):
    await push_m(state, kind, **kwargs)
    await MANAGE_RENDERERS[kind](event, **kwargs)


@router.callback_query(F.data == "nav:back")
async def manage_nav_back(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    stack = data.get("_mstack", [])
    if not stack:
        await callback.answer()
        return
    stack.pop()
    await state.update_data(_mstack=stack)
    if not stack:
        await state.clear()
        await reply(callback, "🔧 Boshqarish tugatildi.")
        await callback.answer()
        return
    prev = stack[-1]
    kind = prev["kind"]
    kwargs = {k: v for k, v in prev.items() if k != "kind"}
    await MANAGE_RENDERERS[kind](callback, **kwargs)
    await callback.answer()


async def mg_after_delete(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    stack = data.get("_mstack", [])
    if stack:
        stack.pop()
    await state.update_data(_mstack=stack)
    await callback.answer("✅ O'chirildi")
    if not stack:
        await state.clear()
        await reply(callback, "✅ O'chirildi.")
        return
    prev = stack[-1]
    kind = prev["kind"]
    kwargs = {k: v for k, v in prev.items() if k != "kind"}
    await MANAGE_RENDERERS[kind](callback, **kwargs)


@router.message(Command("manage"))
async def cmd_manage(message: Message, state: FSMContext):
    await state.clear()
    await state.update_data(_mstack=[{"kind": "mg_countries"}])
    await MANAGE_RENDERERS["mg_countries"](message)


# ---- Render funksiyalari ----

async def mg_render_countries(event, **kw):
    countries = db.get_countries(get_uid(event))
    if not countries:
        await reply(event, "Hali davlat qo'shilmagan.")
        return
    await reply(event, "🌍 Davlatni tanlang:", kb.manage_list_kb(countries, "MGCOUNTRY", lambda c: f"🌍 {c['name']}"))


MANAGE_RENDERERS["mg_countries"] = mg_render_countries


async def mg_render_country_action(event, country_id, **kw):
    country = db.get_country(country_id)
    if not country:
        await reply(event, "Bu davlat topilmadi.")
        return
    await reply(event, f"🌍 <b>{country['name']}</b>", kb.manage_country_action_kb(country_id))


MANAGE_RENDERERS["mg_country_action"] = mg_render_country_action


async def mg_render_country_cities(event, country_id, **kw):
    country = db.get_country(country_id)
    cities = db.get_cities(country_id)
    if not cities:
        await reply(event, f"🌍 {country['name']} da hali shahar yo'q.")
        return
    await reply(event, f"🌍 {country['name']}\n🏙 Shaharni tanlang:",
                kb.manage_list_kb(cities, "MGCITY", lambda c: f"🏙 {c['name']}"))


MANAGE_RENDERERS["mg_country_cities"] = mg_render_country_cities


async def mg_render_city_action(event, city_id, **kw):
    city = db.get_city(city_id)
    if not city:
        await reply(event, "Bu shahar topilmadi.")
        return
    await reply(event, f"🏙 <b>{city['name']}</b>", kb.manage_city_action_kb(city_id))


MANAGE_RENDERERS["mg_city_action"] = mg_render_city_action


async def mg_render_city_trips(event, city_id, **kw):
    city = db.get_city(city_id)
    trips = db.get_trips(city_id)
    if not trips:
        await reply(event, f"🏙 {city['name']} da hali safar yo'q.")
        return
    labels = {}
    for i, t in enumerate(trips, 1):
        emoji = "✅" if t["status"] == "visited" else "🎯"
        labels[t["id"]] = f"{emoji} {i}-safar"
    await reply(event, f"🏙 {city['name']}\n🧳 Safarni tanlang:",
                kb.manage_list_kb(trips, "MGTRIP", lambda t: labels[t["id"]]))


MANAGE_RENDERERS["mg_city_trips"] = mg_render_city_trips


async def mg_render_city_places(event, city_id, **kw):
    city = db.get_city(city_id)
    places = db.get_places(city_id)
    if not places:
        await reply(event, f"🏙 {city['name']} da hali joy yo'q.")
        return
    await reply(event, f"🏙 {city['name']}\n📍 Joyni tanlang:",
                kb.manage_list_kb(places, "MGPLACE",
                                  lambda p: f"{TYPE_LABELS.get(p['type'], '📌 ' + p['type'])} — {p['name']}"))


MANAGE_RENDERERS["mg_city_places"] = mg_render_city_places


async def mg_render_place_action(event, place_id, **kw):
    p = db.get_place(place_id)
    if not p:
        await reply(event, "Bu joy topilmadi.")
        return
    await reply(event, format_place(p), kb.manage_place_action_kb(place_id))


MANAGE_RENDERERS["mg_place_action"] = mg_render_place_action


async def mg_render_trip_action(event, trip_id, **kw):
    trip = db.get_trip(trip_id)
    if not trip:
        await reply(event, "Bu safar topilmadi.")
        return
    city = db.get_city(trip["city_id"])
    country = db.get_country(city["country_id"])
    await reply(event, build_trip_card_text(trip, city, country), kb.manage_trip_action_kb(trip_id))


MANAGE_RENDERERS["mg_trip_action"] = mg_render_trip_action


async def mg_render_trip_contacts(event, trip_id, **kw):
    contacts = db.get_contacts(trip_id)
    if not contacts:
        await reply(event, "Bu safarga hali kontakt qo'shilmagan.")
        return
    await reply(event, "👤 Kontaktni tanlang:", kb.manage_list_kb(contacts, "MGCONTACT", lambda c: c["name"]))


MANAGE_RENDERERS["mg_trip_contacts"] = mg_render_trip_contacts


async def mg_render_contact_action(event, contact_id, **kw):
    c = db.get_contact(contact_id)
    if not c:
        await reply(event, "Bu kontakt topilmadi.")
        return
    text = f"👤 <b>{c['name']}</b>"
    if c.get("contact_info"):
        text += f"\n📞 {c['contact_info']}"
    if c.get("notes"):
        text += f"\n📝 {c['notes']}"
    await reply(event, text, kb.manage_contact_action_kb(contact_id))


MANAGE_RENDERERS["mg_contact_action"] = mg_render_contact_action


async def mg_render_trip_expenses(event, trip_id, **kw):
    expenses = db.get_expenses(trip_id)
    if not expenses:
        await reply(event, "Bu safarga hali xarajat qo'shilmagan.")
        return
    await reply(event, "💰 Xarajatni tanlang:", kb.manage_list_kb(
        expenses, "MGEXPENSE",
        lambda e: f"{CATEGORY_LABELS.get(e['category'], e['category'])} — {fmt_money(e['amount'])} {e['currency']}"
    ))


MANAGE_RENDERERS["mg_trip_expenses"] = mg_render_trip_expenses


async def mg_render_expense_action(event, expense_id, **kw):
    e = db.get_expense(expense_id)
    if not e:
        await reply(event, "Bu xarajat topilmadi.")
        return
    text = f"💰 {CATEGORY_LABELS.get(e['category'], e['category'])} — {fmt_money(e['amount'])} {e['currency']}"
    if e.get("note"):
        text += f"\n📝 {e['note']}"
    await reply(event, text, kb.manage_expense_action_kb(expense_id))


MANAGE_RENDERERS["mg_expense_action"] = mg_render_expense_action


async def mg_render_trip_files(event, trip_id, **kw):
    files = db.get_files(trip_id)
    if not files:
        await reply(event, "Bu safarga hali fayl qo'shilmagan.")
        return
    await reply(event, "📎 Faylni tanlang:",
                kb.manage_list_kb(files, "MGFILE", lambda f: f.get("file_name") or f.get("notes") or "Fayl"))


MANAGE_RENDERERS["mg_trip_files"] = mg_render_trip_files


async def mg_render_file_action(event, file_id, **kw):
    f = db.get_file(file_id)
    if not f:
        await reply(event, "Bu fayl topilmadi.")
        return
    text = "📎 " + (f.get("file_name") or "Fayl")
    if f.get("notes"):
        text += f"\n📝 {f['notes']}"
    await reply(event, text, kb.manage_file_action_kb(file_id))


MANAGE_RENDERERS["mg_file_action"] = mg_render_file_action


async def mg_render_trip_diary(event, trip_id, **kw):
    entries = db.get_diary(trip_id)
    if not entries:
        await reply(event, "Bu safarga hali kundalik yozuvi yo'q.")
        return
    await reply(event, "📔 Yozuvni tanlang:",
                kb.manage_list_kb(entries, "MGDIARY", lambda d: f"{d['entry_date']}: {(d['text'] or '')[:20]}"))


MANAGE_RENDERERS["mg_trip_diary"] = mg_render_trip_diary


async def mg_render_diary_action(event, diary_id, **kw):
    d = db.get_diary_entry(diary_id)
    if not d:
        await reply(event, "Bu yozuv topilmadi.")
        return
    await reply(event, f"📔 {d['entry_date']}\n{d['text']}", kb.manage_diary_action_kb(diary_id))


MANAGE_RENDERERS["mg_diary_action"] = mg_render_diary_action


async def mg_render_trip_weather(event, trip_id, **kw):
    notes = db.get_weather_notes(trip_id)
    if not notes:
        await reply(event, "Bu safarga hali ob-havo yozuvi yo'q.")
        return
    await reply(event, "🌤 Yozuvni tanlang:", kb.manage_list_kb(
        notes, "MGWEATHER", lambda w: f"{w['entry_date']}: {w.get('conditions') or w.get('custom_text') or ''}"
    ))


MANAGE_RENDERERS["mg_trip_weather"] = mg_render_trip_weather


async def mg_render_weather_action(event, weather_id, **kw):
    w = db.get_weather_note(weather_id)
    if not w:
        await reply(event, "Bu yozuv topilmadi.")
        return
    text = f"🌤 {w['entry_date']}"
    if w.get("conditions"):
        text += f"\n{w['conditions']}"
    if w.get("custom_text"):
        text += f"\n📝 {w['custom_text']}"
    await reply(event, text, kb.manage_weather_action_kb(weather_id))


MANAGE_RENDERERS["mg_weather_action"] = mg_render_weather_action


# ---- Ro'yxatdan tanlash bosqichlari ----

@router.callback_query(F.data.startswith("MGCOUNTRY:"))
async def mg_click_country(callback: CallbackQuery, state: FSMContext):
    cid = int(callback.data.split(":")[1])
    await goto_m(callback, state, "mg_country_action", country_id=cid)
    await callback.answer()


@router.callback_query(F.data.startswith("MGCITY:"))
async def mg_click_city(callback: CallbackQuery, state: FSMContext):
    cid = int(callback.data.split(":")[1])
    await goto_m(callback, state, "mg_city_action", city_id=cid)
    await callback.answer()


@router.callback_query(F.data.startswith("MGTRIP:"))
async def mg_click_trip(callback: CallbackQuery, state: FSMContext):
    tid = int(callback.data.split(":")[1])
    await goto_m(callback, state, "mg_trip_action", trip_id=tid)
    await callback.answer()


@router.callback_query(F.data.startswith("MGPLACE:"))
async def mg_click_place(callback: CallbackQuery, state: FSMContext):
    pid = int(callback.data.split(":")[1])
    await goto_m(callback, state, "mg_place_action", place_id=pid)
    await callback.answer()


@router.callback_query(F.data.startswith("MGCONTACT:"))
async def mg_click_contact(callback: CallbackQuery, state: FSMContext):
    cid = int(callback.data.split(":")[1])
    await goto_m(callback, state, "mg_contact_action", contact_id=cid)
    await callback.answer()


@router.callback_query(F.data.startswith("MGEXPENSE:"))
async def mg_click_expense(callback: CallbackQuery, state: FSMContext):
    eid = int(callback.data.split(":")[1])
    await goto_m(callback, state, "mg_expense_action", expense_id=eid)
    await callback.answer()


@router.callback_query(F.data.startswith("MGFILE:"))
async def mg_click_file(callback: CallbackQuery, state: FSMContext):
    fid = int(callback.data.split(":")[1])
    await goto_m(callback, state, "mg_file_action", file_id=fid)
    await callback.answer()


@router.callback_query(F.data.startswith("MGDIARY:"))
async def mg_click_diary(callback: CallbackQuery, state: FSMContext):
    did = int(callback.data.split(":")[1])
    await goto_m(callback, state, "mg_diary_action", diary_id=did)
    await callback.answer()


@router.callback_query(F.data.startswith("MGWEATHER:"))
async def mg_click_weather(callback: CallbackQuery, state: FSMContext):
    wid = int(callback.data.split(":")[1])
    await goto_m(callback, state, "mg_weather_action", weather_id=wid)
    await callback.answer()


# ---- Davlat: nomi / shaharlar / o'chirish ----

async def mg_start_edit(event, state: FSMContext, field, entity_id, prompt):
    await state.set_state(ManageEdit.text_input)
    await state.update_data(_edit_field=field, _edit_id=entity_id)
    await reply(event, prompt, CANCEL_ONLY)


@router.callback_query(F.data.startswith("mngco_name:"))
async def mg_country_name_start(callback: CallbackQuery, state: FSMContext):
    cid = int(callback.data.split(":")[1])
    await mg_start_edit(callback, state, "country_name", cid, "✏️ Yangi davlat nomini yozing:")
    await callback.answer()


@router.callback_query(F.data.startswith("mngco_cities:"))
async def mg_country_cities_btn(callback: CallbackQuery, state: FSMContext):
    cid = int(callback.data.split(":")[1])
    await goto_m(callback, state, "mg_country_cities", country_id=cid)
    await callback.answer()


@router.callback_query(F.data.startswith("mngco_del:"))
async def mg_country_del(callback: CallbackQuery, state: FSMContext):
    cid = int(callback.data.split(":")[1])
    await reply(callback, "⚠️ Davlatni o'chirsangiz, undagi barcha shahar/joy/safar ma'lumotlari ham o'chadi. Ishonchingiz komilmi?",
                kb.confirm_kb(f"mngco_delyes:{cid}", f"mngco_delno:{cid}"))
    await callback.answer()


@router.callback_query(F.data.startswith("mngco_delno:"))
async def mg_country_del_no(callback: CallbackQuery, state: FSMContext):
    cid = int(callback.data.split(":")[1])
    await mg_render_country_action(callback, country_id=cid)
    await callback.answer()


@router.callback_query(F.data.startswith("mngco_delyes:"))
async def mg_country_del_yes(callback: CallbackQuery, state: FSMContext):
    cid = int(callback.data.split(":")[1])
    db.delete_country(cid)
    await mg_after_delete(callback, state)


# ---- Shahar: nomi / safarlar / joylar / o'chirish ----

@router.callback_query(F.data.startswith("mngci_name:"))
async def mg_city_name_start(callback: CallbackQuery, state: FSMContext):
    cid = int(callback.data.split(":")[1])
    await mg_start_edit(callback, state, "city_name", cid, "✏️ Yangi shahar nomini yozing:")
    await callback.answer()


@router.callback_query(F.data.startswith("mngci_trips:"))
async def mg_city_trips_btn(callback: CallbackQuery, state: FSMContext):
    cid = int(callback.data.split(":")[1])
    await goto_m(callback, state, "mg_city_trips", city_id=cid)
    await callback.answer()


@router.callback_query(F.data.startswith("mngci_places:"))
async def mg_city_places_btn(callback: CallbackQuery, state: FSMContext):
    cid = int(callback.data.split(":")[1])
    await goto_m(callback, state, "mg_city_places", city_id=cid)
    await callback.answer()


@router.callback_query(F.data.startswith("mngci_del:"))
async def mg_city_del(callback: CallbackQuery, state: FSMContext):
    cid = int(callback.data.split(":")[1])
    await reply(callback, "⚠️ Shaharni o'chirsangiz, undagi barcha safar/joy ma'lumotlari ham o'chadi. Ishonchingiz komilmi?",
                kb.confirm_kb(f"mngci_delyes:{cid}", f"mngci_delno:{cid}"))
    await callback.answer()


@router.callback_query(F.data.startswith("mngci_delno:"))
async def mg_city_del_no(callback: CallbackQuery, state: FSMContext):
    cid = int(callback.data.split(":")[1])
    await mg_render_city_action(callback, city_id=cid)
    await callback.answer()


@router.callback_query(F.data.startswith("mngci_delyes:"))
async def mg_city_del_yes(callback: CallbackQuery, state: FSMContext):
    cid = int(callback.data.split(":")[1])
    db.delete_city(cid)
    await mg_after_delete(callback, state)


# ---- Safar: holati / izoh / byudjet / valyuta / kurs / sub-bo'limlar / o'chirish ----

@router.callback_query(F.data.startswith("mngt_status:"))
async def mg_trip_status_btn(callback: CallbackQuery, state: FSMContext):
    tid = int(callback.data.split(":")[1])
    await reply(callback, "Holatni tanlang:", kb.manage_status_kb(tid))
    await callback.answer()


@router.callback_query(F.data.regexp(r"^mngt_status_set:(\d+):(visited|wishlist)$"))
async def mg_trip_status_set(callback: CallbackQuery, state: FSMContext):
    _, tid, status = callback.data.split(":")
    db.update_trip_status(int(tid), status)
    await mg_render_trip_action(callback, trip_id=int(tid))
    await callback.answer("✅ Saqlandi")


@router.callback_query(F.data.startswith("mngt_note:"))
async def mg_trip_note_start(callback: CallbackQuery, state: FSMContext):
    tid = int(callback.data.split(":")[1])
    await mg_start_edit(callback, state, "trip_note", tid, "📝 Yangi izoh/sana yozing:")
    await callback.answer()


@router.callback_query(F.data.startswith("mngt_budget:"))
async def mg_trip_budget_start(callback: CallbackQuery, state: FSMContext):
    tid = int(callback.data.split(":")[1])
    trip = db.get_trip(tid)
    await mg_start_edit(callback, state, "trip_budget_amount", tid,
                         f"💰 Yangi byudjet miqdorini kiriting ({trip.get('budget_currency') or ''}, faqat son):")
    await callback.answer()


@router.callback_query(F.data.startswith("mngt_citycur:"))
async def mg_trip_citycur_start(callback: CallbackQuery, state: FSMContext):
    tid = int(callback.data.split(":")[1])
    await mg_start_edit(callback, state, "trip_citycur", tid, "💱 Yangi shahar valyutasini yozing:")
    await callback.answer()


@router.callback_query(F.data.startswith("mngt_rate:"))
async def mg_trip_rate_start(callback: CallbackQuery, state: FSMContext):
    tid = int(callback.data.split(":")[1])
    trip = db.get_trip(tid)
    await mg_start_edit(callback, state, "trip_rate", tid,
                         f"💱 Yangi kursni kiriting (1 {trip.get('budget_currency') or ''} = ? {trip.get('city_currency') or ''}):")
    await callback.answer()


@router.callback_query(F.data.startswith("mngt_contacts:"))
async def mg_trip_contacts_btn(callback: CallbackQuery, state: FSMContext):
    tid = int(callback.data.split(":")[1])
    await goto_m(callback, state, "mg_trip_contacts", trip_id=tid)
    await callback.answer()


@router.callback_query(F.data.startswith("mngt_expenses:"))
async def mg_trip_expenses_btn(callback: CallbackQuery, state: FSMContext):
    tid = int(callback.data.split(":")[1])
    await goto_m(callback, state, "mg_trip_expenses", trip_id=tid)
    await callback.answer()


@router.callback_query(F.data.startswith("mngt_files:"))
async def mg_trip_files_btn(callback: CallbackQuery, state: FSMContext):
    tid = int(callback.data.split(":")[1])
    await goto_m(callback, state, "mg_trip_files", trip_id=tid)
    await callback.answer()


@router.callback_query(F.data.startswith("mngt_diary:"))
async def mg_trip_diary_btn(callback: CallbackQuery, state: FSMContext):
    tid = int(callback.data.split(":")[1])
    await goto_m(callback, state, "mg_trip_diary", trip_id=tid)
    await callback.answer()


@router.callback_query(F.data.startswith("mngt_weather:"))
async def mg_trip_weather_btn(callback: CallbackQuery, state: FSMContext):
    tid = int(callback.data.split(":")[1])
    await goto_m(callback, state, "mg_trip_weather", trip_id=tid)
    await callback.answer()


@router.callback_query(F.data.startswith("mngt_del:"))
async def mg_trip_del(callback: CallbackQuery, state: FSMContext):
    tid = int(callback.data.split(":")[1])
    await reply(callback, "⚠️ Safarni o'chirsangiz, undagi barcha kontakt/xarajat/fayl/kundalik/ob-havo ma'lumotlari ham o'chadi. Ishonchingiz komilmi?",
                kb.confirm_kb(f"mngt_delyes:{tid}", f"mngt_delno:{tid}"))
    await callback.answer()


@router.callback_query(F.data.startswith("mngt_delno:"))
async def mg_trip_del_no(callback: CallbackQuery, state: FSMContext):
    tid = int(callback.data.split(":")[1])
    await mg_render_trip_action(callback, trip_id=tid)
    await callback.answer()


@router.callback_query(F.data.startswith("mngt_delyes:"))
async def mg_trip_del_yes(callback: CallbackQuery, state: FSMContext):
    tid = int(callback.data.split(":")[1])
    db.delete_trip(tid)
    await mg_after_delete(callback, state)


# ---- Joy: narx / reyting / izoh / o'chirish ----

@router.callback_query(F.data.startswith("mngp_price:"))
async def mg_place_price_start(callback: CallbackQuery, state: FSMContext):
    pid = int(callback.data.split(":")[1])
    await mg_start_edit(callback, state, "place_price", pid, "💵 Yangi narxni yozing:")
    await callback.answer()


@router.callback_query(F.data.startswith("mngp_rating:"))
async def mg_place_rating_btn(callback: CallbackQuery, state: FSMContext):
    pid = int(callback.data.split(":")[1])
    await reply(callback, "⭐ Yangi bahoni tanlang:", kb.manage_rating_kb(pid))
    await callback.answer()


@router.callback_query(F.data.regexp(r"^mngp_rating_set:(\d+):(\d+)$"))
async def mg_place_rating_set(callback: CallbackQuery, state: FSMContext):
    _, pid, rating = callback.data.split(":")
    db.update_place_rating(int(pid), int(rating) if int(rating) > 0 else None)
    await mg_render_place_action(callback, place_id=int(pid))
    await callback.answer("✅ Saqlandi")


@router.callback_query(F.data.startswith("mngp_notes:"))
async def mg_place_notes_start(callback: CallbackQuery, state: FSMContext):
    pid = int(callback.data.split(":")[1])
    await mg_start_edit(callback, state, "place_notes", pid, "📝 Yangi izohni yozing:")
    await callback.answer()


@router.callback_query(F.data.startswith("mngp_del:"))
async def mg_place_del(callback: CallbackQuery, state: FSMContext):
    pid = int(callback.data.split(":")[1])
    await reply(callback, "🗑 Ushbu joyni o'chirasizmi?", kb.confirm_kb(f"mngp_delyes:{pid}", f"mngp_delno:{pid}"))
    await callback.answer()


@router.callback_query(F.data.startswith("mngp_delno:"))
async def mg_place_del_no(callback: CallbackQuery, state: FSMContext):
    pid = int(callback.data.split(":")[1])
    await mg_render_place_action(callback, place_id=pid)
    await callback.answer()


@router.callback_query(F.data.startswith("mngp_delyes:"))
async def mg_place_del_yes(callback: CallbackQuery, state: FSMContext):
    pid = int(callback.data.split(":")[1])
    db.delete_place(pid)
    await mg_after_delete(callback, state)


# ---- Xarajat: summa / izoh / o'chirish ----

@router.callback_query(F.data.startswith("mnge_amount:"))
async def mg_expense_amount_start(callback: CallbackQuery, state: FSMContext):
    eid = int(callback.data.split(":")[1])
    await mg_start_edit(callback, state, "expense_amount", eid, "💵 Yangi summani kiriting (faqat son):")
    await callback.answer()


@router.callback_query(F.data.startswith("mnge_note:"))
async def mg_expense_note_start(callback: CallbackQuery, state: FSMContext):
    eid = int(callback.data.split(":")[1])
    await mg_start_edit(callback, state, "expense_note", eid, "📝 Yangi izohni yozing:")
    await callback.answer()


@router.callback_query(F.data.startswith("mnge_del:"))
async def mg_expense_del(callback: CallbackQuery, state: FSMContext):
    eid = int(callback.data.split(":")[1])
    await reply(callback, "🗑 Ushbu xarajatni o'chirasizmi?", kb.confirm_kb(f"mnge_delyes:{eid}", f"mnge_delno:{eid}"))
    await callback.answer()


@router.callback_query(F.data.startswith("mnge_delno:"))
async def mg_expense_del_no(callback: CallbackQuery, state: FSMContext):
    eid = int(callback.data.split(":")[1])
    await mg_render_expense_action(callback, expense_id=eid)
    await callback.answer()


@router.callback_query(F.data.startswith("mnge_delyes:"))
async def mg_expense_del_yes(callback: CallbackQuery, state: FSMContext):
    eid = int(callback.data.split(":")[1])
    db.delete_expense(eid)
    await mg_after_delete(callback, state)


# ---- Kontakt: ma'lumot / o'chirish ----

@router.callback_query(F.data.startswith("mngk_info:"))
async def mg_contact_info_start(callback: CallbackQuery, state: FSMContext):
    kid = int(callback.data.split(":")[1])
    await mg_start_edit(callback, state, "contact_info", kid, "📞 Yangi aloqa ma'lumotini yozing:")
    await callback.answer()


@router.callback_query(F.data.startswith("mngk_del:"))
async def mg_contact_del(callback: CallbackQuery, state: FSMContext):
    kid = int(callback.data.split(":")[1])
    await reply(callback, "🗑 Ushbu kontaktni o'chirasizmi?", kb.confirm_kb(f"mngk_delyes:{kid}", f"mngk_delno:{kid}"))
    await callback.answer()


@router.callback_query(F.data.startswith("mngk_delno:"))
async def mg_contact_del_no(callback: CallbackQuery, state: FSMContext):
    kid = int(callback.data.split(":")[1])
    await mg_render_contact_action(callback, contact_id=kid)
    await callback.answer()


@router.callback_query(F.data.startswith("mngk_delyes:"))
async def mg_contact_del_yes(callback: CallbackQuery, state: FSMContext):
    kid = int(callback.data.split(":")[1])
    db.delete_contact(kid)
    await mg_after_delete(callback, state)


# ---- Fayl / Kundalik / Ob-havo: faqat o'chirish ----

@router.callback_query(F.data.startswith("mngf_del:"))
async def mg_file_del(callback: CallbackQuery, state: FSMContext):
    fid = int(callback.data.split(":")[1])
    await reply(callback, "🗑 Ushbu faylni o'chirasizmi?", kb.confirm_kb(f"mngf_delyes:{fid}", f"mngf_delno:{fid}"))
    await callback.answer()


@router.callback_query(F.data.startswith("mngf_delno:"))
async def mg_file_del_no(callback: CallbackQuery, state: FSMContext):
    fid = int(callback.data.split(":")[1])
    await mg_render_file_action(callback, file_id=fid)
    await callback.answer()


@router.callback_query(F.data.startswith("mngf_delyes:"))
async def mg_file_del_yes(callback: CallbackQuery, state: FSMContext):
    fid = int(callback.data.split(":")[1])
    db.delete_file(fid)
    await mg_after_delete(callback, state)


@router.callback_query(F.data.startswith("mngd_del:"))
async def mg_diary_del(callback: CallbackQuery, state: FSMContext):
    did = int(callback.data.split(":")[1])
    await reply(callback, "🗑 Ushbu yozuvni o'chirasizmi?", kb.confirm_kb(f"mngd_delyes:{did}", f"mngd_delno:{did}"))
    await callback.answer()


@router.callback_query(F.data.startswith("mngd_delno:"))
async def mg_diary_del_no(callback: CallbackQuery, state: FSMContext):
    did = int(callback.data.split(":")[1])
    await mg_render_diary_action(callback, diary_id=did)
    await callback.answer()


@router.callback_query(F.data.startswith("mngd_delyes:"))
async def mg_diary_del_yes(callback: CallbackQuery, state: FSMContext):
    did = int(callback.data.split(":")[1])
    db.delete_diary_entry(did)
    await mg_after_delete(callback, state)


@router.callback_query(F.data.startswith("mngw_del:"))
async def mg_weather_del(callback: CallbackQuery, state: FSMContext):
    wid = int(callback.data.split(":")[1])
    await reply(callback, "🗑 Ushbu yozuvni o'chirasizmi?", kb.confirm_kb(f"mngw_delyes:{wid}", f"mngw_delno:{wid}"))
    await callback.answer()


@router.callback_query(F.data.startswith("mngw_delno:"))
async def mg_weather_del_no(callback: CallbackQuery, state: FSMContext):
    wid = int(callback.data.split(":")[1])
    await mg_render_weather_action(callback, weather_id=wid)
    await callback.answer()


@router.callback_query(F.data.startswith("mngw_delyes:"))
async def mg_weather_del_yes(callback: CallbackQuery, state: FSMContext):
    wid = int(callback.data.split(":")[1])
    db.delete_weather_note(wid)
    await mg_after_delete(callback, state)


# ---- Matn kiritish orqali tahrirlash ----

@router.message(ManageEdit.text_input)
async def mg_text_input(message: Message, state: FSMContext):
    data = await state.get_data()
    field = data.get("_edit_field")
    eid = data.get("_edit_id")
    text = message.text.strip() if message.text else ""

    if field in ("trip_budget_amount", "trip_rate", "expense_amount"):
        val = parse_number(text)
        if val is None:
            await message.answer("Iltimos, faqat son kiriting:", reply_markup=CANCEL_ONLY)
            return
    else:
        val = text
        if not val and field in ("country_name", "city_name", "trip_citycur"):
            await message.answer("Iltimos, matn kiriting:", reply_markup=CANCEL_ONLY)
            return

    if field == "country_name":
        db.update_country_name(eid, val)
        kind, kwargs = "mg_country_action", {"country_id": eid}
    elif field == "city_name":
        db.update_city_name(eid, val)
        kind, kwargs = "mg_city_action", {"city_id": eid}
    elif field == "trip_note":
        db.update_trip_note(eid, val or None)
        kind, kwargs = "mg_trip_action", {"trip_id": eid}
    elif field == "trip_budget_amount":
        db.update_trip_budget_amount(eid, val)
        kind, kwargs = "mg_trip_action", {"trip_id": eid}
    elif field == "trip_citycur":
        db.update_trip_city_currency(eid, val)
        kind, kwargs = "mg_trip_action", {"trip_id": eid}
    elif field == "trip_rate":
        db.update_trip_exchange_rate(eid, val)
        kind, kwargs = "mg_trip_action", {"trip_id": eid}
    elif field == "place_price":
        db.update_place_price(eid, val or None)
        kind, kwargs = "mg_place_action", {"place_id": eid}
    elif field == "place_notes":
        db.update_place_notes(eid, val or None)
        kind, kwargs = "mg_place_action", {"place_id": eid}
    elif field == "expense_amount":
        db.update_expense_amount(eid, val)
        kind, kwargs = "mg_expense_action", {"expense_id": eid}
    elif field == "expense_note":
        db.update_expense_note(eid, val or None)
        kind, kwargs = "mg_expense_action", {"expense_id": eid}
    elif field == "contact_info":
        db.update_contact_info(eid, val or None)
        kind, kwargs = "mg_contact_action", {"contact_id": eid}
    else:
        await state.set_state(None)
        return

    await state.set_state(None)
    await message.answer("✅ Saqlandi")
    await MANAGE_RENDERERS[kind](message, **kwargs)

# Buni handlers.py ichiga, boshqa @router.message(Command("...")) larning
# yoniga (masalan cmd_help funksiyasidan keyin) qo'shing.
# NETLIFY_SITE_URL ni haqiqiy Netlify manzilingizga almashtiring.

NETLIFY_SITE_URL = "https://SIZNING-SAYTINGIZ.netlify.app"


@router.message(Command("mysite"))
async def cmd_mysite(message: Message):
    token = db.get_or_create_web_token(message.from_user.id)
    link = f"{https://mytravel-site.netlify.app/}/?token={token}"
    await message.answer(
        "🔗 Sizning shaxsiy saytingiz:\n"
        f"{link}\n\n"
        "⚠️ Bu havolani hech kimga yubormang — kim havolani bilsa, "
        "sizning barcha safar ma'lumotlaringizni ko'ra oladi."
    )
