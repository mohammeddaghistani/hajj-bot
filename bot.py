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


LANG = {
    "ar": "🇸🇦 العربية",
    "en": "🇬🇧 English",
    "ur": "🇵🇰 اردو",
    "ha": "🇳🇬 Hausa",
}

LANG_NAMES = {
    "ALRAIS2": {"ar": "مبنى الرايس 2", "en": "Alrais 2 Building", "ur": "الرايس 2 عمارت", "ha": "Ginin Alrais 2"},
    "AJWAD": {"ar": "مبنى الجواد", "en": "Ajwad Building", "ur": "اجود عمارت", "ha": "Ginin Ajwad"},
    "ALRAIS3": {"ar": "مبنى الرايس 3", "en": "Alrais 3 Building", "ur": "الرايس 3 عمارت", "ha": "Ginin Alrais 3"},
    "DURRA": {"ar": "مبنى الدرة", "en": "Durra Building", "ur": "درہ عمارت", "ha": "Ginin Durra"},
    "MAN.SITTEEN": {"ar": "برج المنار", "en": "Manar Tower", "ur": "منار ٹاور", "ha": "Hasumiyar Manar"},
    "NUZHA1": {"ar": "مبنى النزهة 1", "en": "Nuzha 1 Building", "ur": "نزہہ 1 عمارت", "ha": "Ginin Nuzha 1"},
    "NUZHA2": {"ar": "مبنى النزهة 2", "en": "Nuzha 2 Building", "ur": "نزہہ 2 عمارت", "ha": "Ginin Nuzha 2"},
    "RAIES1": {"ar": "مبنى الرايس 1", "en": "Alrais 1 Building", "ur": "الرايس 1 عمارت", "ha": "Ginin Alrais 1"},
    "THARAWAT2": {"ar": "مبنى الثروات 2", "en": "Tharawat 2 Building", "ur": "ثروات 2 عمارت", "ha": "Ginin Tharawat 2"},
    "THARAWAT3": {"ar": "مبنى الثروات 3", "en": "Tharawat 3 Building", "ur": "ثروات 3 عمارت", "ha": "Ginin Tharawat 3"},
    "THARAWAT4": {"ar": "مبنى الثروات 4", "en": "Tharawat 4 Building", "ur": "ثروات 4 عمارت", "ha": "Ginin Tharawat 4"},
    "THARAWAT5": {"ar": "مبنى الثروات 5", "en": "Tharawat 5 Building", "ur": "ثروات 5 عمارت", "ha": "Ginin Tharawat 5"},
    "THARAWAT6": {"ar": "مبنى الثروات 6", "en": "Tharawat 6 Building", "ur": "ثروات 6 عمارت", "ha": "Ginin Tharawat 6"},
}

GENDER = {
    "male": {"ar": "ذكر", "en": "Male", "ur": "مرد", "ha": "Namiji"},
    "female": {"ar": "أنثى", "en": "Female", "ur": "عورت", "ha": "Mace"},
}

T = {
    "found": {
        "ar": "✅ تم العثور على الحاج/الحاجة",
        "en": "✅ Pilgrim found",
        "ur": "✅ حاجی مل گیا",
        "ha": "✅ An samo mahajji",
    },
    "name": {
        "ar": "الاسم",
        "en": "Name",
        "ur": "نام",
        "ha": "Suna",
    },
    "gender": {
        "ar": "الجنس",
        "en": "Gender",
        "ur": "جنس",
        "ha": "Jinsi",
    },
    "passport": {
        "ar": "جواز السفر",
        "en": "Passport",
        "ur": "پاسپورٹ",
        "ha": "Fasfo",
    },
    "building": {
        "ar": "المبنى",
        "en": "Building",
        "ur": "عمارت",
        "ha": "Gini",
    },
    "floor": {
        "ar": "الدور",
        "en": "Floor",
        "ur": "منزل",
        "ha": "Hawa",
    },
    "room": {
        "ar": "الغرفة",
        "en": "Room",
        "ur": "کمرہ",
        "ha": "Daki",
    },
    "group": {
        "ar": "المجموعة",
        "en": "Group",
        "ur": "گروپ",
        "ha": "Rukuni",
    },
    "map": {
        "ar": "الموقع على الخريطة",
        "en": "Location on map",
        "ur": "نقشے پر مقام",
        "ha": "Wuri akan taswira",
    },
    "not_found": {
        "ar": "❌ لم يتم العثور على هذا الرقم\nتأكد من كتابة رقم جواز السفر بشكل صحيح.",
        "en": "❌ Passport not found\nPlease check the passport number and try again.",
        "ur": "❌ پاسپورٹ نمبر نہیں ملا\nبراہ کرم پاسپورٹ نمبر چیک کریں۔",
        "ha": "❌ Ba a sami lambar fasfo ba\nDa fatan a duba lambar fasfo.",
    },
    "not_found_result": {
        "ar": "❌ لم يتم العثور على رقم الجواز",
        "en": "❌ Passport number not found",
        "ur": "❌ پاسپورٹ نمبر نہیں ملا",
        "ha": "❌ Ba a sami lambar fasfo ba",
    },
    "ocr_processing": {
        "ar": "🔄 جاري تحليل الصورة...",
        "en": "🔄 Analyzing image...",
        "ur": "🔄 تصویر کا تجزیہ کیا جا رہا ہے...",
        "ha": "🔄 Ana nazarin hoton...",
    },
    "ocr_error": {
        "ar": "❌ حدث خطأ أثناء قراءة الصورة.\nأرسل الرقم كتابةً.",
        "en": "❌ Error reading image.\nPlease send the number as text.",
        "ur": "❌ تصویر پڑھنے میں خرابی۔\nبراہ کرم نمبر بطور تحریر بھیجیں۔",
        "ha": "❌ Kuskure yayin karanta hoton.\nDa fatan a aika lambar a rubuce.",
    },
    "ocr_no_text": {
        "ar": "❌ لم أتمكن من قراءة الصورة.\nأرسل الرقم كتابةً.",
        "en": "❌ Could not read the image.\nPlease send the number as text.",
        "ur": "❌ تصویر نہیں پڑھ سکا۔\nبراہ کرم نمبر بطور تحریر بھیجیں۔",
        "ha": "❌ An kasa karanta hoton.\nDa fatan a aika lambar a rubuce.",
    },
    "ocr_no_passport": {
        "ar": "❌ لم أجد رقم جواز سفر في الصورة.\nأرسل الرقم كتابةً.",
        "en": "❌ No passport number found in the image.\nPlease send the number as text.",
        "ur": "❌ تصویر میں پاسپورٹ نمبر نہیں ملا۔\nبراہ کرم نمبر بطور تحریر بھیجیں۔",
        "ha": "❌ Ba a sami lambar fasfo a hoton ba.\nDa fatan a aika lambar a rubuce.",
    },
    "general_error": {
        "ar": "❌ حدث خطأ. أرسل الرقم كتابةً.",
        "en": "❌ Something went wrong. Please send the number as text.",
        "ur": "❌ کچھ غلط ہو گیا۔ براہ کرم نمبر بطور تحریر بھیجیں۔",
        "ha": "❌ Wani kuskure ya faru. Da fatan a aika lambar a rubuce.",
    },
    "welcome": {
        "ar": "🏨 *بوت الاستعلام عن إسكان الحجاج*\n\n📱 أرسل رقم *جواز السفر* نصاً\n🖼 أو أرسل *صورة* تحتوي على رقم الجواز\n\nمثال: `G3386134`\n\n🔹 `/lang` — تغيير اللغة\n🔹 `/stats` — عدد الحجاج المسجلين",
        "en": "🏨 *Hajj Pilgrim Accommodation Bot*\n\n📱 Send a *passport number* as text\n🖼 Or send a *photo* containing the passport number\n\nExample: `G3386134`\n\n🔹 `/lang` — Change language\n🔹 `/stats` — Total registered pilgrims",
        "ur": "🏨 *حجاج کے قیام کا بوت*\n\n📱 *پاسپورٹ نمبر* بطور تحریر بھیجیں\n🖼 یا *تصویر* بھیجیں جس میں پاسپورٹ نمبر ہو\n\nمثال: `G3386134`\n\n🔹 `/lang` — زبان تبدیل کریں\n🔹 `/stats` — کل رجسٹرڈ حجاج",
        "ha": "🏨 *Bot na matsugunin mahajja*\n\n📱 Aika lambar *fasfo* a rubuce\n🖼 Ko aika *hoto* mai lambar fasfo\n\nMisali: `G3386134`\n\n🔹 `/lang` — Canja harshe\n🔹 `/stats` — Adadin mahajja",
    },
    "stats": {
        "ar": "📊 إجمالي الحجاج المسجلين:",
        "en": "📊 Total registered pilgrims:",
        "ur": "📊 کل رجسٹرڈ حجاج:",
        "ha": "📊 Adadin mahajja da suka yi rijista:",
    },
    "refresh_done": {
        "ar": "✅ تم تحديث البيانات",
        "en": "✅ Data updated",
        "ur": "✅ ڈیٹا اپ ڈیٹ ہو گیا",
        "ha": "✅ An sabunta bayanai",
    },
    "refresh_error": {
        "ar": "❌ فشل التحديث",
        "en": "❌ Update failed",
        "ur": "❌ اپ ڈیٹ ناکام",
        "ha": "❌ An kasa sabuntawa",
    },
    "send_photo_or_text": {
        "ar": "أرسل صورة أو رقم جواز السفر كتابةً.",
        "en": "Send an image or passport number as text.",
        "ur": "تصویر یا پاسپورٹ نمبر بطور تحریر بھیجیں۔",
        "ha": "Aika hoto ko lambar fasfo a rubuce.",
    },
    "lang_prompt": {
        "ar": "🌐 اختر اللغة:",
        "en": "🌐 Choose your language:",
        "ur": "🌐 اپنی زبان منتخب کریں:",
        "ha": "🌐 Zaɓi harshenka:",
    },
    "lang_changed": {
        "ar": "✅ تم تغيير اللغة إلى",
        "en": "✅ Language changed to",
        "ur": "✅ زبان تبدیل کر دی گئی",
        "ha": "✅ An canza harshe zuwa",
    },
    "multiple": {
        "ar": "⚠️ يوجد أكثر من حاج بهذه الأرقام:\nالرجاء إرسال رقم الجواز كاملاً مع الحرف",
        "en": "⚠️ Multiple pilgrims found with these digits:\nPlease send the full passport number with the letter",
        "ur": "⚠️ ان اعداد کے ساتھ ایک سے زیادہ حاجی ملے:\nبراہ کرم پاسپورٹ نمبر حرف سمیت بھیجیں",
        "ha": "⚠️ An sami mahajja fiye da ɗaya da waɗannan lambobin:\nDa fatan a aika cikakken lambar fasfo tare da harafin",
    },
}

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
user_lang = {}

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
        return [row]
    if passport.isdigit():
        digits = passport.lstrip("0")
        matches = []
        for p, r in data.items():
            pd = p[1:].lstrip("0")
            if pd == digits or pd == passport or pd == passport[1:]:
                matches.append(r)
        return matches
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


def get_lang(cid):
    return user_lang.get(cid, "ar")


def tr(key, lang):
    return T[key].get(lang, T[key]["ar"])


def parse_room(room_str, lang="ar"):
    parts = room_str.split("_")
    if len(parts) >= 5:
        building_code = parts[0]
        floor = parts[2]
        room = parts[4]
        name = LANG_NAMES.get(building_code, {}).get(lang, building_code)
        maps_url = BUILDING_MAPS.get(building_code, "")
        return name, f"{tr('floor', lang)} {floor}", f"{tr('room', lang)} {room}", maps_url
    return room_str, "", "", ""


gender_map = {"male": "ذكر", "female": "أنثى"}


def process_image_file(message, file_id):
    cid = message.chat.id
    lang = get_lang(cid)
    bot.reply_to(message, tr("ocr_processing", lang))
    try:
        file_info = bot.get_file(file_id)
        downloaded = bot.download_file(file_info.file_path)

        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
            tmp.write(downloaded)
            tmp_path = tmp.name

        try:
            text = ocr_image(tmp_path)
        except Exception as e:
            print(f"OCR error: {e}")
            bot.send_message(cid, tr("ocr_error", lang))
            return
        finally:
            os.unlink(tmp_path)

        if not text:
            bot.send_message(cid, tr("ocr_no_text", lang))
            return

        result, with_letter = extract_passport(text)
        if not result:
            bot.send_message(cid, tr("ocr_no_passport", lang))
            return

        with lock:
            matches = lookup_passport_number(result, with_letter)

        if not matches:
            bot.send_message(cid, f"{tr('not_found_result', lang)} `{result}`", parse_mode="Markdown")
            return

        if len(matches) > 1:
            bot.send_message(cid, tr("multiple", lang))
            return

        row = matches[0]

        gender = GENDER.get(row["Gender"], {}).get(lang, row["Gender"])
        building, floor, room, maps_url = parse_room(row["Room Number"], lang)

        response = (
            f"{tr('found', lang)}\n\n"
            f"👤 *{tr('name', lang)}:* {row['Name']}\n"
            f"⚧ *{tr('gender', lang)}:* {gender}\n"
            f"🛂 *{tr('passport', lang)}:* `{row['Passport Number']}`\n"
            f"🏢 *{tr('building', lang)}:* {building}\n"
            f"📌 *{tr('floor', lang)}:* {floor}\n"
            f"🚪 *{tr('room', lang)}:* {room}\n"
            f"👥 *{tr('group', lang)}:* {row['Group']}"
        )
        if maps_url:
            response += f"\n📍 [{tr('map', lang)}]({maps_url})"
        bot.reply_to(message, response, parse_mode="Markdown", disable_web_page_preview=False)

    except Exception as e:
        print(f"Image error: {e}")
        try:
            bot.send_message(cid, tr("general_error", lang))
        except:
            pass


@bot.message_handler(content_types=["photo"])
def handle_photo(message):
    process_image_file(message, message.photo[-1].file_id)


@bot.message_handler(content_types=["document"])
def handle_document(message):
    lang = get_lang(message.chat.id)
    if message.document and message.document.mime_type and message.document.mime_type.startswith("image/"):
        process_image_file(message, message.document.file_id)
    else:
        bot.reply_to(message, tr("send_photo_or_text", lang))


@bot.message_handler(commands=["start", "help"])
def send_welcome(message):
    lang = get_lang(message.chat.id)
    bot.reply_to(message, tr("welcome", lang), parse_mode="Markdown")


@bot.message_handler(commands=["lang"])
def choose_lang(message):
    cid = message.chat.id
    lang = get_lang(cid)
    markup = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    for code, name in LANG.items():
        markup.add(telebot.types.KeyboardButton(name))
    bot.reply_to(message, tr("lang_prompt", lang), reply_markup=markup)


@bot.message_handler(commands=["refresh"])
def refresh_data(message):
    lang = get_lang(message.chat.id)
    try:
        load_data()
        bot.reply_to(message, f"{tr('refresh_done', lang)} ({len(data)})")
    except Exception as e:
        bot.reply_to(message, f"{tr('refresh_error', lang)}: {e}")


@bot.message_handler(commands=["stats"])
def send_stats(message):
    lang = get_lang(message.chat.id)
    with lock:
        count = len(data)
    bot.reply_to(message, f"{tr('stats', lang)} *{count}*", parse_mode="Markdown")


@bot.message_handler(func=lambda m: m.text in LANG.values())
def set_lang(message):
    cid = message.chat.id
    for code, name in LANG.items():
        if message.text == name:
            user_lang[cid] = code
            bot.reply_to(message, f"{tr('lang_changed', code)} {name}", reply_markup=telebot.types.ReplyKeyboardRemove())
            return


@bot.message_handler(func=lambda m: True)
def lookup_passport(message):
    cid = message.chat.id
    lang = get_lang(cid)
    passport = message.text.strip().upper()
    is_digits = passport.isdigit()
    with lock:
        if is_digits:
            matches = lookup_passport_number(passport, False)
            if not matches:
                row = None
            elif len(matches) > 1:
                bot.reply_to(message, tr("multiple", lang))
                return
            else:
                row = matches[0]
        else:
            row = data.get(passport)

    if not row:
        bot.reply_to(message, tr("not_found", lang), parse_mode="Markdown")
        return

    gender = GENDER.get(row["Gender"], {}).get(lang, row["Gender"])
    building, floor, room, maps_url = parse_room(row["Room Number"], lang)

    response = (
        f"{tr('found', lang)}\n\n"
        f"👤 *{tr('name', lang)}:* {row['Name']}\n"
        f"⚧ *{tr('gender', lang)}:* {gender}\n"
        f"🛂 *{tr('passport', lang)}:* `{row['Passport Number']}`\n"
        f"🏢 *{tr('building', lang)}:* {building}\n"
        f"📌 *{tr('floor', lang)}:* {floor}\n"
        f"🚪 *{tr('room', lang)}:* {room}\n"
        f"👥 *{tr('group', lang)}:* {row['Group']}"
    )
    if maps_url:
        response += f"\n📍 [{tr('map', lang)}]({maps_url})"
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
