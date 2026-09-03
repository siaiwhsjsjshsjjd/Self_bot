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


# =========================
# بررسی ربات
# =========================

me = telegram("getMe")

if not me.get("ok"):
    print("❌ توکن ربات اشتباه است")
    print(me)
    raise SystemExit

print("✅ ربات متصل شد")
print("Username:", me["result"].get("username"))


# =========================
# گرفتن اطلاعات Custom Emoji
# =========================

emoji_info = telegram(
    "getCustomEmojiStickers",
    {
        "custom_emoji_ids": json.dumps([CUSTOM_EMOJI_ID])
    }
)

if not emoji_info.get("ok"):
    print("❌ خطا در بررسی Custom Emoji")
    print(emoji_info)
    raise SystemExit

stickers = emoji_info.get("result", [])

if not stickers:
    print("❌ Custom Emoji پیدا نشد")
    raise SystemExit

sticker = stickers[0]

REAL_EMOJI = sticker.get("emoji")

print("✅ Custom Emoji پیدا شد")
print("ID:", sticker.get("custom_emoji_id"))
print("Emoji جایگزین:", REAL_EMOJI)
print("Animated:", sticker.get("is_animated"))
print("Video:", sticker.get("is_video"))


# =========================
# حذف Webhook
# =========================

try:
    print(
        "Webhook:",
        telegram(
            "deleteWebhook",
            {"drop_pending_updates": "true"}
        )
    )
except Exception as e:
    print("Webhook error:", e)


# =========================
# شروع ربات
# =========================

print("✅ ربات آماده است")
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

            # همان ایموجی واقعی که متعلق به Custom Emoji است
            text = "سلف درحال ابدیته " + REAL_EMOJI

            # offset ایموجی در UTF-16
            emoji_offset = len(
                "سلف درحال ابدیته ".encode("utf-16-le")
            ) // 2

            emoji_length = len(
                REAL_EMOJI.encode("utf-16-le")
            ) // 2

            entities = [
                {
                    "type": "custom_emoji",
                    "offset": emoji_offset,
                    "length": emoji_length,
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

                sent = result["result"]

                print("✅ پیام ارسال شد")

                print(
                    "Entities:",
                    sent.get("entities")
                )

            else:

                print("❌ ارسال ناموفق:")
                print(result)

    except urllib.error.HTTPError as e:

        if e.code == 409:

            print("⚠️ 409 Conflict")
            print("یک اجرای دیگر همین Bot Token فعال است.")

            time.sleep(10)

        else:

            print("❌ HTTP Error:", e)
            time.sleep(5)

    except Exception as e:

        print("❌ Error:", repr(e))
        time.sleep(5)
