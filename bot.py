import os
import yt_dlp
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

TOKEN = "8312461995:AAEWbinigBntWn8AHUbEmf-hXGvFUFUTYOc"


# /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Salom 👋\n\n"
        "Menga qo‘shiq nomi yoki YouTube link yubor 🎵"
    )


# YouTube qidirish
def search_youtube(query, limit=5):
    ydl_opts = {
        "quiet": True,
        "skip_download": True,
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        result = ydl.extract_info(f"ytsearch{limit}:{query}", download=False)
        videos = result.get("entries", [])
        return [(v["title"], v["webpage_url"]) for v in videos]


# Inline tugma
def create_keyboard(results):
    keyboard = []
    for title, url in results:
        keyboard.append([InlineKeyboardButton(title[:50], callback_data=url)])
    return InlineKeyboardMarkup(keyboard)


# Audio yuklash va yuborish
async def send_audio(chat_id, url, context):
    await context.bot.send_message(chat_id=chat_id, text="⏳ Yuklanmoqda...")

    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": "music.%(ext)s",
        "quiet": True,
        "noplaylist": True,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            title = info.get("title", "Musiqa")
    except Exception as e:
        await context.bot.send_message(chat_id=chat_id, text="❌ Yuklashda xatolik.")
        return

    # Yuklangan faylni topish
    for file in os.listdir():
        if file.startswith("music"):
            with open(file, "rb") as audio:
                await context.bot.send_audio(
                    chat_id=chat_id,
                    audio=audio,
                    title=title,
                    performer="YouTube",
                )
            os.remove(file)
            break


# Matn kelganda
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    chat_id = update.message.chat_id

    # Agar link bo‘lsa
    if "youtube.com" in text or "youtu.be" in text:
        await send_audio(chat_id, text, context)
        return

    # Aks holda qidirish
    try:
        results = search_youtube(text)
    except:
        await update.message.reply_text("❌ Hech narsa topilmadi.")
        return

    if not results:
        await update.message.reply_text("❌ Hech narsa topilmadi.")
        return

    keyboard = create_keyboard(results)
    await update.message.reply_text(
        "Quyidagilardan birini tanlang 👇",
        reply_markup=keyboard,
    )


# Tugma bosilganda
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    url = query.data
    chat_id = query.message.chat_id

    await send_audio(chat_id, url, context)


# Main
def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(CallbackQueryHandler(button_callback))

    print("Bot ishga tushdi ✅")
    app.run_polling()


if __name__ == "__main__":
    main()