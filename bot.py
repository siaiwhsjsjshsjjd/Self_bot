import telebot

BOT_TOKEN = "8200221816:AAHN5J-iFXJoQ9mEFLcRBc3ZVDCv2cmrsxQ"  # از @BotFather بگیر

bot = telebot.TeleBot(BOT_TOKEN)

# شناسه استیکر پریمیوم (بدون فاصله)
STICKER_ID = "5931415565955503486"

@bot.message_handler(commands=['start'])
def send_welcome(message):
    # ارسال متن ساده (بدون فرمت)
    bot.send_message(message.chat.id, "سلف درحال ابدیته")
    # ارسال استیکر پریمیوم
    bot.send_sticker(message.chat.id, STICKER_ID)

print("ربات روشن شد!")
bot.infinity_polling()
