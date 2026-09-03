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


# حذف Webhook قبلی تا با polling تداخل نداشته باشد
try:
    result = telegram("deleteWebhook", {"drop_pending_updates": True})
    print("Webhook:", result)
except Exception as e:
    print("Webhook error:", e)


offset = 0

while True:
    try:
        result = telegram("getUpdates", {
            "offset": offset,
            "timeout": 50
        })

        if not result.get("ok"):
            print("Telegram error:", result)
            time.sleep(3)
            continue

        for update in result.get("result", []):
            offset = update["update_id"] + 1

            message = update.get("message")
            if not message:
                continue

            if message.get("text") != "/start":
                continue

            chat_id = message["chat"]["id"]

            text = "سلف درحال ابدیته 🥰"

            # offset و length بر اساس UTF-16 هستند
            emoji_offset = len(
                "سلف درحال ابدیته ".encode("utf-16-le")
            ) // 2

            entities = [{
                "type": "custom_emoji",
                "offset": emoji_offset,
                "length": 2,
                "custom_emoji_id": CUSTOM_EMOJI_ID
            }]

            response = telegram("sendMessage", {
                "chat_id": chat_id,
                "text": text,
                "entities": json.dumps(entities)
            })

            print("Send result:", response)

    except Exception as e:
        print("ERROR:", repr(e))
        time.sleep(3)
