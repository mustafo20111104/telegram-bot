import os
import json
import re
import hashlib
import requests
import yt_dlp
import time
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

# ─── UTILS ────────────────────────────────────────────────────────────────────
def url_to_id(url):
    uid = hashlib.md5(url.encode()).hexdigest()[:12]
    URL_CACHE[uid] = url
    return uid

def id_to_url(uid):
    return URL_CACHE.get(uid, "")

def fmt_dur(seconds):
    if not seconds:
        return ""
    try:
        s = int(float(seconds))
        m, s = divmod(s, 60)
        h, m = divmod(m, 60)
        if h:
            return f"{h}:{m:02d}:{s:02d}"
        return f"{m}:{s:02d}"
    except:
        return ""

# ─── DATABASE ─────────────────────────────────────────────────────────────────
def load_db():
    try:
        if os.path.exists(DB_FILE):
            with open(DB_FILE) as f:
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
    import datetime
    uid = str(user_id)
    if uid not in db:
        db[uid] = {
            "favorites": [], "history": [],
            "settings": {"results": 10},
            "downloads": 0,
            "name": user_obj.full_name if user_obj else "Noma'lum",
            "username": ("@" + user_obj.username) if user_obj and user_obj.username else "",
            "joined": datetime.datetime.now().strftime("%Y-%m-%d"),
        }
    return db[uid]

def load_top():
    try:
        if os.path.exists(TOP_FILE):
            with open(TOP_FILE) as f:
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

# ─── PLATFORM DETECT ──────────────────────────────────────────────────────────
def detect_platform(url):
    if re.search(r"youtube\.com|youtu\.be", url): return "youtube"
    if re.search(r"instagram\.com", url): return "instagram"
    if re.search(r"tiktok\.com", url): return "tiktok"
    if re.search(r"snapchat\.com", url): return "snapchat"
    if re.search(r"pinterest\.", url): return "pinterest"
    if re.search(r"likee\.", url): return "likee"
    if re.search(r"https?://", url): return "other"
    return None

# ─── SEARCH ───────────────────────────────────────────────────────────────────
def search_youtube_music(query, limit=10):
    """YouTube Music orqali qidirish - eng yaxshi natija"""
    opts = {
        "quiet": True, "skip_download": True,
        "extract_flat": True, "no_warnings": True,
        "socket_timeout": 15,
    }
    results = []
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            data = ydl.extract_info(f"ytmsearch{limit}:{query}", download=False)
            for v in data.get("entries", []):
                if not v:
                    continue
                dur = v.get("duration", 0)
                yt_url = v.get("webpage_url") or f"https://youtube.com/watch?v={v.get('id','')}"
                results.append({
                    "title": v.get("title", "?"),
                    "artist": v.get("uploader", v.get("channel", "")),
                    "url": yt_url,
                    "uid": url_to_id(yt_url),
                    "duration": fmt_dur(dur),
                    "thumb": v.get("thumbnail", ""),
                })
    except:
        pass
    return results

def search_soundcloud(query, limit=10):
    """SoundCloud dan qidirish"""
    opts = {
        "quiet": True, "skip_download": True,
        "extract_flat": True, "no_warnings": True,
        "socket_timeout": 15,
    }
    results = []
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            data = ydl.extract_info(f"scsearch{limit}:{query}", download=False)
            for v in data.get("entries", []):
                if not v:
                    continue
                dur = v.get("duration", 0)
                sc_url = v.get("webpage_url", "")
                results.append({
                    "title": v.get("title", "?"),
                    "artist": v.get("uploader", ""),
                    "url": sc_url,
                    "uid": url_to_id(sc_url),
                    "duration": fmt_dur(dur),
                    "thumb": v.get("thumbnail", ""),
                })
    except:
        pass
    return results

def search_youtube_api(query, limit=5):
    """YouTube API orqali qidirish"""
    if not YT_API_KEY:
        return []
    try:
        res = requests.get(
            "https://www.googleapis.com/youtube/v3/search",
            params={"part": "snippet", "q": query, "type": "video",
                    "videoCategoryId": "10",
                    "maxResults": limit, "key": YT_API_KEY},
            timeout=8
        )
        results = []
        for item in res.json().get("items", []):
            vid_id = item["id"]["videoId"]
            yt_url = f"https://youtube.com/watch?v={vid_id}"
            results.append({
                "title": item["snippet"]["title"],
                "artist": item["snippet"]["channelTitle"],
                "url": yt_url,
                "uid": url_to_id(yt_url),
                "duration": "",
                "thumb": item["snippet"]["thumbnails"]["default"]["url"],
            })
        return results
    except:
        return []

def combine_search(query, limit=10):
    """YouTube Music + SoundCloud + YouTube API birlashtirilgan qidiruv"""
    ym = search_youtube_music(query, limit)
    sc = search_soundcloud(query, limit // 2)
    yt = search_youtube_api(query, 3)

    seen = set()
    combined = []
    for r in ym + sc + yt:
        key = r["title"].lower().strip()
        if key not in seen:
            seen.add(key)
            combined.append(r)
    return combined[:limit]

# ─── INSTAGRAM MUSIC ──────────────────────────────────────────────────────────
def get_instagram_music_title(url):
    opts = {"quiet": True, "skip_download": True, "no_warnings": True, "socket_timeout": 15}
    if os.path.exists("/app/cookies.txt"):
        opts["cookiefile"] = "/app/cookies.txt"
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
            music = info.get("track") or info.get("music") or info.get("title", "")
            artist = info.get("artist", "")
            if artist and music and artist not in music:
                return f"{artist} - {music}"
            return music or info.get("title", "")
    except:
        return ""

# ─── FORMAT RESULTS ───────────────────────────────────────────────────────────
def format_results(results):
    """Natijalarni Tune Hunt uslubida formatlash"""
    nums = ["1️⃣","2️⃣","3️⃣","4️⃣","5️⃣","6️⃣","7️⃣","8️⃣","9️⃣","🔟"]
    text = "🎵 Natijalar:\n\n"
    buttons = []
    for i, r in enumerate(results[:10]):
        dur = r.get("duration", "")
        artist = r.get("artist", "")
        title = r["title"][:45]
        line = nums[i] + " " + title
        if artist:
            line += " — " + artist[:20]
        if dur:
            line += " [" + dur + "]"
        text += line + "\n"
        btn = nums[i] + " " + r["title"][:35]
        if dur:
            btn += " [" + dur + "]"
        buttons.append([InlineKeyboardButton(btn, callback_data="dl|" + r["uid"])])
    return text, buttons

# ─── DOWNLOAD AUDIO ───────────────────────────────────────────────────────────
async def download_audio(chat_id, url, title, context, user_id=None, user_obj=None):
    msg = await context.bot.send_message(chat_id=chat_id, text="⏳ Yuklanmoqda...")
    outfile = "/tmp/audio_" + str(chat_id)

    # Eski fayllarni tozalash
    for ext in ["mp3", "m4a", "webm", "opus", "ogg", "mp4"]:
        p = outfile + "." + ext
        if os.path.exists(p):
            try: os.remove(p)
            except: pass

    # FFmpeg bor yoki yo'qligini tekshirish
    import shutil
    has_ffmpeg = shutil.which("ffmpeg") is not None

    opts = {
        "format": "bestaudio[ext=mp3]/bestaudio[ext=m4a]/bestaudio",
        "outtmpl": outfile + ".%(ext)s",
        "quiet": True, "no_warnings": True,
        "noplaylist": True, "socket_timeout": 60, "retries": 5,
    }
    if has_ffmpeg:
        opts["postprocessors"] = [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "192",
        }]
    if os.path.exists("/app/cookies.txt"):
        opts["cookiefile"] = "/app/cookies.txt"

    real_title = title
    artist = ""
    thumb_url = ""

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            real_title = info.get("title", title)
            artist = info.get("uploader", info.get("artist", ""))
            thumb_url = info.get("thumbnail", "")
    except Exception as e:
        await msg.edit_text("❌ Yuklashda xatolik: " + str(e)[:100])
        return

    # mp3 fayl izlash
    filepath = outfile + ".mp3"
    if not os.path.exists(filepath):
        for ext in ["m4a", "webm", "opus", "ogg", "mp4"]:
            p = outfile + "." + ext
            if os.path.exists(p):
                filepath = p
                break

    if not filepath or not os.path.exists(filepath):
        for f in os.listdir("/tmp"):
            if f.startswith("audio_" + str(chat_id)):
                filepath = "/tmp/" + f
                break

    if filepath and os.path.exists(filepath):
        fsize = os.path.getsize(filepath)
        if fsize > 50 * 1024 * 1024:
            await msg.edit_text("❌ Fayl juda katta (50MB dan oshdi).")
            try: os.remove(filepath)
            except: pass
            return

        increment_top(real_title, url)
        if user_id:
            db = load_db()
            user = get_user(db, user_id, user_obj)
            user["downloads"] += 1
            h = {"title": real_title, "url": url}
            if h not in user["history"]:
                user["history"].insert(0, h)
                user["history"] = user["history"][:20]
            save_db(db)

        uid = url_to_id(url)
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("❤️ Sevimli", callback_data="fav|" + uid + "|" + real_title[:25]),
            InlineKeyboardButton("🎬 Video", callback_data="vid|" + uid),
        ]])

        try:
            with open(filepath, "rb") as audio:
                await context.bot.send_audio(
                    chat_id=chat_id, audio=audio,
                    title=real_title, performer=artist,
                    reply_markup=keyboard,
                    read_timeout=120, write_timeout=120,
                )
        except Exception as e:
            try:
                with open(filepath, "rb") as doc:
                    await context.bot.send_document(
                        chat_id=chat_id, document=doc,
                        caption="🎵 " + real_title,
                        reply_markup=keyboard,
                    )
            except:
                await msg.edit_text("❌ Yuborishda xatolik.")
                return
        try: os.remove(filepath)
        except: pass
        await msg.delete()
    else:
        await msg.edit_text("❌ Fayl topilmadi.")

# ─── DOWNLOAD VIDEO ───────────────────────────────────────────────────────────
async def download_video(chat_id, url, context, platform="other"):
    names = {
        "youtube": "YouTube", "instagram": "Instagram", "tiktok": "TikTok",
        "snapchat": "Snapchat", "pinterest": "Pinterest", "likee": "Likee", "other": "Video"
    }
    name = names.get(platform, "Video")
    msg = await context.bot.send_message(chat_id=chat_id, text="🎬 " + name + " yuklanmoqda...")
    outfile = "/tmp/video_" + str(chat_id) + ".mp4"
    if os.path.exists(outfile):
        try: os.remove(outfile)
        except: pass

    opts = {
        "format": "best[height<=720][filesize<45M]/best[height<=480]/best[height<=360]/worst",
        "outtmpl": outfile, "quiet": True, "noplaylist": True,
        "socket_timeout": 60, "retries": 3,
        "merge_output_format": "mp4",
    }
    if os.path.exists("/app/cookies.txt"):
        opts["cookiefile"] = "/app/cookies.txt"

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            real_title = info.get("title", name)
    except Exception as e:
        await msg.edit_text("❌ " + name + " yuklashda xatolik.")
        return

    if os.path.exists(outfile):
        if os.path.getsize(outfile) > 50 * 1024 * 1024:
            await msg.edit_text("❌ Video juda katta (50MB dan oshdi).")
            try: os.remove(outfile)
            except: pass
            return
        try:
            with open(outfile, "rb") as video:
                await context.bot.send_video(
                    chat_id=chat_id, video=video,
                    caption="🎬 " + real_title,
                    read_timeout=120, write_timeout=120,
                )
        except:
            with open(outfile, "rb") as doc:
                await context.bot.send_document(chat_id=chat_id, document=doc, caption="🎬 " + real_title)
        try: os.remove(outfile)
        except: pass
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

def link_keyboard(uid, platform):
    if platform in ["youtube", "instagram", "tiktok", "snapchat", "pinterest", "likee", "other"]:
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("🎵 To'liq musiqa", callback_data="ig_music|" + uid)],
            [InlineKeyboardButton("🎵 Videodagi musiqa", callback_data="dl|" + uid)],
            [InlineKeyboardButton("🎬 Videoni yukla", callback_data="vid|" + uid)],
        ])
    return None

# ─── /start ───────────────────────────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db = load_db()
    is_new = str(user.id) not in db
    get_user(db, user.id, user)
    save_db(db)
    if is_new:
        await update.message.reply_text(
            "🎵 Salom, " + user.first_name + "! Xush kelibsiz!\n\n"
            "Bu bot orqali:\n"
            "Qo'shiq nomi yozib qidiring yoki\n"
            "YouTube, Instagram, TikTok, Snapchat link yuboring.\n\n"
            "Har bir link uchun:\n"
            "🎵 To'liq musiqa | 🎵 Videodagi musiqa | 🎬 Video",
            reply_markup=main_keyboard()
        )
    else:
        await update.message.reply_text(
            "🎵 Bosh menyu\n\nQo'shiq nomi yozing yoki link yuboring!",
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

    if platform:
        uid = url_to_id(text)
        platform_names = {
            "youtube": "🎬 YouTube", "instagram": "📸 Instagram",
            "tiktok": "🎵 TikTok", "snapchat": "👻 Snapchat",
            "pinterest": "📌 Pinterest", "likee": "💚 Likee", "other": "🔗 Link"
        }
        name = platform_names.get(platform, "Link")
        kb = link_keyboard(uid, platform)
        await update.message.reply_text(name + " — nima kerak?", reply_markup=kb)
        return

    # Qo'shiq qidirish
    db = load_db()
    user = get_user(db, user_id, user_obj)
    limit = user["settings"]["results"]
    msg = await update.message.reply_text("🔍 Qidirilmoqda...")

    try:
        results = combine_search(text, limit)
    except:
        await msg.edit_text("❌ Xatolik yuz berdi.")
        return

    if not results:
        await msg.edit_text("❌ Hech narsa topilmadi.")
        return

    result_text, buttons = format_results(results)
    await msg.edit_text(result_text, reply_markup=InlineKeyboardMarkup(buttons))

# ─── HANDLE VOICE ─────────────────────────────────────────────────────────────
async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🎤 Qo'shiq nomini yozing!")

# ─── CALLBACK ─────────────────────────────────────────────────────────────────
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
            await query.answer("❌ Muddati o'tgan.", show_alert=True)
            return
        await query.edit_message_text("🔍 Musiqa nomi aniqlanmoqda...")
        music_title = get_instagram_music_title(url)
        if music_title:
            results = combine_search(music_title, 10)
            if results:
                result_text, buttons = format_results(results)
                await query.edit_message_text(result_text, reply_markup=InlineKeyboardMarkup(buttons))
            else:
                await query.edit_message_text("❌ " + music_title + " topilmadi. Qo'lda yozing:")
        else:
            await query.edit_message_text("❌ Musiqa nomi aniqlanmadi. Qo'shiq nomini yozing:")

    elif data.startswith("dl|"):
        uid = data.split("|")[1]
        url = id_to_url(uid)
        if not url:
            await query.answer("❌ Muddati o'tgan. Qayta qidiring.", show_alert=True)
            return
        await download_audio(chat_id, url, "Qo'shiq", context, user_id, user_obj)

    elif data.startswith("vid|"):
        uid = data.split("|")[1]
        url = id_to_url(uid)
        if not url:
            await query.answer("❌ Muddati o'tgan.", show_alert=True)
            return
        platform = detect_platform(url) or "other"
        await download_video(chat_id, url, context, platform)

    elif data.startswith("fav|"):
        parts = data.split("|")
        uid = parts[1]
        title = parts[2] if len(parts) > 2 else "Qo'shiq"
        url = id_to_url(uid)
        if not url:
            await query.answer("❌ Muddati o'tgan.", show_alert=True)
            return
        db = load_db()
        user = get_user(db, user_id, user_obj)
        if not any(f.get("uid") == uid for f in user["favorites"]):
            user["favorites"].insert(0, {"title": title, "uid": uid, "url": url})
            user["favorites"] = user["favorites"][:50]
            save_db(db)
            await query.answer("❤️ Sevimlilarga qo'shildi!", show_alert=True)
        else:
            await query.answer("Allaqachon sevimlilar ro'yxatida!", show_alert=True)

    elif data == "my_fav":
        db = load_db()
        user = get_user(db, user_id, user_obj)
        favs = user["favorites"]
        if not favs:
            await query.edit_message_text("❤️ Sevimlilar ro'yxati bo'sh.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Orqaga", callback_data="back")]]))
        else:
            txt = "❤️ Sevimlilar:\n\n"
            buttons = []
            for i, fav in enumerate(favs[:10]):
                txt += str(i+1) + ". " + fav["title"][:45] + "\n"
                buttons.append([InlineKeyboardButton("▶️ " + fav["title"][:40], callback_data="dl|" + fav["uid"])])
            buttons.append([
                InlineKeyboardButton("🗑 Tozalash", callback_data="clr_fav"),
                InlineKeyboardButton("🔙 Orqaga", callback_data="back")
            ])
            await query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup(buttons))

    elif data == "clr_fav":
        db = load_db()
        user = get_user(db, user_id, user_obj)
        user["favorites"] = []
        save_db(db)
        await query.edit_message_text("🗑 Sevimlilar tozalandi.")

    elif data == "top10":
        top = load_top()
        if not top:
            txt = "🏆 Hali yuklanmagan qo'shiqlar yo'q."
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
            await query.edit_message_text("📜 Tarix bo'sh.",
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
            "YouTube, Instagram, TikTok, Snapchat, Pinterest, Likee\n\n"
            "Har biri uchun:\n"
            "• To'liq musiqa — musiqa nomini aniqlab qidiradi\n"
            "• Videodagi musiqa — videodan audio chiqaradi\n"
            "• Videoni yukla — videoni yuboradi\n\n"
            "Qo'shiq qidirish:\n"
            "Nom yozing — YouTube Music + SoundCloud dan topadi\n\n"
            "Buyruqlar: /start /top /favorites /history /stats /admin",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Orqaga", callback_data="back")]]))

    elif data == "back":
        await query.edit_message_text(
            "🎵 Bosh menyu\n\nQo'shiq nomi yozing yoki link yuboring!",
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
        txt += "Jami qo'shiqlar: " + str(len(top)) + " ta\n\nTop 5:\n"
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

# ─── COMMANDS ─────────────────────────────────────────────────────────────────
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
    txt += "Jami qo'shiqlar: " + str(len(top)) + " ta\n\n"
    txt += "So'nggi 10 foydalanuvchi:\n"
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
        await update.message.reply_text("🏆 Hali yuklanmagan qo'shiqlar yo'q.")
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
        await update.message.reply_text("❤️ Sevimlilar ro'yxati bo'sh.")
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
        await update.message.reply_text("📜 Tarix bo'sh.")
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
        "Jami qo'shiqlar: " + str(len(top)) + " ta\n"
        "Yuklanmalar: " + str(sum(v["count"] for v in top.values())) + " ta"
    )

# ─── ERROR HANDLER ────────────────────────────────────────────────────────────
async def error_handler(update, context):
    print("⚠️ Xato: " + str(context.error))

# ─── MAIN ─────────────────────────────────────────────────────────────────────
def main():
    while True:
        try:
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
            app.add_error_handler(error_handler)
            print("🎵 MusicBot ishga tushdi!")
            app.run_polling(drop_pending_updates=True)
        except Exception as e:
            print("❌ Xato: " + str(e))
            print("🔄 5 soniyadan keyin qayta uriniladi...")
            time.sleep(5)

if __name__ == "__main__":
    main()


















