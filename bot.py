import telebot
import requests
import csv
import io
import os
import time
from threading import Lock

SHEET_URL = "https://docs.google.com/spreadsheets/d/1Nzf0kGuhmwiAAcfGSl6xxkRYbtjGuaXujvKcq_oqgWg/export?format=csv"

env_path = os.path.join(os.path.dirname(__file__), ".env")
if os.path.exists(env_path):
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")

bot = telebot.TeleBot(BOT_TOKEN)
data = {}
lock = Lock()
last_refresh = 0


def load_data():
    global data, last_refresh
    resp = requests.get(SHEET_URL, timeout=30)
    resp.raise_for_status()
    reader = csv.DictReader(io.StringIO(resp.text))
    lookup = {}
    for row in reader:
        passport = row.get("Passport Number", "").strip().upper()
        if passport:
            lookup[passport] = row
    with lock:
        data = lookup
        last_refresh = time.time()
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Loaded {len(data)} passports")


def refresh_loop():
    while True:
        try:
            load_data()
        except Exception as e:
            print(f"Refresh error: {e}")
        time.sleep(300)


def parse_room(room_str):
    parts = room_str.split("_")
    if len(parts) >= 5 and parts[0] == "ALRAIS2":
        floor = parts[2]
        room = parts[4]
        return f"المبنى الرئيسي", f"الدور {floor}", f"غرفة {room}"
    return "", "", room_str


gender_map = {"male": "ذكر", "female": "أنثى"}


@bot.message_handler(commands=["start", "help"])
def send_welcome(message):
    text = (
        "🏨 *بوت الاستعلام عن إسكان الحجاج*\n\n"
        "أرسل رقم *جواز السفر* للحصول على معلومات الغرفة.\n\n"
        "مثال: `G3386134`\n\n"
        "🔹 `/stats` — عدد الحجاج المسجلين"
    )
    bot.reply_to(message, text, parse_mode="Markdown")


@bot.message_handler(commands=["refresh"])
def refresh_data(message):
    try:
        load_data()
        bot.reply_to(message, f"✅ تم تحديث البيانات ({len(data)} جواز سفر)")
    except Exception as e:
        bot.reply_to(message, f"❌ فشل التحديث: {e}")


@bot.message_handler(commands=["stats"])
def send_stats(message):
    with lock:
        count = len(data)
    bot.reply_to(message, f"📊 إجمالي الحجاج المسجلين: *{count}*", parse_mode="Markdown")


@bot.message_handler(func=lambda m: True)
def lookup_passport(message):
    passport = message.text.strip().upper()
    with lock:
        row = data.get(passport)

    if not row:
        bot.reply_to(message, "❌ *لم يتم العثور* على هذا الرقم\n\nتأكد من كتابة رقم جواز السفر بشكل صحيح.", parse_mode="Markdown")
        return

    gender = gender_map.get(row["Gender"], row["Gender"])
    building, floor, room = parse_room(row["Room Number"])

    response = (
        f"✅ *تم العثور على الحاج/الحاجة*\n\n"
        f"👤 *الاسم:* {row['Name']}\n"
        f"⚧ *الجنس:* {gender}\n"
        f"🛂 *جواز السفر:* `{row['Passport Number']}`\n"
        f"🏢 *المبنى:* {building}\n"
        f"📌 *الدور:* {floor}\n"
        f"🚪 *الغرفة:* {room}\n"
        f"👥 *المجموعة:* {row['Group']}"
    )
    bot.reply_to(message, response, parse_mode="Markdown")


def start_http():
    import http.server
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"OK")
        def log_message(self, *a): pass
    server = http.server.HTTPServer(("0.0.0.0", int(os.environ.get("PORT", 8080))), Handler)
    server.serve_forever()


if __name__ == "__main__":
    import threading
    threading.Thread(target=refresh_loop, daemon=True).start()
    threading.Thread(target=start_http, daemon=True).start()
    load_data()
    print("Bot started...")
    bot.infinity_polling()
