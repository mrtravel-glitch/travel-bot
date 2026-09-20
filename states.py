from aiogram.fsm.state import State, StatesGroup


class Pick(StatesGroup):
    """Kundalik/kontakt/fayl/xarajat/ob-havo uchun umumiy davlat -> shahar tanlash."""
    country = State()
    new_country_name = State()
    new_country_status = State()
    city = State()
    new_city_name = State()


class TripAdd(StatesGroup):
    select_country = State()
    new_country_name = State()
    status = State()
    budget = State()
    budget_currency = State()
    budget_currency_other = State()
    budget_period = State()
    notes = State()
    select_city = State()
    new_city_name = State()


class TripsNewCity(StatesGroup):
    name = State()


class DiaryAdd(StatesGroup):
    text = State()


class PlaceAdd(StatesGroup):
    name = State()
    country = State()
    new_country_name = State()
    new_country_status = State()
    city = State()
    new_city_name = State()
    type = State()
    halal = State()
    price = State()
    rating = State()
    location = State()
    photos = State()
    notes = State()


class ContactAdd(StatesGroup):
    name = State()
    contact_info = State()
    notes = State()


class ExpenseAdd(StatesGroup):
    category = State()
    amount = State()
    currency = State()
    currency_other = State()
    place = State()
    note = State()


class FileAdd(StatesGroup):
    file = State()
    notes = State()


class WeatherAdd(StatesGroup):
    date = State()
    date_custom = State()
    condition = State()
    temp = State()
    note = State()
