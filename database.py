from contextlib import contextmanager

import psycopg2
from psycopg2.extras import RealDictCursor

from config import DATABASE_URL


def init_db():
    ddl = """
    CREATE TABLE IF NOT EXISTS countries (
        id SERIAL PRIMARY KEY,
        user_id BIGINT NOT NULL,
        name TEXT NOT NULL,
        status TEXT NOT NULL CHECK (status IN ('visited','wishlist')),
        budget NUMERIC,
        budget_period TEXT,
        notes TEXT
    );

    CREATE TABLE IF NOT EXISTS cities (
        id SERIAL PRIMARY KEY,
        country_id INTEGER NOT NULL REFERENCES countries(id) ON DELETE CASCADE,
        name TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS user_state (
        user_id BIGINT PRIMARY KEY,
        active_country_id INTEGER,
        active_city_id INTEGER
    );

    CREATE TABLE IF NOT EXISTS diary (
        id SERIAL PRIMARY KEY,
        city_id INTEGER NOT NULL REFERENCES cities(id) ON DELETE CASCADE,
        entry_date TEXT NOT NULL,
        text TEXT,
        photo_file_id TEXT
    );

    CREATE TABLE IF NOT EXISTS places (
        id SERIAL PRIMARY KEY,
        city_id INTEGER NOT NULL REFERENCES cities(id) ON DELETE CASCADE,
        name TEXT NOT NULL,
        type TEXT NOT NULL,
        is_halal BOOLEAN,
        price TEXT,
        rating INTEGER,
        address TEXT,
        latitude DOUBLE PRECISION,
        longitude DOUBLE PRECISION,
        notes TEXT
    );

    CREATE TABLE IF NOT EXISTS place_photos (
        id SERIAL PRIMARY KEY,
        place_id INTEGER NOT NULL REFERENCES places(id) ON DELETE CASCADE,
        photo_file_id TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS contacts (
        id SERIAL PRIMARY KEY,
        city_id INTEGER NOT NULL REFERENCES cities(id) ON DELETE CASCADE,
        name TEXT NOT NULL,
        contact_info TEXT,
        notes TEXT
    );

    CREATE TABLE IF NOT EXISTS expenses (
        id SERIAL PRIMARY KEY,
        city_id INTEGER NOT NULL REFERENCES cities(id) ON DELETE CASCADE,
        category TEXT NOT NULL,
        amount NUMERIC NOT NULL,
        currency TEXT DEFAULT 'so''m',
        expense_date TEXT,
        place_id INTEGER REFERENCES places(id) ON DELETE SET NULL,
        note TEXT
    );

    CREATE TABLE IF NOT EXISTS files (
        id SERIAL PRIMARY KEY,
        city_id INTEGER NOT NULL REFERENCES cities(id) ON DELETE CASCADE,
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


# ---------- Countries ----------

def add_country(user_id, name, status, budget=None, budget_period=None, notes=None):
    row = _one(
        "INSERT INTO countries (user_id, name, status, budget, budget_period, notes) "
        "VALUES (%s,%s,%s,%s,%s,%s) RETURNING id",
        (user_id, name, status, budget, budget_period, notes),
    )
    return row["id"]


def find_country_by_name(user_id, name):
    return _one(
        "SELECT * FROM countries WHERE user_id=%s AND LOWER(name)=LOWER(%s) LIMIT 1",
        (user_id, name.strip()),
    )


def get_countries(user_id, status=None):
    if status:
        return _all("SELECT * FROM countries WHERE user_id=%s AND status=%s ORDER BY id DESC", (user_id, status))
    return _all("SELECT * FROM countries WHERE user_id=%s ORDER BY id DESC", (user_id,))


def get_country(country_id):
    return _one("SELECT * FROM countries WHERE id=%s", (country_id,))


# ---------- Cities ----------

def add_city(country_id, name):
    row = _one("INSERT INTO cities (country_id, name) VALUES (%s,%s) RETURNING id", (country_id, name))
    return row["id"]


def find_city_by_name(country_id, name):
    return _one(
        "SELECT * FROM cities WHERE country_id=%s AND LOWER(name)=LOWER(%s) LIMIT 1",
        (country_id, name.strip()),
    )


def get_cities(country_id):
    return _all("SELECT * FROM cities WHERE country_id=%s ORDER BY id", (country_id,))


def get_city(city_id):
    return _one("SELECT * FROM cities WHERE id=%s", (city_id,))


# ---------- Active state ----------

def set_active(user_id, country_id, city_id=None):
    _run(
        "INSERT INTO user_state (user_id, active_country_id, active_city_id) VALUES (%s,%s,%s) "
        "ON CONFLICT (user_id) DO UPDATE SET active_country_id=EXCLUDED.active_country_id, "
        "active_city_id=EXCLUDED.active_city_id",
        (user_id, country_id, city_id),
    )


def get_active_country(user_id):
    row = _one("SELECT active_country_id FROM user_state WHERE user_id=%s", (user_id,))
    if not row or not row["active_country_id"]:
        return None
    return get_country(row["active_country_id"])


def get_active_city(user_id):
    row = _one("SELECT active_city_id FROM user_state WHERE user_id=%s", (user_id,))
    if not row or not row["active_city_id"]:
        return None
    return get_city(row["active_city_id"])


# ---------- Diary ----------

def add_diary(city_id, entry_date, text, photo_file_id=None):
    _run(
        "INSERT INTO diary (city_id, entry_date, text, photo_file_id) VALUES (%s,%s,%s,%s)",
        (city_id, entry_date, text, photo_file_id),
    )


def get_diary(city_id):
    return _all("SELECT * FROM diary WHERE city_id=%s ORDER BY entry_date DESC", (city_id,))


# ---------- Places ----------

def add_place(city_id, name, ptype, is_halal, price, rating, address, latitude, longitude, notes):
    row = _one(
        "INSERT INTO places (city_id, name, type, is_halal, price, rating, address, latitude, longitude, notes) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
        (city_id, name, ptype, is_halal, price, rating, address, latitude, longitude, notes),
    )
    return row["id"]


def get_places(city_id, ptype=None):
    if ptype:
        return _all("SELECT * FROM places WHERE city_id=%s AND type=%s ORDER BY id DESC", (city_id, ptype))
    return _all("SELECT * FROM places WHERE city_id=%s ORDER BY id DESC", (city_id,))


def find_place_by_name(city_id, name):
    return _one(
        "SELECT * FROM places WHERE city_id=%s AND LOWER(name)=LOWER(%s) LIMIT 1",
        (city_id, name.strip()),
    )


def add_place_photo(place_id, photo_file_id):
    _run("INSERT INTO place_photos (place_id, photo_file_id) VALUES (%s,%s)", (place_id, photo_file_id))


def get_place_photos(place_id):
    return _all("SELECT * FROM place_photos WHERE place_id=%s ORDER BY id", (place_id,))


# ---------- Contacts ----------

def add_contact(city_id, name, contact_info, notes):
    _run(
        "INSERT INTO contacts (city_id, name, contact_info, notes) VALUES (%s,%s,%s,%s)",
        (city_id, name, contact_info, notes),
    )


def get_contacts(city_id):
    return _all("SELECT * FROM contacts WHERE city_id=%s ORDER BY id DESC", (city_id,))


# ---------- Expenses ----------

def add_expense(city_id, category, amount, currency, expense_date, place_id, note):
    _run(
        "INSERT INTO expenses (city_id, category, amount, currency, expense_date, place_id, note) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s)",
        (city_id, category, amount, currency, expense_date, place_id, note),
    )


def get_expenses(city_id):
    return _all("SELECT * FROM expenses WHERE city_id=%s ORDER BY id DESC", (city_id,))


def get_expense_summary(city_id):
    return _all(
        "SELECT category, SUM(amount) as total, currency FROM expenses "
        "WHERE city_id=%s GROUP BY category, currency",
        (city_id,),
    )


def get_country_expense_total(country_id):
    row = _one(
        "SELECT SUM(e.amount) s FROM expenses e JOIN cities ci ON e.city_id=ci.id WHERE ci.country_id=%s",
        (country_id,),
    )
    return float(row["s"] or 0)


# ---------- Files ----------

def add_file(city_id, file_id, file_type, file_name, notes):
    _run(
        "INSERT INTO files (city_id, file_id, file_type, file_name, notes) VALUES (%s,%s,%s,%s,%s)",
        (city_id, file_id, file_type, file_name, notes),
    )


def get_files(city_id):
    return _all("SELECT * FROM files WHERE city_id=%s ORDER BY id DESC", (city_id,))


# ---------- Stats ----------

def get_stats(user_id):
    visited_count = _one(
        "SELECT COUNT(*) c FROM countries WHERE user_id=%s AND status='visited'", (user_id,)
    )["c"]
    wishlist_count = _one(
        "SELECT COUNT(*) c FROM countries WHERE user_id=%s AND status='wishlist'", (user_id,)
    )["c"]
    total_row = _one(
        "SELECT SUM(e.amount) s FROM expenses e JOIN cities ci ON e.city_id=ci.id "
        "JOIN countries co ON ci.country_id=co.id WHERE co.user_id=%s",
        (user_id,),
    )
    total_spent = float(total_row["s"] or 0)
    places_count = _one(
        "SELECT COUNT(*) c FROM places p JOIN cities ci ON p.city_id=ci.id "
        "JOIN countries co ON ci.country_id=co.id WHERE co.user_id=%s",
        (user_id,),
    )["c"]
    top_category = _one(
        "SELECT e.category, SUM(e.amount) total FROM expenses e JOIN cities ci ON e.city_id=ci.id "
        "JOIN countries co ON ci.country_id=co.id WHERE co.user_id=%s "
        "GROUP BY e.category ORDER BY total DESC LIMIT 1",
        (user_id,),
    )
    most_expensive = _one(
        "SELECT co.name, SUM(e.amount) total FROM expenses e JOIN cities ci ON e.city_id=ci.id "
        "JOIN countries co ON ci.country_id=co.id WHERE co.user_id=%s "
        "GROUP BY co.id, co.name ORDER BY total DESC LIMIT 1",
        (user_id,),
    )
    cheapest = _one(
        "SELECT co.name, SUM(e.amount) total FROM expenses e JOIN cities ci ON e.city_id=ci.id "
        "JOIN countries co ON ci.country_id=co.id WHERE co.user_id=%s "
        "GROUP BY co.id, co.name ORDER BY total ASC LIMIT 1",
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
