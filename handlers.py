from datetime import date

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery

import database as db
import keyboards as kb
from states import TripAdd, DiaryAdd, PlaceAdd, ContactAdd, ExpenseAdd

router = Router()

TYPE_NAMES = {"hotel": "🏨 Mehmonxona", "restaurant": "🍽 Restoran", "attraction": "🏛 Ko'rish joyi"}


def fmt_money(amount):
    return f"{amount:,.0f}".replace(",", " ")


# ================= BASIC =================

@router.message(Command("start"))
async def cmd_start(message: Message):
    await message.answer(
        "👋 Salom! Men sizning shaxsiy sayohat botingizman.\n\n"
        "Borgan va bormoqchi bo'lgan davlatlaringizni, kundaligingizni, "
        "joylar, kontaktlar va xarajatlaringizni saqlab boraman.\n\n"
        "Boshlash uchun: /trip_add — yangi safar qo'shing\n"
        "Barcha komandalar: /help"
    )


@router.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(
        "📋 <b>Komandalar</b>\n\n"
        "<b>Safarlar</b>\n"
        "/trip_add — yangi davlat/safar qo'shish\n"
        "/trips — barcha safarlar, faolini tanlash\n"
        "/trip — hozirgi faol safar haqida ma'lumot\n\n"
        "<b>Kundalik</b>\n"
        "/diary_add — yozuv qo'shish (matn yoki rasm+izoh)\n"
        "/diary — yozuvlarni ko'rish\n\n"
        "<b>Joylar</b>\n"
        "/place_add — mehmonxona/restoran/joy qo'shish\n"
        "/places — joylar ro'yxati\n\n"
        "<b>Kontaktlar</b>\n"
        "/contact_add — kontakt qo'shish\n"
        "/contacts — kontaktlar ro'yxati\n\n"
        "<b>Xarajatlar</b>\n"
        "/expense_add — xarajat qo'shish\n"
        "/expenses — faol safar bo'yicha hisobot\n\n"
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
    await state.set_state(TripAdd.notes)
    await callback.message.edit_text(
        "Izoh qoldirmoqchimisiz? (reja, maqsad va h.k.)", reply_markup=kb.skip_kb("skip_trip_notes")
    )
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
        status=data["status"], notes=notes,
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
    await message.answer("Safarni tanlang (faol qilib belgilash uchun):", reply_markup=kb.trips_kb(trips))


@router.callback_query(F.data.startswith("select_trip:"))
async def cb_select_trip(callback: CallbackQuery):
    trip_id = int(callback.data.split(":")[1])
    db.set_active_trip(callback.from_user.id, trip_id)
    trip = db.get_trip(trip_id)
    emoji = "✅" if trip["status"] == "visited" else "🎯"
    label = trip["country"] + (f", {trip['city']}" if trip["city"] else "")
    await callback.message.edit_text(f"{emoji} Faol safar: {label}")
    await callback.answer()


@router.message(Command("trip"))
async def cmd_trip(message: Message):
    trip = await require_active_trip(message)
    if not trip:
        return
    emoji = "✅" if trip["status"] == "visited" else "🎯"
    text = f"{emoji} <b>{trip['country']}</b>"
    if trip["city"]:
        text += f", {trip['city']}"
    if trip["notes"]:
        text += f"\n📝 {trip['notes']}"

    places = db.get_places(trip["id"])
    diary = db.get_diary(trip["id"])
    contacts = db.get_contacts(trip["id"])
    expenses = db.get_expense_summary(trip["id"])
    total = sum(r["total"] for r in expenses) if expenses else 0

    text += (
        f"\n\n📍 Joylar: {len(places)}\n📔 Kundalik: {len(diary)}\n"
        f"👤 Kontaktlar: {len(contacts)}\n💰 Jami xarajat: {fmt_money(total)} so'm"
    )
    await message.answer(text)


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
    await state.set_state(PlaceAdd.type)
    await message.answer("Turi qanday?", reply_markup=kb.place_type_kb())


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
    await state.set_state(PlaceAdd.address)
    await callback.message.edit_text(
        "📌 Manzil/lokatsiya (matn):", reply_markup=kb.skip_kb("skip_address")
    )
    await callback.answer()


@router.message(PlaceAdd.address)
async def place_add_address(message: Message, state: FSMContext):
    await state.update_data(address=message.text.strip())
    await state.set_state(PlaceAdd.notes)
    await message.answer("📝 Izoh:", reply_markup=kb.skip_kb("skip_place_notes"))


@router.callback_query(PlaceAdd.address, F.data == "skip_address")
async def place_add_address_skip(callback: CallbackQuery, state: FSMContext):
    await state.update_data(address=None)
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
    db.add_place(
        trip["id"], data["name"], data["type"], data.get("is_halal"),
        data.get("price"), data.get("rating"), data.get("address"), None, notes,
    )
    await state.clear()
    await answer_func(f"✅ Saqlandi: {data['name']} ({TYPE_NAMES.get(data['type'], data['type'])})")


@router.message(Command("places"))
async def cmd_places(message: Message):
    trip = await require_active_trip(message)
    if not trip:
        return
    places = db.get_places(trip["id"])
    if not places:
        await message.answer("Bu safar uchun hali joylar qo'shilmagan.")
        return
    lines = []
    for p in places:
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
        if p["notes"]:
            line += f"\n📝 {p['notes']}"
        lines.append(line)
    await message.answer("\n\n".join(lines))


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
    await message.answer(
        "📞 Telefon/Telegram/Instagram:", reply_markup=kb.skip_kb("skip_contact_info")
    )


@router.message(ContactAdd.contact_info)
async def contact_add_info(message: Message, state: FSMContext):
    await state.update_data(contact_info=message.text.strip())
    await state.set_state(ContactAdd.notes)
    await message.answer(
        "📝 Izoh (qayerda tanishdingiz va h.k.):", reply_markup=kb.skip_kb("skip_contact_notes")
    )


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
    await state.set_state(ExpenseAdd.note)
    await message.answer(
        "📝 Izoh (masalan, joy nomi):", reply_markup=kb.skip_kb("skip_expense_note")
    )


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
    db.add_expense(trip["id"], data["category"], data["amount"], "so'm", str(date.today()), note)
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
    await message.answer("\n".join(lines))


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
        text += f"\n🔝 Eng ko'p sarflangan: {s['top_category']['category']} ({fmt_money(s['top_category']['total'])})"
    await message.answer(text)
