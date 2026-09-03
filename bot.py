import urllib.request
import urllib.parse
import json
import time

TOKEN = "8200221816:AAHN5J-iFXJoQ9mEFLcRBc3ZVDCv2cmrsxQ"
EMOJI_ID = "5931415565955503486"

API = f"https://api.telegram.org/bot{TOKEN}/"

def telegram(method, data):
    data = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(API + method, data=data)
    with urllib.request.urlopen(req, timeout=60) as response:
        return json.loads(response.read().decode())

offset = 0

while True:
    try:
        result = telegram("getUpdates", {
            "offset": offset,
            "timeout": 50
        })

        for update in result.get("result", []):
            offset = update["update_id"] + 1

            message = update.get("message")
            if not message:
                continue

            if message.get("text") == "/start":
                chat_id = message["chat"]["id"]

                text = "سلف درحال ابدیته 🥰"

                # محل ایموجی پریمیوم در متن
                emoji_offset = len(
                    "سلف درحال ابدیته ".encode("utf-16-le")
                ) // 2

                data = {
                    "chat_id": chat_id,
                    "text": text,
                    "entities": json.dumps([
                        {
                            "type": "custom_emoji",
                            "offset": emoji_offset,
                            "length": 2,
                            "custom_emoji_id": EMOJI_ID
                        }
                    ])
                }

                telegram("sendMessage", data)

    except Exception as e:
        print("Error:", e)
        time.sleep(3)
