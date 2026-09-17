from contextlib import contextmanager

import psycopg2
from psycopg2.extras import RealDictCursor

from config import DATABASE_URL


def init_db():
    ddl = """
    CREATE TABLE IF NOT EXISTS trips (
        id SERIAL PRIMARY KEY,
        user_id BIGINT NOT NULL,
        country TEXT NOT NULL,
        city TEXT,
        status TEXT NOT NULL CHECK (status IN ('visited','wishlist')),
        start_date TEXT,
        end_date TEXT,
        notes TEXT
    );

    CREATE TABLE IF NOT EXISTS user_state (
        user_id BIGINT PRIMARY KEY,
        active_trip_id INTEGER
    );

    CREATE TABLE IF NOT EXISTS diary (
        id SERIAL PRIMARY KEY,
        trip_id INTEGER NOT NULL REFERENCES trips(id) ON DELETE CASCADE,
        entry_date TEXT NOT NULL,
        text TEXT,
        photo_file_id TEXT
    );

    CREATE TABLE IF NOT EXISTS places (
        id SERIAL PRIMARY KEY,
        trip_id INTEGER NOT NULL REFERENCES trips(id) ON DELETE CASCADE,
        name TEXT NOT NULL,
        type TEXT NOT NULL,
        is_halal BOOLEAN,
        price TEXT,
        rating INTEGER,
        address TEXT,
        link TEXT,
        photo_file_id TEXT,
        notes TEXT
    );

    CREATE TABLE IF NOT EXISTS contacts (
        id SERIAL PRIMARY KEY,
        trip_id INTEGER NOT NULL REFERENCES trips(id) ON DELETE CASCADE,
        name TEXT NOT NULL,
        contact_info TEXT,
        notes TEXT
    );

    CREATE TABLE IF NOT EXISTS expenses (
        id SERIAL PRIMARY KEY,
        trip_id INTEGER NOT NULL REFERENCES trips(id) ON DELETE CASCADE,
        category TEXT NOT NULL,
        amount NUMERIC NOT NULL,
        currency TEXT DEFAULT 'so''m',
        expense_date TEXT,
        note TEXT
    );
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(ddl)


@contextmanager
def get_conn():
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _one(query, params=()):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(query, params)
            return cur.fetchone()


def _all(query, params=()):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(query, params)
            return cur.fetchall()


def _run(query, params=()):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(query, params)


# ---------- Trips ----------

def add_trip(user_id, country, city, status, start_date=None, end_date=None, notes=None):
    row = _one(
        "INSERT INTO trips (user_id, country, city, status, start_date, end_date, notes) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id",
        (user_id, country, city, status, start_date, end_date, notes),
    )
    return row["id"]


def get_trips(user_id, status=None):
    if status:
        return _all("SELECT * FROM trips WHERE user_id=%s AND status=%s ORDER BY id DESC", (user_id, status))
    return _all("SELECT * FROM trips WHERE user_id=%s ORDER BY id DESC", (user_id,))


def get_trip(trip_id):
    return _one("SELECT * FROM trips WHERE id=%s", (trip_id,))


def set_active_trip(user_id, trip_id):
    _run(
        "INSERT INTO user_state (user_id, active_trip_id) VALUES (%s,%s) "
        "ON CONFLICT (user_id) DO UPDATE SET active_trip_id=EXCLUDED.active_trip_id",
        (user_id, trip_id),
    )


def get_active_trip(user_id):
    row = _one("SELECT active_trip_id FROM user_state WHERE user_id=%s", (user_id,))
    if not row or not row["active_trip_id"]:
        return None
    return get_trip(row["active_trip_id"])


# ---------- Diary ----------

def add_diary(trip_id, entry_date, text, photo_file_id=None):
    _run(
        "INSERT INTO diary (trip_id, entry_date, text, photo_file_id) VALUES (%s,%s,%s,%s)",
        (trip_id, entry_date, text, photo_file_id),
    )


def get_diary(trip_id):
    return _all("SELECT * FROM diary WHERE trip_id=%s ORDER BY entry_date DESC", (trip_id,))


# ---------- Places ----------

def add_place(trip_id, name, ptype, is_halal, price, rating, address, link, notes):
    _run(
        "INSERT INTO places (trip_id, name, type, is_halal, price, rating, address, link, notes) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (trip_id, name, ptype, is_halal, price, rating, address, link, notes),
    )


def get_places(trip_id, ptype=None):
    if ptype:
        return _all("SELECT * FROM places WHERE trip_id=%s AND type=%s ORDER BY id DESC", (trip_id, ptype))
    return _all("SELECT * FROM places WHERE trip_id=%s ORDER BY id DESC", (trip_id,))


# ---------- Contacts ----------

def add_contact(trip_id, name, contact_info, notes):
    _run(
        "INSERT INTO contacts (trip_id, name, contact_info, notes) VALUES (%s,%s,%s,%s)",
        (trip_id, name, contact_info, notes),
    )


def get_contacts(trip_id):
    return _all("SELECT * FROM contacts WHERE trip_id=%s ORDER BY id DESC", (trip_id,))


# ---------- Expenses ----------

def add_expense(trip_id, category, amount, currency, expense_date, note):
    _run(
        "INSERT INTO expenses (trip_id, category, amount, currency, expense_date, note) "
        "VALUES (%s,%s,%s,%s,%s,%s)",
        (trip_id, category, amount, currency, expense_date, note),
    )


def get_expenses(trip_id):
    return _all("SELECT * FROM expenses WHERE trip_id=%s ORDER BY id DESC", (trip_id,))


def get_expense_summary(trip_id):
    return _all(
        "SELECT category, SUM(amount) as total, currency FROM expenses "
        "WHERE trip_id=%s GROUP BY category, currency",
        (trip_id,),
    )


# ---------- Stats ----------

def get_stats(user_id):
    visited_count = _one(
        "SELECT COUNT(*) c FROM trips WHERE user_id=%s AND status='visited'", (user_id,)
    )["c"]
    wishlist_count = _one(
        "SELECT COUNT(*) c FROM trips WHERE user_id=%s AND status='wishlist'", (user_id,)
    )["c"]
    total_row = _one(
        "SELECT SUM(e.amount) s FROM expenses e JOIN trips t ON e.trip_id=t.id WHERE t.user_id=%s",
        (user_id,),
    )
    total_spent = float(total_row["s"] or 0)
    places_count = _one(
        "SELECT COUNT(*) c FROM places p JOIN trips t ON p.trip_id=t.id WHERE t.user_id=%s", (user_id,)
    )["c"]
    top_category = _one(
        "SELECT e.category, SUM(e.amount) total FROM expenses e JOIN trips t ON e.trip_id=t.id "
        "WHERE t.user_id=%s GROUP BY e.category ORDER BY total DESC LIMIT 1",
        (user_id,),
    )
    return {
        "visited_count": visited_count,
        "wishlist_count": wishlist_count,
        "total_spent": total_spent,
        "places_count": places_count,
        "top_category": dict(top_category) if top_category else None,
    }
