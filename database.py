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
        notes TEXT,
        budget_currency TEXT DEFAULT 'UZS'
    );

    CREATE TABLE IF NOT EXISTS cities (
        id SERIAL PRIMARY KEY,
        country_id INTEGER NOT NULL REFERENCES countries(id) ON DELETE CASCADE,
        name TEXT NOT NULL,
        budget NUMERIC,
        budget_period TEXT,
        budget_currency TEXT DEFAULT 'UZS'
    );

    CREATE TABLE IF NOT EXISTS schema_migrations (
        name TEXT PRIMARY KEY
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
        currency TEXT DEFAULT 'UZS',
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

    CREATE TABLE IF NOT EXISTS weather_log (
        id SERIAL PRIMARY KEY,
        city_id INTEGER NOT NULL REFERENCES cities(id) ON DELETE CASCADE,
        log_date TEXT NOT NULL,
        weather_type TEXT NOT NULL,
        temp NUMERIC,
        note TEXT
    );

    -- Eski bazalar uchun: har safar xavfsiz ishlaydi, malumotlarni ochirmaydi
    ALTER TABLE countries ADD COLUMN IF NOT EXISTS budget_currency TEXT DEFAULT 'UZS';
    UPDATE countries SET budget_currency='UZS' WHERE budget_currency IS NULL;
    ALTER TABLE cities ADD COLUMN IF NOT EXISTS budget NUMERIC;
    ALTER TABLE cities ADD COLUMN IF NOT EXISTS budget_period TEXT;
    ALTER TABLE cities ADD COLUMN IF NOT EXISTS budget_currency TEXT DEFAULT 'UZS';
    UPDATE expenses SET currency='UZS' WHERE currency IS NULL OR currency='so''m';
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(ddl)
            # Eski davlat byudjetini bir marta shaharga koshamiz (faqat 1 ta shahari bor davlatlar uchun;
            # bir nechta shahari borlarini foydalanuvchi /budget orqali ozi taqsimlaydi)
            cur.execute("SELECT 1 FROM schema_migrations WHERE name=%s", ("city_budget_v1",))
            if not cur.fetchone():
                cur.execute(
                    "UPDATE cities SET budget=co.budget, budget_period=co.budget_period, "
                    "budget_currency=COALESCE(co.budget_currency, 'UZS') "
                    "FROM countries co WHERE cities.country_id=co.id AND cities.budget IS NULL "
                    "AND co.budget IS NOT NULL "
                    "AND (SELECT COUNT(*) FROM cities c2 WHERE c2.country_id=co.id) = 1"
                )
                cur.execute("INSERT INTO schema_migrations (name) VALUES (%s)", ("city_budget_v1",))


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

def add_country(user_id, name, status, notes=None):
    row = _one(
        "INSERT INTO countries (user_id, name, status, notes) VALUES (%s,%s,%s,%s) RETURNING id",
        (user_id, name, status, notes),
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


# ---------- Egalik tekshiruvi (boshqa foydalanuvchi ID'sidan himoya) ----------

def get_country_owned(user_id, country_id):
    return _one("SELECT * FROM countries WHERE id=%s AND user_id=%s", (country_id, user_id))


def get_city_owned(user_id, city_id):
    return _one(
        "SELECT ci.* FROM cities ci JOIN countries co ON ci.country_id=co.id "
        "WHERE ci.id=%s AND co.user_id=%s",
        (city_id, user_id),
    )


def get_place_owned(user_id, place_id):
    return _one(
        "SELECT p.* FROM places p JOIN cities ci ON p.city_id=ci.id "
        "JOIN countries co ON ci.country_id=co.id WHERE p.id=%s AND co.user_id=%s",
        (place_id, user_id),
    )


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


def set_city_budget(city_id, budget, currency, period):
    """Shahar byudjetini belgilaydi. budget=None bo'lsa byudjet olib tashlanadi."""
    _run(
        "UPDATE cities SET budget=%s, budget_currency=%s, budget_period=%s WHERE id=%s",
        (budget, currency or "UZS", period, city_id),
    )


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
    return _all("SELECT * FROM diary WHERE city_id=%s ORDER BY entry_date DESC, id DESC", (city_id,))


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


def get_expenses(city_id, limit=50):
    return _all(
        "SELECT e.*, p.name AS place_name FROM expenses e LEFT JOIN places p ON e.place_id=p.id "
        "WHERE e.city_id=%s ORDER BY e.id DESC LIMIT %s",
        (city_id, limit),
    )


def get_expense_summary(city_id):
    return _all(
        "SELECT category, SUM(amount) AS total, currency FROM expenses "
        "WHERE city_id=%s GROUP BY category, currency ORDER BY currency, SUM(amount) DESC",
        (city_id,),
    )


def get_city_expense_totals(city_id):
    return _all(
        "SELECT currency, SUM(amount) AS total FROM expenses WHERE city_id=%s "
        "GROUP BY currency ORDER BY currency",
        (city_id,),
    )


def get_country_expense_totals(country_id):
    return _all(
        "SELECT e.currency, SUM(e.amount) AS total FROM expenses e JOIN cities ci ON e.city_id=ci.id "
        "WHERE ci.country_id=%s GROUP BY e.currency ORDER BY e.currency",
        (country_id,),
    )


# ---------- Weather log ----------

def add_weather(city_id, log_date, condition, temp, note):
    _run(
        "INSERT INTO weather_log (city_id, log_date, weather_type, temp, note) VALUES (%s,%s,%s,%s,%s)",
        (city_id, log_date, condition, temp, note),
    )


def get_weather_log(city_id, limit=10):
    return _all(
        "SELECT * FROM weather_log WHERE city_id=%s ORDER BY log_date DESC, id DESC LIMIT %s",
        (city_id, limit),
    )


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
    places_count = _one(
        "SELECT COUNT(*) c FROM places p JOIN cities ci ON p.city_id=ci.id "
        "JOIN countries co ON ci.country_id=co.id WHERE co.user_id=%s",
        (user_id,),
    )["c"]
    base = (
        "FROM expenses e JOIN cities ci ON e.city_id=ci.id "
        "JOIN countries co ON ci.country_id=co.id WHERE co.user_id=%s "
    )
    totals = _all(
        "SELECT e.currency, SUM(e.amount) AS total " + base + "GROUP BY e.currency ORDER BY e.currency",
        (user_id,),
    )
    by_category = _all(
        "SELECT e.currency, e.category, SUM(e.amount) AS total " + base + "GROUP BY e.currency, e.category",
        (user_id,),
    )
    by_country = _all(
        "SELECT co.id, co.name, e.currency, SUM(e.amount) AS total " + base
        + "GROUP BY co.id, co.name, e.currency",
        (user_id,),
    )
    return {
        "visited_count": visited_count,
        "wishlist_count": wishlist_count,
        "places_count": places_count,
        "totals": totals,
        "by_category": by_category,
        "by_country": by_country,
    }
