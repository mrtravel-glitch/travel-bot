import secrets

import psycopg2
import psycopg2.extras

from config import DATABASE_URL


def get_conn():
    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = True
    return conn

    def init_db():
    ddl = """
    CREATE TABLE IF NOT EXISTS countries (
        id SERIAL PRIMARY KEY,
        user_id BIGINT NOT NULL,
        name TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS cities (
        id SERIAL PRIMARY KEY,
        country_id INTEGER NOT NULL REFERENCES countries(id) ON DELETE CASCADE,
        name TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS trips (
        id SERIAL PRIMARY KEY,
        city_id INTEGER NOT NULL REFERENCES cities(id) ON DELETE CASCADE,
        status TEXT NOT NULL CHECK (status IN ('visited','wishlist')),
        note TEXT,
        budget_amount NUMERIC,
        budget_currency TEXT,
        city_currency TEXT,
        exchange_rate NUMERIC,
        created_at TIMESTAMP DEFAULT now()
    );
    CREATE TABLE IF NOT EXISTS user_state (
        user_id BIGINT PRIMARY KEY,
        active_trip_id INTEGER
    );
    CREATE TABLE IF NOT EXISTS places (
        id SERIAL PRIMARY KEY,
        city_id INTEGER NOT NULL REFERENCES cities(id) ON DELETE CASCADE,
        name TEXT NOT NULL,
        type TEXT NOT NULL,
        is_halal TEXT,
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
        currency TEXT NOT NULL,
        expense_date TEXT,
        note TEXT
    );
    CREATE TABLE IF NOT EXISTS files (
        id SERIAL PRIMARY KEY,
        trip_id INTEGER NOT NULL REFERENCES trips(id) ON DELETE CASCADE,
        file_id TEXT NOT NULL,
        file_type TEXT NOT NULL DEFAULT 'document',
        file_name TEXT,
        notes TEXT
    );
    CREATE TABLE IF NOT EXISTS diary (
        id SERIAL PRIMARY KEY,
        trip_id INTEGER NOT NULL REFERENCES trips(id) ON DELETE CASCADE,
        entry_date TEXT NOT NULL,
        text TEXT,
        photo_file_id TEXT
    );
    CREATE TABLE IF NOT EXISTS weather_notes (
        id SERIAL PRIMARY KEY,
        trip_id INTEGER NOT NULL REFERENCES trips(id) ON DELETE CASCADE,
        entry_date TEXT NOT NULL,
        conditions TEXT,
        custom_text TEXT
    );
    CREATE TABLE IF NOT EXISTS web_tokens (
        user_id BIGINT PRIMARY KEY,
        token TEXT UNIQUE NOT NULL
    );
    ALTER TABLE cities ADD COLUMN IF NOT EXISTS latitude DOUBLE PRECISION;
    ALTER TABLE cities ADD COLUMN IF NOT EXISTS longitude DOUBLE PRECISION;
    ALTER TABLE cities ADD COLUMN IF NOT EXISTS photo TEXT;
    ALTER TABLE countries ADD COLUMN IF NOT EXISTS photo TEXT;
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(ddl)

def _one(query, params=()):
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(query, params)
            return cur.fetchone()


def _all(query, params=()):
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(query, params)
            return cur.fetchall()


def _run(query, params=()):
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(query, params)
            if cur.description:
                return cur.fetchone()
            return None


# ---------- Web token (sayt uchun shaxsiy havola) ----------

def get_or_create_web_token(user_id):
    row = _one("SELECT token FROM web_tokens WHERE user_id=%s", (user_id,))
    if row:
        return row["token"]
    token = secrets.token_urlsafe(16)
    _run(
        "INSERT INTO web_tokens (user_id, token) VALUES (%s,%s) "
        "ON CONFLICT (user_id) DO UPDATE SET token=EXCLUDED.token",
        (user_id, token),
    )
    return token


def get_user_id_by_token(token):
    row = _one("SELECT user_id FROM web_tokens WHERE token=%s", (token,))
    return row["user_id"] if row else None


# ---------- Countries ----------

def add_country(user_id, name):
    return _run("INSERT INTO countries (user_id, name) VALUES (%s,%s) RETURNING *", (user_id, name))


def find_country_by_name(user_id, name):
    return _one(
        "SELECT * FROM countries WHERE user_id=%s AND lower(trim(name))=lower(trim(%s))",
        (user_id, name),
    )


def get_countries(user_id):
    return _all("SELECT * FROM countries WHERE user_id=%s ORDER BY name", (user_id,))


def get_country(country_id):
    return _one("SELECT * FROM countries WHERE id=%s", (country_id,))


def update_country_name(country_id, name):
    _run("UPDATE countries SET name=%s WHERE id=%s", (name, country_id))


def delete_country(country_id):
    _run("DELETE FROM countries WHERE id=%s", (country_id,))


# ---------- Cities ----------

def add_city(country_id, name):
    return _run("INSERT INTO cities (country_id, name) VALUES (%s,%s) RETURNING *", (country_id, name))


def find_city_by_name(country_id, name):
    return _one(
        "SELECT * FROM cities WHERE country_id=%s AND lower(trim(name))=lower(trim(%s))",
        (country_id, name),
    )


def get_cities(country_id):
    return _all("SELECT * FROM cities WHERE country_id=%s ORDER BY name", (country_id,))


def get_city(city_id):
    return _one("SELECT * FROM cities WHERE id=%s", (city_id,))


def update_city_name(city_id, name):
    _run("UPDATE cities SET name=%s WHERE id=%s", (name, city_id))


def delete_city(city_id):
    _run("DELETE FROM cities WHERE id=%s", (city_id,))


# ---------- Trips (safar) ----------

def add_trip(city_id, status, note=None, budget_amount=None, budget_currency=None,
             city_currency=None, exchange_rate=None):
    return _run(
        "INSERT INTO trips (city_id, status, note, budget_amount, budget_currency, "
        "city_currency, exchange_rate) VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING *",
        (city_id, status, note, budget_amount, budget_currency, city_currency, exchange_rate),
    )


def get_trips(city_id):
    return _all("SELECT * FROM trips WHERE city_id=%s ORDER BY created_at", (city_id,))


def get_trip(trip_id):
    return _one("SELECT * FROM trips WHERE id=%s", (trip_id,))


def update_trip_status(trip_id, status):
    _run("UPDATE trips SET status=%s WHERE id=%s", (status, trip_id))


def update_trip_note(trip_id, note):
    _run("UPDATE trips SET note=%s WHERE id=%s", (note, trip_id))


def update_trip_budget(trip_id, budget_amount, budget_currency):
    _run("UPDATE trips SET budget_amount=%s, budget_currency=%s WHERE id=%s",
         (budget_amount, budget_currency, trip_id))


def update_trip_budget_amount(trip_id, budget_amount):
    _run("UPDATE trips SET budget_amount=%s WHERE id=%s", (budget_amount, trip_id))


def update_trip_city_currency(trip_id, city_currency):
    _run("UPDATE trips SET city_currency=%s WHERE id=%s", (city_currency, trip_id))


def update_trip_exchange_rate(trip_id, exchange_rate):
    _run("UPDATE trips SET exchange_rate=%s WHERE id=%s", (exchange_rate, trip_id))


def delete_trip(trip_id):
    _run("DELETE FROM trips WHERE id=%s", (trip_id,))


# ---------- Active state ----------

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


def get_active_trip_full(user_id):
    trip = get_active_trip(user_id)
    if not trip:
        return None, None, None
    city = get_city(trip["city_id"])
    country = get_country(city["country_id"]) if city else None
    return trip, city, country


# ---------- Places ----------

def add_place(city_id, name, ptype, is_halal, price, rating, address, latitude, longitude, notes):
    return _run(
        "INSERT INTO places (city_id, name, type, is_halal, price, rating, address, "
        "latitude, longitude, notes) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *",
        (city_id, name, ptype, is_halal, price, rating, address, latitude, longitude, notes),
    )


def get_places(city_id, ptype=None):
    if ptype and ptype != "all":
        return _all("SELECT * FROM places WHERE city_id=%s AND type=%s ORDER BY name", (city_id, ptype))
    return _all("SELECT * FROM places WHERE city_id=%s ORDER BY type, name", (city_id,))


def get_place_types(city_id):
    rows = _all("SELECT DISTINCT type FROM places WHERE city_id=%s ORDER BY type", (city_id,))
    return [r["type"] for r in rows]


def get_place(place_id):
    return _one("SELECT * FROM places WHERE id=%s", (place_id,))


def add_place_photo(place_id, photo_file_id):
    _run("INSERT INTO place_photos (place_id, photo_file_id) VALUES (%s,%s)", (place_id, photo_file_id))


def get_place_photos(place_id):
    return _all("SELECT * FROM place_photos WHERE place_id=%s", (place_id,))


def update_place_price(place_id, price):
    _run("UPDATE places SET price=%s WHERE id=%s", (price, place_id))


def update_place_rating(place_id, rating):
    _run("UPDATE places SET rating=%s WHERE id=%s", (rating, place_id))


def update_place_notes(place_id, notes):
    _run("UPDATE places SET notes=%s WHERE id=%s", (notes, place_id))


def delete_place(place_id):
    _run("DELETE FROM places WHERE id=%s", (place_id,))


# ---------- Contacts ----------

def add_contact(trip_id, name, contact_info, notes):
    return _run(
        "INSERT INTO contacts (trip_id, name, contact_info, notes) VALUES (%s,%s,%s,%s) RETURNING *",
        (trip_id, name, contact_info, notes),
    )


def get_contacts(trip_id):
    return _all("SELECT * FROM contacts WHERE trip_id=%s ORDER BY name", (trip_id,))


def get_contact(contact_id):
    return _one("SELECT * FROM contacts WHERE id=%s", (contact_id,))


def update_contact_info(contact_id, contact_info):
    _run("UPDATE contacts SET contact_info=%s WHERE id=%s", (contact_info, contact_id))


def delete_contact(contact_id):
    _run("DELETE FROM contacts WHERE id=%s", (contact_id,))


# ---------- Expenses ----------

def add_expense(trip_id, category, amount, currency, expense_date, note):
    return _run(
        "INSERT INTO expenses (trip_id, category, amount, currency, expense_date, note) "
        "VALUES (%s,%s,%s,%s,%s,%s) RETURNING *",
        (trip_id, category, amount, currency, expense_date, note),
    )


def get_expenses(trip_id):
    return _all("SELECT * FROM expenses WHERE trip_id=%s ORDER BY expense_date, id", (trip_id,))


def get_expense_summary(trip_id):
    return _all(
        "SELECT category, currency, SUM(amount) AS total FROM expenses "
        "WHERE trip_id=%s GROUP BY category, currency ORDER BY category",
        (trip_id,),
    )


def get_expense_totals_by_currency(trip_id):
    return _all(
        "SELECT currency, SUM(amount) AS total FROM expenses WHERE trip_id=%s GROUP BY currency",
        (trip_id,),
    )


def get_expense(expense_id):
    return _one("SELECT * FROM expenses WHERE id=%s", (expense_id,))


def update_expense_amount(expense_id, amount):
    _run("UPDATE expenses SET amount=%s WHERE id=%s", (amount, expense_id))


def update_expense_note(expense_id, note):
    _run("UPDATE expenses SET note=%s WHERE id=%s", (note, expense_id))


def delete_expense(expense_id):
    _run("DELETE FROM expenses WHERE id=%s", (expense_id,))


# ---------- Files ----------

def add_file(trip_id, file_id, file_type, file_name, notes):
    return _run(
        "INSERT INTO files (trip_id, file_id, file_type, file_name, notes) "
        "VALUES (%s,%s,%s,%s,%s) RETURNING *",
        (trip_id, file_id, file_type, file_name, notes),
    )


def get_files(trip_id):
    return _all("SELECT * FROM files WHERE trip_id=%s ORDER BY id", (trip_id,))


def get_file(file_id):
    return _one("SELECT * FROM files WHERE id=%s", (file_id,))


def delete_file(file_id):
    _run("DELETE FROM files WHERE id=%s", (file_id,))


# ---------- Diary ----------

def add_diary(trip_id, entry_date, text, photo_file_id=None):
    return _run(
        "INSERT INTO diary (trip_id, entry_date, text, photo_file_id) VALUES (%s,%s,%s,%s) RETURNING *",
        (trip_id, entry_date, text, photo_file_id),
    )


def get_diary(trip_id):
    return _all("SELECT * FROM diary WHERE trip_id=%s ORDER BY entry_date, id", (trip_id,))


def get_diary_entry(diary_id):
    return _one("SELECT * FROM diary WHERE id=%s", (diary_id,))


def delete_diary_entry(diary_id):
    _run("DELETE FROM diary WHERE id=%s", (diary_id,))


# ---------- Weather notes ----------

def add_weather_note(trip_id, entry_date, conditions, custom_text):
    return _run(
        "INSERT INTO weather_notes (trip_id, entry_date, conditions, custom_text) "
        "VALUES (%s,%s,%s,%s) RETURNING *",
        (trip_id, entry_date, conditions, custom_text),
    )


def get_weather_notes(trip_id):
    return _all("SELECT * FROM weather_notes WHERE trip_id=%s ORDER BY entry_date, id", (trip_id,))


def get_weather_note(weather_id):
    return _one("SELECT * FROM weather_notes WHERE id=%s", (weather_id,))


def delete_weather_note(weather_id):
    _run("DELETE FROM weather_notes WHERE id=%s", (weather_id,))


# ---------- Stats ----------

def get_stats(user_id):
    countries = get_countries(user_id)
    visited = 0
    wishlist_cities = 0
    total_cities = 0
    total_trips = 0
    for c in countries:
        cities = get_cities(c["id"])
        total_cities += len(cities)
        for city in cities:
            trips = get_trips(city["id"])
            total_trips += len(trips)
            for t in trips:
                if t["status"] == "visited":
                    visited += 1
                else:
                    wishlist_cities += 1
    return {
        "countries": len(countries),
        "cities": total_cities,
        "trips": total_trips,
        "visited_trips": visited,
        "wishlist_trips": wishlist_cities,
    }


def get_all_trips_for_user(user_id):
    return _all(
        "SELECT t.*, ci.name AS city_name, co.name AS country_name "
        "FROM trips t JOIN cities ci ON t.city_id=ci.id JOIN countries co ON ci.country_id=co.id "
        "WHERE co.user_id=%s ORDER BY t.created_at",
        (user_id,),
    )


# ---------- Export helpers ----------

def export_countries(user_id):
    return get_countries(user_id)


def export_cities(user_id):
    return _all(
        "SELECT ci.*, co.name AS country_name FROM cities ci "
        "JOIN countries co ON ci.country_id=co.id WHERE co.user_id=%s ORDER BY co.name, ci.name",
        (user_id,),
    )


def export_trips(user_id, country_id=None, city_id=None, trip_id=None):
    q = (
        "SELECT t.*, ci.name AS city_name, co.name AS country_name FROM trips t "
        "JOIN cities ci ON t.city_id=ci.id JOIN countries co ON ci.country_id=co.id "
        "WHERE co.user_id=%s"
    )
    params = [user_id]
    if trip_id:
        q += " AND t.id=%s"
        params.append(trip_id)
    elif city_id:
        q += " AND ci.id=%s"
        params.append(city_id)
    elif country_id:
        q += " AND co.id=%s"
        params.append(country_id)
    q += " ORDER BY co.name, ci.name, t.created_at"
    return _all(q, params)


def export_places(user_id, country_id=None, city_id=None):
    q = (
        "SELECT p.*, ci.name AS city_name, co.name AS country_name FROM places p "
        "JOIN cities ci ON p.city_id=ci.id JOIN countries co ON ci.country_id=co.id "
        "WHERE co.user_id=%s"
    )
    params = [user_id]
    if city_id:
        q += " AND ci.id=%s"
        params.append(city_id)
    elif country_id:
        q += " AND co.id=%s"
        params.append(country_id)
    q += " ORDER BY co.name, ci.name, p.type, p.name"
    return _all(q, params)


def _trip_scoped_export(table, user_id, country_id=None, city_id=None, trip_id=None, extra_cols=""):
    q = (
        f"SELECT x.*{extra_cols}, t.id AS trip_ref, ci.name AS city_name, co.name AS country_name "
        f"FROM {table} x JOIN trips t ON x.trip_id=t.id "
        "JOIN cities ci ON t.city_id=ci.id JOIN countries co ON ci.country_id=co.id "
        "WHERE co.user_id=%s"
    )
    params = [user_id]
    if trip_id:
        q += " AND t.id=%s"
        params.append(trip_id)
    elif city_id:
        q += " AND ci.id=%s"
        params.append(city_id)
    elif country_id:
        q += " AND co.id=%s"
        params.append(country_id)
    q += " ORDER BY co.name, ci.name, t.created_at"
    return _all(q, params)


def export_contacts(user_id, country_id=None, city_id=None, trip_id=None):
    return _trip_scoped_export("contacts", user_id, country_id, city_id, trip_id)


def export_expenses(user_id, country_id=None, city_id=None, trip_id=None):
    return _trip_scoped_export("expenses", user_id, country_id, city_id, trip_id)


def export_diary(user_id, country_id=None, city_id=None, trip_id=None):
    return _trip_scoped_export("diary", user_id, country_id, city_id, trip_id)


def export_weather(user_id, country_id=None, city_id=None, trip_id=None):
    return _trip_scoped_export("weather_notes", user_id, country_id, city_id, trip_id)


def export_files(user_id, country_id=None, city_id=None, trip_id=None):
    return _trip_scoped_export("files", user_id, country_id, city_id, trip_id)

# ---------- Xarita: koordinata va rasmlar ----------
def update_city_coords(city_id, lat, lng):
    _run("UPDATE cities SET latitude=%s, longitude=%s WHERE id=%s", (lat, lng, city_id))

def update_city_photo(city_id, photo):
    _run("UPDATE cities SET photo=%s WHERE id=%s", (photo, city_id))

def update_country_photo(country_id, photo):
    _run("UPDATE countries SET photo=%s WHERE id=%s", (photo, country_id))
