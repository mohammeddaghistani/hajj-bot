import telebot
import sqlite3
import os, re, json, time, logging, http.server, socketserver, sys, threading, urllib.request
from datetime import datetime
from google.oauth2.service_account import Credentials
import gspread

# ─────────── LOCAL .env ───────────

_env = os.path.join(os.path.dirname(__file__), ".env")
if os.path.exists(_env):
    with open(_env) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

# ─────────── ENVIRONMENT ───────────

NUSUK_TOKEN = os.environ.get("NUSUK_BOT_TOKEN") or os.environ.get("BOT_TOKEN", "")
ROOM_TOKEN  = os.environ.get("ROOM_BOT_TOKEN") or os.environ.get("BOT_TOKEN", "")
SHEET_ID    = os.environ.get("SHEET_ID", "1ct8MGpZi_3qE4EIfftmje9w_3HOX4HR33ffl6YRB054")
PORT        = int(os.environ.get("PORT", 8080))
RENDER_URL  = os.environ.get("RENDER_EXTERNAL_URL", "").rstrip("/")
GS_KEY      = os.environ.get("GOOGLE_SHEETS_KEY", "{}")
DB_PATH     = os.path.join(os.path.dirname(__file__), "nusuk.db")

# ─────────── LOGGING ───────────

logging.basicConfig(level=logging.INFO, format="%(asctime)s  [%(levelname)s]  %(message)s")
log = logging.getLogger("bot")

# ─────────── NUSUK BOT ───────────

if NUSUK_TOKEN:
    try:
        nusuk_bot = telebot.TeleBot(NUSUK_TOKEN)
    except Exception as e:
        log.error("Nusuk bot init failed: %s", e); sys.exit(1)
else:
    log.error("NUSUK_BOT_TOKEN not set"); sys.exit(1)

# ─────────── DATABASE ───────────

try:
    c = sqlite3.connect(DB_PATH)
    c.execute("CREATE TABLE IF NOT EXISTS requests (id INTEGER PRIMARY KEY AUTOINCREMENT, passport TEXT NOT NULL, status TEXT, hotel TEXT, floor TEXT, room TEXT, employee TEXT, date TEXT)")
    c.close()
    log.info("DB ready")
except Exception as e:
    log.warning("DB init: %s", e)

# ─────────── NUSUK HANDLERS ───────────

DIV = "▬" * 30

def main_menu(chat_id):
    mk = telebot.types.InlineKeyboardMarkup(row_width=2)
    mk.add(
        telebot.types.InlineKeyboardButton("1️⃣ طلب جديد", callback_data="new"),
        telebot.types.InlineKeyboardButton("2️⃣ العدد", callback_data="count"),
        telebot.types.InlineKeyboardButton("3️⃣ آخر الطلبات", callback_data="history"),
        telebot.types.InlineKeyboardButton("4️⃣ إحصائيات", callback_data="stats"),
    )
    nusuk_bot.send_message(chat_id,
        f"*Nusuk Card System*\n*نظام بطاقات نسك*\n\n{DIV}\n\n"
        f"1️⃣ طلب جديد\n2️⃣ العدد\n3️⃣ آخر ١٠\n4️⃣ إحصائيات\n\n{DIV}",
        parse_mode="Markdown", reply_markup=mk)

state = {}

@nusuk_bot.callback_query_handler(func=lambda c: c.data in ("new","count","history","stats"))
def cb(c):
    fn = {"new": start_req, "count": cmd_count, "history": cmd_history, "stats": cmd_stats}[c.data]
    fn(c.message)
    nusuk_bot.answer_callback_query(c.id)

@nusuk_bot.message_handler(commands=["start","help","menu"])
def cmd_start(m):
    main_menu(m.chat.id)

@nusuk_bot.message_handler(commands=["new"])
def start_req(m=None):
    cid = m.chat.id
    state[cid] = {"step": "passport"}
    nusuk_bot.send_message(cid, f"🛂 *الخطوة 1/5 — جواز السفر*\nأرسل رقم الجواز\nمثال: `G3386134`\n\n`رجوع` للإلغاء", parse_mode="Markdown")
start_req = start_req

@nusuk_bot.message_handler(func=lambda m: state.get(m.chat.id,{}).get("step")=="passport")
def get_pass(m):
    cid = m.chat.id; txt = m.text.strip().upper()
    if txt in ("الغاء","إلغاء","cancel","رجوع","back"): del state[cid]; main_menu(cid); return
    if not re.match(r"^[A-Z]\d{6,9}$", txt):
        nusuk_bot.reply_to(m, "❌ صيغة خاطئة. مثال: `G3386134`", parse_mode="Markdown"); return
    state[cid]["passport"] = txt; state[cid]["step"] = "status"
    mk = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True, row_width=2)
    mk.add("📭 لم يستلم", "🔄 بدل فاقد")
    nusuk_bot.reply_to(m, "📌 *الخطوة 2/5 — الحالة*\nاختر:", reply_markup=mk, parse_mode="Markdown")

@nusuk_bot.message_handler(func=lambda m: state.get(m.chat.id,{}).get("step")=="status")
def get_status(m):
    cid = m.chat.id; txt = m.text.strip()
    if txt in ("الغاء","إلغاء","cancel","رجوع","back"): del state[cid]; main_menu(cid); return
    if "لم يستلم" in txt: state[cid]["status"] = "not_received"
    elif "فاقد" in txt or "بدل" in txt: state[cid]["status"] = "lost"
    else: nusuk_bot.reply_to(m, "❌ استخدم الأزرار"); return
    state[cid]["step"] = "hotel"
    nusuk_bot.reply_to(m, "🏨 *الخطوة 3/5 — السكن*\nأرسل اسم السكن:", parse_mode="Markdown", reply_markup=telebot.types.ReplyKeyboardRemove())

@nusuk_bot.message_handler(func=lambda m: state.get(m.chat.id,{}).get("step")=="hotel")
def get_hotel(m):
    cid = m.chat.id; txt = m.text.strip()
    if txt in ("الغاء","إلغاء","cancel","رجوع","back"): del state[cid]; main_menu(cid); return
    if not txt: nusuk_bot.reply_to(m, "❌ أرسل الاسم"); return
    state[cid]["hotel"] = txt; state[cid]["step"] = "floor"
    nusuk_bot.reply_to(m, "📶 *الخطوة 4/5 — الدور*\nأرسل رقم الدور:", parse_mode="Markdown")

@nusuk_bot.message_handler(func=lambda m: state.get(m.chat.id,{}).get("step")=="floor")
def get_floor(m):
    cid = m.chat.id; txt = m.text.strip()
    if txt in ("الغاء","إلغاء","cancel","رجوع","back"): del state[cid]; main_menu(cid); return
    if not txt.isdigit(): nusuk_bot.reply_to(m, "❌ أدخل رقماً"); return
    state[cid]["floor"] = txt; state[cid]["step"] = "room"
    nusuk_bot.reply_to(m, "🚪 *الخطوة 5/5 — الغرفة*\nأرسل رقم الغرفة:", parse_mode="Markdown")

@nusuk_bot.message_handler(func=lambda m: state.get(m.chat.id,{}).get("step")=="room")
def get_room(m):
    cid = m.chat.id; txt = m.text.strip()
    if txt in ("الغاء","إلغاء","cancel","رجوع","back"): del state[cid]; main_menu(cid); return
    if not txt: nusuk_bot.reply_to(m, "❌ أدخل رقم الغرفة"); return
    s = state[cid]
    s["room"] = txt; s["employee"] = f"{m.from_user.first_name or ''} {m.from_user.last_name or ''}".strip()
    s["date"] = datetime.now().strftime("%Y-%m-%d %H:%M"); s["step"] = "confirm"
    st = "لم يستلم" if s["status"]=="not_received" else "بدل فاقد"
    nusuk_bot.reply_to(m,
        f"📋 *تأكيد*\n\n{DIV}\n"
        f"🛂 جواز: `{s['passport']}`\n📌 حالة: {st}\n🏨 سكن: {s['hotel']}\n📶 دور: {s['floor']}\n🚪 غرفة: {s['room']}\n👤 موظف: {s['employee']}\n📅 تاريخ: {s['date']}\n{DIV}\n\n"
        "✅ أرسل `تم` للحفظ\n❌ `إلغاء` للإلغاء",
        parse_mode="Markdown")

@nusuk_bot.message_handler(func=lambda m: state.get(m.chat.id,{}).get("step")=="confirm")
def confirm(m):
    cid = m.chat.id; txt = m.text.strip()
    if txt in ("الغاء","إلغاء","cancel","رجوع","back","لا"): del state[cid]; main_menu(cid); return
    if txt in ("تم","تأكيد","confirm","yes","نعم"):
        s = state.pop(cid)
        try:
            c = sqlite3.connect(DB_PATH)
            c.execute("INSERT INTO requests (passport,status,hotel,floor,room,employee,date) VALUES (?,?,?,?,?,?,?)",
                      (s["passport"],s["status"],s["hotel"],s["floor"],s["room"],s["employee"],s["date"]))
            c.commit(); c.close()
        except Exception as e:
            log.warning("DB insert: %s", e)
        try:
            k = json.loads(GS_KEY)
            if k:
                gs = gspread.authorize(Credentials.from_service_account_info(k, scopes=["https://www.googleapis.com/auth/spreadsheets"])).open_by_key(SHEET_ID).sheet1
                gs.append_row([s["date"],s["passport"],"لم يستلم" if s["status"]=="not_received" else "بدل فاقد",s["hotel"],s["floor"],s["room"],s["employee"]])
        except Exception as e:
            log.warning("Sheets append: %s", e)
        nusuk_bot.reply_to(m, f"✅ *تم الحفظ!*\n{DIV}", parse_mode="Markdown")
        main_menu(cid)
    else:
        nusuk_bot.reply_to(m, "أرسل `تم` أو `إلغاء`", parse_mode="Markdown")

@nusuk_bot.message_handler(commands=["count"])
def cmd_count(m=None):
    try:
        c = sqlite3.connect(DB_PATH)
        n = c.execute("SELECT COUNT(*) FROM requests").fetchone()[0]; c.close()
    except: n = 0
    txt = f"📊 *إجمالي الطلبات:* `{n}`"
    if m: nusuk_bot.reply_to(m, txt, parse_mode="Markdown")

@nusuk_bot.message_handler(commands=["history"])
def cmd_history(m=None):
    try:
        c = sqlite3.connect(DB_PATH)
        rows = c.execute("SELECT passport,status,hotel,floor,room,date FROM requests ORDER BY id DESC LIMIT 10").fetchall(); c.close()
    except: rows = []
    if not rows: nusuk_bot.reply_to(m, "📭 لا توجد طلبات", parse_mode="Markdown"); return
    lines = ["🗂 *آخر ١٠:*\n"]
    for r in rows:
        st = "لم يستلم" if r[1]=="not_received" else "بدل فاقد"
        lines.append(f"`{r[0]}` {st}\n  🏨{r[2]} | F{r[3]} R{r[4]} | {r[5]}")
    nusuk_bot.reply_to(m, "\n".join(lines), parse_mode="Markdown")

@nusuk_bot.message_handler(commands=["stats"])
def cmd_stats(m=None):
    try:
        c = sqlite3.connect(DB_PATH)
        rows = c.execute("SELECT status,hotel FROM requests").fetchall(); c.close()
    except: rows = []
    if not rows: nusuk_bot.reply_to(m, "📭 لا توجد بيانات"); return
    statuses, hotels = {}, {}
    for st, ho in rows:
        statuses[st] = statuses.get(st,0)+1
        hotels[ho] = hotels.get(ho,0)+1
    lines = ["📈 *إحصائيات*\n\n*حسب الحالة:*"]
    for s,n in statuses.items(): lines.append(f"  {s}: `{n}`")
    lines.append("\n*حسب السكن:*")
    for h,n in sorted(hotels.items(), key=lambda x:-x[1]): lines.append(f"  {h}: `{n}`")
    nusuk_bot.reply_to(m, "\n".join(lines), parse_mode="Markdown")

# ─────────── BUILDING MAPS ───────────

BUILDING_MAPS = {
    "ALRAIS2": "https://maps.app.goo.gl/1671T2oFdhV6UuVw5",
    "AJWAD": "https://maps.app.goo.gl/SKAWGzcLmcEqfbWcA",
    "ALRAIS3": "https://maps.app.goo.gl/kXt4cFLLHAs4nDBz8",
    "DURRA": "https://maps.app.goo.gl/T1P75ecrCnh8jrN4A",
    "MAN.SITTEEN": "https://maps.app.goo.gl/H6AKvdriSzFxv1BA8",
    "NUZHA1": "https://maps.app.goo.gl/jfD6UMQFmo9BhRz57",
    "NUZHA2": "https://maps.app.goo.gl/KMGfKadewiNL5vBSA",
    "RAIES1": "https://maps.app.goo.gl/qkH1GQuTm8C8nAGG7",
    "THARAWAT2": "https://maps.app.goo.gl/wVhu49YPr2DLALy38",
    "THARAWAT3": "https://maps.app.goo.gl/QWnWixiv6nLA7E2R7",
    "THARAWAT4": "https://maps.app.goo.gl/Qqcw8K5PQDoYQ3PT9",
    "THARAWAT5": "https://maps.app.goo.gl/bEd7nUrjpU4PgwuaA",
    "THARAWAT6": "https://maps.app.goo.gl/bEd7nUrjpU4PgwuaA",
}

# ─────────── ROOM BOT ───────────

room_bot = None
ROOM_CSV_URL = os.environ.get("ROOM_CSV_URL",
    "https://docs.google.com/spreadsheets/d/1s1LKapsD1Q_1LPnkJYsnoIatsy8bBi1WyBXp7AU-_Ek/export?format=csv")

if ROOM_TOKEN:
    try:
        room_bot = telebot.TeleBot(ROOM_TOKEN)

        @room_bot.message_handler(commands=["start","help"])
        def rs(m):
            room_bot.send_message(m.chat.id,
                f"🕋  HAJJ ROOM  🕋\n{DIV}\n\n"
                f"🏨 *نظام الاستعلام عن الغرف*\n_Room Inquiry System_\n\n{DIV}\n\n"
                f"🛂  أرسل رقم جواز السفر\n_Send passport number_\n\n"
                f"مثال / Example: `G3386134`\n\n{DIV}",
                parse_mode="Markdown")

        _data_cache = [None]
        def _load_data():
            if _data_cache[0]: return _data_cache[0]
            try:
                resp = urllib.request.urlopen(ROOM_CSV_URL, timeout=15)
                text = resp.read().decode("utf-8")
                rows = []
                for line in text.splitlines()[1:]:
                    parts = line.split(",")
                    if len(parts) >= 5:
                        pid = parts[3].strip().upper()
                        rn = parts[4].strip()
                        parts_rn = rn.split("_")
                        if len(parts_rn) >= 5:
                            hotel = parts_rn[0]
                            floor = parts_rn[2]
                            room = parts_rn[4]
                        else:
                            hotel, floor, room = rn, "", ""
                        rows.append((pid, hotel, floor, room))
                _data_cache[0] = rows
                log.info("Room data loaded: %d records", len(rows))
            except Exception as e:
                log.warning("Room data load: %s", e)
                _data_cache[0] = []
            return _data_cache[0]

        @room_bot.message_handler(commands=["refresh"])
        def rr(m):
            _data_cache[0] = None
            d = _load_data()
            room_bot.reply_to(m, f"✅ تم التحديث  ·  _Updated_ — {len(d)} حاج / pilgrims")

        @room_bot.message_handler(func=lambda m: m.text and not m.text.startswith("/"))
        def rl(m):
            p = m.text.strip().upper()
            if not re.match(r"^[A-Z]\d{6,9}$", p):
                room_bot.reply_to(m, "❌ جواز غير صحيح  ·  _Invalid passport_\n`G3386134`", parse_mode="Markdown"); return
            try:
                rows = _load_data()
                for pid, hotel, floor, room in rows:
                    if pid == p:
                        map_url = BUILDING_MAPS.get(hotel, "")
                        reply = (f"🕋  HAJJ ROOM  🕋\n{DIV}\n"
                                 f"✅ *تم العثور*  ·  _Found_\n{DIV}\n"
                                 f"🆔  `{p}`\n🏨  {hotel}\n📶  {floor}\n🚪  {room}\n{DIV}\n🙏  حج مبرور")
                        if map_url:
                            reply += f"\n📍 [الموقع على الخريطة]({map_url})"
                        room_bot.reply_to(m, reply, parse_mode="Markdown", disable_web_page_preview=False)
                        return
                room_bot.reply_to(m,
                    f"🕋  HAJJ ROOM  🕋\n{DIV}\n"
                    f"❌ *غير مسجل*  ·  _Not found_\n{DIV}\n"
                    f"🆔  `{p}`\nغير موجود  ·  _Not registered_\n{DIV}",
                    parse_mode="Markdown")
            except Exception as e:
                room_bot.reply_to(m, "⚠️ خطأ في البحث  ·  _Search error_", parse_mode="Markdown")
                log.warning("Room lookup: %s", e)

        log.info("Room bot ready")
    except Exception as e:
        log.warning("Room bot init failed: %s", e)
        room_bot = None

# ─────────── WEBHOOK SERVER ───────────

class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")
    def do_POST(self):
        length = int(self.headers.get("Content-Length",0))
        try:
            body = self.rfile.read(length)
            upd = telebot.types.Update.de_json(json.loads(body))
            if self.path == "/room_webhook":
                if room_bot: room_bot.process_new_updates([upd])
            else:
                nusuk_bot.process_new_updates([upd])
        except Exception as e:
            log.error("Webhook: %s", e)
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")
    def log_message(self, *a): pass

# ─────────── MAIN ───────────

if __name__ == "__main__":
    wh_url = f"{RENDER_URL}/webhook" if RENDER_URL else ""
    room_wh = f"{RENDER_URL}/room_webhook" if RENDER_URL else ""

    for a in range(3):
        try: nusuk_bot.set_webhook(url=wh_url); log.info("Nusuk webhook set"); break
        except Exception as e: log.warning("Nusuk webhook attempt %d: %s", a+1, e); time.sleep(2)

    if room_bot and room_wh:
        for a in range(3):
            try: room_bot.set_webhook(url=room_wh); log.info("Room webhook set"); break
            except Exception as e: log.warning("Room webhook attempt %d: %s", a+1, e); time.sleep(2)

    # Keep-alive (every 10 min to prevent Render free-tier spin-down)
    if RENDER_URL:
        def _p():
            while True:
                time.sleep(600)
                try:
                    urllib.request.urlopen(f"{RENDER_URL}/", timeout=10)
                except:
                    pass
        threading.Thread(target=_p, daemon=True).start()
        log.info("Keep-alive started → every 10 min")

    socketserver.TCPServer.allow_reuse_address = True
    server = http.server.HTTPServer(("0.0.0.0", PORT), Handler)
    log.info("Hajj Bots - listening :%d", PORT)
    server.serve_forever()
