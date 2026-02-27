import os
import json
import re
import asyncio
import requests
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
YT_API_KEY = "AIzaSyCTHPm3oLBd-vXhl1JH9rEYOvbt1USOvzg"

# ─── DATABASE ─────────────────────────────────────────────────────────────────
DB_FILE = "/tmp/users.json"
TOP_FILE = "/tmp/top.json"

def load_db():
    try:
        if os.path.exists(DB_FILE):
            with open(DB_FILE, "r") as f:
                return json.load(f)
    except:
        pass
    return {}

def save_db(db):
    try:
        with open(DB_FILE, "w") as f:
            json.dump(db, f, ensure_ascii=False, indent=2)
    except:
        pass

def get_user(db, user_id):
    uid = str(user_id)
    if uid not in db:
        db[uid] = {"favorites": [], "history": [], "settings": {"results": 5}, "downloads": 0}
    return db[uid]

def load_top():
    try:
        if os.path.exists(TOP_FILE):
            with open(TOP_FILE, "r") as f:
                return json.load(f)
    except:
        pass
    return {}

def save_top(top):
    try:
        with open(TOP_FILE, "w") as f:
            json.dump(top, f, ensure_ascii=False, indent=2)
    except:
        pass

def increment_top(title, url):
    top = load_top()
    if url not in top:
        top[url] = {"title": title, "count": 0}
    top[url]["count"] += 1
    save_top(top)

# ─── SEARCH via YouTube API ───────────────────────────────────────────────────
def search_youtube_api(query, limit=5):
    """YouTube Data API v3 orqali qidirish - hech qachon bloklanmaydi"""
    if not YT_API_KEY:
        return search_youtube_ytdlp(query, limit)
    try:
        url = "https://www.googleapis.com/youtube/v3/search"
        params = {
            "part": "snippet",
            "q": query,
            "type": "video",
            "videoCategoryId": "10",  # Music category
            "maxResults": limit,
            "key": YT_API_KEY,
        }
        res = requests.get(url, params=params, timeout=10)
        data = res.json()
        results = []
        for item in data.get("items", []):
            vid_id = item["id"]["videoId"]
            title = item["snippet"]["title"]
            channel = item["snippet"]["channelTitle"]
            results.append({
                "title": title,
                "url": f"https://youtube.com/watch?v={vid_id}",
                "duration": "?",
                "channel": channel,
                "source": "🎬 YouTube",
            })
        return results
    except Exception as e:
        return search_youtube_ytdlp(query, limit)

def search_youtube_ytdlp(query, limit=5):
    """yt-dlp orqali qidirish (backup)"""
    ydl_opts = {
        "quiet": True,
        "skip_download": True,
        "extract_flat": True,
        "no_warnings": True,
        "socket_timeout": 10,
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            result = ydl.extract_info(f"ytsearch{limit}:{query}", download=False)
            results = []
            for v in result.get("entries", []):
                if v:
                    dur = v.get("duration", 0)
                    results.append({
                        "title": v.get("title", "?"),
                        "url": f"https://youtube.com/watch?v={v.get('id','')}",
                        "duration": f"{dur//60}:{dur%60:02d}" if dur else "?",
                        "channel": v.get("uploader", "YouTube"),
                        "source": "🎬 YouTube",
                    })
            return results
    except:
        return []

def search_soundcloud(query, limit=3):
    ydl_opts = {
        "quiet": True,
        "skip_download": True,
        "extract_flat": True,
        "no_warnings": True,
        "socket_timeout": 10,
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            result = ydl.extract_info(f"scsearch{limit}:{query}", download=False)
            results = []
            for v in result.get("entries", []):
                if v:
                    dur = v.get("duration", 0)
                    results.append({
                        "title": v.get("title", "?"),
                        "url": v.get("webpage_url", ""),
                        "duration": f"{dur//60}:{dur%60:02d}" if dur else "?",
                        "channel": v.get("uploader", "SoundCloud"),
                        "source": "🎵 SoundCloud",
                    })
            return results
    except:
        return []

def combine_search(query, limit=5):
    yt = search_youtube_api(query, limit)
    sc = search_soundcloud(query, 2)
    combined = yt + sc
    return combined[:limit + 3]

# ─── DOWNLOAD AUDIO ───────────────────────────────────────────────────────────
async def download_audio(chat_id, url, title, context, user_id=None):
    msg = await context.bot.send_message(
        chat_id=chat_id,
        text=f"⏳ Yuklanmoqda...",
    )
    outfile = f"/tmp/audio_{chat_id}"
    
    # Avval mp3 convert bilan urinib ko'r
    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": f"{outfile}.%(ext)s",
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "socket_timeout": 30,
        "retries": 3,
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "192",
        }],
    }
    
    real_title = title
    artist = ""
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            real_title = info.get("title", title)
            artist = info.get("uploader", "")
    except Exception as e:
        # FFmpeg yo'q bo'lsa, convert qilmasdan yukla
        ydl_opts2 = {
            "format": "bestaudio[ext=m4a]/bestaudio[ext=mp3]/bestaudio",
            "outtmpl": f"{outfile}.%(ext)s",
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "socket_timeout": 30,
            "retries": 3,
        }
        try:
            with yt_dlp.YoutubeDL(ydl_opts2) as ydl:
                info = ydl.extract_info(url, download=True)
                real_title = info.get("title", title)
                artist = info.get("uploader", "")
        except Exception as e2:
            await msg.edit_text(f"❌ Yuklashda xatolik. Qaytadan urinib ko'ring.")
            return

    # Yuklangan faylni top
    filepath = None
    for ext in ["mp3", "m4a", "webm", "opus", "ogg"]:
        p = f"{outfile}.{ext}"
        if os.path.exists(p):
            filepath = p
            break

    if not filepath:
        # /tmp dan qidir
        for f in os.listdir("/tmp"):
            if f.startswith(f"audio_{chat_id}"):
                filepath = f"/tmp/{f}"
                break

    if filepath and os.path.exists(filepath):
        increment_top(real_title, url)
        if user_id:
            db = load_db()
            user = get_user(db, user_id)
            user["downloads"] += 1
            h = {"title": real_title, "url": url}
            if h not in user["history"]:
                user["history"].insert(0, h)
                user["history"] = user["history"][:15]
            save_db(db)

        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("❤️ Sevimli", callback_data=f"fav|{url}|{real_title[:40]}"),
            InlineKeyboardButton("🎬 Video", callback_data=f"vid|{url}|{real_title[:40]}"),
        ]])
        try:
            with open(filepath, "rb") as audio:
                await context.bot.send_audio(
                    chat_id=chat_id,
                    audio=audio,
                    title=real_title,
                    performer=artist,
                    reply_markup=keyboard,
                )
        except Exception:
            with open(filepath, "rb") as doc:
                await context.bot.send_document(
                    chat_id=chat_id,
                    document=doc,
                    caption=f"🎵 {real_title}",
                    reply_markup=keyboard,
                )
        os.remove(filepath)
        await msg.delete()
    else:
        await msg.edit_text("❌ Fayl topilmadi. Boshqa qo'shiq bilan urinib ko'ring.")

# ─── DOWNLOAD VIDEO ───────────────────────────────────────────────────────────
async def download_video(chat_id, url, title, context):
    msg = await context.bot.send_message(chat_id=chat_id, text="🎬 Video yuklanmoqda...")
    outfile = f"/tmp/video_{chat_id}.mp4"
    
    ydl_opts = {
        "format": "best[filesize<45M]/best[height<=480]/best",
        "outtmpl": outfile,
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "socket_timeout": 30,
        "retries": 3,
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            real_title = info.get("title", title)
    except Exception as e:
        await msg.edit_text(f"❌ Video yuklashda xatolik: {str(e)[:80]}")
        return

    if os.path.exists(outfile):
        size = os.path.getsize(outfile)
        if size > 50 * 1024 * 1024:
            await msg.edit_text("❌ Video hajmi 50MB dan katta. MP3 yuklab oling.")
            os.remove(outfile)
            return
        try:
            with open(outfile, "rb") as video:
                await context.bot.send_video(chat_id=chat_id, video=video, caption=f"🎬 {real_title}")
        except:
            with open(outfile, "rb") as doc:
                await context.bot.send_document(chat_id=chat_id, document=doc, caption=f"🎬 {real_title}")
        os.remove(outfile)
        await msg.delete()
    else:
        await msg.edit_text("❌ Video topilmadi.")

# ─── MAIN MENU KEYBOARD ───────────────────────────────────────────────────────
def main_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔍 Qidirish", switch_inline_query_current_chat=""),
         InlineKeyboardButton("❤️ Sevimlilar", callback_data="my_favorites")],
        [InlineKeyboardButton("🏆 Top 10", callback_data="top10"),
         InlineKeyboardButton("📜 Tarix", callback_data="history")],
        [InlineKeyboardButton("⚙️ Sozlamalar", callback_data="settings"),
         InlineKeyboardButton("ℹ️ Yordam", callback_data="help")],
    ])

# ─── /start ───────────────────────────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await update.message.reply_text(
        f"🎵 *Salom, {user.first_name}!*\n\n"
        "Men kuchli musiqa botiman!\n\n"
        "🎬 *YouTube* — mp3 + video\n"
        "🎵 *SoundCloud* — mp3\n\n"
        "📌 Qo'shiq nomi yoki artist yozing\n"
        "🔗 YouTube link yuboring → MP3 yoki Video",
        parse_mode="Markdown",
        reply_markup=main_keyboard()
    )

# ─── HANDLE TEXT ──────────────────────────────────────────────────────────────
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    chat_id = update.message.chat_id
    user_id = update.effective_user.id

    # YouTube link
    if re.search(r"(youtube\.com|youtu\.be)", text):
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("🎵 MP3", callback_data=f"dl|{text}|Qoshiq"),
            InlineKeyboardButton("🎬 Video", callback_data=f"vid|{text}|Video"),
        ]])
        await update.message.reply_text("YouTube link topildi! Nima yuklamoqchisiz?", reply_markup=keyboard)
        return

    # Boshqa link
    if re.search(r"https?://", text):
        await download_video(chat_id, text, "Video", context)
        return

    # Qidirish
    db = load_db()
    user = get_user(db, user_id)
    limit = user["settings"]["results"]

    msg = await update.message.reply_text(f"🔍 *{text}* qidirilmoqda...", parse_mode="Markdown")

    try:
        results = combine_search(text, limit)
    except Exception as e:
        await msg.edit_text("❌ Qidirishda xatolik. Qaytadan urinib ko'ring.")
        return

    if not results:
        await msg.edit_text("❌ Hech narsa topilmadi. Boshqa so'z bilan urinib ko'ring.")
        return

    nums = ["1️⃣","2️⃣","3️⃣","4️⃣","5️⃣","6️⃣","7️⃣","8️⃣","9️⃣","🔟"]
    result_text = f"🎵 *'{text}'* natijalari:\n\n"
    buttons = []
    for i, r in enumerate(results[:10]):
        result_text += f"{nums[i]} {r['source']} | {r['title'][:40]}\n    ⏱ {r['duration']} • {r['channel'][:20]}\n\n"
        buttons.append([InlineKeyboardButton(
            f"{nums[i]} {r['title'][:45]}",
            callback_data=f"dl|{r['url']}|{r['title'][:40]}"
        )])

    await msg.edit_text(result_text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(buttons))

# ─── CALLBACK ─────────────────────────────────────────────────────────────────
async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = update.effective_user.id
    chat_id = query.message.chat_id

    if data.startswith("dl|"):
        _, url, title = data.split("|", 2)
        await download_audio(chat_id, url, title, context, user_id)

    elif data.startswith("vid|"):
        _, url, title = data.split("|", 2)
        await download_video(chat_id, url, title, context)

    elif data.startswith("fav|"):
        _, url, title = data.split("|", 2)
        db = load_db()
        user = get_user(db, user_id)
        fav = {"title": title, "url": url}
        if fav not in user["favorites"]:
            user["favorites"].insert(0, fav)
            user["favorites"] = user["favorites"][:50]
            save_db(db)
            await query.answer("❤️ Sevimlilarga qoshildi!", show_alert=True)
        else:
            await query.answer("Allaqachon sevimlilar royxatida!", show_alert=True)

    elif data == "my_favorites":
        db = load_db()
        user = get_user(db, user_id)
        favs = user["favorites"]
        if not favs:
            await query.edit_message_text("❤️ Sevimlilar royxatingiz bosh.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Orqaga", callback_data="main_menu")]]))
        else:
            text = "❤️ *Sevimlilar:*\n\n"
            buttons = []
            for i, fav in enumerate(favs[:10]):
                text += f"{i+1}. {fav['title'][:45]}\n"
                buttons.append([InlineKeyboardButton(f"▶️ {fav['title'][:40]}", callback_data=f"dl|{fav['url']}|{fav['title'][:40]}")])
            buttons.append([InlineKeyboardButton("🗑 Tozalash", callback_data="clear_favorites"),
                            InlineKeyboardButton("🔙 Orqaga", callback_data="main_menu")])
            await query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(buttons))

    elif data == "clear_favorites":
        db = load_db()
        user = get_user(db, user_id)
        user["favorites"] = []
        save_db(db)
        await query.edit_message_text("🗑 Sevimlilar tozalandi.")

    elif data == "top10":
        top = load_top()
        if not top:
            text = "🏆 Hali yuklanmagan qoshiqlar yoq."
        else:
            sorted_top = sorted(top.values(), key=lambda x: x["count"], reverse=True)[:10]
            nums = ["1️⃣","2️⃣","3️⃣","4️⃣","5️⃣","6️⃣","7️⃣","8️⃣","9️⃣","🔟"]
            text = "🏆 *TOP 10:*\n\n"
            for i, item in enumerate(sorted_top):
                text += f"{nums[i]} {item['title'][:40]} — *{item['count']}x*\n"
        await query.edit_message_text(text, parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Orqaga", callback_data="main_menu")]]))

    elif data == "history":
        db = load_db()
        user = get_user(db, user_id)
        history = user["history"]
        if not history:
            await query.edit_message_text("📜 Tarix bosh.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Orqaga", callback_data="main_menu")]]))
        else:
            text = "📜 *Tarix:*\n\n"
            buttons = []
            for i, item in enumerate(history[:10]):
                text += f"{i+1}. {item['title'][:45]}\n"
                buttons.append([InlineKeyboardButton(f"▶️ {item['title'][:40]}", callback_data=f"dl|{item['url']}|{item['title'][:40]}")])
            buttons.append([InlineKeyboardButton("🔙 Orqaga", callback_data="main_menu")])
            await query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(buttons))

    elif data == "settings":
        db = load_db()
        user = get_user(db, user_id)
        cnt = user["settings"]["results"]
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(f"{'✅' if cnt==3 else '3️⃣'} 3 ta", callback_data="set_results_3"),
             InlineKeyboardButton(f"{'✅' if cnt==5 else '5️⃣'} 5 ta", callback_data="set_results_5"),
             InlineKeyboardButton(f"{'✅' if cnt==10 else '🔟'} 10 ta", callback_data="set_results_10")],
            [InlineKeyboardButton("🔙 Orqaga", callback_data="main_menu")],
        ])
        await query.edit_message_text(f"⚙️ *Sozlamalar*\n\nNatijalar soni: *{cnt} ta*",
            parse_mode="Markdown", reply_markup=keyboard)

    elif data.startswith("set_results_"):
        count = int(data.split("_")[-1])
        db = load_db()
        user = get_user(db, user_id)
        user["settings"]["results"] = count
        save_db(db)
        await query.answer(f"✅ {count} ta natija o'rnatildi!", show_alert=True)

    elif data == "help":
        await query.edit_message_text(
            "ℹ️ *Yordam*\n\n"
            "🎵 Qoshiq nomi → YouTube + SoundCloud dan qidiradi\n"
            "🔗 YouTube link → MP3 yoki Video tanlang\n"
            "🔗 Boshqa link → video yuklab beradi\n\n"
            "📌 *Buyruqlar:*\n"
            "/start — Bosh menyu\n"
            "/top — Top 10\n"
            "/favorites — Sevimlilar\n"
            "/history — Tarix\n"
            "/stats — Statistika\n",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Orqaga", callback_data="main_menu")]]))

    elif data == "main_menu":
        await query.edit_message_text(
            "🎵 *Bosh menyu*\n\nQoshiq nomi yoki link yuboring!",
            parse_mode="Markdown", reply_markup=main_keyboard())

# ─── COMMANDS ─────────────────────────────────────────────────────────────────
async def top_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    top = load_top()
    if not top:
        await update.message.reply_text("🏆 Hali yuklanmagan qoshiqlar yoq.")
        return
    sorted_top = sorted(top.values(), key=lambda x: x["count"], reverse=True)[:10]
    nums = ["1️⃣","2️⃣","3️⃣","4️⃣","5️⃣","6️⃣","7️⃣","8️⃣","9️⃣","🔟"]
    text = "🏆 *TOP 10:*\n\n"
    for i, item in enumerate(sorted_top):
        text += f"{nums[i]} {item['title'][:40]} — *{item['count']}x*\n"
    await update.message.reply_text(text, parse_mode="Markdown")

async def favorites_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db = load_db()
    user = get_user(db, update.effective_user.id)
    favs = user["favorites"]
    if not favs:
        await update.message.reply_text("❤️ Sevimlilar royxatingiz bosh.")
        return
    text = "❤️ *Sevimlilar:*\n\n"
    buttons = []
    for i, fav in enumerate(favs[:10]):
        text += f"{i+1}. {fav['title'][:45]}\n"
        buttons.append([InlineKeyboardButton(f"▶️ {fav['title'][:40]}", callback_data=f"dl|{fav['url']}|{fav['title'][:40]}")])
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(buttons))

async def history_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db = load_db()
    user = get_user(db, update.effective_user.id)
    history = user["history"]
    if not history:
        await update.message.reply_text("📜 Tarix bosh.")
        return
    text = "📜 *Tarix:*\n\n"
    buttons = []
    for i, item in enumerate(history[:10]):
        text += f"{i+1}. {item['title'][:45]}\n"
        buttons.append([InlineKeyboardButton(f"▶️ {item['title'][:40]}", callback_data=f"dl|{item['url']}|{item['title'][:40]}")])
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(buttons))

async def stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db = load_db()
    user = get_user(db, update.effective_user.id)
    top = load_top()
    await update.message.reply_text(
        f"📊 *Statistika:*\n\n"
        f"⬇️ Siz yuklagan: *{user['downloads']} ta*\n"
        f"❤️ Sevimlilar: *{len(user['favorites'])} ta*\n"
        f"📜 Tarix: *{len(user['history'])} ta*\n\n"
        f"🌍 *Umumiy:*\n"
        f"🎵 Jami qoshiqlar: *{len(top)} ta*\n"
        f"⬇️ Jami yuklanmalar: *{sum(v['count'] for v in top.values())} ta*",
        parse_mode="Markdown"
    )

# ─── MAIN ─────────────────────────────────────────────────────────────────────
def main():
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("top", top_cmd))
    app.add_handler(CommandHandler("favorites", favorites_cmd))
    app.add_handler(CommandHandler("history", history_cmd))
    app.add_handler(CommandHandler("stats", stats_cmd))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    print("🎵 MusicBot ishga tushdi ✅")
    app.run_polling()

if __name__ == "__main__":
    main()

