# -*- coding: utf-8 -*-
import sqlite3
import threading
import html
import logging
import time
import random
import os
from datetime import datetime
import asyncio

import telebot
from telebot import types
from pyrogram import Client

# ----------------- CONFIG -----------------
BOT_TOKEN = "8200221816:AAFVgwZ2reZzm3tDM_k0bEWHSkCTlWacxlY"
OWNER_ID = 5552127428
ADMIN_IDS = [OWNER_ID]

API_ID = 37386944
API_HASH = "d64069023db75d11ae5982f653069a98"

DB_PATH = "vip_bet.db"
DIAMOND_RATE = 40
REF_BONUS = 40
BOT_USERNAME = "self_made_iran_bot"
ACTIVATE_COST = 20
HOURLY_COST = 2

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")
logging.basicConfig(level=logging.INFO)
db_lock = threading.RLock()

# ----------------- یوزربات -----------------
userbot = Client("userbot_session", api_id=API_ID, api_hash=API_HASH)

# دیکشنری کدها
temp_codes = {}

# ----------------- دیتابیس -----------------
def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            diamonds INTEGER DEFAULT 0,
            created_at INTEGER,
            is_self_active INTEGER DEFAULT 0,
            self_active_time INTEGER DEFAULT 0
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

# ----------------- توابع -----------------
INFINITE = 10**18

def ensure_user(uid):
    with db_lock, sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("INSERT OR IGNORE INTO users(user_id,diamonds,created_at,is_self_active,self_active_time) VALUES(?,?,?,?,?)", 
                   (uid, 0, int(time.time()), 0, 0))
        cur.execute("INSERT OR IGNORE INTO self_settings(user_id,text_mode,is_clock_on,font_style,action_mode,is_auto_reply_on,auto_reply_text) VALUES(?,?,?,?,?,?,?)",
                   (uid, 'normal', 0, 'font1', 'none', 0, ''))
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

def get_self_settings(uid):
    ensure_user(uid)
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("SELECT text_mode, is_clock_on, font_style, action_mode, is_auto_reply_on, auto_reply_text FROM self_settings WHERE user_id=?", (uid,))
        r = cur.fetchone()
        if not r:
            return {'text_mode': 'normal', 'is_clock_on': 0, 'font_style': 'font1', 'action_mode': 'none', 'is_auto_reply_on': 0, 'auto_reply_text': ''}
        return {'text_mode': r[0], 'is_clock_on': r[1], 'font_style': r[2], 'action_mode': r[3], 'is_auto_reply_on': r[4], 'auto_reply_text': r[5]}

def set_self_settings(uid, key, value):
    with db_lock, sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute(f"UPDATE self_settings SET {key}=? WHERE user_id=?", (value, uid))
        conn.commit()

def in_private(m):
    return m.chat.type == "private"

def get_clock_display(uid):
    settings = get_self_settings(uid)
    current = datetime.now().strftime("%H:%M")
    if settings['font_style'] == 'font2':
        sup = {'0':'⁰','1':'¹','2':'²','3':'³','4':'⁴','5':'⁵','6':'⁶','7':'⁷','8':'⁸','9':'⁹'}
        return ''.join(sup.get(c,c) for c in current)
    return current

# ----------------- START -----------------
@bot.message_handler(commands=['start'])
def start(m):
    user_id = m.from_user.id
    ensure_user(user_id)
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row("≼ سـلـفـ 𝐕𝐢𝐏 ≽", "≼ خـدمـاتـ 𝐕𝐢𝐏 ≽")
    markup.row("≼ شـارژ مـوجـودی 💳 ≽", "≼ الماس رایگان ≽")
    markup.row("≼ پروفایل ≽")
    if is_owner(user_id):
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
    
    # تولید کد تصادفی
    code = str(random.randint(10000, 99999))
    temp_codes[uid] = {'code': code, 'phone': phone, 'time': time.time()}
    
    # ارسال کد با یوزربات به کاربر
    async def send_code():
        try:
            await userbot.send_message(uid, f"🔐 کد تایید شما:\n<code>{code}</code>\n\nاین کد ۵ دقیقه اعتبار دارد.", parse_mode="HTML")
            bot.send_message(uid, "✅ کد به تلگرام شما ارسال شد.\nلطفاً کد ۵ رقمی را وارد کنید:")
        except Exception as e:
            bot.send_message(uid, f"❌ خطا: یوزربات متصل نیست!\nلطفاً با ادمین تماس بگیرید.\nخطا: {e}")
    
    asyncio.run_coroutine_threadsafe(send_code(), userbot.loop)

# ----------------- دریافت کد -----------------
@bot.message_handler(func=lambda m: in_private(m) and m.text and m.text not in ["≼ سـلـفـ 𝐕𝐢𝐏 ≽", "≼ خـدمـاتـ 𝐕𝐢𝐏 ≽", "≼ شـارژ مـوجـودی 💳 ≽", "≼ الماس رایگان ≽", "≼ پروفایل ≽", "⚙️ پنل مدیریت"])
def handle_code(m):
    uid = m.from_user.id
    text = m.text.strip()
    
    if uid not in temp_codes:
        return
    
    if not text.isdigit() or len(text) != 5:
        bot.reply_to(m, "❌ کد ۵ رقمی وارد کن!")
        return
    
    data = temp_codes[uid]
    if time.time() - data['time'] > 300:
        del temp_codes[uid]
        bot.reply_to(m, "❌ کد منقضی شد! دوباره شماره بفرست.")
        return
    
    if text != data['code']:
        bot.reply_to(m, "❌ کد اشتباه است! دوباره تلاش کن.")
        return
    
    del temp_codes[uid]
    
    # تایید کد با یوزربات
    async def verify_and_activate():
        try:
            # لاگین با کد
            await userbot.sign_in(
                phone_number=data['phone'],
                code=text,
                phone_code_hash=data.get('phone_code_hash', '')
            )
            # فعال‌سازی سلف
            success, msg = activate_self(uid)
            bot.reply_to(m, f"✅ {msg}")
        except Exception as e:
            bot.reply_to(m, f"❌ خطا در تایید کد: {e}")
    
    asyncio.run_coroutine_threadsafe(verify_and_activate(), userbot.loop)

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
        settings = get_self_settings(uid)
        text = f"✅ وضعیت سلف:\nمتن: {settings['text_mode']}\nساعت: {'روشن' if settings['is_clock_on'] else 'خاموش'}\nفونت: {settings['font_style']}\nاکشن: {settings['action_mode']}\nمنشی: {'روشن' if settings['is_auto_reply_on'] else 'خاموش'}"
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
        settings = get_self_settings(uid)
        is_on = settings['is_clock_on']
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton(f"{'🟢 روشن' if is_on else '🔴 خاموش'}", callback_data=f"clock:{1 if not is_on else 0}"))
        markup.add(types.InlineKeyboardButton("🔙 بازگشت", callback_data="svc:back"))
        bot.edit_message_text(f"⏰ ساعت: {'روشن' if is_on else 'خاموش'}", c.message.chat.id, c.message.message_id, reply_markup=markup)
        return
    
    if action == "font":
        settings = get_self_settings(uid)
        current = settings['font_style']
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton(f"{'✅' if current=='font1' else ''} فونت ۱", callback_data="font:font1"),
            types.InlineKeyboardButton(f"{'✅' if current=='font2' else ''} فونت ۲", callback_data="font:font2")
        )
        markup.add(types.InlineKeyboardButton("🔙 بازگشت", callback_data="svc:back"))
        bot.edit_message_text("🔤 فونت:", c.message.chat.id, c.message.message_id, reply_markup=markup)
        return
    
    if action == "action":
        settings = get_self_settings(uid)
        current = settings['action_mode']
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton(f"{'✅' if current=='none' else ''} خاموش", callback_data="action:none"),
            types.InlineKeyboardButton(f"{'✅' if current=='voice' else ''} ویس", callback_data="action:voice"),
            types.InlineKeyboardButton(f"{'✅' if current=='game' else ''} بازی", callback_data="action:game"),
            types.InlineKeyboardButton(f"{'✅' if current=='sticker' else ''} استیکر", callback_data="action:sticker")
        )
        markup.add(types.InlineKeyboardButton("🔙 بازگشت", callback_data="svc:back"))
        bot.edit_message_text("🎬 اکشن:", c.message.chat.id, c.message.message_id, reply_markup=markup)
        return
    
    if action == "reply":
        settings = get_self_settings(uid)
        is_on = settings['is_auto_reply_on']
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton(f"{'🟢 روشن' if is_on else '🔴 خاموش'}", callback_data=f"reply:{1 if not is_on else 0}"))
        markup.add(types.InlineKeyboardButton("📝 تغییر متن", callback_data="reply:text"))
        markup.add(types.InlineKeyboardButton("🔙 بازگشت", callback_data="svc:back"))
        bot.edit_message_text(f"🤖 منشی: {'روشن' if is_on else 'خاموش'}", c.message.chat.id, c.message.message_id, reply_markup=markup)
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
    set_self_settings(uid, "text_mode", mode)
    bot.edit_message_text(f"✅ حالت متن به {mode} تغییر کرد", c.message.chat.id, c.message.message_id)
    cmd_services(c.message)

@bot.callback_query_handler(func=lambda c: c.data.startswith("clock:"))
def cb_clock(c):
    try: bot.answer_callback_query(c.id)
    except: pass
    uid = c.from_user.id
    val = int(c.data.split(":")[1])
    set_self_settings(uid, "is_clock_on", val)
    bot.edit_message_text(f"✅ ساعت {'روشن' if val else 'خاموش'} شد", c.message.chat.id, c.message.message_id)
    cmd_services(c.message)

@bot.callback_query_handler(func=lambda c: c.data.startswith("font:"))
def cb_font(c):
    try: bot.answer_callback_query(c.id)
    except: pass
    uid = c.from_user.id
    font = c.data.split(":")[1]
    set_self_settings(uid, "font_style", font)
    bot.edit_message_text(f"✅ فونت به {font} تغییر کرد", c.message.chat.id, c.message.message_id)
    cmd_services(c.message)

@bot.callback_query_handler(func=lambda c: c.data.startswith("action:"))
def cb_action(c):
    try: bot.answer_callback_query(c.id)
    except: pass
    uid = c.from_user.id
    mode = c.data.split(":")[1]
    set_self_settings(uid, "action_mode", mode)
    bot.edit_message_text(f"✅ اکشن به {mode} تغییر کرد", c.message.chat.id, c.message.message_id)
    cmd_services(c.message)

@bot.callback_query_handler(func=lambda c: c.data.startswith("reply:"))
def cb_reply(c):
    try: bot.answer_callback_query(c.id)
    except: pass
    uid = c.from_user.id
    parts = c.data.split(":")
    if parts[1] == "text":
        bot.send_message(c.message.chat.id, "📝 متن جدید رو ریپلای کن و بفرست")
        return
    val = int(parts[1])
    set_self_settings(uid, "is_auto_reply_on", val)
    bot.edit_message_text(f"✅ منشی {'روشن' if val else 'خاموش'} شد", c.message.chat.id, c.message.message_id)
    cmd_services(c.message)

@bot.callback_query_handler(func=lambda c: c.data.startswith("self:"))
def cb_self(c):
    try: bot.answer_callback_query(c.id)
    except: pass
    uid = c.from_user.id
    if c.data == "self:off":
        deactivate_self(uid)
        bot.edit_message_text("❌ سلف غیرفعال شد", c.message.chat.id, c.message.message_id)

# ----------------- منوهای دیگه -----------------
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
    link = f"https://t.me/{BOT_USERNAME}?start={uid}"
    bot.reply_to(m, f"💎 با دعوت دوستان الماس بگیر!\n🔗 {link}")

# ----------------- پنل ادمین -----------------
@bot.message_handler(func=lambda m: in_private(m) and m.text == "⚙️ پنل مدیریت")
def admin_panel(m):
    if not is_owner(m.from_user.id):
        return
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("📋 لیست کاربران", callback_data="admin:list"),
        types.InlineKeyboardButton("📊 آمار", callback_data="admin:stats"),
        types.InlineKeyboardButton("💰 تنظیم الماس", callback_data="admin:set"),
        types.InlineKeyboardButton("➕ /give", callback_data="admin:give"),
        types.InlineKeyboardButton("➖ /remove", callback_data="admin:remove")
    )
    markup.add(types.InlineKeyboardButton("❌ بستن", callback_data="admin:close"))
    bot.reply_to(m, "⚙️ پنل مدیریت:", reply_markup=markup)

@bot.callback_query_handler(func=lambda c: c.data.startswith("admin:"))
def cb_admin(c):
    if not is_owner(c.from_user.id):
        try: bot.answer_callback_query(c.id, "❌ فقط مالک!")
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
            cur.execute("SELECT user_id, diamonds FROM users ORDER BY diamonds DESC LIMIT 20")
            rows = cur.fetchall()
        if not rows:
            text = "📋 کاربری یافت نشد"
        else:
            text = "📋 لیست کاربران:\n"
            for uid, d in rows:
                if uid == OWNER_ID:
                    text += f"• {uid} — ∞ 💎 (مالک)\n"
                else:
                    text += f"• {uid} — {d} 💎\n"
        bot.send_message(c.from_user.id, text)
        return
    
    if action == "stats":
        with sqlite3.connect(DB_PATH) as conn:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM users")
            count = cur.fetchone()[0]
            cur.execute("SELECT SUM(diamonds) FROM users")
            total = cur.fetchone()[0] or 0
        text = f"📊 آمار:\n👥 کاربران: {count}\n💰 مجموع الماس: {total}"
        bot.send_message(c.from_user.id, text)
        return
    
    if action == "set":
        bot.send_message(c.from_user.id, "📝 برای تنظیم الماس:\n/setdiamonds <user_id> <amount>")
        return
    
    if action == "give":
        bot.send_message(c.from_user.id, "📝 برای اضافه کردن:\n/give <user_id> <amount>")
        return
    
    if action == "remove":
        bot.send_message(c.from_user.id, "📝 برای کم کردن:\n/remove <user_id> <amount>")
        return

# ----------------- دستورات ادمین -----------------
@bot.message_handler(commands=['setdiamonds'])
def set_diamonds(m):
    if not is_owner(m.from_user.id):
        return
    try:
        parts = m.text.split()
        target = int(parts[1])
        amount = int(parts[2])
        if is_owner(target):
            bot.reply_to(m, "❌ مالک بینهایت است!")
            return
        set_balance(target, amount)
        bot.reply_to(m, f"✅ الماس {target} به {amount} تنظیم شد")
    except:
        bot.reply_to(m, "فرمت: /setdiamonds <user_id> <amount>")

@bot.message_handler(commands=['give'])
def give(m):
    if not is_owner(m.from_user.id):
        return
    try:
        parts = m.text.split()
        target = int(parts[1])
        amount = int(parts[2])
        if is_owner(target):
            bot.reply_to(m, "❌ مالک بینهایت است!")
            return
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
        if is_owner(target):
            bot.reply_to(m, "❌ مالک بینهایت است!")
            return
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
