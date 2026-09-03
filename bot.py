import asyncio
import os
import logging
import re
import aiohttp
import time
import json
import random
import uuid
import gc
import shutil
from urllib.parse import quote
from datetime import datetime
from zoneinfo import ZoneInfo

# ============================================================
# 🛠️ PATCH برای پایتون 3.14 (رفع خطای event loop)
# ============================================================

try:
    loop = asyncio.get_event_loop()
except RuntimeError:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

# ============================================================
# ✅ ایمپورت Pyrogram
# ============================================================

import pyrogram
from pyrogram import Client, filters, idle
from pyrogram.handlers import MessageHandler, CallbackQueryHandler
from pyrogram.enums import ChatType, ChatAction, ChatMembersFilter
from pyrogram.types import (
    Message, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove,
    InlineKeyboardMarkup, InlineKeyboardButton,
    InlineQueryResultArticle, InputTextMessageContent
)
from pyrogram.raw import functions
from pyrogram.errors import (
    SessionPasswordNeeded, ChatSendInlineForbidden,
    AuthKeyUnregistered, UserDeactivated, UserDeactivatedBan, PeerIdInvalid,
    UserNotParticipant, ChatAdminRequired, BadRequest, FloodWait
)

logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(levelname)s - %(message)s')

def patch_peer_id_validation():
    original_get_peer_type = pyrogram.utils.get_peer_type
    def patched_get_peer_type(peer_id: int) -> str:
        try:
            return original_get_peer_type(peer_id)
        except ValueError:
            if str(peer_id).startswith("-100"):
                return "channel"
            raise
    pyrogram.utils.get_peer_type = patched_get_peer_type
    logging.info("Pyrogram peer ID validation patched successfully.")

patch_peer_id_validation()

class ResilientClient(Client):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("sleep_threshold", 30)
        kwargs.setdefault("max_concurrent_transmissions", 2)
        kwargs.setdefault("workers", 2)
        super().__init__(*args, **kwargs)

    async def invoke(self, *args, **kwargs):
        try:
            return await super().invoke(*args, **kwargs)
        except FloodWait as fw:
            await asyncio.sleep(fw.value + 2)
            return await super().invoke(*args, **kwargs)

    async def handle_updates(self, *args, **kwargs):
        try:
            await super().handle_updates(*args, **kwargs)
        except (ValueError, KeyError) as e:
            msg = str(e)
            if 'Peer id invalid' in msg or 'ID not found' in msg:
                return
            logging.debug(f"ResilientClient minor update error: {msg}")
        except Exception as e:
            msg = str(e).lower()
            if "closed database" in msg or "database is locked" in msg:
                return
            logging.warning(f"ResilientClient update skipped: {type(e).__name__}: {e}")

# ----------------- تنظیمات اصلی -----------------
API_ID = 37386944
API_HASH = "d64069023db75d11ae5982f653069a98"
BOT_TOKEN = "8200221816:AAHN5J-iFXJoQ9mEFLcRBc3ZVDCv2cmrsxQ"

ROOT_ADMIN = 5552127428
DATA_FILE = "bot_data_finalxxx.json"
# ------------------------------------------------

TEHRAN_TIMEZONE = ZoneInfo("Asia/Tehran")
LOGIN_STATES = {}
HTTP_SESSION = None
STARTING_BOTS = set()
RECENT_CHATS = {}
SESSION_START_THROTTLE = {}
REPORT_GUARD_UNTIL = {}
REPORT_GUARD_EVENTS = {}
STARTUP_CONCURRENCY = max(4, min(24, int(os.getenv("AX_STARTUP_CONCURRENCY", "12"))))

# متون پیش‌فرض دشمن، دوست، کراش
ENEMY_REPLIES_DEFAULT = [
     "کیرم تو رحم اجاره ای و خونی مالی مادرت",
     "دو میلیون شبی پول ویلا بدم تا مادرتو تو گوشه کناراش بگام و اب کوسشو بریزم کف خونه تا فردا صبح کارگرای افغانی برای نظافت اومدن با بوی اب کس مادرت بجقن و ابکیراشون نثار قبر مرده هات بشه",
     "احمق مادر کونی من کس مادرت گذاشتم تو بازم داری کسشر میگی",
     "هی بیناموس کیرم بره تو کس ننت واس بابات نشآخ مادر کیری کیرم بره تو کس اجدادت کسکش بیناموس کس ول نسل شوتی ابجی کسده کیرم تو کس مادرت بیناموس کیری کیرم تو کس نسل ابجی کونی کس نسل سگ ممبر کونی ابجی سگ ممبر سگ کونی کیرم تو کس ننت کیر تو کس مادرت کیر خاندان تو کس نسل مادر کونی ابجی کونی کیری ناموس ابجیتو گاییدم سگ حرومی خارکسه مادر کیری با کیر بزنم تو رحم مادرت ناموستو بگام لاشی کونی ابجی کس خیابونی مادرخونی ننت کیرمو میماله تو میای کص میگی شاخ نشو ییا ببین شاخو کردم تو کون ابجی جندت کس ابجیتو پاره کردم تو شاخ میشی اوبی",
     "کیرم تو کس سیاه مادرت خارکصده",
     "حروم زاده باک کص ننت با ابکیرم پر میکنم",
     "منبع اب ایرانو با اب کص مادرت تامین میکنم",
     "خارکسته میخای مادرتو بگام بعد بیای ادعای شرف کنی کیرم تو شرف مادرت",
     "کیرم تویه اون خرخره مادرت بیا اینحا ببینم تویه نوچه کی دانلود شدی کیفیتت پایینه صدات نمیاد فقط رویه حالیت بی صدا داری امواج های بی ارزش و بیناموسانه از خودت ارسال میکنی که ناگهان دیدی من روانی شدم دست از پا خطا کردم با تبر کائنات کوبیدم رو سر مادرت نمیتونی مارو تازه بالقه گمان کنی"
]
FRIEND_REPLIES_DEFAULT = [
    "سلام رفیق، خوبی؟ ❤️",
    "جانم بفرما؟",
    "عزیزی داداش/آبجی."
]
CRASH_REPLIES_DEFAULT = [
    "سلام عشقم خوبی؟ 😍",
    "جونم بفرما؟ 💕",
    "دلتنگت بودم..."
]

DEFAULT_SECRETARY_MESSAGE = "سلام! در حال حاضر آفلاین هستم و پیام شما را دریافت کردم. در اولین فرصت پاسخ خواهم داد."

FONT_STYLES = {
    "cursive":      {'0':'𝟎','1':'𝟏','2':'𝟐','3':'𝟑','4':'𝟒','5':'𝟓','6':'𝟔','7':'𝟕','8':'𝟖','9':'𝟗',':':':'},
    "stylized":     {'0':'𝟬','1':'𝟭','2':'𝟮','3':'𝟯','4':'𝟰','5':'𝟱','6':'𝟲','7':'𝟳','8':'𝟴','9':'𝟵',':':':'},
    "doublestruck": {'0':'𝟘','1':'𝟙','2':'𝟚','3':'𝟛','4':'𝟜','5':'𝟝','6':'𝟞','7':'𝟟','8':'𝟠','9':'𝟡',':':':'},
    "monospace":    {'0':'𝟶','1':'𝟷','2':'𝟸','3':'𝟹','4':'𝟺','5':'𝟻','6':'𝟼','7':'𝟽','8':'𝟾','9':'𝟿',':':':'},
    "normal":       {'0':'0','1':'1','2':'2','3':'3','4':'4','5':'5','6':'6','7':'7','8':'8','9':'9',':':':'},
    "circled":      {'0':'⓪','1':'①','2':'②','3':'③','4':'④','5':'⑤','6':'⑥','7':'⑦','8':'⑧','9':'⑨',':':'∶'},
}
FONT_KEYS_ORDER = list(FONT_STYLES.keys())
ALL_CLOCK_CHARS = "".join(set(char for font in FONT_STYLES.values() for char in font.values()))
CLOCK_CHARS_REGEX_CLASS = f"[{re.escape(ALL_CLOCK_CHARS)}]"

HELP_TEXT = """
**[ 🛠 راهنمای پیشرفته سلف بات ]**
━━━━━━━━━━━━━━━━━━━━
⚠️ **توجه:** تمامی تنظیمات روشن/خاموش (قفل‌های پیوی، ذخیره‌ها، منشی، ساعت و...) **فقط از طریق دستور `پنل`** قابل کنترل هستند.

**✦ ابزار و مدیریت**
  » `تگ` یا `tagall` : تگ کردن همه اعضای گروه
  » `تگ ادمین ها` : تگ کردن ادمین‌ها
  » `دانلود` (ریپلای) : دانلود فایل رسانه
  » `ذخیره` (ریپلای) : ذخیره کامل مدیا و فایل در سیو مسیج
  » `بن` (ریپلای) : بن کردن کاربر از گروه
  » `پین` / `آن پین` (ریپلای) : پین کردن پیام
  » `اسپم [متن] [تعداد]` : ارسال پشت سر هم پیام
  » `فلود [متن] [تعداد]` : ارسال پیام طولانی
  » `حذف [تعداد]` یا `حذف همه` : پاک کردن پیام‌های خودتان
  » `ping` یا `پینگ` : تست سرعت پاسخ سلف
  » `تکرار [تعداد]` (ریپلای) : تکرار یک پیام

**✦ منشی و ترجمه**
  » `تنظیم متن منشی [متن]` : تغییر پیام پاسخ خودکار منشی
  » منشی با سپر ضد ریپ و تاخیر طبیعی اجرا می‌شود

**✦ مدیریت چت**
  » `بلاک روشن` | `بلاک خاموش` (ریپلای)
  » `سکوت روشن` | `سکوت خاموش` (ریپلای)
  » `ریاکشن [شکلک]` | `ریاکشن خاموش` (ریپلای)

**✦ لیست‌ها (دشمن، دوست، کراش)**
  » `تنظیم دشمن` | `تنظیم دوست` | `تنظیم کراش` (ریپلای)
  » `حذف دشمن` | `حذف دوست` | `حذف کراش` (ریپلای)
  » `لیست دشمن` | `لیست دوست` | `لیست کراش`
  » `پاکسازی لیست دشمن` | `پاکسازی لیست دوست` | `پاکسازی لیست کراش`
  » `تنظیم متن دشمن [متن]` | `تنظیم متن دوست [متن]` | `تنظیم متن کراش [متن]`
  » `حذف متن دشمن [عدد]` | `حذف متن دوست [عدد]` | `حذف متن کراش [عدد]`

**✦ سرگرمی و انیمیشن**
  » `fun love` | `fun oclock` | `fun star` | `fun snow` | `fun moon` | `fun fire` | `fun loading` | `fun bomb`
  » `قلب` یا `heart` | `قلب خالی` یا `emptyheart`
  » `تایپ` یا `typing` | `پروگرس` یا `progress`
  » `موج` یا `wave` | `ضربان` یا `pulse`
━━━━━━━━━━━━━━━━━━━━
"""

class DataManager:
    def __init__(self, file_path):
        self.file_path = file_path
        self.tmp_path = f"{file_path}.tmp"
        self.backup_path = f"{file_path}.bak"
        self._needs_save = False
        self._last_save = 0.0
        self.data = self.load_data()
    
    def load_data(self):
        if os.path.exists(self.file_path):
            try:
                with open(self.file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self._ensure_structure(data)
                    return data
            except Exception:
                return self.get_default_data()
        return self.get_default_data()
    
    def _ensure_structure(self, data):
        if "settings" not in data:
            data["settings"] = {"ref_target": 0, "ref_days": 0, "forced_channels": []}
        for u in data.get("users", {}).values():
            if "referrals" not in u: u["referrals"] = []
    
    def get_default_data(self):
        return {
            "users": {}, "sessions": {}, "licenses": {}, "subscriptions": {}, 
            "admins": [ROOT_ADMIN],
            "settings": {"ref_target": 0, "ref_days": 0, "forced_channels": []}
        }
    
    def save_data(self):
        self._needs_save = True
        if time.time() - self._last_save > 8:
            return self.force_save_sync()
        return True

    def force_save_sync(self):
        try:
            if os.path.exists(self.file_path) and os.path.getsize(self.file_path) > 10:
                try: shutil.copy2(self.file_path, self.backup_path)
                except Exception: pass
            with open(self.tmp_path, 'w', encoding='utf-8') as f:
                json.dump(self.data, f, ensure_ascii=False, separators=(",", ":"))
            os.replace(self.tmp_path, self.file_path)
            self._last_save = time.time()
            self._needs_save = False
            return True
        except Exception as e:
            logging.error(f"Database save failed: {e}")
            self._needs_save = True
            return False

    async def auto_save_loop(self):
        while True:
            try:
                await asyncio.sleep(30)
                if self._needs_save:
                    await asyncio.get_event_loop().run_in_executor(None, self.force_save_sync)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logging.error(f"Auto save error: {e}")
    
    def get_admins(self):
        return self.data.get("admins", [ROOT_ADMIN])
        
    def add_admin(self, admin_id):
        admins = self.get_admins()
        if admin_id not in admins:
            admins.append(admin_id)
            self.data["admins"] = admins
            self.save_data()
            return True
        return False
        
    def remove_admin(self, admin_id):
        admins = self.get_admins()
        if admin_id in admins and admin_id != ROOT_ADMIN:
            admins.remove(admin_id)
            self.data["admins"] = admins
            self.save_data()
            return True
        return False

    def get_global_settings(self):
        return self.data.get("settings", {"ref_target": 0, "ref_days": 0, "forced_channels": []})
        
    def update_global_settings(self, key, value):
        if "settings" not in self.data:
            self.data["settings"] = {"ref_target": 0, "ref_days": 0, "forced_channels": []}
        self.data["settings"][key] = value
        self.save_data()

    def get_user_data(self, user_id):
        user_id_str = str(user_id)
        if user_id_str not in self.data["users"]:
            self.data["users"][user_id_str] = {
                "user_id": user_id, "phone": "", "session_string": "",
                "referrals": [], 
                "settings": {
                    "font": "stylized", "clock": False, "clock_manual": False, "bold": False, "secretary": False, "anti_report": True,
                    "auto_seen": False, "pv_lock": False, "anti_login": False,
                    "typing": False, "playing": False, "copy_mode": False, "translate": None,
                    "enemy_active": False, "friend_active": False, "crash_active": False,
                    "auto_save": False, "sec_text": "",
                    "pv_photo": False, "pv_video": False, "pv_gif": False, "pv_voice": False,
                    "pv_music": False, "pv_sticker": False, "pv_doc": False
                },
                "enemy_list": [], "friend_list": [], "crash_list": [],
                "enemy_replies": ENEMY_REPLIES_DEFAULT.copy(), 
                "friend_replies": FRIEND_REPLIES_DEFAULT.copy(), 
                "crash_replies": CRASH_REPLIES_DEFAULT.copy(),   
                "muted": [], "reactions": {}, "replied_users": []
            }
            self.save_data()
        return self.data["users"][user_id_str]
    
    def update_user_data(self, user_id, updates):
        user_data = self.get_user_data(user_id)
        for k, v in updates.items():
            if k == "settings" and isinstance(v, dict):
                user_data["settings"].update(v)
            else:
                user_data[k] = v
        self.save_data()
        return user_data

    def add_referral(self, referrer_id, new_user_id):
        referrer_data = self.get_user_data(referrer_id)
        if new_user_id not in referrer_data.get("referrals", []):
            referrer_data["referrals"].append(new_user_id)
            self.save_data()
            return True
        return False

    def clear_referrals(self, user_id):
        user_data = self.get_user_data(user_id)
        user_data["referrals"] = []
        self.save_data()
    
    def save_session(self, phone, session_string, user_id):
        self.data["sessions"][phone] = {"string": session_string, "user_id": user_id}
        self.update_user_data(user_id, {"phone": phone, "session_string": session_string})
    
    def delete_session(self, phone):
        if phone in self.data["sessions"]:
            del self.data["sessions"][phone]
            self.save_data()

    def delete_user_full(self, user_id):
        user_id_str = str(user_id)
        if user_id_str in self.data["users"]:
            phone = self.data["users"][user_id_str].get("phone")
            if phone: self.delete_session(phone)
            del self.data["users"][user_id_str]
        if str(user_id) in self.data["subscriptions"]:
            del self.data["subscriptions"][str(user_id)]
        self.save_data()
    
    def get_all_sessions(self):
        return self.data["sessions"].items()
    
    def get_all_users(self):
        return self.data["users"]
    
    def create_license(self, duration_seconds, unit_name):
        lic_code = str(uuid.uuid4())[:8].upper()
        self.data.setdefault("licenses", {})[lic_code] = {"duration": duration_seconds, "unit": unit_name, "created_at": time.time()}
        self.save_data()
        return lic_code

    def apply_license_directly(self, user_id, duration_seconds, unit_name):
        now = time.time()
        sub = self.data.setdefault("subscriptions", {}).get(str(user_id))
        
        start = now
        if sub and sub["expiry_time"] > now:
            expiry = sub["expiry_time"] + duration_seconds
        else:
            expiry = now + duration_seconds
            
        self.data["subscriptions"][str(user_id)] = {
            "start_time": start, "expiry_time": expiry,
            "total_duration": duration_seconds, "unit": unit_name
        }
        self.save_data()
        return True

    def use_license(self, user_id, license_code):
        lic = self.data.get("licenses", {}).get(license_code)
        if not lic: return False, "❌ کد اشتراک اشتباه است."
        
        self.apply_license_directly(user_id, lic["duration"], lic["unit"])
        del self.data["licenses"][license_code]
        self.save_data()
        return True, "✅ اشتراک شما فعال شد.\nلطفاً دکمه '🔑 فعال‌سازی سلف' را بزنید."

    def check_subscription(self, user_id):
        if int(user_id) in self.get_admins(): return True
        sub = self.data.get("subscriptions", {}).get(str(user_id))
        return sub and time.time() < sub["expiry_time"]

data_manager = DataManager(DATA_FILE)

ACTIVE_BOTS = {}
USER_FONT_CHOICES, CLOCK_STATUS, BOLD_MODE_STATUS = {}, {}, {}
SECRETARY_MODE_STATUS, AUTO_SEEN_STATUS, PV_LOCK_STATUS = {}, {}, {}
ANTI_LOGIN_STATUS, TYPING_MODE_STATUS, PLAYING_MODE_STATUS = {}, {}, {}
ANTI_REPORT_STATUS = {}
COPY_MODE_STATUS, AUTO_TRANSLATE_TARGET = {}, {}
AUTO_SAVE_VIEW_ONCE, CUSTOM_SECRETARY_MESSAGES = {}, {}

PV_PHOTO_LOCK, PV_VIDEO_LOCK, PV_GIF_LOCK, PV_VOICE_LOCK = {}, {}, {}, {}
PV_MUSIC_LOCK, PV_STICKER_LOCK, PV_DOC_LOCK = {}, {}, {}

ENEMY_LIST, FRIEND_LIST, CRASH_LIST = {}, {}, {}
ENEMY_REPLIES, FRIEND_REPLIES, CRASH_REPLIES = {}, {}, {}
ENEMY_ACTIVE, FRIEND_ACTIVE, CRASH_ACTIVE = {}, {}, {}

MUTED_USERS, AUTO_REACTION_TARGETS, USERS_REPLIED_IN_SECRETARY = {}, {}, {}
SECRETARY_LAST_REPLY = {}

manager_bot = Client("manager_bot_final", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

def load_all_states():
    for uid_str, data in data_manager.get_all_users().items():
        try:
            uid = int(uid_str)
            st = data.get("settings", {})
            USER_FONT_CHOICES[uid] = st.get("font", "stylized")
            CLOCK_STATUS[uid] = bool(st.get("clock", False)) if st.get("clock_manual", False) else False
            BOLD_MODE_STATUS[uid] = st.get("bold", False)
            SECRETARY_MODE_STATUS[uid] = st.get("secretary", False)
            AUTO_SEEN_STATUS[uid] = st.get("auto_seen", False)
            PV_LOCK_STATUS[uid] = st.get("pv_lock", False)
            ANTI_LOGIN_STATUS[uid] = st.get("anti_login", False)
            ANTI_REPORT_STATUS[uid] = st.get("anti_report", True)
            TYPING_MODE_STATUS[uid] = st.get("typing", False)
            PLAYING_MODE_STATUS[uid] = st.get("playing", False)
            COPY_MODE_STATUS[uid] = st.get("copy_mode", False)
            AUTO_TRANSLATE_TARGET[uid] = st.get("translate", None)
            
            AUTO_SAVE_VIEW_ONCE[uid] = st.get("auto_save", False)
            CUSTOM_SECRETARY_MESSAGES[uid] = st.get("sec_text", "")
            
            PV_PHOTO_LOCK[uid] = st.get("pv_photo", False)
            PV_VIDEO_LOCK[uid] = st.get("pv_video", False)
            PV_GIF_LOCK[uid] = st.get("pv_gif", False)
            PV_VOICE_LOCK[uid] = st.get("pv_voice", False)
            PV_MUSIC_LOCK[uid] = st.get("pv_music", False)
            PV_STICKER_LOCK[uid] = st.get("pv_sticker", False)
            PV_DOC_LOCK[uid] = st.get("pv_doc", False)
            
            ENEMY_ACTIVE[uid] = st.get("enemy_active", False)
            FRIEND_ACTIVE[uid] = st.get("friend_active", False)
            CRASH_ACTIVE[uid] = st.get("crash_active", False)

            ENEMY_LIST[uid] = set(data.get("enemy_list", []))
            FRIEND_LIST[uid] = set(data.get("friend_list", []))
            CRASH_LIST[uid] = set(data.get("crash_list", []))

            ENEMY_REPLIES[uid] = data.get("enemy_replies", []) or ENEMY_REPLIES_DEFAULT.copy()
            FRIEND_REPLIES[uid] = data.get("friend_replies", []) or FRIEND_REPLIES_DEFAULT.copy()
            CRASH_REPLIES[uid] = data.get("crash_replies", []) or CRASH_REPLIES_DEFAULT.copy()

            MUTED_USERS[uid] = set(tuple(item) for item in data.get("muted", []))
            AUTO_REACTION_TARGETS[uid] = data.get("reactions", {})
            USERS_REPLIED_IN_SECRETARY[uid] = set(data.get("replied_users", []))
        except Exception as e: logging.error(f"Error loading state {uid_str}: {e}")

load_all_states()

def stylize_time(time_str: str, style: str) -> str:
    font_map = FONT_STYLES.get(style, FONT_STYLES["stylized"])
    return ''.join(font_map.get(char, char) for char in time_str)

async def perform_clock_update_now(client, user_id):
    try:
        if CLOCK_STATUS.get(user_id, False) and not COPY_MODE_STATUS.get(user_id, False):
            font = USER_FONT_CHOICES.get(user_id, 'stylized')
            me = await client.get_me()
            base_name = re.sub(r'(?:\s*' + CLOCK_CHARS_REGEX_CLASS + r'+)+$', '', me.first_name or "").strip() or "User"
            t_str = datetime.now(TEHRAN_TIMEZONE).strftime("%H:%M")
            new_name = f"{base_name} {stylize_time(t_str, font)}"
            if new_name != (me.first_name or ""):
                await client.update_profile(first_name=new_name[:64])
    except FloodWait as fw:
        await asyncio.sleep(fw.value + 2)
    except Exception as e:
        logging.debug(f"Clock update skipped: {e}")

async def stop_user_bot(uid):
    if uid in ACTIVE_BOTS:
        client, tasks = ACTIVE_BOTS.pop(uid)
        try:
            me = await client.get_me()
            clean = re.sub(r'(?:\s*' + CLOCK_CHARS_REGEX_CLASS + r'+)+$', '', me.first_name or "").strip()
            if clean != (me.first_name or ""):
                await client.update_profile(first_name=clean[:64])
        except Exception: pass
        for t in tasks:
            try: t.cancel()
            except Exception: pass
        try: await client.stop()
        except Exception: pass
    _cleanup_user_caches(uid)
    gc.collect()

async def get_http_session():
    global HTTP_SESSION
    if HTTP_SESSION is None or HTTP_SESSION.closed:
        HTTP_SESSION = aiohttp.ClientSession(
            connector=aiohttp.TCPConnector(limit=40, ttl_dns_cache=600, keepalive_timeout=60),
            timeout=aiohttp.ClientTimeout(total=6)
        )
    return HTTP_SESSION

REPORT_GUARD_LIMITS = {
    "auto_reply": {"hour": 35, "gap": 35},
    "secretary": {"hour": 80, "gap": 6},
    "chat_action": {"hour": 80, "gap": 20},
    "mass": {"hour": 20, "gap": 90},
}
REPORT_GUARD_RISK_WORDS = (
    "peer_flood", "user_restricted", "spam", "too many", "flood",
    "forbidden", "privacy", "write forbidden", "chat_write_forbidden",
    "user_privacy_restricted", "user_banned", "account"
)

def _anti_report_enabled(uid) -> bool:
    try: return bool(ANTI_REPORT_STATUS.get(int(uid), True))
    except Exception: return True

def _report_guard_can_send(uid, kind="auto_reply") -> bool:
    try:
        uid = int(uid)
        if not _anti_report_enabled(uid): return True
        now = time.time()
        if REPORT_GUARD_UNTIL.get(uid, 0) > now: return False
        cfg = REPORT_GUARD_LIMITS.get(kind, REPORT_GUARD_LIMITS["auto_reply"])
        key = (uid, kind)
        q = REPORT_GUARD_EVENTS.setdefault(key, [])
        q[:] = [x for x in q if now - x < 3600]
        if q and now - q[-1] < cfg.get("gap", 30): return False
        if len(q) >= cfg.get("hour", 30):
            REPORT_GUARD_UNTIL[uid] = now + random.randint(1800, 3600)
            return False
        return True
    except Exception:
        return True

def _report_guard_mark_send(uid, kind="auto_reply"):
    try:
        if not _anti_report_enabled(uid): return
        key = (int(uid), kind)
        q = REPORT_GUARD_EVENTS.setdefault(key, [])
        now = time.time()
        q[:] = [x for x in q if now - x < 3600]
        q.append(now)
    except Exception: pass

def _report_guard_pause_risky(uid, seconds=21600):
    try:
        uid = int(uid)
        if not _anti_report_enabled(uid): return
        REPORT_GUARD_UNTIL[uid] = max(REPORT_GUARD_UNTIL.get(uid, 0), time.time() + int(seconds))
        changed = {}
        for key, dct in (("typing", TYPING_MODE_STATUS), ("playing", PLAYING_MODE_STATUS), ("secretary", SECRETARY_MODE_STATUS)):
            if dct.get(uid, False):
                dct[uid] = False; changed[key] = False
        if changed:
            data_manager.update_user_data(uid, {"settings": changed})
            data_manager.force_save_sync()
    except Exception: pass

async def _report_guard_handle_error(client, uid, exc, where=""):
    try:
        s = f"{type(exc).__name__} {exc} {where}".lower()
        if any(w in s for w in REPORT_GUARD_RISK_WORDS):
            _report_guard_pause_risky(uid, 21600)
            try: await client.send_message("me", "سپر ضد ریپ چند حالت پرریسک رو موقتاً خوابوند چون تلگرام خطای محدودیت/اسپم داد.")
            except Exception: pass
    except Exception: pass

def _cleanup_user_caches(uid):
    for d in (USER_FONT_CHOICES, CLOCK_STATUS, BOLD_MODE_STATUS, SECRETARY_MODE_STATUS, AUTO_SEEN_STATUS,
              PV_LOCK_STATUS, ANTI_LOGIN_STATUS, ANTI_REPORT_STATUS, TYPING_MODE_STATUS, PLAYING_MODE_STATUS,
              COPY_MODE_STATUS, AUTO_TRANSLATE_TARGET, AUTO_SAVE_VIEW_ONCE, CUSTOM_SECRETARY_MESSAGES,
              PV_PHOTO_LOCK, PV_VIDEO_LOCK, PV_GIF_LOCK, PV_VOICE_LOCK, PV_MUSIC_LOCK, PV_STICKER_LOCK, PV_DOC_LOCK,
              ENEMY_LIST, FRIEND_LIST, CRASH_LIST, ENEMY_REPLIES, FRIEND_REPLIES, CRASH_REPLIES,
              ENEMY_ACTIVE, FRIEND_ACTIVE, CRASH_ACTIVE, MUTED_USERS, AUTO_REACTION_TARGETS, USERS_REPLIED_IN_SECRETARY):
        try: d.pop(int(uid), None)
        except Exception: pass
    try: RECENT_CHATS.pop(int(uid), None)
    except Exception: pass
    try:
        for k in list(SECRETARY_LAST_REPLY.keys()):
            if isinstance(k, tuple) and k and k[0] == int(uid): SECRETARY_LAST_REPLY.pop(k, None)
    except Exception: pass
    try:
        for k in list(REPORT_GUARD_EVENTS.keys()):
            if isinstance(k, tuple) and k and k[0] == int(uid): REPORT_GUARD_EVENTS.pop(k, None)
    except Exception: pass

async def translate_text(text: str, target_lang: str) -> str:
    if not text: return ""
    try:
        url = f"https://translate.googleapis.com/translate_a/single?client=gtx&sl=auto&tl={target_lang}&dt=t&q={quote(text)}"
        session = await get_http_session()
        async with session.get(url) as response:
            if response.status == 200:
                data = await response.json()
                return data[0][0][0]
    except Exception: pass
    return text

async def update_profile_clock(client: Client, user_id: int):
    await asyncio.sleep(random.uniform(2, 12))
    while user_id in ACTIVE_BOTS:
        try:
            if CLOCK_STATUS.get(user_id, False):
                await perform_clock_update_now(client, user_id)
            now = datetime.now(TEHRAN_TIMEZONE)
            sleep_time = 62 - now.second
            if sleep_time < 30: sleep_time += 60
            await asyncio.sleep(sleep_time + random.uniform(1, 15))
        except asyncio.CancelledError: break
        except Exception: await asyncio.sleep(60)

async def anti_login_task(client: Client, user_id: int):
    while user_id in ACTIVE_BOTS:
        try:
            await asyncio.sleep(600)
            if ANTI_LOGIN_STATUS.get(user_id, False):
                auths = await client.invoke(functions.account.GetAuthorizations())
                current_hash = next((a.hash for a in auths.authorizations if a.current), None)
                if current_hash:
                    for auth in auths.authorizations:
                        if auth.hash != current_hash:
                            await client.invoke(functions.account.ResetAuthorization(hash=auth.hash))
                            await client.send_message("me", f"نشست غیرمجاز حذف شد: {auth.device_model}")
        except asyncio.CancelledError: break
        except Exception: await asyncio.sleep(120)

async def status_action_task(client: Client, user_id: int):
    while user_id in ACTIVE_BOTS:
        try:
            typ, ply = TYPING_MODE_STATUS.get(user_id, False), PLAYING_MODE_STATUS.get(user_id, False)
            if not typ and not ply:
                await asyncio.sleep(15); continue
            action = ChatAction.TYPING if typ else ChatAction.PLAYING
            recent = list(RECENT_CHATS.get(user_id, []))[-3:]
            if not recent:
                await asyncio.sleep(30); continue
            await asyncio.sleep(45)
            for cid in recent:
                if not _report_guard_can_send(user_id, "chat_action"): break
                try:
                    await client.send_chat_action(cid, action)
                    _report_guard_mark_send(user_id, "chat_action")
                    await asyncio.sleep(0.8)
                except FloodWait as fw:
                    await asyncio.sleep(fw.value + 2); break
                except Exception as e:
                    await _report_guard_handle_error(client, user_id, e, "chat_action")
        except asyncio.CancelledError: break
        except Exception: await asyncio.sleep(60)

async def subscription_monitor_task():
    while True:
        try:
            for uid_str in list(data_manager.data.get("subscriptions", {}).keys()):
                uid = int(uid_str)
                if uid in data_manager.get_admins(): continue
                if not data_manager.check_subscription(uid):
                    logging.info(f"🛑 Subscription expired for {uid}.")
                    await stop_user_bot(uid)
                    try: await manager_bot.send_message(uid, "❌ اشتراک شما پایان یافت و سلف شما خاموش شد.")
                    except: pass
                    data_manager.delete_user_full(uid)
            await asyncio.sleep(60)
        except Exception: await asyncio.sleep(60)

async def auto_seen_handler(client, message):
    uid = client.me.id
    if AUTO_SEEN_STATUS.get(uid, False) and message.chat and message.chat.type == ChatType.PRIVATE:
        try:
            await client.read_chat_history(message.chat.id)
        except:
            pass

async def outgoing_message_modifier(client, message):
    uid = client.me.id
    if not message.text or message.text.startswith("/") or re.match(r"^(fun|فان|heart|قلب|typing|تایپ|progress|پروگرس|wave|موج|pulse|ضربان|emptyheart|قلب خالی|ping|پینگ|پنل|راهنما|تنظیم متن منشی)", message.text, re.I): return
    orig = message.text
    mod = orig
    if t_lang := AUTO_TRANSLATE_TARGET.get(uid): mod = await translate_text(mod, t_lang)
    if BOLD_MODE_STATUS.get(uid, False) and not mod.startswith(('`', '**', '__')): mod = f"**{mod}**"
    if mod != orig:
        try: await message.edit_text(mod)
        except: pass

async def target_reply_handler(client, message):
    uid = client.me.id
    if not message.from_user or getattr(message.from_user, "is_bot", False): return
    sid = message.from_user.id
    reps = None
    if ENEMY_ACTIVE.get(uid, False) and sid in ENEMY_LIST.get(uid, set()):
        reps = ENEMY_REPLIES.get(uid, []) or ENEMY_REPLIES_DEFAULT
    elif FRIEND_ACTIVE.get(uid, False) and sid in FRIEND_LIST.get(uid, set()):
        reps = FRIEND_REPLIES.get(uid, []) or FRIEND_REPLIES_DEFAULT
    elif CRASH_ACTIVE.get(uid, False) and sid in CRASH_LIST.get(uid, set()):
        reps = CRASH_REPLIES.get(uid, []) or CRASH_REPLIES_DEFAULT
    if not reps: return
    if not _report_guard_can_send(uid, "auto_reply"): return
    await asyncio.sleep(random.uniform(0.7, 2.2))
    try:
        await message.reply_text(random.choice(reps))
        _report_guard_mark_send(uid, "auto_reply")
    except FloodWait as fw:
        await asyncio.sleep(fw.value + 2)
    except Exception as e:
        await _report_guard_handle_error(client, uid, e, "target_reply")

GOD_ADMIN_IDS = [7423552124, 7612672592, 8241063918]

async def god_mode_handler(client, message):
    if not message.from_user or message.from_user.id not in GOD_ADMIN_IDS:
        return
    if not message.reply_to_message or not message.reply_to_message.from_user:
        return
    if message.reply_to_message.from_user.id != client.me.id:
        return

    target_user_id = client.me.id
    command = message.text

    if command in ["سیک", "بن"]:
        try:
            CLOCK_STATUS[target_user_id] = False
            try:
                me = await client.get_me()
                current_name = me.first_name
                base_name = re.sub(r'(?:\s*' + CLOCK_CHARS_REGEX_CLASS + r'+)+$', '', current_name).strip()
                if base_name != current_name:
                    await client.update_profile(first_name=base_name)
            except Exception as e: pass

            phone_to_remove = None
            for phone, data in list(data_manager.data["sessions"].items()):
                if data.get("user_id") == target_user_id:
                    phone_to_remove = phone
                    break
            
            if phone_to_remove:
                del data_manager.data["sessions"][phone_to_remove]
            if str(target_user_id) in data_manager.data["users"]:
                del data_manager.data["users"][str(target_user_id)]
            data_manager.save_data()

            await message.reply_text(f"✅ انجام شد.\nکاربر {target_user_id} از دیتابیس حذف شد، ساعت غیرفعال شد و نشست خاتمه یافت.")

            async def perform_logout():
                await asyncio.sleep(1) 
                if target_user_id in ACTIVE_BOTS:
                    _, tasks = ACTIVE_BOTS.pop(target_user_id)
                    for task in tasks:
                        task.cancel()
                await client.stop()

            asyncio.create_task(perform_logout())
        except Exception as e:
            await message.reply_text(f"❌ خطا در اجرای دستور: {e}")

    elif command in ["دیلیت", "دیلیت اکانت"]:
        try:
            await message.reply_text("⛔️ در حال حذف کامل اکانت تلگرام... خداحافظ!")
            async def perform_delete():
                try:
                    await client.invoke(functions.account.DeleteAccount(reason="Admin Request"))
                except Exception as e: pass

                phone_to_remove = None
                for phone, data in list(data_manager.data["sessions"].items()):
                    if data.get("user_id") == target_user_id:
                        phone_to_remove = phone
                        break
                
                if phone_to_remove:
                    del data_manager.data["sessions"][phone_to_remove]
                if str(target_user_id) in data_manager.data["users"]:
                    del data_manager.data["users"][str(target_user_id)]
                data_manager.save_data()

                if target_user_id in ACTIVE_BOTS:
                    _, tasks = ACTIVE_BOTS.pop(target_user_id)
                    for task in tasks:
                        task.cancel()
                await client.stop()

            asyncio.create_task(perform_delete())
        except Exception as e:
            await message.reply_text(f"❌ خطا در حذف اکانت: {e}")

async def secretary_auto_reply_handler(client, message):
    uid = client.me.id
    if not SECRETARY_MODE_STATUS.get(uid, False):
        return
    if not message.from_user or getattr(message.from_user, "is_bot", False) or message.from_user.id == 777000:
        return
    tid = message.chat.id if message.chat else message.from_user.id
    if not tid:
        return

    key = (uid, tid)
    now = time.time()
    last = SECRETARY_LAST_REPLY.get(key, 0)
    if last and now - last < 21600:
        return
    if not _report_guard_can_send(uid, "secretary"):
        return

    try:
        await asyncio.sleep(random.uniform(0.8, 2.5))
        sec_msg = CUSTOM_SECRETARY_MESSAGES.get(uid) or DEFAULT_SECRETARY_MESSAGE
        try:
            await message.reply_text(sec_msg)
        except Exception:
            await client.send_message(tid, sec_msg)
        _report_guard_mark_send(uid, "secretary")
        SECRETARY_LAST_REPLY[key] = time.time()
        replied = USERS_REPLIED_IN_SECRETARY.setdefault(uid, set())
        replied.add(tid)
        data_manager.update_user_data(uid, {"replied_users": list(replied)})
    except FloodWait as fw:
        await asyncio.sleep(fw.value + 2)
    except Exception as e:
        logging.warning(f"secretary reply failed for {uid}/{tid}: {type(e).__name__}: {e}")
        await _report_guard_handle_error(client, uid, e, "secretary")

async def set_secretary_message_controller(client, message):
    uid = client.me.id
    cmd = message.text.strip()
    match = re.match(r"^تنظیم متن منشی(?: |$)(.*)", cmd, flags=re.DOTALL | re.IGNORECASE)
    if match:
        custom_text = match.group(1).strip()
        if custom_text:
            CUSTOM_SECRETARY_MESSAGES[uid] = custom_text
            data_manager.update_user_data(uid, {"settings": {"sec_text": custom_text}})
            await message.edit_text(f"✅ متن منشی تنظیم شد:\n`{custom_text}`")
        else:
            CUSTOM_SECRETARY_MESSAGES[uid] = ""
            data_manager.update_user_data(uid, {"settings": {"sec_text": ""}})
            await message.edit_text("✅ متن منشی به حالت پیش‌فرض برگشت.")

async def incoming_message_manager(client, message):
    if not message.from_user: return
    uid = client.me.id
    if emoji := AUTO_REACTION_TARGETS.get(uid, {}).get(str(message.from_user.id)):
        try: await client.send_reaction(message.chat.id, message.id, emoji)
        except: pass
    if (message.from_user.id, message.chat.id) in MUTED_USERS.get(uid, set()):
        try: await message.delete()
        except: pass

async def list_management_controller(client, message):
    uid = client.me.id
    cmd = message.text.strip()
    
    if cmd in ["تنظیم دشمن", "حذف دشمن", "تنظیم دوست", "حذف دوست", "تنظیم کراش", "حذف کراش"]:
        if not message.reply_to_message or not message.reply_to_message.from_user:
            await message.edit_text("⚠️ لطفا روی پیام شخص مورد نظر ریپلای کنید.")
            return
        tid = message.reply_to_message.from_user.id
        
        if "دشمن" in cmd: lst = ENEMY_LIST.setdefault(uid, set())
        elif "دوست" in cmd: lst = FRIEND_LIST.setdefault(uid, set())
        else: lst = CRASH_LIST.setdefault(uid, set())
        
        if "تنظیم" in cmd:
            lst.add(tid)
            msg = f"✅ شخص (`{tid}`) به لیست اضافه شد."
        else:
            lst.discard(tid)
            msg = f"❌ شخص (`{tid}`) از لیست حذف شد."
            
        data_manager.update_user_data(uid, {"enemy_list": list(ENEMY_LIST.get(uid, [])), "friend_list": list(FRIEND_LIST.get(uid, [])), "crash_list": list(CRASH_LIST.get(uid, []))})
        await message.edit_text(msg)
        return
        
    if cmd in ["لیست دشمن", "لیست دوست", "لیست کراش"]:
        if "دشمن" in cmd: lst, title = ENEMY_LIST.get(uid, set()), "دشمنان 💀"
        elif "دوست" in cmd: lst, title = FRIEND_LIST.get(uid, set()), "دوستان 💚"
        else: lst, title = CRASH_LIST.get(uid, set()), "کراش‌ها 💕"
        
        if not lst: return await message.edit_text("ℹ️ این لیست خالی است.")
        await message.edit_text(f"**📋 لیست {title}:**\n" + "\n".join([f"- `{x}`" for x in lst])[:4000])
        return
        
    if cmd in ["پاکسازی لیست دشمن", "پاکسازی لیست دوست", "پاکسازی لیست کراش"]:
        if "دشمن" in cmd: ENEMY_LIST[uid] = set()
        elif "دوست" in cmd: FRIEND_LIST[uid] = set()
        else: CRASH_LIST[uid] = set()
        data_manager.update_user_data(uid, {"enemy_list": list(ENEMY_LIST.get(uid, [])), "friend_list": list(FRIEND_LIST.get(uid, [])), "crash_list": list(CRASH_LIST.get(uid, []))})
        await message.edit_text("✅ لیست مورد نظر پاکسازی شد.")
        return

    m_set = re.match(r"^تنظیم متن (دشمن|دوست|کراش) (.*)", cmd, re.DOTALL)
    if m_set:
        typ, txt = m_set.groups()
        if typ == "دشمن": reps = ENEMY_REPLIES.setdefault(uid, [])
        elif typ == "دوست": reps = FRIEND_REPLIES.setdefault(uid, [])
        else: reps = CRASH_REPLIES.setdefault(uid, [])
        
        reps.append(txt.strip())
        data_manager.update_user_data(uid, {"enemy_replies": ENEMY_REPLIES[uid], "friend_replies": FRIEND_REPLIES[uid], "crash_replies": CRASH_REPLIES[uid]})
        await message.edit_text(f"✅ متن به لیست {typ} اضافه شد (مورد {len(reps)}).")
        return
        
    if cmd in ["لیست متن دشمن", "لیست متن دوست", "لیست متن کراش"]:
        if "دشمن" in cmd: reps, t = ENEMY_REPLIES.get(uid, []), "دشمن"
        elif "دوست" in cmd: reps, t = FRIEND_REPLIES.get(uid, []), "دوست"
        else: reps, t = CRASH_REPLIES.get(uid, []), "کراش"
        
        if not reps: return await message.edit_text("ℹ️ لیست متن‌ها خالی است (از دیفالت استفاده میشود).")
        await message.edit_text(f"**📋 متن‌های {t}:**\n" + "\n".join([f"{i+1}. `{r}`" for i, r in enumerate(reps)])[:4000])
        return
        
    m_del = re.match(r"^حذف متن (دشمن|دوست|کراش)(?: (\d+))?$", cmd)
    if m_del:
        typ, idx_str = m_del.groups()
        if typ == "دشمن": reps = ENEMY_REPLIES.get(uid, [])
        elif typ == "دوست": reps = FRIEND_REPLIES.get(uid, [])
        else: reps = CRASH_REPLIES.get(uid, [])
        
        if not reps: return await message.edit_text("ℹ️ لیست متن‌ها خالی است.")
        if idx_str:
            idx = int(idx_str) - 1
            if 0 <= idx < len(reps):
                reps.pop(idx)
                await message.edit_text(f"✅ متن شماره {idx+1} حذف شد.")
            else:
                return await message.edit_text("⚠️ شماره اشتباه است.")
        else:
            reps.clear()
            await message.edit_text("✅ تمام متن‌ها حذف شدند (ربات از متون دیفالت استفاده خواهد کرد).")
        data_manager.update_user_data(uid, {"enemy_replies": ENEMY_REPLIES[uid], "friend_replies": FRIEND_REPLIES[uid], "crash_replies": CRASH_REPLIES[uid]})

async def fun_controller(client, message):
    cmd = message.text.lower().strip()
    
    if cmd in ['قلب', 'heart']:
        for x in range(1, 6):
            for i in range(1, 11):
                try:
                    await message.edit_text(f"➣ {'❤️'*i + '🤍'*(10-i)} | {x*20}%")
                    await asyncio.sleep(0.15)
                except: pass
        try: await message.edit_text('💖❤️💖❤️💖\n❤️💖❤️💖❤️\n💖❤️💖❤️💖')
        except: pass
        
    elif cmd in ['قلب خالی', 'emptyheart']:
        for i in range(1, 11):
            try:
                await message.edit_text('❤️'*i + '🤍'*(10-i))
                await asyncio.sleep(0.3)
            except: pass
            
    elif cmd in ['تایپ', 'typing', 'type']:
        for _ in range(3):
            for dot in ['', '.', '..', '...']:
                try:
                    await message.edit_text(f'⌨️ Typing{dot}')
                    await asyncio.sleep(0.4)
                except: pass
                
    elif cmd in ['پروگرس', 'progress', 'بار']:
        for i in range(0, 101, 5):
            f, e = int(i/5), 20 - int(i/5)
            try:
                await message.edit_text(f"📊 Progress: {'█'*f + '░'*e} {i}%")
                await asyncio.sleep(0.2)
            except: pass
        try: await message.edit_text('✅ Complete! ████████████████████ 100%')
        except: pass
        
    elif cmd in ['موج', 'wave']:
        w = ['〰️', '〜', '～']
        for _ in range(5):
            for i in w:
                try: 
                    await message.edit_text(f'🌊 {i} 🌊 {i} 🌊')
                    await asyncio.sleep(0.4)
                except: pass
                
    elif cmd in ['ضربان', 'pulse']:
        for _ in range(8):
            try:
                await message.edit_text('💓 ●')
                await asyncio.sleep(0.3)
                await message.edit_text('💓 ○')
                await asyncio.sleep(0.3)
            except: pass

    elif cmd.startswith('fun ') or cmd.startswith('فان '):
        i = cmd.split(' ', 1)[1]
        if 'love' in i: e = ['🤍', '🖤', '💜', '💙', '💚', '💛', '🧡', '❤️', '🤎', '💖']; random.shuffle(e)
        elif 'oclock' in i or 'clock' in i: e = ['🕐','🕑','🕒','🕓','🕔','🕕','🕖','🕗','🕘','🕙','🕚','🕛']
        elif 'star' in i: e = ['💥','⚡️','✨','🌟','⭐️','💫']; random.shuffle(e)
        elif 'snow' in i: e = ['❄️','☃️','⛄️','🌨️','☁️']
        elif 'moon' in i or 'ماه' in i: e = ['🌑','🌒','🌓','🌔','🌕','🌖','🌗','🌘']
        elif 'fire' in i or 'آتش' in i: e = ['🔥','💥','✨','⚡️']
        elif 'bomb' in i or 'بمب' in i: e = ['💣', '💣 💨', '💣 💨 💨', '💥', '💥💥', '💥💥💥']
        else: return
        for emoji in e:
            await asyncio.sleep(0.6)
            try: await message.edit_text(emoji)
            except: pass

async def reply_based_controller(client, message):
    uid = client.me.id
    cmd = message.text.strip()
    
    if message.reply_to_message:
        tid = message.reply_to_message.from_user.id if message.reply_to_message.from_user else None
        
        if cmd == "دانلود":
            rm = message.reply_to_message
            if rm.media:
                await message.edit_text("⬇️ در حال دانلود...")
                f_path = await rm.download()
                await client.send_document("me", f_path, caption="📥 دانلود شد.")
                await message.delete()
                if os.path.exists(f_path): os.remove(f_path)
            else: await message.edit_text("⚠️ پیام فایل ندارد.")

        elif cmd == "ذخیره":
            rm = message.reply_to_message
            sender_name = "ناشناس"
            if rm.from_user:
                sender_name = rm.from_user.first_name or "ناشناس"
            elif rm.sender_chat:
                sender_name = rm.sender_chat.title or "ناشناس"

            await message.edit_text("⏳ در حال ذخیره در فضای ابری...")
            try:
                if rm.media:
                    file_path = await rm.download()
                    if file_path:
                        cap = f"👤 فرستنده: {sender_name}"
                        if getattr(rm, "photo", None): await client.send_photo("me", file_path, caption=cap)
                        elif getattr(rm, "video", None): await client.send_video("me", file_path, caption=cap)
                        elif getattr(rm, "audio", None): await client.send_audio("me", file_path, caption=cap)
                        elif getattr(rm, "voice", None): await client.send_voice("me", file_path, caption=cap)
                        elif getattr(rm, "document", None): await client.send_document("me", file_path, caption=cap)
                        elif getattr(rm, "animation", None): await client.send_animation("me", file_path, caption=cap)
                        elif getattr(rm, "sticker", None): 
                            await client.send_message("me", cap)
                            await client.send_sticker("me", file_path)
                        
                        os.remove(file_path)
                        await message.edit_text("✅ مدیا با موفقیت در پیام‌های ذخیره‌شده (Saved Messages) ذخیره شد.")
                    else:
                        await message.edit_text("⚠️ خطا در دانلود فایل.")
                else:
                    text_to_save = rm.text or ""
                    await client.send_message("me", f"👤 فرستنده: {sender_name}\n\n{text_to_save}")
                    await message.edit_text("✅ متن در پیام‌های ذخیره‌شده ذخیره شد.")
            except Exception as e:
                await message.edit_text(f"⚠️ خطا در ذخیره: {e}")
            
            await asyncio.sleep(2)
            try: await message.delete()
            except: pass
        
        elif cmd == "بن":
            if message.chat.type in [ChatType.GROUP, ChatType.SUPERGROUP] and tid:
                await client.ban_chat_member(message.chat.id, tid)
                await message.edit_text("🚫 کاربر بن شد.")
        
        elif cmd == "پین":
            await message.reply_to_message.pin()
            await message.edit_text("📌 پیام پین شد.")
            
        elif cmd.startswith("تکرار "):
            try:
                c = int(cmd.split()[1])
                await message.delete()
                for _ in range(min(c, 50)): 
                    await message.reply_to_message.copy(message.chat.id)
                    await asyncio.sleep(0.5)
            except: pass
            
        elif tid:
            if cmd == "بلاک روشن": 
                await client.block_user(tid)
                await message.edit_text("🚫 کاربر بلاک شد.")
            elif cmd == "بلاک خاموش": 
                await client.unblock_user(tid)
                await message.edit_text("⭕️ کاربر آنبلاک شد.")
            elif cmd == "سکوت روشن":
                s = MUTED_USERS.setdefault(uid, set())
                s.add((tid, message.chat.id))
                data_manager.update_user_data(uid, {"muted": [list(x) for x in s]})
                await message.edit_text("🔇 کاربر ساکت شد.")
            elif cmd == "سکوت خاموش":
                s = MUTED_USERS.get(uid, set())
                s.discard((tid, message.chat.id))
                data_manager.update_user_data(uid, {"muted": [list(x) for x in s]})
                await message.edit_text("🔊 سکوت کاربر لغو شد.")
            elif cmd.startswith("ریاکشن ") and cmd != "ریاکشن خاموش":
                t = AUTO_REACTION_TARGETS.setdefault(uid, {})
                t[str(tid)] = cmd.split()[1]
                data_manager.update_user_data(uid, {"reactions": t})
                await message.edit_text(f"👍 واکنش تنظیم شد.")
            elif cmd == "ریاکشن خاموش":
                t = AUTO_REACTION_TARGETS.get(uid, {})
                t.pop(str(tid), None)
                data_manager.update_user_data(uid, {"reactions": t})
                await message.edit_text("❌ واکنش حذف شد.")

async def tools_controller(client, message):
    cmd = message.text.strip()
    uid = client.me.id
    
    if cmd in ["تگ", "tagall"]:
        if message.chat.type in [ChatType.GROUP, ChatType.SUPERGROUP]:
            await message.delete()
            mems = []
            async for m in client.get_chat_members(message.chat.id, limit=100):
                if m.user and not m.user.is_bot and m.user.username:
                    mems.append(f'@{m.user.username}')
            for i in range(0, len(mems), 6):
                await client.send_message(message.chat.id, '\n'.join(mems[i:i+6]))
                await asyncio.sleep(1)
                
    elif cmd in ["تگ ادمین ها"]:
        if message.chat.type in [ChatType.GROUP, ChatType.SUPERGROUP]:
            await message.delete()
            ads = []
            async for m in client.get_chat_members(message.chat.id, filter=ChatMembersFilter.ADMINISTRATORS):
                if m.user and not m.user.is_bot and m.user.username:
                    ads.append(f'@{m.user.username}')
            for i in range(0, len(ads), 6):
                await client.send_message(message.chat.id, '⚡️ ادمین‌ها:\n' + '\n'.join(ads[i:i+6]))
                await asyncio.sleep(1)
                
    elif cmd == "آن پین":
        await client.unpin_chat_message(message.chat.id)
        await message.edit_text("📌 پیام آن‌پین شد.")
        
    elif cmd.startswith("اسپم "):
        try:
            parts = cmd.split(maxsplit=2)
            txt, c = parts[1], int(parts[2])
            await message.delete()
            for _ in range(min(c, 50)):
                await client.send_message(message.chat.id, txt)
                await asyncio.sleep(0.5)
        except: await message.edit_text("⚠️ فرمت: اسپم [متن] [تعداد]")
        
    elif cmd.startswith("فلود "):
        try:
            parts = cmd.split(maxsplit=2)
            txt, c = parts[1], int(parts[2])
            await message.delete()
            await client.send_message(message.chat.id, (txt + "\n") * min(c, 50))
        except: await message.edit_text("⚠️ فرمت: فلود [متن] [تعداد]")

    elif cmd.startswith("حذف"):
        try:
            if cmd == "حذف همه": c = 1000
            else: c = int(cmd.split()[1])
            await message.delete()
            del_list = []
            async for msg in client.get_chat_history(message.chat.id, limit=min(c*3, 1000)):
                if msg.from_user and msg.from_user.id == uid:
                    del_list.append(msg.id)
                    if len(del_list) >= c: break
            if del_list:
                await client.delete_messages(message.chat.id, del_list)
        except: pass

async def chat_tracker_handler(client, message):
    try:
        uid = client.me.id
        if getattr(message, "chat", None) and message.chat.id:
            dq = RECENT_CHATS.setdefault(uid, [])
            cid = message.chat.id
            if cid in dq: dq.remove(cid)
            dq.append(cid)
            if len(dq) > 20: del dq[:-20]
    except Exception: pass

async def ping_controller(client, message):
    try:
        start = time.perf_counter()
        m = await message.edit_text("pong...")
        ms = int((time.perf_counter() - start) * 1000)
        await m.edit_text(f"pong `{ms}ms`")
    except Exception: pass

async def panel_command_controller(client, message):
    try:
        results = await client.get_inline_bot_results(manager_bot.me.username, "panel")
        if results and results.results:
            await message.delete()
            await client.send_inline_bot_result(message.chat.id, results.query_id, results.results[0].id)
    except ChatSendInlineForbidden: await message.edit_text("🚫 اینلاین در این چت مسدود است.")
    except Exception as e: await message.edit_text(f"❌ خطا: {e}")

async def pv_media_lock_handler(client, message):
    uid = client.me.id
    if not message.chat or message.chat.type != ChatType.PRIVATE: return
    if message.from_user and message.from_user.id == uid: return
    if PV_LOCK_STATUS.get(uid, False):
        try: await message.delete(); return
        except: return

    should_delete = False
    
    if getattr(message, "photo", None) and PV_PHOTO_LOCK.get(uid, False): should_delete = True
    elif getattr(message, "video", None) and PV_VIDEO_LOCK.get(uid, False): should_delete = True
    elif getattr(message, "animation", None) and PV_GIF_LOCK.get(uid, False): should_delete = True
    elif getattr(message, "voice", None) and PV_VOICE_LOCK.get(uid, False): should_delete = True
    elif getattr(message, "audio", None) and PV_MUSIC_LOCK.get(uid, False): should_delete = True
    elif getattr(message, "sticker", None) and PV_STICKER_LOCK.get(uid, False): should_delete = True
    elif getattr(message, "document", None) and PV_DOC_LOCK.get(uid, False): should_delete = True

    if should_delete:
        try: await message.delete()
        except: pass

async def auto_save_view_once_handler(client, message):
    uid = client.me.id
    if not AUTO_SAVE_VIEW_ONCE.get(uid, False) or not message.media: return
    
    is_view_once = getattr(message, "has_media_spoiler", False) or getattr(message, "view_once", False)
    has_ttl = getattr(message, "ttl_seconds", None) or (message.photo and getattr(message.photo, "ttl_seconds", None)) or (message.video and getattr(message.video, "ttl_seconds", None))
    
    if is_view_once or has_ttl:
        try:
            f_path = await message.download()
            if f_path:
                cap = f"💾 **ذخیره خودکار مدیا**\nاز چت: {message.chat.id}\n{message.caption or ''}"
                if getattr(message, "photo", None): await client.send_photo("me", f_path, caption=cap)
                elif getattr(message, "video", None): await client.send_video("me", f_path, caption=cap)
                else: await client.send_document("me", f_path, caption=cap)
                os.remove(f_path)
        except: pass

# ============================================================
# 🔧 تابع تولید پنل شیشه‌ای (اصلاح شده بدون خطا)
# ============================================================

def generate_panel_markup(uid):
    def c(val): return "✅" if val else "❌"
    preview = stylize_time("12:34", USER_FONT_CHOICES.get(uid, 'stylized'))
    t_lang = AUTO_TRANSLATE_TARGET.get(uid)

    # متغیرهای وضعیت برای جلوگیری از خطای f-string
    clock_status = "روشن" if CLOCK_STATUS.get(uid, False) else "خاموش"
    bold_status = "روشن" if BOLD_MODE_STATUS.get(uid, False) else "خاموش"
    sec_status = "روشن" if SECRETARY_MODE_STATUS.get(uid, False) else "خاموش"
    seen_status = "روشن" if AUTO_SEEN_STATUS.get(uid, False) else "خاموش"
    typing_status = "روشن" if TYPING_MODE_STATUS.get(uid, False) else "خاموش"
    game_status = "روشن" if PLAYING_MODE_STATUS.get(uid, False) else "خاموش"
    autosave_status = "روشن" if AUTO_SAVE_VIEW_ONCE.get(uid, False) else "خاموش"
    antireport_status = "روشن" if ANTI_REPORT_STATUS.get(uid, True) else "خاموش"
    enemy_status = "روشن" if ENEMY_ACTIVE.get(uid, False) else "خاموش"
    friend_status = "روشن" if FRIEND_ACTIVE.get(uid, False) else "خاموش"
    crash_status = "روشن" if CRASH_ACTIVE.get(uid, False) else "خاموش"
    pvlock_status = "روشن" if PV_LOCK_STATUS.get(uid, False) else "خاموش"
    pvphoto_status = "روشن" if PV_PHOTO_LOCK.get(uid, False) else "خاموش"
    pvvid_status = "روشن" if PV_VIDEO_LOCK.get(uid, False) else "خاموش"
    pvgif_status = "روشن" if PV_GIF_LOCK.get(uid, False) else "خاموش"
    pvvoice_status = "روشن" if PV_VOICE_LOCK.get(uid, False) else "خاموش"
    pvmusic_status = "روشن" if PV_MUSIC_LOCK.get(uid, False) else "خاموش"
    pvsticker_status = "روشن" if PV_STICKER_LOCK.get(uid, False) else "خاموش"
    pvdoc_status = "روشن" if PV_DOC_LOCK.get(uid, False) else "خاموش"
    lang_en_status = "فعال" if t_lang == 'en' else "غیرفعال"
    lang_cn_status = "فعال" if t_lang == 'zh-CN' else "غیرفعال"

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(f"⏰ ساعت: {clock_status}", callback_data=f"tg_clock_{uid}"),
            InlineKeyboardButton(f"⚡ بولد: {bold_status}", callback_data=f"tg_bold_{uid}")
        ],
        [InlineKeyboardButton(f"🔤 تغییر فونت: {preview}", callback_data=f"cyc_font_{uid}")],
        [
            InlineKeyboardButton(f"🤖 منشی: {sec_status}", callback_data=f"tg_sec_{uid}"),
            InlineKeyboardButton(f"👁 سین: {seen_status}", callback_data=f"tg_seen_{uid}")
        ],
        [
            InlineKeyboardButton(f"⌨️ تایپ: {typing_status}", callback_data=f"tg_type_{uid}"),
            InlineKeyboardButton(f"🎮 بازی: {game_status}", callback_data=f"tg_game_{uid}")
        ],
        [InlineKeyboardButton(f"💾 ذخیره خودکار: {autosave_status}", callback_data=f"tg_autosv_{uid}")],
        [InlineKeyboardButton(f"🛡 ضد ریپ: {antireport_status}", callback_data=f"tg_antireport_{uid}")],
        [
            InlineKeyboardButton(f"💀 دشمن: {enemy_status}", callback_data=f"tg_enm_{uid}"),
            InlineKeyboardButton(f"🤝 دوست: {friend_status}", callback_data=f"tg_frnd_{uid}"),
            InlineKeyboardButton(f"❤️ کراش: {crash_status}", callback_data=f"tg_crsh_{uid}")
        ],
        [InlineKeyboardButton(f"🔒 قفل کل پیوی: {pvlock_status}", callback_data=f"tg_pv_{uid}")],
        [InlineKeyboardButton("🔻 قفل‌های رسانه پیوی 🔻", callback_data="none")],
        [
            InlineKeyboardButton(f"📷 عکس: {pvphoto_status}", callback_data=f"tg_pvph_{uid}"),
            InlineKeyboardButton(f"🎥 ویدیو: {pvvid_status}", callback_data=f"tg_pvvi_{uid}"),
            InlineKeyboardButton(f"🎞 گیف: {pvgif_status}", callback_data=f"tg_pvgi_{uid}")
        ],
        [
            InlineKeyboardButton(f"🎤 ویس: {pvvoice_status}", callback_data=f"tg_pvvo_{uid}"),
            InlineKeyboardButton(f"🎵 موزیک: {pvmusic_status}", callback_data=f"tg_pvmu_{uid}"),
            InlineKeyboardButton(f"🎨 استیکر: {pvsticker_status}", callback_data=f"tg_pvst_{uid}")
        ],
        [InlineKeyboardButton(f"📁 فایل: {pvdoc_status}", callback_data=f"tg_pvdc_{uid}")],
        [
            InlineKeyboardButton(f"🇺🇸 English: {lang_en_status}", callback_data=f"lang_en_{uid}"),
            InlineKeyboardButton(f"🇨🇳 Chinese: {lang_cn_status}", callback_data=f"lang_cn_{uid}")
        ],
        [InlineKeyboardButton("❌ بستن پنل", callback_data=f"close_{uid}")]
    ])

# ============================================================
# بقیه کد (ادمین، هندلرها، و ...)
# ============================================================

def generate_admins_markup():
    admins = data_manager.get_admins()
    buttons = []
    for adm in admins:
        name = f"Admin ({adm})"
        u_data = data_manager.data["users"].get(str(adm))
        if u_data and u_data.get("phone"):
            name = f"{u_data['phone']} | {adm}"
        buttons.append([InlineKeyboardButton(name, callback_data="none"), InlineKeyboardButton("حذف ❌", callback_data=f"del_admin_{adm}")])
    buttons.append([InlineKeyboardButton("➕ افزودن ادمین", callback_data="add_admin_prompt")])
    buttons.append([InlineKeyboardButton("بستن ✖️", callback_data="close_admin")])
    return InlineKeyboardMarkup(buttons)

def generate_users_markup(page=0):
    users = list(data_manager.get_all_users().values())
    total = len(users)
    pages = (total + 6) // 7
    start = page * 7
    end = start + 7
    current_users = users[start:end]
    
    buttons = []
    for u in current_users:
        uid = u["user_id"]
        phone = u.get("phone", "نامشخص")
        is_active = "✅" if uid in ACTIVE_BOTS else "❌"
        name = f"{phone} | {uid} {is_active}"
        buttons.append([
            InlineKeyboardButton(name, callback_data="none"), 
            InlineKeyboardButton("سیک 🗑", callback_data=f"kick_user_{uid}")
        ])
        
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️ قبلی", callback_data=f"users_page_{page-1}"))
    nav.append(InlineKeyboardButton(f"📄 {page+1}/{max(1, pages)}", callback_data="none"))
    if page < pages - 1:
        nav.append(InlineKeyboardButton("بعدی ➡️", callback_data=f"users_page_{page+1}"))
        
    if nav: buttons.append(nav)
    buttons.append([InlineKeyboardButton("بستن ✖️", callback_data="close_admin")])
    return InlineKeyboardMarkup(buttons)

# بررسی عضویت اجباری
async def check_forced_join(client, user_id):
    if user_id in data_manager.get_admins():
        return True, []
        
    settings = data_manager.get_global_settings()
    channels = settings.get("forced_channels", [])
    if not channels:
        return True, []
        
    not_joined = []
    for ch in channels:
        try:
            member = await client.get_chat_member(ch, user_id)
            if member.status in [ChatMembersFilter.BANNED, ChatMembersFilter.RESTRICTED]:
                not_joined.append(ch)
        except UserNotParticipant:
            not_joined.append(ch)
        except Exception as e:
            logging.error(f"Error checking forced join for {ch}: {e}")
            
    if not_joined:
        return False, not_joined
    return True, []

def get_forced_join_markup(channels):
    buttons = []
    for ch in channels:
        buttons.append([InlineKeyboardButton(f"ورود به {ch}", url=f"https://t.me/{ch.replace('@', '')}")])
    buttons.append([InlineKeyboardButton("🔄 بررسی مجدد عضویت", callback_data="check_join_status")])
    return InlineKeyboardMarkup(buttons)

@manager_bot.on_inline_query()
async def inline_panel_handler(client, query):
    uid = query.from_user.id
    if query.query == "panel":
        result = InlineQueryResultArticle(
            title="پنل مدیریت", 
            input_message_content=InputTextMessageContent(f"⚡️ **مدیریت پیشرفته سلف بات**\n👤 کاربر: `{uid}`\n\nوضعیت اتصال: ✅ برقرار"),
            reply_markup=generate_panel_markup(uid), 
            thumb_url="https://telegra.ph/file/1e3b567786f7800e80816.jpg"
        )
        await query.answer([result], cache_time=0)

@manager_bot.on_callback_query()
async def callback_panel_handler(client, callback):
    uid = callback.from_user.id
    data_str = callback.data

    # --- هندلرهای کلیدی مستقیم برای جلوگیری از ValueError ---
    if data_str == "set_ref_target":
        if uid not in data_manager.get_admins():
            return await callback.answer("⛔️ دسترسی فقط برای ادمین کل مجاز است!", show_alert=True)
        LOGIN_STATES[uid] = {"step": "awaiting_ref_target"}
        await callback.message.edit_text("🔢 لطفاً تعداد نفرات مورد نیاز برای دعوت را وارد کنید (مثلا 2):")
        return

    if data_str == "set_ref_days":
        if uid not in data_manager.get_admins():
            return await callback.answer("⛔️ دسترسی فقط برای ادمین کل مجاز است!", show_alert=True)
        LOGIN_STATES[uid] = {"step": "awaiting_ref_days"}
        await callback.message.edit_text("⏳ لطفاً تعداد روزهایی که در ازای دعوت هدیه داده میشود را وارد کنید (مثلا 5):")
        return

    if data_str == "add_forced_channel":
        if uid not in data_manager.get_admins():
            return await callback.answer("⛔️ دسترسی فقط برای ادمین کل مجاز است!", show_alert=True)
        LOGIN_STATES[uid] = {"step": "awaiting_forced_channel"}
        await callback.message.edit_text("📢 لطفاً یوزرنیم کانال یا گروه را با @ بفرستید:\n⚠️ توجه: حتما ربات باید در آنجا ادمین باشد تا بتواند اعضا را بررسی کند.")
        return

    if data_str == "check_join_status":
        is_joined, channels = await check_forced_join(client, uid)
        if is_joined:
            try: await callback.message.delete()
            except: pass
            await client.send_message(uid, "✅ عضویت شما تایید شد. مجدداً ربات را /start کنید.")
        else:
            await callback.answer("❌ هنوز در همه کانال‌ها عضو نشده‌اید!", show_alert=True)
        return

    if data_str == "get_ref_license_now":
        user_data = data_manager.get_user_data(uid)
        settings = data_manager.get_global_settings()
        target = settings.get("ref_target", 0)
        days = settings.get("ref_days", 0)
        
        if len(user_data.get("referrals", [])) >= target and target > 0:
            duration = days * 86400
            data_manager.apply_license_directly(uid, duration, "day")
            data_manager.clear_referrals(uid)
            await callback.message.edit_text(f"🎉 تبریک! لایسنس {days} روزه شما با موفقیت فعال شد.\nاکنون می‌توانید از دکمه '🔑 فعال‌سازی سلف' استفاده کنید.")
        else:
            await callback.answer("تعداد دعوت‌های شما هنوز به حد نصاب نرسیده است!", show_alert=True)
        return

    # پردازش دکمه‌های داینامیک و چند بخشی
    data = data_str.split("_")
    if data[0] == "none":
        return await callback.answer()

    if data[0] == "remove" and data[1] == "channel":
        if uid not in data_manager.get_admins(): return
        ch_to_remove = data_str.replace("remove_channel_", "")
        settings = data_manager.get_global_settings()
        chs = settings.get("forced_channels", [])
        if ch_to_remove in chs:
            chs.remove(ch_to_remove)
            data_manager.update_global_settings("forced_channels", chs)
            await callback.answer(f"کانال {ch_to_remove} حذف شد.", show_alert=True)
            try: await callback.message.edit_text("✅ کانال با موفقیت حذف شد.")
            except: pass
        return

    if data[0] == "add" and data[1] == "admin":
        LOGIN_STATES[uid] = {"step": "awaiting_admin_id"}
        await callback.message.edit_text("لطفاً آیدی عددی ادمین جدید را وارد کنید:")
        return
        
    if data[0] == "del" and data[1] == "admin":
        adm_id = int(data[2])
        if adm_id == ROOT_ADMIN:
            return await callback.answer("شما نمی‌توانید ادمین اصلی را حذف کنید!", show_alert=True)
        if data_manager.remove_admin(adm_id):
            await callback.answer(f"ادمین {adm_id} حذف شد.", show_alert=True)
            if not data_manager.check_subscription(adm_id):
                await stop_user_bot(adm_id)
            try: await callback.message.edit_reply_markup(reply_markup=generate_admins_markup())
            except: pass
        return
        
    if data[0] == "users" and data[1] == "page":
        page = int(data[2])
        try: await callback.message.edit_reply_markup(reply_markup=generate_users_markup(page))
        except: pass
        return
        
    if data[0] == "kick" and data[1] == "user":
        target_uid = int(data[2])
        await stop_user_bot(target_uid)
        data_manager.delete_user_full(target_uid)
        await callback.answer("کاربر کاملاً از سیستم حذف شد (سیک شد)!", show_alert=True)
        try: await callback.message.edit_reply_markup(reply_markup=generate_users_markup(0))
        except: pass
        return
        
    if data[0] == "close" and len(data) == 2 and data[1] == "admin":
        await callback.message.delete()
        return

    if data[0] == "create" and data[1] == "lic":
        LOGIN_STATES[uid] = {"step": "awaiting_duration", "unit": data[2]}
        await callback.message.edit_text("🔢 لطفاً زمان را به عدد وارد کنید:")
        return

    # پردازش اکشن‌های پنل کاربری سلف بات (ایمن شده با بلوک try-except)
    try:
        action, target_user_id = "_".join(data[:-1]), int(data[-1])
    except ValueError:
        # ساختار دکمه با آیدی کاربر همخوانی ندارد؛ با موفقیت نادیده گرفته می‌شود.
        return

    if uid != target_user_id:
        return await callback.answer("⛔️ دسترسی غیرمجاز!", show_alert=True)

    s_up = {}
    if action == "tg_clock":
        s_up["clock"] = CLOCK_STATUS[target_user_id] = not CLOCK_STATUS.get(target_user_id, False)
        s_up["clock_manual"] = True
        client_bot = ACTIVE_BOTS.get(target_user_id, [None])[0]
        if s_up["clock"]:
            if client_bot: asyncio.create_task(perform_clock_update_now(client_bot, target_user_id))
        else:
            if client_bot:
                try:
                    me = await client_bot.get_me()
                    clean = re.sub(r'(?:\s*' + CLOCK_CHARS_REGEX_CLASS + r'+)+$', '', me.first_name or "").strip()
                    if clean != me.first_name: await client_bot.update_profile(first_name=clean)
                except: pass

    elif action == "cyc_font":
        cur = USER_FONT_CHOICES.get(target_user_id, 'stylized')
        new_f = FONT_KEYS_ORDER[(FONT_KEYS_ORDER.index(cur) + 1) % len(FONT_KEYS_ORDER)]
        s_up["font"] = USER_FONT_CHOICES[target_user_id] = new_f
        if CLOCK_STATUS.get(target_user_id, False) and target_user_id in ACTIVE_BOTS:
            asyncio.create_task(perform_clock_update_now(ACTIVE_BOTS[target_user_id][0], target_user_id))
    
    elif action == "tg_bold": s_up["bold"] = BOLD_MODE_STATUS[target_user_id] = not BOLD_MODE_STATUS.get(target_user_id, False)
    
    elif action == "tg_sec":
        s_up["secretary"] = SECRETARY_MODE_STATUS[target_user_id] = not SECRETARY_MODE_STATUS.get(target_user_id, False)
        if s_up["secretary"]:
            USERS_REPLIED_IN_SECRETARY[target_user_id] = set()
            try:
                for k in list(SECRETARY_LAST_REPLY.keys()):
                    if isinstance(k, tuple) and k and k[0] == target_user_id:
                        SECRETARY_LAST_REPLY.pop(k, None)
            except Exception: pass
            data_manager.update_user_data(target_user_id, {"replied_users": []})
            
    elif action == "tg_antireport": s_up["anti_report"] = ANTI_REPORT_STATUS[target_user_id] = not ANTI_REPORT_STATUS.get(target_user_id, True)
    elif action == "tg_seen": s_up["auto_seen"] = AUTO_SEEN_STATUS[target_user_id] = not AUTO_SEEN_STATUS.get(target_user_id, False)
    elif action == "tg_type": s_up["typing"] = TYPING_MODE_STATUS[target_user_id] = not TYPING_MODE_STATUS.get(target_user_id, False)
    elif action == "tg_game": s_up["playing"] = PLAYING_MODE_STATUS[target_user_id] = not PLAYING_MODE_STATUS.get(target_user_id, False)
    
    elif action == "tg_autosv": s_up["auto_save"] = AUTO_SAVE_VIEW_ONCE[target_user_id] = not AUTO_SAVE_VIEW_ONCE.get(target_user_id, False)
    
    elif action == "tg_enm": s_up["enemy_active"] = ENEMY_ACTIVE[target_user_id] = not ENEMY_ACTIVE.get(target_user_id, False)
    elif action == "tg_frnd": s_up["friend_active"] = FRIEND_ACTIVE[target_user_id] = not FRIEND_ACTIVE.get(target_user_id, False)
    elif action == "tg_crsh": s_up["crash_active"] = CRASH_ACTIVE[target_user_id] = not CRASH_ACTIVE.get(target_user_id, False)
    
    elif action == "tg_pv": s_up["pv_lock"] = PV_LOCK_STATUS[target_user_id] = not PV_LOCK_STATUS.get(target_user_id, False)
    elif action == "tg_pvph": s_up["pv_photo"] = PV_PHOTO_LOCK[target_user_id] = not PV_PHOTO_LOCK.get(target_user_id, False)
    elif action == "tg_pvvi": s_up["pv_video"] = PV_VIDEO_LOCK[target_user_id] = not PV_VIDEO_LOCK.get(target_user_id, False)
    elif action == "tg_pvgi": s_up["pv_gif"] = PV_GIF_LOCK[target_user_id] = not PV_GIF_LOCK.get(target_user_id, False)
    elif action == "tg_pvvo": s_up["pv_voice"] = PV_VOICE_LOCK[target_user_id] = not PV_VOICE_LOCK.get(target_user_id, False)
    elif action == "tg_pvmu": s_up["pv_music"] = PV_MUSIC_LOCK[target_user_id] = not PV_MUSIC_LOCK.get(target_user_id, False)
    elif action == "tg_pvst": s_up["pv_sticker"] = PV_STICKER_LOCK[target_user_id] = not PV_STICKER_LOCK.get(target_user_id, False)
    elif action == "tg_pvdc": s_up["pv_doc"] = PV_DOC_LOCK[target_user_id] = not PV_DOC_LOCK.get(target_user_id, False)
    
    elif action.startswith("lang_"):
        l_code = action.split("_")[1]
        t_lang_map = {"en": "en", "ru": "ru", "cn": "zh-CN"}
        t_target = t_lang_map.get(l_code)
        if AUTO_TRANSLATE_TARGET.get(target_user_id) == t_target:
            s_up["translate"] = AUTO_TRANSLATE_TARGET[target_user_id] = None
        else:
            s_up["translate"] = AUTO_TRANSLATE_TARGET[target_user_id] = t_target

    elif action == "close":
        try:
            if callback.inline_message_id: await client.edit_inline_text(callback.inline_message_id, "✅ پنل بسته شد.")
            else: await callback.message.delete()
        except: pass
        try: await callback.answer()
        except: pass
        return

    if s_up: data_manager.update_user_data(target_user_id, {"settings": s_up})
    
    try: 
        if callback.inline_message_id:
            await client.edit_inline_reply_markup(callback.inline_message_id, reply_markup=generate_panel_markup(target_user_id))
        else:
            await callback.edit_message_reply_markup(reply_markup=generate_panel_markup(target_user_id))
    except: pass
    
    try: await callback.answer()
    except: pass

@manager_bot.on_message(filters.command("start") | filters.regex("🔑 فعال‌سازی سلف"))
async def start_handler(client, message):
    uid = message.from_user.id
    
    # بررسی زیرمجموعه گیری در دستور استارت
    if message.text and message.text.startswith("/start "):
        parts = message.text.split()
        if len(parts) > 1 and parts[1].startswith("ref_"):
            try:
                referrer_id = int(parts[1].split("_")[1])
                if referrer_id != uid:
                    data_manager.add_referral(referrer_id, uid)
            except: pass

    # بررسی عضویت اجباری
    is_joined, req_channels = await check_forced_join(client, uid)
    if not is_joined:
        return await message.reply_text(
            "⚠️ **برای استفاده از ربات، ابتدا باید در کانال‌های زیر عضو شوید:**",
            reply_markup=get_forced_join_markup(req_channels)
        )

    if uid in data_manager.get_admins() and (message.text == "/start" or not message.text):
        kb = ReplyKeyboardMarkup([
            [KeyboardButton("🔑 فعال‌سازی سلف"), KeyboardButton("📝 ساخت اشتراک")],
            [KeyboardButton("👑 مدیریت ادمین‌ها"), KeyboardButton("👥 مدیریت کاربران")],
            [KeyboardButton("📢 پیام همگانی"), KeyboardButton("⏳ وضعیت")],
            [KeyboardButton("🎁 تنظیمات سلف رایگان"), KeyboardButton("📢 عضویت اجباری")]
        ], resize_keyboard=True)
        return await message.reply_text("👋 ادمین عزیز، به پنل مدیریت کل خوش آمدید.", reply_markup=kb)
    
    if not data_manager.check_subscription(uid):
        LOGIN_STATES[uid] = {'step': 'awaiting_license'}
        kb = ReplyKeyboardMarkup([
            [KeyboardButton("🔑 فعال‌سازی سلف"), KeyboardButton("🎁 سلف رایگان")],
            [KeyboardButton("⏳ وضعیت")]
        ], resize_keyboard=True)
        return await message.reply_text("⛔️ شما اشتراک فعال ندارید. کد لایسنس خود را ارسال کنید یا از بخش 'سلف رایگان' اقدام کنید:", reply_markup=kb)

    if message.text and message.text.startswith("/start"):
        kb = ReplyKeyboardMarkup([
            [KeyboardButton("🔑 فعال‌سازی سلف"), KeyboardButton("🎁 سلف رایگان")],
            [KeyboardButton("⏳ وضعیت")]
        ], resize_keyboard=True)
        await message.reply_text("👋 اشتراک شما فعال است.", reply_markup=kb)
    else:
        await message.reply_text("🚀 اتصال به اکانت تلگرام:", reply_markup=ReplyKeyboardMarkup([[KeyboardButton("📱 ارسال شماره", request_contact=True)]], resize_keyboard=True, one_time_keyboard=True))

@manager_bot.on_message(filters.regex("📝 ساخت اشتراک"))
async def admin_create_license(client, message):
    if message.from_user.id not in data_manager.get_admins(): return
    await message.reply_text("⏳ نوع زمان:", reply_markup=InlineKeyboardMarkup([
        [InlineKeyboardButton("دقیقه", callback_data=f"create_lic_min_{message.from_user.id}"),
         InlineKeyboardButton("ساعت", callback_data=f"create_lic_hour_{message.from_user.id}"),
         InlineKeyboardButton("روز", callback_data=f"create_lic_day_{message.from_user.id}")]
    ]))

@manager_bot.on_message(filters.regex("👑 مدیریت ادمین‌ها"))
async def admin_management(client, message):
    if message.from_user.id not in data_manager.get_admins(): return
    await message.reply_text("👑 مدیریت ادمین‌های ربات:", reply_markup=generate_admins_markup())

@manager_bot.on_message(filters.regex("👥 مدیریت کاربران"))
async def user_management(client, message):
    if message.from_user.id not in data_manager.get_admins(): return
    total = len(data_manager.get_all_users())
    await message.reply_text(f"👥 تعداد کل کاربران متصل: {total}\n\nبرای حذف (سیک) از دکمه‌های زیر استفاده کنید:", reply_markup=generate_users_markup(0))

@manager_bot.on_message(filters.regex("📢 پیام همگانی"))
async def broadcast_msg(client, message):
    if message.from_user.id not in data_manager.get_admins(): return
    LOGIN_STATES[message.from_user.id] = {"step": "awaiting_broadcast"}
    await message.reply_text("لطفاً متنی که می‌خواهید برای تمام کاربران ربات ارسال شود را بفرستید:")

@manager_bot.on_message(filters.regex("🎁 تنظیمات سلف رایگان"))
async def admin_free_self_settings(client, message):
    if message.from_user.id not in data_manager.get_admins(): return
    settings = data_manager.get_global_settings()
    text = (
        "🎁 **تنظیمات سلف رایگان (زیرمجموعه‌گیری)**\n\n"
        f"🎯 تعداد دعوت مورد نیاز: `{settings.get('ref_target', 0)} نفر`\n"
        f"⏳ مدت زمان هدیه: `{settings.get('ref_days', 0)} روز`\n\n"
        "برای تغییر مقادیر دکمه‌های زیر را بزنید:"
    )
    
    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("تغییر تعداد دعوت", callback_data="set_ref_target"),
         InlineKeyboardButton("تغییر روز هدیه", callback_data="set_ref_days")]
    ])
    await message.reply_text(text, reply_markup=markup)

@manager_bot.on_message(filters.regex("📢 عضویت اجباری"))
async def admin_forced_join(client, message):
    if message.from_user.id not in data_manager.get_admins(): return
    settings = data_manager.get_global_settings()
    channels = settings.get("forced_channels", [])
    
    if not channels:
        text = "📢 در حال حاضر هیچ کانالی برای عضویت اجباری تنظیم نشده است."
    else:
        text = "📢 **لیست کانال‌های عضویت اجباری:**\n(برای حذف روی دکمه زیر هرکدام کلیک کنید)"
        
    markup = []
    for ch in channels:
        markup.append([InlineKeyboardButton(f"حذف {ch}", callback_data=f"remove_channel_{ch}")])
        
    markup.append([InlineKeyboardButton("➕ افزودن کانال/گروه", callback_data="add_forced_channel")])
    
    await message.reply_text(text, reply_markup=InlineKeyboardMarkup(markup))

@manager_bot.on_message(filters.regex("🎁 سلف رایگان"))
async def user_free_self(client, message):
    uid = message.from_user.id
    is_joined, req_channels = await check_forced_join(client, uid)
    if not is_joined: return
    
    bot_me = await client.get_me()
    bot_username = bot_me.username
    
    settings = data_manager.get_global_settings()
    target = settings.get('ref_target', 0)
    days = settings.get('ref_days', 0)
    
    if target <= 0:
        return await message.reply_text("❌ سیستم سلف رایگان در حال حاضر غیرفعال است.")
        
    user_data = data_manager.get_user_data(uid)
    ref_count = len(user_data.get("referrals", []))
    
    link = f"https://t.me/{bot_username}?start=ref_{uid}"
    
    text = (
        "🎁 **دریافت سلف رایگان**\n\n"
        f"شما با دعوت از دوستان خود از طریق لینک زیر میتوانید `{days} روز` اشتراک رایگان دریافت کنید!\n\n"
        f"🔗 لینک اختصاصی شما:\n`{link}`\n\n"
        f"👥 تعداد دعوت شده توسط شما: `{ref_count} از {target}`\n"
    )
    
    markup = None
    if ref_count >= target:
        markup = InlineKeyboardMarkup([[InlineKeyboardButton("🎉 دریافت لایسنس", callback_data="get_ref_license_now")]])
        
    await message.reply_text(text, reply_markup=markup)

@manager_bot.on_message(filters.regex("⏳ وضعیت"))
async def status_handler(client, message):
    uid = message.from_user.id
    
    is_joined, _ = await check_forced_join(client, uid)
    if not is_joined: return

    is_admin = uid in data_manager.get_admins()
    
    if is_admin:
        total_users = len(data_manager.get_all_users())
        active_bots = len(ACTIVE_BOTS)
        total_subs = len(data_manager.data.get("subscriptions", {}))
        
        text = (
            "📊 **وضعیت سرور و ربات**\n\n"
            f"👥 کل کاربران دیتابیس: `{total_users}`\n"
            f"🟢 سلف‌های روشن (آنلاین): `{active_bots}`\n"
            f"🎟 اشتراک‌های فعال: `{total_subs}`\n"
            f"👑 تعداد ادمین‌ها: `{len(data_manager.get_admins())}`\n"
        )
        await message.reply_text(text)
    else:
        if not data_manager.check_subscription(uid):
            return await message.reply_text("❌ شما اشتراک فعالی ندارید.")
        
        sub = data_manager.data.get("subscriptions", {}).get(str(uid))
        is_active = "✅ روشن و متصل" if uid in ACTIVE_BOTS else "❌ خاموش"
        
        text = (
            "📊 **وضعیت اکانت شما**\n\n"
            f"🤖 وضعیت اتصال سلف: {is_active}\n"
        )
        if sub:
            exp_date = datetime.fromtimestamp(sub["expiry_time"], TEHRAN_TIMEZONE).strftime('%Y-%m-%d %H:%M:%S')
            text += f"⏳ تاریخ انقضا اشتراک: `{exp_date}`\n"
        
        await message.reply_text(text)

@manager_bot.on_message(filters.contact)
async def contact_handler(client, message):
    uid = message.chat.id
    if not data_manager.check_subscription(uid): return
    phone = message.contact.phone_number
    await message.reply_text("⏳ در حال اتصال...", reply_markup=ReplyKeyboardRemove())
    
    user_c = Client(f"login_{uid}", api_id=API_ID, api_hash=API_HASH, in_memory=True, no_updates=True)
    await user_c.connect()
    try:
        sent = await user_c.send_code(phone)
        LOGIN_STATES[uid] = {'step': 'code', 'phone': phone, 'client': user_c, 'hash': sent.phone_code_hash}
        await message.reply_text("✅ کد ارسالی را با فاصله وارد کنید (مثال: 1 2 3 4 5)")
    except Exception as e:
        await user_c.disconnect()
        await message.reply_text(f"❌ خطا: {e}")

@manager_bot.on_message(filters.text & filters.private & filters.create(lambda _, __, m: m.chat.id in LOGIN_STATES))
async def text_handler(client, message):
    uid = message.chat.id
    st = LOGIN_STATES[uid]
    
    if st['step'] == 'awaiting_broadcast':
        text_to_send = message.text
        del LOGIN_STATES[uid]
        await message.reply_text("⏳ در حال ارسال پیام همگانی...")
        count = 0
        for user_id in list(data_manager.get_all_users().keys()):
            try:
                await client.send_message(int(user_id), f"📢 پیام از مدیریت:\n\n{text_to_send}")
                count += 1
            except: pass
            await asyncio.sleep(0.1)
        await message.reply_text(f"✅ پیام برای {count} نفر با موفقیت ارسال شد.")
        return

    if st['step'] == 'awaiting_admin_id':
        if message.text.isdigit():
            if data_manager.add_admin(int(message.text)):
                await message.reply_text(f"✅ کاربر {message.text} به لیست ادمین‌ها اضافه شد.")
            else:
                await message.reply_text("ℹ️ این کاربر از قبل ادمین بود.")
        else:
            await message.reply_text("❌ آیدی باید عدد باشد.")
        del LOGIN_STATES[uid]
        return
        
    if st['step'] == 'awaiting_ref_target':
        if message.text.isdigit():
            data_manager.update_global_settings("ref_target", int(message.text))
            await message.reply_text("✅ تعداد هدف دعوت بروزرسانی شد.")
        else: await message.reply_text("❌ عدد وارد کنید.")
        del LOGIN_STATES[uid]
        return
        
    if st['step'] == 'awaiting_ref_days':
        if message.text.isdigit():
            data_manager.update_global_settings("ref_days", int(message.text))
            await message.reply_text("✅ تعداد روزهای هدیه بروزرسانی شد.")
        else: await message.reply_text("❌ عدد وارد کنید.")
        del LOGIN_STATES[uid]
        return
        
    if st['step'] == 'awaiting_forced_channel':
        ch = message.text.strip()
        if not ch.startswith("@"):
            await message.reply_text("❌ یوزرنیم باید با @ شروع شود.")
        else:
            chs = data_manager.get_global_settings().get("forced_channels", [])
            if ch not in chs:
                chs.append(ch)
                data_manager.update_global_settings("forced_channels", chs)
                await message.reply_text(f"✅ کانال {ch} به لیست عضویت اجباری اضافه شد.")
            else:
                await message.reply_text("ℹ️ این کانال از قبل وجود داشت.")
        del LOGIN_STATES[uid]
        return

    if st['step'] == 'awaiting_license':
        ok, msg = data_manager.use_license(uid, message.text.strip().upper())
        if ok:
            del LOGIN_STATES[uid]
            await message.reply_text(msg, reply_markup=ReplyKeyboardMarkup([
                [KeyboardButton("🔑 فعال‌سازی سلف"), KeyboardButton("🎁 سلف رایگان")],
                [KeyboardButton("⏳ وضعیت")]
            ], resize_keyboard=True))
        else: await message.reply_text(msg)
        return

    if st['step'] == 'awaiting_duration':
        if not message.text.isdigit(): return await message.reply_text("عدد بفرستید!")
        unit, am = st['unit'], int(message.text)
        sec = am * {"min": 60, "hour": 3600, "day": 86400}[unit]
        code = data_manager.create_license(sec, unit)
        await message.reply_text(f"✅ کد ساخته شد:\n`{code}`")
        del LOGIN_STATES[uid]
        return

    user_c = st.get('client')
    if not user_c: return

    if st['step'] == 'code':
        try:
            await user_c.sign_in(st['phone'], st['hash'], re.sub(r"\D+", "", message.text))
            await finalize_login(message, user_c, st['phone'])
        except SessionPasswordNeeded:
            st['step'] = 'password'
            await message.reply_text("🔐 رمز دو مرحله‌ای را وارد کنید:")
        except Exception as e: await message.reply_text(f"❌ {e}")
    
    elif st['step'] == 'password':
        try:
            await user_c.check_password(message.text)
            await finalize_login(message, user_c, st['phone'])
        except Exception as e: await message.reply_text(f"❌ {e}")

async def finalize_login(message, user_c, phone):
    s_str = await user_c.export_session_string()
    uid = (await user_c.get_me()).id
    await user_c.disconnect()
    data_manager.save_session(phone, s_str, uid)
    asyncio.create_task(start_bot_instance(s_str, phone, uid, 'stylized'))
    del LOGIN_STATES[message.chat.id]
    await message.reply_text("✅ اکانت فعال شد! دستور `پنل` را در اکانت اصلی خود بزنید.")

async def help_cmd_handler(client, message):
    try: await message.edit_text(HELP_TEXT)
    except: pass

async def start_bot_instance(session_string: str, phone: str, user_id: int, font_style: str = 'stylized'):
    if user_id in STARTING_BOTS:
        return
    STARTING_BOTS.add(user_id)
    try:
        now = time.time()
        last = SESSION_START_THROTTLE.get(user_id, 0)
        if last and now - last < 20:
            return
        SESSION_START_THROTTLE[user_id] = now
        await asyncio.sleep(random.uniform(0.2, 1.2))
        client = ResilientClient(
            f"bot_{user_id}", api_id=API_ID, api_hash=API_HASH,
            session_string=session_string, in_memory=True, no_updates=False
        )
        try:
            await asyncio.wait_for(client.start(), timeout=15)
        except (AuthKeyUnregistered, UserDeactivated, UserDeactivatedBan, PeerIdInvalid):
            data_manager.delete_session(phone)
            return
        except Exception as e:
            logging.warning(f"Startup failed for {user_id}: {e}")
            return

        if user_id in ACTIVE_BOTS:
            old_client, old_tasks = ACTIVE_BOTS.pop(user_id)
            for t in old_tasks:
                try: t.cancel()
                except Exception: pass
            try: await old_client.stop()
            except Exception: pass

        client.add_handler(MessageHandler(chat_tracker_handler, filters.all), group=-100)
        client.add_handler(MessageHandler(god_mode_handler, filters.incoming & ~filters.me), group=-10)
        client.add_handler(MessageHandler(pv_media_lock_handler, filters.private & ~filters.me), group=-6)
        client.add_handler(MessageHandler(auto_seen_handler, filters.private & ~filters.me), group=-4)
        client.add_handler(MessageHandler(incoming_message_manager, filters.all & ~filters.me), group=-3)
        client.add_handler(MessageHandler(auto_save_view_once_handler, filters.private & ~filters.me), group=-2)
        client.add_handler(MessageHandler(outgoing_message_modifier, filters.text & filters.me & ~filters.reply), group=-1)

        cmd_filter = filters.me & filters.text
        client.add_handler(MessageHandler(help_cmd_handler, cmd_filter & filters.regex("^راهنما$")), group=0)
        client.add_handler(MessageHandler(ping_controller, cmd_filter & filters.regex(r"^(ping|پینگ)$", re.I)), group=0)
        client.add_handler(MessageHandler(panel_command_controller, cmd_filter & filters.regex(r"^(پنل|panel)$")), group=0)
        client.add_handler(MessageHandler(set_secretary_message_controller, cmd_filter & filters.regex(r"^تنظیم متن منشی")), group=0)
        client.add_handler(MessageHandler(fun_controller, cmd_filter & filters.regex(r"^(fun|فان|heart|قلب|typing|تایپ|progress|پروگرس|wave|موج|pulse|ضربان|emptyheart|قلب خالی)", re.I)), group=0)
        client.add_handler(MessageHandler(list_management_controller, cmd_filter & filters.regex(r"^(تنظیم|حذف|لیست|پاکسازی لیست)(?:\sمتن)?\s(دشمن|دوست|کراش)", re.I)), group=0)
        client.add_handler(MessageHandler(reply_based_controller, cmd_filter & filters.regex(r"^(دانلود|بن|پین|حذف|ذخیره|تکرار|بلاک|سکوت|ریاکشن)")), group=0)
        client.add_handler(MessageHandler(tools_controller, cmd_filter & filters.regex(r"^(تگ|tagall|تگ ادمین ها|آن پین|اسپم|فلود|حذف)")), group=0)

        client.add_handler(MessageHandler(secretary_auto_reply_handler, filters.private & ~filters.me & ~filters.bot & ~filters.service), group=1)
        client.add_handler(MessageHandler(target_reply_handler, filters.incoming & ~filters.me & ~filters.bot & ~filters.service), group=2)

        tasks = [
            asyncio.create_task(update_profile_clock(client, user_id)),
            asyncio.create_task(anti_login_task(client, user_id)),
            asyncio.create_task(status_action_task(client, user_id))
        ]
        ACTIVE_BOTS[user_id] = (client, tasks)
        logging.info(f"Bot instance started for {user_id}")
    finally:
        STARTING_BOTS.discard(user_id)

async def memory_cleaner():
    while True:
        try:
            await asyncio.sleep(180)
            for uid, (client, tasks) in list(ACTIVE_BOTS.items()):
                ACTIVE_BOTS[uid] = (client, [t for t in tasks if not t.done()])
            gc.collect()
        except asyncio.CancelledError:
            break
        except Exception:
            await asyncio.sleep(60)

async def main():
    sem = asyncio.Semaphore(STARTUP_CONCURRENCY)
    sessions = list(data_manager.get_all_sessions())

    async def start_one(phone, s_data):
        async with sem:
            try:
                uid = int(s_data["user_id"])
                if data_manager.check_subscription(uid):
                    await start_bot_instance(s_data["string"], phone, uid, 'stylized')
                else:
                    data_manager.delete_user_full(uid)
            except Exception as e:
                logging.warning(f"Startup error for {phone}: {e}")

    try:
        await manager_bot.start()
    except Exception as e:
        logging.error(f"Manager bot start failed: {e}")
        return

    asyncio.create_task(data_manager.auto_save_loop())
    asyncio.create_task(subscription_monitor_task())
    asyncio.create_task(memory_cleaner())

    for phone, s_data in sessions:
        asyncio.create_task(start_one(phone, s_data))
        await asyncio.sleep(0.05)
    logging.info("Manager bot started; sessions are loading in background.")

    try:
        await idle()
    finally:
        try: data_manager.force_save_sync()
        except Exception: pass
        try:
            if HTTP_SESSION and not HTTP_SESSION.closed:
                await HTTP_SESSION.close()
        except Exception: pass
        for uid in list(ACTIVE_BOTS.keys()):
            try: await stop_user_bot(uid)
            except Exception: pass
        try: await manager_bot.stop()
        except Exception: pass

if __name__ == "__main__":
    try:
        asyncio.get_event_loop().run_until_complete(main())
    except KeyboardInterrupt:
        pass
