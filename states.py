from aiogram.fsm.state import State, StatesGroup


class TripAdd(StatesGroup):
    select_country = State()
    new_country_name = State()
    select_city = State()
    new_city_name = State()
    status = State()
    budget_currency = State()
    budget_currency_custom = State()
    budget_amount = State()
    city_currency = State()
    city_currency_custom = State()
    exchange_rate = State()
    note = State()


class PlaceAdd(StatesGroup):
    select_country = State()
    select_city = State()
    select_trip = State()
    type = State()
    type_custom = State()
    name = State()
    price = State()
    halal = State()
    rating = State()
    address = State()
    photos = State()
    notes = State()


class ContactAdd(StatesGroup):
    select_country = State()
    select_city = State()
    select_trip = State()
    name = State()
    contact_info = State()
    notes = State()


class ExpenseAdd(StatesGroup):
    select_country = State()
    select_city = State()
    select_trip = State()
    setup_budget_currency = State()
    setup_budget_amount = State()
    setup_city_currency = State()
    setup_exchange_rate = State()
    category = State()
    currency = State()
    amount = State()
    note = State()


class FileAdd(StatesGroup):
    select_country = State()
    select_city = State()
    select_trip = State()
    file = State()
    notes = State()


class WeatherAdd(StatesGroup):
    select_country = State()
    select_city = State()
    select_trip = State()
    conditions = State()
    custom_text = State()


class DiaryAdd(StatesGroup):
    select_country = State()
    select_city = State()
    select_trip = State()
    text = State()


class ManageEdit(StatesGroup):
    text_input = State()


class ExportFlow(StatesGroup):
    select_country = State()
    select_city = State()
    select_trip = State()
