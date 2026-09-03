# -*- coding: utf-8 -*-
"""
VIP Bot v19 - نسخه ترکیبی ربات + یوزربات
"""
import sqlite3
import threading
import html
import logging
import time
import random
import asyncio
import os
import re
import json
import requests
from datetime import datetime, timezone, timedelta

import telebot
from telebot import types
from pyrogram import Client, filters, enums
from pyrogram.types import Message as PyroMessage, InlineQueryResultArticle, InputTextMessageContent
from pyrogram.errors import SessionPasswordNeeded, FloodWait
from pyrogram.handlers import MessageHandler

# ----------------- CONFIG -----------------
BOT_TOKEN = "8200221816:AAHN5J-iFXJoQ9mEFLcRBc3ZVDCv2cmrsxQ"
OWNER_ID = 5552127428
DEVELOPER_ID = 5552127428
ADMIN_IDS = [OWNER_ID, DEVELOPER_ID]

# اطلاعات یوزربات
API_ID = 37386944
API_HASH = "d64069023db75d11ae5982f653069a98"
SESSION_NAME = "userbot_session"

# مسیر دیتابیس
DATA_DIR = os.path.join(os.getcwd(), "data")
if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)
DB_PATH = os.path.join(DATA_DIR, "vip_bet.db")

DIAMOND_RATE = 40
REF_BONUS = 40
BOT_USERNAME = "self_made_iran_bot"
ACTIVATE_COST = 20
HOURLY_COST = 2
# ساعت نام سلف؛ 210 دقیقه یعنی UTC+03:30 (قابل تغییر برای ساعت محل شما)
CLOCK_UTC_OFFSET_MINUTES = 210

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")
logging.basicConfig(level=logging.INFO)
db_lock = threading.RLock()

# ----------------- یوزربات / لاگین -----------------
LOGIN_CLIENTS = {}
SELF_CLIENTS = {}
LOGIN_LOOPS = {}
temp_data = {}
AUTH_FLOOD_UNTIL = {}  # uid -> unix timestamp; prevents repeated SendCode attempts
SELF_TASKS = {}
ADMIN_STATE = {}

# وضعیت‌های runtime سلف (دستورات راهنمای AX)
BLOCKED_USERS = {}          # uid -> set(user_id)
MUTED_USERS = {}            # uid -> set((chat_id, user_id))
AUTO_REACTION_TARGETS = {}  # uid -> {str(user_id): emoji}

# عضویت اجباری ربات (تنظیم‌شده از پنل ادمین)
def get_forced_channels():
    raw = get_setting("forced_channels")
    if not raw:
        return []
    try:
        return json.loads(raw)
    except Exception:
        return [x.strip() for x in raw.split(",") if x.strip()]

def set_forced_channels(channels):
    channels = list(dict.fromkeys([str(x).strip() for x in channels if str(x).strip()]))
    set_setting("forced_channels", json.dumps(channels, ensure_ascii=False))

def check_forced_join_bot(user_id):
    """عضویت اجباری را با خود Bot API بررسی می‌کند."""
    if is_admin(user_id):
        return True, []
    channels = get_forced_channels()
    if not channels:
        return True, []
    missing = []
    for ch in channels:
        try:
            member = bot.get_chat_member(ch, user_id)
            status = getattr(member, "status", "")
            if status in ("left", "kicked"):
                missing.append(ch)
        except Exception as e:
            logging.warning("forced join check failed for %s: %s", ch, e)
            missing.append(ch)
    return (not missing), missing

def forced_join_markup(channels):
    kb = types.InlineKeyboardMarkup()
    for ch in channels:
        username = ch.lstrip("@")
        kb.add(types.InlineKeyboardButton(f"📢 ورود به {ch}", url=f"https://t.me/{username}"))
    kb.add(types.InlineKeyboardButton("🔄 بررسی عضویت", callback_data="joincheck"))
    return kb

LOGIN_LOOP = asyncio.new_event_loop()

def _login_loop_worker():
    asyncio.set_event_loop(LOGIN_LOOP)
    LOGIN_LOOP.run_forever()

threading.Thread(target=_login_loop_worker, daemon=True).start()

def run_login_coro(coro):
    return asyncio.run_coroutine_threadsafe(coro, LOGIN_LOOP)


# ----------------- دیتابیس -----------------
def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.executescript("""
        PRAGMA foreign_keys = ON;
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            diamonds INTEGER DEFAULT 0,
            created_at INTEGER,
            is_self_active INTEGER DEFAULT 0,
            self_active_time INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        );
        CREATE TABLE IF NOT EXISTS referrals (
            user_id INTEGER PRIMARY KEY,
            count INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS ref_used (
            user_id INTEGER PRIMARY KEY,
            referrer_id INTEGER
        );
        CREATE TABLE IF NOT EXISTS bets (
            bet_id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER,
            creator_id INTEGER,
            amount INTEGER,
            state TEXT,
            player_joined_id INTEGER,
            message_id INTEGER,
            created_at INTEGER
        );
        CREATE TABLE IF NOT EXISTS self_settings (
            user_id INTEGER PRIMARY KEY,
            text_mode TEXT DEFAULT 'normal',
            is_clock_on INTEGER DEFAULT 0,
            font_style TEXT DEFAULT 'font1',
            action_mode TEXT DEFAULT 'none',
            is_auto_reply_on INTEGER DEFAULT 0,
            auto_reply_text TEXT DEFAULT '',
            base_first_name TEXT DEFAULT '',
            base_last_name TEXT DEFAULT '',
            is_bio_on INTEGER DEFAULT 0,
            is_seen_on INTEGER DEFAULT 0,
            is_typing_on INTEGER DEFAULT 0,
            anti_raid INTEGER DEFAULT 0,
            tabchi_on INTEGER DEFAULT 0,
            tabchi_text TEXT DEFAULT 'سلام 👋 پیام شما دریافت شد.'
        );
        """)
        # مهاجرت امن دیتابیس قدیمی؛ هیچ موجودی/کاربری حذف یا تغییر نمی‌شود.
        cur = conn.cursor()
        cur.execute("PRAGMA table_info(self_settings)")
        cols = {row[1] for row in cur.fetchall()}
        migrations = {
            'base_first_name': "ALTER TABLE self_settings ADD COLUMN base_first_name TEXT DEFAULT ''",
            'base_last_name': "ALTER TABLE self_settings ADD COLUMN base_last_name TEXT DEFAULT ''",
            'is_bio_on': "ALTER TABLE self_settings ADD COLUMN is_bio_on INTEGER DEFAULT 0",
            'is_seen_on': "ALTER TABLE self_settings ADD COLUMN is_seen_on INTEGER DEFAULT 0",
            'is_typing_on': "ALTER TABLE self_settings ADD COLUMN is_typing_on INTEGER DEFAULT 0",
            'anti_raid': "ALTER TABLE self_settings ADD COLUMN anti_raid INTEGER DEFAULT 0",
            'tabchi_on': "ALTER TABLE self_settings ADD COLUMN tabchi_on INTEGER DEFAULT 0",
            'tabchi_text': "ALTER TABLE self_settings ADD COLUMN tabchi_text TEXT DEFAULT 'سلام 👋 پیام شما دریافت شد.'",
        }
        for col, sql in migrations.items():
            if col not in cols:
                cur.execute(sql)

        # امکانات اضافه‌شده از AX
        extra_cols = {
            "bold_mode": "ALTER TABLE self_settings ADD COLUMN bold_mode INTEGER DEFAULT 0",
            "auto_save": "ALTER TABLE self_settings ADD COLUMN auto_save INTEGER DEFAULT 0",
            "anti_report": "ALTER TABLE self_settings ADD COLUMN anti_report INTEGER DEFAULT 1",
            "enemy_active": "ALTER TABLE self_settings ADD COLUMN enemy_active INTEGER DEFAULT 0",
            "friend_active": "ALTER TABLE self_settings ADD COLUMN friend_active INTEGER DEFAULT 0",
            "crash_active": "ALTER TABLE self_settings ADD COLUMN crash_active INTEGER DEFAULT 0",
            "pv_lock": "ALTER TABLE self_settings ADD COLUMN pv_lock INTEGER DEFAULT 0",
            "pv_photo": "ALTER TABLE self_settings ADD COLUMN pv_photo INTEGER DEFAULT 0",
            "pv_video": "ALTER TABLE self_settings ADD COLUMN pv_video INTEGER DEFAULT 0",
            "pv_gif": "ALTER TABLE self_settings ADD COLUMN pv_gif INTEGER DEFAULT 0",
            "pv_voice": "ALTER TABLE self_settings ADD COLUMN pv_voice INTEGER DEFAULT 0",
            "pv_music": "ALTER TABLE self_settings ADD COLUMN pv_music INTEGER DEFAULT 0",
            "pv_sticker": "ALTER TABLE self_settings ADD COLUMN pv_sticker INTEGER DEFAULT 0",
            "pv_doc": "ALTER TABLE self_settings ADD COLUMN pv_doc INTEGER DEFAULT 0",
            "enemy_list": "ALTER TABLE self_settings ADD COLUMN enemy_list TEXT DEFAULT '[]'",
            "friend_list": "ALTER TABLE self_settings ADD COLUMN friend_list TEXT DEFAULT '[]'",
            "crash_list": "ALTER TABLE self_settings ADD COLUMN crash_list TEXT DEFAULT '[]'",
            "enemy_replies": "ALTER TABLE self_settings ADD COLUMN enemy_replies TEXT DEFAULT '[]'",
            "friend_replies": "ALTER TABLE self_settings ADD COLUMN friend_replies TEXT DEFAULT '[]'",
            "crash_replies": "ALTER TABLE self_settings ADD COLUMN crash_replies TEXT DEFAULT '[]'",
        }
        for col, sql in extra_cols.items():
            if col not in cols:
                cur.execute(sql)
        conn.commit()

# ----------------- توابع کمکی -----------------
INFINITE_OWNER_REPR = 10**18

def normalize_digits(value: str) -> str:
    """تبدیل اعداد فارسی/عربی و حذف فاصله‌ها برای کد ورود تلگرام."""
    trans = str.maketrans(
        "۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩",
        "01234567890123456789"
    )
    return value.translate(trans).replace(" ", "").replace("-", "")

def to_superscript(num: str) -> str:
    """تبدیل اعداد به بالانویس (فونت ۲)"""
    superscript_map = {
        '0': '⁰', '1': '¹', '2': '²', '3': '³', '4': '⁴',
        '5': '⁵', '6': '⁶', '7': '⁷', '8': '⁸', '9': '⁹'
    }
    return ''.join(superscript_map.get(c, c) for c in str(num))

def format_clock_by_font(clock: str, font: str) -> str:
    maps = {
        'font1': str.maketrans('0123456789:', '0123456789:'),
        'font2': str.maketrans('0123456789:', '⁰¹²³⁴⁵⁶⁷⁸⁹ː'),
        'font3': str.maketrans('0123456789:', '⓪①②③④⑤⑥⑦⑧⑨:'),
        'font4': str.maketrans('0123456789:', '０１２３４５６７８９：'),
        'font5': str.maketrans('0123456789:', '𝟎𝟏𝟐𝟑𝟒𝟓𝟔𝟕𝟖𝟗:'),
    }
    return clock.translate(maps.get(font, maps['font1']))

def get_clock_display(user_id: int) -> str:
    settings = get_self_settings(user_id)
    now = datetime.now(timezone(timedelta(minutes=CLOCK_UTC_OFFSET_MINUTES)))
    return format_clock_by_font(now.strftime('%H:%M'), settings.get('font_style', 'font1'))

def ensure_user(uid: int):
    with db_lock:
        with sqlite3.connect(DB_PATH) as conn:
            cur = conn.cursor()
            cur.execute("INSERT OR IGNORE INTO users(user_id,diamonds,created_at,is_self_active,self_active_time) VALUES(?,?,?,?,?)", 
                       (uid, 0, int(time.time()), 0, 0))
            cur.execute("INSERT OR IGNORE INTO referrals(user_id,count) VALUES(?,0)", (uid,))
            cur.execute("INSERT OR IGNORE INTO self_settings(user_id,text_mode,is_clock_on,font_style,action_mode,is_auto_reply_on,auto_reply_text) VALUES(?,?,?,?,?,?,?)",
                       (uid, 'normal', 0, 'font1', 'none', 0, ''))
            conn.commit()

def is_owner(uid: int) -> bool:
    return uid == OWNER_ID

def get_admin_ids():
    """لیست ادمین‌ها را از دیتابیس می‌خواند تا بعد از ری‌استارت هم باقی بمانند."""
    raw = get_setting("admin_ids")
    base = [OWNER_ID, DEVELOPER_ID]
    if raw:
        try:
            saved = [int(x) for x in json.loads(raw)]
            base.extend(saved)
        except Exception:
            pass
    return list(dict.fromkeys(base))

def save_admin_ids(ids):
    ids = [int(x) for x in ids if int(x) != OWNER_ID]
    set_setting("admin_ids", json.dumps(list(dict.fromkeys(ids))))
    ADMIN_IDS[:] = list(dict.fromkeys([OWNER_ID, DEVELOPER_ID] + ids))

def is_admin(uid: int) -> bool:
    return uid in get_admin_ids()

def get_balance(uid: int) -> int:
    if is_owner(uid):
        return INFINITE_OWNER_REPR
    ensure_user(uid)
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("SELECT diamonds FROM users WHERE user_id=?", (uid,))
        r = cur.fetchone()
        return int(r[0]) if r else 0

def set_balance(uid: int, amount: int):
    if is_owner(uid):
        return
    ensure_user(uid)
    with db_lock:
        with sqlite3.connect(DB_PATH) as conn:
            cur = conn.cursor()
            cur.execute("UPDATE users SET diamonds=? WHERE user_id=?", (int(amount), uid))
            conn.commit()

def change_balance(uid: int, delta: int):
    if is_owner(uid):
        return
    ensure_user(uid)
    with db_lock:
        with sqlite3.connect(DB_PATH) as conn:
            cur = conn.cursor()
            cur.execute("UPDATE users SET diamonds = diamonds + ? WHERE user_id=?", (delta, uid))
            conn.commit()

def is_self_active(uid: int) -> bool:
    ensure_user(uid)
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("SELECT is_self_active, self_active_time FROM users WHERE user_id=?", (uid,))
        r = cur.fetchone()
        if not r or r[0] == 0:
            return False
        current_time = int(time.time())
        hours_passed = (current_time - r[1]) // 3600
        if hours_passed > 0:
            cost = hours_passed * HOURLY_COST
            bal = get_balance(uid)
            if bal >= cost:
                change_balance(uid, -cost)
                with db_lock:
                    with sqlite3.connect(DB_PATH) as conn:
                        cur2 = conn.cursor()
                        cur2.execute("UPDATE users SET self_active_time=? WHERE user_id=?", (current_time, uid))
                        conn.commit()
                return True
            else:
                with db_lock:
                    with sqlite3.connect(DB_PATH) as conn:
                        cur2 = conn.cursor()
                        cur2.execute("UPDATE users SET is_self_active=0, self_active_time=0 WHERE user_id=?", (uid,))
                        conn.commit()
                return False
        return True

def activate_self(uid: int):
    ensure_user(uid)
    bal = get_balance(uid)
    if bal < ACTIVATE_COST:
        return False, "موجودی کافی نیست"
    change_balance(uid, -ACTIVATE_COST)
    with db_lock:
        with sqlite3.connect(DB_PATH) as conn:
            cur = conn.cursor()
            cur.execute("UPDATE users SET is_self_active=1, self_active_time=? WHERE user_id=?", (int(time.time()), uid))
            conn.commit()
    return True, "سلف شما فعال شد"

def deactivate_self(uid: int):
    ensure_user(uid)
    with db_lock:
        with sqlite3.connect(DB_PATH) as conn:
            cur = conn.cursor()
            cur.execute("UPDATE users SET is_self_active=0, self_active_time=0 WHERE user_id=?", (uid,))
            conn.commit()

def get_self_settings(uid: int):
    ensure_user(uid)
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("""SELECT text_mode,is_clock_on,font_style,action_mode,is_auto_reply_on,auto_reply_text,
                              base_first_name,base_last_name,is_bio_on,is_seen_on,is_typing_on,anti_raid,tabchi_on,tabchi_text,
                              bold_mode,auto_save,anti_report,enemy_active,friend_active,crash_active,pv_lock,
                              pv_photo,pv_video,pv_gif,pv_voice,pv_music,pv_sticker,pv_doc,
                              enemy_list,friend_list,crash_list,enemy_replies,friend_replies,crash_replies
                       FROM self_settings WHERE user_id=?""", (uid,))
        r = cur.fetchone()
        if not r:
            return {}
        keys=['text_mode','is_clock_on','font_style','action_mode','is_auto_reply_on','auto_reply_text',
              'base_first_name','base_last_name','is_bio_on','is_seen_on','is_typing_on','anti_raid','tabchi_on','tabchi_text',
              'bold_mode','auto_save','anti_report','enemy_active','friend_active','crash_active','pv_lock',
              'pv_photo','pv_video','pv_gif','pv_voice','pv_music','pv_sticker','pv_doc',
              'enemy_list','friend_list','crash_list','enemy_replies','friend_replies','crash_replies']
        d=dict(zip(keys,r))
        for k in ('enemy_list','friend_list','crash_list','enemy_replies','friend_replies','crash_replies'):
            try: d[k]=json.loads(d.get(k) or '[]')
            except Exception: d[k]=[]
        return d

def set_self_settings(uid: int, key: str, value):
    ensure_user(uid)
    with db_lock:
        with sqlite3.connect(DB_PATH) as conn:
            cur = conn.cursor()
            cur.execute(f"UPDATE self_settings SET {key}=? WHERE user_id=?", (value, uid))
            conn.commit()

def set_setting(key: str, value: str):
    with db_lock, sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(key,value))
        conn.commit()

def get_setting(key: str):
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("SELECT value FROM settings WHERE key=?", (key,))
        r = cur.fetchone()
        return r[0] if r else None

def add_referral(referrer_id: int):
    with db_lock, sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("INSERT INTO referrals(user_id,count) VALUES(?,1) ON CONFLICT(user_id) DO UPDATE SET count=count+1",(referrer_id,))
        conn.commit()

def get_ref_count(uid: int) -> int:
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("SELECT count FROM referrals WHERE user_id=?", (uid,))
        r = cur.fetchone()
        return int(r[0]) if r else 0

def mark_ref_used(user_id: int, referrer_id: int):
    with db_lock, sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("INSERT OR IGNORE INTO ref_used(user_id,referrer_id) VALUES(?,?)", (user_id, referrer_id))
        conn.commit()

def has_used_ref(user_id: int):
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("SELECT referrer_id FROM ref_used WHERE user_id=?", (user_id,))
        r = cur.fetchone()
        return int(r[0]) if r else None

def user_display_from_userobj(u):
    if not u:
        return "کاربر"
    if getattr(u, "username", None):
        return f"@{u.username}"
    name = getattr(u, "first_name", None) or "کاربر"
    return f"<a href='tg://user?id={u.id}'>{html.escape(name)}</a>"

def user_display_from_id(uid: int):
    try:
        u = bot.get_chat(uid)
        return user_display_from_userobj(u)
    except Exception:
        if is_owner(uid):
            return "مالک (∞)"
        return f"<a href='tg://user?id={uid}'>کاربر</a>"

def in_private(m): return m.chat.type == "private"
def in_group(m): return m.chat.type in ("group","supergroup")

# ----------------- START -----------------
@bot.message_handler(commands=['start'])
def cmd_start(m: types.Message):
    args = m.text.split()
    inviter_id = None
    if len(args) > 1:
        try:
            inviter_id = int(args[1])
        except:
            inviter_id = None
    user_id = m.from_user.id
    ensure_user(user_id)

    # عضویت اجباری قبل از نمایش منوی ربات
    joined, missing = check_forced_join_bot(user_id)
    if not joined:
        bot.send_message(
            m.chat.id,
            "⚠️ برای استفاده از ربات ابتدا باید در کانال‌های زیر عضو شوید:",
            reply_markup=forced_join_markup(missing)
        )
        return

    if inviter_id and inviter_id != user_id and not has_used_ref(user_id):
        change_balance(inviter_id, REF_BONUS)
        add_referral(inviter_id)
        mark_ref_used(user_id, inviter_id)
        try:
            bot.send_message(user_id, f"💎 با تشکر از دعوت! به دعوت‌کننده‌ی شما {REF_BONUS} الماس داده شد.")
        except:
            pass
        try:
            bot.send_message(inviter_id, f"✅ یک نفر با لینک دعوت شما وارد ربات شد و {REF_BONUS} الماس به شما داده شد.")
        except:
            pass
    if in_private(m):
    text = "سلام 👋\nبه ربات VIP خوش آمدید 🌟\nاز منو زیر گزینه مورد نظر را انتخاب کنید."

    premium_entities = [
        types.MessageEntity(
            type="custom_emoji",
            offset=6,
            length=2,
            custom_emoji_id="5994750571041525522"
        ),
        types.MessageEntity(
            type="custom_emoji",
            offset=35,
            length=2,
            custom_emoji_id="5958376256788502078"
        )
    ]

    photo_id = get_setting("start_photo")
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row("≼ سـلـفـ 𝐕𝐢𝐏 ≽", "≼ شـارژ مـوجـودی 💳 ≽")
    markup.row("≼ الماس رایگان ≽", "≼ پروفایل ≽")

    if photo_id:
        try:
            bot.send_photo(
                m.chat.id,
                photo_id,
                caption=text,
                caption_entities=premium_entities,
                reply_markup=markup
            )
        except:
            bot.send_message(
                m.chat.id,
                text,
                entities=premium_entities,
                reply_markup=markup
            )
    else:
        bot.send_message(
            m.chat.id,
            text,
            entities=premium_entities,
            reply_markup=markup
        )

# ============================================================
# ✅ بخش احراز هویت با کد تلگرام
# ============================================================

@bot.message_handler(func=lambda m: in_private(m) and m.text and m.text.strip() == "≼ سـلـفـ 𝐕𝐢𝐏 ≽")
def cmd_self(m: types.Message):
    uid = m.from_user.id
    ensure_user(uid)

    if is_self_active(uid):
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("❌ حذف کردن سلف", callback_data="self:deactivate"))
        bot.send_message(m.chat.id, "✅ سلف شما فعال است!\nبرای غیر فعال کردن روی دکمه زیر کلیک کنید.", reply_markup=markup)
        return

    balance = get_balance(uid)
    if balance < ACTIVATE_COST:
        bot.send_message(
            m.chat.id,
            f"❌ موجودی کافی نیست.\n"
            f"هزینه فعال‌سازی سلف: {ACTIVATE_COST} الماس\n"
            f"موجودی شما: {balance} الماس"
        )
        return

    # هزینه فعال‌سازی قبل از شروع لاگین رزرو/کسر می‌شود.
    change_balance(uid, -ACTIVATE_COST)

    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    markup.add(types.KeyboardButton("📱 ارسال شماره تلفن", request_contact=True))
    bot.send_message(
        m.chat.id,
        f"✅ {ACTIVATE_COST} الماس از موجودی شما کسر شد.\n\n"
        "🔐 حالا شماره تلفن خود را ارسال کنید تا کد ورود فرستاده شود.",
        reply_markup=markup
    )


@bot.message_handler(content_types=['contact'])
def handle_contact(m: types.Message):
    uid = m.from_user.id
    ensure_user(uid)

    if not m.contact:
        return
    if m.contact.user_id != uid:
        bot.send_message(m.chat.id, "❌ لطفاً شماره تلفن خودتان را ارسال کنید.")
        return

    phone = m.contact.phone_number

    # Telegram برای درخواست‌های مکرر کد، FloodWait اعمال می‌کند.
    # قبل از هر درخواست جدید، زمان محدودیت محلی را بررسی می‌کنیم تا دوباره SendCode زده نشود.
    now = time.time()
    blocked_until = AUTH_FLOOD_UNTIL.get(uid, 0)
    if blocked_until > now:
        remain = int(blocked_until - now)
        h, rem = divmod(remain, 3600)
        mm, ss = divmod(rem, 60)
        bot.send_message(
            m.chat.id,
            f"⏳ تلگرام موقتاً ارسال کد برای این حساب را محدود کرده است.\n"
            f"⏱ زمان باقی‌مانده: {h:02d}:{mm:02d}:{ss:02d}\n\n"
            "❗️در این مدت دوباره درخواست کد ندهید؛ با تمام شدن زمان محدودیت دوباره شماره را ارسال کنید."
        )
        return

    # اگر برای همین کاربر یک نشست کد فعال وجود دارد، درخواست دوم غیرضروری است.
    existing = temp_data.get(uid)
    if existing and existing.get("step") in ("code", "password") and LOGIN_CLIENTS.get(uid):
        bot.send_message(m.chat.id, "📩 یک کد قبلاً برای شما درخواست شده است. همان کد را وارد کنید.")
        return

    bot.send_message(m.chat.id, f"✅ شماره شما دریافت شد!\nشماره: {phone}\n\n📤 در حال ارسال درخواست کد به تلگرام...")

    async def login_start():
        client = None
        try:
            old = LOGIN_CLIENTS.pop(uid, None)
            if old:
                try:
                    await old.disconnect()
                except Exception:
                    pass

            client = Client(
                f"login_{uid}",
                api_id=API_ID,
                api_hash=API_HASH,
                in_memory=True,
                no_updates=True
            )
            await client.connect()

            sent = await client.send_code(phone)
            LOGIN_CLIENTS[uid] = client
            temp_data[uid] = {
                "step": "code",
                "phone": phone,
                "phone_code_hash": sent.phone_code_hash,
                "time": time.time(),
                "activation_paid": True
            }

            markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
            markup.row("≼ سـلـفـ 𝐕𝐢𝐏 ≽", "≼ شـارژ مـوجـودی 💳 ≽")
            markup.row("≼ الماس رایگان ≽", "≼ پروفایل ≽")
            bot.send_message(
                uid,
                "✅ کد تایید به تلگرام شما ارسال شد.\n📝 لطفاً کد ۵ رقمی را که از تلگرام دریافت کردید را با فاصله وارد کنید مثل  ( 5 4 6 1 2 ) :",
                reply_markup=markup
            )
        except FloodWait as e:
            # این محدودیت از سمت Telegram است و قابل دور زدن نیست.
            wait_seconds = int(getattr(e, "value", getattr(e, "x", 0)) or 0)
            if wait_seconds <= 0:
                wait_seconds = 1
            AUTH_FLOOD_UNTIL[uid] = time.time() + wait_seconds
            if client:
                try:
                    await client.disconnect()
                except Exception:
                    pass
            LOGIN_CLIENTS.pop(uid, None)
            state = temp_data.pop(uid, None)
            if state and state.get("activation_paid"):
                change_balance(uid, ACTIVATE_COST)
            h, rem = divmod(wait_seconds, 3600)
            mm, ss = divmod(rem, 60)
            bot.send_message(
                uid,
                f"⏳ تلگرام ارسال کد را موقتاً محدود کرده است.\n"
                f"⏱ زمان انتظار: {h:02d}:{mm:02d}:{ss:02d}\n\n"
                f"💎 {ACTIVATE_COST} الماس به موجودی شما برگشت داده شد.\n"
                "❗️لطفاً تا پایان این زمان دوباره درخواست کد ندهید."
            )
        except Exception as e:
            if client:
                try:
                    await client.disconnect()
                except Exception:
                    pass
            LOGIN_CLIENTS.pop(uid, None)
            state = temp_data.pop(uid, None)
            if state and state.get("activation_paid"):
                change_balance(uid, ACTIVATE_COST)
                bot.send_message(uid, f"❌ خطا در ارسال کد: {e}\n💎 {ACTIVATE_COST} الماس به موجودی شما برگشت داده شد.")
            else:
                bot.send_message(uid, f"❌ خطا در ارسال کد: {e}")

    run_login_coro(login_start())


# ============================================================
# 🧊 پنل شیشه‌ای Self VIP (برگرفته از پنل AX)
# ============================================================
def _panel_check(uid, value):
    return "✅" if value else "❌"

def generate_ax_panel_markup(uid):
    s = get_self_settings(uid)
    def c(v): return "✅" if bool(v) else "❌"
    font = s.get("font_style","font1")
    preview = format_clock_by_font("12:34", font)
    kb = types.InlineKeyboardMarkup(row_width=3)
    kb.row(
        types.InlineKeyboardButton(f"ساعت {c(s.get('is_clock_on'))}", callback_data=f"axp:clock:{uid}"),
        types.InlineKeyboardButton(f"بولد {c(s.get('bold_mode'))}", callback_data=f"axp:bold:{uid}")
    )
    kb.row(types.InlineKeyboardButton(f"تغییر فونت: {preview}", callback_data=f"axp:font:{uid}"))
    kb.row(
        types.InlineKeyboardButton(f"منشی {c(s.get('is_auto_reply_on'))}", callback_data=f"axp:reply:{uid}"),
        types.InlineKeyboardButton(f"سین {c(s.get('is_seen_on'))}", callback_data=f"axp:seen:{uid}")
    )
    kb.row(
        types.InlineKeyboardButton(f"تایپ {c(s.get('is_typing_on'))}", callback_data=f"axp:typing:{uid}"),
        types.InlineKeyboardButton(f"بازی {c(s.get('action_mode')=='game')}", callback_data=f"axp:action:{uid}")
    )
    kb.row(types.InlineKeyboardButton(f"ذخیره خودکار {c(s.get('auto_save'))}", callback_data=f"axp:autosave:{uid}"))
    kb.row(types.InlineKeyboardButton(f"سپر ضد ریپ {c(s.get('anti_report',1))}", callback_data=f"axp:antireport:{uid}"))
    kb.row(
        types.InlineKeyboardButton(f"دشمن {c(s.get('enemy_active'))}", callback_data=f"axp:enemy:{uid}"),
        types.InlineKeyboardButton(f"دوست {c(s.get('friend_active'))}", callback_data=f"axp:friend:{uid}"),
        types.InlineKeyboardButton(f"کراش {c(s.get('crash_active'))}", callback_data=f"axp:crash:{uid}")
    )
    kb.row(types.InlineKeyboardButton(f"🔒 قفل کل پیوی {c(s.get('pv_lock'))}", callback_data=f"axp:pvlock:{uid}"))
    kb.row(types.InlineKeyboardButton("🔻 قفل‌های رسانه پیوی 🔻", callback_data="axp:none:"+str(uid)))
    kb.row(
        types.InlineKeyboardButton(f"عکس {c(s.get('pv_photo'))}", callback_data=f"axp:media_photo:{uid}"),
        types.InlineKeyboardButton(f"ویدیو {c(s.get('pv_video'))}", callback_data=f"axp:media_video:{uid}"),
        types.InlineKeyboardButton(f"گیف {c(s.get('pv_gif'))}", callback_data=f"axp:media_gif:{uid}")
    )
    kb.row(
        types.InlineKeyboardButton(f"ویس {c(s.get('pv_voice'))}", callback_data=f"axp:media_voice:{uid}"),
        types.InlineKeyboardButton(f"موزیک {c(s.get('pv_music'))}", callback_data=f"axp:media_music:{uid}"),
        types.InlineKeyboardButton(f"استیکر {c(s.get('pv_sticker'))}", callback_data=f"axp:media_sticker:{uid}")
    )
    kb.row(types.InlineKeyboardButton(f"فایل {c(s.get('pv_doc'))}", callback_data=f"axp:media_doc:{uid}"))
    kb.row(
        types.InlineKeyboardButton("📊 وضعیت سلف", callback_data=f"axp:status:{uid}"),
        types.InlineKeyboardButton("🔄 بروزرسانی", callback_data=f"axp:refresh:{uid}")
    )
    kb.row(types.InlineKeyboardButton("❌ بستن پنل", callback_data=f"axp:close:{uid}"))
    return kb

def ax_panel_text(uid):
    s = get_self_settings(uid)
    return (
        "⚡️ <b>مدیریت پیشرفته سلف بات</b>\n"
        f"👤 کاربر: <code>{uid}</code>\n\n"
        "📡 وضعیت اتصال: <b>برقرار ✅</b>\n"
        f"⏰ ساعت: {'روشن ✅' if s.get('is_clock_on') else 'خاموش ❌'}\n"
        f"🔤 فونت ساعت/اسم: <b>{s.get('font_style','font1')}</b>\n"
        f"📝 حالت متن: <b>{s.get('text_mode','normal')}</b>\n"
        f"🤖 منشی: {'روشن ✅' if s.get('is_auto_reply_on') else 'خاموش ❌'}\n"
        f"👁 سین: {'روشن ✅' if s.get('is_seen_on') else 'خاموش ❌'}\n"
        f"⌨️ تایپ: {'روشن ✅' if s.get('is_typing_on') else 'خاموش ❌'}\n"
        f"🛡 سپر ضد ریپ: {'روشن ✅' if s.get('anti_report',1) else 'خاموش ❌'}\n"
        f"👤 دشمن/دوست/کراش: {'روشن' if s.get('enemy_active') or s.get('friend_active') or s.get('crash_active') else 'خاموش'}\n"
        f"🔒 قفل پیوی: {'روشن ✅' if s.get('pv_lock') else 'خاموش ❌'}"
    )

@bot.inline_handler(lambda q: (q.query or '').strip().lower() in ('panel', 'پنل', 'menu', 'منو'))
def ax_inline_panel(q):
    uid = q.from_user.id
    ensure_user(uid)
    if not is_self_active(uid):
        return bot.answer_inline_query(
            q.id, [], cache_time=0, is_personal=True,
            switch_pm_text="ابتدا سلف را فعال کنید", switch_pm_parameter="start"
        )
    result = types.InlineQueryResultArticle(
        id=f"ax_panel_{uid}",
        title="🧊 پنل شیشه‌ای سلف",
        description="پنل حرفه‌ای دستورات سلف",
        input_message_content=types.InputTextMessageContent(ax_panel_text(uid), parse_mode="HTML"),
        reply_markup=generate_ax_panel_markup(uid)
    )
    bot.answer_inline_query(q.id, [result], cache_time=0, is_personal=True)

@bot.inline_handler(lambda q: (q.query or '').strip().lower() in ('help', 'راهنما'))
def ax_inline_help(q):
    uid=q.from_user.id
    ensure_user(uid)
    if not is_self_active(uid):
        return bot.answer_inline_query(q.id, [], cache_time=0, is_personal=True,
                                       switch_pm_text="ابتدا سلف را فعال کنید", switch_pm_parameter="start")
    answer_help_inline(q.id, uid)

@bot.callback_query_handler(func=lambda c: c.data and c.data.startswith("axp:"))
def ax_panel_callback(c):
    try:
        uid = c.from_user.id
        parts = c.data.split(":")
        action = parts[1]
        target = int(parts[2])
        if uid != target:
            return bot.answer_callback_query(c.id, "⛔️ این پنل برای شما نیست.", show_alert=True)
        if not is_self_active(uid):
            return bot.answer_callback_query(c.id, "❌ سلف شما فعال نیست.", show_alert=True)
        s = get_self_settings(uid)

        toggle_map = {
            "clock": "is_clock_on", "reply": "is_auto_reply_on", "bio": "is_bio_on",
            "seen": "is_seen_on", "typing": "is_typing_on", "antiraid": "anti_raid",
            "autosave": "auto_save", "antireport": "anti_report",
            "enemy": "enemy_active", "friend": "friend_active", "crash": "crash_active",
            "pvlock": "pv_lock", "media_photo": "pv_photo", "media_video": "pv_video",
            "media_gif": "pv_gif", "media_voice": "pv_voice", "media_music": "pv_music",
            "media_sticker": "pv_sticker", "media_doc": "pv_doc",
        }
        if action in toggle_map:
            key = toggle_map[action]
            value = 0 if s.get(key, 0) else 1
            set_self_settings(uid, key, value)
            if action == "clock":
                refresh_clock_profile(uid)
            run_self_message(uid, f"✅ {key} {'روشن' if value else 'خاموش'} شد")
        elif action == "bold":
            value = 0 if s.get("bold_mode",0) else 1
            set_self_settings(uid, "bold_mode", value)
            set_self_settings(uid, "text_mode", "bold" if value else "normal")
            run_self_message(uid, f"بولد {'روشن' if value else 'خاموش'} شد")
        elif action in {"quote","spoiler"}:
            mode = action if s.get("text_mode") != action else "normal"
            set_self_settings(uid, "text_mode", mode)
            run_self_message(uid, f"حالت متن: {mode}")
        elif action == "font":
            fonts = FONT_KEYS_ORDER
            cur = s.get("font_style", "font1")
            value = fonts[(fonts.index(cur)+1) % len(fonts)] if cur in fonts else fonts[0]
            set_self_settings(uid, "font_style", value)
            # اگر ساعت روشن است، همین لحظه نام پروفایل را با فونت جدید Refresh کن.
            # اگر خاموش است، فونت ذخیره می‌شود و با روشن‌کردن ساعت اعمال خواهد شد.
            ok, err = refresh_clock_profile(uid)
            preview = format_clock_by_font('12:34', value)
            if ok:
                run_self_message(uid, f"🔤 فونت ساعت/اسم به {value} تغییر کرد: {preview}")
                try:
                    bot.answer_callback_query(c.id, f"✅ فونت تغییر کرد: {preview}", show_alert=True)
                except Exception:
                    pass
            else:
                # ذخیره فونت حتی در صورت قطع‌بودن سلف؛ با Refresh بعدی اعمال می‌شود.
                try:
                    bot.answer_callback_query(c.id, f"⚠️ فونت {value} ذخیره شد؛ اتصال سلف برای تغییر اسم برقرار نیست.", show_alert=True)
                except Exception:
                    pass
        elif action == "action":
            value = "none" if s.get("action_mode") == "game" else "game"
            set_self_settings(uid, "action_mode", value)
            run_self_message(uid, f"🎮 بازی {'روشن' if value=='game' else 'خاموش'} شد")
        elif action == "status":
            pass
        elif action == "refresh":
            refresh_clock_profile(uid)
        elif action == "none":
            return bot.answer_callback_query(c.id)
        elif action == "close":
            try:
                bot.edit_message_text("❌ <b>پنل بسته شد.</b>", inline_message_id=c.inline_message_id, parse_mode="HTML")
            except Exception:
                try: bot.delete_message(c.message.chat.id, c.message.message_id)
                except Exception: pass
            return bot.answer_callback_query(c.id)

        try:
            bot.edit_message_text(ax_panel_text(uid), inline_message_id=c.inline_message_id,
                                  reply_markup=generate_ax_panel_markup(uid), parse_mode="HTML")
        except Exception:
            try:
                bot.edit_message_reply_markup(inline_message_id=c.inline_message_id,
                                              reply_markup=generate_ax_panel_markup(uid))
            except Exception:
                pass
        bot.answer_callback_query(c.id, "✅ انجام شد")
    except Exception as e:
        logging.exception("AX/CIP panel callback error")
        try: bot.answer_callback_query(c.id, f"❌ خطا: {e}", show_alert=True)
        except Exception: pass

# ================== امکانات واقعی سلف ==================
def _escape_html(text):
    return html.escape(str(text), quote=False)

# حروف ساعت تمام فونت‌های استفاده‌شده؛ برای پاک‌کردن ساعت قبلی از اسم
CLOCK_FONT_CHARS = "0123456789:⁰¹²³⁴⁵⁶⁷⁸⁹ː⓪①②③④⑤⑥⑦⑧⑨∶０１２３４５６７８９：𝟎𝟏𝟐𝟑𝟒𝟓𝟔𝟕𝟖𝟗𝟘𝟙𝟚𝟛𝟜𝟝𝟞𝟟𝟠𝟡𝟢𝟣𝟤𝟥𝟦𝟧𝟨𝟩𝟪𝟫"
CLOCK_SUFFIX_RE = re.compile(r"(?:\s*[%s]+)+$" % re.escape(CLOCK_FONT_CHARS))

# فونت‌های ساعت؛ با هر بار زدن دکمه یکی عوض می‌شود.
FONT_STYLES = {
    "font1": str.maketrans("0123456789:", "0123456789:"),
    "font2": str.maketrans("0123456789:", "⁰¹²³⁴⁵⁶⁷⁸⁹ː"),
    "font3": str.maketrans("0123456789:", "⓪①②③④⑤⑥⑦⑧⑨∶"),
    "font4": str.maketrans("0123456789:", "０１２３４５６７８９："),
    "font5": str.maketrans("0123456789:", "𝟎𝟏𝟐𝟑𝟒𝟓𝟔𝟕𝟖𝟗:"),
    "font6": str.maketrans("0123456789:", "𝟘𝟙𝟚𝟛𝟜𝟝𝟞𝟟𝟠𝟡:"),
    "font7": str.maketrans("0123456789:", "𝟢𝟣𝟤𝟥𝟦𝟧𝟨𝟩𝟪𝟫:"),
}
FONT_KEYS_ORDER = list(FONT_STYLES)

HELP_TEXT = """[ 🛠 راهنمای پیشرفته سلف بات ]
━━━━━━━━━━━━━━━━━━━━
⚠️ توجه: تمامی تنظیمات روشن/خاموش (قفل‌های پیوی، ذخیره‌ها، منشی، ساعت و...) فقط از طریق دستور «پنل» قابل کنترل هستند.

✦ ابزار و مدیریت
» <code>تگ</code> یا <code>tagall</code> : تگ کردن همه اعضای گروه
» <code>تگ ادمین ها</code> : تگ کردن ادمین‌ها
» <code>دانلود</code> (ریپلای) : دانلود فایل رسانه
» <code>ذخیره</code> (ریپلای) : ذخیره کامل مدیا و فایل در سیو مسیج
» <code>بن</code> (ریپلای) : بن کردن کاربر از گروه
» <code>پین</code> / <code>آن پین</code> (ریپلای) : پین کردن پیام
» <code>اسپم [متن] [تعداد]</code> : ارسال پشت سر هم پیام
» <code>فلود [متن] [تعداد]</code> : ارسال پیام طولانی
» <code>حذف [تعداد]</code> یا <code>حذف همه</code> : پاک کردن پیام‌های خودتان
» <code>ping</code> یا <code>پینگ</code> : تست سرعت پاسخ سلف
» <code>تکرار [تعداد]</code> (ریپلای) : تکرار یک پیام

✦ پنل و تنظیمات
» <code>پنل</code> : باز کردن پنل شیشه‌ای
» <code>تغییر فونت</code> : تغییر فونت ساعت اسم
» <code>راهنما</code> : نمایش همین راهنما
» <code>/admin</code> : پنل مدیریت مالک/ادمین

✦ منشی و ترجمه
» <code>تنظیم متن منشی [متن]</code> : تغییر پیام پاسخ خودکار منشی
» منشی با سپر ضد ریپ و تأخیر طبیعی اجرا می‌شود

✦ مدیریت چت
» <code>بلاک روشن</code> | <code>بلاک خاموش</code> (ریپلای)
» <code>سکوت روشن</code> | <code>سکوت خاموش</code> (ریپلای)
» <code>ریاکشن [شکلک]</code> | <code>ریاکشن خاموش</code> (ریپلای)

✦ لیست‌ها (دشمن، دوست، کراش)
» <code>تنظیم دشمن</code> | <code>تنظیم دوست</code> | <code>تنظیم کراش</code> (ریپلای)
» <code>حذف دشمن</code> | <code>حذف دوست</code> | <code>حذف کراش</code> (ریپلای)
» <code>لیست دشمن</code> | <code>لیست دوست</code> | <code>لیست کراش</code>
» <code>پاکسازی لیست دشمن</code> | <code>پاکسازی لیست دوست</code> | <code>پاکسازی لیست کراش</code>
» <code>تنظیم متن دشمن [متن]</code> | <code>تنظیم متن دوست [متن]</code> | <code>تنظیم متن کراش [متن]</code>
» <code>حذف متن دشمن [عدد]</code> | <code>حذف متن دوست [عدد]</code> | <code>حذف متن کراش [عدد]</code>

✦ سرگرمی و انیمیشن
» <code>fun love</code> | <code>fun oclock</code> | <code>fun star</code>
» <code>fun snow</code> | <code>fun moon</code> | <code>fun fire</code> | <code>fun loading</code> | <code>fun bomb</code>
» <code>قلب</code> یا <code>heart</code> | <code>قلب خالی</code> یا <code>emptyheart</code>
» <code>تایپ</code> یا <code>typing</code> | <code>پروگرس</code> یا <code>progress</code>
» <code>موج</code> یا <code>wave</code> | <code>ضربان</code> یا <code>pulse</code>
━━━━━━━━━━━━━━━━━━━━"""

# جایگزین تابع قدیمی تا همه فونت‌ها یکسان کار کنند.
def format_clock_by_font(clock: str, font: str) -> str:
    return clock.translate(FONT_STYLES.get(font, FONT_STYLES["font1"]))

HELP_COPY_COMMANDS = [
    "تگ", "tagall", "تگ اعضا", "تگ اعضا گروه", "تگ ادمین ها", "تگ ادمینا",
    "دانلود", "ذخیره", "بن", "پین", "آن پین", "اسپم [متن] [تعداد]", "فلود [متن] [تعداد]",
    "حذف [تعداد]", "حذف همه", "ping", "پینگ", "تکرار [تعداد]",
    "تنظیم متن منشی [متن]", "بلاک روشن", "بلاک خاموش", "سکوت روشن", "سکوت خاموش",
    "ریاکشن ❤️", "ریاکشن خاموش",
    "تنظیم دشمن", "حذف دشمن", "لیست دشمن", "پاکسازی لیست دشمن", "تنظیم متن دشمن [متن]", "حذف متن دشمن [عدد]",
    "تنظیم دوست", "حذف دوست", "لیست دوست", "پاکسازی لیست دوست", "تنظیم متن دوست [متن]", "حذف متن دوست [عدد]",
    "تنظیم کراش", "حذف کراش", "لیست کراش", "پاکسازی لیست کراش", "تنظیم متن کراش [متن]", "حذف متن کراش [عدد]",
    "fun love", "fun oclock", "fun star", "fun snow", "fun moon", "fun fire", "fun loading", "fun bomb",
    "قلب", "heart", "قلب خالی", "emptyheart", "تایپ", "typing", "پروگرس", "progress", "موج", "wave", "ضربان", "pulse",
    "پنل", "تغییر فونت", "راهنما", "/admin",
]

def _copy_keyboard_raw():
    # Bot API CopyTextButton: با یک لمس متن دقیقاً در کلیپ‌بورد کپی می‌شود.
    rows=[]
    for i in range(0, len(HELP_COPY_COMMANDS), 2):
        row=[]
        for text in HELP_COPY_COMMANDS[i:i+2]:
            row.append({"text": f"📋 {text}", "copy_text": {"text": text}})
        rows.append(row)
    return {"inline_keyboard": rows}

def _raw_bot_call(method, payload):
    try:
        r=requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/{method}", json=payload, timeout=20)
        data=r.json()
        if not data.get("ok"):
            logging.warning("Bot API %s failed: %s", method, data)
        return data
    except Exception as e:
        logging.exception("Bot API %s error", method)
        return {"ok": False, "description": str(e)}

def send_help_copy_message(chat_id):
    return _raw_bot_call("sendMessage", {
        "chat_id": chat_id,
        "text": HELP_TEXT,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
        "reply_markup": _copy_keyboard_raw(),
    })

def answer_help_inline(query_id, uid):
    result={
        "type":"article",
        "id":f"cip_help_{uid}",
        "title":"📋 راهنمای سلف — کپی با یک لمس",
        "description":"روی هر دستور بزن تا همان متن کپی شود.",
        "input_message_content":{
            "message_text":HELP_TEXT,
            "parse_mode":"HTML",
            "disable_web_page_preview":True,
        },
        "reply_markup":_copy_keyboard_raw(),
    }
    return _raw_bot_call("answerInlineQuery", {
        "inline_query_id":query_id,
        "results":[result],
        "cache_time":0,
        "is_personal":True,
    })

def _clean_clock_from_name(name: str) -> str:
    return CLOCK_SUFFIX_RE.sub("", name or "").strip()

def get_clock_display(user_id: int) -> str:
    settings = get_self_settings(user_id)
    now = datetime.now(timezone(timedelta(minutes=CLOCK_UTC_OFFSET_MINUTES)))
    return format_clock_by_font(now.strftime('%H:%M'), settings.get('font_style', 'font1'))

def refresh_clock_profile(uid):
    """نام پروفایل را فوراً با فونت انتخاب‌شده به‌روزرسانی می‌کند."""
    client = SELF_CLIENTS.get(uid) or LOGIN_CLIENTS.get(uid)
    if not client:
        return False, "سلف متصل نیست."

    async def _refresh():
        s = get_self_settings(uid)
        me = await client.get_me()
        current_first = me.first_name or ""
        # همیشه نام پایه را از مقدار ذخیره‌شده می‌گیریم و ساعت قبلی را پاک می‌کنیم.
        base = _clean_clock_from_name(s.get("base_first_name") or current_first)
        base = base.strip() or "Self"
        if not s.get("base_first_name") or _clean_clock_from_name(s.get("base_first_name")) != base:
            set_self_settings(uid, "base_first_name", base)
        last_name = s.get("base_last_name") or me.last_name or ""
        if s.get("is_clock_on"):
            display = get_clock_display(uid)
            new_first = f"{base} {display}".strip()
        else:
            new_first = base
        await client.update_profile(first_name=new_first[:64], last_name=last_name[:64])
        return new_first

    try:
        fut = run_login_coro(_refresh())
        fut.result(timeout=12)
        return True, "انجام شد"
    except Exception as e:
        logging.warning("refresh clock failed for %s: %s", uid, e)
        return False, str(e)

async def _apply_text_style(message, uid):
    if not message.text or message.text.strip().lower() in {"پنل", "panel", "/panel"}:
        return
    s = get_self_settings(uid)
    mode = s.get("text_mode", "normal")
    raw = message.text
    if mode == "normal":
        return
    try:
        if mode == "bold":
            await message.edit_text(f"<b>{_escape_html(raw)}</b>", parse_mode=enums.ParseMode.HTML)
        elif mode == "quote":
            await message.edit_text(f"<blockquote>{_escape_html(raw)}</blockquote>", parse_mode=enums.ParseMode.HTML)
        elif mode == "spoiler":
            await message.edit_text(f"<tg-spoiler>{_escape_html(raw)}</tg-spoiler>", parse_mode=enums.ParseMode.HTML)
    except Exception:
        pass

async def _clock_loop(client, uid):
    try:
        me = await client.get_me()
        s = get_self_settings(uid)
        base = _clean_clock_from_name(s.get("base_first_name") or me.first_name or "")
        if not s.get("base_first_name") or s.get("base_first_name") != base:
            set_self_settings(uid, "base_first_name", base)
        if not s.get("base_last_name"):
            set_self_settings(uid, "base_last_name", me.last_name or "")
        while is_self_active(uid):
            s = get_self_settings(uid)
            base = _clean_clock_from_name(s.get("base_first_name") or me.first_name or "")
            target_name = f"{base} {get_clock_display(uid)}".strip() if s.get("is_clock_on") else base
            try:
                current = await client.get_me()
                if (current.first_name or "") != target_name:
                    await client.update_profile(first_name=target_name, last_name=s.get("base_last_name") or current.last_name or "")
            except Exception as e:
                logging.debug("clock profile update failed for %s: %s", uid, e)
            await asyncio.sleep(30)
    except asyncio.CancelledError:
        return
    except Exception:
        logging.exception("clock loop stopped for %s", uid)

async def _incoming_features(client, message, uid):
    if not message.from_user or message.from_user.is_bot or message.outgoing:
        return
    sender_id = message.from_user.id
    chat_id = message.chat.id if message.chat else 0
    s = get_self_settings(uid)

    # ریاکشن خودکار روی شخص مشخص‌شده
    # از دیتابیس هم بازیابی می‌کنیم تا بعد از ری‌استارت سلف تنظیمات از بین نرود.
    reactions = AUTO_REACTION_TARGETS.setdefault(uid, {})
    # هر بار از دیتابیس هم همگام می‌کنیم؛ این کار باعث می‌شود تنظیم قدیمی بعد از restart جا نماند.
    try:
        raw = get_setting(f"auto_reactions_{uid}")
        if raw:
            saved = json.loads(raw)
            if isinstance(saved, dict):
                reactions.update({str(k): str(v) for k, v in saved.items() if v})
    except Exception:
        logging.exception("failed to load auto reactions for %s", uid)
    emoji = reactions.get(str(sender_id))
    if emoji:
        ok=False
        for fn in (
            lambda: client.send_reaction(chat_id=chat_id, message_id=message.id, emoji=emoji),
            lambda: message.react(emoji=emoji),
        ):
            try:
                await fn(); ok=True; break
            except Exception as e:
                logging.warning("auto reaction attempt failed uid=%s sender=%s chat=%s emoji=%s: %s", uid, sender_id, chat_id, emoji, e)
        if not ok:
            logging.warning("auto reaction failed permanently uid=%s sender=%s", uid, sender_id)

    # سکوت: پیام‌های شخص در چت مشخص حذف می‌شوند.
    if (chat_id, sender_id) in MUTED_USERS.get(uid, set()):
        try: await message.delete()
        except Exception: pass
        return

    # قفل کل پیوی و قفل رسانه‌ها
    if message.chat and message.chat.type == enums.ChatType.PRIVATE:
        should_delete = bool(s.get("pv_lock"))
        if getattr(message, "photo", None) and s.get("pv_photo"): should_delete = True
        if getattr(message, "video", None) and s.get("pv_video"): should_delete = True
        if getattr(message, "animation", None) and s.get("pv_gif"): should_delete = True
        if getattr(message, "voice", None) and s.get("pv_voice"): should_delete = True
        if getattr(message, "audio", None) and s.get("pv_music"): should_delete = True
        if getattr(message, "sticker", None) and s.get("pv_sticker"): should_delete = True
        if getattr(message, "document", None) and s.get("pv_doc"): should_delete = True
        if should_delete:
            try: await message.delete()
            except Exception: pass
            return
        if s.get("is_seen_on"):
            try: await client.read_chat_history(message.chat.id)
            except Exception: pass

    # دشمن/دوست/کراش در پیوی و گروه
    kind = None
    if sender_id in (s.get("enemy_list") or []) and s.get("enemy_active"): kind = "enemy"
    elif sender_id in (s.get("friend_list") or []) and s.get("friend_active"): kind = "friend"
    elif sender_id in (s.get("crash_list") or []) and s.get("crash_active"): kind = "crash"
    if kind:
        key = f"{kind}_replies"
        defaults = {
            "enemy": ["⚠️ پیام شما دریافت شد."],
            "friend": ["سلام رفیق ❤️", "جانم؟"],
            "crash": ["سلام ❤️", "جانم بفرما؟"]
        }
        replies = s.get(key) or defaults[kind]
        try:
            if s.get("is_typing_on"):
                await client.send_chat_action(chat_id, enums.ChatAction.TYPING)
                await asyncio.sleep(0.6)
            await message.reply_text(random.choice(replies))
        except Exception: pass
        return

    # منشی فقط پیوی
    if message.chat and message.chat.type == enums.ChatType.PRIVATE and (s.get("is_auto_reply_on") or s.get("tabchi_on")):
        reply_text = s.get("auto_reply_text") if s.get("is_auto_reply_on") else s.get("tabchi_text")
        reply_text = reply_text or "سلام 👋 پیام شما دریافت شد."
        try:
            if s.get("is_typing_on"):
                await client.send_chat_action(message.chat.id, enums.ChatAction.TYPING)
                await asyncio.sleep(1)
            await message.reply_text(reply_text)
        except Exception: pass

async def _safe_delete(message):
    try: await message.delete()
    except Exception: pass

async def _tag_members(client, message, admins=False):
    if not message.chat or message.chat.type not in (enums.ChatType.GROUP, enums.ChatType.SUPERGROUP):
        return await message.reply_text("❌ این دستور فقط داخل گروه یا سوپرگروه کار می‌کند.")
    tags=[]
    try:
        if admins:
            try:
                iterator = client.get_chat_members(message.chat.id, filter=enums.ChatMembersFilter.ADMINISTRATORS)
                async for member in iterator:
                    u=member.user
                    if not u or u.is_bot or u.is_deleted:
                        continue
                    name=((u.first_name or "کاربر") + (" " + u.last_name if u.last_name else "")).strip()
                    tags.append(f'<a href="tg://user?id={u.id}">{_escape_html(name)}</a>')
            except Exception as first_error:
                logging.warning("admin filter failed, using status fallback: %s", first_error)
                iterator = client.get_chat_members(message.chat.id, limit=500)
                async for member in iterator:
                    status=str(getattr(member, "status", "")).lower()
                    if status not in {"administrator", "owner", "creator", "chatmembersstatus.administrator", "chatmembersstatus.owner"}:
                        continue
                    u=member.user
                    if not u or u.is_bot or u.is_deleted:
                        continue
                    name=((u.first_name or "کاربر") + (" " + u.last_name if u.last_name else "")).strip()
                    tags.append(f'<a href="tg://user?id={u.id}">{_escape_html(name)}</a>')
        else:
            iterator = client.get_chat_members(message.chat.id, limit=500)
            async for member in iterator:
                u=member.user
                if not u or u.is_bot or u.is_deleted:
                    continue
                name=((u.first_name or "کاربر") + (" " + u.last_name if u.last_name else "")).strip()
                tags.append(f'<a href="tg://user?id={u.id}">{_escape_html(name)}</a>')
    except Exception as e:
        logging.exception("tag members failed")
        return await message.reply_text(f"❌ دریافت اعضای گروه انجام نشد:\n<code>{_escape_html(e)}</code>", parse_mode=enums.ParseMode.HTML)
    if not tags:
        return await message.reply_text("❌ هیچ عضو قابل تگ پیدا نشد. اکانت سلف باید عضو گروه باشد و تلگرام باید اجازه دریافت اعضا را بدهد.")
    chunks=[]; cur=""
    for t in tags:
        if len(cur)+len(t)+1>3500:
            chunks.append(cur); cur=""
        cur += (" " if cur else "")+t
    if cur: chunks.append(cur)
    title="📢 تگ ادمین‌ها:" if admins else "📢 تگ اعضای گروه:"
    try: await message.delete()
    except Exception: pass
    for i,ch in enumerate(chunks):
        await client.send_message(message.chat.id, (title+"\n" if i==0 else "")+ch, parse_mode=enums.ParseMode.HTML, disable_web_page_preview=True)
        await asyncio.sleep(0.3)

async def _run_fun(client, message, name):
    frames={
      "love":["🤍","🤍❤️","🤍❤️🩷","🤍❤️🩷💗","❤️🩷💗💕"],
      "oclock":["🕐","🕑","🕒","🕓","🕔","🕕","🕖","🕗","🕘","🕙","🕚","🕛"],
      "star":["⭐","🌟","✨","🌟","⭐"],
      "snow":["❄️","❄️❄️","☃️❄️","❄️☃️❄️"],
      "moon":["🌑","🌒","🌓","🌔","🌕","🌖","🌗","🌘"],
      "fire":["🔥","🔥🔥","❤️‍🔥🔥","🔥🔥🔥"],
      "loading":["▱▱▱▱▱","▰▱▱▱▱","▰▰▱▱▱","▰▰▰▱▱","▰▰▰▰▱","▰▰▰▰▰"],
      "bomb":["💣","💣💨","💣💥","💥"],
      "heart":["🤍","🩷","❤️","💖","💗"],
      "emptyheart":["♡","♡♡","♡♡♡","♡♡♡♡"],
      "typing":["▌","▌▌","▌▌▌"],
      "progress":["0%","25%","50%","75%","100%"],
      "wave":["👋","👋🏻","👋🏻👋","👋"],
      "pulse":["💓","💗","💖","💗","💓"]
    }
    seq=frames.get(name, [name])
    try:
        m=message
        for i,f in enumerate(seq):
            if i==0: m=await message.reply_text(f)
            else: await asyncio.sleep(0.25); await m.edit_text(f)
    except Exception: pass

async def _self_runtime_handler(client, message):
    # در پیام‌های outgoing بعضی نسخه‌های Pyrogram from_user را خالی می‌دهند؛ شناسه خود سلف را از client.me می‌گیریم.
    uid = getattr(message.from_user, "id", None)
    if not uid:
        try:
            me = await client.get_me()
            uid = me.id if me else 0
        except Exception:
            uid = 0
    if not uid or not is_self_active(uid) or not message.outgoing or not message.text:
        return
    cmd = re.sub(r"\s+", " ", message.text.strip())
    low = cmd.casefold()
    if low in {"پنل","panel","/panel"}:
        await self_panel_command_controller(client, message); return

    if low in {"تغییر فونت", "فونت"}:
        s = get_self_settings(uid)
        fonts = FONT_KEYS_ORDER
        cur = s.get("font_style", "font1")
        value = fonts[(fonts.index(cur) + 1) % len(fonts)] if cur in fonts else fonts[0]
        set_self_settings(uid, "font_style", value)
        ok, err = refresh_clock_profile(uid)
        preview = format_clock_by_font("12:34", value)
        if ok:
            await message.edit_text(f"✅ فونت به <code>{html.escape(value)}</code> تغییر کرد.\nنمونه ساعت: <code>{html.escape(preview)}</code>", parse_mode=enums.ParseMode.HTML)
        else:
            await message.edit_text(f"⚠️ فونت ذخیره شد ولی پروفایل تغییر نکرد: {html.escape(err)}", parse_mode=enums.ParseMode.HTML)
        return

    # راهنما: همان چیدمان متنی نمونه، با دستورها داخل code تا در تلگرام راحت انتخاب/کپی شوند.
    if low in {"راهنما", "/help", "help"}:
        try:
            results=await client.get_inline_bot_results(BOT_USERNAME, "help")
            if results and results.results:
                try: await message.delete()
                except Exception: pass
                await client.send_inline_bot_result(message.chat.id, results.query_id, results.results[0].id)
                return
        except Exception as e:
            logging.warning("inline help failed: %s", e)
        try: await message.edit_text(HELP_TEXT, parse_mode=enums.ParseMode.HTML, disable_web_page_preview=True)
        except Exception: await message.reply_text(HELP_TEXT, parse_mode=enums.ParseMode.HTML, disable_web_page_preview=True)
        return

    # دشمن/دوست/کراش
    m=re.match(r"^(تنظیم|حذف) (دشمن|دوست|کراش)$", cmd)
    if m:
        op,typ=m.groups(); target=message.reply_to_message.from_user if message.reply_to_message else None
        if not target: return await message.edit_text("❌ این دستور باید روی پیام کاربر ریپلای شود.")
        key={"دشمن":"enemy_list","دوست":"friend_list","کراش":"crash_list"}[typ]
        arr=list(get_self_settings(uid).get(key) or [])
        if op=="تنظیم":
            if target.id not in arr: arr.append(target.id)
            result=f"✅ {typ} تنظیم شد."
        else:
            if target.id in arr: arr.remove(target.id)
            result=f"✅ {typ} حذف شد."
        set_self_settings(uid,key,json.dumps(arr)); await message.edit_text(result); return
    m=re.match(r"^لیست (دشمن|دوست|کراش)$",cmd)
    if m:
        typ=m.group(1); key={"دشمن":"enemy_list","دوست":"friend_list","کراش":"crash_list"}[typ]
        arr=get_self_settings(uid).get(key) or []
        await message.edit_text(f"📋 لیست {typ}:\n"+(("\n".join(f"• <code>{x}</code>" for x in arr)) if arr else "خالی است."),parse_mode="HTML"); return
    m=re.match(r"^پاکسازی لیست (دشمن|دوست|کراش)$",cmd)
    if m:
        typ=m.group(1); key={"دشمن":"enemy_list","دوست":"friend_list","کراش":"crash_list"}[typ]
        set_self_settings(uid,key,"[]"); await message.edit_text(f"✅ لیست {typ} پاک شد."); return
    m=re.match(r"^تنظیم متن (دشمن|دوست|کراش)\s+(.+)$",cmd,re.S)
    if m:
        typ,txt=m.groups(); key={"دشمن":"enemy_replies","دوست":"friend_replies","کراش":"crash_replies"}[typ]
        arr=list(get_self_settings(uid).get(key) or []); arr.append(txt.strip()); set_self_settings(uid,key,json.dumps(arr,ensure_ascii=False)); await message.edit_text(f"✅ متن به لیست {typ} اضافه شد (مورد {len(arr)})."); return
    m=re.match(r"^حذف متن (دشمن|دوست|کراش)\s*(\d+)?$",cmd)
    if m:
        typ,idx=m.groups(); key={"دشمن":"enemy_replies","دوست":"friend_replies","کراش":"crash_replies"}[typ]; arr=list(get_self_settings(uid).get(key) or [])
        if not arr: return await message.edit_text("ℹ️ لیست متن‌ها خالی است.")
        if idx:
            i=int(idx)-1
            if not 0<=i<len(arr): return await message.edit_text("⚠️ شماره اشتباه است.")
            arr.pop(i); msg=f"✅ متن شماره {i+1} حذف شد."
        else: arr.clear(); msg="✅ تمام متن‌ها حذف شدند."
        set_self_settings(uid,key,json.dumps(arr,ensure_ascii=False)); await message.edit_text(msg); return

    # منشی
    m=re.match(r"^تنظیم متن منشی(?:\s+(.+))?$",cmd,re.S)
    if m:
        txt=(m.group(1) or "").strip(); set_self_settings(uid,"auto_reply_text",txt); await message.edit_text("✅ متن منشی تنظیم شد." if txt else "✅ متن منشی به حالت پیش‌فرض برگشت."); return

    # بلاک/سکوت/ریاکشن روی ریپلای
    m=re.match(r"^(بلاک|سکوت)(?:\s+)(روشن|خاموش)$",cmd)
    if m:
        typ,state=m.groups(); target=message.reply_to_message.from_user if message.reply_to_message else None
        if not target: return await message.edit_text("❌ روی پیام شخص ریپلای کنید.")
        if typ=="بلاک":
            BLOCKED_USERS.setdefault(uid,set())
            if state=="روشن":
                try: await client.block_user(target.id)
                except Exception: pass
                BLOCKED_USERS[uid].add(target.id)
            else:
                try: await client.unblock_user(target.id)
                except Exception: pass
                BLOCKED_USERS[uid].discard(target.id)
        else:
            MUTED_USERS.setdefault(uid,set()); k=(message.chat.id,target.id)
            if state=="روشن": MUTED_USERS[uid].add(k)
            else: MUTED_USERS[uid].discard(k)
        await message.edit_text(f"✅ {typ} {state} شد."); return
    m=re.match(r"^ریاکشن(?:\s+(.+))?$",cmd)
    if m:
        target_msg=message.reply_to_message
        arg=(m.group(1) or "").strip()
        if not target_msg:
            return await message.edit_text("❌ روی پیام شخص ریپلای کنید. مثال: ریاکشن ❤️")

        # در پی‌وی خیلی وقت‌ها کاربر روی پیام خودش ریپلای می‌کند.
        # در این حالت هدف واقعی همان طرف مقابلِ چت است، نه خود سلف.
        target=target_msg.from_user
        # اگر ریپلای روی پیام خود سلف باشد، در PV هدف همان طرف مقابل چت است.
        # در گروه، اگر پیام ریپلای‌شده متعلق به سلف باشد، نمی‌توان هدف را از آن حدس زد؛ صریحاً خطا می‌دهیم.
        if target and target.id == uid:
            if message.chat and message.chat.type == enums.ChatType.PRIVATE:
                try:
                    peer=await client.get_users(message.chat.id)
                    if peer and not peer.is_self:
                        target=peer
                except Exception:
                    target=None
            else:
                target=None
        if not target:
            return await message.edit_text("❌ کاربر هدف پیدا نشد. روی پیام همان شخص ریپلای کنید.")

        AUTO_REACTION_TARGETS.setdefault(uid,{})
        if arg.lower() in {"خاموش","off","disable"}:
            AUTO_REACTION_TARGETS[uid].pop(str(target.id),None)
            try:
                raw = get_setting(f"auto_reactions_{uid}")
                saved = json.loads(raw) if raw else {}
                if isinstance(saved, dict):
                    saved.pop(str(target.id), None)
                    set_setting(f"auto_reactions_{uid}", json.dumps(saved, ensure_ascii=False))
            except Exception:
                pass
            return await message.edit_text("✅ ریاکشن خودکار خاموش شد.")

        # اول روی پیام هدف تست می‌کنیم؛ فقط در صورت موفقیت، تنظیم را ذخیره می‌کنیم.
        reaction_ok=False
        errors=[]
        try:
            await client.send_reaction(chat_id=message.chat.id, message_id=target_msg.id, emoji=arg)
            reaction_ok=True
        except Exception as e:
            errors.append(str(e))
            try:
                await target_msg.react(emoji=arg)
                reaction_ok=True
            except Exception as e2:
                errors.append(str(e2))

        if not reaction_ok:
            return await message.edit_text("❌ ریاکشن اجرا نشد. اول مطمئن شوید همان پیامِ شخص هدف را ریپلای کرده‌اید.\n" + (errors[-1] if errors else "خطای نامشخص"))

        AUTO_REACTION_TARGETS[uid][str(target.id)]=arg
        try:
            set_setting(f"auto_reactions_{uid}", json.dumps(AUTO_REACTION_TARGETS[uid], ensure_ascii=False))
        except Exception:
            pass
        await message.edit_text(f"✅ ریاکشن {arg} برای {target.first_name or target.id} تنظیم شد.\nاز این به بعد هر پیام جدید او به‌صورت خودکار ریاکشن می‌گیرد.")
        return

    # ابزار گروه
    if low in {"تگ","tagall","تگ اعضا","تگ اعضا گروه","تگ اعضای گروه","تگ همه","تگ همه اعضا","تگ همه گروه","تگ گروه","تگ کل اعضا"}:
        await _tag_members(client,message,False); return
    if low in {"تگ ادمین ها","تگ ادمین‌ها","تگ ادمینا","تگ ادمین","تگ مدیرها","تگ مدیران","تگ مدیر ها","تگ مدیر‌ها","تگ ادمین های گروه","تگ ادمین‌های گروه","tagadmins","tag admins"}:
        await _tag_members(client,message,True); return
    if low in {"پینگ","ping"}:
        t=time.perf_counter(); m2=await message.edit_text("pong..."); ms=int((time.perf_counter()-t)*1000); await m2.edit_text(f"pong `{ms}ms`"); return
    if low in {"پین","pin"} and message.reply_to_message:
        try: await client.pin_chat_message(message.chat.id,message.reply_to_message.id,both_sides=False)
        except Exception: pass
        return await message.edit_text("📌 پیام پین شد.")
    if low in {"آن پین","unpin"}:
        try: await client.unpin_chat_message(message.chat.id)
        except Exception: pass
        return await message.edit_text("📌 پیام آن‌پین شد.")
    if low.startswith("بن") and message.reply_to_message:
        try: await client.ban_chat_member(message.chat.id,message.reply_to_message.from_user.id)
        except Exception as e: return await message.edit_text(f"❌ بن انجام نشد: {e}")
        return await message.edit_text("🔨 کاربر بن شد.")
    m=re.match(r"^اسپم\s+(.+?)\s+(\d+)$",cmd,re.S)
    if m:
        txt,c=m.groups(); c=min(int(c),50); await _safe_delete(message)
        for _ in range(c): await client.send_message(message.chat.id,txt); await asyncio.sleep(.35)
        return
    m=re.match(r"^فلود\s+(.+?)\s+(\d+)$",cmd,re.S)
    if m:
        txt,c=m.groups(); c=min(int(c),30); await _safe_delete(message); await client.send_message(message.chat.id,(txt+"\n")*c); return
    m=re.match(r"^حذف(?:\s+(\d+)|\s+همه)?$",cmd)
    if m:
        count=int(m.group(1) or (1000 if "همه" in cmd else 1)); ids=[]
        async for msg in client.get_chat_history(message.chat.id,limit=min(count*4,1000)):
            if msg.from_user and msg.from_user.id==uid: ids.append(msg.id)
            if len(ids)>=count: break
        if ids:
            try: await client.delete_messages(message.chat.id,ids)
            except Exception: pass
        return
    m=re.match(r"^تکرار\s+(\d+)$",cmd)
    if m and message.reply_to_message:
        c=min(int(m.group(1)),50); src=message.reply_to_message
        for _ in range(c): await src.copy(message.chat.id); await asyncio.sleep(.25)
        return
    if low=="دانلود" and message.reply_to_message:
        try:
            path=await message.reply_to_message.download()
            await client.send_document("me",path,caption="📥 دانلود شده")
            try: os.remove(path)
            except: pass
            await message.edit_text("✅ فایل در Saved Messages ذخیره شد.")
        except Exception as e: await message.edit_text(f"❌ دانلود نشد: {e}")
        return
    if low=="ذخیره" and message.reply_to_message:
        try: await message.reply_to_message.copy("me"); await message.edit_text("✅ در Saved Messages ذخیره شد.")
        except Exception as e: await message.edit_text(f"❌ ذخیره نشد: {e}")
        return

    # سرگرمی/انیمیشن
    fun_alias={"قلب":"heart","heart":"heart","قلب خالی":"emptyheart","emptyheart":"emptyheart","تایپ":"typing","typing":"typing","پروگرس":"progress","progress":"progress","موج":"wave","wave":"wave","ضربان":"pulse","pulse":"pulse"}
    if low.startswith("fun "): return await _run_fun(client,message,low.split(maxsplit=1)[1])
    if low in fun_alias: return await _run_fun(client,message,fun_alias[low])

    await _apply_text_style(message,uid)

async def _attach_self_runtime(client, uid):
    # فقط یک handler برای outgoing و یک handler برای incoming؛ نسخه قبلی دو بار attach می‌کرد.
    try: client.remove_handler(_self_runtime_handler, group=0)
    except Exception: pass
    client.add_handler(MessageHandler(_self_runtime_handler, filters.outgoing & filters.text), group=0)
    async def _incoming_wrapper(c, m):
        try:
            await _incoming_features(c, m, uid)
        except Exception:
            logging.exception("incoming feature handler failed uid=%s", uid)
    client.add_handler(MessageHandler(_incoming_wrapper, filters.incoming), group=1)
    old=SELF_TASKS.pop(uid,None)
    if old:
        try: old.cancel()
        except Exception: pass
    SELF_TASKS[uid]=asyncio.create_task(_clock_loop(client,uid))

async def self_panel_command_controller(client, message):
    """پنل شیشه‌ای؛ مخصوصاً برای Saved Messages با fallback مطمئن."""
    # مسیر اول: Inline Mode
    try:
        results=await client.get_inline_bot_results(BOT_USERNAME,"panel")
        if results and results.results:
            await client.send_inline_bot_result(message.chat.id, results.query_id, results.results[0].id)
            try: await message.delete()
            except Exception: pass
            return
    except Exception as e:
        logging.warning("inline panel failed: %s", e)
    # مسیر دوم: ارسال «پنل» به ربات و کپی همان پیام دارای کیبورد به Saved Messages
    try:
        sent=await client.send_message(BOT_USERNAME,"پنل")
        bot_user=await client.get_users(BOT_USERNAME)
        found=None
        for _ in range(12):
            await asyncio.sleep(0.5)
            async for m in client.get_chat_history(BOT_USERNAME, limit=30):
                if m.id <= sent.id:
                    continue
                if m.from_user and bot_user and m.from_user.id == bot_user.id and m.reply_markup:
                    found=m
                    break
            if found:
                break
        if found:
            await client.copy_message("me", BOT_USERNAME, found.id)
            if message.chat.id != "me":
                try: await message.delete()
                except Exception: pass
            return
        # مسیر سوم: اگر کیبورد در پیام بات نیامد، خود پنل را در Saved Messages به صورت مستقیم بفرستیم
        if message.chat and message.chat.type==enums.ChatType.PRIVATE and message.chat.id==message.from_user.id:
            await client.send_message("me", ax_panel_text(message.from_user.id), reply_markup=generate_ax_panel_markup(message.from_user.id), parse_mode=enums.ParseMode.HTML)
            try: await message.delete()
            except Exception: pass
            return
        await message.reply("❌ پنل از ربات دریافت نشد. Inline Mode ربات را در BotFather فعال کنید.")
    except Exception as e:
        logging.exception("Saved Messages panel fallback failed")
        try: await message.reply(f"❌ باز کردن پنل ناموفق بود: {e}")
        except Exception: pass

@bot.message_handler(func=lambda m: in_private(m) and m.text and m.text.strip().lower() in ("پنل", "/panel"))
def cmd_panel(m: types.Message):
    uid = m.from_user.id
    ensure_user(uid)
    if not is_self_active(uid):
        return bot.send_message(m.chat.id, "❌ سلف شما فعال نیست.\nابتدا سلف را فعال کنید.")
    bot.send_message(m.chat.id, ax_panel_text(uid), reply_markup=generate_ax_panel_markup(uid), parse_mode="HTML")

@bot.message_handler(
    func=lambda m: (
        in_private(m)
        and bool(m.text)
        and m.from_user is not None
        and m.from_user.id in temp_data
    )
)
def handle_code_input(m: types.Message):
    uid = m.from_user.id
    text = m.text.strip()
    st = temp_data.get(uid)
    if not st:
        return

    if time.time() - st.get("time", 0) > 300:
        state = temp_data.pop(uid, None)
        client = LOGIN_CLIENTS.pop(uid, None)
        if client:
            try:
                run_login_coro(client.disconnect())
            except Exception:
                pass
        if state and state.get("activation_paid"):
            change_balance(uid, ACTIVATE_COST)
        bot.reply_to(
            m,
            "❌ زمان کد منقضی شده است. دوباره فعال‌سازی را شروع کنید.\n"
            f"💎 {ACTIVATE_COST} الماس به موجودی شما برگشت داده شد."
        )
        return

    client = LOGIN_CLIENTS.get(uid)
    if not client:
        temp_data.pop(uid, None)
        bot.reply_to(m, "❌ نشست ورود پیدا نشد. دوباره فعال‌سازی سلف را بزنید.")
        return

    # کد را قبل از بررسی، از اعداد فارسی/عربی به انگلیسی تبدیل می‌کنیم.
    normalized_text = normalize_digits(text)

    if st["step"] == "code" and (not normalized_text.isdigit() or len(normalized_text) != 5):
        bot.reply_to(m, "❌ لطفاً کد ۵ رقمی دریافت شده از تلگرام را وارد کنید.\nمثال: 12345")
        return

    async def verify():
        try:
            if st["step"] == "password":
                await client.check_password(text)
            else:
                await client.sign_in(
                    st["phone"],
                    st["phone_code_hash"],
                    normalized_text
                )

            # هزینه 20 الماس قبلاً در زمان شروع فعال‌سازی کسر شده است.
            # اینجا فقط وضعیت سلف را فعال می‌کنیم و دوباره هزینه کم نمی‌شود.
            with db_lock:
                with sqlite3.connect(DB_PATH) as conn:
                    cur = conn.cursor()
                    cur.execute(
                        "UPDATE users SET is_self_active=1, self_active_time=? WHERE user_id=?",
                        (int(time.time()), uid)
                    )
                    conn.commit()

            # تبدیل نشست ورود به سلف زنده تا «پنل» از خود اکانت قابل دریافت باشد.
            session_string = await client.export_session_string()
            try:
                await client.disconnect()
            except Exception:
                pass
            live_client = Client(
                f"self_{uid}",
                api_id=API_ID,
                api_hash=API_HASH,
                session_string=session_string,
                no_updates=False
            )
            await live_client.start()
            await _attach_self_runtime(live_client, uid)
            old_live = SELF_CLIENTS.pop(uid, None)
            if old_live:
                try: await old_live.stop()
                except Exception: pass
            SELF_CLIENTS[uid] = live_client
            temp_data.pop(uid, None)
            LOGIN_CLIENTS[uid] = live_client
            bot.send_message(
                uid,
                "✅ ورود با موفقیت انجام شد.\n\n"
                "🔐 سلف شما فعال شد.\n"
                f"💎 هزینه فعال‌سازی: {ACTIVATE_COST} الماس\n"
                f"💎 موجودی فعلی: {get_balance(uid)} الماس\n\n"
                "برای باز کردن پنل، «پنل» را ارسال کنید."
            )

        except SessionPasswordNeeded:
            st["step"] = "password"
            st["time"] = time.time()
            bot.send_message(uid, "🔐 این حساب رمز دو مرحله‌ای دارد.\nلطفاً رمز 2FA را وارد کنید:")
        except Exception as e:
            err = str(e)
            if "PHONE_CODE_INVALID" in err:
                bot.send_message(uid, "❌ کد اشتباه است. دوباره کد را وارد کنید.")
            elif "PHONE_CODE_EXPIRED" in err:
                state = temp_data.pop(uid, None)
                LOGIN_CLIENTS.pop(uid, None)
                try:
                    await client.disconnect()
                except Exception:
                    pass
                if state and state.get("activation_paid"):
                    change_balance(uid, ACTIVATE_COST)
                    bot.send_message(uid, f"❌ کد منقضی شده است.\n💎 {ACTIVATE_COST} الماس به موجودی شما برگشت داده شد.")
                else:
                    bot.send_message(uid, "❌ کد منقضی شده است. دوباره شماره خود را ارسال کنید.")
            else:
                bot.send_message(uid, f"❌ خطا در ورود: {err}")

    run_login_coro(verify())


def run_self_message(uid, text):
    client = LOGIN_CLIENTS.get(uid)
    if not client:
        return

    async def send():
        try:
            await client.send_message(uid, text)
        except Exception:
            pass

    threading.Thread(target=lambda: asyncio.run(send()), daemon=True).start()


@bot.callback_query_handler(func=lambda c: c.data and c.data.startswith("self:"))
def cb_self(c):
    try:
        bot.answer_callback_query(c.id)
    except:
        pass
    
    user_id = c.from_user.id
    ensure_user(user_id)
    action = c.data.split(":")[1]
    
    if action == "deactivate":
        deactivate_self(user_id)
        live = SELF_CLIENTS.pop(user_id, None)
        LOGIN_CLIENTS.pop(user_id, None)
        task = SELF_TASKS.pop(user_id, None)
        if task:
            try: task.cancel()
            except Exception: pass
        if live:
            async def _restore_and_stop():
                try:
                    s = get_self_settings(user_id)
                    me = await live.get_me()
                    base = s.get("base_first_name") or me.first_name or ""
                    await live.update_profile(first_name=base, last_name=s.get("base_last_name") or me.last_name or "")
                except Exception:
                    pass
                try:
                    await live.stop()
                except Exception:
                    pass
            try: run_login_coro(_restore_and_stop())
            except Exception: pass
        bot.send_message(c.message.chat.id, "❌ سلف شما غیرفعال شد.")

# ============================================================
# ✅ بخش پنل خدمات
# ============================================================


@bot.message_handler(func=lambda m: in_private(m) and m.reply_to_message)
def handle_reply_text(m):
    user_id = m.from_user.id
    waiting = get_setting(f"reply_change_{user_id}")
    if waiting == "waiting":
        new_text = m.text
        set_self_settings(user_id, "auto_reply_text", new_text)
        set_setting(f"reply_change_{user_id}", "done")
        bot.send_message(m.chat.id, "✅ متن منشی پی‌وی تغییر یافت.")
        bot.send_message(m.chat.id, "✅ متن منشی پی‌وی تغییر یافت.")

# ----------------- PROFILE -----------------
@bot.message_handler(func=lambda m: in_private(m) and m.text and m.text.strip() == "≼ پروفایل ≽")
def cmd_profile(m: types.Message):
    user_id = m.from_user.id
    ensure_user(user_id)
    bal = get_balance(user_id)
    is_active = is_self_active(user_id)
    
    text = f"👤 پروفایل شما:\n\n"
    text += f"💎 الماس: {bal}\n"
    text += f"💰 تومان: {bal * DIAMOND_RATE:,}\n"
    text += f"🔐 وضعیت سلف: {'✅ فعال' if is_active else '❌ غیرفعال'}\n"
    text += f"👥 تعداد دعوت‌ها: {get_ref_count(user_id)}"
    
    bot.send_message(m.chat.id, text)

# ----------------- TRANSFER -----------------
@bot.message_handler(func=lambda message: message.text and message.text.startswith("انتقال"))
def transfer_diamonds(message):
    if message.chat.type not in ["group", "supergroup"]:
        bot.reply_to(message, "❌ این دستور فقط در گروه‌ها قابل استفاده است.")
        return

    parts = message.text.split()
    if len(parts) < 2:
        bot.reply_to(
            message,
            "📋 فرمت درست:\nریپلای کنید یا بنویسید:\n<b>انتقال ۲۰</b>\nیا\n<b>انتقال ۲۰ 123456789</b>",
            parse_mode="HTML"
        )
        return

    try:
        amount = int(parts[1])
        if amount <= 0:
            raise ValueError
    except ValueError:
        bot.reply_to(message, "❌ مقدار الماس باید عدد مثبت باشد.")
        return

    receiver_id = None
    if message.reply_to_message:
        receiver_id = message.reply_to_message.from_user.id
    elif len(parts) >= 3 and parts[2].isdigit():
        receiver_id = int(parts[2])

    if not receiver_id:
        bot.reply_to(message, "❌ گیرنده مشخص نیست.\nریپلای کنید یا آیدی عددی بنویسید.")
        return

    sender_id = message.from_user.id
    if sender_id == receiver_id:
        bot.reply_to(message, "❌ نمی‌توانید به خودتان الماس بفرستید.")
        return

    if is_owner(sender_id):
        tax = 0
        change_balance(receiver_id, amount)
        sender_name = message.from_user.username or message.from_user.first_name or f"مالک"
        receipt = (
            f"💎 رسید انتقال الماس\n"
            f"👤 فرستنده: <b>{sender_name} (مالک)</b>\n"
            f"👥 گیرنده: <code>{receiver_id}</code>\n"
            f"💵 مبلغ ارسال: {amount}\n"
            f"🧾 مالیات: {tax}\n"
            f"✅ مبلغ دریافتی گیرنده: {amount}"
        )
        bot.reply_to(message, receipt, parse_mode="HTML")
        try:
            bot.send_message(
                receiver_id,
                f"🎉 تبریک!\nشما <b>{amount}</b> الماس از مالک دریافت کردید.",
                parse_mode="HTML"
            )
        except:
            pass
        return

    tax = int(amount * 0.05)
    total_cost = amount + tax

    sender_balance = get_balance(sender_id)
    if sender_balance < total_cost:
        bot.reply_to(message, f"❌ موجودی کافی نیست.\nشما برای انتقال {amount} الماس، باید {total_cost} الماس داشته باشید (شامل مالیات ۵٪).")
        return

    change_balance(sender_id, -total_cost)
    change_balance(receiver_id, amount)

    sender_name = message.from_user.username or message.from_user.first_name or f"کاربر {sender_id}"

    receipt = (
        f"💎 رسید انتقال الماس\n"
        f"👤 فرستنده: <b>{sender_name}</b>\n"
        f"👥 گیرنده: <code>{receiver_id}</code>\n"
        f"💵 مبلغ ارسال: {amount}\n"
        f"🧾 مالیات از فرستنده: {tax}\n"
        f"✅ مبلغ دریافتی گیرنده: {amount}"
    )
    bot.reply_to(message, receipt, parse_mode="HTML")

    try:
        bot.send_message(
            receiver_id,
            f"🎉 تبریک!\nشما <b>{amount}</b> الماس از <b>{sender_name}</b> دریافت کردید.",
            parse_mode="HTML"
        )
    except:
        pass

# ================== BET SECTION ==================
MIN_BET = 20
BET_TAX_PERCENT = 2

BET_OPEN_TEXT = (
    "◈ ━━━━ 𝐕𝐈𝐏 ━━━━━ ◈\n"
    "شرطبندی باز شد:\n"
    "💎 الماس: {amount}\n"
    "👤 سازنده: {creator}\n"
    "◈ ━━━━ 𝐕𝐈𝐏 ━━━━━ ◈"
)
BET_RESULT_TEXT = (
    "◈━━━━━━ 𝐕𝐈𝐏 ━━━━━━ ◈\n"
    "نتیجه شرطبندی:\n"
    "🏆 برنده: {winner}\n"
    "💀 بازنده: {loser}\n"
    "💎 جایزه: {prize}\n"
    "🧾 مالیات: {tax}\n"
    "◈━━━━━━ 𝐕𝐈𝐏 ━━━━━━ ◈"
)

def bet_keyboard(bet_id: int, creator_id: int):
    kb = types.InlineKeyboardMarkup()
    kb.add(
        types.InlineKeyboardButton("لغو ❌", callback_data=f"bet:cancel:{bet_id}:{creator_id}"),
        types.InlineKeyboardButton("پیوستن ✅", callback_data=f"bet:join:{bet_id}")
    )
    return kb

@bot.message_handler(func=lambda m: m.text and m.text.startswith("شرطبندی"))
def cmd_bet(m):
    if m.chat.type not in ("group", "supergroup"):
        return bot.reply_to(m, "❌ شرطبندی فقط داخل گپ/گروه فعال است.")
    try:
        amount = int(m.text.split()[1])
    except:
        return bot.reply_to(m, f"فرمت: شرطبندی <مقدار> (حداقل {MIN_BET} 💎)")

    if amount < MIN_BET:
        return bot.reply_to(m, f"حداقل شرط {MIN_BET} 💎 است.")

    user_id = m.from_user.id
    bal = get_balance(user_id)
    if bal < amount:
        return bot.reply_to(m, "موجودی کافی ندارید.")

    change_balance(user_id, -amount)

    with db_lock:
        with sqlite3.connect(DB_PATH) as conn:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO bets(chat_id,creator_id,amount,state,created_at) VALUES(?,?,?,?,?)",
                (m.chat.id, user_id, amount, "open", int(time.time()))
            )
            bet_id = cur.lastrowid
            conn.commit()

    text = BET_OPEN_TEXT.format(amount=amount, creator=user_display_from_id(user_id))
    kb = bet_keyboard(bet_id, user_id)

    msg = bot.send_message(m.chat.id, text, reply_markup=kb, reply_to_message_id=m.message_id)

    with db_lock:
        with sqlite3.connect(DB_PATH) as conn:
            cur = conn.cursor()
            cur.execute("UPDATE bets SET message_id=? WHERE bet_id=?", (msg.message_id, bet_id))
            conn.commit()

@bot.callback_query_handler(func=lambda c: c.data and c.data.startswith("bet:"))
def cb_bet(c):
    try:
        bot.answer_callback_query(c.id)
    except:
        pass

    try:
        parts = c.data.split(":")
        action = parts[1]
        bet_id = int(parts[2])
    except Exception as e:
        try:
            bot.answer_callback_query(c.id, "❌ داده نامعتبر.")
        except:
            pass
        return

    try:
        with db_lock:
            with sqlite3.connect(DB_PATH) as conn:
                cur = conn.cursor()
                cur.execute("SELECT creator_id, amount, state, player_joined_id, message_id FROM bets WHERE bet_id=?", (bet_id,))
                row = cur.fetchone()

        if not row:
            return bot.answer_callback_query(c.id, "شرط پیدا نشد.")

        creator_id, amount, state, joined_id, message_id = row
        user_id = c.from_user.id

        if action == "cancel":
            if user_id != creator_id:
                return bot.answer_callback_query(c.id, "فقط سازنده می‌تواند لغو کند.")
            if state != "open":
                return bot.answer_callback_query(c.id, "این شرط قبلاً بسته شده است.")

            change_balance(creator_id, amount)

            with db_lock:
                with sqlite3.connect(DB_PATH) as conn:
                    cur = conn.cursor()
                    cur.execute("UPDATE bets SET state='cancelled' WHERE bet_id=?", (bet_id,))
                    conn.commit()

            try:
                bot.edit_message_text("❌ این شرط توسط سازنده لغو شد.", c.message.chat.id, message_id)
            except Exception:
                try:
                    bot.edit_message_text("❌ این شرط توسط سازنده لغو شد.", c.message.chat.id, message_id)
                except:
                    pass

            return bot.answer_callback_query(c.id, "شرط لغو شد.")

        elif action == "join":
            with db_lock:
                with sqlite3.connect(DB_PATH) as conn:
                    cur = conn.cursor()
                    cur.execute("SELECT creator_id, amount, state, player_joined_id, message_id FROM bets WHERE bet_id=?", (bet_id,))
                    row2 = cur.fetchone()
            if not row2:
                return bot.answer_callback_query(c.id, "شرط پیدا نشد.")
            creator_id, amount, state, joined_id, message_id = row2

            if state != "open":
                return bot.answer_callback_query(c.id, "این شرط بسته شده است.")
            if joined_id:
                return bot.answer_callback_query(c.id, "یک نفر قبلاً پیوسته است.")
            if user_id == creator_id:
                return bot.answer_callback_query(c.id, "نمی‌توانید روی شرط خودتان شرکت کنید.")

            bal = get_balance(user_id)
            if bal < amount:
                return bot.answer_callback_query(c.id, "موجودی کافی ندارید.")

            change_balance(user_id, -amount)

            tax = (amount * 2 * BET_TAX_PERCENT) // 100
            prize = amount * 2 - tax

            winner_id = random.choice([creator_id, user_id])
            loser_id = creator_id if winner_id == user_id else user_id

            change_balance(winner_id, prize)

            with db_lock:
                with sqlite3.connect(DB_PATH) as conn:
                    cur = conn.cursor()
                    cur.execute("UPDATE bets SET state='closed', player_joined_id=? WHERE bet_id=?", (user_id, bet_id))
                    conn.commit()

            text = BET_RESULT_TEXT.format(
                winner=user_display_from_id(winner_id),
                loser=user_display_from_id(loser_id),
                prize=prize,
                tax=tax
            )
            try:
                bot.edit_message_text(text, c.message.chat.id, message_id)
            except Exception:
                try:
                    bot.edit_message_text(text, c.message.chat.id, message_id)
                except:
                    pass

            return bot.answer_callback_query(c.id, "شرطبندی انجام شد!")

    except Exception as e:
        print("Bet Callback Error:", repr(e))
        try:
            bot.answer_callback_query(c.id, "❌ خطا رخ داد. دوباره تلاش کنید.")
        except:
            pass

# ============================================================
# ✅ پنل مدیریت (فقط برای مالک و ادمین‌ها)
# ============================================================

@bot.message_handler(commands=['help'])
def cmd_help_bot(m: types.Message):
    if not is_self_active(m.from_user.id):
        return bot.reply_to(m, "❌ ابتدا سلف را فعال کنید.")
    send_help_copy_message(m.chat.id)

@bot.message_handler(commands=['admin'])
def cmd_admin(m: types.Message):
    if not is_admin(m.from_user.id):
        return bot.reply_to(m, "❌ شما اجازه دسترسی به پنل مدیریت را ندارید.")
    bot.send_message(m.chat.id, "⚙️ <b>پنل مدیریت CIP</b>\nمدیریت کامل الماس، ادمین‌ها، جوین اجباری و آمار", reply_markup=admin_main_markup(m.from_user.id), parse_mode="HTML")

def admin_main_markup(uid):
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.row(
        types.InlineKeyboardButton("➕ افزایش الماس", callback_data="admin:give"),
        types.InlineKeyboardButton("➖ کسر الماس", callback_data="admin:remove")
    )
    kb.row(
        types.InlineKeyboardButton("📢 جوین اجباری", callback_data="admin:forced"),
        types.InlineKeyboardButton("📊 آمار ربات", callback_data="admin:stats")
    )
    kb.row(
        types.InlineKeyboardButton("➕ افزودن ادمین", callback_data="admin:add_admin"),
        types.InlineKeyboardButton("➖ حذف ادمین", callback_data="admin:del_admin")
    )
    kb.row(
        types.InlineKeyboardButton("👥 لیست ادمین‌ها", callback_data="admin:admins"),
        types.InlineKeyboardButton("📋 لیست کاربران", callback_data="admin:list_users")
    )
    kb.row(types.InlineKeyboardButton("🎲 وضعیت شرط‌بندی", callback_data="admin:bets"))
    kb.row(types.InlineKeyboardButton("❌ بستن", callback_data="admin:close"))
    return kb

def admin_forced_markup():
    channels=get_forced_channels()
    kb=types.InlineKeyboardMarkup(row_width=1)
    for ch in channels:
        kb.add(types.InlineKeyboardButton(f"🗑 حذف {ch}", callback_data=f"admin:forced_del:{ch}"))
    kb.add(types.InlineKeyboardButton("➕ افزودن کانال", callback_data="admin:forced_add"))
    kb.add(types.InlineKeyboardButton("🔄 بروزرسانی", callback_data="admin:forced"))
    kb.add(types.InlineKeyboardButton("↩️ بازگشت", callback_data="admin:back"))
    return kb

@bot.callback_query_handler(func=lambda c: c.data and c.data.startswith("joincheck"))
def cb_joincheck(c):
    ok, missing=check_forced_join_bot(c.from_user.id)
    if ok:
        bot.answer_callback_query(c.id,"✅ عضویت شما تایید شد.",show_alert=True)
        try: bot.delete_message(c.message.chat.id,c.message.message_id)
        except Exception: pass
        bot.send_message(c.message.chat.id,"✅ عضویت تایید شد. حالا /start را بزنید.")
    else:
        bot.answer_callback_query(c.id,"❌ هنوز در همه کانال‌ها عضو نشده‌اید.",show_alert=True)

@bot.callback_query_handler(func=lambda c: c.data and c.data.startswith("admin:"))
def cb_admin(c):
    uid = c.from_user.id
    if not is_admin(uid):
        return bot.answer_callback_query(c.id,"❌ دسترسی ندارید.",show_alert=True)
    parts=c.data.split(":")
    action=parts[1] if len(parts)>1 else ""

    if action in {"give","remove"}:
        ADMIN_STATE[uid] = action
        title = "افزایش" if action == "give" else "کسر"
        return bot.edit_message_text(
            f"💎 <b>{title} الماس</b>\n\n👤 روی پیام کاربر ریپلای کنید و فقط مقدار را بفرستید.\nیا به صورت <code>user_id amount</code> بفرستید.\nهمچنین می‌توانید ابتدا فقط <code>user_id</code> و سپس مقدار را بفرستید.",
            c.message.chat.id,c.message.message_id,parse_mode="HTML",reply_markup=types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("↩️ بازگشت",callback_data="admin:back"))
        )
    if action=="forced":
        channels=get_forced_channels()
        text="📢 <b>عضویت اجباری</b>\n\n" + ("\n".join(f"• {x}" for x in channels) if channels else "هیچ کانالی تنظیم نشده است.")
        return bot.edit_message_text(text,c.message.chat.id,c.message.message_id,reply_markup=admin_forced_markup(),parse_mode="HTML")
    if action=="forced_add":
        ADMIN_STATE[uid]="forced_add"
        return bot.edit_message_text("📢 یوزرنیم کانال را با @ ارسال کنید.\nمثال: @mychannel\n⚠️ ربات باید دسترسی لازم برای بررسی عضویت را داشته باشد.",c.message.chat.id,c.message.message_id)
    if action=="forced_del" and len(parts)>=3:
        ch=":".join(parts[2:])
        channels=get_forced_channels()
        if ch in channels:
            channels.remove(ch); set_forced_channels(channels)
        bot.answer_callback_query(c.id,"✅ حذف شد.")
        channels=get_forced_channels()
        text="📢 <b>عضویت اجباری</b>\n\n"+("\n".join(f"• {x}" for x in channels) if channels else "هیچ کانالی تنظیم نشده است.")
        return bot.edit_message_text(text,c.message.chat.id,c.message.message_id,reply_markup=admin_forced_markup(),parse_mode="HTML")
    if action=="add_admin":
        if not is_owner(uid):
            return bot.answer_callback_query(c.id,"⛔ فقط مالک می‌تواند ادمین اضافه کند.",show_alert=True)
        ADMIN_STATE[uid]="add_admin"
        return bot.edit_message_text("🆔 آیدی عددی ادمین جدید را ارسال کنید.",c.message.chat.id,c.message.message_id)
    if action=="del_admin":
        if not is_owner(uid):
            return bot.answer_callback_query(c.id,"⛔ فقط مالک می‌تواند ادمین حذف کند.",show_alert=True)
        ADMIN_STATE[uid]="del_admin"
        return bot.edit_message_text("🆔 آیدی عددی ادمینی که باید حذف شود را ارسال کنید.",c.message.chat.id,c.message.message_id)
    if action=="admins":
        admins=get_admin_ids()
        lines=[]
        for x in admins:
            role="👑 مالک" if x==OWNER_ID else "🛡 ادمین"
            lines.append(f"{role}: <code>{x}</code>")
        kb=types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("↩️ بازگشت",callback_data="admin:back"))
        return bot.edit_message_text("👥 <b>لیست ادمین‌ها</b>\n\n"+"\n".join(lines),c.message.chat.id,c.message.message_id,reply_markup=kb,parse_mode="HTML")
    if action=="list_users":
        with sqlite3.connect(DB_PATH) as conn:
            rows=conn.execute("SELECT user_id,diamonds FROM users ORDER BY diamonds DESC LIMIT 50").fetchall()
        text="📋 <b>کاربران</b>\n\n"+(("\n".join(f"• <code>{u}</code> — {d} 💎" for u,d in rows)) if rows else "خالی است.")
        return bot.edit_message_text(text,c.message.chat.id,c.message.message_id,reply_markup=types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("↩️ بازگشت",callback_data="admin:back")),parse_mode="HTML")
    if action=="stats":
        with sqlite3.connect(DB_PATH) as conn:
            n=conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
            total=conn.execute("SELECT COALESCE(SUM(diamonds),0) FROM users").fetchone()[0]
            active=conn.execute("SELECT COUNT(*) FROM users WHERE is_self_active=1").fetchone()[0]
            bets_open=conn.execute("SELECT COUNT(*) FROM bets WHERE state='open'").fetchone()[0]
            bets_total=conn.execute("SELECT COUNT(*) FROM bets").fetchone()[0]
        text=f"📊 <b>آمار ربات</b>\n\n👥 کاربران: {n}\n💎 مجموع الماس کاربران: {total}\n🔐 سلف‌های فعال: {active}\n🎲 شرط‌های باز: {bets_open}\n🎲 کل شرط‌ها: {bets_total}"
        return bot.edit_message_text(text,c.message.chat.id,c.message.message_id,reply_markup=types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("↩️ بازگشت",callback_data="admin:back")),parse_mode="HTML")
    if action=="bets":
        with sqlite3.connect(DB_PATH) as conn:
            open_count=conn.execute("SELECT COUNT(*) FROM bets WHERE state='open'").fetchone()[0]
            closed_count=conn.execute("SELECT COUNT(*) FROM bets WHERE state='closed'").fetchone()[0]
            cancelled=conn.execute("SELECT COUNT(*) FROM bets WHERE state='cancelled'").fetchone()[0]
        text=f"🎲 <b>وضعیت شرط‌بندی</b>\n\n🟢 باز: {open_count}\n🏁 بسته: {closed_count}\n❌ لغوشده: {cancelled}\n\nدستور گروه: <code>شرطبندی 20</code>"
        return bot.edit_message_text(text,c.message.chat.id,c.message.message_id,reply_markup=types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("↩️ بازگشت",callback_data="admin:back")),parse_mode="HTML")
    if action=="back":
        return bot.edit_message_text("⚙️ <b>پنل مدیریت CIP</b>", c.message.chat.id, c.message.message_id, reply_markup=admin_main_markup(uid), parse_mode="HTML")
    if action=="close":
        try: bot.delete_message(c.message.chat.id,c.message.message_id)
        except Exception: pass
        return
    bot.answer_callback_query(c.id)

@bot.message_handler(func=lambda m: m.from_user and m.from_user.id in ADMIN_STATE)
def admin_state_handler(m: types.Message):
    uid=m.from_user.id; state=ADMIN_STATE.get(uid)
    if not is_admin(uid): ADMIN_STATE.pop(uid,None); return
    text=(m.text or "").strip()
    if state in {"give","remove"} or (isinstance(state,dict) and state.get("action") in {"give","remove"}):
        action=state.get("action") if isinstance(state,dict) else state
        target=None; amount=None
        try:
            if m.reply_to_message and m.reply_to_message.from_user and not m.reply_to_message.from_user.is_bot:
                target=m.reply_to_message.from_user.id
                if text.isdigit(): amount=int(text)
            if target is None:
                parts=text.split()
                if len(parts)==2 and parts[0].isdigit() and parts[1].isdigit():
                    target=int(parts[0]); amount=int(parts[1])
                elif len(parts)==1 and parts[0].isdigit() and isinstance(state,dict) and state.get("target"):
                    target=int(state["target"]); amount=int(parts[0])
                elif len(parts)==1 and parts[0].isdigit():
                    ADMIN_STATE[uid]={"action":action,"target":int(parts[0])}
                    return bot.reply_to(m,"✅ آیدی دریافت شد. حالا فقط مقدار الماس را بفرستید.")
            if target is None or amount is None or amount<=0:
                return bot.reply_to(m,"❌ لطفاً روی پیام کاربر ریپلای کنید و فقط مقدار را بفرستید، یا <code>user_id amount</code> را ارسال کنید.",parse_mode="HTML")
            if action=="remove" and is_owner(target):
                ADMIN_STATE.pop(uid,None); return bot.reply_to(m,"❌ موجودی مالک قابل کسر نیست.")
            if action=="remove":
                actual=min(amount,get_balance(target)); change_balance(target,-actual); result=f"✅ {actual} الماس از <code>{target}</code> کسر شد."
            else:
                change_balance(target,amount); result=f"✅ {amount} الماس به <code>{target}</code> اضافه شد."
            ADMIN_STATE.pop(uid,None); return bot.reply_to(m,result,parse_mode="HTML")
        except Exception:
            return bot.reply_to(m,"❌ عملیات انجام نشد. روی پیام کاربر ریپلای + مقدار بفرستید، یا <code>user_id amount</code>.",parse_mode="HTML")
    elif state=="forced_add":
        if not text.startswith("@") or len(text)<2: return bot.reply_to(m,"❌ یوزرنیم باید با @ باشد.")
        channels=get_forced_channels()
        if text not in channels: channels.append(text); set_forced_channels(channels); bot.reply_to(m,f"✅ {text} به عضویت اجباری اضافه شد.")
        else: bot.reply_to(m,"ℹ️ این کانال از قبل تنظیم شده است.")
        ADMIN_STATE.pop(uid,None)
    elif state=="add_admin":
        if not is_owner(uid): ADMIN_STATE.pop(uid,None); return bot.reply_to(m,"⛔ فقط مالک می‌تواند ادمین اضافه کند.")
        if not text.isdigit(): return bot.reply_to(m,"❌ آیدی باید عددی باشد.")
        target=int(text); ids=get_admin_ids(); ids.append(target); save_admin_ids(ids); bot.reply_to(m,f"✅ ادمین <code>{target}</code> اضافه شد و ذخیره شد.",parse_mode="HTML"); ADMIN_STATE.pop(uid,None)
    elif state=="del_admin":
        if not is_owner(uid): ADMIN_STATE.pop(uid,None); return bot.reply_to(m,"⛔ فقط مالک می‌تواند ادمین حذف کند.")
        if not text.isdigit(): return bot.reply_to(m,"❌ آیدی باید عددی باشد.")
        target=int(text)
        if target==OWNER_ID: return bot.reply_to(m,"❌ مالک قابل حذف نیست.")
        ids=get_admin_ids()
        if target not in ids: ADMIN_STATE.pop(uid,None); return bot.reply_to(m,"ℹ️ این آیدی ادمین نیست.")
        ids.remove(target); save_admin_ids(ids); bot.reply_to(m,f"✅ ادمین <code>{target}</code> حذف شد.",parse_mode="HTML"); ADMIN_STATE.pop(uid,None)

@bot.message_handler(commands=['give'])
def cmd_give(m: types.Message):
    if not is_admin(m.from_user.id):
        return bot.reply_to(m, "❌ شما اجازه دسترسی به این دستور را ندارید.")
    try:
        if m.reply_to_message:
            target = m.reply_to_message.from_user.id
            amount = int(m.text.split()[1])
        else:
            parts = m.text.split()
            target = int(parts[1])
            amount = int(parts[2])
    except:
        return bot.reply_to(m, "فرمت: ریپلای + /give <amount> یا /give <user_id> <amount>")
    change_balance(target, amount)
    bot.reply_to(m, f"✅ {amount} الماس به کاربر {target} اضافه شد.")


@bot.message_handler(commands=['remove'])
def cmd_remove(m: types.Message):
    if not is_admin(m.from_user.id):
        return bot.reply_to(m, "❌ شما اجازه دسترسی به این دستور را ندارید.")
    try:
        if m.reply_to_message:
            target = m.reply_to_message.from_user.id
            amount = int(m.text.split()[1])
        else:
            parts = m.text.split()
            target = int(parts[1])
            amount = int(parts[2])
    except:
        return bot.reply_to(m, "فرمت: ریپلای + /remove <amount> یا /remove <user_id> <amount>")
    if is_owner(target):
        return bot.reply_to(m, "❌ روی مالک نمی‌توان موجودی را کم کرد (مالک بینهایت است).")
    bal = get_balance(target)
    if amount > bal:
        amount = bal
    change_balance(target, -amount)
    bot.reply_to(m, f"✅ {amount} الماس از کاربر {target} کسر شد.")


@bot.message_handler(commands=['setdiamonds'])
def cmd_setdiamonds(m: types.Message):
    if not is_admin(m.from_user.id):
        return bot.reply_to(m, "❌ شما اجازه دسترسی به این دستور را ندارید.")
    
    parts = m.text.split()
    if len(parts) != 3:
        return bot.reply_to(m, "فرمت: /setdiamonds <user_id> <amount>")
    try:
        target = int(parts[1])
        amount = int(parts[2])
    except:
        return bot.reply_to(m, "آیدی یا مقدار نامعتبر است.")
    if is_owner(target):
        return bot.reply_to(m, "❌ روی مالک نمی‌توان مقدار را تنظیم کرد (مالک بینهایت است).")
    set_balance(target, amount)
    bot.reply_to(m, f"✅ موجودی کاربر <code>{target}</code> به <b>{amount}</b> الماس تنظیم شد.", parse_mode="HTML")

# ----------------- PRIVATE MENU -----------------
@bot.message_handler(func=lambda m: in_private(m) and isinstance(m.text, str) and m.text.strip() in [
    "≼ سـلـفـ 𝐕𝐢𝐏 ≽", "≼ شـارژ مـوجـودی 💳 ≽", "≼ الماس رایگان ≽", "≼ پروفایل ≽"
])
def private_menu(m: types.Message):
    txt = m.text.strip()
    if txt == "≼ سـلـفـ 𝐕𝐢𝐏 ≽":
        cmd_self(m)
    elif txt == "≼ شـارژ مـوجـودی 💳 ≽":
        return bot.reply_to(m, "برای خرید به آیدی‌های زیر مراجعه کنید:\n👤 مالک: @AliZord_yt\n🛡 پشتیبانی: @ABOLRNRNR")
    elif txt == "≼ الماس رایگان ≽":
        count = get_ref_count(m.from_user.id)
        link = f"https://t.me/{BOT_USERNAME}?start={m.from_user.id}"
        return bot.reply_to(m, FREE_DIAMOND_TEXT.format(count=count, link=link))
    elif txt == "≼ پروفایل ≽":
        cmd_profile(m)

# ----------------- BALANCE -----------------
FREE_DIAMOND_TEXT = (
    "💎 با دعوت دوستان خود\n"
    "50 الماس دریافت کنید! فقط تا امروز..\n"
    "👥 کل دعوتی‌ها: {count}\n"
    "🔗 لینک دعوت: {link}"
)

BALANCE_TEXT = "💎 موجودی شما:\nالماس 💎: {diamonds}\nبه تومان: {toman:,}"

@bot.message_handler(func=lambda m: isinstance(m.text, str) and m.text.strip() == "موجودی")
def cmd_balance(m: types.Message):
    user_id = m.from_user.id
    if is_owner(user_id):
        text = "💎 موجودی شما:\nالماس 💎: ∞\nبه تومان: ∞"
        return bot.reply_to(m, text)
    bal = get_balance(user_id)
    text = BALANCE_TEXT.format(diamonds=bal, toman=bal * DIAMOND_RATE)
    game_photo = get_setting("game_photo")

    if game_photo:
        try:
            bot.send_photo(
                chat_id=m.chat.id,
                photo=game_photo,
                caption=text,
                reply_to_message_id=m.message_id
            )
        except:
            bot.reply_to(m, text)
    else:
        bot.reply_to(m, text)

# ----------------- MAIN -----------------
def run_bot():
    init_db()
    # ادمین‌های ذخیره‌شده را بعد از ری‌استارت بازیابی کن.
    ADMIN_IDS[:] = get_admin_ids()
    print("✅ VIP Bot v19 ران شد.")
    print("ℹ️ لاگین سلف برای هر کاربر به‌صورت جداگانه انجام می‌شود.")
    bot.infinity_polling()

if __name__ == "__main__":
    run_bot()
