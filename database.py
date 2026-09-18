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
        budget NUMERIC,
        start_date TEXT,
        end_date TEXT,
        notes TEXT
    );
    ALTER TABLE trips ADD COLUMN IF NOT EXISTS budget NUMERIC;

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
        city TEXT,
        is_halal BOOLEAN,
        price TEXT,
        rating INTEGER,
        address TEXT,
        latitude DOUBLE PRECISION,
        longitude DOUBLE PRECISION,
        link TEXT,
        photo_file_id TEXT,
        notes TEXT
    );
    ALTER TABLE places ADD COLUMN IF NOT EXISTS latitude DOUBLE PRECISION;
    ALTER TABLE places ADD COLUMN IF NOT EXISTS longitude DOUBLE PRECISION;
    ALTER TABLE places ADD COLUMN IF NOT EXISTS city TEXT;

    CREATE TABLE IF NOT EXISTS place_photos (
        id SERIAL PRIMARY KEY,
        place_id INTEGER NOT NULL REFERENCES places(id) ON DELETE CASCADE,
        photo_file_id TEXT NOT NULL
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
        place_id INTEGER REFERENCES places(id) ON DELETE SET NULL,
        note TEXT
    );
    ALTER TABLE expenses ADD COLUMN IF NOT EXISTS place_id INTEGER REFERENCES places(id) ON DELETE SET NULL;

    CREATE TABLE IF NOT EXISTS files (
        id SERIAL PRIMARY KEY,
        trip_id INTEGER NOT NULL REFERENCES trips(id) ON DELETE CASCADE,
        file_id TEXT NOT NULL,
        file_type TEXT NOT NULL DEFAULT 'document',
        file_name TEXT,
        notes TEXT
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

def add_trip(user_id, country, city, status, budget=None, start_date=None, end_date=None, notes=None):
    row = _one(
        "INSERT INTO trips (user_id, country, city, status, budget, start_date, end_date, notes) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
        (user_id, country, city, status, budget, start_date, end_date, notes),
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

def add_place(trip_id, name, ptype, city, is_halal, price, rating, address, latitude, longitude, notes):
    row = _one(
        "INSERT INTO places (trip_id, name, type, city, is_halal, price, rating, address, latitude, longitude, "
        "notes) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
        (trip_id, name, ptype, city, is_halal, price, rating, address, latitude, longitude, notes),
    )
    return row["id"]


def get_places(trip_id, city=None, ptype=None):
    query = "SELECT * FROM places WHERE trip_id=%s"
    params = [trip_id]
    if city:
        query += " AND city=%s"
        params.append(city)
    if ptype:
        query += " AND type=%s"
        params.append(ptype)
    query += " ORDER BY id DESC"
    return _all(query, tuple(params))


def get_trip_cities(trip_id):
    rows = _all(
        "SELECT DISTINCT city FROM places WHERE trip_id=%s AND city IS NOT NULL ORDER BY city", (trip_id,)
    )
    return [r["city"] for r in rows]


def add_place_photo(place_id, photo_file_id):
    _run("INSERT INTO place_photos (place_id, photo_file_id) VALUES (%s,%s)", (place_id, photo_file_id))


def get_place_photos(place_id):
    return _all("SELECT * FROM place_photos WHERE place_id=%s ORDER BY id", (place_id,))


# ---------- Contacts ----------

def add_contact(trip_id, name, contact_info, notes):
    _run(
        "INSERT INTO contacts (trip_id, name, contact_info, notes) VALUES (%s,%s,%s,%s)",
        (trip_id, name, contact_info, notes),
    )


def get_contacts(trip_id):
    return _all("SELECT * FROM contacts WHERE trip_id=%s ORDER BY id DESC", (trip_id,))


# ---------- Expenses ----------

def add_expense(trip_id, category, amount, currency, expense_date, place_id, note):
    _run(
        "INSERT INTO expenses (trip_id, category, amount, currency, expense_date, place_id, note) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s)",
        (trip_id, category, amount, currency, expense_date, place_id, note),
    )


def get_expenses(trip_id):
    return _all("SELECT * FROM expenses WHERE trip_id=%s ORDER BY id DESC", (trip_id,))


def get_expense_summary(trip_id):
    return _all(
        "SELECT category, SUM(amount) as total, currency FROM expenses "
        "WHERE trip_id=%s GROUP BY category, currency",
        (trip_id,),
    )


# ---------- Files ----------

def add_file(trip_id, file_id, file_type, file_name, notes):
    _run(
        "INSERT INTO files (trip_id, file_id, file_type, file_name, notes) VALUES (%s,%s,%s,%s,%s)",
        (trip_id, file_id, file_type, file_name, notes),
    )


def get_files(trip_id):
    return _all("SELECT * FROM files WHERE trip_id=%s ORDER BY id DESC", (trip_id,))


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
    most_expensive = _one(
        "SELECT t.country, t.city, SUM(e.amount) total FROM trips t JOIN expenses e ON e.trip_id=t.id "
        "WHERE t.user_id=%s GROUP BY t.id, t.country, t.city ORDER BY total DESC LIMIT 1",
        (user_id,),
    )
    cheapest = _one(
        "SELECT t.country, t.city, SUM(e.amount) total FROM trips t JOIN expenses e ON e.trip_id=t.id "
        "WHERE t.user_id=%s GROUP BY t.id, t.country, t.city ORDER BY total ASC LIMIT 1",
        (user_id,),
    )
    return {
        "visited_count": visited_count,
        "wishlist_count": wishlist_count,
        "total_spent": total_spent,
        "places_count": places_count,
        "top_category": dict(top_category) if top_category else None,
        "most_expensive": dict(most_expensive) if most_expensive else None,
        "cheapest": dict(cheapest) if cheapest else None,
    }
