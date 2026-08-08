# -*- coding: utf-8 -*-
"""
VIP Bot v18 - نسخه ویرایش‌شده با پنل مدیریت و الماس بینهایت برای مالک
"""
import sqlite3
import threading
import html
import logging
import time
import random

import telebot
from telebot import types

# ----------------- CONFIG -----------------
BOT_TOKEN = "8200221816:AAFVgwZ2reZzm3tDM_k0bEWHSkCTlWacxlY"
OWNER_ID = 5552127428
DEVELOPER_ID = 5552127428
ADMIN_IDS = [OWNER_ID, DEVELOPER_ID]

DB_PATH = "vip_bet.db"
DIAMOND_RATE = 40
REF_BONUS = 40
BOT_USERNAME = "self_made_iran_bot"

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")
logging.basicConfig(level=logging.INFO)
# اگر لازم باشد RLock برای برخی عملیات پیچیده‌تر را می‌توان فعال کرد
db_lock = threading.RLock()

# ----------------- DATABASE -----------------
def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.executescript("""
        PRAGMA foreign_keys = ON;
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            diamonds INTEGER DEFAULT 0,
            created_at INTEGER
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
        """)
        conn.commit()

# ----------------- DB HELPERS -----------------
INFINITE_OWNER_REPR = 10**18  # نمایشی از بینهایت برای مالک

def ensure_user(uid: int):
    with db_lock:
        with sqlite3.connect(DB_PATH) as conn:
            cur = conn.cursor()
            cur.execute("INSERT OR IGNORE INTO users(user_id,diamonds,created_at) VALUES(?,?,?)", (uid, 0, int(time.time())))
            cur.execute("INSERT OR IGNORE INTO referrals(user_id,count) VALUES(?,0)", (uid,))
            conn.commit()

def is_owner(uid: int) -> bool:
    return uid == OWNER_ID

def is_admin(uid: int) -> bool:
    return uid in ADMIN_IDS

def get_balance(uid: int) -> int:
    # مالک بینهایت است (نمایش و رفتار بینهایت)
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
        # روی مالک کاری انجام نمی‌دهیم؛ مالک بینهایت است
        return
    ensure_user(uid)
    with db_lock:
        with sqlite3.connect(DB_PATH) as conn:
            cur = conn.cursor()
            cur.execute("UPDATE users SET diamonds=? WHERE user_id=?", (int(amount), uid))
            conn.commit()

def change_balance(uid: int, delta: int):
    # هیچگاه از مالک کم نکنیم — مالک بینهایت است
    if is_owner(uid):
        # اگر خواستید می‌توانید لاگ ذخیره کنید؛ در این نسخه صرفاً نادیده می‌گیریم.
        return
    ensure_user(uid)
    with db_lock:
        with sqlite3.connect(DB_PATH) as conn:
            cur = conn.cursor()
            cur.execute("UPDATE users SET diamonds = diamonds + ? WHERE user_id=?", (delta, uid))
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

# ----------------- TEXT TEMPLATES -----------------
BALANCE_TEXT = "💎 موجودی شما:\nالماس 💎: {diamonds}\nبه تومان: {toman:,}"
FREE_DIAMOND_TEXT = (
    "💎 با دعوت دوستان خود\n"
    "50 الماس دریافت کنید! فقط تا امروز..\n"
    "👥 کل دعوتی‌ها: {count}\n"
    "🔗 لینک دعوت: {link}"
)

# ----------------- HELPERS -----------------
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
        # اگر گرفتن اطلاعات کاربر شکست خورد، آیدی را نشان می‌دهیم
        if is_owner(uid):
            return "مالک (∞)"
        return f"<a href='tg://user?id={uid}'>کاربر</a>"

def in_private(m): return m.chat.type == "private"
def in_group(m): return m.chat.type in ("group","supergroup")

# ----------------- START & REFERRAL -----------------
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
        if photo_id:
            try:
                bot.send_photo(m.chat.id, photo_id, caption=text, reply_markup=markup)
            except:
                bot.send_message(m.chat.id, text, reply_markup=markup)
        else:
            bot.send_message(m.chat.id, text, reply_markup=markup)

# ----------------- ADMIN GIVE / REMOVE -----------------
@bot.message_handler(commands=['give'])
def cmd_give(m: types.Message):
    if not is_admin(m.from_user.id):
        return bot.reply_to(m, "اجازه ندارید.")
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
    # اگر فرستنده مالک است و به خاطر بینهایت بودن مالک، کسی خواست از مالک کم شود
    # این دستور فقط الماس را به کاربر اضافه می‌کند
    change_balance(target, amount)
    bot.reply_to(m, f"✅ {amount} الماس به کاربر {target} اضافه شد.")

@bot.message_handler(commands=['remove'])
def cmd_remove(m: types.Message):
    if not is_admin(m.from_user.id):
        return bot.reply_to(m, "اجازه ندارید.")
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

# ----------------- TRANSFER DIAMONDS (GROUP ONLY) -----------------
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

    # شناسایی گیرنده
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

    # اگر فرستنده مالک باشد: اجازه انتقال بدون کسر موجودی و بدون مالیات (بینهایت)
    if is_owner(sender_id):
        tax = 0
        # فقط دریافت‌کننده را شارژ می‌کنیم (مالک از موجودی کم نمی‌شود)
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

    # محاسبه مالیات و بررسی موجودی فرستنده (برای کاربران معمولی)
    tax = int(amount * 0.05)
    total_cost = amount + tax  # مبلغی که از فرستنده کم می‌شود

    sender_balance = get_balance(sender_id)
    if sender_balance < total_cost:
        bot.reply_to(message, f"❌ موجودی کافی نیست.\nشما برای انتقال {amount} الماس، باید {total_cost} الماس داشته باشید (شامل مالیات ۵٪).")
        return

    # انتقال الماس
    change_balance(sender_id, -total_cost)
    change_balance(receiver_id, amount)

    sender_name = message.from_user.username or message.from_user.first_name or f"کاربر {sender_id}"

    # رسید
    receipt = (
        f"💎 رسید انتقال الماس\n"
        f"👤 فرستنده: <b>{sender_name}</b>\n"
        f"👥 گیرنده: <code>{receiver_id}</code>\n"
        f"💵 مبلغ ارسال: {amount}\n"
        f"🧾 مالیات از فرستنده: {tax}\n"
        f"✅ مبلغ دریافتی گیرنده: {amount}"
    )
    bot.reply_to(message, receipt, parse_mode="HTML")

    # پیام اطلاع‌رسانی به گیرنده
    try:
        bot.send_message(
            receiver_id,
            f"🎉 تبریک!\nشما <b>{amount}</b> الماس از <b>{sender_name}</b> دریافت کردید.",
            parse_mode="HTML"
        )
    except:
        pass

# ================== BET SECTION (FIXED: RLock + early answer) ==================

MIN_BET = 20
BET_TAX_PERCENT = 2
# DB_PATH already set
# db_lock is RLock above

# متن‌ها
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

    # کم کردن از کاربر (این تابع خودش از db_lock استفاده می‌کند)
    change_balance(user_id, -amount)

    # ثبت شرط در دیتابیس — فقط هنگام نوشتن به DB قفل می‌گیریم
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

    # پیام شرط (ریپلای روی پیام شروع‌کننده)
    msg = bot.send_message(m.chat.id, text, reply_markup=kb, reply_to_message_id=m.message_id)

    # ذخیره message_id
    with db_lock:
        with sqlite3.connect(DB_PATH) as conn:
            cur = conn.cursor()
            cur.execute("UPDATE bets SET message_id=? WHERE bet_id=?", (msg.message_id, bet_id))
            conn.commit()


@bot.callback_query_handler(func=lambda c: c.data and c.data.startswith("bet:"))
def cb_bet(c):
    # جواب کوتاه فوری به تلگرام تا دکمه "مشغول" نشه
    try:
        bot.answer_callback_query(c.id)
    except:
        pass

    try:
        parts = c.data.split(":")
        action = parts[1]
        bet_id = int(parts[2])
    except Exception as e:
        # invalid callback data
        try:
            bot.answer_callback_query(c.id, "❌ داده نامعتبر.")
        except:
            pass
        return

    try:
        # خواندن اطلاعات شرط (بدون نگه داشتن لاک طولانی)
        with db_lock:
            with sqlite3.connect(DB_PATH) as conn:
                cur = conn.cursor()
                cur.execute("SELECT creator_id, amount, state, player_joined_id, message_id FROM bets WHERE bet_id=?", (bet_id,))
                row = cur.fetchone()

        if not row:
            return bot.answer_callback_query(c.id, "شرط پیدا نشد.")

        creator_id, amount, state, joined_id, message_id = row
        user_id = c.from_user.id

        # --- HANDLE CANCEL ---
        if action == "cancel":
            if user_id != creator_id:
                return bot.answer_callback_query(c.id, "فقط سازنده می‌تواند لغو کند.")
            if state != "open":
                return bot.answer_callback_query(c.id, "این شرط قبلاً بسته شده است.")

            # بازگرداندن مبلغ به سازنده — change_balance خودش قفل می‌گیرد (RLock)
            change_balance(creator_id, amount)

            # علامت‌گذاری شرط به عنوان cancelled
            with db_lock:
                with sqlite3.connect(DB_PATH) as conn:
                    cur = conn.cursor()
                    cur.execute("UPDATE bets SET state='cancelled' WHERE bet_id=?", (bet_id,))
                    conn.commit()

            # ویرایش پیام شرط (استفاده از message_id ذخیره شده)
            try:
                bot.edit_message_text("❌ این شرط توسط سازنده لغو شد.", c.message.chat.id, message_id)
            except Exception:
                # fallback: اگر استفاده از c.message مشکل داشت، تلاش با chat_id/message_id ذخیره‌شده
                try:
                    bot.edit_message_text("❌ این شرط توسط سازنده لغو شد.", c.message.chat.id, message_id)
                except:
                    pass

            return bot.answer_callback_query(c.id, "شرط لغو شد.")

        # --- HANDLE JOIN ---
        elif action == "join":
            # دوباره وضعیت را چک می‌کنیم در لحظهٔ پیوستن (برای جلوگیری از race)
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

            # انجام تراکنش برای بازیکن دوم (این تابع قفل را مدیریت می‌کند)
            change_balance(user_id, -amount)

            # محاسبه مالیات و جایزه
            tax = (amount * 2 * BET_TAX_PERCENT) // 100
            prize = amount * 2 - tax

            # انتخاب برنده
            winner_id = random.choice([creator_id, user_id])
            loser_id = creator_id if winner_id == user_id else user_id

            # واریز جایزه به برنده
            change_balance(winner_id, prize)

            # بروزرسانی وضعیت شرط
            with db_lock:
                with sqlite3.connect(DB_PATH) as conn:
                    cur = conn.cursor()
                    cur.execute("UPDATE bets SET state='closed', player_joined_id=? WHERE bet_id=?", (user_id, bet_id))
                    conn.commit()

            # ویرایش پیام با نتیجه
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
        # لاگ کن برای دیباگ (print یا logging)
        print("Bet Callback Error:", repr(e))
        try:
            bot.answer_callback_query(c.id, "❌ خطا رخ داد. دوباره تلاش کنید.")
        except:
            pass

# ----------------- ADMIN PANEL -----------------
@bot.message_handler(commands=['admin'])
def cmd_admin(m: types.Message):
    if not is_admin(m.from_user.id):
        return bot.reply_to(m, "❌ فقط ادمین‌ها می‌توانند از پنل مدیریت استفاده کنند.")
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
        return bot.answer_callback_query(c.id, "اجازه ندارید.")

    parts = c.data.split(":")
    action = parts[1]

    # لیست کاربران (بر اساس بیشترین الماس)
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

# دستور تنظیم الماس توسط ادمین
@bot.message_handler(commands=['setdiamonds'])
def cmd_setdiamonds(m: types.Message):
    if not is_admin(m.from_user.id):
        return bot.reply_to(m, "اجازه ندارید.")
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
    "≼ سـلـفـ 𝐕𝐢𝐏 ≽", "≼ خـدمـاتـ 𝐕𝐢𝐏 ≽", "≼ شـارژ مـوجـودی 💳 ≽", "≼ الماس رایگان ≽"
])
def private_menu(m: types.Message):
    txt = m.text.strip()
    if txt in ("≼ سـلـفـ 𝐕𝐢𝐏 ≽", "≼ خـدمـاتـ 𝐕𝐢𝐏 ≽"):
        return bot.reply_to(m, "در حال آپدیت...")
    if txt == "≼ شـارژ مـوجـودی 💳 ≽":
        return bot.reply_to(m, "برای خرید به آیدی‌های زیر مراجعه کنید:\n👤 مالک: @AliZord_yt\n🛡 پشتیبانی: @ABOLRNRNR")
    if txt == "≼ الماس رایگان ≽":
        count = get_ref_count(m.from_user.id)
        link = f"https://t.me/{BOT_USERNAME}?start={m.from_user.id}"
        return bot.reply_to(m, FREE_DIAMOND_TEXT.format(count=count, link=link))

# ----------------- BALANCE (ریپلای + عکس) -----------------
@bot.message_handler(func=lambda m: isinstance(m.text, str) and m.text.strip() == "موجودی")
def cmd_balance(m: types.Message):
    user_id = m.from_user.id
    if is_owner(user_id):
        # نمایش بینهایت برای مالک
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
if __name__ == "__main__":
    init_db()
    print("✅ VIP Bot v18 ران شد (نسخه مدیریت + الماس بینهایت برای مالک).")
    bot.infinity_polling()