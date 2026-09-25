from aiogram.utils.keyboard import InlineKeyboardBuilder

CURRENCIES = ["so'm", "$", "€"]

WEATHER_OPTIONS = [
    ("hot", "☀️ Issiq"),
    ("warm", "🌤 Iliq"),
    ("cold", "❄️ Sovuq"),
    ("windy", "💨 Shamolli"),
    ("rainy", "🌧 Yomg'irli"),
    ("snowy", "🌨 Qorli"),
    ("cloudy", "☁️ Bulutli"),
]

CATEGORIES = [
    ("flight", "✈️ Aviachipta"),
    ("hotel", "🏨 Mehmonxona"),
    ("food", "🍽 Ovqat"),
    ("transport", "🚕 Transport"),
    ("shopping", "🛍 Xarid"),
    ("other", "📌 Boshqa"),
]

PLACE_TYPES = [
    ("hotel", "🏨 Mehmonxona"),
    ("restaurant", "🍽 Restoran"),
    ("attraction", "🏛 Ko'rish joyi"),
    ("other", "📌 Boshqa"),
]


def add_nav(b: InlineKeyboardBuilder, back=True, cancel=False, adjust_last=1):
    if back:
        b.button(text="⬅️ Orqaga", callback_data="nav:back")
    if cancel:
        b.button(text="❌ Bekor qilish", callback_data="nav:cancel")


def nav_only_kb(back=True, cancel=True):
    b = InlineKeyboardBuilder()
    add_nav(b, back=back, cancel=cancel)
    b.adjust(2)
    return b.as_markup()


def skip_kb(callback_data, back=True, back_cb="nav:back"):
    b = InlineKeyboardBuilder()
    b.button(text="O'tkazib yuborish ⏭", callback_data=callback_data)
    if back:
        b.button(text="⬅️ Orqaga", callback_data=back_cb)
    b.adjust(1)
    return b.as_markup()


def done_kb(callback_data, text="✅ Tugatdim", back=False, back_cb="nav:back"):
    b = InlineKeyboardBuilder()
    b.button(text=text, callback_data=callback_data)
    if back:
        b.button(text="⬅️ Orqaga", callback_data=back_cb)
    b.adjust(1)
    return b.as_markup()


def status_kb(back_cb="nav:back"):
    b = InlineKeyboardBuilder()
    b.button(text="✅ Borgan", callback_data="status:visited")
    b.button(text="🎯 Bormoqchi", callback_data="status:wishlist")
    b.button(text="⬅️ Orqaga", callback_data=back_cb)
    b.adjust(2, 1)
    return b.as_markup()


def country_select_kb(countries, prefix, show_add=True, back=False):
    b = InlineKeyboardBuilder()
    for c in countries:
        b.button(text=f"🌍 {c['name']}", callback_data=f"{prefix}:{c['id']}")
    if show_add:
        b.button(text="➕ Yangi davlat qo'shish", callback_data=f"{prefix}:new")
    if back:
        b.button(text="⬅️ Orqaga", callback_data="nav:back")
    b.adjust(1)
    return b.as_markup()


def city_select_kb(cities, prefix, show_add=True):
    b = InlineKeyboardBuilder()
    for c in cities:
        b.button(text=f"🏙 {c['name']}", callback_data=f"{prefix}:{c['id']}")
    if show_add:
        b.button(text="➕ Yangi shahar qo'shish", callback_data=f"{prefix}:new")
    add_nav(b, back=True)
    b.adjust(1)
    return b.as_markup()


def trip_select_kb(trips, prefix, labels=None):
    b = InlineKeyboardBuilder()
    for i, t in enumerate(trips, 1):
        emoji = "✅" if t["status"] == "visited" else "🎯"
        label = labels[t["id"]] if labels and t["id"] in labels else f"{i}-safar"
        b.button(text=f"{emoji} {label}", callback_data=f"{prefix}:{t['id']}")
    add_nav(b, back=True)
    b.adjust(1)
    return b.as_markup()


def currency_kb(prefix, back=True, back_cb="nav:back"):
    b = InlineKeyboardBuilder()
    for c in CURRENCIES:
        b.button(text=c, callback_data=f"{prefix}:{c}")
    b.button(text="✏️ O'zim yozaman", callback_data=f"{prefix}:custom")
    if back:
        b.button(text="⬅️ Orqaga", callback_data=back_cb)
    b.adjust(3, 1, 1)
    return b.as_markup()


def later_kb(callback_data, back=True, back_cb="nav:back"):
    b = InlineKeyboardBuilder()
    b.button(text="⏳ Keyinroq kiritaman", callback_data=callback_data)
    if back:
        b.button(text="⬅️ Orqaga", callback_data=back_cb)
    b.adjust(1)
    return b.as_markup()


def place_type_kb(prefix="ptype", back_cb="nav:back"):
    b = InlineKeyboardBuilder()
    for code, label in PLACE_TYPES:
        b.button(text=label, callback_data=f"{prefix}:{code}")
    b.button(text="⬅️ Orqaga", callback_data=back_cb)
    b.adjust(1)
    return b.as_markup()


def yes_no_unknown_kb(prefix, back=True, back_cb="nav:back"):
    b = InlineKeyboardBuilder()
    b.button(text="✅ Ha", callback_data=f"{prefix}:yes")
    b.button(text="❌ Yo'q", callback_data=f"{prefix}:no")
    b.button(text="🤷 Bilmayman", callback_data=f"{prefix}:unknown")
    if back:
        b.button(text="⬅️ Orqaga", callback_data=back_cb)
    b.adjust(3, 1)
    return b.as_markup()


def rating_kb(prefix="rating", back_cb="nav:back"):
    b = InlineKeyboardBuilder()
    for i in range(1, 6):
        b.button(text="⭐" * i, callback_data=f"{prefix}:{i}")
    b.button(text="O'tkazib yuborish ⏭", callback_data=f"{prefix}:skip")
    b.button(text="⬅️ Orqaga", callback_data=back_cb)
    b.adjust(1)
    return b.as_markup()


def category_kb(prefix="cat", back_cb="nav:back"):
    b = InlineKeyboardBuilder()
    for code, label in CATEGORIES:
        b.button(text=label, callback_data=f"{prefix}:{code}")
    b.button(text="⬅️ Orqaga", callback_data=back_cb)
    b.adjust(2, 1)
    return b.as_markup()


def expense_currency_kb(budget_currency, city_currency, prefix="expcur", back_cb="nav:back"):
    b = InlineKeyboardBuilder()
    if budget_currency == city_currency:
        b.button(text=budget_currency, callback_data=f"{prefix}:{budget_currency}")
    else:
        b.button(text=f"💱 {city_currency} (shahar)", callback_data=f"{prefix}:{city_currency}")
        b.button(text=f"💰 {budget_currency} (byudjet)", callback_data=f"{prefix}:{budget_currency}")
    b.button(text="⬅️ Orqaga", callback_data=back_cb)
    b.adjust(1)
    return b.as_markup()


def weather_kb(selected, back_cb="nav:back"):
    b = InlineKeyboardBuilder()
    for code, label in WEATHER_OPTIONS:
        mark = "✅ " if code in selected else ""
        b.button(text=f"{mark}{label}", callback_data=f"wopt:{code}")
    b.button(text="📝 Boshqa (o'zim yozaman)", callback_data="wopt:custom")
    b.button(text="✅ Tugatdim", callback_data="wopt:done")
    b.button(text="⬅️ Orqaga", callback_data=back_cb)
    b.adjust(2, 2, 2, 1, 1, 1)
    return b.as_markup()


def places_link_kb(places):
    b = InlineKeyboardBuilder()
    for p in places:
        b.button(text=p["name"], callback_data=f"link_place:{p['id']}")
    b.button(text="Bog'lamaslik ⏭", callback_data="link_place:none")
    add_nav(b, back=True)
    b.adjust(1)
    return b.as_markup()


def type_filter_kb(city_id, types, back_cb="nav:back"):
    b = InlineKeyboardBuilder()
    labels = dict(PLACE_TYPES)
    for t in types:
        b.button(text=labels.get(t, f"📌 {t}"), callback_data=f"places_show:{city_id}:{t}")
    b.button(text="📋 Barchasi", callback_data=f"places_show:{city_id}:all")
    b.button(text="⬅️ Orqaga", callback_data=back_cb)
    b.adjust(1)
    return b.as_markup()


def single_delete_kb(callback_data, back=True, back_cb="nav:back"):
    b = InlineKeyboardBuilder()
    b.button(text="🗑 O'chirish", callback_data=callback_data)
    if back:
        b.button(text="⬅️ Orqaga", callback_data=back_cb)
    b.adjust(1)
    return b.as_markup()


def confirm_kb(yes_cb, no_cb):
    b = InlineKeyboardBuilder()
    b.button(text="✅ Ha, o'chirish", callback_data=yes_cb)
    b.button(text="❌ Bekor qilish", callback_data=no_cb)
    b.adjust(2)
    return b.as_markup()


def trip_card_kb(trip_id):
    b = InlineKeyboardBuilder()
    b.button(text="📍 Joylar", callback_data=f"tc_places:{trip_id}")
    b.button(text="➕ Joy", callback_data=f"tc_place_add:{trip_id}")
    b.button(text="👤 Kontaktlar", callback_data=f"tc_contacts:{trip_id}")
    b.button(text="➕ Kontakt", callback_data=f"tc_contact_add:{trip_id}")
    b.button(text="💰 Xarajatlar", callback_data=f"tc_expenses:{trip_id}")
    b.button(text="➕ Xarajat", callback_data=f"tc_expense_add:{trip_id}")
    b.button(text="📎 Fayllar", callback_data=f"tc_files:{trip_id}")
    b.button(text="➕ Fayl", callback_data=f"tc_file_add:{trip_id}")
    b.button(text="🌤 Ob-havo", callback_data=f"tc_weather:{trip_id}")
    b.button(text="➕ Ob-havo", callback_data=f"tc_weather_add:{trip_id}")
    b.button(text="📔 Kundalik", callback_data=f"tc_diary:{trip_id}")
    b.button(text="➕ Kundalik", callback_data=f"tc_diary_add:{trip_id}")
    b.adjust(2)
    return b.as_markup()


# ---------- Manage keyboards ----------

def manage_root_kb():
    b = InlineKeyboardBuilder()
    b.button(text="🌍 Davlatlar", callback_data="mng_countries")
    add_nav(b, back=False, cancel=True)
    b.adjust(1)
    return b.as_markup()


def manage_list_kb(items, prefix, label_func):
    b = InlineKeyboardBuilder()
    for it in items:
        b.button(text=label_func(it), callback_data=f"{prefix}:{it['id']}")
    add_nav(b, back=True)
    b.adjust(1)
    return b.as_markup()


def manage_country_action_kb(country_id):
    b = InlineKeyboardBuilder()
    b.button(text="✏️ Nomi", callback_data=f"mngco_name:{country_id}")
    b.button(text="🏙 Shaharlar", callback_data=f"mngco_cities:{country_id}")
    b.button(text="🗑 Davlatni o'chirish", callback_data=f"mngco_del:{country_id}")
    add_nav(b, back=True)
    b.adjust(1)
    return b.as_markup()


def manage_city_action_kb(city_id):
    b = InlineKeyboardBuilder()
    b.button(text="✏️ Nomi", callback_data=f"mngci_name:{city_id}")
    b.button(text="🧳 Safarlar", callback_data=f"mngci_trips:{city_id}")
    b.button(text="📍 Joylar", callback_data=f"mngci_places:{city_id}")
    b.button(text="🗑 Shaharni o'chirish", callback_data=f"mngci_del:{city_id}")
    add_nav(b, back=True)
    b.adjust(1)
    return b.as_markup()


def manage_trip_action_kb(trip_id):
    b = InlineKeyboardBuilder()
    b.button(text="✏️ Holati", callback_data=f"mngt_status:{trip_id}")
    b.button(text="✏️ Izoh/sana", callback_data=f"mngt_note:{trip_id}")
    b.button(text="✏️ Byudjet", callback_data=f"mngt_budget:{trip_id}")
    b.button(text="✏️ Shahar valyutasi", callback_data=f"mngt_citycur:{trip_id}")
    b.button(text="✏️ Kurs", callback_data=f"mngt_rate:{trip_id}")
    b.button(text="👤 Kontaktlar", callback_data=f"mngt_contacts:{trip_id}")
    b.button(text="💰 Xarajatlar", callback_data=f"mngt_expenses:{trip_id}")
    b.button(text="📎 Fayllar", callback_data=f"mngt_files:{trip_id}")
    b.button(text="📔 Kundalik", callback_data=f"mngt_diary:{trip_id}")
    b.button(text="🌤 Ob-havo", callback_data=f"mngt_weather:{trip_id}")
    b.button(text="🗑 Safarni o'chirish", callback_data=f"mngt_del:{trip_id}")
    add_nav(b, back=True)
    b.adjust(1)
    return b.as_markup()


def manage_place_action_kb(place_id):
    b = InlineKeyboardBuilder()
    b.button(text="✏️ Narxi", callback_data=f"mngp_price:{place_id}")
    b.button(text="⭐ Reyting", callback_data=f"mngp_rating:{place_id}")
    b.button(text="✏️ Izoh", callback_data=f"mngp_notes:{place_id}")
    b.button(text="🗑 O'chirish", callback_data=f"mngp_del:{place_id}")
    add_nav(b, back=True)
    b.adjust(1)
    return b.as_markup()


def manage_rating_kb(place_id):
    b = InlineKeyboardBuilder()
    for i in range(1, 6):
        b.button(text="⭐" * i, callback_data=f"mngp_rating_set:{place_id}:{i}")
    b.button(text="Baholanmagan", callback_data=f"mngp_rating_set:{place_id}:0")
    add_nav(b, back=True)
    b.adjust(1)
    return b.as_markup()


def manage_expense_action_kb(expense_id):
    b = InlineKeyboardBuilder()
    b.button(text="✏️ Summasi", callback_data=f"mnge_amount:{expense_id}")
    b.button(text="✏️ Izoh", callback_data=f"mnge_note:{expense_id}")
    b.button(text="🗑 O'chirish", callback_data=f"mnge_del:{expense_id}")
    add_nav(b, back=True)
    b.adjust(1)
    return b.as_markup()


def manage_contact_action_kb(contact_id):
    b = InlineKeyboardBuilder()
    b.button(text="✏️ Ma'lumotini o'zgartirish", callback_data=f"mngk_info:{contact_id}")
    b.button(text="🗑 O'chirish", callback_data=f"mngk_del:{contact_id}")
    add_nav(b, back=True)
    b.adjust(1)
    return b.as_markup()


def manage_file_action_kb(file_id):
    b = InlineKeyboardBuilder()
    b.button(text="🗑 O'chirish", callback_data=f"mngf_del:{file_id}")
    add_nav(b, back=True)
    b.adjust(1)
    return b.as_markup()


def manage_diary_action_kb(diary_id):
    b = InlineKeyboardBuilder()
    b.button(text="🗑 O'chirish", callback_data=f"mngd_del:{diary_id}")
    add_nav(b, back=True)
    b.adjust(1)
    return b.as_markup()


def manage_weather_action_kb(weather_id):
    b = InlineKeyboardBuilder()
    b.button(text="🗑 O'chirish", callback_data=f"mngw_del:{weather_id}")
    add_nav(b, back=True)
    b.adjust(1)
    return b.as_markup()


def manage_status_kb(trip_id):
    b = InlineKeyboardBuilder()
    b.button(text="✅ Borgan", callback_data=f"mngt_status_set:{trip_id}:visited")
    b.button(text="🎯 Bormoqchi", callback_data=f"mngt_status_set:{trip_id}:wishlist")
    add_nav(b, back=True)
    b.adjust(2, 1)
    return b.as_markup()


# ---------- Export ----------

def export_scope_kb():
    b = InlineKeyboardBuilder()
    b.button(text="📦 Umumiy (hammasi)", callback_data="exp_scope:all")
    b.button(text="🌍 Ma'lum bir davlat", callback_data="exp_scope:country")
    b.button(text="🏙 Ma'lum bir shahar", callback_data="exp_scope:city")
    b.button(text="🧳 Ma'lum bir safar", callback_data="exp_scope:trip")
    add_nav(b, back=False, cancel=True)
    b.adjust(1)
    return b.as_markup()
