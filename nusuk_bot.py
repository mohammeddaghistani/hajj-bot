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


def show_main_menu(chat_id):
    markup = telebot.types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        telebot.types.InlineKeyboardButton("📝 ١ - طلب جديد", callback_data="new"),
        telebot.types.InlineKeyboardButton("📊 ٢ - العدد", callback_data="count"),
        telebot.types.InlineKeyboardButton("🗂 ٣ - آخر الطلبات", callback_data="history"),
    )
    text = (
        "✨ *Nusuk Card Requests — طلبات بطاقات نسك* ✨\n\n"
        "Send a number or tap a button:\n"
        "ارسـل الرقم أو اضغط الزر:\n\n"
        "1️⃣ *New Request* — طلب جديد\n"
        "2️⃣ *Count* — عدد الطلبات\n"
        "3️⃣ *History* — آخر ١٠ طلبات"
    )
    bot.send_message(chat_id, text, parse_mode="Markdown", reply_markup=markup)


def go_home(chat_id):
    keyboard = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True)
    keyboard.add(telebot.types.KeyboardButton("🏠 القائمة الرئيسية"))
    bot.send_message(chat_id, "🔽", reply_markup=keyboard)


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


@bot.callback_query_handler(func=lambda c: c.data in ("new", "count", "history"))
def handle_callback(c):
    if c.data == "new":
        start_request(c.message)
    elif c.data == "count":
        send_count(c.message)
    elif c.data == "history":
        send_history(c.message)
    bot.answer_callback_query(c.id)


user_state = {}


@bot.message_handler(commands=["start", "help"])
def send_welcome(message):
    show_main_menu(message.chat.id)


@bot.message_handler(func=lambda m: m.text and m.text.strip() in ("1", "1️⃣") and m.chat.id not in user_state)
def num_new(message):
    start_request(message)


@bot.message_handler(func=lambda m: m.text and m.text.strip() in ("2", "2️⃣") and m.chat.id not in user_state)
def num_count(message):
    send_count(message)


@bot.message_handler(func=lambda m: m.text and m.text.strip() in ("3", "3️⃣") and m.chat.id not in user_state)
def num_history(message):
    send_history(message)


@bot.message_handler(func=lambda m: m.text and "رئيسية" in m.text and m.chat.id not in user_state)
def back_to_menu(message):
    show_main_menu(message.chat.id)


@bot.message_handler(commands=["count"])
def send_count(message):
    with lock:
        count = len(submitted)
    bot.reply_to(message, f"📊 *Count / العدد*\n\nTotal requests / إجمالي الطلبات: *{count}*", parse_mode="Markdown")
    go_home(message.chat.id)


@bot.message_handler(commands=["history"])
def send_history(message):
    with lock:
        recent = submitted[-10:]
    if not recent:
        bot.reply_to(message, "📭 *No requests yet* — لا توجد طلبات بعد")
        go_home(message.chat.id)
        return
    lines = ["🗂 *Last 10 — آخر ١٠ طلبات:*\n"]
    for r in reversed(recent):
        s = "Not received / لم يستلم" if r["status"] == "not_received" else "Lost / بدل فاقد"
        lines.append(f"`{r['passport']}` • {s} • {r['hotel']} • F{r['floor']} R{r['room']}")
    bot.reply_to(message, "\n".join(lines), parse_mode="Markdown")
    go_home(message.chat.id)


@bot.message_handler(commands=["new"])
def start_request(message=None):
    cid = message.chat.id if message else None
    if not cid:
        return
    user_state[cid] = {"step": "passport"}
    bot.send_message(cid,
        "🛂 *Step 1/5 — Passport Number*\n"
        "الرجاء إرسال رقم جواز السفر (مثال: G3386134)\n\n"
        "Send the pilgrim's passport number (e.g. G3386134):",
        parse_mode="Markdown")


@bot.message_handler(func=lambda m: user_state.get(m.chat.id, {}).get("step") == "passport")
def get_passport(message):
    cid = message.chat.id
    passport = message.text.strip().upper()
    if not re.match(r"^[A-Z]\d{6,9}$", passport):
        bot.reply_to(message,
            "❌ *Invalid format / صيغة غير صحيحة*\n"
            "Use letter + 6-9 digits / استخدم حرف + ٦-٩ أرقام\n"
            "Example: G3386134")
        return
    user_state[cid]["passport"] = passport
    user_state[cid]["step"] = "status"
    markup = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True, row_width=2)
    markup.add(
        telebot.types.KeyboardButton("📭 لم يستلم"),
        telebot.types.KeyboardButton("📭 Not Received"),
        telebot.types.KeyboardButton("🔄 بدل فاقد"),
        telebot.types.KeyboardButton("🔄 Lost / Replace"),
    )
    bot.reply_to(message,
        "📌 *Step 2/5 — Card Status / حالة البطاقة*\n\n"
        "Choose the status / اختر الحالة:",
        reply_markup=markup, parse_mode="Markdown")


@bot.message_handler(func=lambda m: user_state.get(m.chat.id, {}).get("step") == "status")
def get_status(message):
    cid = message.chat.id
    text = message.text.strip()
    if any(w in text for w in ["لم يستلم", "Not Received", "not received"]):
        user_state[cid]["status"] = "not_received"
    elif any(w in text for w in ["فاقد", "بدل", "Lost", "Replace", "lost"]):
        user_state[cid]["status"] = "lost"
    else:
        bot.reply_to(message, "❌ Please use the buttons / استخدم الأزرار من فضلك")
        return
    user_state[cid]["step"] = "hotel"
    bot.reply_to(message,
        "🏨 *Step 3/5 — Accommodation / السكن*\n\n"
        "Send the accommodation or hotel name:\n"
        "أرسل اسم السكن أو الفندق:",
        parse_mode="Markdown", reply_markup=telebot.types.ReplyKeyboardRemove())


@bot.message_handler(func=lambda m: user_state.get(m.chat.id, {}).get("step") == "hotel")
def get_hotel(message):
    cid = message.chat.id
    hotel = message.text.strip()
    if not hotel:
        bot.reply_to(message, "❌ Send the accommodation name / أرسل اسم السكن")
        return
    user_state[cid]["hotel"] = hotel
    user_state[cid]["step"] = "floor"
    bot.reply_to(message,
        "📶 *Step 4/5 — Floor / الدور*\n\n"
        "Send the floor number:\n"
        "أرسل رقم الدور (مثال: 1):",
        parse_mode="Markdown")


@bot.message_handler(func=lambda m: user_state.get(m.chat.id, {}).get("step") == "floor")
def get_floor(message):
    cid = message.chat.id
    floor = message.text.strip()
    if not floor.isdigit():
        bot.reply_to(message, "❌ Enter a valid number / أدخل رقماً صحيحاً")
        return
    user_state[cid]["floor"] = floor
    user_state[cid]["step"] = "room"
    bot.reply_to(message,
        "🚪 *Step 5/5 — Room / الغرفة*\n\n"
        "Send the room number:\n"
        "أرسل رقم الغرفة (مثال: 165):",
        parse_mode="Markdown")


@bot.message_handler(func=lambda m: user_state.get(m.chat.id, {}).get("step") == "room")
def get_room(message):
    cid = message.chat.id
    room = message.text.strip()
    if not room:
        bot.reply_to(message, "❌ Enter the room number / أدخل رقم الغرفة")
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
    confirm = (
        f"📋 *Confirm / تأكيد الطلب*\n\n"
        f"🛂 Passport / الجواز: `{s['passport']}`\n"
        f"📌 Status / الحالة: {st}\n"
        f"🏨 Accommodation / السكن: {s['hotel']}\n"
        f"📶 Floor / الدور: {s['floor']}\n"
        f"🚪 Room / الغرفة: {s['room']}\n"
        f"👤 Staff / الموظف: {s['employee']}\n\n"
        f"✅ Send *Confirm / تم* to save\n"
        f"❌ Send *Cancel / إلغاء* to cancel"
    )
    bot.reply_to(message, confirm, parse_mode="Markdown")


@bot.message_handler(func=lambda m: user_state.get(m.chat.id, {}).get("step") == "confirm")
def confirm_handler(message):
    cid = message.chat.id
    text = message.text.strip()
    if text in ["تم", "تأكيد", "Confirm", "confirm", "yes", "نعم"]:
        s = user_state[cid]
        record = {k: s[k] for k in ("passport", "status", "hotel", "floor", "room", "employee", "date")}
        ok = append_to_sheets(record)
        with lock:
            submitted.append(record)
            save_submitted()
            total = len(submitted)
        del user_state[cid]
        if ok:
            bot.reply_to(message,
                f"✅ *Saved! / تم الحفظ!*\n\n"
                f"Total / الإجمالي: {total}\n\n"
                f"Send 1️⃣ for new request or / تفضل بطلب جديد")
        else:
            bot.reply_to(message,
                f"⚠️ *Saved locally / حفظ محلياً*\n"
                f"Sheets offline, will retry later.\n"
                f"سيتم إعادة المحاولة لاحقاً.\n\n"
                f"Total / الإجمالي: {total}")
    elif text in ["إلغاء", "Cancel", "cancel"]:
        del user_state[cid]
        bot.reply_to(message, "❌ *Cancelled / ملغي*")
    else:
        bot.reply_to(message, 'Send *Confirm / تم* to save or *Cancel / إلغاء* to cancel')
        return
    go_home(message.chat.id)


if __name__ == "__main__":
    load_submitted()
    print("Nusuk bot started...")
    bot.remove_webhook()
    time.sleep(1)
    bot.set_webhook(url=f"{WEBHOOK_URL}/webhook")
    print(f"Webhook set to {WEBHOOK_URL}/webhook")
    app.run(host="0.0.0.0", port=PORT)
