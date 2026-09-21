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


def single_delete_kb(callback_data):
    b = InlineKeyboardBuilder()
    b.button(text="🗑 O'chirish", callback_data=callback_data)
    return b.as_markup()


def confirm_kb(yes_cb, no_cb):
    b = InlineKeyboardBuilder()
    b.button(text="✅ Ha, o'chirish", callback_data=yes_cb)
    b.button(text="❌ Bekor qilish", callback_data=no_cb)
    b.adjust(2)
    return b.as_markup()


def manage_list_kb(items, prefix, label_func):
    b = InlineKeyboardBuilder()
    for it in items:
        b.button(text=label_func(it), callback_data=f"{prefix}:{it['id']}")
    b.adjust(1)
    return b.as_markup()


def manage_country_action_kb(country_id):
    b = InlineKeyboardBuilder()
    b.button(text="✏️ Nomi", callback_data=f"mngc_name:{country_id}")
    b.button(text="✏️ Holati", callback_data=f"mngc_status:{country_id}")
    b.button(text="✏️ Byudjet", callback_data=f"mngc_budget:{country_id}")
    b.button(text="✏️ Izoh", callback_data=f"mngc_notes:{country_id}")
    b.button(text="🏙 Shaharlar", callback_data=f"mngc_cities:{country_id}")
    b.button(text="🗑 Davlatni o'chirish", callback_data=f"mngc_del:{country_id}")
    b.adjust(1)
    return b.as_markup()


def manage_status_kb(country_id):
    b = InlineKeyboardBuilder()
    b.button(text="✅ Borgan", callback_data=f"mngc_status_set:{country_id}:visited")
    b.button(text="🎯 Bormoqchi", callback_data=f"mngc_status_set:{country_id}:wishlist")
    b.adjust(2)
    return b.as_markup()


def manage_city_action_kb(city_id):
    b = InlineKeyboardBuilder()
    b.button(text="✏️ Nomini o'zgartirish", callback_data=f"mngci_name:{city_id}")
    b.button(text="📍 Joylar", callback_data=f"mngp:{city_id}")
    b.button(text="👤 Kontaktlar", callback_data=f"mngk:{city_id}")
    b.button(text="📔 Kundalik", callback_data=f"mngd:{city_id}")
    b.button(text="💰 Xarajatlar", callback_data=f"mnge:{city_id}")
    b.button(text="📎 Fayllar", callback_data=f"mngf:{city_id}")
    b.button(text="🗑 Shaharni o'chirish", callback_data=f"mngci_del:{city_id}")
    b.adjust(1)
    return b.as_markup()


def manage_place_action_kb(place_id):
    b = InlineKeyboardBuilder()
    b.button(text="✏️ Narxi", callback_data=f"mngp_price:{place_id}")
    b.button(text="⭐ Reyting", callback_data=f"mngp_rating:{place_id}")
    b.button(text="✏️ Izoh", callback_data=f"mngp_notes:{place_id}")
    b.button(text="🗑 O'chirish", callback_data=f"mngp_del:{place_id}")
    b.adjust(1)
    return b.as_markup()


def manage_rating_kb(place_id):
    b = InlineKeyboardBuilder()
    for i in range(1, 6):
        b.button(text="⭐" * i, callback_data=f"mngp_rating_set:{place_id}:{i}")
    b.button(text="Baholanmagan", callback_data=f"mngp_rating_set:{place_id}:0")
    b.adjust(1)
    return b.as_markup()


def manage_expense_action_kb(expense_id):
    b = InlineKeyboardBuilder()
    b.button(text="✏️ Summasi", callback_data=f"mnge_amount:{expense_id}")
    b.button(text="✏️ Izoh", callback_data=f"mnge_note:{expense_id}")
    b.button(text="🗑 O'chirish", callback_data=f"mnge_del:{expense_id}")
    b.adjust(1)
    return b.as_markup()


def manage_contact_action_kb(contact_id):
    b = InlineKeyboardBuilder()
    b.button(text="✏️ Ma'lumotini o'zgartirish", callback_data=f"mngk_info:{contact_id}")
    b.button(text="🗑 O'chirish", callback_data=f"mngk_del:{contact_id}")
    b.adjust(1)
    return b.as_markup()
