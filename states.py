from aiogram.fsm.state import State, StatesGroup


class TripAdd(StatesGroup):
    country = State()
    city = State()
    status = State()
    notes = State()


class DiaryAdd(StatesGroup):
    text = State()


class PlaceAdd(StatesGroup):
    name = State()
    type = State()
    halal = State()
    price = State()
    rating = State()
    address = State()
    notes = State()


class ContactAdd(StatesGroup):
    name = State()
    contact_info = State()
    notes = State()


class ExpenseAdd(StatesGroup):
    category = State()
    amount = State()
    note = State()
