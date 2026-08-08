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
ADMIN_IDS = [5552127428]  # لیست ادمین‌ها (مالک + ادمین‌های دیگه)

API_ID = 37386944
API_HASH = "d64069023db75d11ae5982f653069a98"

DB_PATH = "vip_bet.db"
ACTIVATE_COST = 20
HOURLY_COST = 2

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")
logging.basicConfig(level=logging.INFO)
db_lock = threading.RLock()

# ----------------- یوزربات (Telethon) -----------------
user_clients = {}
auth_sessions = {}

# ----------------- دیتابیس -----------------
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
            username TEXT,
            first_name TEXT
        );
        """)
        conn.commit()

# ----------------- توابع -----------------
INFINITE = 10**18

def ensure_user(uid):
    with db_lock, sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("INSERT OR IGNORE INTO users(user_id,diamonds,created_at,is_self_active,self_active_time) VALUES(?,?,?,?,?)", 
                   (uid, 0, int(time.time()), 0, 0))
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

def set_balance(uid, amount):
    if is_owner(uid):
        return
    ensure_user(uid)
    with db_lock, sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("UPDATE users SET diamonds=? WHERE user_id=?", (amount, uid))
        conn.commit()

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
                with db_lock, sqlite3.connect(DB_PATH) as conn:
                    cur2 = conn.cursor()
                    cur2.execute("UPDATE users SET is_self_active=0, self_active_time=0 WHERE user_id=?", (uid,))
                    conn.commit()
                return False
        return True

def activate_self(uid):
    ensure_user(uid)
    bal = get_balance(uid)
    if bal < ACTIVATE_COST and not is_owner(uid):
        return False, "موجودی کافی نیست"
    if not is_owner(uid):
        change_balance(uid, -ACTIVATE_COST)
    with db_lock, sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("UPDATE users SET is_self_active=1, self_active_time=? WHERE user_id=?", (int(time.time()), uid))
        conn.commit()
    return True, "✅ سلف شما فعال شد"

def deactivate_self(uid):
    with db_lock, sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("UPDATE users SET is_self_active=0, self_active_time=0 WHERE user_id=?", (uid,))
        conn.commit()

def set_user_phone(uid, phone):
    with db_lock, sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("UPDATE users SET phone=? WHERE user_id=?", (phone, uid))
        conn.commit()

def get_user_info(uid):
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("SELECT user_id, diamonds, is_self_active, phone FROM users WHERE user_id=?", (uid,))
        return cur.fetchone()

def in_private(m):
    return m.chat.type == "private"

# ----------------- START -----------------
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
    bot.send_message(m.chat.id, "سلام 👋 به ربات VIP خوش آمدید", reply_markup=markup)

# ----------------- سلف -----------------
@bot.message_handler(func=lambda m: in_private(m) and m.text == "≼ سـلـفـ 𝐕𝐢𝐏 ≽")
def cmd_self(m):
    uid = m.from_user.id
    ensure_user(uid)
    
    if is_self_active(uid):
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("❌ غیرفعال کردن", callback_data="self:off"))
        bot.send_message(m.chat.id, "✅ سلف شما فعال است!", reply_markup=markup)
    else:
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
        btn = types.KeyboardButton("📱 ارسال شماره", request_contact=True)
        markup.add(btn)
        bot.send_message(m.chat.id, f"🔐 شماره خود را ارسال کنید.\nهزینه: {ACTIVATE_COST} الماس\nهزینه ساعتی: {HOURLY_COST} الماس", reply_markup=markup)

# ----------------- دریافت شماره و ارسال کد با Telethon -----------------
@bot.message_handler(content_types=['contact'])
def handle_contact(m):
    uid = m.from_user.id
    ensure_user(uid)
    
    if not m.contact or m.contact.user_id != uid:
        bot.reply_to(m, "❌ شماره خودت رو بفرست!")
        return
    
    phone = m.contact.phone_number
    set_user_phone(uid, phone)
    
    # اگر مالک است، مستقیم فعال کن
    if is_owner(uid):
        success, msg = activate_self(uid)
        bot.reply_to(m, f"✅ {msg} (مالک)")
        return
    
    bot.reply_to(m, f"✅ شماره شما ثبت شد!\n📱 {phone}\n\n📤 در حال ارسال کد به تلگرام...")
    
    # ایجاد کلاینت جدید برای کاربر
    client = TelegramClient(f'user_{uid}', API_ID, API_HASH)
    
    async def send_code():
        try:
            await client.connect()
            await client.send_code_request(phone)
            
            auth_sessions[uid] = {
                'client': client,
                'phone': phone,
                'step': 'waiting_code',
                'start_time': time.time()
            }
            
            bot.send_message(uid, "📨 کد تایید به تلگرام شما ارسال شد.\nلطفاً کد ۵ رقمی را وارد کنید:")
            
        except FloodWaitError as e:
            bot.send_message(uid, f"❌ لطفاً {e.seconds} ثانیه صبر کنید و دوباره تلاش کنید.")
        except Exception as e:
            bot.send_message(uid, f"❌ خطا: {str(e)}")
    
    asyncio.run_coroutine_threadsafe(send_code(), asyncio.get_event_loop())

# ----------------- دریافت کد و تایید با Telethon -----------------
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
    
    # بررسی زمان (۵ دقیقه)
    if time.time() - auth.get('start_time', 0) > 300:
        del auth_sessions[uid]
        bot.reply_to(m, "❌ زمان کد منقضی شد! دوباره شماره بفرست.")
        return
    
    client = auth['client']
    phone = auth['phone']
    
    async def verify_code():
        try:
            await client.sign_in(phone, text)
            
            # ذخیره کلاینت برای کاربر
            user_clients[uid] = client
            
            # فعال‌سازی سلف
            success, msg = activate_self(uid)
            bot.reply_to(m, f"✅ {msg}")
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

# ----------------- دریافت رمز دو مرحله‌ای -----------------
@bot.message_handler(func=lambda m: in_private(m) and m.text and m.text not in ["≼ سـلـفـ 𝐕𝐢𝐏 ≽", "≼ خـدمـاتـ 𝐕𝐢𝐏 ≽", "≼ شـارژ مـوجـودی 💳 ≽", "≼ الماس رایگان ≽", "≼ پروفایل ≽", "⚙️ پنل مدیریت"])
def handle_password(m):
    uid = m.from_user.id
    text = m.text.strip()
    
    if uid not in auth_sessions:
        return
    
    auth = auth_sessions[uid]
    
    if auth.get('step') != 'waiting_password':
        return
    
    client = auth['client']
    
    async def verify_password():
        try:
            await client.sign_in(password=text)
            
            user_clients[uid] = client
            
            success, msg = activate_self(uid)
            bot.reply_to(m, f"✅ {msg}")
            del auth_sessions[uid]
            
        except Exception as e:
            bot.reply_to(m, f"❌ رمز اشتباه است! {str(e)}")
    
    asyncio.run_coroutine_threadsafe(verify_password(), asyncio.get_event_loop())

# ----------------- پنل خدمات -----------------
@bot.message_handler(func=lambda m: in_private(m) and m.text == "≼ خـدمـاتـ 𝐕𝐢𝐏 ≽")
def cmd_services(m):
    uid = m.from_user.id
    if not is_self_active(uid):
        bot.reply_to(m, "❌ اول سلف رو فعال کن!")
        return
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("📝 حالت متن", callback_data="svc:text"),
        types.InlineKeyboardButton("⏰ ساعت", callback_data="svc:clock"),
        types.InlineKeyboardButton("🔤 فونت", callback_data="svc:font"),
        types.InlineKeyboardButton("🎬 اکشن", callback_data="svc:action"),
        types.InlineKeyboardButton("🤖 منشی", callback_data="svc:reply"),
        types.InlineKeyboardButton("📊 وضعیت", callback_data="svc:status")
    )
    markup.add(types.InlineKeyboardButton("❌ بستن", callback_data="svc:close"))
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
            cur.execute("SELECT is_self_active FROM users WHERE user_id=?", (uid,))
            r = cur.fetchone()
        active = r[0] if r else 0
        text = f"✅ سلف: {'فعال' if active else 'غیرفعال'}"
        bot.send_message(c.message.chat.id, text)
        return
    
    if action == "text":
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton("عادی", callback_data="text:normal"),
            types.InlineKeyboardButton("پررنگ", callback_data="text:bold"),
            types.InlineKeyboardButton("نقل قول", callback_data="text:quote"),
            types.InlineKeyboardButton("اسپویلر", callback_data="text:spoiler")
        )
        markup.add(types.InlineKeyboardButton("🔙 بازگشت", callback_data="svc:back"))
        bot.edit_message_text("📝 حالت متن:", c.message.chat.id, c.message.message_id, reply_markup=markup)
        return
    
    if action == "clock":
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🟢 روشن", callback_data="clock:on"))
        markup.add(types.InlineKeyboardButton("🔴 خاموش", callback_data="clock:off"))
        markup.add(types.InlineKeyboardButton("🔙 بازگشت", callback_data="svc:back"))
        bot.edit_message_text("⏰ ساعت:", c.message.chat.id, c.message.message_id, reply_markup=markup)
        return
    
    if action == "font":
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton("فونت ۱", callback_data="font:font1"),
            types.InlineKeyboardButton("فونت ۲", callback_data="font:font2")
        )
        markup.add(types.InlineKeyboardButton("🔙 بازگشت", callback_data="svc:back"))
        bot.edit_message_text("🔤 فونت:", c.message.chat.id, c.message.message_id, reply_markup=markup)
        return
    
    if action == "action":
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton("خاموش", callback_data="action:none"),
            types.InlineKeyboardButton("ویس", callback_data="action:voice"),
            types.InlineKeyboardButton("بازی", callback_data="action:game"),
            types.InlineKeyboardButton("استیکر", callback_data="action:sticker")
        )
        markup.add(types.InlineKeyboardButton("🔙 بازگشت", callback_data="svc:back"))
        bot.edit_message_text("🎬 اکشن:", c.message.chat.id, c.message.message_id, reply_markup=markup)
        return
    
    if action == "reply":
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🟢 روشن", callback_data="reply:on"))
        markup.add(types.InlineKeyboardButton("🔴 خاموش", callback_data="reply:off"))
        markup.add(types.InlineKeyboardButton("🔙 بازگشت", callback_data="svc:back"))
        bot.edit_message_text("🤖 منشی:", c.message.chat.id, c.message.message_id, reply_markup=markup)
        return
    
    if action == "back":
        cmd_services(c.message)

# ----------------- کالبک‌های ساده -----------------
@bot.callback_query_handler(func=lambda c: c.data.startswith("text:"))
def cb_text(c):
    try: bot.answer_callback_query(c.id)
    except: pass
    bot.edit_message_text(f"✅ حالت متن به {c.data.split(':')[1]} تغییر کرد", c.message.chat.id, c.message.message_id)
    cmd_services(c.message)

@bot.callback_query_handler(func=lambda c: c.data.startswith("clock:"))
def cb_clock(c):
    try: bot.answer_callback_query(c.id)
    except: pass
    val = c.data.split(":")[1]
    bot.edit_message_text(f"✅ ساعت {val} شد", c.message.chat.id, c.message.message_id)
    cmd_services(c.message)

@bot.callback_query_handler(func=lambda c: c.data.startswith("font:"))
def cb_font(c):
    try: bot.answer_callback_query(c.id)
    except: pass
    font = c.data.split(":")[1]
    bot.edit_message_text(f"✅ فونت {font} انتخاب شد", c.message.chat.id, c.message.message_id)
    cmd_services(c.message)

@bot.callback_query_handler(func=lambda c: c.data.startswith("action:"))
def cb_action(c):
    try: bot.answer_callback_query(c.id)
    except: pass
    action = c.data.split(":")[1]
    bot.edit_message_text(f"✅ اکشن {action} انتخاب شد", c.message.chat.id, c.message.message_id)
    cmd_services(c.message)

@bot.callback_query_handler(func=lambda c: c.data.startswith("reply:"))
def cb_reply(c):
    try: bot.answer_callback_query(c.id)
    except: pass
    val = c.data.split(":")[1]
    bot.edit_message_text(f"✅ منشی {val} شد", c.message.chat.id, c.message.message_id)
    cmd_services(c.message)

@bot.callback_query_handler(func=lambda c: c.data.startswith("self:"))
def cb_self(c):
    try: bot.answer_callback_query(c.id)
    except: pass
    uid = c.from_user.id
    if c.data == "self:off":
        deactivate_self(uid)
        bot.edit_message_text("❌ سلف غیرفعال شد", c.message.chat.id, c.message.message_id)

# ----------------- منوها -----------------
@bot.message_handler(func=lambda m: in_private(m) and m.text == "≼ پروفایل ≽")
def profile(m):
    uid = m.from_user.id
    bal = get_balance(uid)
    active = is_self_active(uid)
    
    if is_owner(uid):
        text = f"👤 پروفایل:\n💎 الماس: ∞\n💰 تومان: ∞\n🔐 سلف: {'✅ فعال' if active else '❌ غیرفعال'}\n👑 نقش: مالک"
    elif is_admin(uid):
        text = f"👤 پروفایل:\n💎 الماس: {bal}\n💰 تومان: {bal*40:,}\n🔐 سلف: {'✅ فعال' if active else '❌ غیرفعال'}\n👑 نقش: ادمین"
    else:
        text = f"👤 پروفایل:\n💎 الماس: {bal}\n💰 تومان: {bal*40:,}\n🔐 سلف: {'✅ فعال' if active else '❌ غیرفعال'}"
    
    bot.reply_to(m, text)

@bot.message_handler(func=lambda m: in_private(m) and m.text == "≼ شـارژ مـوجـودی 💳 ≽")
def charge(m):
    bot.reply_to(m, "💳 برای خرید به @ABOLRNRNR پیام بدید")

@bot.message_handler(func=lambda m: in_private(m) and m.text == "≼ الماس رایگان ≽")
def free(m):
    uid = m.from_user.id
    link = f"https://t.me/self_made_iran_bot?start={uid}"
    bot.reply_to(m, f"💎 با دعوت دوستان الماس بگیر!\n🔗 {link}")

# ============================================================
# ✅ پنل مدیریت شیشه‌ای (فقط مالک و ادمین‌ها)
# ============================================================

@bot.message_handler(func=lambda m: in_private(m) and m.text == "⚙️ پنل مدیریت")
def admin_panel(m):
    if not is_admin(m.from_user.id):
        bot.reply_to(m, "❌ شما دسترسی به پنل مدیریت ندارید!")
        return
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("📋 لیست کاربران", callback_data="admin:list"),
        types.InlineKeyboardButton("📊 آمار ربات", callback_data="admin:stats"),
        types.InlineKeyboardButton("➕ افزودن الماس", callback_data="admin:give"),
        types.InlineKeyboardButton("➖ کم کردن الماس", callback_data="admin:remove"),
        types.InlineKeyboardButton("💰 تنظیم الماس", callback_data="admin:set"),
        types.InlineKeyboardButton("📢 ارسال همگانی", callback_data="admin:broadcast")
    )
    markup.add(types.InlineKeyboardButton("❌ بستن پنل", callback_data="admin:close"))
    
    bot.reply_to(m, "⚙️ **پنل مدیریت**\n\nاز دکمه‌های زیر استفاده کنید:", reply_markup=markup, parse_mode="HTML")


@bot.callback_query_handler(func=lambda c: c.data.startswith("admin:"))
def cb_admin(c):
    if not is_admin(c.from_user.id):
        try: bot.answer_callback_query(c.id, "❌ شما دسترسی ندارید!", alert=True)
        except: pass
        return
    
    try: bot.answer_callback_query(c.id)
    except: pass
    
    action = c.data.split(":")[1]
    
    # بستن پنل
    if action == "close":
        try: bot.delete_message(c.message.chat.id, c.message.message_id)
        except: pass
        return
    
    # لیست کاربران
    if action == "list":
        with sqlite3.connect(DB_PATH) as conn:
            cur = conn.cursor()
            cur.execute("SELECT user_id, diamonds, is_self_active FROM users ORDER BY diamonds DESC LIMIT 30")
            rows = cur.fetchall()
        
        if not rows:
            text = "📋 کاربری یافت نشد"
        else:
            text = "📋 **لیست کاربران (۳۰ نفر برتر):**\n\n"
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
    
    # آمار ربات
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
    
    # افزودن الماس
    if action == "give":
        bot.send_message(c.from_user.id, "📝 **افزودن الماس**\n\nفرمت:\n`/give <user_id> <amount>`\n\nمثال:\n`/give 123456789 100`", parse_mode="HTML")
        return
    
    # کم کردن الماس
    if action == "remove":
        bot.send_message(c.from_user.id, "📝 **کم کردن الماس**\n\nفرمت:\n`/remove <user_id> <amount>`\n\nمثال:\n`/remove 123456789 50`", parse_mode="HTML")
        return
    
    # تنظیم الماس
    if action == "set":
        bot.send_message(c.from_user.id, "📝 **تنظیم الماس**\n\nفرمت:\n`/setdiamonds <user_id> <amount>`\n\nمثال:\n`/setdiamonds 123456789 500`", parse_mode="HTML")
        return
    
    # ارسال همگانی
    if action == "broadcast":
        bot.send_message(c.from_user.id, "📢 **ارسال همگانی**\n\nلطفاً پیام خود را به همراه این دستور ارسال کنید:\n`/broadcast <پیام>`\n\nمثال:\n`/broadcast سلام به همه!`", parse_mode="HTML")
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
        
        try:
            bot.send_message(target, f"🎁 {amount} الماس به حسابت اضافه شد!")
        except:
            pass
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
        
        set_balance(target, amount)
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


# ----------------- اجرا -----------------
def run():
    init_db()
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("INSERT OR IGNORE INTO users(user_id,diamonds,created_at,is_self_active,self_active_time) VALUES(?,?,?,?,?)", 
                   (OWNER_ID, 0, int(time.time()), 0, 0))
        conn.commit()
    
    # راه‌اندازی event loop برای asyncio
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    print("✅ ربات روشن شد!")
    bot.infinity_polling()

if __name__ == "__main__":
    run()
