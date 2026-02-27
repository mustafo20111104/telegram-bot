import os
import json
import asyncio
import yt_dlp
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

TOKEN = "8312461995:AAEWbinigBntWn8AHUbEmf-hXGvFUFUTYOc"

# ─── Ma'lumotlar bazasi (JSON fayl) ───────────────────────────────────────────
DB_FILE = "/tmp/users.json"

def load_db():
    if os.path.exists(DB_FILE):
        with open(DB_FILE, "r") as f:
            return json.load(f)
    return {}

def save_db(db):
    with open(DB_FILE, "w") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)

def get_user(db, user_id):
    uid = str(user_id)
    if uid not in db:
        db[uid] = {
            "favorites": [],
            "history": [],
            "settings": {"quality": "best", "results": 5},
            "downloads": 0,
        }
    return db[uid]

# ─── TOP qo'shiqlar (global hisoblagich) ─────────────────────────────────────
TOP_FILE = "/tmp/top.json"

def load_top():
    if os.path.exists(TOP_FILE):
        with open(TOP_FILE, "r") as f:
            return json.load(f)
    return {}

def save_top(top):
    with open(TOP_FILE, "w") as f:
        json.dump(top, f, ensure_ascii=False, indent=2)

def increment_top(title, url):
    top = load_top()
    key = url
    if key not in top:
        top[key] = {"title": title, "count": 0, "url": url}
    top[key]["count"] += 1
    save_top(top)

# ─── YouTube qidirish ─────────────────────────────────────────────────────────
def search_youtube(query, limit=5):
    ydl_opts = {
        "quiet": True,
        "skip_download": True,
        "extract_flat": True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        result = ydl.extract_info(f"ytsearch{limit}:{query}", download=False)
        videos = result.get("entries", [])
        results = []
        for v in videos:
            if v:
                duration = v.get("duration", 0)
                mins = duration // 60 if duration else 0
                secs = duration % 60 if duration else 0
                results.append({
                    "title": v.get("title", "Noma'lum"),
                    "url": f"https://youtube.com/watch?v={v.get('id', '')}",
                    "duration": f"{mins}:{secs:02d}" if duration else "?",
                    "channel": v.get("uploader", ""),
                })
        return results

# ─── Audio yuklash ────────────────────────────────────────────────────────────
async def send_audio(chat_id, url, title, context, user_id=None):
    msg = await context.bot.send_message(
        chat_id=chat_id,
        text=f"⏳ *{title}* yuklanmoqda...",
        parse_mode="Markdown"
    )

    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": f"/tmp/music_{chat_id}.%(ext)s",
        "quiet": True,
        "noplaylist": True,
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "192",
        }],
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            real_title = info.get("title", title)
            artist = info.get("uploader", "YouTube")
            thumb = info.get("thumbnail", None)
    except Exception as e:
        await msg.edit_text("❌ Yuklashda xatolik yuz berdi.")
        return

    # Faylni yuborish
    filepath = f"/tmp/music_{chat_id}.mp3"
    if os.path.exists(filepath):
        # Top hisoblagich
        increment_top(real_title, url)

        # Foydalanuvchi statistikasi
        if user_id:
            db = load_db()
            user = get_user(db, user_id)
            user["downloads"] += 1
            # Tarix
            history_item = {"title": real_title, "url": url}
            if history_item not in user["history"]:
                user["history"].insert(0, history_item)
                user["history"] = user["history"][:10]  # oxirgi 10 ta
            save_db(db)

        # Sevimliga qo'shish tugmasi
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("❤️ Sevimlilarga qo'sh", callback_data=f"fav|{url}|{real_title[:40]}"),
            InlineKeyboardButton("🔄 Yana yukla", callback_data=f"dl|{url}|{real_title[:40]}"),
        ]])

        with open(filepath, "rb") as audio:
            await context.bot.send_audio(
                chat_id=chat_id,
                audio=audio,
                title=real_title,
                performer=artist,
                reply_markup=keyboard,
            )
        os.remove(filepath)
        await msg.delete()
    else:
        await msg.edit_text("❌ Fayl topilmadi.")

# ─── /start ───────────────────────────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔍 Qidirish", switch_inline_query_current_chat=""),
         InlineKeyboardButton("❤️ Sevimlilar", callback_data="my_favorites")],
        [InlineKeyboardButton("📊 Top 10", callback_data="top10"),
         InlineKeyboardButton("📜 Tarix", callback_data="history")],
        [InlineKeyboardButton("⚙️ Sozlamalar", callback_data="settings"),
         InlineKeyboardButton("ℹ️ Yordam", callback_data="help")],
    ])
    await update.message.reply_text(
        f"🎵 *Xush kelibsiz, {user.first_name}!*\n\n"
        "Men sizga YouTube'dan musiqa topib beraman!\n\n"
        "🔍 Qo'shiq nomi yoki artist yozing\n"
        "🔗 Yoki YouTube link yuboring\n\n"
        "Quyidagi tugmalardan foydalaning 👇",
        parse_mode="Markdown",
        reply_markup=keyboard
    )

# ─── /help ────────────────────────────────────────────────────────────────────
async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 *Buyruqlar:*\n\n"
        "/start — Bosh menyu\n"
        "/top — Top 10 qo'shiqlar\n"
        "/favorites — Sevimlilar\n"
        "/history — Tarix\n"
        "/stats — Statistika\n"
        "/settings — Sozlamalar\n\n"
        "💡 *Qanday ishlatish:*\n"
        "• Qo'shiq nomini yozing\n"
        "• Artist nomini yozing\n"
        "• YouTube link yuboring\n"
        "• Natijalardan birini tanlang\n",
        parse_mode="Markdown"
    )

# ─── /top ─────────────────────────────────────────────────────────────────────
async def top_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_top(update.message.chat_id, context, update.message)

async def show_top(chat_id, context, message=None, query=None):
    top = load_top()
    if not top:
        text = "📊 Hali yuklanmagan qo'shiqlar yo'q."
    else:
        sorted_top = sorted(top.values(), key=lambda x: x["count"], reverse=True)[:10]
        text = "🏆 *TOP 10 eng ko'p yuklangan:*\n\n"
        for i, item in enumerate(sorted_top, 1):
            text += f"{i}. {item['title'][:40]} — {item['count']} marta\n"

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("🔙 Orqaga", callback_data="main_menu")
    ]])

    if query:
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=keyboard)
    elif message:
        await message.reply_text(text, parse_mode="Markdown", reply_markup=keyboard)

# ─── /favorites ───────────────────────────────────────────────────────────────
async def favorites_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_favorites(update.effective_user.id, update.message.chat_id, context, message=update.message)

async def show_favorites(user_id, chat_id, context, message=None, query=None):
    db = load_db()
    user = get_user(db, user_id)
    favs = user["favorites"]

    if not favs:
        text = "❤️ Sevimlilar ro'yxatingiz bo'sh.\nQo'shiq yuklagandan so'ng ❤️ tugmasini bosing!"
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Orqaga", callback_data="main_menu")]])
    else:
        text = "❤️ *Sevimli qo'shiqlaringiz:*\n\n"
        buttons = []
        for i, fav in enumerate(favs[:10]):
            text += f"{i+1}. {fav['title'][:45]}\n"
            buttons.append([InlineKeyboardButton(f"▶️ {fav['title'][:35]}", callback_data=f"dl|{fav['url']}|{fav['title'][:40]}")])
        buttons.append([
            InlineKeyboardButton("🗑 Hammasini o'chir", callback_data="clear_favorites"),
            InlineKeyboardButton("🔙 Orqaga", callback_data="main_menu")
        ])
        keyboard = InlineKeyboardMarkup(buttons)

    if query:
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=keyboard)
    elif message:
        await message.reply_text(text, parse_mode="Markdown", reply_markup=keyboard)

# ─── /history ─────────────────────────────────────────────────────────────────
async def history_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_history(update.effective_user.id, update.message.chat_id, context, message=update.message)

async def show_history(user_id, chat_id, context, message=None, query=None):
    db = load_db()
    user = get_user(db, user_id)
    history = user["history"]

    if not history:
        text = "📜 Tarixingiz bo'sh."
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Orqaga", callback_data="main_menu")]])
    else:
        text = "📜 *So'nggi tinglaganlar:*\n\n"
        buttons = []
        for i, item in enumerate(history[:10]):
            text += f"{i+1}. {item['title'][:45]}\n"
            buttons.append([InlineKeyboardButton(f"▶️ {item['title'][:35]}", callback_data=f"dl|{item['url']}|{item['title'][:40]}")])
        buttons.append([InlineKeyboardButton("🔙 Orqaga", callback_data="main_menu")])
        keyboard = InlineKeyboardMarkup(buttons)

    if query:
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=keyboard)
    elif message:
        await message.reply_text(text, parse_mode="Markdown", reply_markup=keyboard)

# ─── /stats ───────────────────────────────────────────────────────────────────
async def stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db = load_db()
    user = get_user(db, update.effective_user.id)
    top = load_top()

    await update.message.reply_text(
        f"📊 *Sizning statistikangiz:*\n\n"
        f"⬇️ Jami yuklangan: {user['downloads']} ta\n"
        f"❤️ Sevimlilar: {len(user['favorites'])} ta\n"
        f"📜 Tarix: {len(user['history'])} ta\n\n"
        f"🌍 *Umumiy statistika:*\n"
        f"🎵 Jami qo'shiqlar: {len(top)} ta\n"
        f"⬇️ Jami yuklanmalar: {sum(v['count'] for v in top.values())} ta",
        parse_mode="Markdown"
    )

# ─── /settings ────────────────────────────────────────────────────────────────
async def settings_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_settings(update.effective_user.id, context, message=update.message)

async def show_settings(user_id, context, message=None, query=None):
    db = load_db()
    user = get_user(db, user_id)
    results_count = user["settings"]["results"]

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(f"{'✅' if results_count == 3 else '3️⃣'} 3 natija", callback_data="set_results_3"),
            InlineKeyboardButton(f"{'✅' if results_count == 5 else '5️⃣'} 5 natija", callback_data="set_results_5"),
            InlineKeyboardButton(f"{'✅' if results_count == 10 else '🔟'} 10 natija", callback_data="set_results_10"),
        ],
        [InlineKeyboardButton("🔙 Orqaga", callback_data="main_menu")],
    ])

    text = (
        "⚙️ *Sozlamalar:*\n\n"
        f"📋 Natijalar soni: *{results_count} ta*\n\n"
        "Qidiruv natijalar sonini tanlang:"
    )

    if query:
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=keyboard)
    elif message:
        await message.reply_text(text, parse_mode="Markdown", reply_markup=keyboard)

# ─── Matn xabari ─────────────────────────────────────────────────────────────
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    chat_id = update.message.chat_id
    user_id = update.effective_user.id

    # YouTube link bo'lsa
    if "youtube.com" in text or "youtu.be" in text:
        await send_audio(chat_id, text, "Qo'shiq", context, user_id)
        return

    # Qidirish
    db = load_db()
    user = get_user(db, user_id)
    limit = user["settings"]["results"]

    msg = await update.message.reply_text(f"🔍 *{text}* qidirilmoqda...", parse_mode="Markdown")

    try:
        results = search_youtube(text, limit)
    except Exception:
        await msg.edit_text("❌ Qidirishda xatolik. Qaytadan urinib ko'ring.")
        return

    if not results:
        await msg.edit_text("❌ Hech narsa topilmadi.")
        return

    buttons = []
    result_text = f"🎵 *'{text}'* bo'yicha natijalar:\n\n"
    for i, r in enumerate(results):
        result_text += f"{i+1}. {r['title'][:45]}\n    ⏱ {r['duration']} | 📺 {r['channel'][:20]}\n\n"
        buttons.append([InlineKeyboardButton(
            f"{'1️⃣2️⃣3️⃣4️⃣5️⃣6️⃣7️⃣8️⃣9️⃣🔟'.split()[i] if i < 10 else str(i+1)} {r['title'][:40]}",
            callback_data=f"dl|{r['url']}|{r['title'][:40]}"
        )])

    keyboard = InlineKeyboardMarkup(buttons)
    await msg.edit_text(result_text, parse_mode="Markdown", reply_markup=keyboard)

# ─── Callback handler ─────────────────────────────────────────────────────────
async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = update.effective_user.id
    chat_id = query.message.chat_id

    # Yuklab olish
    if data.startswith("dl|"):
        _, url, title = data.split("|", 2)
        await send_audio(chat_id, url, title, context, user_id)

    # Sevimlilarga qo'shish
    elif data.startswith("fav|"):
        _, url, title = data.split("|", 2)
        db = load_db()
        user = get_user(db, user_id)
        fav = {"title": title, "url": url}
        if fav not in user["favorites"]:
            user["favorites"].insert(0, fav)
            user["favorites"] = user["favorites"][:50]
            save_db(db)
            await query.answer("❤️ Sevimlilarga qo'shildi!", show_alert=True)
        else:
            await query.answer("⚠️ Allaqachon sevimlilar ro'yxatida!", show_alert=True)

    # Sevimlilarni ko'rish
    elif data == "my_favorites":
        await show_favorites(user_id, chat_id, context, query=query)

    # Sevimlilarni tozalash
    elif data == "clear_favorites":
        db = load_db()
        user = get_user(db, user_id)
        user["favorites"] = []
        save_db(db)
        await query.edit_message_text("🗑 Sevimlilar tozalandi.")

    # Top 10
    elif data == "top10":
        await show_top(chat_id, context, query=query)

    # Tarix
    elif data == "history":
        await show_history(user_id, chat_id, context, query=query)

    # Sozlamalar
    elif data == "settings":
        await show_settings(user_id, context, query=query)

    # Natijalar sonini o'zgartirish
    elif data.startswith("set_results_"):
        count = int(data.split("_")[-1])
        db = load_db()
        user = get_user(db, user_id)
        user["settings"]["results"] = count
        save_db(db)
        await show_settings(user_id, context, query=query)

    # Yordam
    elif data == "help":
        await query.edit_message_text(
            "📖 *Buyruqlar:*\n\n"
            "/start — Bosh menyu\n"
            "/top — Top 10 qo'shiqlar\n"
            "/favorites — Sevimlilar\n"
            "/history — Tarix\n"
            "/stats — Statistika\n"
            "/settings — Sozlamalar\n\n"
            "💡 *Qanday ishlatish:*\n"
            "• Qo'shiq nomini yozing\n"
            "• Artist nomini yozing\n"
            "• YouTube link yuboring\n"
            "• Natijalardan birini tanlang\n",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 Orqaga", callback_data="main_menu")
            ]])
        )

    # Bosh menyu
    elif data == "main_menu":
        user_name = update.effective_user.first_name
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔍 Qidirish", switch_inline_query_current_chat=""),
             InlineKeyboardButton("❤️ Sevimlilar", callback_data="my_favorites")],
            [InlineKeyboardButton("📊 Top 10", callback_data="top10"),
             InlineKeyboardButton("📜 Tarix", callback_data="history")],
            [InlineKeyboardButton("⚙️ Sozlamalar", callback_data="settings"),
             InlineKeyboardButton("ℹ️ Yordam", callback_data="help")],
        ])
        await query.edit_message_text(
            f"🎵 *Xush kelibsiz, {user_name}!*\n\n"
            "Men sizga YouTube'dan musiqa topib beraman!\n\n"
            "🔍 Qo'shiq nomi yoki artist yozing\n"
            "🔗 Yoki YouTube link yuboring\n\n"
            "Quyidagi tugmalardan foydalaning 👇",
            parse_mode="Markdown",
            reply_markup=keyboard
        )

# ─── Main ─────────────────────────────────────────────────────────────────────
def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("top", top_cmd))
    app.add_handler(CommandHandler("favorites", favorites_cmd))
    app.add_handler(CommandHandler("history", history_cmd))
    app.add_handler(CommandHandler("stats", stats_cmd))
    app.add_handler(CommandHandler("settings", settings_cmd))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    print("🎵 MusicBot ishga tushdi ✅")
    app.run_polling()

if __name__ == "__main__":
    main()
