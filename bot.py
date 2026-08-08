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
from datetime import datetime

import telebot
from telebot import types
from pyrogram import Client
from pyrogram.types import Message as PyroMessage

# ----------------- CONFIG -----------------
BOT_TOKEN = "8200221816:AAFVgwZ2reZzm3tDM_k0bEWHSkCTlWacxlY"
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

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")
logging.basicConfig(level=logging.INFO)
db_lock = threading.RLock()

# ----------------- یوزربات -----------------
userbot = Client(
    SESSION_NAME,
    api_id=API_ID,
    api_hash=API_HASH
)

# دیکشنری برای ذخیره اطلاعات موقت
temp_data = {}

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
            auto_reply_text TEXT DEFAULT ''
        );
        """)
        conn.commit()

# ----------------- توابع کمکی -----------------
INFINITE_OWNER_REPR = 10**18

def to_superscript(num: str) -> str:
    """تبدیل اعداد به بالانویس (فونت ۲)"""
    superscript_map = {
        '0': '⁰', '1': '¹', '2': '²', '3': '³', '4': '⁴',
        '5': '⁵', '6': '⁶', '7': '⁷', '8': '⁸', '9': '⁹'
    }
    return ''.join(superscript_map.get(c, c) for c in str(num))

def get_clock_display(user_id: int) -> str:
    """دریافت ساعت با فرمت مناسب بر اساس فونت کاربر"""
    settings = get_self_settings(user_id)
    current_time = datetime.now().strftime("%H:%M")
    
    if settings['font_style'] == 'font2':
        return to_superscript(current_time)
    else:
        return current_time

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

def is_admin(uid: int) -> bool:
    return uid in ADMIN_IDS

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
        cur.execute("SELECT text_mode, is_clock_on, font_style, action_mode, is_auto_reply_on, auto_reply_text FROM self_settings WHERE user_id=?", (uid,))
        r = cur.fetchone()
        if not r:
            return {'text_mode': 'normal', 'is_clock_on': 0, 'font_style': 'font1', 'action_mode': 'none', 'is_auto_reply_on': 0, 'auto_reply_text': ''}
        return {'text_mode': r[0], 'is_clock_on': r[1], 'font_style': r[2], 'action_mode': r[3], 'is_auto_reply_on': r[4], 'auto_reply_text': r[5]}

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
        text = get_setting("start_text") or "سلام 👋\nبه ربات VIP خوش آمدید 🌟\nاز منو زیر گزینه مورد نظر را انتخاب کنید."
        photo_id = get_setting("start_photo")
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
        markup.row("≼ سـلـفـ 𝐕𝐢𝐏 ≽", "≼ خـدمـاتـ 𝐕𝐢𝐏 ≽")
        markup.row("≼ شـارژ مـوجـودی 💳 ≽", "≼ الماس رایگان ≽")
        markup.row("≼ پروفایل ≽")
        if photo_id:
            try:
                bot.send_photo(m.chat.id, photo_id, caption=text, reply_markup=markup)
            except:
                bot.send_message(m.chat.id, text, reply_markup=markup)
        else:
            bot.send_message(m.chat.id, text, reply_markup=markup)

# ============================================================
# ✅ بخش احراز هویت با کد تلگرام
# ============================================================

@bot.message_handler(func=lambda m: in_private(m) and m.text and m.text.strip() == "≼ سـلـفـ 𝐕𝐢𝐏 ≽")
def cmd_self(m: types.Message):
    user_id = m.from_user.id
    ensure_user(user_id)
    
    if is_self_active(user_id):
        text = "✅ سلف شما فعال است!\nبرای غیر فعال کردن روی دکمه زیر کلیک کنید."
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("❌ غیرفعال کردن سلف", callback_data="self:deactivate"))
        bot.send_message(m.chat.id, text, reply_markup=markup)
    else:
        text = f"🔐 برای فعال سازی سلف، شماره تلفن خود را ارسال کنید.\nهزینه فعال‌سازی: {ACTIVATE_COST} الماس\nهر ساعت {HOURLY_COST} الماس از موجودی شما کم می‌شود."
        
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
        btn = types.KeyboardButton("📱 ارسال شماره تلفن", request_contact=True)
        markup.add(btn)
        
        bot.send_message(m.chat.id, text, reply_markup=markup)


@bot.message_handler(content_types=['contact'])
def handle_contact(m: types.Message):
    user_id = m.from_user.id
    ensure_user(user_id)
    
    if m.contact:
        phone_number = m.contact.phone_number
        
        if m.contact.user_id != user_id:
            bot.send_message(m.chat.id, "❌ لطفاً شماره تلفن خودتان را ارسال کنید.")
            return
        
        # اگر کاربر مالک است، مستقیم فعال کن (بدون کد)
        if is_owner(user_id):
            success, msg = activate_self(user_id)
            if success:
                bot.send_message(m.chat.id, f"✅ {msg}\nشما مالک هستید و سلف شما فعال شد!")
            else:
                bot.send_message(m.chat.id, f"❌ {msg}")
            return
        
        # برای کاربران عادی، کد ارسال کن
        bot.send_message(m.chat.id, f"✅ شماره شما دریافت شد!\nشماره: {phone_number}\n\n📤 در حال ارسال درخواست کد به تلگرام...")
        
        async def send_code_request():
            try:
                sent_code = await userbot.send_code(phone_number)
                
                temp_data[user_id] = {
                    'phone': phone_number,
                    'phone_code_hash': sent_code.phone_code_hash,
                    'time': time.time()
                }
                
                markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
                markup.row("≼ سـلـفـ 𝐕𝐢𝐏 ≽", "≼ خـدمـاتـ 𝐕𝐢𝐏 ≽")
                markup.row("≼ شـارژ مـوجـودی 💳 ≽", "≼ الماس رایگان ≽")
                markup.row("≼ پروفایل ≽")
                
                bot.send_message(
                    user_id,
                    f"✅ کد تایید به تلگرام شما ارسال شد.\n📝 لطفاً کد ۵ رقمی را که از تلگرام دریافت کردید، وارد کنید:",
                    reply_markup=markup
                )
                
            except Exception as e:
                error_msg = str(e)
                if "FLOOD_WAIT" in error_msg:
                    wait_time = error_msg.split("FLOOD_WAIT_")[1].split("_")[0] if "_" in error_msg else "چند"
                    bot.send_message(user_id, f"❌ تلگرام محدودیت ایجاد کرده. لطفاً {wait_time} ثانیه صبر کنید و دوباره تلاش کنید.")
                elif "PHONE_NUMBER_BANNED" in error_msg:
                    bot.send_message(user_id, f"❌ این شماره توسط تلگرام مسدود شده است.")
                else:
                    bot.send_message(user_id, f"❌ خطا در ارسال کد: {error_msg}")
        
        asyncio.run_coroutine_threadsafe(send_code_request(), userbot.loop)


# این تابع همه پیام‌های متنی رو چک میکنه (برای دریافت کد)
@bot.message_handler(func=lambda m: in_private(m) and m.text and m.text not in [
    "≼ سـلـفـ 𝐕𝐢𝐏 ≽", "≼ خـدمـاتـ 𝐕𝐢𝐏 ≽", "≼ شـارژ مـوجـودی 💳 ≽", 
    "≼ الماس رایگان ≽", "≼ پروفایل ≽"
])
def handle_code_input(m: types.Message):
    user_id = m.from_user.id
    text = m.text.strip()
    
    # چک کردن اینکه کاربر منتظر کد هست یا نه
    if user_id in temp_data:
        # بررسی اینکه متن ارسالی عدد ۵ رقمی هست یا نه
        if not text.isdigit() or len(text) != 5:
            bot.reply_to(m, "❌ لطفاً کد ۵ رقمی دریافت شده از تلگرام را وارد کنید.\nمثال: 12345")
            return
        
        stored_data = temp_data[user_id]
        
        # چک کردن زمان (۵ دقیقه اعتبار)
        if time.time() - stored_data['time'] > 300:
            del temp_data[user_id]
            bot.reply_to(m, "❌ زمان کد منقضی شده است. دوباره شماره خود را ارسال کنید.")
            return
        
        # تایید کد با یوزربات
        async def verify_code():
            try:
                await userbot.sign_in(
                    phone_number=stored_data['phone'],
                    code=text,
                    phone_code_hash=stored_data['phone_code_hash']
                )
                
                # کد درست است
                del temp_data[user_id]
                
                # فعال‌سازی سلف
                success, msg = activate_self(user_id)
                if success:
                    bot.reply_to(m, f"✅ {msg}\nشما می‌توانید از پنل خدمات استفاده کنید.")
                else:
                    bot.reply_to(m, f"❌ {msg}\nموجودی فعلی: {get_balance(user_id)} الماس")
                
            except Exception as e:
                error_msg = str(e)
                if "PHONE_CODE_INVALID" in error_msg:
                    bot.reply_to(m, "❌ کد اشتباه است. دوباره تلاش کنید.")
                elif "PHONE_CODE_EXPIRED" in error_msg:
                    del temp_data[user_id]
                    bot.reply_to(m, "❌ کد منقضی شده است. دوباره شماره خود را ارسال کنید.")
                else:
                    bot.reply_to(m, f"❌ خطا: {error_msg}")
        
        asyncio.run_coroutine_threadsafe(verify_code(), userbot.loop)
        return


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
        bot.send_message(c.message.chat.id, "❌ سلف شما غیرفعال شد.")

# ============================================================
# ✅ بخش پنل خدمات
# ============================================================

@bot.message_handler(func=lambda m: in_private(m) and m.text and m.text.strip() == "≼ خـدمـاتـ 𝐕𝐢𝐏 ≽")
def cmd_services(m: types.Message):
    user_id = m.from_user.id
    ensure_user(user_id)
    
    if not is_self_active(user_id):
        text = "❌ برای استفاده از خدمات VIP ابتدا سلف خود را فعال کنید.\nاز دکمه ≼ سـلـفـ 𝐕𝐢𝐏 ≽ استفاده کنید."
        bot.send_message(m.chat.id, text)
        return
    
    text = "🎯 پنل خدمات VIP\n\nاز دکمه‌های زیر برای تنظیمات استفاده کنید:"
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("📝 حالت متن", callback_data="service:text_mode"),
        types.InlineKeyboardButton("⏰ ساعت", callback_data="service:clock"),
        types.InlineKeyboardButton("🔤 فونت", callback_data="service:font"),
        types.InlineKeyboardButton("🎬 اکشن", callback_data="service:action"),
        types.InlineKeyboardButton("🤖 منشی پی‌وی", callback_data="service:auto_reply"),
        types.InlineKeyboardButton("📊 وضعیت سلف", callback_data="service:status")
    )
    markup.add(types.InlineKeyboardButton("❌ بستن پنل", callback_data="service:close"))
    bot.send_message(m.chat.id, text, reply_markup=markup)

@bot.callback_query_handler(func=lambda c: c.data and c.data.startswith("service:"))
def cb_service(c):
    try:
        bot.answer_callback_query(c.id)
    except:
        pass
    
    user_id = c.from_user.id
    ensure_user(user_id)
    action = c.data.split(":")[1]
    
    if action == "close":
        try:
            bot.delete_message(c.message.chat.id, c.message.message_id)
        except:
            bot.send_message(c.message.chat.id, "پنل بسته شد.")
        return
    
    if action == "status":
        if is_self_active(user_id):
            text = "✅ سلف شما فعال است"
            settings = get_self_settings(user_id)
            text += f"\n📝 حالت متن: {settings['text_mode']}"
            text += f"\n⏰ ساعت: {'روشن' if settings['is_clock_on'] else 'خاموش'}"
            text += f"\n🔤 فونت: {settings['font_style']}"
            text += f"\n🎬 اکشن: {settings['action_mode']}"
            text += f"\n🤖 منشی پی‌وی: {'روشن' if settings['is_auto_reply_on'] else 'خاموش'}"
        else:
            text = "❌ سلف شما فعال نیست"
        bot.send_message(c.message.chat.id, text)
        return
    
    if action == "text_mode":
        settings = get_self_settings(user_id)
        current = settings['text_mode']
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton(f"{'✅ ' if current == 'normal' else ''}عادی", callback_data="text:set:normal"),
            types.InlineKeyboardButton(f"{'✅ ' if current == 'bold' else ''}پررنگ", callback_data="text:set:bold"),
            types.InlineKeyboardButton(f"{'✅ ' if current == 'quote' else ''}نقل قول", callback_data="text:set:quote"),
            types.InlineKeyboardButton(f"{'✅ ' if current == 'spoiler' else ''}اسپویلر", callback_data="text:set:spoiler")
        )
        markup.add(types.InlineKeyboardButton("🔙 بازگشت", callback_data="service:text_back"))
        bot.edit_message_text("📝 انتخاب حالت متن:", c.message.chat.id, c.message.message_id, reply_markup=markup)
        return
    
    if action == "clock":
        settings = get_self_settings(user_id)
        is_on = settings['is_clock_on']
        current_time = get_clock_display(user_id)
        markup = types.InlineKeyboardMarkup(row_width=1)
        markup.add(
            types.InlineKeyboardButton(f"{'🟢 روشن' if is_on else '🔴 خاموش'}", callback_data=f"clock:toggle:{1 if not is_on else 0}"),
            types.InlineKeyboardButton("🔙 بازگشت", callback_data="service:clock_back")
        )
        bot.edit_message_text(f"⏰ تنظیمات ساعت:\nوضعیت: {'روشن' if is_on else 'خاموش'}\nنمایش فعلی: {current_time}", c.message.chat.id, c.message.message_id, reply_markup=markup)
        return
    
    if action == "font":
        settings = get_self_settings(user_id)
        current = settings['font_style']
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton(f"{'✅ ' if current == 'font1' else ''}فونت ۱ (۰۱۲۳)", callback_data="font:set:font1"),
            types.InlineKeyboardButton(f"{'✅ ' if current == 'font2' else ''}فونت ۲ (⁰¹²³)", callback_data="font:set:font2")
        )
        markup.add(types.InlineKeyboardButton("🔙 بازگشت", callback_data="service:font_back"))
        bot.edit_message_text("🔤 انتخاب فونت:", c.message.chat.id, c.message.message_id, reply_markup=markup)
        return
    
    if action == "action":
        settings = get_self_settings(user_id)
        current = settings['action_mode']
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton(f"{'✅ ' if current == 'none' else ''}خاموش", callback_data="action:set:none"),
            types.InlineKeyboardButton(f"{'✅ ' if current == 'voice' else ''}ویس", callback_data="action:set:voice"),
            types.InlineKeyboardButton(f"{'✅ ' if current == 'game' else ''}بازی", callback_data="action:set:game"),
            types.InlineKeyboardButton(f"{'✅ ' if current == 'sticker' else ''}استیکر", callback_data="action:set:sticker")
        )
        markup.add(types.InlineKeyboardButton("🔙 بازگشت", callback_data="service:action_back"))
        bot.edit_message_text("🎬 انتخاب اکشن:", c.message.chat.id, c.message.message_id, reply_markup=markup)
        return
    
    if action == "auto_reply":
        settings = get_self_settings(user_id)
        is_on = settings['is_auto_reply_on']
        current_text = settings['auto_reply_text'] or "⚡️سلام وقت بخیر دوست گرامی ⭐️\n\n🧖‍♂بنده آفلاین هستم آنلاین شدم زود جوابتو میدم 😶‍🌫"
        markup = types.InlineKeyboardMarkup(row_width=1)
        markup.add(
            types.InlineKeyboardButton(f"{'🟢 روشن' if is_on else '🔴 خاموش'}", callback_data=f"reply:toggle:{1 if not is_on else 0}"),
            types.InlineKeyboardButton("📝 تغییر متن", callback_data="reply:change_text"),
            types.InlineKeyboardButton("🔙 بازگشت", callback_data="service:reply_back")
        )
        bot.edit_message_text(f"🤖 منشی پی‌وی:\nوضعیت: {'روشن' if is_on else 'خاموش'}\n\nمتن فعلی:\n{current_text}", c.message.chat.id, c.message.message_id, reply_markup=markup)
        return
    
    if action in ["text_back", "clock_back", "font_back", "action_back", "reply_back"]:
        cmd_services(c.message)

# ----------------- TEXT MODE -----------------
@bot.callback_query_handler(func=lambda c: c.data and c.data.startswith("text:"))
def cb_text(c):
    try:
        bot.answer_callback_query(c.id)
    except:
        pass
    user_id = c.from_user.id
    action = c.data.split(":")[1]
    if action == "set":
        mode = c.data.split(":")[2]
        set_self_settings(user_id, "text_mode", mode)
        asyncio.run_coroutine_threadsafe(
            userbot.send_message(user_id, f"حالت متن به {mode} تغییر یافت"),
            userbot.loop
        )
        bot.send_message(c.message.chat.id, f"✅ حالت متن به {mode} تغییر یافت.")
        cmd_services(c.message)
    elif action == "back":
        cmd_services(c.message)

# ----------------- CLOCK -----------------
@bot.callback_query_handler(func=lambda c: c.data and c.data.startswith("clock:"))
def cb_clock(c):
    try:
        bot.answer_callback_query(c.id)
    except:
        pass
    user_id = c.from_user.id
    action = c.data.split(":")[1]
    if action == "toggle":
        value = int(c.data.split(":")[2])
        set_self_settings(user_id, "is_clock_on", value)
        asyncio.run_coroutine_threadsafe(
            userbot.send_message(user_id, f"ساعت {'روشن' if value else 'خاموش'} شد"),
            userbot.loop
        )
        bot.send_message(c.message.chat.id, f"✅ ساعت {'روشن' if value else 'خاموش'} شد.")
        cmd_services(c.message)
    elif action == "back":
        cmd_services(c.message)

# ----------------- FONT -----------------
@bot.callback_query_handler(func=lambda c: c.data and c.data.startswith("font:"))
def cb_font(c):
    try:
        bot.answer_callback_query(c.id)
    except:
        pass
    user_id = c.from_user.id
    action = c.data.split(":")[1]
    if action == "set":
        font = c.data.split(":")[2]
        set_self_settings(user_id, "font_style", font)
        asyncio.run_coroutine_threadsafe(
            userbot.send_message(user_id, f"فونت به {font} تغییر یافت"),
            userbot.loop
        )
        bot.send_message(c.message.chat.id, f"✅ فونت به {font} تغییر یافت.")
        cmd_services(c.message)
    elif action == "back":
        cmd_services(c.message)

# ----------------- ACTION -----------------
@bot.callback_query_handler(func=lambda c: c.data and c.data.startswith("action:"))
def cb_action(c):
    try:
        bot.answer_callback_query(c.id)
    except:
        pass
    user_id = c.from_user.id
    action = c.data.split(":")[1]
    if action == "set":
        mode = c.data.split(":")[2]
        set_self_settings(user_id, "action_mode", mode)
        asyncio.run_coroutine_threadsafe(
            userbot.send_message(user_id, f"اکشن به {mode} تغییر یافت"),
            userbot.loop
        )
        bot.send_message(c.message.chat.id, f"✅ اکشن به {mode} تغییر یافت.")
        cmd_services(c.message)
    elif action == "back":
        cmd_services(c.message)

# ----------------- AUTO REPLY -----------------
@bot.callback_query_handler(func=lambda c: c.data and c.data.startswith("reply:"))
def cb_reply(c):
    try:
        bot.answer_callback_query(c.id)
    except:
        pass
    user_id = c.from_user.id
    action = c.data.split(":")[1]
    if action == "toggle":
        value = int(c.data.split(":")[2])
        set_self_settings(user_id, "is_auto_reply_on", value)
        asyncio.run_coroutine_threadsafe(
            userbot.send_message(user_id, f"منشی پی‌وی {'روشن' if value else 'خاموش'} شد"),
            userbot.loop
        )
        bot.send_message(c.message.chat.id, f"✅ منشی پی‌وی {'روشن' if value else 'خاموش'} شد.")
        cmd_services(c.message)
    elif action == "change_text":
        bot.send_message(c.message.chat.id, "📝 متن جدید را به همراه ریپلای به این پیام ارسال کنید.\nبرای تغییر متن، روی این پیام ریپلای بزنید و متن جدید را بنویسید.")
        with db_lock:
            set_setting(f"reply_change_{user_id}", "waiting")
    elif action == "back":
        cmd_services(c.message)

# ----------------- دریافت متن جدید منشی -----------------
@bot.message_handler(func=lambda m: in_private(m) and m.reply_to_message)
def handle_reply_text(m):
    user_id = m.from_user.id
    waiting = get_setting(f"reply_change_{user_id}")
    if waiting == "waiting":
        new_text = m.text
        set_self_settings(user_id, "auto_reply_text", new_text)
        set_setting(f"reply_change_{user_id}", "done")
        bot.send_message(m.chat.id, "✅ متن منشی پی‌وی تغییر یافت.")
        cmd_services(m)

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

@bot.message_handler(commands=['admin'])
def cmd_admin(m: types.Message):
    if not is_admin(m.from_user.id):
        return bot.reply_to(m, "❌ شما اجازه دسترسی به پنل مدیریت را ندارید.")
    
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("📋 لیست کاربران", callback_data="admin:list_users"))
    kb.add(types.InlineKeyboardButton("⚙️ تنظیم الماس (راهنما)", callback_data="admin:set_help"))
    kb.add(types.InlineKeyboardButton("📊 آمار ربات", callback_data="admin:stats"))
    bot.reply_to(m, "⚙️ پنل مدیریت:", reply_markup=kb)


@bot.callback_query_handler(func=lambda c: c.data and c.data.startswith("admin:"))
def cb_admin(c):
    try:
        bot.answer_callback_query(c.id)
    except:
        pass
    
    if not is_admin(c.from_user.id):
        return bot.answer_callback_query(c.id, "❌ شما اجازه دسترسی به پنل مدیریت را ندارید.")
    
    parts = c.data.split(":")
    action = parts[1]

    if action == "list_users":
        with sqlite3.connect(DB_PATH) as conn:
            cur = conn.cursor()
            cur.execute("SELECT user_id, diamonds FROM users ORDER BY diamonds DESC LIMIT 20")
            rows = cur.fetchall()
        if not rows:
            return bot.send_message(c.from_user.id, "لیستی یافت نشد.")
        text_lines = ["📋 لیست ۲۰ کاربر برتر (برحسب الماس):\n"]
        for uid, d in rows:
            if is_owner(uid):
                d_display = "∞"
            else:
                d_display = str(d)
            text_lines.append(f"• <code>{uid}</code> — {d_display} 💎")
        bot.send_message(c.from_user.id, "\n".join(text_lines), parse_mode="HTML")
        return

    if action == "set_help":
        help_text = (
            "🛠️ دستور تنظیم الماس:\n\n"
            "/setdiamonds <user_id> <amount>\n\n"
            "مثال: /setdiamonds 123456789 500\n\n"
            "توضیح: این دستور مقدار الماس کاربر را به عدد وارد شده تنظیم می‌کند. "
            "توجه: روی مالک تأثیری ندارد (مالک بینهایت است)."
        )
        bot.send_message(c.from_user.id, help_text)
        return

    if action == "stats":
        with sqlite3.connect(DB_PATH) as conn:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM users")
            users_count = cur.fetchone()[0]
            cur.execute("SELECT SUM(diamonds) FROM users")
            total_diamonds = cur.fetchone()[0] or 0
        text = f"📊 آمار ربات:\n• کل کاربران ثبت‌شده: {users_count}\n• مجموع الماس‌های ثبت‌شده در DB: {total_diamonds}"
        bot.send_message(c.from_user.id, text)
        return


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
    "≼ سـلـفـ 𝐕𝐢𝐏 ≽", "≼ خـدمـاتـ 𝐕𝐢𝐏 ≽", "≼ شـارژ مـوجـودی 💳 ≽", "≼ الماس رایگان ≽", "≼ پروفایل ≽"
])
def private_menu(m: types.Message):
    txt = m.text.strip()
    if txt == "≼ سـلـفـ 𝐕𝐢𝐏 ≽":
        cmd_self(m)
    elif txt == "≼ خـدمـاتـ 𝐕𝐢𝐏 ≽":
        cmd_services(m)
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

# ----------------- یوزربات -----------------
async def userbot_worker():
    @userbot.on_message()
    async def handle_user_messages(client, message: PyroMessage):
        pass

    await userbot.start()
    print("✅ یوزربات متصل شد!")
    await userbot.idle()

# ----------------- MAIN -----------------
def run_bot():
    init_db()
    
    def start_userbot():
        asyncio.run(userbot_worker())
    
    userbot_thread = threading.Thread(target=start_userbot)
    userbot_thread.daemon = True
    userbot_thread.start()
    
    print("✅ VIP Bot v19 ران شد (نسخه ترکیبی ربات + یوزربات).")
    bot.infinity_polling()

if __name__ == "__main__":
    run_bot()
