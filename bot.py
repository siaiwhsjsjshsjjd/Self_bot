import urllib.request
import urllib.parse
import json
import time

TOKEN = "8200221816:AAHN5J-iFXJoQ9mEFLcRBc3ZVDCv2cmrsxQ"

CUSTOM_EMOJI_ID = "5931415565955503486"

API = f"https://api.telegram.org/bot{TOKEN}/"


def telegram(method, data=None):
    if data is None:
        data = {}

    encoded = urllib.parse.urlencode(data).encode("utf-8")
    request = urllib.request.Request(API + method, data=encoded)

    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


# -------------------------
# 1. بررسی اتصال به ربات
# -------------------------

try:
    me = telegram("getMe")

    if not me.get("ok"):
        print("❌ توکن ربات مشکل دارد:")
        print(me)
        raise SystemExit

    print("✅ ربات متصل است:")
    print("@", me["result"].get("username"))

except Exception as e:
    print("❌ خطا در اتصال به Telegram:", e)
    raise SystemExit


# -------------------------
# 2. بررسی Custom Emoji
# -------------------------

try:
    emoji_result = telegram(
        "getCustomEmojiStickers",
        {
            "custom_emoji_ids": json.dumps([CUSTOM_EMOJI_ID])
        }
    )

    if not emoji_result.get("ok"):
        print("❌ Telegram این Custom Emoji را قبول نکرد:")
        print(emoji_result)
        raise SystemExit

    stickers = emoji_result.get("result", [])

    if not stickers:
        print("❌ این Custom Emoji پیدا نشد:")
        print(CUSTOM_EMOJI_ID)
        raise SystemExit

    emoji = stickers[0]

    print("✅ Custom Emoji سالم است")
    print("ID:", emoji.get("custom_emoji_id"))
    print("Type:", emoji.get("type"))
    print("Animated:", emoji.get("is_animated"))
    print("Video:", emoji.get("is_video"))


except Exception as e:
    print("❌ خطا در بررسی Custom Emoji:", e)
    raise SystemExit


# -------------------------
# 3. حذف Webhook
# -------------------------

try:
    result = telegram(
        "deleteWebhook",
        {
            "drop_pending_updates": "true"
        }
    )

    print("Webhook:", result)

except Exception as e:
    print("❌ خطا در حذف Webhook:", e)


# -------------------------
# 4. شروع ربات
# -------------------------

print("✅ ربات آماده است.")
print("منتظر /start ...")

offset = 0

while True:

    try:

        updates = telegram(
            "getUpdates",
            {
                "offset": offset,
                "timeout": 50
            }
        )

        if not updates.get("ok"):
            print("❌ Telegram error:", updates)
            time.sleep(5)
            continue

        for update in updates.get("result", []):

            offset = update["update_id"] + 1

            message = update.get("message")

            if not message:
                continue

            if message.get("text") != "/start":
                continue

            chat_id = message["chat"]["id"]

            # یک کاراکتر جای ایموجی قرار می‌دهیم
            text = "سلف درحال ابدیته 🥰"

            # Telegram برای entity از UTF-16 offset استفاده می‌کند
            emoji_offset = len(
                "سلف درحال ابدیته ".encode("utf-16-le")
            ) // 2

            entities = [
                {
                    "type": "custom_emoji",
                    "offset": emoji_offset,
                    "length": 2,
                    "custom_emoji_id": CUSTOM_EMOJI_ID
                }
            ]

            result = telegram(
                "sendMessage",
                {
                    "chat_id": chat_id,
                    "text": text,
                    "entities": json.dumps(entities)
                }
            )

            if result.get("ok"):
                print("✅ پیام با Custom Emoji ارسال شد.")
            else:
                print("❌ ارسال پیام ناموفق:")
                print(result)

    except urllib.error.HTTPError as e:

        if e.code == 409:
            print("⚠️ خطای 409 Conflict")
            print("یک اجرای دیگر از همین ربات هنوز فعال است.")
            print("اجرای اضافی ربات را خاموش کنید.")
            time.sleep(10)

        else:
            print("❌ HTTP Error:", e)
            time.sleep(5)

    except Exception as e:

        print("❌ Error:", repr(e))
        time.sleep(5)
