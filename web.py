import os
import json
import hmac
import hashlib
from urllib.parse import parse_qsl

from aiohttp import web

from config import BOT_TOKEN
import database as db


# ---------- Telegram WebApp initData tekshiruvi ----------

def validate_init_data(init_data: str, bot_token: str):
    """Telegram yuborgan initData haqiqiyligini tekshiradi.
    To'g'ri bo'lsa dict (user, auth_date, ...) qaytaradi, aks holda None."""
    try:
        parsed = dict(parse_qsl(init_data, strict_parsing=True))
    except ValueError:
        return None
    received_hash = parsed.pop("hash", None)
    if not received_hash:
        return None
    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(parsed.items()))
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    calculated_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calculated_hash, received_hash):
        return None
    return parsed


def get_user_id(request) -> int | None:
    init_data = request.headers.get("X-Telegram-Init-Data", "")
    parsed = validate_init_data(init_data, BOT_TOKEN)
    if not parsed:
        return None
    user = json.loads(parsed.get("user", "{}"))
    return user.get("id")


def auth_required(handler):
    async def wrapper(request):
        user_id = get_user_id(request)
        if user_id is None:
            return web.json_response({"error": "unauthorized"}, status=401)
        request["user_id"] = user_id
        return await handler(request)
    return wrapper


# ---------- Oddiy ping (Render/UptimeRobot uchun, o'zgarmadi) ----------

async def handle_ping(request):
    return web.Response(text="Bot ishlayapti ✅")


# ---------- API: umumiy holat ----------

@auth_required
async def api_overview(request):
    user_id = request["user_id"]
    stats = db.get_stats(user_id)
    countries = db.get_countries(user_id)
    result = []
    for c in countries:
        cities = db.get_cities(c["id"])
        city_list = []
        for city in cities:
            trips = db.get_trips(city["id"])
            city_list.append({**city, "trips": trips})
        result.append({**c, "cities": city_list})
    return web.json_response({"stats": stats, "countries": result})


# ---------- API: bitta safar detali ----------

@auth_required
async def api_trip_detail(request):
    trip_id = int(request.match_info["trip_id"])
    trip = db.get_trip(trip_id)
    if not trip:
        return web.json_response({"error": "not_found"}, status=404)
    city = db.get_city(trip["city_id"])
    country = db.get_country(city["country_id"])
    # xavfsizlik: bu safar shu foydalanuvchiga tegishli ekanini tekshirish
    if country["user_id"] != request["user_id"]:
        return web.json_response({"error": "forbidden"}, status=403)

    return web.json_response({
        "trip": trip,
        "city": city,
        "country": country,
        "expenses": db.get_expenses(trip_id),
        "expense_totals": db.get_expense_totals_by_currency(trip_id),
        "diary": db.get_diary(trip_id),
        "contacts": db.get_contacts(trip_id),
        "files": db.get_files(trip_id),
        "weather": db.get_weather_notes(trip_id),
        "places": db.get_places(trip["city_id"]),
    })


# ---------- API: xarajat qo'shish ----------

@auth_required
async def api_add_expense(request):
    trip_id = int(request.match_info["trip_id"])
    trip = db.get_trip(trip_id)
    if not trip:
        return web.json_response({"error": "not_found"}, status=404)
    city = db.get_city(trip["city_id"])
    country = db.get_country(city["country_id"])
    if country["user_id"] != request["user_id"]:
        return web.json_response({"error": "forbidden"}, status=403)

    body = await request.json()
    row = db.add_expense(
        trip_id,
        body.get("category", "boshqa"),
        body["amount"],
        body.get("currency", "UZS"),
        body.get("date", ""),
        body.get("note", ""),
    )
    return web.json_response({"ok": True, "expense": row})


# ---------- API: kundalik yozuv qo'shish ----------

@auth_required
async def api_add_diary(request):
    trip_id = int(request.match_info["trip_id"])
    trip = db.get_trip(trip_id)
    if not trip:
        return web.json_response({"error": "not_found"}, status=404)
    city = db.get_city(trip["city_id"])
    country = db.get_country(city["country_id"])
    if country["user_id"] != request["user_id"]:
        return web.json_response({"error": "forbidden"}, status=403)

    body = await request.json()
    row = db.add_diary(trip_id, body.get("date", ""), body.get("text", ""))
    return web.json_response({"ok": True, "diary": row})


# ---------- Mini App sahifasi (frontend shu yerda, alohida fayl shart emas) ----------

APP_HTML = """<!DOCTYPE html>
<html lang="uz">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>Sayohat Bot</title>
<script src="https://telegram.org/js/telegram-web-app.js"></script>
<style>
  :root{
    --bg: var(--tg-theme-bg-color, #F7F2E7);
    --text: var(--tg-theme-text-color, #24303A);
    --hint: var(--tg-theme-hint-color, #7C8C7D);
    --btn: var(--tg-theme-button-color, #C98A3E);
    --btn-text: var(--tg-theme-button-text-color, #ffffff);
    --card: var(--tg-theme-secondary-bg-color, #EFE7D6);
    padding-top:env(safe-area-inset-top,0px);
    padding-bottom:env(safe-area-inset-bottom,0px);
  }
  *{box-sizing:border-box;}
  body{margin:0; background:var(--bg); color:var(--text); font-family:system-ui,sans-serif; padding:16px;}
  h1{font-size:20px; margin:4px 0 16px;}
  h2{font-size:16px; margin:0 0 8px;}
  .card{background:var(--card); border-radius:14px; padding:14px; margin-bottom:12px;}
  .row{display:flex; justify-content:space-between; padding:6px 0; font-size:14px; border-bottom:1px solid rgba(0,0,0,.06);}
  .row:last-child{border-bottom:none;}
  .hint{color:var(--hint); font-size:13px;}
  .city-btn{display:block; width:100%; text-align:left; background:var(--card); border:none; border-radius:12px; padding:12px; margin-bottom:8px; font-size:15px; color:var(--text);}
  button.primary{background:var(--btn); color:var(--btn-text); border:none; border-radius:10px; padding:10px 14px; font-size:14px; width:100%;}
  input, select{width:100%; padding:10px; border-radius:8px; border:1px solid rgba(0,0,0,.15); margin-bottom:8px; font-size:14px; background:#fff;}
  .back{background:none; border:none; color:var(--hint); font-size:14px; padding:0 0 12px; text-align:left;}
  .stat{display:flex; justify-content:space-between; padding:4px 0;}
</style>
</head>
<body>
<div id="root">Yuklanmoqda…</div>

<script>
const tg = window.Telegram?.WebApp;
tg?.ready();
tg?.expand();

const initData = tg?.initData || "";
const root = document.getElementById("root");

async function api(path, opts = {}) {
  const res = await fetch(path, {
    ...opts,
    headers: {
      "Content-Type": "application/json",
      "X-Telegram-Init-Data": initData,
      ...(opts.headers || {}),
    },
  });
  if (!res.ok) throw new Error("Xatolik: " + res.status);
  return res.json();
}

function fmt(n){ return n === null || n === undefined ? "0" : Number(n).toLocaleString("ru-RU"); }

async function renderOverview() {
  root.innerHTML = "Yuklanmoqda…";
  try {
    const data = await api("/api/overview");
    let html = `<h1>Sayohatlarim</h1>`;
    html += `<div class="card"><div class="stat"><span>Davlatlar</span><b>${data.stats.countries}</b></div>
      <div class="stat"><span>Shaharlar</span><b>${data.stats.cities}</b></div>
      <div class="stat"><span>Safarlar</span><b>${data.stats.trips}</b></div></div>`;

    for (const c of data.countries) {
      html += `<h2>${c.name}</h2>`;
      for (const city of c.cities) {
        for (const trip of city.trips) {
          const label = `${city.name} — ${trip.status === "visited" ? "borilgan ✅" : "istak ro'yxatida ⭐"}`;
          html += `<button class="city-btn" onclick="renderTrip(${trip.id})">${label}</button>`;
        }
      }
    }
    if (data.countries.length === 0) html += `<p class="hint">Hali safar qo'shilmagan. Botda /trip_add buyrug'ini yuboring.</p>`;
    root.innerHTML = html;
  } catch (e) {
    root.innerHTML = `<p class="hint">Ma'lumot yuklanmadi. Botni Telegram ichidan oching.</p>`;
  }
}

async function renderTrip(tripId) {
  root.innerHTML = "Yuklanmoqda…";
  const d = await api(`/api/trip/${tripId}`);
  let html = `<button class="back" onclick="renderOverview()">← Orqaga</button>`;
  html += `<h1>${d.city.name}, ${d.country.name}</h1>`;

  html += `<div class="card"><h2>Xarajatlar</h2>`;
  for (const t of d.expense_totals) html += `<div class="stat"><span>${t.currency}</span><b>${fmt(t.total)}</b></div>`;
  for (const e of d.expenses) html += `<div class="row"><span>${e.category}${e.note ? " · " + e.note : ""}</span><span>${fmt(e.amount)} ${e.currency}</span></div>`;
  html += `
    <select id="exp-cat"><option>ovqat</option><option>transport</option><option>mehmonxona</option><option>ko'ngilochar</option><option>boshqa</option></select>
    <input id="exp-amount" type="number" placeholder="Summa">
    <input id="exp-currency" placeholder="Valyuta (masalan USD)" value="UZS">
    <input id="exp-note" placeholder="Izoh (ixtiyoriy)">
    <button class="primary" onclick="addExpense(${tripId})">Xarajat qo'shish</button>
  </div>`;

  html += `<div class="card"><h2>Kundalik</h2>`;
  for (const e of d.diary) html += `<div class="row"><span>${e.entry_date}</span><span class="hint">${e.text || ""}</span></div>`;
  html += `
    <input id="diary-date" type="date">
    <input id="diary-text" placeholder="Bugun nima bo'ldi?">
    <button class="primary" onclick="addDiary(${tripId})">Yozuv qo'shish</button>
  </div>`;

  if (d.places.length) {
    html += `<div class="card"><h2>Joylar</h2>`;
    for (const p of d.places) html += `<div class="row"><span>${p.name} (${p.type})</span><span>${p.rating ? "★" + p.rating : ""}</span></div>`;
    html += `</div>`;
  }

  if (d.contacts.length) {
    html += `<div class="card"><h2>Aloqalar</h2>`;
    for (const c of d.contacts) html += `<div class="row"><span>${c.name}</span><span class="hint">${c.contact_info || ""}</span></div>`;
    html += `</div>`;
  }

  root.innerHTML = html;
}

async function addExpense(tripId) {
  const amount = document.getElementById("exp-amount").value;
  if (!amount) return;
  await api(`/api/trip/${tripId}/expense`, {
    method: "POST",
    body: JSON.stringify({
      category: document.getElementById("exp-cat").value,
      amount: Number(amount),
      currency: document.getElementById("exp-currency").value || "UZS",
      note: document.getElementById("exp-note").value,
    }),
  });
  renderTrip(tripId);
}

async function addDiary(tripId) {
  const text = document.getElementById("diary-text").value;
  const date = document.getElementById("diary-date").value;
  if (!text || !date) return;
  await api(`/api/trip/${tripId}/diary`, {
    method: "POST",
    body: JSON.stringify({ date, text }),
  });
  renderTrip(tripId);
}

renderOverview();
</script>
</body>
</html>
"""

async def handle_app(request):
    return web.Response(text=APP_HTML, content_type="text/html")


async def start_web_server():
    app = web.Application()
    app.router.add_get("/", handle_ping)
    app.router.add_get("/app", handle_app)
    app.router.add_get("/api/overview", api_overview)
    app.router.add_get("/api/trip/{trip_id}", api_trip_detail)
    app.router.add_post("/api/trip/{trip_id}/expense", api_add_expense)
    app.router.add_post("/api/trip/{trip_id}/diary", api_add_diary)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
