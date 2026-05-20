import telebot
import json
import csv
import os
import time
import re
import smtplib
import tempfile
import http.server
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from threading import Lock, Thread
from datetime import datetime, timedelta

BOT_TOKEN = os.environ.get("NUSUK_BOT_TOKEN", "")
EMAIL_ADDR = os.environ.get("EMAIL_ADDR", "")
EMAIL_PASS = os.environ.get("EMAIL_PASS", "")
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587
DATA_FILE = os.path.join(os.path.dirname(__file__), "nusuk_requests.json")

bot = telebot.TeleBot(BOT_TOKEN)
lock = Lock()
requests_store = []


def load_requests():
    global requests_store
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r") as f:
            requests_store = json.load(f)


def save_requests():
    with open(DATA_FILE, "w") as f:
        json.dump(requests_store, f, ensure_ascii=False, indent=2)


def send_email():
    global requests_store
    with lock:
        if not requests_store:
            return
        pending = list(requests_store)
        requests_store = []
        save_requests()

    if not pending:
        return

    groups = {}
    for r in pending:
        hotel = r.get("hotel", "غير محدد")
        if hotel not in groups:
            groups[hotel] = []
        groups[hotel].append(r)

    msg = MIMEMultipart()
    msg["From"] = EMAIL_ADDR
    msg["To"] = EMAIL_ADDR
    msg["Subject"] = f"طلبات بطاقات نسك - {datetime.now().strftime('%Y-%m-%d %H:%M')}"

    body = f"إجمالي الطلبات: {len(pending)}\n"
    body += f"عدد الفنادق: {len(groups)}\n\n"
    for hotel, items in groups.items():
        body += f"🏨 {hotel}: {len(items)} طلب\n"

    msg.attach(MIMEText(body, "plain", "utf-8"))

    for hotel, items in groups.items():
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["رقم", "جواز السفر", "الحالة", "السكن", "الدور", "الغرفة", "الموظف", "التاريخ"])
            for i, r in enumerate(items, 1):
                status = "لم يستلم" if r["status"] == "not_received" else "بدل فاقد"
                writer.writerow([i, r["passport"], status, r["hotel"], r["floor"], r["room"], r.get("employee", ""), r.get("date", "")])
            tmp_path = f.name

        with open(tmp_path, "rb") as f:
            attachment = MIMEBase("application", "octet-stream")
            attachment.set_payload(f.read())
            encoders.encode_base64(attachment)
            attachment.add_header("Content-Disposition", f"attachment; filename={hotel}.csv")
            msg.attach(attachment)
        os.unlink(tmp_path)

    try:
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        server.login(EMAIL_ADDR, EMAIL_PASS)
        server.send_message(msg)
        server.quit()
        print(f"[EMAIL] Sent {len(pending)} requests grouped into {len(groups)} hotels")
    except Exception as e:
        print(f"[EMAIL ERROR] {e}")
        with lock:
            requests_store = pending + requests_store
            save_requests()


def email_loop():
    while True:
        now = datetime.now()
        next_hour = (now + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
        sleep_sec = (next_hour - now).total_seconds()
        time.sleep(sleep_sec)
        send_email()


user_state = {}


@bot.message_handler(commands=["start", "help"])
def send_welcome(message):
    text = (
        "📋 *بوت طلبات بطاقات نسك*\n\n"
        "هذا البوت لجمع طلبات استلام بطاقات نسك للحجاج.\n\n"
        "🔹 `/new` — طلب جديد\n"
        "🔹 `/count` — عدد الطلبات المعلقة\n"
        "🔹 `/send` — إرسال الطلبات فوراً (للمشرف)"
    )
    bot.reply_to(message, text, parse_mode="Markdown")


@bot.message_handler(commands=["count"])
def send_count(message):
    with lock:
        count = len(requests_store)
    bot.reply_to(message, f"📊 عدد الطلبات المعلقة: *{count}*", parse_mode="Markdown")


@bot.message_handler(commands=["send"])
def force_send(message):
    bot.reply_to(message, "🔄 جاري إرسال الطلبات...")
    send_email()
    bot.reply_to(message, "✅ تم إرسال الطلبات!")


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
        bot.reply_to(message, "❌ رقم جواز غير صحيح. أرسل رقماً صحيحاً (مثال: G3386134)")
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
    bot.reply_to(message, "🔹 أرسل *رقم الدور* (مثال: 1):", parse_mode="Markdown")


@bot.message_handler(func=lambda m: user_state.get(m.chat.id, {}).get("step") == "floor")
def get_floor(message):
    cid = message.chat.id
    floor = message.text.strip()
    if not floor.isdigit():
        bot.reply_to(message, "❌ أرسل رقماً صحيحاً للدور")
        return
    user_state[cid]["floor"] = floor
    user_state[cid]["step"] = "room"
    bot.reply_to(message, "🔹 أرسل *رقم الغرفة* (مثال: 165):", parse_mode="Markdown")


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

    passport = user_state[cid]["passport"]
    status_text = "لم يستلم البطاقة" if user_state[cid]["status"] == "not_received" else "بدل فاقد"
    hotel = user_state[cid]["hotel"]
    floor = user_state[cid]["floor"]
    room_num = user_state[cid]["room"]

    confirm = (
        f"📋 *تأكيد الطلب*\n\n"
        f"🛂 *جواز:* `{passport}`\n"
        f"📌 *الحالة:* {status_text}\n"
        f"🏨 *السكن:* {hotel}\n"
        f"📶 *الدور:* {floor}\n"
        f"🚪 *الغرفة:* {room_num}\n"
        f"👤 *الموظف:* {user_state[cid]['employee']}\n\n"
        f"✅ للحفظ أرسل *تم* أو *تأكيد*"
    )
    bot.reply_to(message, confirm, parse_mode="Markdown")


@bot.message_handler(func=lambda m: user_state.get(m.chat.id, {}).get("step") == "confirm")
def confirm_handler(message):
    cid = message.chat.id
    text = message.text.strip()
    if text in ["تم", "تأكيد", "yes", "نعم"]:
        record = {
            "passport": user_state[cid]["passport"],
            "status": user_state[cid]["status"],
            "hotel": user_state[cid]["hotel"],
            "floor": user_state[cid]["floor"],
            "room": user_state[cid]["room"],
            "employee": user_state[cid]["employee"],
            "date": user_state[cid]["date"],
        }
        with lock:
            requests_store.append(record)
            save_requests()
            count = len(requests_store)
        del user_state[cid]
        bot.reply_to(message, f"✅ *تم حفظ الطلب!*\n\nإجمالي الطلبات المعلقة: {count}\n\n`/new` — طلب جديد", parse_mode="Markdown")
    else:
        del user_state[cid]
        bot.reply_to(message, "❌ تم إلغاء الطلب.\n\n`/new` — طلب جديد", parse_mode="Markdown")


def run_health_server():
    port = int(os.environ.get("PORT", 8080))
    server = http.server.HTTPServer(("0.0.0.0", port), http.server.SimpleHTTPRequestHandler)
    print(f"[HTTP] Health server on port {port}")
    server.serve_forever()


load_requests()
Thread(target=email_loop, daemon=True).start()
Thread(target=run_health_server, daemon=True).start()
print("Nusuk bot started...")
bot.infinity_polling()
