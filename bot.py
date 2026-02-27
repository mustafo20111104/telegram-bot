import os
import json
import re
import hashlib
import asyncio
import gc
import logging
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
    InlineQueryHandler,
)

# ============== KONFIGURATSIYA ==============
TOKEN = os.environ.get("BOT_TOKEN")
YT_API_KEY = os.environ.get("YT_API_KEY", "")
HEROKU_APP_NAME = os.environ.get("HEROKU_APP_NAME", "")  # Heroku uchun
RAILWAY_STATIC_URL = os.environ.get("RAILWAY_STATIC_URL", "")  # Railway uchun

# Logging sozlash
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ============== URL CACHE ==============
URL_CACHE = {}
URL_CACHE_TIMEOUT = 3600  # 1 soat

def url_to_id(url):
    """URL ni qisqa ID ga aylantirish"""
    uid = hashlib.md5(url.encode()).hexdigest()[:12]
    URL_CACHE[uid] = {"url": url, "time": datetime.now().timestamp()}
    return uid

def id_to_url(uid):
    """ID dan URL olish"""
    cache = URL_CACHE.get(uid)
    if not cache:
        return ""
    # Check timeout
    if datetime.now().timestamp() - cache.get("time", 0) > URL_CACHE_TIMEOUT:
        return ""
    return cache.get("url", "")

# ============== DATABASE ==============
DB_FILE = "/tmp/users.json"
TOP_FILE = "/tmp/top.json"

def load_db():
    try:
        if os.path.exists(DB_FILE):
            with open(DB_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        logger.error(f"DB load error: {e}")
    return {}

def save_db(db):
    try:
        with open(DB_FILE, "w", encoding="utf-8") as f:
            json.dump(db, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"DB save error: {e}")

def get_user(db, user_id):
    uid = str(user_id)
    if uid not in db:
        db[uid] = {
            "favorites": [], 
            "history": [], 
            "settings": {"results": 5, "quality": "192"}, 
            "downloads": 0,
            "first_name": "",
            "username": ""
        }
    return db[uid]

def load_top():
    try:
        if os.path.exists(TOP_FILE):
            with open(TOP_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except:
        pass
    return {}

def save_top(top):
    try:
        with open(TOP_FILE, "w", encoding="utf-8") as f:
            json.dump(top, f, ensure_ascii=False, indent=2)
    except:
        pass

def increment_top(title, url):
    top = load_top()
    if url not in top:
        top[url] = {"title": title, "count": 0, "downloads": 0}
    top[url]["count"] += 1
    top[url]["downloads"] = top[url].get("downloads", 0) + 1
    top[url]["last_download"] = datetime.now().isoformat()
    save_top(top)

# ============== YOUTUBE SEARCH ==============
def search_youtube_api(query, limit=5):
    """YouTube API orqali qidiruv"""
    if not YT_API_KEY:
        return search_youtube_ytdlp(query, limit)
    
    try:
        import requests
        url = "https://www.googleapis.com/youtube/v3/search"
        params = {
            "part": "snippet",
            "q": query,
            "type": "video",
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
            yt_url = f"https://youtube.com/watch?v={vid_id}"
            results.append({
                "title": title,
                "url": yt_url,
                "uid": url_to_id(yt_url),
                "duration": "?",
                "channel": channel,
                "source": "YouTube",
                "thumbnail": f"https://img.youtube.com/vi/{vid_id}/mqdefault.jpg"
            })
        return results
    except Exception as e:
        logger.error(f"YouTube API error: {e}")
        return search_youtube_ytdlp(query, limit)

def search_youtube_ytdlp(query, limit=5):
    """yt-dlp orqali qidiruv (API yo'q bo'lsa)"""
    import yt_dlp
    
    ydl_opts = {
        "quiet": True, 
        "skip_download": True, 
        "extract_flat": True, 
        "no_warnings": True, 
        "socket_timeout": 15,
        "ignoreerrors": True
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            result = ydl.extract_info(f"ytsearch{limit}:{query}", download=False)
            results = []
            for v in result.get("entries", []):
                if v and v.get("id"):
                    dur = v.get("duration", 0) or 0
                    yt_url = f"https://youtube.com/watch?v={v.get('id')}"
                    results.append({
                        "title": v.get("title", "Noma'lum"),
                        "url": yt_url,
                        "uid": url_to_id(yt_url),
                        "duration": f"{dur//60}:{dur%60:02d}" if dur else "?",
                        "channel": v.get("uploader", "YouTube"),
                        "source": "YouTube",
                        "thumbnail": f"https://img.youtube.com/vi/{v.get('id')}/mqdefault.jpg"
                    })
            return results
    except Exception as e:
        logger.error(f"yt-dlp search error: {e}")
        return []

def search_soundcloud(query, limit=2):
    """SoundCloud qidiruv"""
    import yt_dlp
    
    ydl_opts = {
        "quiet": True, 
        "skip_download": True, 
        "extract_flat": True, 
        "no_warnings": True, 
        "socket_timeout": 15,
        "ignoreerrors": True
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            result = ydl.extract_info(f"scsearch{limit}:{query}", download=False)
            results = []
            for v in result.get("entries", []):
                if v:
                    dur = v.get("duration", 0) or 0
                    sc_url = v.get("webpage_url", "")
                    results.append({
                        "title": v.get("title", "Noma'lum"),
                        "url": sc_url,
                        "uid": url_to_id(sc_url),
                        "duration": f"{dur//60}:{dur%60:02d}" if dur else "?",
                        "channel": v.get("uploader", "SoundCloud"),
                        "source": "SoundCloud",
                        "thumbnail": "https://a-v2.sndcdn.com/assets/images/sc/default_avatar-713e982.png"
                    })
            return results
    except Exception as e:
        logger.error(f"SoundCloud search error: {e}")
        return []

def combine_search(query, limit=5):
    """Ikkala manbadan qidiruv"""
    import concurrent.futures
    
    results = []
    
    def run_yt():
        return search_youtube_api(query, limit)
    
    def run_sc():
        return search_soundcloud(query, 2)
    
    try:
        with concurrent.futures.ThreadPoolExecutor() as executor:
            yt_future = executor.submit(run_yt)
            sc_future = executor.submit(run_sc)
            
            yt_results = yt_future.result(timeout=10)
            sc_results = sc_future.result(timeout=10)
            
            results = (yt_results + sc_results)[:limit + 2]
    except Exception as e:
        logger.error(f"Combine search error: {e}")
        results = search_youtube_ytdlp(query, limit)
    
    return results

# ============== DOWNLOAD ==============
async def download_audio(chat_id, url, title, context, user_id=None, quality="192"):
    """Musiqa yuklab olish"""
    
    # Progress callback
    progress_data = {"last_percent": 0}
    
    def progress_hook(d):
        if d['status'] == 'downloading':
            try:
                total = d.get('total_bytes') or d.get('total_bytes_estimate', 0)
                downloaded = d.get('downloaded_bytes', 0)
                if total > 0:
                    percent = int(downloaded * 100 / total)
                    if percent - progress_data["last_percent"] >= 10:
                        progress_data["last_percent"] = percent
                        logger.info(f"Download progress: {percent}%")
            except:
                pass
    
    msg = await context.bot.send_message(
        chat_id=chat_id, 
        text="⏳ <b>Yuklanmoqda...</b>\n<i> kutaring</i>",
        parse_mode="HTML"
    )
    
    import yt_dlp
    import tempfile
    
    # Unique filename
    import uuid
    unique_id = uuid.uuid4().hex[:8]
    outfile = f"/tmp/audio_{unique_id}"
    
    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": f"{outfile}.%(ext)s",
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "socket_timeout": 60,
        "retries": 3,
        "fragment_retries": 3,
        "ignoreerrors": False,
        "nocheckcertificate": True,
        "progress_hooks": [progress_hook],
        "postprocessors": [{
            "key": "FFmpegExtractAudio", 
            "preferredcodec": "mp3", 
            "preferredquality": quality
        }],
    }
    
    real_title = title
    artist = ""
    thumbnail = ""
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            real_title = info.get("title", title)
            artist = info.get("uploader", "")
            thumbnail = info.get("thumbnail", "")
            duration = info.get("duration", 0)
    except Exception as e:
        logger.error(f"Download error (first attempt): {e}")
        
        # Second attempt with m4a
        ydl_opts2 = {
            "format": "bestaudio[ext=m4a]/bestaudio",
            "outtmpl": f"{outfile}.%(ext)s",
            "quiet": True,
            "noplaylist": True,
            "socket_timeout": 60,
            "retries": 3,
            "progress_hooks": [progress_hook],
        }
        try:
            with yt_dlp.YoutubeDL(ydl_opts2) as ydl:
                info = ydl.extract_info(url, download=True)
                real_title = info.get("title", title)
                artist = info.get("uploader", "")
                thumbnail = info.get("thumbnail", "")
        except Exception as e2:
            logger.error(f"Download error (second attempt): {e2}")
            await msg.edit_text(
                "❌ <b>Yuklashda xatolik yuz berdi!</b>\n\n"
                "Sabablari:\n"
                "• Video huquqlar bilan himoyalangan\n"
                "• Server ulanishi muammosi\n"
                "• Veryfiaktsiya talab qilinadi\n\n"
                "Qayta urinib ko'ring!",
                parse_mode="HTML"
            )
            return

    # Find downloaded file
    filepath = None
    for ext in ["mp3", "m4a", "webm", "opus", "ogg", "flac"]:
        p = f"{outfile}.{ext}"
        if os.path.exists(p):
            filepath = p
            break
    
    # Alternative: search in /tmp
    if not filepath:
        for f in os.listdir("/tmp"):
            if f.startswith("audio_") and f.endswith((".mp3", ".m4a", ".webm")):
                filepath = f"/tmp/{f}"
                break
    
    if filepath and os.path.exists(filepath):
        try:
            # Check file size (Telegram limit: 50MB for free)
            file_size = os.path.getsize(filepath)
            max_size = 50 * 1024 * 1024  # 50MB
            
            if file_size > max_size:
                await msg.edit_text(
                    f"❌ <b>Fayl juda katta!</b>\n\n"
                    f"Hajmi: {file_size / (1024*1024):.1f}MB\n"
                    f"Limit: 50MB\n\n"
                    "Pastroq sifatni tanlashga urinib ko'ring.",
                    parse_mode="HTML"
                )
                try:
                    os.remove(filepath)
                except:
                    pass
                return
            
            # Update top
            increment_top(real_title, url)
            
            # Save to history
            if user_id:
                db = load_db()
                user = get_user(db, user_id)
                user["downloads"] = user.get("downloads", 0) + 1
                
                h = {"title": real_title, "url": url, "time": datetime.now().isoformat()}
                if h not in user["history"]:
                    user["history"].insert(0, h)
                    user["history"] = user["history"][:20]
                save_db(db)
            
            # Buttons
            uid = url_to_id(url)
            keyboard = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("❤️ Sevimli", callback_data=f"fav|{uid}|{real_title[:25]}"),
                    InlineKeyboardButton("🎬 Video", callback_data=f"vid|{uid}"),
                ]
            ])
            
            # Send audio
            await msg.edit_text("✅ <b>Yuklandi!</b> Yuborilmoqda...", parse_mode="HTML")
            
            try:
                with open(filepath, "rb") as audio:
                    await context.bot.send_audio(
                        chat_id=chat_id,
                        audio=audio,
                        title=real_title[:200],
                        performer=artist[:100],
                        reply_markup=keyboard,
                        parse_mode="HTML"
                    )
            except Exception as e:
                logger.error(f"Send audio error: {e}")
                # Send as document
                with open(filepath, "rb") as doc:
                    await context.bot.send_document(
                        chat_id=chat_id,
                        document=doc,
                        caption=f"🎵 {real_title[:200]}",
                        reply_markup=keyboard
                    )
            
            # Cleanup
            try:
                os.remove(filepath)
            except:
                pass
            
            await msg.delete()
            
            # Clean memory
            gc.collect()
            
        except Exception as e:
            logger.error(f"File processing error: {e}")
            await msg.edit_text(f"❌ Xatolik: {str(e)[:100]}")
    else:
        await msg.edit_text("❌ Fayl topilmadi. Qayta urinib ko'ring.")

async def download_video(chat_id, url, context):
    """Video yuklab olish"""
    msg = await context.bot.send_message(
        chat_id=chat_id, 
        text="🎬 <b>Video yuklanmoqda...</b>",
        parse_mode="HTML"
    )
    
    import yt_dlp
    import uuid
    
    unique_id = uuid.uuid4().hex[:8]
    outfile = f"/tmp/video_{unique_id}.mp4"
    
    ydl_opts = {
        "format": "best[height<=720]/best",
        "outtmpl": outfile,
        "quiet": True,
        "noplaylist": True,
        "socket_timeout": 60,
        "retries": 3,
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            real_title = info.get("title", "Video")
    except Exception as e:
        logger.error(f"Video download error: {e}")
        await msg.edit_text(f"❌ Video yuklashda xatolik:





