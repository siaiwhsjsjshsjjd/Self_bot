import telebot

BOT_TOKEN = "8200221816:AAHN5J-iFXJoQ9mEFLcRBc3ZVDCv2cmrsxQ"  # از @BotFather بگیر

bot = telebot.TeleBot(BOT_TOKEN)

STICKER_ID = "5931415565955503486"   # استیکر پریمیوم

@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.send_message(message.chat.id, "سلف درحال ابدیته")
    bot.send_sticker(message.chat.id, STICKER_ID)

print("ربات روشن شد و فقط به /start پاسخ می‌دهد.")
bot.infinity_polling()
