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


def budget_period_kb():
    b = InlineKeyboardBuilder()
    b.button(text="💰 Umumiy", callback_data="bperiod:total")
    b.button(text="📅 Kunlik", callback_data="bperiod:daily")
    b.button(text="🗓 Oylik", callback_data="bperiod:monthly")
    b.adjust(1)
    return b.as_markup()


def country_select_kb(countries, prefix, show_add=True):
    b = InlineKeyboardBuilder()
    for c in countries:
        emoji = "✅" if c["status"] == "visited" else "🎯"
        b.button(text=f"{emoji} {c['name']}", callback_data=f"{prefix}:{c['id']}")
    if show_add:
        b.button(text="➕ Yangi davlat qo'shish", callback_data=f"{prefix}:new")
    b.adjust(1)
    return b.as_markup()


def city_select_kb(cities, prefix, show_add=True):
    b = InlineKeyboardBuilder()
    for c in cities:
        b.button(text=f"🏙 {c['name']}", callback_data=f"{prefix}:{c['id']}")
    if show_add:
        b.button(text="➕ Yangi shahar qo'shish", callback_data=f"{prefix}:new")
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
        b.button(text=p["name"], callback_data=f"link_place:{p['id']}")
    b.button(text="Bog'lamaslik ⏭", callback_data="link_place:none")
    b.adjust(1)
    return b.as_markup()


def weather_save_kb():
    b = InlineKeyboardBuilder()
    b.button(text="📔 Kundalikka saqlash", callback_data="save_weather")
    return b.as_markup()


def type_filter_kb(city_id):
    b = InlineKeyboardBuilder()
    b.button(text="🏨 Mehmonxona", callback_data=f"places_show:{city_id}:hotel")
    b.button(text="🍽 Restoran", callback_data=f"places_show:{city_id}:restaurant")
    b.button(text="🏛 Ko'rish joyi", callback_data=f"places_show:{city_id}:attraction")
    b.button(text="📋 Barchasi", callback_data=f"places_show:{city_id}:all")
    b.adjust(1)
    return b.as_markup()
