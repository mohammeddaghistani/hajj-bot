import telebot
import json
import os
import time
import re
import requests
import http.server
from threading import Lock, Thread
from datetime import datetime

BOT_TOKEN = os.environ.get("NUSUK_BOT_TOKEN", "")
SHEETS_URL = os.environ.get("SHEETS_URL", "")
DATA_FILE = os.path.join(os.path.dirname(__file__), "nusuk_requests.json")

bot = telebot.TeleBot(BOT_TOKEN)
lock = Lock()
submitted = []


def load_submitted():
    global submitted
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r") as f:
            submitted = json.load(f)


def save_submitted():
    with open(DATA_FILE, "w") as f:
        json.dump(submitted, f, ensure_ascii=False, indent=2)


def append_to_sheets(record):
    try:
        r = requests.post(SHEETS_URL, json={
            "passport": record["passport"],
            "status": "لم يستلم" if record["status"] == "not_received" else "بدل فاقد",
            "hotel": record["hotel"],
            "floor": record["floor"],
            "room": record["room"],
            "employee": record["employee"],
        }, timeout=10)
        print(f"[SHEETS] {r.status_code} - {record['passport']}")
        return r.status_code == 200
    except Exception as e:
        print(f"[SHEETS ERROR] {e}")
        return False


user_state = {}


@bot.message_handler(commands=["start", "help"])
def send_welcome(message):
    name = message.from_user.first_name or "حبيب"
    text = (
        f"وعليكم السلام ورحمة الله وبركاته {name} 🤍\n\n"
        "📋 *بوت جمع طلبات بطاقات نسك*\n"
        "هذا البوت مخصص لموظفي الحج لتسجيل طلبات استلام البطاقات.\n\n"
        "*-*-*-*-*-*-*-*-*-*-*-*-*-*\n\n"
        "🔹 `/new` → بدء طلب جديد\n"
        "🔹 `/count` → عدد الطلبات المسجلة\n"
        "🔹 `/history` → آخر 10 طلبات\n\n"
        "*-*-*-*-*-*-*-*-*-*-*-*-*-*\n\n"
        "👳🏼‍♂️ *ملاحظة:* جميع الطلبات تُسجل مباشرة في Google Sheets بشكل لحظي."
    )
    bot.reply_to(message, text, parse_mode="Markdown")


@bot.message_handler(commands=["count"])
def send_count(message):
    with lock:
        count = len(submitted)
    bot.reply_to(message, f"📊 عدد الطلبات المسجلة: *{count}*", parse_mode="Markdown")


@bot.message_handler(commands=["history"])
def send_history(message):
    with lock:
        recent = submitted[-10:]
    if not recent:
        bot.reply_to(message, "لا توجد طلبات مسجلة")
        return
    lines = ["🗂 *آخر 10 طلبات:*\n"]
    for r in reversed(recent):
        status = r.get("status", "")
        lines.append(f"`{r['passport']}` • {status} • {r.get('hotel','')} • دور {r.get('floor','')} غ {r.get('room','')}")
    bot.reply_to(message, "\n".join(lines), parse_mode="Markdown")


@bot.message_handler(commands=["new"])
def start_request(message):
    cid = message.chat.id
    user_state[cid] = {"step": "passport"}
    bot.reply_to(message, "🔹 أرسل *رقم جواز السفر* للحاج:", parse_mode="Markdown")


@bot.message_handler(func=lambda m: user_state.get(m.chat.id, {}).get("step") == "passport")
def get_passport(message):
    cid = message.chat.id
    passport = message.text.strip().upper()
    if not re.match(r"^[A-Z]\d{6,9}$", passport):
        bot.reply_to(message, "❌ رقم جواز غير صحيح. مثال: G3386134")
        return
    user_state[cid]["passport"] = passport
    user_state[cid]["step"] = "status"
    markup = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    markup.add(telebot.types.KeyboardButton("لم يستلم البطاقة"))
    markup.add(telebot.types.KeyboardButton("بدل فاقد"))
    bot.reply_to(message, "🔹 اختر حالة البطاقة:", reply_markup=markup)


@bot.message_handler(func=lambda m: user_state.get(m.chat.id, {}).get("step") == "status")
def get_status(message):
    cid = message.chat.id
    text = message.text.strip()
    if "لم يستلم" in text:
        user_state[cid]["status"] = "not_received"
    elif "فاقد" in text or "بدل" in text:
        user_state[cid]["status"] = "lost"
    else:
        bot.reply_to(message, "❌ اختر من الأزرار: 'لم يستلم البطاقة' أو 'بدل فاقد'")
        return
    user_state[cid]["step"] = "hotel"
    bot.reply_to(message, "🔹 أرسل *اسم السكن أو الفندق*:", parse_mode="Markdown", reply_markup=telebot.types.ReplyKeyboardRemove())


@bot.message_handler(func=lambda m: user_state.get(m.chat.id, {}).get("step") == "hotel")
def get_hotel(message):
    cid = message.chat.id
    hotel = message.text.strip()
    if not hotel:
        bot.reply_to(message, "❌ أرسل اسم السكن من فضلك")
        return
    user_state[cid]["hotel"] = hotel
    user_state[cid]["step"] = "floor"
    bot.reply_to(message, "🔹 أرسل *رقم الدور*:", parse_mode="Markdown")


@bot.message_handler(func=lambda m: user_state.get(m.chat.id, {}).get("step") == "floor")
def get_floor(message):
    cid = message.chat.id
    floor = message.text.strip()
    if not floor.isdigit():
        bot.reply_to(message, "❌ أرسل رقماً صحيحاً للدور")
        return
    user_state[cid]["floor"] = floor
    user_state[cid]["step"] = "room"
    bot.reply_to(message, "🔹 أرسل *رقم الغرفة*:", parse_mode="Markdown")


@bot.message_handler(func=lambda m: user_state.get(m.chat.id, {}).get("step") == "room")
def get_room(message):
    cid = message.chat.id
    room = message.text.strip()
    if not room:
        bot.reply_to(message, "❌ أرسل رقم الغرفة من فضلك")
        return
    user_state[cid]["room"] = room
    user_state[cid]["step"] = "confirm"
    emp = message.from_user.first_name or ""
    if message.from_user.last_name:
        emp += f" {message.from_user.last_name}"
    user_state[cid]["employee"] = emp.strip()
    user_state[cid]["date"] = datetime.now().strftime("%Y-%m-%d %H:%M")

    s = user_state[cid]
    status_text = "لم يستلم" if s["status"] == "not_received" else "بدل فاقد"
    confirm = (
        f"📋 *تأكيد الطلب*\n\n"
        f"🛂 *جواز:* `{s['passport']}`\n"
        f"📌 *الحالة:* {status_text}\n"
        f"🏨 *السكن:* {s['hotel']}\n"
        f"📶 *الدور:* {s['floor']}\n"
        f"🚪 *الغرفة:* {s['room']}\n"
        f"👤 *الموظف:* {s['employee']}\n\n"
        f"✅ أرسل *تم* للحفظ"
    )
    bot.reply_to(message, confirm, parse_mode="Markdown")


@bot.message_handler(func=lambda m: user_state.get(m.chat.id, {}).get("step") == "confirm")
def confirm_handler(message):
    cid = message.chat.id
    text = message.text.strip()
    if text in ["تم", "تأكيد", "yes", "نعم"]:
        s = user_state[cid]
        record = {k: s[k] for k in ("passport", "status", "hotel", "floor", "room", "employee", "date")}
        ok = append_to_sheets(record)
        with lock:
            submitted.append(record)
            save_submitted()
            total = len(submitted)
        del user_state[cid]
        if ok:
            bot.reply_to(message, f"✅ *تم حفظ الطلب في Google Sheets!*\n\nالإجمالي: {total}\n\n`/new` — طلب جديد", parse_mode="Markdown")
        else:
            bot.reply_to(message, f"⚠️ *حُفظ محلياً* لكن فشل الاتصال بـ Sheets.\n\nالإجمالي: {total}\n\n`/new` — طلب جديد", parse_mode="Markdown")
    else:
        del user_state[cid]
        bot.reply_to(message, "❌ تم إلغاء الطلب.\n\n`/new` — طلب جديد", parse_mode="Markdown")


def run_health_server():
    port = int(os.environ.get("PORT", 8080))
    server = http.server.HTTPServer(("0.0.0.0", port), http.server.SimpleHTTPRequestHandler)
    print(f"[HTTP] Health server on port {port}")
    server.serve_forever()


load_submitted()
Thread(target=run_health_server, daemon=True).start()
time.sleep(1)
print("Nusuk bot started...")
try:
    bot.remove_webhook()
except Exception:
    pass
time.sleep(1)
bot.polling(none_stop=True, skip_pending=True)
