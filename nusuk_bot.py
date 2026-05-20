import telebot
import json
import os
import re
import requests
import time
import http.server
from threading import Lock, Thread
from datetime import datetime

BOT_TOKEN = os.environ.get("NUSUK_BOT_TOKEN", "")
SHEETS_URL = os.environ.get("SHEETS_URL", "")
DATA_FILE = os.path.join(os.path.dirname(__file__), "nusuk_requests.json")
PORT = int(os.environ.get("PORT", 8080))

bot = telebot.TeleBot(BOT_TOKEN)
lock = Lock()
store = []


def load_store():
    global store
    try:
        r = requests.get(f"{SHEETS_URL}?action=all", timeout=10)
        if r.status_code == 200 and isinstance(r.json(), list):
            store = r.json()
            save_store_backup()
            return
    except Exception as e:
        print(f"[LOAD] {e}")
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r") as f:
            store = json.load(f)


def save_store_backup():
    with open(DATA_FILE, "w") as f:
        json.dump(store, f, ensure_ascii=False, indent=2)


def sheets_get(action, **params):
    try:
        params["action"] = action
        r = requests.get(SHEETS_URL, params=params, timeout=10)
        return r.json() if r.status_code == 200 else None
    except Exception as e:
        print(f"[SHEETS GET] {e}")
        return None


def sheets_post(record):
    try:
        r = requests.post(SHEETS_URL, json={
            "passport": record["passport"],
            "status": record["status"],
            "hotel": record["hotel"],
            "floor": record["floor"],
            "room": record["room"],
            "employee": record["employee"],
        }, timeout=10)
        return r.status_code == 200
    except Exception as e:
        print(f"[SHEETS POST] {e}")
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
    result = sheets_get("count")
    count = result["count"] if result else len(store)
    txt = (f"📊 *Total Requests — إجمالي الطلبات*\n\n*{count}* requests / طلب")
    if message:
        bot.reply_to(message, txt, parse_mode="Markdown")


@bot.message_handler(commands=["history"])
def cmd_history(message=None):
    result = sheets_get("all")
    data = result if isinstance(result, list) else store
    if not data:
        bot.reply_to(message, "📭 *No requests yet* — لا توجد طلبات بعد", parse_mode="Markdown")
        return
    recent = data[-10:]
    lines = ["🗂 *Last 10 — آخر ١٠:*\n"]
    for r in reversed(recent):
        s = r.get("status", "")
        p = r.get("passport", "N/A")
        h = r.get("hotel", "?")
        f = r.get("floor", "?")
        rm = r.get("room", "?")
        lines.append(f"`{p}` {s}\n    {h} | F{f} R{rm}")
    bot.reply_to(message, "\n".join(lines), parse_mode="Markdown")


@bot.message_handler(commands=["stats"])
def cmd_stats(message=None):
    result = sheets_get("stats")
    if not result:
        bot.reply_to(message, "⚠️ *Stats unavailable* — غير متوفرة حالياً", parse_mode="Markdown")
        return
    hotels = result.get("hotels", {})
    statuses = result.get("statuses", {})
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
    check = sheets_get("check", passport=passport)
    if check and check.get("exists"):
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
        status_label = "لم يستلم" if s["status"] == "not_received" else "بدل فاقد"
        record = {k: s[k] for k in ("passport", "status", "hotel", "floor", "room", "employee", "date")}
        ok = sheets_post(record)
        with lock:
            store.append({"passport": s["passport"], "status": status_label, "hotel": s["hotel"],
                          "floor": s["floor"], "room": s["room"], "employee": s["employee"], "date": s["date"]})
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
    print("Loading data...")
    load_store()
    print(f"Loaded {len(store)} records")
    for i in range(5):
        try:
            bot.remove_webhook()
            break
        except Exception as e:
            print(f"[WEBHOOK CLEAR] attempt {i+1}: {e}")
            time.sleep(2)
    Thread(target=run_health_server, daemon=True).start()
    time.sleep(1)
    print("Nusuk bot started...")
    while True:
        try:
            bot.polling(none_stop=True, timeout=30)
        except Exception as e:
            print(f"[POLLING ERROR] {e}, retrying in 5s...")
            time.sleep(5)
