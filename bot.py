import telebot
import sqlite3
import os, re, json, time, logging, http.server, socketserver, sys, threading, urllib.request
from datetime import datetime
from google.oauth2.service_account import Credentials
import gspread

_env = os.path.join(os.path.dirname(__file__), ".env")
if os.path.exists(_env):
    with open(_env) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

NUSUK_TOKEN = os.environ.get("NUSUK_BOT_TOKEN") or os.environ.get("BOT_TOKEN", "")
ROOM_TOKEN  = os.environ.get("ROOM_BOT_TOKEN") or os.environ.get("BOT_TOKEN", "")
SHEET_ID    = os.environ.get("SHEET_ID", "1ct8MGpZi_3qE4EIfftmje9w_3HOX4HR33ffl6YRB054")
PORT        = int(os.environ.get("PORT", 8080))
RENDER_URL  = os.environ.get("RENDER_EXTERNAL_URL", "").rstrip("/")
GS_KEY      = os.environ.get("GOOGLE_SHEETS_KEY", "{}")
DB_PATH     = os.path.join(os.path.dirname(__file__), "nusuk.db")

logging.basicConfig(level=logging.INFO, format="%(asctime)s  [%(levelname)s]  %(message)s")
log = logging.getLogger("bot")

if NUSUK_TOKEN:
    try: nusuk_bot = telebot.TeleBot(NUSUK_TOKEN)
    except Exception as e: log.error("Nusuk bot init failed: %s", e); sys.exit(1)
else: log.error("NUSUK_BOT_TOKEN not set"); sys.exit(1)

try:
    c = sqlite3.connect(DB_PATH)
    c.execute("CREATE TABLE IF NOT EXISTS requests (id INTEGER PRIMARY KEY AUTOINCREMENT, passport TEXT NOT NULL, status TEXT, hotel TEXT, floor TEXT, room TEXT, employee TEXT, date TEXT)")
    c.close(); log.info("DB ready")
except Exception as e: log.warning("DB init: %s", e)

H = "\u2500" * 36

# ─────────── HELPERS ───────────

STATUS_NAMES = {
    "not_received": "\U0001f4ed \u0644\u0645 \u064a\u0633\u062a\u0644\u0645 \u00b7 Not Received",
    "lost": "\U0001f504 \u0628\u062f\u0644 \u0641\u0627\u0642\u062f \u00b7 Replacement",
    "photo_mismatch": "\U0001f5bc \u0627\u0644\u0635\u0648\u0631\u0629 \u063a\u064a\u0631 \u0645\u0637\u0627\u0628\u0642\u0629 \u00b7 Photo Mismatch",
    "data_diff": "\U0001f4cb \u0627\u062e\u062a\u0644\u0627\u0641 \u0628\u064a\u0627\u0646\u0627\u062a \u00b7 Data Discrepancy",
    "photo_diff": "\U0001f4f8 \u0627\u062e\u062a\u0644\u0627\u0641 \u0635\u0648\u0631\u0629 \u00b7 Photo Diff",
}
def _st(s): return STATUS_NAMES.get(s, s)
def _st_code(s):
    for k,v in STATUS_NAMES.items():
        if any(w in s for w in v.split()): return k
    return s

def _db(sql, params=(), fetch=None):
    c = sqlite3.connect(DB_PATH)
    r = c.execute(sql, params)
    if fetch=="one": r = r.fetchone()
    elif fetch=="all": r = r.fetchall()
    else: r = None
    c.commit(); c.close()
    return r

# ─────────── MAIN MENU ───────────

def main_menu(cid):
    mk = telebot.types.InlineKeyboardMarkup(row_width=2)
    mk.add(
        telebot.types.InlineKeyboardButton("\U0001f4dd \u0637\u0644\u0628 \u062c\u062f\u064a\u062f \u00b7 New", callback_data="nm_new"),
        telebot.types.InlineKeyboardButton("\U0001f50d \u0628\u062d\u062b \u00b7 Search", callback_data="nm_search"),
        telebot.types.InlineKeyboardButton("\U0001f4cb \u0622\u062e\u0631 \u0627\u0644\u0637\u0644\u0628\u0627\u062a \u00b7 Recent", callback_data="nm_history"),
        telebot.types.InlineKeyboardButton("\u270f\ufe0f \u062a\u0639\u062f\u064a\u0644/\u062d\u0630\u0641 \u00b7 Edit/Del", callback_data="nm_edit"),
        telebot.types.InlineKeyboardButton("\U0001f4ca \u0625\u062d\u0635\u0627\u0626\u064a\u0627\u062a \u00b7 Stats", callback_data="nm_stats"),
    )
    nusuk_bot.send_message(cid,
        f"*\U0001F3E2 Nusuk Card System*  \u2014  *\u0646\u0638\u0627\u0645 \u0628\u0637\u0627\u0642\u0627\u062a \u0646\u0633\u0643*\n"
        f"*\u0637\u0644\u0628\u0627\u062a \u0628\u0637\u0627\u0642\u0627\u062a \u0627\u0644\u062d\u062c\u0627\u062c \u0646\u0633\u0643 \u063a\u0627\u0646\u0627 2026*\n{H}\n"
        f"\U0001f4dd \u0637\u0644\u0628 \u062c\u062f\u064a\u062f \u00b7 New Request\n"
        f"\U0001f50d \u0628\u062d\u062b \u00b7 Search\n"
        f"\U0001f4cb \u0622\u062e\u0631 \u0627\u0644\u0637\u0644\u0628\u0627\u062a \u00b7 Recent\n"
        f"\u270f\ufe0f \u062a\u0639\u062f\u064a\u0644/\u062d\u0630\u0641 \u00b7 Edit/Delete\n"
        f"\U0001f4ca \u0625\u062d\u0635\u0627\u0626\u064a\u0627\u062a \u00b7 Statistics",
        parse_mode="Markdown", reply_markup=mk)

@nusuk_bot.callback_query_handler(func=lambda c: c.data.startswith("nm_"))
def cb_main(c):
    fn = {"nm_new": start_req, "nm_search": search_menu, "nm_history": cmd_history, "nm_edit": edit_menu, "nm_stats": cmd_stats}
    fn[c.data](c.message)
    nusuk_bot.answer_callback_query(c.id)

@nusuk_bot.message_handler(commands=["start","help","menu"])
def cmd_start(m): main_menu(m.chat.id)

# ─────────── NEW REQUEST ───────────

state = {}

@nusuk_bot.message_handler(commands=["new"])
def start_req(m=None):
    cid = m.chat.id
    state[cid] = {"step": "passport"}
    nusuk_bot.send_message(cid,
        f"*\U0001F6C2 Step 1/5 \u2014 Passport | \u062c\u0648\u0627\u0632 \u0627\u0644\u0633\u0641\u0631*\n{H}\n"
        f"Send passport number | \u0623\u0631\u0633\u0644 \u0631\u0642\u0645 \u062c\u0648\u0627\u0632 \u0627\u0644\u0633\u0641\u0631\n"
        f"Example | \u0645\u062b\u0627\u0644: `G3386134`\n{H}\n"
        f"Send `back` to cancel | \u0623\u0631\u0633\u0644 `\u0631\u062c\u0648\u0639` \u0644\u0644\u0625\u0644\u063a\u0627\u0621",
        parse_mode="Markdown")

@nusuk_bot.message_handler(func=lambda m: state.get(m.chat.id,{}).get("step")=="passport")
def get_pass(m):
    cid = m.chat.id; txt = m.text.strip().upper()
    if txt in ("\u0627\u0644\u063a\u0627\u0621","\u0625\u0644\u063a\u0627\u0621","cancel","\u0631\u062c\u0648\u0639","back"): del state[cid]; main_menu(cid); return
    if not re.match(r"^[A-Z]\d{6,9}$", txt):
        nusuk_bot.reply_to(m,
            f"*\u274C Invalid Format | \u0635\u064a\u063a\u0629 \u063a\u064a\u0631 \u0635\u062d\u064a\u062d\u0629*\n{H}\n"
            f"Correct format | \u0627\u0644\u0635\u064a\u063a\u0629 \u0627\u0644\u0635\u062d\u064a\u062d\u0629: `G3386134`\n"
            f"1 letter + 7 digits | \u062d\u0631\u0641 + 7 \u0623\u0631\u0642\u0627\u0645",
            parse_mode="Markdown")
        return
    exists = _db("SELECT id FROM requests WHERE passport=?", (txt,), fetch="one")
    if exists:
        nusuk_bot.reply_to(m,
            f"*\u26A0\uFE0F Duplicate Passport | \u064a\u0648\u062c\u062f \u0637\u0644\u0628 \u0633\u0627\u0628\u0642*\n{H}\n"
            f"\U0001F6C2 Passport | \u0627\u0644\u062c\u0648\u0627\u0632: `{txt}`\n"
            f"\U0001F511 Request ID | \u0631\u0642\u0645 \u0627\u0644\u0637\u0644\u0628: `#{exists[0]}`\n{H}\n"
            f"This passport already has an active request | \u0647\u0646\u0627\u0643 \u0637\u0644\u0628 \u0633\u0627\u0628\u0642 \u0644\u0647\u0630\u0627 \u0627\u0644\u062c\u0648\u0627\u0632",
            parse_mode="Markdown")
        del state[cid]; return
    state[cid]["passport"] = txt; state[cid]["step"] = "status"
    mk = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True, row_width=1)
    for v in STATUS_NAMES.values(): mk.add(v)
    nusuk_bot.reply_to(m,
        f"*\U0001F4CC Step 2/5 \u2014 Status | \u0627\u0644\u062d\u0627\u0644\u0629*\n{H}\n"
        f"Choose status from buttons below | \u0627\u062e\u062a\u0631 \u0627\u0644\u062d\u0627\u0644\u0629 \u0645\u0646 \u0627\u0644\u0623\u0632\u0631\u0627\u0631:",
        reply_markup=mk, parse_mode="Markdown")

@nusuk_bot.message_handler(func=lambda m: state.get(m.chat.id,{}).get("step")=="status")
def get_status(m):
    cid = m.chat.id; txt = m.text.strip()
    if txt in ("\u0627\u0644\u063a\u0627\u0621","\u0625\u0644\u063a\u0627\u0621","cancel","\u0631\u062c\u0648\u0639","back"): del state[cid]; main_menu(cid); return
    code = _st_code(txt)
    if code not in STATUS_NAMES:
        nusuk_bot.reply_to(m, f"\u274C Use the buttons only | \u0627\u0633\u062a\u062e\u062f\u0645 \u0627\u0644\u0623\u0632\u0631\u0627\u0631 \u0641\u0642\u0637")
        return
    state[cid]["status"] = code
    state[cid]["step"] = "hotel"
    nusuk_bot.reply_to(m,
        f"*\U0001F3E8 Step 3/5 \u2014 Building | \u0627\u0644\u0633\u0643\u0646*\n{H}\n"
        f"Send building name | \u0623\u0631\u0633\u0644 \u0627\u0633\u0645 \u0627\u0644\u0645\u0628\u0646\u0649:",
        parse_mode="Markdown", reply_markup=telebot.types.ReplyKeyboardRemove())

@nusuk_bot.message_handler(func=lambda m: state.get(m.chat.id,{}).get("step")=="hotel")
def get_hotel(m):
    cid = m.chat.id; txt = m.text.strip()
    if txt in ("\u0627\u0644\u063a\u0627\u0621","\u0625\u0644\u063a\u0627\u0621","cancel","\u0631\u062c\u0648\u0639","back"): del state[cid]; main_menu(cid); return
    if not txt:
        nusuk_bot.reply_to(m, f"\u274C Please send the building name | \u064a\u0631\u062c\u0649 \u0625\u0631\u0633\u0627\u0644 \u0627\u0633\u0645 \u0627\u0644\u0645\u0628\u0646\u0649"); return
    state[cid]["hotel"] = txt; state[cid]["step"] = "floor"
    nusuk_bot.reply_to(m,
        f"*\U0001F4F6 Step 4/5 \u2014 Floor | \u0627\u0644\u062f\u0648\u0631*\n{H}\n"
        f"Send floor number | \u0623\u0631\u0633\u0644 \u0631\u0642\u0645 \u0627\u0644\u062f\u0648\u0631:",
        parse_mode="Markdown")

@nusuk_bot.message_handler(func=lambda m: state.get(m.chat.id,{}).get("step")=="floor")
def get_floor(m):
    cid = m.chat.id; txt = m.text.strip()
    if txt in ("\u0627\u0644\u063a\u0627\u0621","\u0625\u0644\u063a\u0627\u0621","cancel","\u0631\u062c\u0648\u0639","back"): del state[cid]; main_menu(cid); return
    if not txt.isdigit():
        nusuk_bot.reply_to(m, f"\u274C Please enter a valid number | \u064a\u0631\u062c\u0649 \u0625\u062f\u062e\u0627\u0644 \u0631\u0642\u0645 \u0635\u062d\u064a\u062d"); return
    state[cid]["floor"] = txt; state[cid]["step"] = "room"
    nusuk_bot.reply_to(m,
        f"*\U0001F6AA Step 5/5 \u2014 Room | \u0627\u0644\u063a\u0631\u0641\u0629*\n{H}\n"
        f"Send room number | \u0623\u0631\u0633\u0644 \u0631\u0642\u0645 \u0627\u0644\u063a\u0631\u0641\u0629:",
        parse_mode="Markdown")

@nusuk_bot.message_handler(func=lambda m: state.get(m.chat.id,{}).get("step")=="room")
def get_room(m):
    cid = m.chat.id; txt = m.text.strip()
    if txt in ("\u0627\u0644\u063a\u0627\u0621","\u0625\u0644\u063a\u0627\u0621","cancel","\u0631\u062c\u0648\u0639","back"): del state[cid]; main_menu(cid); return
    if not txt:
        nusuk_bot.reply_to(m, f"\u274C Please send room number | \u064a\u0631\u062c\u0649 \u0625\u0631\u0633\u0627\u0644 \u0631\u0642\u0645 \u0627\u0644\u063a\u0631\u0641\u0629"); return
    s = state[cid]
    s["room"] = txt; s["employee"] = f"{m.from_user.first_name or ''} {m.from_user.last_name or ''}".strip()
    s["date"] = datetime.now().strftime("%Y-%m-%d %H:%M"); s["step"] = "confirm"
    nusuk_bot.reply_to(m,
        f"*\u2705 Confirm Request | \u062a\u0623\u0643\u064a\u062f \u0627\u0644\u0637\u0644\u0628*\n{H}\n"
        f"\U0001F6C2 Passport | \u062c\u0648\u0627\u0632 \u0627\u0644\u0633\u0641\u0631: `{s['passport']}`\n"
        f"\U0001F4CC Status | \u0627\u0644\u062d\u0627\u0644\u0629: {_st(s['status'])}\n"
        f"\U0001F3E8 Building | \u0627\u0644\u0645\u0628\u0646\u0649: {s['hotel']}\n"
        f"\U0001F4F6 Floor | \u0627\u0644\u062f\u0648\u0631: {s['floor']}\n"
        f"\U0001F6AA Room | \u0627\u0644\u063a\u0631\u0641\u0629: {s['room']}\n"
        f"\U0001F464 Employee | \u0627\u0644\u0645\u0648\u0638\u0641: {s['employee']}\n"
        f"\U0001F4C5 Date | \u0627\u0644\u062a\u0627\u0631\u064a\u062e: {s['date']}\n{H}\n\n"
        f"\u2705 Send `confirm` to save | \u0623\u0631\u0633\u0644 `\u062a\u0645` \u0644\u0644\u062d\u0641\u0638\n"
        f"\u274C Send `cancel` to cancel | \u0623\u0631\u0633\u0644 `\u0625\u0644\u063a\u0627\u0621` \u0644\u0644\u0625\u0644\u063a\u0627\u0621",
        parse_mode="Markdown")

@nusuk_bot.message_handler(func=lambda m: state.get(m.chat.id,{}).get("step")=="confirm")
def confirm(m):
    cid = m.chat.id; txt = m.text.strip()
    if txt in ("\u0627\u0644\u063a\u0627\u0621","\u0625\u0644\u063a\u0627\u0621","cancel","\u0631\u062c\u0648\u0639","back","\u0644\u0627"): del state[cid]; main_menu(cid); return
    if txt in ("\u062a\u0645","\u062a\u0623\u0643\u064a\u062f","confirm","yes","\u0646\u0639\u0645"):
        s = state.pop(cid)
        _db("INSERT INTO requests (passport,status,hotel,floor,room,employee,date) VALUES (?,?,?,?,?,?,?)",
            (s["passport"],s["status"],s["hotel"],s["floor"],s["room"],s["employee"],s["date"]))
        try:
            lcid = os.environ.get("LOG_CHAT_ID","")
            if lcid:
                msg = (
                    f"*\U0001F4E5 New Request | \u0637\u0644\u0628 \u062c\u062f\u064a\u062f*\n{H}\n"
                    f"\U0001F6C2 Passport | \u062c\u0648\u0627\u0632: `{s['passport']}`\n"
                    f"\U0001F4CC Status | \u0627\u0644\u062d\u0627\u0644\u0629: {_st(s['status'])}\n"
                    f"\U0001F3E8 Building | \u0627\u0644\u0645\u0628\u0646\u0649: {s['hotel']}\n"
                    f"\U0001F4F6 Floor | \u0627\u0644\u062f\u0648\u0631: {s['floor']}\n"
                    f"\U0001F6AA Room | \u0627\u0644\u063a\u0631\u0641\u0629: {s['room']}\n"
                    f"\U0001F464 Employee | \u0627\u0644\u0645\u0648\u0638\u0641: {s['employee']}\n"
                    f"\U0001F4C5 Date | \u0627\u0644\u062a\u0627\u0631\u064a\u062e: {s['date']}\n{H}"
                )
                nusuk_bot.send_message(int(lcid), msg, parse_mode="Markdown")
        except: pass
        try:
            k = json.loads(GS_KEY)
            if k:
                gs = gspread.authorize(Credentials.from_service_account_info(k, scopes=["https://www.googleapis.com/auth/spreadsheets"])).open_by_key(SHEET_ID).sheet1
                gs.append_row([s["date"],s["passport"],_st(s["status"]),s["hotel"],s["floor"],s["room"],s["employee"]])
        except: pass
        nusuk_bot.reply_to(m,
            f"*\u2705 Request Saved | \u062a\u0645 \u062d\u0641\u0638 \u0627\u0644\u0637\u0644\u0628*\n{H}\n"
            f"\u0634\u0643\u0631\u0627\u064b \u00b7 Thank you!",
            parse_mode="Markdown")
        main_menu(cid)
    else:
        nusuk_bot.reply_to(m,
            f"Send `confirm` to save or `cancel` to cancel | \u0623\u0631\u0633\u0644 `\u062a\u0645` \u0623\u0648 `\u0625\u0644\u063a\u0627\u0621`",
            parse_mode="Markdown")

# ─────────── SEARCH ───────────

_search_state = {}
def search_menu(m=None):
    cid = m.chat.id if hasattr(m,'chat') else m
    mk = telebot.types.InlineKeyboardMarkup(row_width=1)
    mk.add(
        telebot.types.InlineKeyboardButton("\U0001F6C2 Passport | \u062c\u0648\u0627\u0632 \u0627\u0644\u0633\u0641\u0631", callback_data="sr_pass"),
        telebot.types.InlineKeyboardButton("\U0001F3E8 Building | \u0627\u0644\u0645\u0628\u0646\u0649", callback_data="sr_hotel"),
        telebot.types.InlineKeyboardButton("\U0001F4C5 Date | \u0627\u0644\u062a\u0627\u0631\u064a\u062e", callback_data="sr_date"),
        telebot.types.InlineKeyboardButton("\u25C0\uFE0F Back | \u0631\u062c\u0648\u0639", callback_data="sr_back"),
    )
    nusuk_bot.send_message(cid,
        f"*\U0001F50D Search Request | \u0628\u062d\u062b \u0639\u0646 \u0637\u0644\u0628*\n{H}\n"
        f"Choose search type | \u0627\u062e\u062a\u0631 \u0646\u0648\u0639 \u0627\u0644\u0628\u062d\u062b:",
        parse_mode="Markdown", reply_markup=mk)

@nusuk_bot.callback_query_handler(func=lambda c: c.data.startswith("sr_"))
def cb_search(c):
    if c.data=="sr_back": nusuk_bot.answer_callback_query(c.id); main_menu(c.message.chat.id); return
    _search_state[c.message.chat.id] = {"type": c.data.replace("sr_","")}
    nusuk_bot.answer_callback_query(c.id)
    nusuk_bot.send_message(c.message.chat.id,
        f"\U0001F4E4 Send search term | \u0623\u0631\u0633\u0644 \u0643\u0644\u0645\u0629 \u0627\u0644\u0628\u062d\u062b",
        parse_mode="Markdown")

@nusuk_bot.message_handler(func=lambda m: m.chat.id in _search_state)
def do_search(m):
    cid = m.chat.id; t = _search_state.pop(cid)
    q = m.text.strip()
    if q in ("\u0627\u0644\u063a\u0627\u0621","\u0625\u0644\u063a\u0627\u0621","cancel","\u0631\u062c\u0648\u0639","back"): main_menu(cid); return
    try:
        if t["type"]=="pass":
            rows = _db("SELECT id,passport,status,hotel,floor,room,employee,date FROM requests WHERE passport LIKE ?", (f"%{q.upper()}%",), fetch="all")
        elif t["type"]=="hotel":
            rows = _db("SELECT id,passport,status,hotel,floor,room,employee,date FROM requests WHERE hotel LIKE ?", (f"%{q}%",), fetch="all")
        elif t["type"]=="date":
            rows = _db("SELECT id,passport,status,hotel,floor,room,employee,date FROM requests WHERE date LIKE ?", (f"%{q}%",), fetch="all")
        else: rows = []
    except: rows = []
    if not rows:
        nusuk_bot.reply_to(m,
            f"*\u274C No Results | \u0644\u0627 \u062a\u0648\u062c\u062f \u0646\u062a\u0627\u0626\u062c*\n{H}\n"
            f"No matching requests found | \u0644\u0645 \u064a\u062a\u0645 \u0627\u0644\u0639\u062b\u0648\u0631 \u0639\u0644\u0649 \u0637\u0644\u0628\u0627\u062a \u0645\u0637\u0627\u0628\u0642\u0629",
            parse_mode="Markdown")
        main_menu(cid); return
    lines = [f"*\U0001F50D Search Results | \u0646\u062a\u0627\u0626\u062c \u0627\u0644\u0628\u062d\u062b* \u2014 {len(rows)}"]
    lines.append(H)
    for r in rows[:10]:
        lines.append(f"`#{r[0]}` `{r[1]}` \u2014 {_st(r[2])}")
        lines.append(f"  \U0001F3E8{r[3]} \u00b7 \U0001F4F6{r[4]} \u00b7 \U0001F6AA{r[5]}")
        lines.append(f"  \U0001F464{r[6]} \u00b7 \U0001F4C5{r[7]}")
        lines.append("")
    if len(rows)>10:
        lines.append(f"\u2026 +{len(rows)-10} more | \u0623\u062e\u0631\u0649")
        lines.append(H)
    nusuk_bot.reply_to(m, "\n".join(lines), parse_mode="Markdown")
    main_menu(cid)

# ─────────── HISTORY ───────────

@nusuk_bot.message_handler(commands=["history"])
def cmd_history(m=None):
    rows = _db("SELECT passport,status,hotel,floor,room,date FROM requests ORDER BY id DESC LIMIT 10", fetch="all") or []
    if not rows:
        nusuk_bot.reply_to(m,
            f"*\U0001F4ED No Requests | \u0644\u0627 \u062a\u0648\u062c\u062f \u0637\u0644\u0628\u0627\u062a*\n{H}\n"
            f"No requests recorded yet | \u0644\u0645 \u064a\u062a\u0645 \u062a\u0633\u062c\u064a\u0644 \u0623\u064a \u0637\u0644\u0628 \u0628\u0639\u062f",
            parse_mode="Markdown")
        return
    lines = ["*\U0001F4CB Recent 10 | \u0622\u062e\u0631 10 \u0637\u0644\u0628\u0627\u062a*\n"]
    for r in rows:
        lines.append(f"`{r[0]}` \u2014 {_st(r[1])}")
        lines.append(f"  \U0001F3E8{r[2]} \u00b7 \U0001F4F6{r[3]} \u00b7 \U0001F6AA{r[4]} \u00b7 \U0001F4C5{r[5]}")
        lines.append("")
    nusuk_bot.reply_to(m, "\n".join(lines), parse_mode="Markdown")

# ─────────── STATS ───────────

@nusuk_bot.message_handler(commands=["count"])
def cmd_count(m=None):
    n = (_db("SELECT COUNT(*) FROM requests", fetch="one") or [0])[0]
    txt = f"*\U0001F4CA Total Requests | \u0625\u062c\u0645\u0627\u0644\u064a \u0627\u0644\u0637\u0644\u0628\u0627\u062a:* `{n}`"
    if m: nusuk_bot.reply_to(m, txt, parse_mode="Markdown")

@nusuk_bot.message_handler(commands=["stats"])
def cmd_stats(m=None):
    rows = _db("SELECT status,hotel FROM requests", fetch="all") or []
    if not rows:
        nusuk_bot.reply_to(m,
            f"*\U0001F4ED No Data | \u0644\u0627 \u062a\u0648\u062c\u062f \u0628\u064a\u0627\u0646\u0627\u062a*\n{H}\n"
            f"No requests recorded yet | \u0644\u0645 \u064a\u062a\u0645 \u062a\u0633\u062c\u064a\u0644 \u0623\u064a \u0637\u0644\u0628\u0627\u062a \u0628\u0639\u062f",
            parse_mode="Markdown")
        return
    sts, hts = {}, {}
    for st, ho in rows: sts[st]=sts.get(st,0)+1; hts[ho]=hts.get(ho,0)+1
    lines = ["*\U0001F4CA Statistics | \u0625\u062d\u0635\u0627\u0626\u064a\u0627\u062a*\n"]
    lines.append(f"*\u0627\u0644\u0639\u062f\u062f \u0627\u0644\u0643\u0644\u064a | Total:* `{sum(sts.values())}`")
    lines.append(f"\n*\u200F\u062d\u0633\u0628 \u0627\u0644\u062d\u0627\u0644\u0629 | By Status:*")
    for s,n in sts.items(): lines.append(f"  \u2022 {_st(s)}: `{n}`")
    lines.append(f"\n*\u200F\u062d\u0633\u0628 \u0627\u0644\u0645\u0628\u0646\u0649 | By Building (>5):*")
    for h,n in sorted(hts.items(), key=lambda x:-x[1]):
        if n>5: lines.append(f"  \u2022 {h}: `{n}`")
    nusuk_bot.reply_to(m, "\n".join(lines), parse_mode="Markdown")

# ─────────── EDIT / DELETE ───────────

_edit_state = {}
def edit_menu(m=None):
    cid = m.chat.id if hasattr(m,'chat') else m
    nusuk_bot.send_message(cid,
        f"*\u270F\uFE0F Edit / Delete Request | \u062a\u0639\u062f\u064a\u0644 \u0623\u0648 \u062d\u0630\u0641 \u0637\u0644\u0628*\n{H}\n"
        f"Send request ID | \u0623\u0631\u0633\u0644 \u0631\u0642\u0645 \u0627\u0644\u0637\u0644\u0628\n"
        f"Example | \u0645\u062b\u0627\u0644: `#1` \u0623\u0648 `1`\n{H}\n"
        f"Or send `/menu` to go back | \u0623\u0648 \u0623\u0631\u0633\u0644 `/menu` \u0644\u0644\u0631\u062c\u0648\u0639",
        parse_mode="Markdown")
    _edit_state[cid] = {"step": "id"}

@nusuk_bot.message_handler(func=lambda m: _edit_state.get(m.chat.id,{}).get("step")=="id")
def edit_get_id(m):
    cid = m.chat.id; txt = m.text.strip().replace("#","")
    if txt in ("\u0627\u0644\u063a\u0627\u0621","\u0625\u0644\u063a\u0627\u0621","cancel","\u0631\u062c\u0648\u0639","back","/menu"): del _edit_state[cid]; main_menu(cid); return
    if not txt.isdigit():
        nusuk_bot.reply_to(m, f"\u274C Send a valid ID number | \u0623\u0631\u0633\u0644 \u0631\u0642\u0645 \u0635\u062d\u064a\u062d \u0645\u062b\u0627\u0644: `1`", parse_mode="Markdown")
        return
    row = _db("SELECT * FROM requests WHERE id=?", (int(txt),), fetch="one")
    if not row:
        nusuk_bot.reply_to(m,
            f"*\u274C Request Not Found | \u0644\u0627 \u064a\u0648\u062c\u062f \u0637\u0644\u0628*\n{H}\n"
            f"Check the ID and try again | \u062a\u0623\u0643\u062f \u0645\u0646 \u0631\u0642\u0645 \u0627\u0644\u0637\u0644\u0628 \u0648\u0623\u0639\u062f \u0627\u0644\u0645\u062d\u0627\u0648\u0644\u0629",
            parse_mode="Markdown")
        return
    _edit_state[cid] = {"step": "action", "id": row[0], "data": row[1:]}
    mk = telebot.types.InlineKeyboardMarkup(row_width=2)
    mk.add(
        telebot.types.InlineKeyboardButton("\U0001F504 \u062a\u0639\u062f\u064a\u0644", callback_data=f"ed_edit_{row[0]}"),
        telebot.types.InlineKeyboardButton("\U0001F5D1 \u062d\u0630\u0641", callback_data=f"ed_del_{row[0]}"),
        telebot.types.InlineKeyboardButton("\u25C0\uFE0F \u0631\u062c\u0648\u0639", callback_data="ed_back"),
    )
    d = row; st = _st(d[2])
    nusuk_bot.reply_to(m,
        f"*\U0001F511 Request #{d[0]} | \u0637\u0644\u0628 #{d[0]}*\n{H}\n"
        f"\U0001F6C2 Passport | \u062c\u0648\u0627\u0632: `{d[1]}`\n"
        f"\U0001F4CC Status | \u0627\u0644\u062d\u0627\u0644\u0629: {st}\n"
        f"\U0001F3E8 Building | \u0627\u0644\u0645\u0628\u0646\u0649: {d[3]}\n"
        f"\U0001F4F6 Floor | \u0627\u0644\u062f\u0648\u0631: {d[4]}\n"
        f"\U0001F6AA Room | \u0627\u0644\u063a\u0631\u0641\u0629: {d[5]}\n"
        f"\U0001F464 Employee | \u0627\u0644\u0645\u0648\u0638\u0641: {d[6]}\n"
        f"\U0001F4C5 Date | \u0627\u0644\u062a\u0627\u0631\u064a\u062e: {d[7]}\n{H}\n"
        f"Choose action | \u0627\u062e\u062a\u0631 \u0625\u062c\u0631\u0627\u0621:",
        parse_mode="Markdown", reply_markup=mk)

@nusuk_bot.callback_query_handler(func=lambda c: c.data.startswith("ed_"))
def cb_edit(c):
    cid = c.message.chat.id
    parts = c.data.split("_")
    action, rid = parts[1], int(parts[2])
    nusuk_bot.answer_callback_query(c.id)
    if action=="back": del _edit_state[cid]; main_menu(cid); return
    if action=="del":
        _db("DELETE FROM requests WHERE id=?", (rid,))
        nusuk_bot.send_message(cid,
            f"*\u2705 Request #{rid} Deleted | \u062a\u0645 \u062d\u0630\u0641 \u0627\u0644\u0637\u0644\u0628*\n{H}\n"
            f"Request deleted successfully | \u062a\u0645 \u062d\u0630\u0641 \u0627\u0644\u0637\u0644\u0628 \u0628\u0646\u062c\u0627\u062d",
            parse_mode="Markdown")
        del _edit_state[cid]; main_menu(cid); return
    if action=="edit":
        _edit_state[cid] = {"step": "field", "id": rid}
        mk = telebot.types.InlineKeyboardMarkup(row_width=2)
        mk.add(
            telebot.types.InlineKeyboardButton("\U0001F6C2 Passport | \u062c\u0648\u0627\u0632", callback_data=f"ef_pass_{rid}"),
            telebot.types.InlineKeyboardButton("\U0001F4CC Status | \u062d\u0627\u0644\u0629", callback_data=f"ef_status_{rid}"),
            telebot.types.InlineKeyboardButton("\U0001F3E8 Building | \u0645\u0628\u0646\u0649", callback_data=f"ef_hotel_{rid}"),
            telebot.types.InlineKeyboardButton("\U0001F4F6 Floor | \u062f\u0648\u0631", callback_data=f"ef_floor_{rid}"),
            telebot.types.InlineKeyboardButton("\U0001F6AA Room | \u063a\u0631\u0641\u0629", callback_data=f"ef_room_{rid}"),
            telebot.types.InlineKeyboardButton("\u25C0\uFE0F Back | \u0631\u062c\u0648\u0639", callback_data="ed_back"),
        )
        nusuk_bot.send_message(cid,
            f"*\u270F\uFE0F Edit Request #{rid} | \u062a\u0639\u062f\u064a\u0644 \u0627\u0644\u0637\u0644\u0628*\n{H}\n"
            f"Choose field to edit | \u0627\u062e\u062a\u0631 \u0627\u0644\u062d\u0642\u0644:",
            reply_markup=mk, parse_mode="Markdown")

@nusuk_bot.callback_query_handler(func=lambda c: c.data.startswith("ef_"))
def cb_edit_field(c):
    cid = c.message.chat.id; parts = c.data.split("_")
    field, rid = parts[1], int(parts[2])
    _edit_state[cid] = {"step": "value", "id": rid, "field": field}
    nusuk_bot.answer_callback_query(c.id)
    names = {"pass":"Passport | \u0627\u0644\u062c\u0648\u0627\u0632","status":"Status | \u0627\u0644\u062d\u0627\u0644\u0629","hotel":"Building | \u0627\u0644\u0645\u0628\u0646\u0649","floor":"Floor | \u0627\u0644\u062f\u0648\u0631","room":"Room | \u0627\u0644\u063a\u0631\u0641\u0629"}
    nusuk_bot.send_message(cid,
        f"*\u270F\uFE0F Edit {names.get(field,field)}*\n{H}\n"
        f"Send new value | \u0623\u0631\u0633\u0644 \u0627\u0644\u0642\u064a\u0645\u0629 \u0627\u0644\u062c\u062f\u064a\u062f\u0629:",
        parse_mode="Markdown")

@nusuk_bot.message_handler(func=lambda m: _edit_state.get(m.chat.id,{}).get("step")=="value")
def edit_set_value(m):
    cid = m.chat.id; txt = m.text.strip()
    if txt in ("\u0627\u0644\u063a\u0627\u0621","\u0625\u0644\u063a\u0627\u0621","cancel","\u0631\u062c\u0648\u0639","back"): del _edit_state[cid]; main_menu(cid); return
    s = _edit_state[cid]; field = s["field"]; rid = s["id"]
    col = {"pass":"passport","status":"status","hotel":"hotel","floor":"floor","room":"room"}[field]
    val = txt.upper() if field=="pass" else txt
    if field=="status":
        val = _st_code(val)
        if val not in STATUS_NAMES:
            nusuk_bot.reply_to(m,
                f"\u274C Invalid status | \u062d\u0627\u0644\u0629 \u063a\u064a\u0631 \u0635\u062d\u064a\u062d\u0629\n"
                f"Use the buttons only | \u0627\u0633\u062a\u062e\u062f\u0645 \u0627\u0644\u0623\u0632\u0631\u0627\u0631 \u0641\u0642\u0637")
            return
    _db(f"UPDATE requests SET {col}=? WHERE id=?", (val, rid))
    nusuk_bot.reply_to(m,
        f"*\u2705 Request #{rid} Updated | \u062a\u0645 \u062a\u062d\u062f\u064a\u062b \u0627\u0644\u0637\u0644\u0628*\n{H}\n"
        f"Field `{col}` updated successfully | \u062a\u0645 \u062a\u062d\u062f\u064a\u062b `{col}` \u0628\u0646\u062c\u0627\u062d",
        parse_mode="Markdown")
    del _edit_state[cid]; main_menu(cid)

# ─────────── BUILDING MAPS ───────────

BUILDING_MAPS = {
    "ALRAIS2": "https://maps.app.goo.gl/1671T2oFdhV6UuVw5",
    "AJWAD": "https://maps.app.goo.gl/SKAWGzcLmcEqfbWcA",
    "ALRAIS3": "https://maps.app.goo.gl/kXt4cFLLHAs4nDBz8",
    "DURRA": "https://maps.app.goo.gl/T1P75ecrCnh8jrN4A",
    "MAN.SITTEEN": "https://maps.app.goo.gl/H6AKvdriSzFxv1BA8",
    "NUZHA1": "https://maps.app.goo.gl/jd6UMQFmo9BhRz57",
    "NUZHA2": "https://maps.app.goo.gl/KMGfKadewiNL5vBSA",
    "RAIES1": "https://maps.app.goo.gl/qkH1GQuTm8C8nAGG7",
    "THARAWAT2": "https://maps.app.goo.gl/wVhu49YPr2DLALy38",
    "THARAWAT3": "https://maps.app.goo.gl/QWnWixiv6nLA7E2R7",
    "THARAWAT4": "https://maps.app.goo.gl/Qqcw8K5PQDoYQ3PT9",
    "THARAWAT5": "https://maps.app.goo.gl/bEd7nUrjpU4PgwuaA",
    "THARAWAT6": "https://maps.app.goo.gl/bEd7nUrjpU4PgwuaA",
}

# ─────────── ROOM BOT ───────────

room_bot = None
ROOM_CSV_URL = os.environ.get("ROOM_CSV_URL",
    "https://docs.google.com/spreadsheets/d/1s1LKapsD1Q_1LPnkJYsnoIatsy8bBi1WyBXp7AU-_Ek/export?format=csv")

if ROOM_TOKEN:
    try:
        room_bot = telebot.TeleBot(ROOM_TOKEN)

        @room_bot.message_handler(commands=["start","help"])
        def rs(m):
            room_bot.send_message(m.chat.id,
                f"*\U0001F3D4\uFE0F HAJJ ROOM 2026 \u2014 \u0646\u0638\u0627\u0645 \u0627\u0644\u063a\u0631\u0641*\n"
                f"*\u0637\u0644\u0628\u0627\u062a \u0628\u0637\u0627\u0642\u0627\u062a \u0627\u0644\u062d\u062c\u0627\u062c \u0646\u0633\u0643 \u063a\u0627\u0646\u0627 2026*\n{H}\n"
                f"\U0001F3E8 *Room Inquiry System*\n"
                f"_ \u0646\u0638\u0627\u0645 \u0627\u0644\u0627\u0633\u062a\u0639\u0644\u0627\u0645 \u0639\u0646 \u0627\u0644\u063a\u0631\u0641 _\n\n"
                f"\U0001F4CC *How to use | \u0637\u0631\u064a\u0642\u0629 \u0627\u0644\u0627\u0633\u062a\u062e\u062f\u0627\u0645:*\n"
                f"Send your passport number | \u0623\u0631\u0633\u0644 \u0631\u0642\u0645 \u062c\u0648\u0627\u0632 \u0627\u0644\u0633\u0641\u0631\n\n"
                f"\u0645\u062b\u0627\u0644 | Example: `G3386134`",
                parse_mode="Markdown")

        _data_cache = [None]
        def _load_data():
            if _data_cache[0]: return _data_cache[0]
            try:
                resp = urllib.request.urlopen(ROOM_CSV_URL, timeout=15)
                text = resp.read().decode("utf-8")
                rows = []
                for line in text.splitlines()[1:]:
                    parts = line.split(",")
                    if len(parts) >= 5:
                        pid = parts[3].strip().upper()
                        rn = parts[4].strip()
                        parts_rn = rn.split("_")
                        if len(parts_rn) >= 5:
                            hotel = parts_rn[0]; floor = parts_rn[2]; room = parts_rn[4]
                        else: hotel, floor, room = rn, "", ""
                        rows.append((pid, hotel, floor, room))
                _data_cache[0] = rows
                log.info("Room data loaded: %d records", len(rows))
            except Exception as e:
                log.warning("Room data load: %s", e)
                _data_cache[0] = []
            return _data_cache[0]

        @room_bot.message_handler(commands=["refresh"])
        def rr(m):
            _data_cache[0] = None; d = _load_data()
            room_bot.reply_to(m,
                f"*\u2705 \u062a\u0645 \u062a\u062d\u062f\u064a\u062b \u0627\u0644\u0628\u064a\u0627\u0646\u0627\u062a*\n{H}\n"
                f"_Updated_ \u2014 {len(d)} \u062d\u0627\u062c / pilgrims")

        @room_bot.message_handler(func=lambda m: m.text and not m.text.startswith("/"))
        def rl(m):
            p = m.text.strip().upper()
            if not re.match(r"^[A-Z]\d{6,9}$", p):
                room_bot.reply_to(m,
                    f"*\u274C Invalid Passport | \u062c\u0648\u0627\u0632 \u063a\u064a\u0631 \u0635\u062d\u064a\u062d*\n{H}\n"
                    f"\u0627\u0644\u0635\u064a\u063a\u0629 \u0627\u0644\u0635\u062d\u064a\u062d\u0629 | Correct format: `G3386134`",
                    parse_mode="Markdown")
                return
            try:
                rows = _load_data()
                for pid, hotel, floor, room in rows:
                    if pid == p:
                        map_url = BUILDING_MAPS.get(hotel, "")
                        reply = (f"*\u2705 Found | \u062a\u0645 \u0627\u0644\u0639\u062b\u0648\u0631*\n{H}\n"
                                 f"\U0001F6C2 Passport | \u062c\u0648\u0627\u0632 \u0627\u0644\u0633\u0641\u0631: `{p}`\n"
                                 f"\U0001F3E8 Building | \u0627\u0644\u0645\u0628\u0646\u0649: `{hotel}`\n"
                                 f"\U0001F4F6 Floor | \u0627\u0644\u062f\u0648\u0631: `{floor}`\n"
                                 f"\U0001F6AA Room | \u0627\u0644\u063a\u0631\u0641\u0629: `{room}`")
                        if map_url:
                            reply += f"\n{H}\n\U0001F4CD [\U0001F4CD Location | \u0627\u0644\u0645\u0648\u0642\u0639]({map_url})"
                        reply += f"\n{H}\n\u062d\u062c\u064b\u0627 \u0645\u0628\u0631\u0648\u0631\u064b\u0627 \u0648\u0633\u0639\u064a\u064b\u0627 \u0645\u0634\u0643\u0648\u0631\u064b\u0627 \u2022 Hajj Mabrur"
                        room_bot.reply_to(m, reply, parse_mode="Markdown", disable_web_page_preview=False)
                        return
                room_bot.reply_to(m,
                    f"*\u274C Not Found | \u063a\u064a\u0631 \u0645\u0633\u062c\u0644*\n{H}\n"
                    f"\U0001F6C2 Passport | \u062c\u0648\u0627\u0632 \u0627\u0644\u0633\u0641\u0631: `{p}`\n"
                    f"\u063a\u064a\u0631 \u0645\u0633\u062c\u0644 \u0641\u064a \u0646\u0638\u0627\u0645 \u0627\u0644\u063a\u0631\u0641\n"
                    f"Not registered in the room system",
                    parse_mode="Markdown")
            except Exception as e:
                room_bot.reply_to(m,
                    f"*\u26A0\uFE0F Search Error | \u062e\u0637\u0623 \u0641\u064a \u0627\u0644\u0628\u062d\u062b*\n{H}\n"
                    f"Please try again | \u0627\u0644\u0631\u062c\u0627\u0621 \u0627\u0644\u0645\u062d\u0627\u0648\u0644\u0629 \u0645\u0631\u0629 \u0623\u062e\u0631\u0649",
                    parse_mode="Markdown")
                log.warning("Room lookup: %s", e)

        log.info("Room bot ready")
    except Exception as e:
        log.warning("Room bot init failed: %s", e)
        room_bot = None

# ─────────── WEBHOOK SERVER ───────────

class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")
    def do_POST(self):
        length = int(self.headers.get("Content-Length",0))
        try:
            body = self.rfile.read(length)
            upd = telebot.types.Update.de_json(json.loads(body))
            if self.path == "/room_webhook":
                if room_bot: room_bot.process_new_updates([upd])
            else: nusuk_bot.process_new_updates([upd])
        except: pass
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")
    def log_message(self, *a): pass

# ─────────── MAIN ───────────

def _del_webhooks():
    for bot in [nusuk_bot, room_bot]:
        if not bot: continue
        bot.remove_webhook()
        try:
            u = urllib.request.urlopen(f"https://api.telegram.org/bot{bot.token}/deleteWebhook?drop_pending_updates=true", timeout=5)
            log.info("Webhook deleted for %s (drop_pending)", bot.token[:8])
            u.read()
        except Exception as e:
            log.warning("deleteWebhook API call: %s", e)
        time.sleep(0.5)

if __name__ == "__main__":
    _del_webhooks()

    if RENDER_URL:
        for a in range(3):
            try: nusuk_bot.set_webhook(url=f"{RENDER_URL}/webhook"); log.info("Nusuk webhook set"); break
            except Exception as e: log.warning("Nusuk webhook attempt %d: %s", a+1, e); time.sleep(2)
        if room_bot:
            for a in range(3):
                try: room_bot.set_webhook(url=f"{RENDER_URL}/room_webhook"); log.info("Room webhook set"); break
                except Exception as e: log.warning("Room webhook attempt %d: %s", a+1, e); time.sleep(2)
        def _p():
            while True:
                time.sleep(600)
                try: urllib.request.urlopen(f"{RENDER_URL}/", timeout=10)
                except: pass
        threading.Thread(target=_p, daemon=True).start()
        log.info("Keep-alive started \u2192 every 10 min")
    else:
        threading.Thread(target=nusuk_bot.infinity_polling, daemon=True, name="nusuk-poll").start()
        if room_bot:
            threading.Thread(target=room_bot.infinity_polling, daemon=True, name="room-poll").start()
        log.info("Polling started")

    socketserver.TCPServer.allow_reuse_address = True
    server = http.server.HTTPServer(("0.0.0.0", PORT), Handler)
    log.info("Hajj Bots - listening :%d", PORT)
    server.serve_forever()
