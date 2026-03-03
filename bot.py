import os
import json
import re
import hashlib
import requests
import yt_dlp
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters,
)

TOKEN = "8312461995:AAExjPqVRhrHvhBQVi4XALAn-cNyM5RZsYw"
YT_API_KEY = "AIzaSyCTHPm3oLBd-vXhl1JH9rEYOvbt1USOvzg"
ADMIN_ID = 6705765282
URL_CACHE = {}
DB_FILE = "/tmp/users.json"
TOP_FILE = "/tmp/top.json"

def url_to_id(url):
    uid = hashlib.md5(url.encode()).hexdigest()[:12]
    URL_CACHE[uid] = url
    return uid

def id_to_url(uid):
    return URL_CACHE.get(uid, "")

def load_db():
    try:
        if os.path.exists(DB_FILE):
            with open(DB_FILE) as f: return json.load(f)
    except: pass
    return {}

def save_db(db):
    try:
        with open(DB_FILE, "w") as f: json.dump(db, f, ensure_ascii=False, indent=2)
    except: pass

def get_user(db, user_id, user_obj=None):
    import datetime
    uid = str(user_id)
    if uid not in db:
        db[uid] = {
            "favorites": [], "history": [], "settings": {"results": 10},
            "downloads": 0,
            "name": user_obj.full_name if user_obj else "Noma lum",
            "username": ("@" + user_obj.username) if user_obj and user_obj.username else "",
            "joined": datetime.datetime.now().strftime("%Y-%m-%d"),
        }
    return db[uid]

def load_top():
    try:
        if os.path.exists(TOP_FILE):
            with open(TOP_FILE) as f: return json.load(f)
    except: pass
    return {}

def save_top(top):
    try:
        with open(TOP_FILE, "w") as f: json.dump(top, f, ensure_ascii=False, indent=2)
    except: pass

def increment_top(title, url):
    top = load_top()
    if url not in top: top[url] = {"title": title, "count": 0}
    top[url]["count"] += 1
    save_top(top)

def detect_platform(url):
    if re.search(r"youtube\.com|youtu\.be", url): return "youtube"
    if re.search(r"instagram\.com", url): return "instagram"
    if re.search(r"tiktok\.com", url): return "tiktok"
    if re.search(r"snapchat\.com", url): return "snapchat"
    if re.search(r"pinterest\.", url): return "pinterest"
    if re.search(r"likee\.", url): return "likee"
    if re.search(r"https?://", url): return "other"
    return None

def search_soundcloud(query, limit=10):
    opts = {"quiet": True, "skip_download": True, "extract_flat": True, "no_warnings": True, "socket_timeout": 15}
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            result = ydl.extract_info("scsearch" + str(limit) + ":" + query, download=False)
            out = []
            for v in result.get("entries", []):
                if v:
                    dur = v.get("duration", 0)
                    sc_url = v.get("webpage_url", "")
                    out.append({"title": v.get("title", "?"), "url": sc_url, "uid": url_to_id(sc_url),
                                "duration": str(dur//60) + ":" + str(dur%60).zfill(2) if dur else "?",
                                "channel": v.get("uploader", "SC"), "source": "SoundCloud"})
            return out
    except: return []

def search_youtube_api(query, limit=5):
    if not YT_API_KEY: return []
    try:
        res = requests.get("https://www.googleapis.com/youtube/v3/search",
            params={"part": "snippet", "q": query, "type": "video", "maxResults": limit, "key": YT_API_KEY}, timeout=8)
        out = []
        for item in res.json().get("items", []):
            vid_id = item["id"]["videoId"]
            yt_url = "https://youtube.com/watch?v=" + vid_id
            out.append({"title": item["snippet"]["title"], "url": yt_url, "uid": url_to_id(yt_url),
                        "duration": "?", "channel": item["snippet"]["channelTitle"], "source": "YouTube"})
        return out
    except: return []

def combine_search(query, limit=10):
    sc = search_soundcloud(query, limit)
    yt = search_youtube_api(query, 5)
    seen = set()
    out = []
    for r in sc + yt:
        if r["title"] not in seen:
            seen.add(r["title"])
            out.append(r)
    return out[:limit]

def get_instagram_music_title(url):
    opts = {"quiet": True, "skip_download": True, "no_warnings": True, "socket_timeout": 15}
    if os.path.exists("/app/cookies.txt"): opts["cookiefile"] = "/app/cookies.txt"
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
            music = info.get("track") or info.get("artist") or info.get("music") or info.get("title", "")
            artist = info.get("artist", "")
            if artist and music and artist not in music: return artist + " - " + music
            return music or info.get("title", "")
    except: return ""

async def download_audio(chat_id, url, title, context, user_id=None, user_obj=None):
    msg = await context.bot.send_message(chat_id=chat_id, text="⏳ Audio yuklanmoqda...")
    outfile = "/tmp/audio_" + str(chat_id)
    opts = {"format": "bestaudio[ext=mp3]/bestaudio[ext=m4a]/bestaudio",
            "outtmpl": outfile + ".%(ext)s", "quiet": True, "no_warnings": True,
            "noplaylist": True, "socket_timeout": 60, "retries": 5}
    if os.path.exists("/app/cookies.txt"): opts["cookiefile"] = "/app/cookies.txt"
    real_title = title
    artist = ""
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            real_title = info.get("title", title)
            artist = info.get("uploader", "")
    except:
        opts2 = {"format": "bestaudio/best", "outtmpl": outfile + ".%(ext)s",
                 "quiet": True, "no_warnings": True, "noplaylist": True, "socket_timeout": 60,
                 "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "128"}]}
        if os.path.exists("/app/cookies.txt"): opts2["cookiefile"] = "/app/cookies.txt"
        try:
            with yt_dlp.YoutubeDL(opts2) as ydl:
                info = ydl.extract_info(url, download=True)
                real_title = info.get("title", title)
                artist = info.get("uploader", "")
        except:
            await msg.edit_text("❌ Yuklashda xatolik.")
            return
    filepath = None
    for ext in ["mp3", "m4a", "webm", "opus", "ogg", "mp4"]:
        p = outfile + "." + ext
        if os.path.exists(p):
            filepath = p
            break
    if not filepath:
        for f in os.listdir("/tmp"):
            if f.startswith("audio_" + str(chat_id)):
                filepath = "/tmp/" + f
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
            InlineKeyboardButton("❤️ Sevimli", callback_data="fav|" + uid + "|" + real_title[:25]),
            InlineKeyboardButton("🎬 Video", callback_data="vid|" + uid),
        ]])
        try:
            with open(filepath, "rb") as audio:
                await context.bot.send_audio(chat_id=chat_id, audio=audio, title=real_title,
                    performer=artist, reply_markup=keyboard, read_timeout=120, write_timeout=120)
        except:
            try:
                with open(filepath, "rb") as doc:
                    await context.bot.send_document(chat_id=chat_id, document=doc,
                        caption="🎵 " + real_title, reply_markup=keyboard, read_timeout=120, write_timeout=120)
            except:
                await msg.edit_text("❌ Yuborishda xatolik.")
                return
        try: os.remove(filepath)
        except: pass
        await msg.delete()
    else:
        await msg.edit_text("❌ Fayl topilmadi.")

async def download_video(chat_id, url, context, platform="other"):
    names = {"youtube": "YouTube", "instagram": "Instagram", "tiktok": "TikTok",
             "snapchat": "Snapchat", "pinterest": "Pinterest", "likee": "Likee", "other": "Video"}
    name = names.get(platform, "Video")
    msg = await context.bot.send_message(chat_id=chat_id, text="🎬 " + name + " yuklanmoqda...")
    outfile = "/tmp/video_" + str(chat_id) + ".mp4"
    opts = {"format": "best[height<=480][filesize<45M]/best[height<=360]/worst",
            "outtmpl": outfile, "quiet": True, "noplaylist": True, "socket_timeout": 60, "retries": 3}
    if os.path.exists("/app/cookies.txt"): opts["cookiefile"] = "/app/cookies.txt"
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            real_title = info.get("title", name)
    except:
        await msg.edit_text("❌ " + name + " yuklashda xatolik.")
        return
    if os.path.exists(outfile):
        try:
            with open(outfile, "rb") as video:
                await context.bot.send_video(chat_id=chat_id, video=video,
                    caption="🎬 " + real_title, read_timeout=120, write_timeout=120)
        except:
            with open(outfile, "rb") as doc:
                await context.bot.send_document(chat_id=chat_id, document=doc, caption="🎬 " + real_title)
        try: os.remove(outfile)
        except: pass
        await msg.delete()
    else:
        await msg.edit_text("❌ Video topilmadi.")

def main_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔍 Qidirish", switch_inline_query_current_chat=""),
         InlineKeyboardButton("❤️ Sevimlilar", callback_data="my_fav")],
        [InlineKeyboardButton("🏆 Top 10", callback_data="top10"),
         InlineKeyboardButton("📜 Tarix", callback_data="history")],
        [InlineKeyboardButton("⚙️ Sozlamalar", callback_data="settings"),
         InlineKeyboardButton("ℹ️ Yordam", callback_data="help")],
    ])

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db = load_db()
    get_user(db, user.id, user)
    save_db(db)
    await update.message.reply_text(
        "🎵 Salom, " + user.first_name + "!\n\n"
        "📥 Yuklab olish:\n"
        "• YouTube — video + audio\n"
        "• Instagram — musiqa qidirish + video\n"
        "• TikTok — suvsiz video\n"
        "• Snapchat, Pinterest, Likee — video\n\n"
        "🎤 Qoshiq qidirish: nom yozing!\n"
        "🔗 Link yuboring yoki qoshiq nomi yozing!",
        reply_markup=main_keyboard()
    )

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    chat_id = update.message.chat_id
    user_id = update.effective_user.id
    user_obj = update.effective_user
    db = load_db()
    get_user(db, user_id, user_obj)
    save_db(db)
    platform = detect_platform(text)
    if platform in ["youtube", "instagram", "tiktok", "snapchat", "pinterest", "likee", "other"]:
        uid = url_to_id(text)
        platform_names = {
            "youtube": "🎬 YouTube", "instagram": "📸 Instagram", "tiktok": "🎵 TikTok",
            "snapchat": "👻 Snapchat", "pinterest": "📌 Pinterest", "likee": "💚 Likee", "other": "🔗 Link"
        }
        name = platform_names.get(platform, "Link")
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🎵 To'liq musiqa", callback_data="ig_music|" + uid)],
            [InlineKeyboardButton("🎵 Videodagi musiqa", callback_data="dl|" + uid)],
            [InlineKeyboardButton("🎬 Videoni yukla", callback_data="vid|" + uid)],
        ])
        await update.message.reply_text(name + " link! Nima kerak?", reply_markup=kb)
        return
    db = load_db()
    user = get_user(db, user_id, user_obj)
    limit = user["settings"]["results"]
    msg = await update.message.reply_text("🔍 " + text + " qidirilmoqda...")
    try:
        results = combine_search(text, limit)
    except:
        await msg.edit_text("❌ Xatolik yuz berdi.")
        return
    if not results:
        await msg.edit_text("❌ Hech narsa topilmadi.")
        return
    nums = ["1️⃣","2️⃣","3️⃣","4️⃣","5️⃣","6️⃣","7️⃣","8️⃣","9️⃣","🔟"]
    result_text = "🎵 " + text + " natijalari:\n\n"
    buttons = []
    for i, r in enumerate(results[:10]):
        result_text += nums[i] + " " + r["source"] + " | " + r["title"][:40] + "\n    " + r["duration"] + " | " + r["channel"][:20] + "\n\n"
        buttons.append([InlineKeyboardButton(nums[i] + " " + r["title"][:45], callback_data="dl|" + r["uid"])])
    await msg.edit_text(result_text, reply_markup=InlineKeyboardMarkup(buttons))

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🎤 Hozircha ovozli qidirish mavjud emas. Qoshiq nomini yozing!")

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = update.effective_user.id
    user_obj = update.effective_user
    chat_id = query.message.chat_id

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
                result_text = "🎵 " + music_title + " natijalari:\n\n"
                buttons = []
                for i, r in enumerate(results[:10]):
                    result_text += nums[i] + " " + r["source"] + " | " + r["title"][:40] + "\n    " + r["duration"] + " | " + r["channel"][:20] + "\n\n"
                    buttons.append([InlineKeyboardButton(nums[i] + " " + r["title"][:45], callback_data="dl|" + r["uid"])])
                await query.edit_message_text(result_text, reply_markup=InlineKeyboardMarkup(buttons))
            else:
                await query.edit_message_text("❌ " + music_title + " topilmadi. Qolda yozing:")
        else:
            await query.edit_message_text("❌ Musiqa nomi aniqlanmadi.\n\nQoshiq nomini qolda yozing:")

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
            text = "❤️ Sevimlilar:\n\n"
            buttons = []
            for i, fav in enumerate(favs[:10]):
                text += str(i+1) + ". " + fav["title"][:45] + "\n"
                buttons.append([InlineKeyboardButton("▶️ " + fav["title"][:40], callback_data="dl|" + fav["uid"])])
            buttons.append([InlineKeyboardButton("🗑 Tozalash", callback_data="clr_fav"),
                            InlineKeyboardButton("🔙 Orqaga", callback_data="back")])
            await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons))

    elif data == "clr_fav":
        db = load_db()
        user = get_user(db, user_id, user_obj)
        user["favorites"] = []
        save_db(db)
        await query.edit_message_text("🗑 Sevimlilar tozalandi.")

    elif data == "top10":
        top = load_top()
        if not top:
            txt = "🏆 Hali yuklanmagan qoshiqlar yoq."
        else:
            sorted_top = sorted(top.values(), key=lambda x: x["count"], reverse=True)[:10]
            nums = ["1️⃣","2️⃣","3️⃣","4️⃣","5️⃣","6️⃣","7️⃣","8️⃣","9️⃣","🔟"]
            txt = "🏆 TOP 10:\n\n"
            for i, item in enumerate(sorted_top):
                txt += nums[i] + " " + item["title"][:40] + " — " + str(item["count"]) + "x\n"
        await query.edit_message_text(txt,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Orqaga", callback_data="back")]]))

    elif data == "history":
        db = load_db()
        user = get_user(db, user_id, user_obj)
        history = user["history"]
        if not history:
            await query.edit_message_text("📜 Tarix bosh.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Orqaga", callback_data="back")]]))
        else:
            txt = "📜 Tarix:\n\n"
            buttons = []
            for i, item in enumerate(history[:10]):
                txt += str(i+1) + ". " + item["title"][:45] + "\n"
                uid = url_to_id(item["url"])
                buttons.append([InlineKeyboardButton("▶️ " + item["title"][:40], callback_data="dl|" + uid)])
            buttons.append([InlineKeyboardButton("🔙 Orqaga", callback_data="back")])
            await query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup(buttons))

    elif data == "settings":
        db = load_db()
        user = get_user(db, user_id, user_obj)
        cnt = user["settings"]["results"]
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ 5 ta" if cnt==5 else "5 ta", callback_data="sr5"),
             InlineKeyboardButton("✅ 10 ta" if cnt==10 else "10 ta", callback_data="sr10")],
            [InlineKeyboardButton("🔙 Orqaga", callback_data="back")],
        ])
        await query.edit_message_text("Sozlamalar\n\nNatijalar soni: " + str(cnt) + " ta", reply_markup=kb)

    elif data in ["sr5", "sr10"]:
        count = int(data[2:])
        db = load_db()
        user = get_user(db, user_id, user_obj)
        user["settings"]["results"] = count
        save_db(db)
        await query.answer("✅ " + str(count) + " ta natija!", show_alert=True)

    elif data == "help":
        await query.edit_message_text(
            "Yordam\n\n"
            "Link yuborish:\n"
            "• YouTube — MP3 yoki Video\n"
            "• Instagram — Musiqani qidirish / Video\n"
            "• TikTok — Suvsiz video\n"
            "• Snapchat, Pinterest, Likee — Video\n\n"
            "Qidirish:\n"
            "Qoshiq nomi yozing — SoundCloud + YouTube dan topadi\n\n"
            "Buyruqlar: /start /top /favorites /history /stats /admin",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Orqaga", callback_data="back")]]))

    elif data == "back":
        await query.edit_message_text("🎵 Bosh menyu\n\nLink yuboring yoki qoshiq nomi yozing!",
            reply_markup=main_keyboard())

    elif data == "admin_stats":
        if user_id != ADMIN_ID: return
        db = load_db()
        top = load_top()
        total_dl = sum(u.get("downloads", 0) for u in db.values())
        top5 = sorted(top.values(), key=lambda x: x["count"], reverse=True)[:5]
        txt = "Batafsil statistika:\n\n"
        txt += "Foydalanuvchilar: " + str(len(db)) + " ta\n"
        txt += "Jami yuklanmalar: " + str(total_dl) + " ta\n"
        txt += "Jami qoshiqlar: " + str(len(top)) + " ta\n\nTop 5:\n"
        for i, item in enumerate(top5):
            txt += str(i+1) + ". " + item["title"][:35] + " — " + str(item["count"]) + "x\n"
        await query.edit_message_text(txt,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Orqaga", callback_data="back")]]))

    elif data == "admin_users":
        if user_id != ADMIN_ID: return
        db = load_db()
        txt = "Foydalanuvchilar (" + str(len(db)) + " ta):\n\n"
        for uid, u in list(db.items())[-20:]:
            txt += "• " + u.get("name","?") + " " + u.get("username","") + " — " + str(u.get("downloads",0)) + " ta\n"
        await query.edit_message_text(txt,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Orqaga", callback_data="back")]]))

async def admin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Siz admin emassiz!")
        return
    db = load_db()
    top = load_top()
    total_dl = sum(u.get("downloads", 0) for u in db.values())
    txt = "👑 Admin Panel\n\n"
    txt += "Foydalanuvchilar: " + str(len(db)) + " ta\n"
    txt += "Jami yuklanmalar: " + str(total_dl) + " ta\n"
    txt += "Jami qoshiqlar: " + str(len(top)) + " ta\n\n"
    txt += "Songi 10 foydalanuvchi:\n"
    for uid, u in list(db.items())[-10:]:
        txt += "• " + u.get("name","?") + " " + u.get("username","") + " — " + str(u.get("downloads",0)) + " ta (" + u.get("joined","?") + ")\n"
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("📊 Statistika", callback_data="admin_stats"),
        InlineKeyboardButton("👥 Userlar", callback_data="admin_users"),
    ]])
    await update.message.reply_text(txt, reply_markup=kb)

async def top_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    top = load_top()
    if not top:
        await update.message.reply_text("🏆 Hali yuklanmagan qoshiqlar yoq.")
        return
    sorted_top = sorted(top.values(), key=lambda x: x["count"], reverse=True)[:10]
    nums = ["1️⃣","2️⃣","3️⃣","4️⃣","5️⃣","6️⃣","7️⃣","8️⃣","9️⃣","🔟"]
    txt = "🏆 TOP 10:\n\n"
    for i, item in enumerate(sorted_top):
        txt += nums[i] + " " + item["title"][:40] + " — " + str(item["count"]) + "x\n"
    await update.message.reply_text(txt)

async def favorites_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db = load_db()
    user = get_user(db, update.effective_user.id, update.effective_user)
    favs = user["favorites"]
    if not favs:
        await update.message.reply_text("❤️ Sevimlilar royxatingiz bosh.")
        return
    txt = "❤️ Sevimlilar:\n\n"
    buttons = []
    for i, fav in enumerate(favs[:10]):
        txt += str(i+1) + ". " + fav["title"][:45] + "\n"
        buttons.append([InlineKeyboardButton("▶️ " + fav["title"][:40], callback_data="dl|" + fav["uid"])])
    await update.message.reply_text(txt, reply_markup=InlineKeyboardMarkup(buttons))

async def history_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db = load_db()
    user = get_user(db, update.effective_user.id, update.effective_user)
    history = user["history"]
    if not history:
        await update.message.reply_text("📜 Tarix bosh.")
        return
    txt = "📜 Tarix:\n\n"
    buttons = []
    for i, item in enumerate(history[:10]):
        txt += str(i+1) + ". " + item["title"][:45] + "\n"
        uid = url_to_id(item["url"])
        buttons.append([InlineKeyboardButton("▶️ " + item["title"][:40], callback_data="dl|" + uid)])
    await update.message.reply_text(txt, reply_markup=InlineKeyboardMarkup(buttons))

async def stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db = load_db()
    user = get_user(db, update.effective_user.id, update.effective_user)
    top = load_top()
    await update.message.reply_text(
        "📊 Statistika:\n\n"
        "Siz yuklagan: " + str(user["downloads"]) + " ta\n"
        "Sevimlilar: " + str(len(user["favorites"])) + " ta\n"
        "Tarix: " + str(len(user["history"])) + " ta\n\n"
        "Umumiy:\n"
        "Jami qoshiqlar: " + str(len(top)) + " ta\n"
        "Yuklanmalar: " + str(sum(v["count"] for v in top.values())) + " ta"
    )

def main():
    app = (ApplicationBuilder().token(TOKEN)
        .read_timeout(120).write_timeout(120)
        .connect_timeout(60).pool_timeout(60).build())
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
















