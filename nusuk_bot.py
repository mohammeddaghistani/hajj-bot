import telebot
import json
import os
import re
import requests
import time
from threading import Lock
from datetime import datetime
from flask import Flask, request

BOT_TOKEN = os.environ.get("NUSUK_BOT_TOKEN", "")
SHEETS_URL = os.environ.get("SHEETS_URL", "")
DATA_FILE = os.path.join(os.path.dirname(__file__), "nusuk_requests.json")
PORT = int(os.environ.get("PORT", 8080))
WEBHOOK_URL = os.environ.get("RENDER_EXTERNAL_URL", f"https://hajj-nusuk-bot.onrender.com")

bot = telebot.TeleBot(BOT_TOKEN)
app = Flask(__name__)
lock = Lock()
store = []


def load_store():
    global store
    try:
        r = requests.get(f"{SHEETS_URL}?action=all", timeout=10)
        if r.status_code == 200:
            store = r.json()
            save_store_backup()
            return
    except Exception as e:
        print(f"[LOAD ERROR] {e}")
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
        print(f"[SHEETS GET ERROR] {e}")
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
        print(f"[SHEETS POST ERROR] {e}")
        return False


def show_main_menu(chat_id, edit_msg_id=None):
    markup = telebot.types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        telebot.types.InlineKeyboardButton("📝 ١ - طلب جديد", callback_data="new"),
        telebot.types.InlineKeyboardButton("📊 ٢ - العدد", callback_data="count"),
        telebot.types.InlineKeyboardButton("🗂 ٣ - آخر الطلبات", callback_data="history"),
        telebot.types.InlineKeyboardButton("📈 ٤ - الإحصائيات", callback_data="stats"),
    )
    text = (
        "╔══════════════════╗\n"
        "    ✨ *Nusuk Card System* ✨\n"
        "    *نظام بطاقات نسك*\n"
        "╚══════════════════╝\n\n"
        "Send a number or tap:\n"
        "ارسـل الرقم أو اضغط:\n\n"
        "1️⃣ New Request — طلب جديد\n"
        "2️⃣ Count — العدد\n"
        "3️⃣ Last 10 — آخر ١٠\n"
        "4️⃣ Statistics — إحصائيات\n\n"
        "╔══════════════════╗\n"
        "  👳🏼‍♂️ Real-time Google Sheets\n"
        "╚══════════════════╝"
    )
    if edit_msg_id:
        bot.edit_message_text(text, chat_id, edit_msg_id, parse_mode="Markdown", reply_markup=markup)
    else:
        bot.send_message(chat_id, text, parse_mode="Markdown", reply_markup=markup)


def cancel_state(cid, msg=None):
    if cid in user_state:
        del user_state[cid]
    if msg:
        bot.reply_to(msg, "❌ *Cancelled / ملغي*", parse_mode="Markdown")
    show_main_menu(cid)


BACK_WORDS = ["رجوع", "back", "القائمة", "menu", "🏠", "الرئيسية"]


def is_back(text):
    return any(w in text for w in BACK_WORDS)


@app.route("/")
def health():
    return "OK", 200


@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        update = telebot.types.Update.de_json(request.get_json())
        bot.process_new_updates([update])
    except Exception as e:
        print(f"[WEBHOOK ERROR] {e}")
    return "OK", 200


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


user_state = {}


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
def back_in_conversation(message):
    cancel_state(message.chat.id, message)


@bot.message_handler(commands=["count"])
def cmd_count(message=None):
    result = sheets_get("count")
    count = result["count"] if result else len(store)
    txt = (
        "╔══════════════════╗\n"
        "    📊 *Total Requests*\n"
        "    *إجمالي الطلبات*\n"
        "╚══════════════════╝\n\n"
        f"*{count}* requests / طلب\n\n"
        "Tap /start for menu"
    )
    if message:
        bot.reply_to(message, txt, parse_mode="Markdown")
    else:
        return txt


@bot.message_handler(commands=["history"])
def cmd_history(message=None):
    result = sheets_get("all")
    data = result if result else store
    if not data:
        txt = "📭 *No requests yet* — لا توجد طلبات بعد"
        if message:
            bot.reply_to(message, txt, parse_mode="Markdown")
        return
    recent = data[-10:]
    lines = ["╔══════════════════╗\n    🗂 *Last 10 — آخر ١٠*\n╚══════════════════╝\n"]
    for r in reversed(recent):
        s = "📭 Not received" if r.get("status", "").startswith("لم") or r.get("status") == "not_received" else "🔄 Lost"
        p = r.get("passport", "N/A")
        h = r.get("hotel", "?")
        f = r.get("floor", "?")
        rm = r.get("room", "?")
        lines.append(f"`{p}` {s}\n    {h} | دور {f} غ {rm}\n")
    txt = "\n".join(lines)
    if message:
        bot.reply_to(message, txt, parse_mode="Markdown")
    return txt


@bot.message_handler(commands=["stats"])
def cmd_stats(message=None):
    result = sheets_get("stats")
    if not result:
        txt = "⚠️ *Stats unavailable* — غير متوفرة حالياً"
        if message:
            bot.reply_to(message, txt, parse_mode="Markdown")
        return
    hotels = result.get("hotels", {})
    statuses = result.get("statuses", {})
    lines = ["╔══════════════════╗\n    📈 *Statistics — إحصائيات*\n╚══════════════════╝\n"]
    lines.append("📌 *By Status / حسب الحالة:*")
    for s, c in statuses.items():
        lines.append(f"  {s}: *{c}*")
    lines.append("\n🏨 *By Accommodation / حسب السكن:*")
    for h, c in sorted(hotels.items(), key=lambda x: -x[1]):
        lines.append(f"  {h}: *{c}*")
    txt = "\n".join(lines)
    if message:
        bot.reply_to(message, txt, parse_mode="Markdown")
    return txt


@bot.message_handler(commands=["new"])
def start_request(message=None):
    cid = message.chat.id
    user_state[cid] = {"step": "passport"}
    txt = (
        "╔══════════════════╗\n"
        "    🛂 *Step 1/5 — Passport*\n"
        "╚══════════════════╝\n\n"
        "Send the pilgrim's passport number:\n"
        "أرسل رقم جواز السفر\n\n"
        "Example: `G3386134`\n\n"
        "*Back / رجوع* to cancel"
    )
    bot.send_message(cid, txt, parse_mode="Markdown")


@bot.message_handler(func=lambda m: user_state.get(m.chat.id, {}).get("step") == "passport")
def get_passport(message):
    cid = message.chat.id
    passport = message.text.strip().upper()
    if not re.match(r"^[A-Z]\d{6,9}$", passport):
        bot.reply_to(message,
            "❌ *Invalid format*\n"
            "Use letter + 6-9 digits\n"
            "مثال: `G3386134`")
        return
    check = sheets_get("check", passport=passport)
    if check and check.get("exists"):
        bot.reply_to(message,
            f"⚠️ *Passport {passport} already exists!*\n"
            f"*رقم الجواز موجود مسبقاً!*\n\n"
            "Send another or /start for menu")
        return
    user_state[cid]["passport"] = passport
    user_state[cid]["step"] = "status"
    markup = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True, row_width=2)
    markup.add("📭 لم يستلم", "📭 Not Received", "🔄 بدل فاقد", "🔄 Lost")
    bot.reply_to(message,
        "╔══════════════════╗\n"
        "    📌 *Step 2/5 — Status*\n"
        "╚══════════════════╝\n\n"
        "Choose card status:\n"
        "اختر حالة البطاقة:",
        reply_markup=markup, parse_mode="Markdown")


@bot.message_handler(func=lambda m: user_state.get(m.chat.id, {}).get("step") == "status")
def get_status(message):
    cid = message.chat.id
    text = message.text.strip()
    if is_back(text):
        return cancel_state(cid, message)
    if any(w in text for w in ["لم يستلم", "Not Received"]):
        user_state[cid]["status"] = "not_received"
    elif any(w in text for w in ["فاقد", "بدل", "Lost"]):
        user_state[cid]["status"] = "lost"
    else:
        bot.reply_to(message, "❌ Use the buttons / استخدم الأزرار")
        return
    user_state[cid]["step"] = "hotel"
    bot.reply_to(message,
        "╔══════════════════╗\n"
        "    🏨 *Step 3/5 — Accommodation*\n"
        "╚══════════════════╝\n\n"
        "Send accommodation name:\n"
        "أرسل اسم السكن أو الفندق:\n\n"
        "*Back / رجوع* to cancel",
        parse_mode="Markdown", reply_markup=telebot.types.ReplyKeyboardRemove())


@bot.message_handler(func=lambda m: user_state.get(m.chat.id, {}).get("step") == "hotel")
def get_hotel(message):
    cid = message.chat.id
    hotel = message.text.strip()
    if is_back(hotel):
        return cancel_state(cid, message)
    if not hotel:
        bot.reply_to(message, "❌ Send the name / أرسل الاسم")
        return
    user_state[cid]["hotel"] = hotel
    user_state[cid]["step"] = "floor"
    bot.reply_to(message,
        "╔══════════════════╗\n"
        "    📶 *Step 4/5 — Floor*\n"
        "╚══════════════════╝\n\n"
        "Send floor number:\n"
        "أرسل رقم الدور (مثال: 1):\n\n"
        "*Back / رجوع* to cancel",
        parse_mode="Markdown")


@bot.message_handler(func=lambda m: user_state.get(m.chat.id, {}).get("step") == "floor")
def get_floor(message):
    cid = message.chat.id
    floor = message.text.strip()
    if is_back(floor):
        return cancel_state(cid, message)
    if not floor.isdigit():
        bot.reply_to(message, "❌ Enter a number / أدخل رقماً")
        return
    user_state[cid]["floor"] = floor
    user_state[cid]["step"] = "room"
    bot.reply_to(message,
        "╔══════════════════╗\n"
        "    🚪 *Step 5/5 — Room*\n"
        "╚══════════════════╝\n\n"
        "Send room number:\n"
        "أرسل رقم الغرفة (مثال: 165):\n\n"
        "*Back / رجوع* to cancel",
        parse_mode="Markdown")


@bot.message_handler(func=lambda m: user_state.get(m.chat.id, {}).get("step") == "room")
def get_room(message):
    cid = message.chat.id
    room = message.text.strip()
    if is_back(room):
        return cancel_state(cid, message)
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
    txt = (
        "╔══════════════════╗\n"
        "    📋 *Confirm — تأكيد*\n"
        "╚══════════════════╝\n\n"
        f"🛂 Passport: `{s['passport']}`\n"
        f"📌 Status: {st}\n"
        f"🏨 Accommodation: {s['hotel']}\n"
        f"📶 Floor: {s['floor']}\n"
        f"🚪 Room: {s['room']}\n"
        f"👤 Staff: {s['employee']}\n\n"
        "✅ Send *Confirm / تم* to save\n"
        "❌ Send *Cancel / إلغاء* or *Back / رجوع*"
    )
    bot.reply_to(message, txt, parse_mode="Markdown")


@bot.message_handler(func=lambda m: user_state.get(m.chat.id, {}).get("step") == "confirm")
def confirm_handler(message):
    cid = message.chat.id
    text = message.text.strip()
    if is_back(text) or text in ["Cancel", "cancel", "إلغاء"]:
        return cancel_state(cid, message)
    if text in ["تم", "تأكيد", "Confirm", "confirm", "yes", "نعم"]:
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
            bot.reply_to(message,
                "╔══════════════════╗\n"
                "    ✅ *Saved! تم الحفظ!*\n"
                "╚══════════════════╝\n\n"
                f"Total / الإجمالي: *{total}*\n\n"
                "1️⃣ New request or /start for menu",
                parse_mode="Markdown")
        else:
            bot.reply_to(message,
                "⚠️ *Saved locally / حفظ محلياً*\n"
                "Will sync when Sheets available\n"
                f"Total: {total}")
    else:
        bot.reply_to(message, 'Send *Confirm / تم* or *Cancel / إلغاء*')
        return
    show_main_menu(message.chat.id)


if __name__ == "__main__":
    print("Loading data...")
    load_store()
    print(f"Loaded {len(store)} records")
    bot.remove_webhook()
    time.sleep(1)
    bot.set_webhook(url=f"{WEBHOOK_URL}/webhook")
    print(f"Webhook set to {WEBHOOK_URL}/webhook")
    app.run(host="0.0.0.0", port=PORT)
