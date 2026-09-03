from telegram import Update, MessageEntity
from telegram.ext import Application, CommandHandler, ContextTypes

TOKEN = "8200221816:AAHN5J-iFXJoQ9mEFLcRBc3ZVDCv2cmrsxQ"
CUSTOM_EMOJI_ID = "5931415565955503486"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = "سلف درحال ابدیته 🥰"

    entities = [
        MessageEntity(
            type="custom_emoji",
            offset=len("سلف درحال ابدیته ".encode("utf-16-le")) // 2,
            length=2,
            custom_emoji_id=CUSTOM_EMOJI_ID
        )
    ]

    await update.message.reply_text(
        text=text,
        entities=entities
    )

app = Application.builder().token(TOKEN).build()
app.add_handler(CommandHandler("start", start))

app.run_polling()
