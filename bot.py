# -*- coding: utf-8 -*-
import sqlite3
import threading
import logging
import time
import random
from datetime import datetime

import telebot
from telebot import types

# ----------------- CONFIG -----------------
BOT_TOKEN = "8200221816:AAFVgwZ2reZzm3tDM_k0bEWHSkCTlWacxlY"
OWNER_ID = 5552127428
ADMIN_IDS = [5552127428]

DB_PATH = "vip_bet.db"
ACTIVATE_COST = 20
HOURLY_COST = 2
MIN_BET = 20

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")
logging.basicConfig(level=logging.INFO)
db_lock = threading.RLock()

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
            phone TEXT
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
# ربات
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
        markup.add(types.InlineKeyboardButton("🔴 غیرفعال کردن", callback_data="self:off"))
        bot.send_message(m.chat.id, "✅ سلف شما فعال است!", reply_markup=markup)
    else:
        text = f"🔐 برای فعال‌سازی سلف به ادمین پیام دهید.\n\n💰 هزینه فعال‌سازی: {ACTIVATE_COST} الماس\n⏱ هزینه ساعتی: {HOURLY_COST} الماس\n💎 موجودی شما: {get_balance(uid)}\n\n👤 ادمین: @AliZord_yt"
        bot.send_message(m.chat.id, text)

# ----------------- غیرفعال کردن سلف -----------------

@bot.callback_query_handler(func=lambda c: c.data.startswith("self:"))
def cb_self(c):
    try: bot.answer_callback_query(c.id)
    except: pass
    uid = c.from_user.id
    if c.data == "self:off":
        deactivate_self(uid)
        bot.edit_message_text("❌ سلف شما غیرفعال شد", c.message.chat.id, c.message.message_id)

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
        active = is_self_active(uid)
        bal = get_balance(uid)
        text = f"📊 **وضعیت شما**\n\n💎 الماس: {bal}\n🔐 سلف: {'✅ فعال' if active else '❌ غیرفعال'}"
        bot.send_message(c.message.chat.id, text, parse_mode="HTML")
        return
    
    if action == "text":
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton("🟢 عادی", callback_data="text:normal"),
            types.InlineKeyboardButton("🔵 پررنگ", callback_data="text:bold"),
            types.InlineKeyboardButton("🟡 نقل قول", callback_data="text:quote"),
            types.InlineKeyboardButton("🟣 اسپویلر", callback_data="text:spoiler")
        )
        markup.add(types.InlineKeyboardButton("🔙 بازگشت", callback_data="svc:back"))
        bot.edit_message_text("📝 **حالت متن**", c.message.chat.id, c.message.message_id, reply_markup=markup, parse_mode="HTML")
        return
    
    if action == "clock":
        markup = types.InlineKeyboardMarkup()
        markup.add(
            types.InlineKeyboardButton("🟢 روشن", callback_data="clock:on"),
            types.InlineKeyboardButton("🔴 خاموش", callback_data="clock:off")
        )
        markup.add(types.InlineKeyboardButton("🔙 بازگشت", callback_data="svc:back"))
        bot.edit_message_text("⏰ **ساعت**", c.message.chat.id, c.message.message_id, reply_markup=markup, parse_mode="HTML")
        return
    
    if action == "font":
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton("🔵 فونت ۱", callback_data="font:font1"),
            types.InlineKeyboardButton("🟣 فونت ۲", callback_data="font:font2")
        )
        markup.add(types.InlineKeyboardButton("🔙 بازگشت", callback_data="svc:back"))
        bot.edit_message_text("🔤 **فونت**", c.message.chat.id, c.message.message_id, reply_markup=markup, parse_mode="HTML")
        return
    
    if action == "back":
        cmd_services(c.message)

# ----------------- کالبک‌های تنظیمات -----------------

@bot.callback_query_handler(func=lambda c: c.data.startswith("text:"))
def cb_text(c):
    try: bot.answer_callback_query(c.id)
    except: pass
    mode = c.data.split(":")[1]
    bot.edit_message_text(f"✅ حالت متن به {mode} تغییر کرد", c.message.chat.id, c.message.message_id)
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
        types.InlineKeyboardButton("❌ لغو", callback_data=f"bet:cancel:{bet_id}"),
        types.InlineKeyboardButton("✅ پیوستن", callback_data=f"bet:join:{bet_id}")
    )
    
    msg = bot.send_message(
        m.chat.id,
        f"🎯 **شرط‌بندی جدید**\n\n💎 مبلغ: {amount}\n👤 سازنده: {m.from_user.first_name}",
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
            bot.answer_callback_query(c.id, "❌ فقط سازنده!", alert=True)
            return
        if state != "open":
            bot.answer_callback_query(c.id, "❌ بسته شده!", alert=True)
            return
        
        change_balance(creator_id, amount)
        with db_lock, sqlite3.connect(DB_PATH) as conn:
            cur = conn.cursor()
            cur.execute("UPDATE bets SET state='cancelled' WHERE bet_id=?", (bet_id,))
            conn.commit()
        bot.edit_message_text("❌ شرط لغو شد.", chat_id, message_id)
        bot.answer_callback_query(c.id, "✅ لغو شد!")
        return
    
    if action == "join":
        if state != "open":
            bot.answer_callback_query(c.id, "❌ بسته شده!", alert=True)
            return
        if player_joined_id != 0:
            bot.answer_callback_query(c.id, "❌ قبلاً پیوسته!", alert=True)
            return
        if uid == creator_id:
            bot.answer_callback_query(c.id, "❌ خودت!", alert=True)
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
        bot.answer_callback_query(c.id, "✅ انجام شد!")

# ============================================================
# ✅ انتقال الماس
# ============================================================

@bot.message_handler(func=lambda m: m.text and m.text.startswith("انتقال"))
def transfer_diamonds(m):
    if m.chat.type not in ["private", "group", "supergroup"]:
        return
    
    parts = m.text.split()
    
    if len(parts) < 2:
        bot.reply_to(m, "❌ فرمت: انتقال <مقدار> [آیدی/یوزرنیم]\nمثال: انتقال 20 @username\nیا با ریپلای: انتقال 20")
        return
    
    try:
        amount = int(parts[1])
        if amount <= 0:
            raise ValueError
    except:
        bot.reply_to(m, "❌ مقدار باید عدد مثبت باشد!")
        return
    
    receiver_id = None
    
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
    
    ensure_user(receiver_id)
    
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
    
    try:
        sender_name = m.from_user.first_name or "کاربر"
        bot.send_message(receiver_id, f"🎁 شما {amount} الماس از {sender_name} دریافت کردید!")
    except:
        pass

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
        types.InlineKeyboardButton("📋 لیست کاربران", callback_data="admin:list"),
        types.InlineKeyboardButton("📊 آمار ربات", callback_data="admin:stats"),
        types.InlineKeyboardButton("➕ افزودن الماس", callback_data="admin:give"),
        types.InlineKeyboardButton("➖ کم کردن الماس", callback_data="admin:remove"),
        types.InlineKeyboardButton("💰 تنظیم الماس", callback_data="admin:set")
    )
    markup.add(types.InlineKeyboardButton("🔴 بستن پنل", callback_data="admin:close"))
    
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

# ============================================================
# اجرا
# ============================================================

def run():
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
    run()
