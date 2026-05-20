import telebot
import json
import os
import re
import time
import http.server
import gspread
from google.oauth2.service_account import Credentials
from threading import Lock, Thread
from datetime import datetime

BOT_TOKEN = os.environ.get("NUSUK_BOT_TOKEN", "")
GOOGLE_KEY_JSON = os.environ.get("GOOGLE_SHEETS_KEY", "{}")
SHEET_ID = os.environ.get("SHEET_ID", "")
PORT = 8080
try:
    PORT = int(os.environ.get("PORT", 8080))
except (ValueError, TypeError):
    pass

bot = telebot.TeleBot(BOT_TOKEN)
lock = Lock()
sheet = None
store = []


def init_sheet():
    global sheet, store
    try:
        key = json.loads(GOOGLE_KEY_JSON)
        creds = Credentials.from_service_account_info(key, scopes=["https://www.googleapis.com/auth/spreadsheets"])
        client = gspread.authorize(creds)
        sheet = client.open_by_key(SHEET_ID).sheet1
        load_store()
        print(f"[SHEETS] Connected. {len(store)} records")
    except Exception as e:
        print(f"[SHEETS INIT ERROR] {e}")


def load_store():
    global store
    if not sheet:
        return
    try:
        records = sheet.get_all_records()
        store = records
        save_store_backup()
    except Exception as e:
        print(f"[LOAD ERROR] {e}")
        if os.path.exists(DATA_FILE):
            with open(DATA_FILE, "r") as f:
                store = json.load(f)


DATA_FILE = os.path.join(os.path.dirname(__file__), "nusuk_requests.json")


def save_store_backup():
    with open(DATA_FILE, "w") as f:
        json.dump(store, f, ensure_ascii=False, indent=2)


def append_to_sheet(record):
    if not sheet:
        return False
    try:
        sheet.append_row([
            record["date"],
            record["passport"],
            "لم يستلم" if record["status"] == "not_received" else "بدل فاقد",
            record["hotel"],
            record["floor"],
            record["room"],
            record["employee"],
        ])
        return True
    except Exception as e:
        print(f"[APPEND ERROR] {e}")
        return False


def show_main_menu(chat_id):
    markup = telebot.types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        telebot.types.InlineKeyboardButton("📝 ١ - طلب جديد", callback_data="new"),
        telebot.types.InlineKeyboardButton("📊 ٢ - العدد", callback_data="count"),
        telebot.types.InlineKeyboardButton("🗂 ٣ - آخر الطلبات", callback_data="history"),
        telebot.types.InlineKeyboardButton("📈 ٤ - الإحصائيات", callback_data="stats"),
    )
    text = (
        "✨ *Nusuk Card System* ✨\n"
        "*نظام بطاقات نسك*\n\n"
        "Send a number or tap:\n"
        "ارسـل الرقم أو اضغط:\n\n"
        "1️⃣ New Request — طلب جديد\n"
        "2️⃣ Count — العدد\n"
        "3️⃣ Last 10 — آخر ١٠\n"
        "4️⃣ Statistics — إحصائيات\n\n"
        "👳🏼‍♂️ Real-time Google Sheets"
    )
    bot.send_message(chat_id, text, parse_mode="Markdown", reply_markup=markup)


def cancel_state(cid):
    if cid in user_state:
        del user_state[cid]
    show_main_menu(cid)


BACK_WORDS = ["رجوع", "back", "القائمة", "menu", "🏠", "الرئيسية"]


def is_back(text):
    return any(w in text for w in BACK_WORDS)


user_state = {}


@bot.callback_query_handler(func=lambda c: c.data in ("new", "count", "history", "stats"))
def handle_callback(c):
    if c.data == "new":
        start_request(c.message)
    elif c.data == "count":
        cmd_count(c.message)
    elif c.data == "history":
        cmd_history(c.message)
    elif c.data == "stats":
        cmd_stats(c.message)
    bot.answer_callback_query(c.id)


@bot.message_handler(commands=["start", "help", "menu"])
def cmd_start(message):
    show_main_menu(message.chat.id)


@bot.message_handler(func=lambda m: m.text and m.text.strip() in ("1", "1️⃣") and m.chat.id not in user_state)
def num_new(message):
    start_request(message)


@bot.message_handler(func=lambda m: m.text and m.text.strip() in ("2", "2️⃣") and m.chat.id not in user_state)
def num_count(message):
    cmd_count(message)


@bot.message_handler(func=lambda m: m.text and m.text.strip() in ("3", "3️⃣") and m.chat.id not in user_state)
def num_history(message):
    cmd_history(message)


@bot.message_handler(func=lambda m: m.text and m.text.strip() in ("4", "4️⃣") and m.chat.id not in user_state)
def num_stats(message):
    cmd_stats(message)


@bot.message_handler(func=lambda m: m.text and is_back(m.text) and m.chat.id in user_state)
def back_handler(message):
    cancel_state(message.chat.id)


@bot.message_handler(commands=["count"])
def cmd_count(message=None):
    with lock:
        count = len(store)
    txt = f"📊 *Total Requests — إجمالي الطلبات*\n\n*{count}* requests / طلب"
    if message:
        bot.reply_to(message, txt, parse_mode="Markdown")


@bot.message_handler(commands=["history"])
def cmd_history(message=None):
    with lock:
        data = list(store)
    if not data:
        bot.reply_to(message, "📭 *No requests yet* — لا توجد طلبات بعد", parse_mode="Markdown")
        return
    recent = data[-10:]
    lines = ["🗂 *Last 10 — آخر ١٠:*\n"]
    for r in reversed(recent):
        s = r.get("Status", "") or r.get("status", "")
        p = r.get("Passport", "") or r.get("passport", "N/A")
        h = r.get("Accommodation", "") or r.get("hotel", "?")
        f = r.get("Floor", "") or r.get("floor", "?")
        rm = r.get("Room", "") or r.get("room", "?")
        lines.append(f"`{p}` {s}\n    {h} | F{f} R{rm}")
    bot.reply_to(message, "\n".join(lines), parse_mode="Markdown")


@bot.message_handler(commands=["stats"])
def cmd_stats(message=None):
    with lock:
        data = list(store)
    if not data:
        bot.reply_to(message, "📭 *No data* — لا توجد بيانات", parse_mode="Markdown")
        return
    hotels = {}
    statuses = {}
    for r in data:
        h = r.get("Accommodation", "") or r.get("hotel", "غير محدد")
        s = r.get("Status", "") or r.get("status", "")
        hotels[h] = hotels.get(h, 0) + 1
        statuses[s] = statuses.get(s, 0) + 1
    lines = ["📈 *Statistics — إحصائيات*\n"]
    lines.append("*By Status / حسب الحالة:*")
    for s, c in statuses.items():
        lines.append(f"  {s}: *{c}*")
    lines.append("\n*By Accommodation / حسب السكن:*")
    for h, c in sorted(hotels.items(), key=lambda x: -x[1]):
        lines.append(f"  {h}: *{c}*")
    bot.reply_to(message, "\n".join(lines), parse_mode="Markdown")


@bot.message_handler(commands=["new"])
def start_request(message=None):
    cid = message.chat.id
    user_state[cid] = {"step": "passport"}
    txt = ("🛂 *Step 1/5 — Passport*\n\n"
           "Send passport number / أرسل رقم الجواز\n"
           "Example: `G3386134`\n\n"
           "*Back / رجوع* to cancel")
    bot.send_message(cid, txt, parse_mode="Markdown")


@bot.message_handler(func=lambda m: user_state.get(m.chat.id, {}).get("step") == "passport")
def get_passport(message):
    cid = message.chat.id
    passport = message.text.strip().upper()
    if is_back(passport):
        return cancel_state(cid)
    if not re.match(r"^[A-Z]\d{6,9}$", passport):
        bot.reply_to(message, "❌ Invalid format. Example: `G3386134`", parse_mode="Markdown")
        return
    with lock:
        exists = any(
            (r.get("Passport", "") or r.get("passport", "")).upper() == passport
            for r in store
        )
    if exists:
        bot.reply_to(message, f"⚠️ Passport *{passport}* already exists / موجود مسبقاً", parse_mode="Markdown")
        return
    user_state[cid]["passport"] = passport
    user_state[cid]["step"] = "status"
    markup = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True, row_width=2)
    markup.add("📭 لم يستلم", "📭 Not Received", "🔄 بدل فاقد", "🔄 Lost")
    bot.reply_to(message, "📌 *Step 2/5 — Status*\nChoose / اختر:", reply_markup=markup, parse_mode="Markdown")


@bot.message_handler(func=lambda m: user_state.get(m.chat.id, {}).get("step") == "status")
def get_status(message):
    cid = message.chat.id
    text = message.text.strip()
    if is_back(text):
        return cancel_state(cid)
    if "لم يستلم" in text or "Not Received" in text:
        user_state[cid]["status"] = "not_received"
    elif "فاقد" in text or "بدل" in text or "Lost" in text:
        user_state[cid]["status"] = "lost"
    else:
        bot.reply_to(message, "❌ Use the buttons / استخدم الأزرار")
        return
    user_state[cid]["step"] = "hotel"
    bot.reply_to(message, "🏨 *Step 3/5 — Accommodation*\nSend name / أرسل اسم السكن:",
                 parse_mode="Markdown", reply_markup=telebot.types.ReplyKeyboardRemove())


@bot.message_handler(func=lambda m: user_state.get(m.chat.id, {}).get("step") == "hotel")
def get_hotel(message):
    cid = message.chat.id
    hotel = message.text.strip()
    if is_back(hotel):
        return cancel_state(cid)
    if not hotel:
        bot.reply_to(message, "❌ Send the name / أرسل الاسم")
        return
    user_state[cid]["hotel"] = hotel
    user_state[cid]["step"] = "floor"
    bot.reply_to(message, "📶 *Step 4/5 — Floor*\nSend number / أرسل الدور:", parse_mode="Markdown")


@bot.message_handler(func=lambda m: user_state.get(m.chat.id, {}).get("step") == "floor")
def get_floor(message):
    cid = message.chat.id
    floor = message.text.strip()
    if is_back(floor):
        return cancel_state(cid)
    if not floor.isdigit():
        bot.reply_to(message, "❌ Enter a number / أدخل رقماً")
        return
    user_state[cid]["floor"] = floor
    user_state[cid]["step"] = "room"
    bot.reply_to(message, "🚪 *Step 5/5 — Room*\nSend number / أرسل الغرفة:", parse_mode="Markdown")


@bot.message_handler(func=lambda m: user_state.get(m.chat.id, {}).get("step") == "room")
def get_room(message):
    cid = message.chat.id
    room = message.text.strip()
    if is_back(room):
        return cancel_state(cid)
    if not room:
        bot.reply_to(message, "❌ Enter room / أدخل الغرفة")
        return
    user_state[cid]["room"] = room
    user_state[cid]["step"] = "confirm"
    emp = message.from_user.first_name or ""
    if message.from_user.last_name:
        emp += f" {message.from_user.last_name}"
    user_state[cid]["employee"] = emp.strip()
    user_state[cid]["date"] = datetime.now().strftime("%Y-%m-%d %H:%M")

    s = user_state[cid]
    st = "Not received / لم يستلم" if s["status"] == "not_received" else "Lost / بدل فاقد"
    txt = (f"📋 *Confirm — تأكيد*\n\n"
           f"🛂 Passport: `{s['passport']}`\n"
           f"📌 Status: {st}\n"
           f"🏨 Accommodation: {s['hotel']}\n"
           f"📶 Floor: {s['floor']}\n"
           f"🚪 Room: {s['room']}\n"
           f"👤 Staff: {s['employee']}\n\n"
           "✅ Send *Confirm / تم* to save\n"
           "❌ Send *Cancel / إلغاء* or *Back / رجوع*")
    bot.reply_to(message, txt, parse_mode="Markdown")


@bot.message_handler(func=lambda m: user_state.get(m.chat.id, {}).get("step") == "confirm")
def confirm_handler(message):
    cid = message.chat.id
    text = message.text.strip()
    if is_back(text) or text in ("Cancel", "cancel", "إلغاء"):
        return cancel_state(cid)
    if text in ("تم", "تأكيد", "Confirm", "confirm", "yes", "نعم"):
        s = user_state[cid]
        record = {k: s[k] for k in ("passport", "status", "hotel", "floor", "room", "employee", "date")}
        ok = append_to_sheet(record)
        with lock:
            store.append({
                "Passport": s["passport"],
                "Status": "لم يستلم" if s["status"] == "not_received" else "بدل فاقد",
                "Accommodation": s["hotel"],
                "Floor": s["floor"],
                "Room": s["room"],
                "Employee": s["employee"],
                "Date": s["date"],
            })
            save_store_backup()
            total = len(store)
        del user_state[cid]
        if ok:
            bot.reply_to(message, f"✅ *Saved! تم الحفظ!*\nTotal: *{total}*", parse_mode="Markdown")
        else:
            bot.reply_to(message, f"⚠️ *Saved locally* — Sheets offline\nTotal: {total}")
    else:
        bot.reply_to(message, 'Send *Confirm / تم* or *Cancel / إلغاء*')
        return
    show_main_menu(message.chat.id)


def run_health_server():
    server = http.server.HTTPServer(("0.0.0.0", PORT), http.server.SimpleHTTPRequestHandler)
    print(f"[HTTP] Health server on port {PORT}")
    server.serve_forever()


if __name__ == "__main__":
    print("Connecting to Google Sheets...")
    init_sheet()
    Thread(target=run_health_server, daemon=True).start()
    time.sleep(1)
    print("Nusuk bot started...")
    while True:
        try:
            bot.remove_webhook()
            time.sleep(2)
            bot.polling(none_stop=True, timeout=30)
        except Exception as e:
            print(f"[POLLING] {e}, retrying in 5s...")
            time.sleep(5)
