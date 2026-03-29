#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import json
import re
import hashlib
import asyncio
import subprocess
import shutil
from pathlib import Path
from datetime import datetime

import requests
import yt_dlp
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters,
)

# -------------------- KONFIGURATSIYA (xavfsiz) --------------------
TOKEN = os.environ.get("BOT_TOKEN")          # Tokenni environment'dan o‘qing!
if not TOKEN:
    raise ValueError("BOT_TOKEN environment o‘zgaruvchisi o‘rnatilmagan")

ADMIN_ID = int(os.environ.get 6705765282  
YT_API_KEY = os.environ.get "8312461995:AAExjPqVRhrHvhBQVi4XALAn-cNyM5RZsYw"          

# Papkalar
DOWNLOAD_DIR = "/tmp/musicbot_downloads"     # Vaqtinchalik fayllar
Path(DOWNLOAD_DIR).mkdir(exist_ok=True)

# Fayl yo‘llari
DB_FILE = os.path.join(DOWNLOAD_DIR, "users.json")
TOP_FILE = os.path.join(DOWNLOAD_DIR, "top.json")
CACHE_FILE = os.path.join(DOWNLOAD_DIR, "url_cache.json")

# Global o‘zgaruvchilar
URL_CACHE = {}
DOWNLOAD_SEMAPHORE = asyncio.Semaphore(3)   # Maksimal 3 ta parallel yuklab olish

# -------------------- YORDAMCHI FUNKSIYALAR --------------------
def load_cache():
    global URL_CACHE
    try:
        if os.path.exists(CACHE_FILE):
            with open(CACHE_FILE, "r") as f:
                URL_CACHE = json.load(f)
    except:
        URL_CACHE = {}

def save_cache():
    try:
        items = list(URL_CACHE.items())[-3000:]   # Faqat oxirgi 3000 ta
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
        if s <= 0:
            return ""
        m, s = divmod(s, 60)
        h, m = divmod(m, 60)
        if h:
            return f"{h}:{m:02d}:{s:02d}"
        return f"{m}:{s:02d}"
    except:
        return ""

def get_audio_duration(file_path):
    """FFprobe yordamida audio davomiyligini sekundlarda olish"""
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", file_path],
            capture_output=True, text=True, timeout=10
        )
        return float(result.stdout.strip())
    except:
        return 0

def compress_audio(input_path, output_path, target_size_mb=48):
    """Agar fayl target_size_mb dan katta bo‘lsa, bitrate pasaytirib siqadi"""
    current_size = os.path.getsize(input_path) / (1024 * 1024)
    if current_size <= target_size_mb:
        shutil.copy2(input_path, output_path)
        return output_path

    duration = get_audio_duration(input_path)
    if duration <= 0:
        shutil.copy2(input_path, output_path)
        return output_path

    # Bitrate = (target_size_mb * 8 * 1024) / duration (kbps)
    target_bitrate = int((target_size_mb * 8 * 1024) / duration)
    target_bitrate = max(32, min(192, target_bitrate))   # 32-192 kbps oralig‘i

    cmd = [
        "ffmpeg", "-i", input_path,
        "-b:a", f"{target_bitrate}k",
        "-ac", "2", "-ar", "44100",
        "-y", output_path
    ]
    subprocess.run(cmd, capture_output=True)
    return output_path

def add_metadata(file_path, title, artist, album="Music Bot", cover_url=None):
    """MP3 faylga ID3 taglar qo‘shish (agar eyed3 o‘rnatilgan bo‘lsa)"""
    try:
        import eyed3
        audiofile = eyed3.load(file_path)
        if audiofile.tag is None:
            audiofile.initTag()
        audiofile.tag.title = title[:100]
        audiofile.tag.artist = artist[:100]
        audiofile.tag.album = album[:100]
        if cover_url:
            try:
                resp = requests.get(cover_url, timeout=10)
                if resp.status_code == 200:
                    audiofile.tag.images.set(3, resp.content, "image/jpeg")
            except:
                pass
        audiofile.tag.save()
    except ImportError:
        pass  # eyed3 o‘rnatilmagan bo‘lsa, hech narsa qilma

# -------------------- DATABASE (JSON) --------------------
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
        db[uid] = {
            "favorites": [], "history": [],
            "settings": {"results": 10},
            "downloads": 0,
            "name": user_obj.full_name if user_obj else "Noma'lum",
            "username": ("@" + user_obj.username) if user_obj and user_obj.username else "",
            "joined": datetime.now().strftime("%Y-%m-%d"),
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

# -------------------- PLATFORMANI ANIQLASH --------------------
def detect_platform(url):
    if re.search(r"youtube\.com|youtu\.be", url): return "youtube"
    if re.search(r"instagram\.com", url): return "instagram"
    if re.search(r"tiktok\.com", url): return "tiktok"
    if re.search(r"snapchat\.com", url): return "snapchat"
    if re.search(r"pinterest\.", url): return "pinterest"
    if re.search(r"likee\.", url): return "likee"
    if re.search(r"https?://", url): return "other"
    return None

# -------------------- QIDIRUV FUNKSIYALARI --------------------
def search_soundcloud(query, limit=10):
    opts = {"quiet": True, "skip_download": True, "extract_flat": True,
            "no_warnings": True, "socket_timeout": 15}
    results = []
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            data = ydl.extract_info(f"scsearch{limit}:{query}", download=False)
            for v in (data.get("entries") or []):
                if not v: continue
                sc_url = v.get("webpage_url")
                if not sc_url: continue
                dur = v.get("duration", 0)
                title = v.get("title", "?")
                artist = v.get("uploader", "")
                if " - " in title:
                    parts = title.split(" - ", 1)
                    if not artist:
                        artist = parts[0].strip()
                    title = parts[1].strip()
                results.append({
                    "title": title, "artist": artist,
                    "url": sc_url, "uid": url_to_id(sc_url),
                    "duration": fmt_dur(dur), "source": "sc",
                })
    except:
        pass
    return results

def search_youtube_music(query, limit=10):
    opts = {"quiet": True, "skip_download": True, "extract_flat": True,
            "no_warnings": True, "socket_timeout": 15}
    results = []
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            data = ydl.extract_info(f"ytmsearch{limit}:{query}", download=False)
            for v in (data.get("entries") or []):
                if not v: continue
                vid_id = v.get("id")
                if not vid_id: continue
                yt_url = f"https://music.youtube.com/watch?v={vid_id}"
                dur = v.get("duration", 0)
                title = v.get("title", "?")
                artist = v.get("uploader", v.get("channel", ""))
                if artist.endswith(" - Topic"):
                    artist = artist[:-8].strip()
                results.append({
                    "title": title, "artist": artist,
                    "url": yt_url, "uid": url_to_id(yt_url),
                    "duration": fmt_dur(dur), "source": "ytm",
                })
    except:
        pass
    return results

def search_deezer(query, limit=10):
    results = []
    try:
        res = requests.get("https://api.deezer.com/search",
                           params={"q": query, "limit": limit}, timeout=8)
        for item in res.json().get("data", []):
            preview = item.get("preview")
            if not preview: continue
            title = item.get("title", "?")
            artist = item.get("artist", {}).get("name", "")
            dur = item.get("duration", 0)
            results.append({
                "title": title, "artist": artist,
                "url": preview, "uid": url_to_id(preview),
                "duration": fmt_dur(dur), "source": "dz",
            })
    except:
        pass
    return results

def combine_search(query, limit=10):
    sc = search_soundcloud(query, limit)
    ym = search_youtube_music(query, limit)
    dz = search_deezer(query, limit)
    seen = set()
    combined = []
    for r in sc + ym + dz:
        key = (r["title"] + r.get("artist", "")).lower().strip()
        if key not in seen:
            seen.add(key)
            combined.append(r)
    return combined[:limit]

# -------------------- FORMATLASH --------------------
def format_results(results, title=""):
    nums = ["1️⃣","2️⃣","3️⃣","4️⃣","5️⃣","6️⃣","7️⃣","8️⃣","9️⃣","🔟"]
    header = f"🎵 {title} natijalari:\n\n" if title else "🎵 Natijalar:\n\n"
    text = header
    buttons = []
    for i, r in enumerate(results[:10]):
        dur = r.get("duration", "")
        artist = r.get("artist", "")
        t = r["title"][:40]
        line = f"{nums[i]} {t}"
        if artist:
            line += f" — {artist[:20]}"
        if dur:
            line += f" [{dur}]"
        text += line + "\n"
        btn_text = f"{nums[i]} {r['title'][:33]}"
        if dur:
            btn_text += f" [{dur}]"
        buttons.append([InlineKeyboardButton(btn_text, callback_data="dl|" + r["uid"])])
    return text, buttons

# -------------------- VIDEO MUSIQA NOMINI OLISH --------------------
def get_media_music_title(url):
    opts = {"quiet": True, "skip_download": True, "no_warnings": True, "socket_timeout": 20}
    cookies = "/app/cookies.txt"
    if os.path.exists(cookies):
        opts["cookiefile"] = cookies
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
            track = info.get("track")
            artist = info.get("artist")
            if track and artist:
                return f"{artist} - {track}"
            if track:
                return track
            music = info.get("music", [])
            if isinstance(music, list) and music:
                m = music[0]
                song = m.get("song")
                art = m.get("artist")
                if song:
                    return f"{art} - {song}" if art else song
            desc = info.get("description", "")
            for line in (desc or "").splitlines():
                low = line.lower().strip()
                if any(k in low for k in ["music:", "song:", "audio:", "track:"]):
                    clean = line.split(":", 1)[-1].strip()
                    if clean and len(clean) > 3:
                        return clean
            return info.get("title", "")
    except:
        return ""

# -------------------- YUKLAB OLISH (SEMAFOR BILAN) --------------------
async def download_audio(chat_id, url, title, context, user_id=None, user_obj=None):
    async with DOWNLOAD_SEMAPHORE:
        msg = await context.bot.send_message(chat_id, "⏳ Yuklanmoqda (semafor: 3 tagacha)...")

        # Vaqtinchalik fayl nomi
        outfile = f"/tmp/audio_{chat_id}_{int(time.time())}"
        for ext in ["mp3","m4a","webm","opus","ogg","mp4"]:
            p = f"{outfile}.{ext}"
            if os.path.exists(p):
                try: os.remove(p)
                except: pass

        has_ffmpeg = shutil.which("ffmpeg") is not None
        is_youtube = "youtube.com" in url or "youtu.be" in url

        # YouTube bo‘lsa – avval nomini tozalab, SoundCloud/Deezer qidiruvini ko‘rsat
        if is_youtube:
            real_title = title
            try:
                info_opts = {"quiet": True, "skip_download": True, "no_warnings": True}
                with yt_dlp.YoutubeDL(info_opts) as ydl:
                    info = ydl.extract_info(url, download=False)
                    track = info.get("track")
                    art = info.get("artist")
                    if track:
                        real_title = f"{art} - {track}" if art else track
                    else:
                        real_title = info.get("title", title)
            except:
                pass
            await msg.edit_text("🔄 Qidirilmoqda...")
            results = search_soundcloud(real_title, 8)
            if not results:
                results = combine_search(real_title, 8)
            if results:
                result_text, buttons = format_results(results)
                await msg.edit_text(result_text, reply_markup=InlineKeyboardMarkup(buttons))
            else:
                await msg.edit_text("❌ Topilmadi. Qo'shiq nomini yozing.")
            return

        # Deezer preview (30 soniyalik)
        if "dzcdn.net" in url or (url.endswith(".mp3") and "deezer.com" not in url):
            try:
                r = requests.get(url, timeout=30, stream=True)
                filepath = f"{outfile}.mp3"
                with open(filepath, "wb") as f:
                    for chunk in r.iter_content(8192):
                        f.write(chunk)
                if os.path.getsize(filepath) > 1000:
                    # Siqish (agar kerak bo‘lsa)
                    compressed = compress_audio(filepath, f"{outfile}_compressed.mp3")
                    final_path = compressed
                    add_metadata(final_path, title, "", "Deezer Preview")
                    increment_top(title, url)
                    if user_id:
                        db = load_db()
                        user = get_user(db, user_id, user_obj)
                        user["downloads"] += 1
                        h = {"title": title, "url": url}
                        if h not in user["history"]:
                            user["history"].insert(0, h)
                            user["history"] = user["history"][:20]
                        save_db(db)
                    uid = url_to_id(url)
                    kb = InlineKeyboardMarkup([[
                        InlineKeyboardButton("❤️ Sevimli", callback_data=f"fav|{uid}|{title[:25]}")
                    ]])
                    with open(final_path, "rb") as audio:
                        await context.bot.send_audio(chat_id, audio=audio, title=title, reply_markup=kb)
                    for f in [filepath, final_path]:
                        try: os.remove(f)
                        except: pass
                    await msg.delete()
                    return
            except:
                pass
            await msg.edit_text("❌ Yuklashda xatolik.")
            return

        # SoundCloud va boshqa platformalar
        opts = {
            "format": "bestaudio[ext=m4a]/bestaudio[ext=mp3]/bestaudio/best",
            "outtmpl": outfile + ".%(ext)s",
            "quiet": True, "no_warnings": True,
            "noplaylist": True, "socket_timeout": 60, "retries": 3,
        }
        if has_ffmpeg:
            opts["postprocessors"] = [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"}]

        cookies = "/app/cookies.txt"
        if os.path.exists(cookies):
            opts["cookiefile"] = cookies

        real_title = title
        artist = ""
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)
                track = info.get("track")
                art = info.get("artist")
                if track:
                    real_title = track
                    artist = art
                else:
                    real_title = info.get("title", title)
                    artist = info.get("uploader", art)
        except Exception as e:
            await msg.edit_text(f"❌ Yuklashda xatolik: {str(e)[:50]}")
            return

        # Yuklangan faylni topish
        filepath = f"{outfile}.mp3"
        if not os.path.exists(filepath):
            for ext in ["m4a","webm","opus","ogg","mp4"]:
                p = f"{outfile}.{ext}"
                if os.path.exists(p):
                    filepath = p
                    break
        if not os.path.exists(filepath):
            await msg.edit_text("❌ Fayl topilmadi.")
            return

        # Hajmni tekshirish va siqish
        size_mb = os.path.getsize(filepath) / (1024*1024)
        if size_mb > 50:
            compressed_path = f"{outfile}_compressed.mp3"
            compress_audio(filepath, compressed_path, 48)
            filepath = compressed_path

        # Metadatalog qo‘shish
        add_metadata(filepath, real_title, artist, "Music Bot")

        # Statistikani yangilash
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
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("❤️ Sevimli", callback_data=f"fav|{uid}|{real_title[:25]}")
        ]])

        try:
            with open(filepath, "rb") as audio:
                await context.bot.send_audio(chat_id, audio=audio, title=real_title, performer=artist, reply_markup=kb)
        except Exception:
            with open(filepath, "rb") as doc:
                await context.bot.send_document(chat_id, document=doc, caption=f"🎵 {real_title}", reply_markup=kb)

        for f in [filepath, outfile + ".mp3", outfile + ".m4a", outfile + ".webm"]:
            try: os.remove(f)
            except: pass
        await msg.delete()

# -------------------- VIDEO YUKLASH --------------------
async def download_video(chat_id, url, context, platform="other"):
    async with DOWNLOAD_SEMAPHORE:
        names = {"youtube":"YouTube","instagram":"Instagram","tiktok":"TikTok",
                 "snapchat":"Snapchat","pinterest":"Pinterest","likee":"Likee","other":"Video"}
        name = names.get(platform, "Video")
        msg = await context.bot.send_message(chat_id, f"🎬 {name} yuklanmoqda...")

        outfile = f"/tmp/video_{chat_id}_{int(time.time())}"
        for ext in ["mp4","webm","mkv","mov"]:
            p = f"{outfile}.{ext}"
            if os.path.exists(p):
                try: os.remove(p)
                except: pass

        opts = {
            "format": "best[ext=mp4][height<=720]/best[height<=720]/best[height<=480]/best",
            "outtmpl": outfile + ".%(ext)s",
            "quiet": True, "noplaylist": True,
            "socket_timeout": 60, "retries": 5, "no_warnings": True,
        }
        if platform == "instagram":
            opts["http_headers"] = {"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X)"}
        cookies = "/app/cookies.txt"
        if os.path.exists(cookies):
            opts["cookiefile"] = cookies

        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)
                real_title = info.get("title", name)
        except Exception:
            await msg.edit_text(f"❌ {name} yuklashda xatolik.")
            return

        filepath = None
        for ext in ["mp4","webm","mkv","mov"]:
            p = f"{outfile}.{ext}"
            if os.path.exists(p):
                filepath = p
                break
        if filepath and os.path.exists(filepath):
            if os.path.getsize(filepath) > 50*1024*1024:
                await msg.edit_text("❌ Video juda katta (50MB).")
                try: os.remove(filepath)
                except: pass
                return
            try:
                with open(filepath, "rb") as video:
                    await context.bot.send_video(chat_id, video=video, caption=f"🎬 {real_title}")
            except:
                with open(filepath, "rb") as doc:
                    await context.bot.send_document(chat_id, document=doc, caption=f"🎬 {real_title}")
            try: os.remove(filepath)
            except: pass
            await msg.delete()
        else:
            await msg.edit_text("❌ Video topilmadi.")

# -------------------- TELEGRAM BOT KOMMANDALARI --------------------
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

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db = load_db()
    is_new = str(user.id) not in db
    get_user(db, user.id, user)
    save_db(db)
    if is_new:
        await update.message.reply_text(
            f"👋 Salom, {user.first_name}!\n\n"
            "🎵 Qo'shiq nomi yoki artist ismini yozing\n"
            "🔗 YouTube, Instagram, TikTok, Snapchat linki yuboring\n"
            "🎤 Ovozli xabar yuboring (hozircha faqat matn)\n\n"
            "Manba: SoundCloud + YouTube Music + Deezer",
            reply_markup=main_keyboard()
        )
    else:
        await update.message.reply_text(
            "🎵 Bosh menyu\n\nQo'shiq nomi yozing yoki link yuboring!",
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
    if platform:
        uid = url_to_id(text)
        icons = {"youtube":"🎬","instagram":"📸","tiktok":"🎵","snapchat":"👻","pinterest":"📌","likee":"💚","other":"🔗"}
        icon = icons.get(platform, "🔗")
        names = {"youtube":"YouTube","instagram":"Instagram","tiktok":"TikTok",
                 "snapchat":"Snapchat","pinterest":"Pinterest","likee":"Likee","other":"Link"}
        name = names.get(platform, "Link")
        await update.message.reply_text(f"{icon} {name} — nima kerak?", reply_markup=link_keyboard(uid))
        return

    # Qo‘shiq qidirish
    user = get_user(db, user_id, user_obj)
    limit = user["settings"]["results"]
    msg = await update.message.reply_text("🔍 Qidirilmoqda...")
    results = combine_search(text, limit)
    if not results:
        await msg.edit_text("❌ Hech narsa topilmadi.")
        return
    result_text, buttons = format_results(results, text)
    await msg.edit_text(result_text, reply_markup=InlineKeyboardMarkup(buttons))

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
            await query.answer("❌ Muddati o'tgan. Qayta yuboring.", show_alert=True)
            return
        await query.edit_message_text("🔍 Musiqa qidirilmoqda...")
        music_title = get_media_music_title(url)
        if music_title and len(music_title) > 2:
            results = combine_search(music_title, 10)
            if results:
                result_text, buttons = format_results(results, music_title)
                await query.edit_message_text(result_text, reply_markup=InlineKeyboardMarkup(buttons))
                return
        await query.edit_message_text("❌ Musiqa nomi aniqlanmadi. Qo'shiq nomini yozing:")

    elif data.startswith("igdl|"):
        uid = data.split("|")[1]
        url = id_to_url(uid)
        if not url:
            await query.answer("❌ Muddati o'tgan.", show_alert=True)
            return
        await download_audio(chat_id, url, "Videodan audio", context, user_id, user_obj)

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
            buttons.append([InlineKeyboardButton("🗑 Tozalash", callback_data="clr_fav"),
                            InlineKeyboardButton("🔙 Orqaga", callback_data="back")])
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
        await query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Orqaga", callback_data="back")]]))

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
        await query.edit_message_text(f"⚙️ Sozlamalar\n\nNatijalar soni: {cnt} ta", reply_markup=kb)

    elif data in ["sr5", "sr10"]:
        count = int(data[2:])
        db = load_db()
        user = get_user(db, user_id, user_obj)
        user["settings"]["results"] = count
        save_db(db)
        await query.answer(f"✅ {count} ta natija!", show_alert=True)

    elif data == "help":
        await query.edit_message_text(
            "ℹ️ Yordam\n\n"
            "Qo'shiq qidirish:\n"
            "Artist yoki qo'shiq nomini yozing\n\n"
            "Link yuborish:\n"
            "YouTube, Instagram, TikTok, Snapchat, Pinterest, Likee\n\n"
            "Har bir link uchun:\n"
            "• To'liq musiqa — musiqa nomini qidiradi\n"
            "• Videodagi musiqa — videodan audio chiqaradi\n"
            "• Videoni yukla — videoni yuboradi\n\n"
            "Buyruqlar:\n"
            "/start /top /favorites /history /stats /admin",
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
        txt = "📊 Statistika:\n\n"
        txt += f"Foydalanuvchilar: {len(db)} ta\n"
        txt += f"Jami yuklanmalar: {total_dl} ta\n"
        txt += f"Jami qo'shiqlar: {len(top)} ta\n\nTop 5:\n"
        for i, item in enumerate(top5):
            txt += f"{i+1}. {item['title'][:35]} — {item['count']}x\n"
        await query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Orqaga", callback_data="back")]]))

    elif data == "admin_users":
        if user_id != ADMIN_ID: return
        db = load_db()
        txt = f"👥 Foydalanuvchilar ({len(db)} ta):\n\n"
        for uid, u in list(db.items())[-20:]:
            txt += f"• {u.get('name','?')} {u.get('username','')} — {u.get('downloads',0)} ta\n"
        await query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Orqaga", callback_data="back")]]))

# -------------------- KLAVISH BUYRUG'LAR --------------------
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

async def error_handler(update, context):
    print(f"⚠️ Xato: {context.error}")

# -------------------- MAIN --------------------
if __name__ == "__main__":
    import time
    load_cache()
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
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_error_handler(error_handler)
    print("🎵 MusicBot ishga tushdi!")
    app.run_polling(drop_pending_updates=True, allowed_updates=Update.ALL_TYPES)



















