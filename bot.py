import os
import json
import re
import hashlib
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

TOKEN = "8312461995:AAGqJkT11O9zqoSrw3NP4D_1fbl6Wrg2xQk"
YT_API_KEY = "AIzaSyCTHPm3oLBd-vXhl1JH9rEYOvbt1USOvzg"
ADMIN_ID = "6705765282"

URL_CACHE = {}
INSTAGRAM_TITLES = {}  # Instagram URL → video title (musiqa nomi uchun)

def url_to_id(url):
    uid = hashlib.md5(url.encode()).hexdigest()[:12]
    URL_CACHE[uid] = url
    return uid

def id_to_url(uid):
    return URL_CACHE.get(uid, "")

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

def get_user(db, user_id, user_obj=None):
    uid = str(user_id)
    if uid not in db:
        import datetime
        db[uid] = {
            "favorites": [],
            "history": [],
            "settings": {"results": 10},
            "downloads": 0,
            "name": user_obj.full_name if user_obj else "Noma'lum",
            "username": f"@{user_obj.username}" if user_obj and user_obj.username else "",
            "joined": datetime.datetime.now().strftime("%Y-%m-%d"),
        }
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

def detect_platform(url):
    if re.search(r"(youtube\.com|youtu\.be)", url):
        return "youtube"
    elif re.search(r"instagram\.com", url):
        return "instagram"
    elif re.search(r"tiktok\.com", url):
        return "tiktok"
    elif re.search(r"snapchat\.com", url):
        return "snapchat"
    elif re.search(r"pinterest\.", url):
        return "pinterest"
    elif re.search(r"likee\.", url):
        return "likee"
    elif re.search(r"https?://", url):
        return "other"
    return None

# ─── SEARCH ───────────────────────────────────────────────────────────────────
def search_soundcloud(query, limit=10):
    ydl_opts = {
        "quiet": True,
        "skip_download": True,
        "extract_flat": True,
        "no_warnings": True,
        "socket_timeout": 15,
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            result = ydl.extract_info(f"scsearch{limit}:{query}", download=False)
            results = []
            for v in result.get("entries", []):
                if v:
                    dur = v.get("duration", 0)
                    sc_url = v.get("webpage_url", "")
                    results.append({
                        "title": v.get("title", "?"),
                        "url": sc_url,
                        "uid": url_to_id(sc_url),
                        "duration": f"{dur//60}:{dur%60:02d}" if dur else "?",
                        "channel": v.get("uploader", "SC"),
                        "source": "🎵 SoundCloud",
                    })
            return results
    except:
        return []

def search_youtube_api(query, limit=5):
    if not YT_API_KEY:
        return []
    try:
        params = {
            "part": "snippet",
            "q": query,
            "type": "video",
            "maxResults": limit,
            "key": YT_API_KEY,
        }
        res = requests.get("https://www.googleapis.com/youtube/v3/search", params=params, timeout=8)
        data = res.json()
        results = []
        for item in data.get("items", []):
            vid_id = item["id"]["videoId"]
            title = item["snippet"]["title"]
            channel = item["snippet"]["channelTitle"]
            yt_url = f"https://youtube.com/watch?v={vid_id}"
            results.append({
                "title": title,
                "url": yt_url,
                "uid": url_to_id(yt_url),
                "duration": "?",
                "channel": channel,
                "source": "🎬 YouTube",
            })
        return results
    except:
        return []

def combine_search(query, limit=10):
    sc = search_soundcloud(query, limit)
    yt = search_youtube_api(query, 5)
    seen = set()
    combined = []
    for r in sc + yt:
        if r["title"] not in seen:
            seen.add(r["title"])
            combined.append(r)
    return combined[:limit]

# ─── GET INSTAGRAM MUSIC TITLE ────────────────────────────────────────────────
def get_instagram_music_title(url):
    """Instagram videodagi musiqa nomini olishga harakat qiladi"""
    ydl_opts = {
        "quiet": True,
        "skip_download": True,
        "no_warnings": True,
        "socket_timeout": 15,
    }
    if os.path.exists("/app/cookies.txt"):
        ydl_opts["cookiefile"] = "/app/cookies.txt"
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            # Musiqa nomini turli joylardan qidirish
            music = (
                info.get("track") or
                info.get("artist") or
                info.get("music") or
                info.get("title", "")
            )
            artist = info.get("artist", "")
            if artist and music and artist not in music:
                return f"{artist} - {music}"
            return music or info.get("title", "")
    except:
        return ""

# ─── DOWNLOAD AUDIO ───────────────────────────────────────────────────────────
async def download_audio(chat_id, url, title, context, user_id=None, user_obj=None):
    msg = await context.bot.send_message(chat_id=chat_id, text="⏳ Audio yuklanmoqda...")
    outfile = f"/tmp/audio_{chat_id}"

    ydl_opts = {
        "format": "bestaudio[ext=mp3]/bestaudio[ext=m4a]/bestaudio",
        "outtmpl": f"{outfile}.%(ext)s",
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "socket_timeout": 60,
        "retries": 5,
    }
    if os.path.exists("/app/cookies.txt"):
        ydl_opts["cookiefile"] = "/app/cookies.txt"

    real_title = title
    artist = ""

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            real_title = info.get("title", title)
            artist = info.get("uploader", "")
    except:
        ydl_opts2 = {
            "format": "bestaudio/best",
            "outtmpl": f"{outfile}.%(ext)s",
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "socket_timeout": 60,
            "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "128"}],
        }
        if os.path.exists("/app/cookies.txt"):
            ydl_opts2["cookiefile"] = "/app/cookies.txt"
        try:
            with yt_dlp.YoutubeDL(ydl_opts2) as ydl:
                info = ydl.extract_info(url, download=True)
                real_title = info.get("title", title)
                artist = info.get("uploader", "")
        except:
            await msg.edit_text("❌ Yuklashda xatolik. Boshqa qoshiq bilan urinib koring.")
            return

    filepath = None
    for ext in ["mp3", "m4a", "webm", "opus", "ogg", "mp4"]:
        p = f"{outfile}.{ext}"
        if os.path.exists(p):
            filepath = p
            break
    if not filepath:
        for f in os.listdir("/tmp"):
            if f.startswith(f"audio_{chat_id}"):
                filepath = f"/tmp/{f}"
                break

    if filepath and os.path.exists(filepath):
        increment_top(real_title, url)
        if user_id:
            db = load_db()
            user = get_user(db, user_id, user_obj)
            user["downloads"] += 1
            h = {"title": real_title, "url": url}
            if h not in user["history"]:
                user["history"].insert(0, h)
                user["history"] = user["history"][:15]
            save_db(db)

        uid = url_to_id(url)
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("❤️ Sevimli", callback_data=f"fav|{uid}|{real_title[:25]}"),
            InlineKeyboardButton("🎬 Video", callback_data=f"vid|{uid}"),
        ]])
        try:
            with open(filepath, "rb") as audio:
                await context.bot.send_audio(
                    chat_id=chat_id, audio=audio,
                    title=real_title, performer=artist,
                    reply_markup=keyboard,
                    read_timeout=120, write_timeout=120,
                )
        except:
            try:
                with open(filepath, "rb") as doc:
                    await context.bot.send_document(
                        chat_id=chat_id, document=doc,
                        caption=f"🎵 {real_title}",
                        reply_markup=keyboard,
                        read_timeout=120, write_timeout=120,
                    )
            except:
                await msg.edit_text("❌ Yuborishda xatolik.")
                return
        try:
            os.remove(filepath)
        except:
            pass
        await msg.delete()
    else:
        await msg.edit_text("❌ Fayl topilmadi.")

# ─── DOWNLOAD VIDEO ───────────────────────────────────────────────────────────
async def download_video(chat_id, url, context, platform="other"):
    platform_names = {
        "youtube": "YouTube", "instagram": "Instagram",
        "tiktok": "TikTok", "snapchat": "Snapchat",
        "pinterest": "Pinterest", "likee": "Likee", "other": "Video",
    }
    name = platform_names.get(platform, "Video")
    msg = await context.bot.send_message(chat_id=chat_id, text=f"🎬 {name} yuklanmoqda...")
    outfile = f"/tmp/video_{chat_id}.mp4"

    ydl_opts = {
        "format": "best[height<=480][filesize<45M]/best[height<=360]/worst",
        "outtmpl": outfile,
        "quiet": True,
        "noplaylist": True,
        "socket_timeout": 60,
        "retries": 3,
    }
    if os.path.exists("/app/cookies.txt"):
        ydl_opts["cookiefile"] = "/app/cookies.txt"

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            real_title = info.get("title", name)
    except:
        await msg.edit_text(f"❌ {name} yuklashda xatolik.")
        return

    if os.path.exists(outfile):
        if os.path.getsize(outfile) > 50 * 1024 * 1024:
            ydl_opts["format"] = "worst"
            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ydl.extract_info(url, download=True)
            except:
                await msg.edit_text("❌ Video juda katta.")
                try:
                    os.remove(outfile)
                except:
                    pass
                return
        try:
            with open(outfile, "rb") as video:
                await context.bot.send_video(
                    chat_id=chat_id, video=video,
                    caption=f"🎬 {real_title}",
                    read_timeout=120, write_timeout=120,
                )
        except:
            with open(outfile, "rb") as doc:
                await context.bot.send_document(
                    chat_id=chat_id, document=doc,
                    caption=f"🎬 {real_title}",
                )
        try:
            os.remove(outfile)
        except:
            pass
        await msg.delete()
    else:
        await msg.edit_text("❌ Video topilmadi.")

# ─── KEYBOARDS ────────────────────────────────────────────────────────────────
def main_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔍 Qidirish", switch_inline_query_current_chat=""),
         InlineKeyboardButton("❤️ Sevimlilar", callback_data="my_fav")],
        [InlineKeyboardButton("🏆 Top 10", callback_data="top10"),
         InlineKeyboardButton("📜 Tarix", callback_data="history")],
        [InlineKeyboardButton("⚙️ Sozlamalar", callback_data="settings"),
         InlineKeyboardButton("ℹ️ Yordam", callback_data="help")],
    ])

# ─── /start ───────────────────────────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db = load_db()
    get_user(db, user.id, user)
    save_db(db)
    await update.message.reply_text(
        f"🎵 *Salom, {user.first_name}!*\n\n"
        "📥 *Yuklab olish:*\n"
        "• 🎬 YouTube — video + audio\n"
        "• 📸 Instagram — video + musiqa\n"
        "• 🎵 TikTok — suvsiz video\n"
        "• 👻 Snapchat — video\n"
        "• 📌 Pinterest — video\n"
        "• 💚 Likee — video\n\n"
        "🎤 *Qo'shiq qidirish:* nom yozing!\n\n"
        "🔗 Link yuboring yoki qo'shiq nomi yozing!",
        parse_mode="Markdown",
        reply_markup=main_keyboard()
    )

# ─── HANDLE TEXT ──────────────────────────────────────────────────────────────
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    chat_id = update.message.chat_id
    user_id = update.effective_user.id
    user_obj = update.effective_user

    db = load_db()
    get_user(db, user_id, user_obj)
    save_db(db)

    platform = detect_platform(text)

    # YouTube link
    if platform == "youtube":
        uid = url_to_id(text)
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("🎵 MP3", callback_data=f"dl|{uid}"),
            InlineKeyboardButton("🎬 Video", callback_data=f"vid|{uid}"),
        ]])
        await update.message.reply_text("🎬 YouTube link! Nima yuklamoqchisiz?", reply_markup=keyboard)
        return

    # Instagram link — 3 ta variant
    if platform == "instagram":
        uid = url_to_id(text)
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("🎵 To'liq musiqa", callback_data=f"ig_music|{uid}"),
            InlineKeyboardButton("🎵 Videodagi musiqa", callback_data=f"dl|{uid}"),
        ], [
            InlineKeyboardButton("🎬 Videoni yukla", callback_data=f"vid|{uid}"),
        ]])
        await update.message.reply_text(
            "📸 *Instagram link!*\n\nNima kerak?",
            parse_mode="Markdown",
            reply_markup=keyboard
        )
        return

    # TikTok, Snapchat, Pinterest, Likee — to'g'ridan video
    if platform in ["tiktok", "snapchat", "pinterest", "likee", "other"]:
        await download_video(chat_id, text, context, platform)
        return

    # Qo'shiq qidirish
    db = load_db()
    user = get_user(db, user_id, user_obj)
    limit = user["settings"]["results"]

    msg = await update.message.reply_text(
        f"🔍 *{text}* qidirilmoqda...",
        parse_mode="Markdown"
    )

    try:
        results = combine_search(text, limit)
    except:
        await msg.edit_text("❌ Xatolik yuz berdi.")
        return

    if not results:
        await msg.edit_text("❌ Hech narsa topilmadi.")
        return

    nums = ["1️⃣","2️⃣","3️⃣","4️⃣","5️⃣","6️⃣","7️⃣","8️⃣","9️⃣","🔟"]
    result_text = f"🎵 *'{text}'* natijalari:\n\n"
    buttons = []
    for i, r in enumerate(results[:10]):
        result_text += f"{nums[i]} {r['source']} | {r['title'][:40]}\n    ⏱ {r['duration']} • {r['channel'][:20]}\n\n"
        buttons.append([InlineKeyboardButton(
            f"{nums[i]} {r['title'][:45]}",
            callback_data=f"dl|{r['uid']}"
        )])

    await msg.edit_text(result_text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(buttons))

# ─── HANDLE VOICE ─────────────────────────────────────────────────────────────
async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🎤 Ovozli xabar qabul qilindi!\n"
        "⚠️ Hozircha ovozli xabar orqali qidirish mavjud emas.\n"
        "Qo'shiq nomini yozing!"
    )

# ─── CALLBACK ─────────────────────────────────────────────────────────────────
async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = update.effective_user.id
    user_obj = update.effective_user
    chat_id = query.message.chat_id

    # Instagram → To'liq musiqa qidirish
    if data.startswith("ig_music|"):
        uid = data.split("|")[1]
        url = id_to_url(uid)
        if not url:
            await query.answer("❌ Muddati otgan. Qayta yuboring.", show_alert=True)
            return
        await query.edit_message_text("🔍 Videodagi musiqa nomi aniqlanmoqda...")
        music_title = get_instagram_music_title(url)
        if music_title:
            results = combine_search(music_title, 10)
            if results:
                nums = ["1️⃣","2️⃣","3️⃣","4️⃣","5️⃣","6️⃣","7️⃣","8️⃣","9️⃣","🔟"]
                result_text = f"🎵 *'{music_title}'* natijalari:\n\n"
                buttons = []
                for i, r in enumerate(results[:10]):
                    result_text += f"{nums[i]} {r['source']} | {r['title'][:40]}\n    ⏱ {r['duration']} • {r['channel'][:20]}\n\n"
                    buttons.append([InlineKeyboardButton(
                        f"{nums[i]} {r['title'][:45]}",
                        callback_data=f"dl|{r['uid']}"
                    )])
                await query.edit_message_text(result_text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(buttons))
            else:
                await query.edit_message_text(f"❌ '{music_title}' topilmadi. Qo'lda qidiring!")
        else:
            await query.edit_message_text(
                "❌ Musiqa nomi aniqlanmadi.\n\n"
                "Qo'shiq nomini qo'lda yozing:",
            )

    elif data.startswith("dl|"):
        uid = data.split("|")[1]
        url = id_to_url(uid)
        if not url:
            await query.answer("❌ Muddati otgan. Qayta qidiring.", show_alert=True)
            return
        await download_audio(chat_id, url, "Qoshiq", context, user_id, user_obj)

    elif data.startswith("vid|"):
        uid = data.split("|")[1]
        url = id_to_url(uid)
        if not url:
            await query.answer("❌ Muddati otgan. Qayta qidiring.", show_alert=True)
            return
        platform = detect_platform(url) or "other"
        await download_video(chat_id, url, context, platform)

    elif data.startswith("fav|"):
        parts = data.split("|")
        uid = parts[1]
        title = parts[2] if len(parts) > 2 else "Qoshiq"
        url = id_to_url(uid)
        if not url:
            await query.answer("❌ Muddati otgan.", show_alert=True)
            return
        db = load_db()
        user = get_user(db, user_id, user_obj)
        if not any(f.get("uid") == uid for f in user["favorites"]):
            user["favorites"].insert(0, {"title": title, "uid": uid, "url": url})
            user["favorites"] = user["favorites"][:50]
            save_db(db)
            await query.answer("❤️ Sevimlilarga qoshildi!", show_alert=True)
        else:
            await query.answer("Allaqachon sevimlilar royxatida!", show_alert=True)

    elif data == "my_fav":
        db = load_db()
        user = get_user(db, user_id, user_obj)
        favs = user["favorites"]
        if not favs:
            await query.edit_message_text("❤️ Sevimlilar royxatingiz bosh.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Orqaga", callback_data="back")]]))
        else:
            text = "❤️ *Sevimlilar:*\n\n"
            buttons = []
            for i, fav in enumerate(favs[:10]):
                text += f"{i+1}. {fav['title'][:45]}\n"
                buttons.append([InlineKeyboardButton(f"▶️ {fav['title'][:40]}", callback_data=f"dl|{fav['uid']}")])
            buttons.append([InlineKeyboardButton("🗑 Tozalash", callback_data="clr_fav"),
                            InlineKeyboardButton("🔙 Orqaga", callback_data="back")])
            await query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(buttons))

    elif data == "clr_fav":
        db = load_db()
        user = get_user(db, user_id, user_obj)
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
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Orqaga", callback_data="back")]]))

    elif data == "history":
        db = load_db()
        user = get_user(db, user_id, user_obj)
        history = user["history"]
        if not history:
            await query.edit_message_text("📜 Tarix bosh.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Orqaga", callback_data="back")]]))
        else:
            text = "📜 *Tarix:*\n\n"
            buttons = []
            for i, item in enumerate(history[:10]):
                text += f"{i+1}. {item['title'][:45]}\n"
                uid = url_to_id(item["url"])
                buttons.append([InlineKeyboardButton(f"▶️ {item['title'][:40]}", callback_data=f"dl|{uid}")])
            buttons.append([InlineKeyboardButton("🔙 Orqaga", callback_data="back")])
            await query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(buttons))

    elif data == "settings":
        db = load_db()
        user = get_user(db, user_id, user_obj)
        cnt = user["settings"]["results"]
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(f"{'✅' if cnt==5 else '5️⃣'} 5 ta", callback_data="sr5"),
             InlineKeyboardButton(f"{'✅' if cnt==10 else '🔟'} 10 ta", callback_data="sr10")],
            [InlineKeyboardButton("🔙 Orqaga", callback_data="back")],
        ])
        await query.edit_message_text(f"⚙️ *Sozlamalar*\n\nNatijalar soni: *{cnt} ta*",
            parse_mode="Markdown", reply_markup=keyboard)

    elif data in ["sr5", "sr10"]:
        count = int(data[2:])
        db = load_db()
        user = get_user(db, user_id, user_obj)
        user["settings"]["results"] = count
        save_db(db)
        await query.answer(f"✅ {count} ta natija!", show_alert=True)

    elif data == "help":
        await query.edit_message_text(
            "ℹ️ *Yordam*\n\n"
            "📥 *Link yuborish:*\n"
            "• YouTube → MP3 yoki Video\n"
            "• Instagram → To'liq musiqa / Videodagi musiqa / Video\n"
            "• TikTok → Suvsiz video\n"
            "• Snapchat, Pinterest, Likee → Video\n\n"
            "🎤 *Qidirish:*\n"
            "• Qoshiq nomi yozing\n"
            "• SoundCloud + YouTube dan topadi\n\n"
            "📌 *Buyruqlar:*\n"
            "/start /top /favorites /history /stats /admin",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Orqaga", callback_data="back")]]))

    elif data == "back":
        await query.edit_message_text(
            "🎵 *Bosh menyu*\n\nLink yuboring yoki qoshiq nomi yozing!",
            parse_mode="Markdown", reply_markup=main_keyboard())

    elif data == "admin_stats":
        if user_id != ADMIN_ID:
            return
        db = load_db()
        top = load_top()
        total_downloads = sum(u.get("downloads", 0) for u in db.values())
        top5 = sorted(top.values(), key=lambda x: x["count"], reverse=True)[:5]
        text = f"📊 *Batafsil statistika:*\n\n"
        text += f"👥 Foydalanuvchilar: *{len(db)} ta*\n"
        text += f"⬇️ Jami yuklanmalar: *{total_downloads} ta*\n"
        text += f"🎵 Jami qoshiqlar: *{len(top)} ta*\n\n"
        text += f"🔥 *Top 5:*\n"
        for i, item in enumerate(top5):
            text += f"{i+1}. {item['title'][:35]} — {item['count']}x\n"
        await query.edit_message_text(text, parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Orqaga", callback_data="back")]]))

    elif data == "admin_users":
        if user_id != ADMIN_ID:
            return
        db = load_db()
        text = f"👥 *Foydalanuvchilar ({len(db)} ta):*\n\n"
        for uid, u in list(db.items())[-20:]:
            name = u.get("name", "?")
            username = u.get("username", "")
            downloads = u.get("downloads", 0)
            text += f"• {name} {username} — {downloads} ta\n"
        await query.edit_message_text(text, parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Orqaga", callback_data="back")]]))

# ─── COMMANDS ─────────────────────────────────────────────────────────────────
async def admin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Siz admin emassiz!")
        return
    db = load_db()
    top = load_top()
    total_users = len(db)
    total_downloads = sum(u.get("downloads", 0) for u in db.values())
    text = f"👑 *Admin Panel*\n\n"
    text += f"👥 Foydalanuvchilar: *{total_users} ta*\n"
    text += f"⬇️ Jami yuklanmalar: *{total_downloads} ta*\n"
    text += f"🎵 Jami qoshiqlar: *{len(top)} ta*\n\n"
    text += f"📋 *So'nggi 10 foydalanuvchi:*\n"
    for uid, u in list(db.items())[-10:]:
        name = u.get("name", "?")
        username = u.get("username", "")
        downloads = u.get("downloads", 0)
        joined = u.get("joined", "?")
        text += f"• {name} {username} — {downloads} ta ({joined})\n"
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Statistika", callback_data="admin_stats"),
         InlineKeyboardButton("👥 Userlar", callback_data="admin_users")],
    ])
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=keyboard)

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
    user = get_user(db, update.effective_user.id, update.effective_user)
    favs = user["favorites"]
    if not favs:
        await update.message.reply_text("❤️ Sevimlilar royxatingiz bosh.")
        return
    text = "❤️ *Sevimlilar:*\n\n"
    buttons = []
    for i, fav in enumerate(favs[:10]):
        text += f"{i+1}. {fav['title'][:45]}\n"
        buttons.append([InlineKeyboardButton(f"▶️ {fav['title'][:40]}", callback_data=f"dl|{fav['uid']}")])
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(buttons))

async def history_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db = load_db()
    user = get_user(db, update.effective_user.id, update.effective_user)
    history = user["history"]
    if not history:
        await update.message.reply_text("📜 Tarix bosh.")
        return
    text = "📜 *Tarix:*\n\n"
    buttons = []
    for i, item in enumerate(history[:10]):
        text += f"{i+1}. {item['title'][:45]}\n"
        uid = url_to_id(item["url"])
        buttons.append([InlineKeyboardButton(f"▶️ {item['title'][:40]}", callback_data=f"dl|{uid}")])
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(buttons))

async def stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db = load_db()
    user = get_user(db, update.effective_user.id, update.effective_user)
    top = load_top()
    await update.message.reply_text(
        f"📊 *Statistika:*\n\n"
        f"⬇️ Siz yuklagan: *{user['downloads']} ta*\n"
        f"❤️ Sevimlilar: *{len(user['favorites'])} ta*\n"
        f"📜 Tarix: *{len(user['history'])} ta*\n\n"
        f"🌍 *Umumiy:*\n"
        f"🎵 Jami: *{len(top)} ta*\n"
        f"⬇️ Yuklanmalar: *{sum(v['count'] for v in top.values())} ta*",
        parse_mode="Markdown"
    )

# ─── MAIN ─────────────────────────────────────────────────────────────────────
def main():
    app = (
        ApplicationBuilder()
        .token(TOKEN)
        .read_timeout(120)
        .write_timeout(120)
        .connect_timeout(60)
        .pool_timeout(60)
        .build()
    )
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("top", top_cmd))
    app.add_handler(CommandHandler("favorites", favorites_cmd))
    app.add_handler(CommandHandler("history", history_cmd))
    app.add_handler(CommandHandler("stats", stats_cmd))
    app.add_handler(CommandHandler("admin", admin_cmd))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.VOICE | filters.VIDEO_NOTE, handle_voice))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    print("🎵 MusicBot ishga tushdi ✅")
    app.run_polling()

if __name__ == "__main__":
    main()














