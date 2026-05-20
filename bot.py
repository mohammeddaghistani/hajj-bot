import telebot
import requests
import csv
import io
import os
import re
import time
import tempfile
from threading import Lock

SHEET_URL = "https://docs.google.com/spreadsheets/d/1Nzf0kGuhmwiAAcfGSl6xxkRYbtjGuaXujvKcq_oqgWg/export?format=csv"
MAPS_URL = "https://maps.app.goo.gl/1671T2oFdhV6UuVw5"

env_path = os.path.join(os.path.dirname(__file__), ".env")
if os.path.exists(env_path):
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
OCR_API_KEY = os.environ.get("OCR_API_KEY", "")

bot = telebot.TeleBot(BOT_TOKEN)
data = {}
lock = Lock()
last_refresh = 0

PASSPORT_REGEX = re.compile(r"[A-Z]\d{6,9}")
DIGITS_REGEX = re.compile(r"\d{7,10}")


def extract_passport(text):
    upper = text.upper()
    m = PASSPORT_REGEX.search(upper)
    if m:
        return m.group(), True
    m = DIGITS_REGEX.search(upper)
    if m:
        return m.group(), False
    return None, False


def lookup_passport_number(passport, with_letter):
    row = data.get(passport)
    if row:
        return row
    if passport.isdigit():
        digits = passport.lstrip("0")
        for p, r in data.items():
            pd = p[1:].lstrip("0")
            if pd == digits or pd == passport or pd == passport[1:]:
                return r
    return None


def ocr_image(image_path):
    if not OCR_API_KEY:
        return ""

    from PIL import Image, ImageEnhance, ImageFilter
    try:
        img = Image.open(image_path).convert("L").resize((1200, 900), Image.LANCZOS)
        img = ImageEnhance.Contrast(img).enhance(2.0).filter(ImageFilter.SHARPEN)
        img.save(image_path, "JPEG", quality=95)
    except Exception as e:
        print(f"Image preprocess error: {e}")

    with open(image_path, "rb") as f:
        resp = requests.post(
            "https://api.ocr.space/parse/image",
            files={"file": f},
            data={"apikey": OCR_API_KEY, "language": "eng", "OCREngine": "2"},
            timeout=30,
        )

    try:
        result = resp.json()
    except Exception:
        print(f"OCR API non-JSON response: {resp.text[:300]}")
        f = io.StringIO(resp.text)
        return f.read()

    if result.get("IsErroredOnProcessing"):
        print(f"OCR error: {result.get('ErrorMessage', '')}")
        return ""

    text = "\n".join(p["ParsedText"] for p in result.get("ParsedResults", []))
    print(f"OCR result: {text[:300]}")
    return text


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


def process_image_file(message, file_id):
    try:
        bot.reply_to(message, "🔄 جاري تحليل الصورة...")
        file_info = bot.get_file(file_id)
        downloaded = bot.download_file(file_info.file_path)

        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
            tmp.write(downloaded)
            tmp_path = tmp.name

        try:
            text = ocr_image(tmp_path)
        except Exception as e:
            print(f"OCR error: {e}")
            bot.send_message(message.chat.id, "❌ حدث خطأ أثناء قراءة الصورة.\nأرسل الرقم كتابةً.")
            return
        finally:
            os.unlink(tmp_path)

        if not text:
            bot.send_message(message.chat.id, "❌ لم أتمكن من قراءة الصورة.\nأرسل الرقم كتابةً.")
            return

        result, with_letter = extract_passport(text)
        if not result:
            bot.send_message(message.chat.id, "❌ لم أجد رقم جواز سفر في الصورة.\nأرسل الرقم كتابةً.")
            return

        with lock:
            row = lookup_passport_number(result, with_letter)

        if not row:
            bot.send_message(message.chat.id, f"❌ لم يتم العثور على رقم الجواز `{result}`", parse_mode="Markdown")
            return

        gender = gender_map.get(row["Gender"], row["Gender"])
        building, floor, room = parse_room(row["Room Number"])
    response = (
        f"✅ *تم العثور على الحاج/الحاجة*\n\n"
        f"👤 *الاسم:* {row['Name']}\n"
        f"⚧ *الجنس:* {gender}\n"
        f"🛂 *جواز السفر:* `{row['Passport Number']}\n"
        f"🏢 *المبنى:* {building}\n"
        f"📌 *الدور:* {floor}\n"
        f"🚪 *الغرفة:* {room}\n"
        f"👥 *المجموعة:* {row['Group']}\n"
        f"📍 [الموقع على الخريطة]({MAPS_URL})"
    )
    bot.reply_to(message, response, parse_mode="Markdown", disable_web_page_preview=False)


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
        f"👥 *المجموعة:* {row['Group']}\n"
        f"📍 [الموقع على الخريطة]({MAPS_URL})"
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
