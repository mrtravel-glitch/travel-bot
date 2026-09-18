from aiogram.utils.keyboard import InlineKeyboardBuilder


def skip_kb(callback_data):
    b = InlineKeyboardBuilder()
    b.button(text="O'tkazib yuborish ⏭", callback_data=callback_data)
    return b.as_markup()


def done_kb(callback_data, text="✅ Tugatdim"):
    b = InlineKeyboardBuilder()
    b.button(text=text, callback_data=callback_data)
    return b.as_markup()


def status_kb():
    b = InlineKeyboardBuilder()
    b.button(text="✅ Borgan", callback_data="status:visited")
    b.button(text="🎯 Bormoqchi", callback_data="status:wishlist")
    b.adjust(2)
    return b.as_markup()


def trips_kb(trips):
    b = InlineKeyboardBuilder()
    for t in trips:
        emoji = "✅" if t["status"] == "visited" else "🎯"
        label = f"{emoji} {t['country']}" + (f", {t['city']}" if t["city"] else "")
        b.button(text=label, callback_data=f"select_trip:{t['id']}")
    b.adjust(1)
    return b.as_markup()


def place_type_kb():
    b = InlineKeyboardBuilder()
    b.button(text="🏨 Mehmonxona", callback_data="ptype:hotel")
    b.button(text="🍽 Restoran", callback_data="ptype:restaurant")
    b.button(text="🏛 Ko'rish joyi", callback_data="ptype:attraction")
    b.adjust(1)
    return b.as_markup()


def yes_no_unknown_kb(prefix):
    b = InlineKeyboardBuilder()
    b.button(text="✅ Ha", callback_data=f"{prefix}:yes")
    b.button(text="❌ Yo'q", callback_data=f"{prefix}:no")
    b.button(text="🤷 Bilmayman", callback_data=f"{prefix}:unknown")
    b.adjust(3)
    return b.as_markup()


def rating_kb():
    b = InlineKeyboardBuilder()
    for i in range(1, 6):
        b.button(text="⭐" * i, callback_data=f"rating:{i}")
    b.button(text="O'tkazib yuborish ⏭", callback_data="rating:skip")
    b.adjust(1)
    return b.as_markup()


def category_kb():
    cats = ["✈️ Aviachipta", "🏨 Mehmonxona", "🍽 Ovqat", "🚕 Transport", "🎟 Kirish/faoliyat", "🛍 Xarid", "📌 Boshqa"]
    b = InlineKeyboardBuilder()
    for c in cats:
        b.button(text=c, callback_data=f"cat:{c}")
    b.adjust(2)
    return b.as_markup()


def places_link_kb(places):
    b = InlineKeyboardBuilder()
    for p in places:
        label = f"{p['name']} ({p['city']})" if p["city"] else p["name"]
        b.button(text=label, callback_data=f"link_place:{p['id']}")
    b.button(text="Bog'lamaslik ⏭", callback_data="link_place:none")
    b.adjust(1)
    return b.as_markup()


def weather_save_kb():
    b = InlineKeyboardBuilder()
    b.button(text="📔 Kundalikka saqlash", callback_data="save_weather")
    return b.as_markup()


def city_filter_kb(cities):
    b = InlineKeyboardBuilder()
    for c in cities:
        b.button(text=f"🏙 {c}", callback_data=f"places_city:{c}")
    b.button(text="🌍 Barchasi", callback_data="places_city:all")
    b.adjust(1)
    return b.as_markup()


def type_filter_kb(city):
    b = InlineKeyboardBuilder()
    b.button(text="🏨 Mehmonxona", callback_data=f"places_show:{city}:hotel")
    b.button(text="🍽 Restoran", callback_data=f"places_show:{city}:restaurant")
    b.button(text="🏛 Ko'rish joyi", callback_data=f"places_show:{city}:attraction")
    b.button(text="📋 Barchasi", callback_data=f"places_show:{city}:all")
    b.adjust(1)
    return b.as_markup()
