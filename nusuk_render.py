"""
╔══════════════════════════════════════════════════════════════╗
║              NUSUK CARD MANAGEMENT SYSTEM v6.1              ║
║               Render Edition  —  Webhook Mode               ║
╚══════════════════════════════════════════════════════════════╝
"""

import telebot
import sqlite3
import os
import re
import json
import time
import logging
import http.server
import socketserver
from datetime import datetime
from typing import Optional
from google.oauth2.service_account import Credentials
import gspread

# ─────────────────────────────────────────────────────────────
# ENVIRONMENT
# ─────────────────────────────────────────────────────────────

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
DB_PATH   = os.path.join(os.path.dirname(__file__), "nusuk.db")
SHEET_ID  = os.environ.get("SHEET_ID", "1ct8MGpZi_3qE4EIfftmje9w_3HOX4HR33ffl6YRB054")
PORT      = int(os.environ.get("PORT", 8080))
RENDER_URL = os.environ.get("RENDER_EXTERNAL_URL", "").rstrip("/")
GOOGLE_SHEETS_KEY = os.environ.get("GOOGLE_SHEETS_KEY", "{}")
WEBHOOK_URL = f"{RENDER_URL}/webhook" if RENDER_URL else ""

CANCEL_WORDS = {"الغاء", "إلغاء", "cancel", "رجوع", "back", "✕", "❌"}

# ─────────────────────────────────────────────────────────────
# LOGGING
# ─────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  [%(levelname)s]  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("NusukBot")

# ─────────────────────────────────────────────────────────────
# DATABASE
# ─────────────────────────────────────────────────────────────

def init_db() -> None:
    with sqlite3.connect(DB_PATH) as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS requests (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                date      TEXT    NOT NULL,
                passport  TEXT    UNIQUE NOT NULL,
                status    TEXT    NOT NULL,
                hotel     TEXT    NOT NULL,
                floor     TEXT    NOT NULL,
                room      TEXT    NOT NULL,
                employee  TEXT    NOT NULL
            )
        """)
        db.commit()
    log.info("Database initialized")


def db_insert(record: dict) -> bool:
    try:
        with sqlite3.connect(DB_PATH) as db:
            db.execute(
                "INSERT OR IGNORE INTO requests VALUES (NULL,?,?,?,?,?,?,?)",
                (record["date"], record["passport"], record["status"],
                 record["hotel"],  record["floor"],   record["room"],
                 record["employee"]),
            )
            db.commit()
        return True
    except Exception as exc:
        log.error("DB insert error: %s", exc)
        return False


def db_passport_exists(passport: str) -> bool:
    with sqlite3.connect(DB_PATH) as db:
        return bool(db.execute(
            "SELECT 1 FROM requests WHERE passport = ?", (passport,)
        ).fetchone())


def db_count() -> int:
    with sqlite3.connect(DB_PATH) as db:
        return db.execute("SELECT COUNT(*) FROM requests").fetchone()[0]


def db_last_ten() -> list:
    with sqlite3.connect(DB_PATH) as db:
        return db.execute(
            "SELECT passport, status, hotel, floor, room "
            "FROM requests ORDER BY id DESC LIMIT 10"
        ).fetchall()


# ─────────────────────────────────────────────────────────────
# GOOGLE SHEETS
# ─────────────────────────────────────────────────────────────

def init_sheets() -> Optional[object]:
    try:
        key_data = json.loads(GOOGLE_SHEETS_KEY)
        if not key_data:
            log.warning("GOOGLE_SHEETS_KEY is empty — Sheets disabled")
            return None
        creds = Credentials.from_service_account_info(
            key_data, scopes=["https://www.googleapis.com/auth/spreadsheets"]
        )
        sheet = gspread.authorize(creds).open_by_key(SHEET_ID).sheet1
        log.info("Google Sheets connected ✓")
        return sheet
    except Exception as exc:
        log.warning("Google Sheets unavailable: %s", exc)
        return None


def sheets_append(sheet, record: dict) -> None:
    if sheet is None:
        return
    try:
        sheet.append_row([
            record["date"],     record["passport"], record["status"],
            record["hotel"],    record["floor"],    record["room"],
            record["employee"],
        ])
    except Exception as exc:
        log.error("Sheets append error: %s", exc)


# ─────────────────────────────────────────────────────────────
# UI HELPERS
# ─────────────────────────────────────────────────────────────

BRAND  = "◈  NUSUK  ◈"
DIVIDER = "▬" * 30

STATUS_LABELS = {
    "لم يستلم": ("📭", "Not Received"),
    "بدل فاقد": ("🔄", "Lost Card"),
}


def is_cancel(text: str) -> bool:
    return text.strip().lower().replace("✕", "").strip() in {w.lower() for w in CANCEL_WORDS}


def format_status(arabic: str) -> str:
    icon, english = STATUS_LABELS.get(arabic, ("❓", "Unknown"))
    return f"{icon}  {arabic}  ·  {english}"


def build_summary(s: dict) -> str:
    return (
        f"{BRAND}\n{DIVIDER}\n\n"
        f"📋  *تفاصيل الطلب  ·  Request Details*\n{DIVIDER}\n\n"
        f"  🆔  *Passport*    →  `{s['passport']}`\n"
        f"  🏷️  *Status*      →  {format_status(s['status'])}\n"
        f"  🏨  *Hotel*       →  {s['hotel']}\n"
        f"  🔢  *Floor*       →  {s['floor']}\n"
        f"  🚪  *Room*        →  {s['room']}\n"
        f"  👤  *Staff*       →  {s['employee']}\n"
        f"  📅  *Date*        →  {s['date']}\n{DIVIDER}"
    )


def step_header(num: int, total: int, ar: str, en: str) -> str:
    circles = ["①", "②", "③", "④", "⑤"]
    indicator = "  ".join(
        f"*{circles[i]}*" if i + 1 == num else circles[i]
        for i in range(total)
    )
    return f"{BRAND}\n{DIVIDER}\n\n{indicator}\n\n*{ar}*\n_{en}_\n\n{DIVIDER}\n\n"


def btn(label: str, data: str) -> telebot.types.InlineKeyboardButton:
    return telebot.types.InlineKeyboardButton(label, callback_data=data)


# ─────────────────────────────────────────────────────────────
# SESSION STATE
# ─────────────────────────────────────────────────────────────

sessions: dict = {}


def session_clear(chat_id: int) -> None:
    sessions.pop(chat_id, None)


def session_step(chat_id: int) -> Optional[str]:
    s = sessions.get(chat_id)
    return s["step"] if s else None


# ─────────────────────────────────────────────────────────────
# BOT INSTANCE
# ─────────────────────────────────────────────────────────────

bot   = telebot.TeleBot(BOT_TOKEN)
sheet = init_sheets()
init_db()


# ─────────────────────────────────────────────────────────────
# MAIN MENU
# ─────────────────────────────────────────────────────────────

def send_main_menu(chat_id: int, message_id: int = None) -> None:
    keyboard = telebot.types.InlineKeyboardMarkup(row_width=1)
    keyboard.add(
        btn("🆕  طلب بطاقة جديدة  ·  New Card Request",   "new_request"),
        btn("📊  إجمالي الطلبات   ·  Total Requests",      "view_count"),
        btn("📜  آخر ١٠ طلبات    ·  Last 10 Records",      "view_history"),
    )
    text = (
        f"{BRAND}\n{DIVIDER}\n\n"
        f"*نظام إدارة بطاقات نُسك*\n_Nusuk Card Management System_\n\n{DIVIDER}\n\n"
        f"🆕  *طلب جديد* — تسجيل حاج جديد\n"
        f"📊  *الإحصاءات* — عدد الطلبات المسجّلة\n"
        f"📜  *السجلات* — آخر عشرة طلبات\n\n{DIVIDER}\n"
        f"_اختر الخيار المناسب_ · _Select an option_"
    )
    if message_id:
        bot.edit_message_text(text, chat_id, message_id,
                              parse_mode="Markdown", reply_markup=keyboard)
    else:
        bot.send_message(chat_id, text,
                         parse_mode="Markdown", reply_markup=keyboard)


# ─────────────────────────────────────────────────────────────
# COMMAND HANDLERS
# ─────────────────────────────────────────────────────────────

@bot.message_handler(commands=["start", "menu"])
def cmd_start(message):
    session_clear(message.chat.id)
    send_main_menu(message.chat.id)


# ─────────────────────────────────────────────────────────────
# CALLBACK HANDLERS
# ─────────────────────────────────────────────────────────────

CALLBACK_IDS = {
    "new_request", "view_count", "view_history", "back_to_menu",
    "status_not_received", "status_lost_card",
    "confirm_ok", "confirm_cancel", "new_after_save",
}


@bot.callback_query_handler(func=lambda c: c.data in CALLBACK_IDS)
def handle_callback(call):
    chat_id    = call.message.chat.id
    message_id = call.message.id
    bot.answer_callback_query(call.id)

    if call.data == "back_to_menu":
        session_clear(chat_id)
        send_main_menu(chat_id, message_id)
        return

    if call.data in ("new_request", "new_after_save"):
        sessions[chat_id] = {"step": "passport"}
        text = (
            step_header(1, 5, "جواز السفر", "Passport Number")
            + "أدخل رقم جواز السفر للحاج\n"
            + "Enter the pilgrim's passport number\n\n"
            + "📌  الصيغة: حرف إنجليزي + ٦–٩ أرقام\n"
            + "_Format: one letter + 6–9 digits_\n\n"
            + "مثال · Example:  `G3386134`\n\n"
            + f"{DIVIDER}\n✕  للإلغاء اكتب  cancel"
        )
        bot.edit_message_text(text, chat_id, message_id, parse_mode="Markdown")
        return

    if call.data == "view_count":
        total = db_count()
        keyboard = telebot.types.InlineKeyboardMarkup()
        keyboard.add(btn("←  رجوع  ·  Back", "back_to_menu"))
        bot.edit_message_text(
            f"{BRAND}\n{DIVIDER}\n\n📊  *الإحصاءات  ·  Statistics*\n{DIVIDER}\n\n"
            f"  📈  إجمالي الطلبات المسجّلة\n"
            f"  _Total Registered Requests_\n\n  *{total}*  طلب  ·  Request{'s' if total != 1 else ''}\n\n{DIVIDER}",
            chat_id, message_id, parse_mode="Markdown", reply_markup=keyboard
        )
        return

    if call.data == "view_history":
        records  = db_last_ten()
        keyboard = telebot.types.InlineKeyboardMarkup()
        keyboard.add(btn("←  رجوع  ·  Back", "back_to_menu"))
        lines = f"{BRAND}\n{DIVIDER}\n\n📜  *آخر ١٠ طلبات  ·  Last 10 Records*\n{DIVIDER}\n"
        if not records:
            lines += "\n📭  لا توجد سجلات بعد  ·  No records yet\n"
        else:
            for i, (psp, sta, htl, flr, rm) in enumerate(records, 1):
                icon, _ = STATUS_LABELS.get(sta, ("❓", ""))
                lines += f"\n`{i:02d}`  🆔 `{psp}`\n      {icon} {sta}  ·  🏨 {htl}  🔢{flr}  🚪{rm}\n"
        lines += f"\n{DIVIDER}"
        bot.edit_message_text(lines, chat_id, message_id,
                               parse_mode="Markdown", reply_markup=keyboard)
        return

    if call.data in ("status_not_received", "status_lost_card"):
        s = sessions.get(chat_id)
        if not s:
            send_main_menu(chat_id, message_id)
            return
        s["status"] = "لم يستلم" if call.data == "status_not_received" else "بدل فاقد"
        s["step"] = "hotel"
        text = (
            step_header(3, 5, "السكن", "Accommodation")
            + "أدخل اسم الفندق أو مكان الإقامة\n"
            + "Enter the hotel or accommodation name\n\n"
            + "مثال · Example:  فندق مكة جراند\n\n"
            + f"{DIVIDER}\n✕  للإلغاء اكتب  cancel"
        )
        bot.edit_message_text(text, chat_id, message_id, parse_mode="Markdown")
        return

    if call.data == "confirm_ok":
        s = sessions.get(chat_id)
        if not s:
            bot.edit_message_text("⚠️  انتهت الجلسة · Session expired", chat_id, message_id)
            send_main_menu(chat_id)
            return
        saved = db_insert(s)
        if saved:
            sheets_append(sheet, s)
        total = db_count()
        session_clear(chat_id)
        keyboard = telebot.types.InlineKeyboardMarkup(row_width=1)
        keyboard.add(
            btn("➕  طلب جديد  ·  New Request", "new_after_save"),
            btn("←  القائمة   ·  Main Menu",    "back_to_menu"),
        )
        bot.edit_message_text(
            f"{BRAND}\n{DIVIDER}\n\n✅  *تم الحفظ بنجاح  ·  Saved Successfully*\n{DIVIDER}\n\n"
            f"  🆔  `{s['passport']}`\n  🏷️  {format_status(s['status'])}\n"
            f"  🏨  {s['hotel']}  —  🔢 {s['floor']}  🚪 {s['room']}\n  👤  {s['employee']}\n  📅  {s['date']}\n\n{DIVIDER}\n"
            f"📊  *الإجمالي الكلي:  {total}  طلب*\n{DIVIDER}\n\n🙏  شكراً  ·  Thank You",
            chat_id, message_id, parse_mode="Markdown", reply_markup=keyboard
        )
        log.info("Saved: passport=%s employee=%s", s["passport"], s["employee"])
        return

    if call.data == "confirm_cancel":
        session_clear(chat_id)
        send_main_menu(chat_id, message_id)
        return


# ─────────────────────────────────────────────────────────────
# MULTI-STEP MESSAGE HANDLERS
# ─────────────────────────────────────────────────────────────

@bot.message_handler(func=lambda m: session_step(m.chat.id) == "passport")
def step_passport(message):
    chat_id = message.chat.id
    text    = message.text.strip()
    if is_cancel(text):
        session_clear(chat_id); send_main_menu(chat_id); return
    passport = text.upper()
    if not re.match(r"^[A-Z]\d{6,9}$", passport):
        bot.reply_to(message,
            "❌  *صيغة غير صحيحة  ·  Invalid Format*\n\n"
            "الصيغة الصحيحة: حرف إنجليزي + ٦–٩ أرقام\n"
            "_Format: one letter + 6–9 digits_\n\n"
            "مثال · Example:  `G3386134`", parse_mode="Markdown")
        return
    if db_passport_exists(passport):
        bot.reply_to(message,
            f"⚠️  *مسجّل مسبقاً  ·  Already Registered*\n\n"
            f"جواز  `{passport}`  موجود في قاعدة البيانات.\n"
            f"_This passport is already in the system._", parse_mode="Markdown")
        return
    sessions[chat_id]["passport"] = passport
    sessions[chat_id]["step"]     = "status"
    keyboard = telebot.types.InlineKeyboardMarkup(row_width=1)
    keyboard.add(
        btn("📭  لم يستلم البطاقة  ·  Not Received",     "status_not_received"),
        btn("🔄  بدل فاقد / تالفة  ·  Lost / Damaged Card", "status_lost_card"),
    )
    bot.reply_to(message,
        step_header(2, 5, "حالة البطاقة", "Card Status")
        + "اختر حالة بطاقة الحاج:\n_Select the pilgrim's card status:_",
        parse_mode="Markdown", reply_markup=keyboard)


@bot.message_handler(func=lambda m: session_step(m.chat.id) == "hotel")
def step_hotel(message):
    chat_id = message.chat.id
    text    = message.text.strip()
    if is_cancel(text):
        session_clear(chat_id); send_main_menu(chat_id); return
    if not text:
        bot.reply_to(message, "❌  يرجى إدخال اسم السكن  ·  Please enter accommodation name")
        return
    sessions[chat_id]["hotel"] = text
    sessions[chat_id]["step"]  = "floor"
    bot.reply_to(message,
        step_header(4, 5, "رقم الدور", "Floor Number")
        + "أدخل رقم الدور\nEnter the floor number\n\nمثال · Example:  `3`\n\n"
        + f"{DIVIDER}\n✕  للإلغاء اكتب  cancel", parse_mode="Markdown")


@bot.message_handler(func=lambda m: session_step(m.chat.id) == "floor")
def step_floor(message):
    chat_id = message.chat.id
    text    = message.text.strip()
    if is_cancel(text):
        session_clear(chat_id); send_main_menu(chat_id); return
    if not text.isdigit():
        bot.reply_to(message, "❌  أرقام فقط  ·  Numbers only (e.g. 3)")
        return
    sessions[chat_id]["floor"] = text
    sessions[chat_id]["step"]  = "room"
    bot.reply_to(message,
        step_header(5, 5, "رقم الغرفة", "Room Number")
        + "أدخل رقم الغرفة\nEnter the room number\n\nمثال · Example:  `215`\n\n"
        + f"{DIVIDER}\n✕  للإلغاء اكتب  cancel", parse_mode="Markdown")


@bot.message_handler(func=lambda m: session_step(m.chat.id) == "room")
def step_room(message):
    chat_id = message.chat.id
    text    = message.text.strip()
    if is_cancel(text):
        session_clear(chat_id); send_main_menu(chat_id); return
    if not text:
        bot.reply_to(message, "❌  يرجى إدخال رقم الغرفة  ·  Please enter room number")
        return
    s = sessions[chat_id]
    s["room"]     = text
    s["date"]     = datetime.now().strftime("%Y-%m-%d %H:%M")
    s["employee"] = " ".join(filter(None, [
        message.from_user.first_name,
        message.from_user.last_name,
    ])) or "Unknown"
    s["step"] = "confirm"
    keyboard = telebot.types.InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        btn("✅  تأكيد الحفظ  ·  Confirm", "confirm_ok"),
        btn("✕  إلغاء  ·  Cancel",         "confirm_cancel"),
    )
    bot.reply_to(message,
        build_summary(s) + "\n\n_يرجى مراجعة البيانات قبل الحفظ_\n_Please review before saving_",
        parse_mode="Markdown", reply_markup=keyboard)


# ─────────────────────────────────────────────────────────────
# WEBHOOK + HTTP SERVER
# ─────────────────────────────────────────────────────────────

class WebhookHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Nusuk Bot v6.1 — Running")

    def do_POST(self):
        if self.path == "/webhook":
            length = int(self.headers.get("Content-Length", 0))
            try:
                body = self.rfile.read(length)
                update = telebot.types.Update.de_json(json.loads(body))
                bot.process_new_updates([update])
            except Exception as e:
                log.error("Webhook error: %s", e)
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

    def log_message(self, format, *args):
        pass


# ─────────────────────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    bot.remove_webhook()
    time.sleep(0.5)

    if WEBHOOK_URL:
        for attempt in range(3):
            try:
                bot.set_webhook(url=WEBHOOK_URL)
                log.info("Webhook set → %s", WEBHOOK_URL)
                break
            except Exception as e:
                log.warning("Webhook attempt %d: %s", attempt + 1, e)
                time.sleep(2)
    else:
        log.warning("RENDER_EXTERNAL_URL not set — webhook disabled")

    socketserver.TCPServer.allow_reuse_address = True
    server = http.server.HTTPServer(("0.0.0.0", PORT), WebhookHandler)
    log.info("╔═══════════════════════════════════════════╗")
    log.info("║  NUSUK BOT v6.1  —  listening :%d     ║", PORT)
    log.info("╚═══════════════════════════════════════════╝")
    server.serve_forever()
