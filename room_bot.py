"""
HAJJ ROOM BOT  —  Module (imported by nusuk_render.py)
Lookup pilgrim rooms by passport number in Google Sheets.
"""

import os, re, json, logging
from typing import Optional
from google.oauth2.service_account import Credentials
import gspread

log = logging.getLogger("RoomBot")

ROOM_BOT_TOKEN = os.environ.get("ROOM_BOT_TOKEN", "")
SHEET_ID = os.environ.get("SHEET_ID", "1ct8MGpZi_3qE4EIfftmje9w_3HOX4HR33ffl6YRB054")
GOOGLE_SHEETS_KEY = os.environ.get("GOOGLE_SHEETS_KEY", "{}")
ADMIN_IDS = set(filter(None, os.environ.get("ADMIN_IDS", "").split(",")))

_rooms_ws: Optional[object] = None
_rooms_init_done = False


def _rooms_init():
    global _rooms_ws, _rooms_init_done
    if _rooms_init_done: return
    _rooms_init_done = True
    try:
        key_data = json.loads(GOOGLE_SHEETS_KEY)
        if not key_data: return
        creds = Credentials.from_service_account_info(key_data, scopes=["https://www.googleapis.com/auth/spreadsheets"])
        sh = gspread.authorize(creds).open_by_key(SHEET_ID)
        try:
            _rooms_ws = sh.worksheet("Rooms")
        except gspread.WorksheetNotFound:
            _rooms_ws = sh.add_worksheet("Rooms", 1000, 4)
            _rooms_ws.append_row(["Passport Number", "Hotel", "Floor", "Room"])
        log.info("Rooms sheet ready")
    except Exception as e:
        log.warning("Rooms sheet unavailable: %s", e)


def lookup(passport: str) -> Optional[dict]:
    _rooms_init()
    if not _rooms_ws: return None
    try:
        for row in _rooms_ws.get_all_values()[1:]:
            if len(row) >= 4 and row[0].strip().upper() == passport.upper():
                return {"hotel": row[1].strip(), "floor": row[2].strip(), "room": row[3].strip()}
    except Exception as e:
        log.error("Lookup error: %s", e)
    return None


def add_record(passport: str, hotel: str, floor: str, room: str) -> bool:
    _rooms_init()
    if not _rooms_ws: return False
    try:
        _rooms_ws.append_row([passport.upper(), hotel, floor, room])
        return True
    except Exception as e:
        log.error("Add error: %s", e)
        return False


def delete_record(passport: str) -> bool:
    _rooms_init()
    if not _rooms_ws: return False
    try:
        cell = _rooms_ws.find(passport.upper())
        if cell: _rooms_ws.delete_rows(cell.row); return True
    except Exception as e:
        log.error("Delete error: %s", e)
    return False


def record_count() -> int:
    _rooms_init()
    if not _rooms_ws: return 0
    try: return max(0, len(_rooms_ws.get_all_values()) - 1)
    except: return 0


BRAND = "🕋  HAJJ ROOM  🕋"
DIVIDER = "▬" * 30


def welcome_text() -> str:
    return (
        f"{BRAND}\n{DIVIDER}\n\n"
        f"*نظام الاستعلام عن الغرف*\n_Room Inquiry System_\n\n{DIVIDER}\n\n"
        f"🛂  أرسل رقم جواز السفر لمعرفة الغرفة\n_Send passport to find your room_\n\n"
        f"•  مثال / Example:  `G3386134`\n\n{DIVIDER}"
    )


def found_text(p: str, h: str, f: str, r: str) -> str:
    return (
        f"{BRAND}\n{DIVIDER}\n\n"
        f"✅  *تم العثور على البيانات*\n_Room Information Found_\n{DIVIDER}\n\n"
        f"🆔  *Passport / الجواز*\n      `{p}`\n\n"
        f"🏨  *Hotel / السكن*\n      {h}\n\n"
        f"📶  *Floor / الدور*\n      {f}\n\n"
        f"🚪  *Room / الغرفة*\n      {r}\n\n{DIVIDER}\n"
        f"🙏  حج مبرور  ·  Accepted Pilgrimage"
    )


def not_found_text(p: str) -> str:
    return (
        f"{BRAND}\n{DIVIDER}\n\n"
        f"❌  *لم يتم العثور على البيانات*\n_No Information Found_\n{DIVIDER}\n\n"
        f"🆔  `{p}`\n\nلم يتم تسجيل هذا الجواز.\n_This passport is not registered._\n\n{DIVIDER}"
    )


def register(bot):
    @bot.message_handler(commands=["start", "help"])
    def _start(m):
        bot.send_message(m.chat.id, welcome_text(), parse_mode="Markdown")

    @bot.message_handler(func=lambda m: m.text and not m.text.startswith("/"))
    def _lookup(m):
        p = m.text.strip().upper()
        if not re.match(r"^[A-Z]\d{6,9}$", p):
            bot.reply_to(m, "❌  يرجى إرسال رقم جواز صحيح  ·  _Send a valid passport number_", parse_mode="Markdown")
            return
        rec = lookup(p)
        if rec:
            bot.reply_to(m, found_text(p, rec["hotel"], rec["floor"], rec["room"]), parse_mode="Markdown")
        else:
            bot.reply_to(m, not_found_text(p), parse_mode="Markdown")

    @bot.message_handler(commands=["add"])
    def _add(m):
        if str(m.from_user.id) not in ADMIN_IDS:
            bot.reply_to(m, "⛔  غير مصرح  ·  Unauthorized"); return
        parts = m.text.strip().split(maxsplit=4)
        if len(parts) != 5:
            bot.reply_to(m, "❌  `/add PASSPORT HOTEL FLOOR ROOM`", parse_mode="Markdown"); return
        _, p, h, f, r = parts
        if not re.match(r"^[A-Z]\d{6,9}$", p.upper()):
            bot.reply_to(m, "❌  جواز غير صحيح", parse_mode="Markdown"); return
        if add_record(p, h, f, r):
            bot.reply_to(m, f"✅  تم إضافة `{p.upper()}`", parse_mode="Markdown")

    @bot.message_handler(commands=["delete"])
    def _del(m):
        if str(m.from_user.id) not in ADMIN_IDS:
            bot.reply_to(m, "⛔  غير مصرح  ·  Unauthorized"); return
        parts = m.text.strip().split()
        if len(parts) != 2:
            bot.reply_to(m, "❌  `/delete PASSPORT`", parse_mode="Markdown"); return
        if delete_record(parts[1].upper()):
            bot.reply_to(m, f"🗑️  تم حذف `{parts[1].upper()}`", parse_mode="Markdown")
        else:
            bot.reply_to(m, f"⚠️  `{parts[1].upper()}` غير موجود", parse_mode="Markdown")

    @bot.message_handler(commands=["stats"])
    def _stats(m):
        if str(m.from_user.id) not in ADMIN_IDS:
            bot.reply_to(m, "⛔  غير مصرح  ·  Unauthorized"); return
        bot.reply_to(m, f"{BRAND}\n{DIVIDER}\n\n📊 الإجمالي: *{record_count()}*\n{DIVIDER}", parse_mode="Markdown")

    log.info("Room bot handlers registered")
