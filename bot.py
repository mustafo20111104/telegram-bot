import os
import json
import re
import hashlib
import requests
import yt_dlp
import time
import tempfile
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
CACHE_FILE = "/tmp/url_cache.json"

# ─── UTILS ────────────────────────────────────────────────────────────────────
def load_cache():
    global URL_CACHE
    try:
        if os.path.exists(CACHE_FILE):
            with open(CACHE_FILE) as f:
                URL_CACHE = json.load(f)
    except:
        URL_CACHE = {}

def save_cache():
    try:
        # Faqat oxirgi 2000 ta URL ni saqlash
        items = list(URL_CACHE.items())[-2000:]
        with open(CACHE_FILE, "w") as f:
            json.dump(dict(items), f)
    except:
        pass

def url_to_id(url):
    uid = hashlib.md5(url.encode()).hexdigest()[:12]
    URL_CACHE[uid] = url
    save_cache()
    return uid

def id_to_url(uid):
    if uid not in URL_CACHE:
        load_cache()
    return URL_CACHE.get(uid, "")

def fmt_dur(seconds):
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

# ─── SEARCH FUNCTIONS ─────────────────────────────────────────────────────────
def search_soundcloud(query, limit=10):
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
                if not v: continue
                sc_url = v.get("webpage_url", "")
                if not sc_url: continue
                dur = v.get("duration", 0)
                results.append({
                    "title": v.get("title", "?"),
                    "artist": v.get("uploader", ""),
                    "url": sc_url,
                    "uid": url_to_id(sc_url),
                    "duration": fmt_dur(dur),
                    "source": "sc",
                })
    except:
        pass
    return results

def search_youtube_music(query, limit=10):
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
                if not v: continue
                vid_id = v.get("id", "")
                if not vid_id: continue
                yt_url = f"https://music.youtube.com/watch?v={vid_id}"
                dur = v.get("duration", 0)
                results.append({
                    "title": v.get("title", "?"),
                    "artist": v.get("uploader", v.get("channel", "")),
                    "url": yt_url,
                    "uid": url_to_id(yt_url),
                    "duration": fmt_dur(dur),
                    "source": "ytm",
                })
    except:
        pass
    return results

def search_deezer(query, limit=10):
    results = []
    try:
        res = requests.get(
            "https://api.deezer.com/search",
            params={"q": query, "limit": limit},
            timeout=8
        )
        data = res.json()
        for item in data.get("data", []):
            preview_url = item.get("preview", "")
            title = item.get("title", "?")
            artist = item.get("artist", {}).get("name", "")
            dur = item.get("duration", 0)
            track_id = str(item.get("id", ""))
            deezer_url = item.get("link", f"https://deezer.com/track/{track_id}")
            if preview_url:
                results.append({
                    "title": title,
                    "artist": artist,
                    "url": preview_url,
                    "uid": url_to_id(preview_url),
                    "duration": fmt_dur(dur),
                    "source": "dz",
                    "full_url": deezer_url,
                    "is_preview": True,
                })
    except:
        pass
    return results

def combine_search(query, limit=10):
    sc = search_soundcloud(query, limit)
    ym = search_youtube_music(query, limit // 2)
    dz = search_deezer(query, limit // 2)

    seen = set()
    combined = []
    # SoundCloud birinchi — eng ishonchli manba
    for r in sc + ym + dz:
        key = r["title"].lower().strip()
        if key not in seen:
            seen.add(key)
            combined.append(r)
    return combined[:limit]

# ─── FORMAT RESULTS ───────────────────────────────────────────────────────────
def format_results(results):
    nums = ["1️⃣","2️⃣","3️⃣","4️⃣","5️⃣","6️⃣","7️⃣","8️⃣","9️⃣","🔟"]
    source_icons = {"sc": "🎵", "ytm": "🎬", "dz": "🎶", "": "🎵"}
    text = "🎵 Natijalar:\n\n"
    buttons = []
    for i, r in enumerate(results[:10]):
        dur = r.get("duration", "")
        artist = r.get("artist", "")
        icon = source_icons.get(r.get("source", ""), "🎵")
        title = r["title"][:40]
        line = f"{nums[i]} {title}"
        if artist:
            line += f" — {artist[:18]}"
        if dur:
            line += f" [{dur}]"
        text += line + "\n"
        btn = f"{nums[i]} {r['title'][:35]}"
        if dur:
            btn += f" [{dur}]"
        buttons.append([InlineKeyboardButton(btn, callback_data="dl|" + r["uid"])])
    return text, buttons

# ─── INSTAGRAM MUSIC ──────────────────────────────────────────────────────────
def get_media_music_title(url):
    """Video URL dan musiqa nomini olish — track > artist+music > title"""
    opts = {
        "quiet": True, "skip_download": True,
        "no_warnings": True, "socket_timeout": 20,
    }
    if os.path.exists("/app/cookies.txt"):
        opts["cookiefile"] = "/app/cookies.txt"
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)

            # 1. track meta — eng aniq
            track = info.get("track", "")
            artist = info.get("artist", "")
            if track and artist:
                return f"{artist} - {track}"
            if track:
                return track

            # 2. music meta
            music = info.get("music", [])
            if isinstance(music, list) and music:
                m = music[0]
                song = m.get("song", "")
                art = m.get("artist", "")
                if song and art:
                    return f"{art} - {song}"
                if song:
                    return song

            # 3. description dan musiqa nomini qidirish
            desc = info.get("description", "")
            if desc:
                for line in desc.splitlines():
                    line = line.strip()
                    low = line.lower()
                    if "music:" in low or "song:" in low or "audio:" in low or "track:" in low:
                        clean = line.split(":", 1)[-1].strip()
                        if clean and len(clean) > 3:
                            return clean

            # 4. title dan foydalanish
            title = info.get("title", "")
            return title
    except:
        return ""

# ─── VOICE TO TEXT ────────────────────────────────────────────────────────────
async def voice_to_text(file_path):
    """Telegram ovozli xabarni matnга aylantirish — yt-dlp orqali"""
    # Oddiy yondashuv: foydalanuvchiga nom yozishni so'raymiz
    # Lekin whisper.cpp yoki google speech ishlatish mumkin
    return None

# ─── DOWNLOAD AUDIO ───────────────────────────────────────────────────────────
async def download_audio_direct(chat_id, url, title, context, user_id=None, user_obj=None):
    """Videodagi ovozni to'g'ridan yuklab beradi - YouTube qo'llanmaydi"""
    msg = await context.bot.send_message(chat_id=chat_id, text="⏳ Videodagi musiqa yuklanmoqda...")
    outfile = f"/tmp/igaudio_{chat_id}"

    for ext in ["mp3", "m4a", "webm", "opus", "ogg", "mp4"]:
        p = f"{outfile}.{ext}"
        if os.path.exists(p):
            try: os.remove(p)
            except: pass

    import shutil
    has_ffmpeg = shutil.which("ffmpeg") is not None

    opts = {
        "format": "bestaudio[ext=mp3]/bestaudio[ext=m4a]/bestaudio/best",
        "outtmpl": f"{outfile}.%(ext)s",
        "quiet": True, "no_warnings": True,
        "noplaylist": True, "socket_timeout": 60, "retries": 3,
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
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            # Asl musiqa nomi — track > title
            track = info.get("track", "")
            art = info.get("artist", "")
            if track:
                real_title = track
                artist = art
            else:
                real_title = info.get("title", title)
                artist = info.get("uploader", art)
    except Exception as e:
        await msg.edit_text("❌ Yuklashda xatolik. Qayta urining.")
        return

    filepath = f"{outfile}.mp3"
    if not os.path.exists(filepath):
        for ext in ["m4a", "webm", "opus", "ogg", "mp4"]:
            p = f"{outfile}.{ext}"
            if os.path.exists(p):
                filepath = p
                break

    if not filepath or not os.path.exists(filepath):
        for f in os.listdir("/tmp"):
            if f.startswith(f"igaudio_{chat_id}"):
                filepath = f"/tmp/{f}"
                break

    if filepath and os.path.exists(filepath):
        if os.path.getsize(filepath) > 50 * 1024 * 1024:
            await msg.edit_text("❌ Fayl juda katta.")
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
            InlineKeyboardButton("❤️ Sevimli", callback_data=f"fav|{uid}|{real_title[:25]}"),
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
            with open(filepath, "rb") as doc:
                await context.bot.send_document(
                    chat_id=chat_id, document=doc,
                    caption=f"🎵 {real_title}",
                    reply_markup=keyboard,
                )
        try: os.remove(filepath)
        except: pass
        await msg.delete()
    else:
        await msg.edit_text("❌ Fayl topilmadi.")

async def download_audio(chat_id, url, title, context, user_id=None, user_obj=None):
    msg = await context.bot.send_message(chat_id=chat_id, text="⏳ Yuklanmoqda...")
    outfile = f"/tmp/audio_{chat_id}"

    for ext in ["mp3", "m4a", "webm", "opus", "ogg", "mp4"]:
        p = f"{outfile}.{ext}"
        if os.path.exists(p):
            try: os.remove(p)
            except: pass

    import shutil
    has_ffmpeg = shutil.which("ffmpeg") is not None
    is_youtube = "youtube.com" in url or "youtu.be" in url or "music.youtube.com" in url

    # YouTube bo'lsa — SoundCloud dan qidirish
    if is_youtube:
        real_title = title
        try:
            info_opts = {"quiet": True, "skip_download": True, "no_warnings": True, "socket_timeout": 10}
            with yt_dlp.YoutubeDL(info_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                real_title = info.get("title", title)
        except:
            pass
        await msg.edit_text("🔄 Qidirilmoqda...")
        sc_results = search_soundcloud(real_title, 8)
        if not sc_results:
            sc_results = combine_search(real_title, 8)
        if sc_results:
            result_text, buttons = format_results(sc_results)
            await msg.edit_text(result_text, reply_markup=InlineKeyboardMarkup(buttons))
        else:
            await msg.edit_text("❌ Topilmadi. Qo'shiq nomini yozing.")
        return

    # Deezer preview bo'lsa — to'g'ridan yuklab olamiz
    if "dzcdn.net" in url or url.endswith(".mp3"):
        try:
            r = requests.get(url, timeout=30, stream=True)
            filepath = f"{outfile}.mp3"
            with open(filepath, "wb") as f:
                for chunk in r.iter_content(8192):
                    f.write(chunk)
            if os.path.exists(filepath) and os.path.getsize(filepath) > 1000:
                uid = url_to_id(url)
                keyboard = InlineKeyboardMarkup([[
                    InlineKeyboardButton("❤️ Sevimli", callback_data=f"fav|{uid}|{title[:25]}"),
                ]])
                with open(filepath, "rb") as audio:
                    await context.bot.send_audio(
                        chat_id=chat_id, audio=audio,
                        title=title, reply_markup=keyboard,
                        read_timeout=60, write_timeout=60,
                    )
                os.remove(filepath)
                await msg.delete()
                return
        except:
            pass
        await msg.edit_text("❌ Yuklashda xatolik.")
        return

    # SoundCloud, TikTok, Instagram va boshqalar
    opts = {
        "format": "bestaudio[ext=mp3]/bestaudio[ext=m4a]/bestaudio/best",
        "outtmpl": f"{outfile}.%(ext)s",
        "quiet": True, "no_warnings": True,
        "noplaylist": True, "socket_timeout": 60, "retries": 3,
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
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            # Asl musiqa nomi — track > title
            track = info.get("track", "")
            art = info.get("artist", "")
            if track:
                real_title = track
                artist = art
            else:
                real_title = info.get("title", title)
                artist = info.get("uploader", art)
    except Exception as e:
        await msg.edit_text("❌ Yuklashda xatolik. Qayta urining.")
        return

    filepath = f"{outfile}.mp3"
    if not os.path.exists(filepath):
        for ext in ["m4a", "webm", "opus", "ogg", "mp4"]:
            p = f"{outfile}.{ext}"
            if os.path.exists(p):
                filepath = p
                break

    if not filepath or not os.path.exists(filepath):
        for f in os.listdir("/tmp"):
            if f.startswith(f"audio_{chat_id}"):
                filepath = f"/tmp/{f}"
                break

    if filepath and os.path.exists(filepath):
        if os.path.getsize(filepath) > 50 * 1024 * 1024:
            await msg.edit_text("❌ Fayl juda katta.")
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
    msg = await context.bot.send_message(chat_id=chat_id, text=f"🎬 {name} yuklanmoqda...")
    outfile = f"/tmp/video_{chat_id}"

    # Eski fayllarni tozalash
    for ext in ["mp4", "webm", "mkv", "mov"]:
        p = f"{outfile}.{ext}"
        if os.path.exists(p):
            try: os.remove(p)
            except: pass

    opts = {
        "format": "best[ext=mp4][height<=720]/best[height<=720]/best[height<=480]/best",
        "outtmpl": outfile + ".%(ext)s",
        "quiet": True, "noplaylist": True,
        "socket_timeout": 60, "retries": 5,
        "no_warnings": True,
    }

    # Instagram uchun maxsus sozlamalar
    if platform == "instagram":
        opts["http_headers"] = {
            "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15",
            "Accept-Language": "en-US,en;q=0.9",
        }

    if os.path.exists("/app/cookies.txt"):
        opts["cookiefile"] = "/app/cookies.txt"

    real_title = name
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            real_title = info.get("title", name)
    except Exception as e:
        # Ikkinchi urinish — boshqa format bilan
        opts2 = {
            "format": "worst",
            "outtmpl": outfile + ".%(ext)s",
            "quiet": True, "noplaylist": True,
            "socket_timeout": 60, "retries": 3,
            "no_warnings": True,
        }
        if platform == "instagram":
            opts2["http_headers"] = {
                "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15",
            }
        if os.path.exists("/app/cookies.txt"):
            opts2["cookiefile"] = "/app/cookies.txt"
        try:
            with yt_dlp.YoutubeDL(opts2) as ydl:
                info = ydl.extract_info(url, download=True)
                real_title = info.get("title", name)
        except:
            await msg.edit_text(f"❌ {name} yuklab bo'lmadi. Link ochiq ekanligini tekshiring.")
            return

    # Yuklangan faylni topish
    filepath = None
    for ext in ["mp4", "webm", "mkv", "mov", "avi"]:
        p = f"{outfile}.{ext}"
        if os.path.exists(p):
            filepath = p
            break
    if not filepath:
        for f in os.listdir("/tmp"):
            if f.startswith(f"video_{chat_id}"):
                filepath = f"/tmp/{f}"
                break

    if filepath and os.path.exists(filepath):
        if os.path.getsize(filepath) > 50 * 1024 * 1024:
            await msg.edit_text("❌ Video juda katta (50MB).")
            try: os.remove(filepath)
            except: pass
            return
        try:
            with open(filepath, "rb") as video:
                await context.bot.send_video(
                    chat_id=chat_id, video=video,
                    caption=f"🎬 {real_title}",
                    read_timeout=120, write_timeout=120,
                    supports_streaming=True,
                )
        except:
            with open(filepath, "rb") as doc:
                await context.bot.send_document(
                    chat_id=chat_id, document=doc,
                    caption=f"🎬 {real_title}",
                )
        try: os.remove(filepath)
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

def link_keyboard(uid):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎵 To'liq musiqa", callback_data=f"ig_music|{uid}")],
        [InlineKeyboardButton("🎵 Videodagi musiqa", callback_data=f"igdl|{uid}")],
        [InlineKeyboardButton("🎬 Videoni yukla", callback_data=f"vid|{uid}")],
    ])

# ─── /start ───────────────────────────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db = load_db()
    is_new = str(user.id) not in db
    get_user(db, user.id, user)
    save_db(db)
    if is_new:
        await update.message.reply_text(
            f"🎵 Salom, {user.first_name}! Xush kelibsiz!\n\n"
            "Qo'shiq nomini yozing yoki\n"
            "YouTube, Instagram, TikTok, Snapchat link yuboring.\n\n"
            "🎤 Ovozli xabar ham yuborishingiz mumkin!",
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
        await update.message.reply_text(f"{name} — nima kerak?", reply_markup=link_keyboard(uid))
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
    chat_id = update.message.chat_id
    user_id = update.effective_user.id
    user_obj = update.effective_user

    msg = await update.message.reply_text("🎤 Ovozli xabar qabul qilindi, qidirilmoqda...")

    try:
        # Ovozni yuklab olamiz
        voice = update.message.voice or update.message.audio
        if not voice:
            await msg.edit_text("❌ Ovozni tanib bo'lmadi. Qo'shiq nomini yozing.")
            return

        voice_file = await context.bot.get_file(voice.file_id)
        voice_path = f"/tmp/voice_{chat_id}.ogg"
        await voice_file.download_to_drive(voice_path)

        # Ovozdan matn — Telegram bot API orqali
        # Shazam-uslub: ovoz parmog'ini SoundCloud dan qidirish
        # Hozircha: foydalanuvchiga qo'shiq nomini so'raymiz
        # Lekin audio uzunligiga qarab — qo'shiq bo'lsa qidirish, aks holda
        duration = voice.duration if hasattr(voice, 'duration') else 0

        if duration and duration < 60:
            # Qisqa ovoz — qo'shiq nomi deb taxmin qilamiz, matn sifatida qidiramiz
            # Telegram built-in recognition yo'q, shuning uchun
            # Foydalanuvchiga so'raymiz
            await msg.edit_text(
                "🎤 Ovozli xabarni qabul qildim!\n\n"
                "Qo'shiq nomini matn ko'rinishida yozing, tezroq topib beraman:"
            )
        else:
            await msg.edit_text("🎤 Qo'shiq nomini yozing, tezda topib beraman!")

        if os.path.exists(voice_path):
            os.remove(voice_path)

    except Exception as e:
        await msg.edit_text("🎤 Qo'shiq nomini yozing!")

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
        await query.edit_message_text("🔍 Musiqa qidirilmoqda...")
        music_title = get_media_music_title(url)

        # Musiqa nomi bo'lsa — qidirish
        if music_title and len(music_title) > 2:
            results = combine_search(music_title, 10)
            if results:
                result_text, buttons = format_results(results)
                final_text = "🎵 " + music_title + " natijalari:\n\n" + result_text.replace("🎵 Natijalar:\n\n", "")
                await query.edit_message_text(
                    final_text,
                    reply_markup=InlineKeyboardMarkup(buttons)
                )
                return

        # Musiqa nomi topilmasa — foydalanuvchiga so'rash
        await query.edit_message_text(
            "Videodagi musiqa nomi aniqlanmadi. Qoshiq nomini yozing:"
        )

    elif data.startswith("igdl|"):
        # Videodagi ovozni to'g'ridan yuklab beradi (Instagram, TikTok...)
        uid = data.split("|")[1]
        url = id_to_url(uid)
        if not url:
            await query.answer("❌ Muddati o'tgan.", show_alert=True)
            return
        await download_audio_direct(chat_id, url, "Musiqa", context, user_id, user_obj)

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
                txt += f"{i+1}. {fav['title'][:45]}\n"
                buttons.append([InlineKeyboardButton(f"▶️ {fav['title'][:40]}", callback_data=f"dl|{fav['uid']}")])
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
                txt += f"{nums[i]} {item['title'][:40]} — {item['count']}x\n"
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
                txt += f"{i+1}. {item['title'][:45]}\n"
                uid = url_to_id(item["url"])
                buttons.append([InlineKeyboardButton(f"▶️ {item['title'][:40]}", callback_data=f"dl|{uid}")])
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
        await query.edit_message_text(f"Sozlamalar\n\nNatijalar soni: {cnt} ta", reply_markup=kb)

    elif data in ["sr5", "sr10"]:
        count = int(data[2:])
        db = load_db()
        user = get_user(db, user_id, user_obj)
        user["settings"]["results"] = count
        save_db(db)
        await query.answer(f"✅ {count} ta natija!", show_alert=True)

    elif data == "help":
        await query.edit_message_text(
            "Yordam\n\n"
            "Link yuborish:\n"
            "YouTube, Instagram, TikTok, Snapchat, Pinterest, Likee\n\n"
            "Har biri uchun:\n"
            "• To'liq musiqa — musiqa nomini qidiradi\n"
            "• Videodagi musiqa — videodan audio chiqaradi\n"
            "• Videoni yukla — videoni yuboradi\n\n"
            "Qo'shiq qidirish:\n"
            "Nom yozing — SoundCloud + YouTube Music + Deezer dan topadi\n\n"
            "Ovozli xabar: yuboring, qo'shiq nomini so'raydi\n\n"
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
        txt += f"Foydalanuvchilar: {len(db)} ta\n"
        txt += f"Jami yuklanmalar: {total_dl} ta\n"
        txt += f"Jami qo'shiqlar: {len(top)} ta\n\nTop 5:\n"
        for i, item in enumerate(top5):
            txt += f"{i+1}. {item['title'][:35]} — {item['count']}x\n"
        await query.edit_message_text(txt,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Orqaga", callback_data="back")]]))

    elif data == "admin_users":
        if user_id != ADMIN_ID: return
        db = load_db()
        txt = f"Foydalanuvchilar ({len(db)} ta):\n\n"
        for uid, u in list(db.items())[-20:]:
            txt += f"• {u.get('name','?')} {u.get('username','')} — {u.get('downloads',0)} ta\n"
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
    txt += f"Foydalanuvchilar: {len(db)} ta\n"
    txt += f"Jami yuklanmalar: {total_dl} ta\n"
    txt += f"Jami qo'shiqlar: {len(top)} ta\n\n"
    txt += "So'nggi 10 foydalanuvchi:\n"
    for uid, u in list(db.items())[-10:]:
        txt += f"• {u.get('name','?')} {u.get('username','')} — {u.get('downloads',0)} ta ({u.get('joined','?')})\n"
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
        txt += f"{nums[i]} {item['title'][:40]} — {item['count']}x\n"
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
        txt += f"{i+1}. {fav['title'][:45]}\n"
        buttons.append([InlineKeyboardButton(f"▶️ {fav['title'][:40]}", callback_data=f"dl|{fav['uid']}")])
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
        txt += f"{i+1}. {item['title'][:45]}\n"
        uid = url_to_id(item["url"])
        buttons.append([InlineKeyboardButton(f"▶️ {item['title'][:40]}", callback_data=f"dl|{uid}")])
    await update.message.reply_text(txt, reply_markup=InlineKeyboardMarkup(buttons))

async def stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db = load_db()
    user = get_user(db, update.effective_user.id, update.effective_user)
    top = load_top()
    await update.message.reply_text(
        f"📊 Statistika:\n\n"
        f"Siz yuklagan: {user['downloads']} ta\n"
        f"Sevimlilar: {len(user['favorites'])} ta\n"
        f"Tarix: {len(user['history'])} ta\n\n"
        f"Umumiy:\n"
        f"Jami qo'shiqlar: {len(top)} ta\n"
        f"Yuklanmalar: {sum(v['count'] for v in top.values())} ta"
    )

async def error_handler(update, context):
    print(f"⚠️ Xato: {context.error}")

# ─── MAIN ─────────────────────────────────────────────────────────────────────
def main():
    load_cache()  # URL cache ni yuklash
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
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO | filters.VIDEO_NOTE, handle_voice))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_error_handler(error_handler)
    print("🎵 MusicBot ishga tushdi!")
    app.run_polling(drop_pending_updates=True, allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()




















