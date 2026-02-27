import os
import json
import re
import hashlib
import gc
import logging
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

# ============== KONFIGURATSIYA ==============
TOKEN = "8312461995:AAEWbinigBntWn8AHUbEmf-hXGvFUFUTYOc"
YT_API_KEY = "AIzaSyCTHPm3oLBd-vXhl1JH9rEYOvbt1USOvzg"

# Logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ============== URL CACHE ==============
URL_CACHE = {}

def url_to_id(url):
    uid = hashlib.md5(url.encode()).hexdigest()[:12]
    URL_CACHE[uid] = url
    return uid

def id_to_url(uid):
    return URL_CACHE.get(uid, "")

# ============== DATABASE ==============
DB_FILE = "/tmp/users.json"
TOP_FILE = "/tmp/top.json"

def load_db():
    try:
        if os.path.exists(DB_FILE):
            with open(DB_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except: pass
    return {}

def save_db(db):
    try:
        with open(DB_FILE, "w", encoding="utf-8") as f:
            json.dump(db, f, ensure_ascii=False, indent=2)
    except: pass

def get_user(db, user_id):
    uid = str(user_id)
    if uid not in db:
        db[uid] = {"favorites": [], "history": [], "settings": {"results": 5}, "downloads": 0}
    return db[uid]

def load_top():
    try:
        if os.path.exists(TOP_FILE):
            with open(TOP_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except: pass
    return {}

def save_top(top):
    try:
        with open(TOP_FILE, "w", encoding="utf-8") as f:
            json.dump(top, f, ensure_ascii=False, indent=2)
    except: pass

def increment_top(title, url):
    top = load_top()
    if url not in top:
        top[url] = {"title": title, "count": 0}
    top[url]["count"] += 1
    save_top(top)

# ============== SEARCH ==============
def search_youtube_api(query, limit=5):
    if not YT_API_KEY:
        return search_youtube_ytdlp(query, limit)
    try:
        import requests
        url = "https://www.googleapis.com/youtube/v3/search"
        params = {"part": "snippet", "q": query, "type": "video", "maxResults": limit, "key": YT_API_KEY}
        res = requests.get(url, params=params, timeout=10)
        data = res.json()
        results = []
        for item in data.get("items", []):
            vid_id = item["id"]["videoId"]
            title = item["snippet"]["title"]
            channel = item["snippet"]["channelTitle"]
            yt_url = f"https://youtube.com/watch?v={vid_id}"
            results.append({
                "title": title, "url": yt_url, "uid": url_to_id(yt_url),
                "duration": "?", "channel": channel, "source": "🎬 YouTube"
            })
        return results
    except Exception as e:
        logger.error(f"YT API error: {e}")
        return search_youtube_ytdlp(query, limit)

def search_youtube_ytdlp(query, limit=5):
    import yt_dlp
    ydl_opts = {"quiet": True, "skip_download": True, "extract_flat": True, "no_warnings": True, "socket_timeout": 15}
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            result = ydl.extract_info(f"ytsearch{limit}:{query}", download=False)
            results = []
            for v in result.get("entries", []):
                if v and v.get("id"):
                    dur = v.get("duration", 0) or 0
                    yt_url = f"https://youtube.com/watch?v={v.get('id')}"
                    results.append({
                        "title": v.get("title", "Noma'lum"), "url": yt_url, "uid": url_to_id(yt_url),
                        "duration": f"{dur//60}:{dur%60:02d}" if dur else "?",
                        "channel": v.get("uploader", "YouTube"), "source": "🎬 YouTube"
                    })
            return results
    except Exception as e:
        logger.error(f"YT search error: {e}")
        return []

def search_soundcloud(query, limit=2):
    import yt_dlp
    ydl_opts = {"quiet": True, "skip_download": True, "extract_flat": True, "no_warnings": True, "socket_timeout": 15}
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            result = ydl.extract_info(f"scsearch{limit}:{query}", download=False)
            results = []
            for v in result.get("entries", []):
                if v:
                    dur = v.get("duration", 0) or 0
                    sc_url = v.get("webpage_url", "")
                    results.append({
                        "title": v.get("title", "Noma'lum"), "url": sc_url, "uid": url_to_id(sc_url),
                        "duration": f"{dur//60}:{dur%60:02d}" if dur else "?",
                        "channel": v.get("uploader", "SoundCloud"), "source": "🎵 SC"
                    })
            return results
    except Exception as e:
        logger.error(f"SC search error: {e}")
        return []

def combine_search(query, limit=5):
    import concurrent.futures
    results = []
    try:
        with concurrent.futures.ThreadPoolExecutor() as executor:
            yt_future = executor.submit(search_youtube_api, query, limit)
            sc_future = executor.submit(search_soundcloud, query, 2)
            yt_results = yt_future.result(timeout=12)
            sc_results = sc_future.result(timeout=12)
            results = (yt_results + sc_results)[:limit + 2]
    except Exception as e:
        logger.error(f"Combine error: {e}")
        results = search_youtube_ytdlp(query, limit)
    return results

# ============== DOWNLOAD ==============
async def download_audio(chat_id, url, title, context, user_id=None):
    msg = await context.bot.send_message(chat_id=chat_id, text="⏳ Yuklanmoqda...")
    
    import yt_dlp
    import uuid
    
    unique_id = uuid.uuid4().hex[:8]
    outfile = f"/tmp/audio_{unique_id}"
    
    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": f"{outfile}.%(ext)s",
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "socket_timeout": 90,
        "retries": 5,
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "192"
        }],
    }
    
    real_title = title
    artist = ""
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            real_title = info.get("title", title)
            artist = info.get("uploader", "")
            logger.info(f"Downloaded: {real_title}")
    except Exception as e:
        logger.error(f"Download error: {e}")
        
        ydl_opts2 = {
            "format": "bestaudio[ext=m4a]/best",
            "outtmpl": f"{outfile}.%(ext)s",
            "quiet": True,
            "noplaylist": True,
            "socket_timeout": 90,
            "retries": 5,
        }
        try:
            with yt_dlp.YoutubeDL(ydl_opts2) as ydl:
                info = ydl.extract_info(url, download=True)
                real_title = info.get("title", title)
                artist = info.get("uploader", "")
        except Exception as e2:
            logger.error(f"Second attempt error: {e2}")
            await msg.edit_text(
                "❌ <b>Xatolik!</b>\n\n"
                "Video himoyalangan yoki verification talab qiladi.\n"
                "Boshqa video tanlab ko'ring!",
                parse_mode="HTML"
            )
            return

    # Find file
    filepath = None
    for ext in ["mp3", "m4a", "webm", "opus", "ogg"]:
        p = f"{outfile}.{ext}"
        if os.path.exists(p):
            filepath = p
            break
    
    if not filepath:
        for f in os.listdir("/tmp"):
            if f.startswith("audio_") and f.endswith((".mp3", ".m4a", ".webm")):
                filepath = f"/tmp/{f}"
                break

    if filepath and os.path.exists(filepath):
        try:
            file_size = os.path.getsize(filepath)
            if file_size > 50 * 1024 * 1024:
                await msg.edit_text("❌ Fayl 50MB dan katta!")
                os.remove(filepath)
                return
            
            increment_top(real_title, url)
            
            if user_id:
                db = load_db()
                user = get_user(db, user_id)
                user["downloads"] = user.get("downloads", 0) + 1
                h = {"title": real_title, "url": url}
                if h not in user["history"]:
                    user["history"].insert(0, h)
                    user["history"] = user["history"][:15]
                save_db(db)
            
            uid = url_to_id(url)
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("❤️ Sevimli", callback_data=f"fav|{uid}|{real_title[:25]}"),
                 InlineKeyboardButton("🎬 Video", callback_data=f"vid|{uid}")]
            ])
            
            try:
                with open(filepath, "rb") as audio:
                    await context.bot.send_audio(
                        chat_id=chat_id, audio=audio,
                        title=real_title[:200], performer=artist[:100],
                        reply_markup=keyboard
                    )
            except Exception as e:
                logger.error(f"Send error: {e}")
                with open(filepath, "rb") as doc:
                    await context.bot.send_document(
                        chat_id=chat_id, document=doc,
                        caption=f"🎵 {real_title}", reply_markup=keyboard
                    )
            
            try:
                os.remove(filepath)
            except: pass
            
            await msg.delete()
            gc.collect()
            
        except Exception as e:
            logger.error(f"Process error: {e}")
            await msg.edit_text(f"❌ Xatolik: {str(e)[:50]}")
    else:
        await msg.edit_text("❌ Fayl topilmadi.")

async def download_video(chat_id, url, context):
    msg = await context.bot.send_message(chat_id=chat_id, text="🎬 Video yuklanmoqda...")
    
    import yt_dlp
    import uuid
    
    unique_id = uuid.uuid4().hex[:8]
    outfile = f"/tmp/video_{unique_id}.mp4"
    
    ydl_opts = {
        "format": "best[height<=480]/best",
        "outtmpl": outfile,
        "quiet": True,
        "noplaylist": True,
        "socket_timeout": 90,
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            real_title = info.get("title", "Video")
    except Exception as e:
        logger.error(f"Video error: {e}")
        await msg.edit_text("❌ Video yuklashda xatolik!")
        return

    if os.path.exists(outfile):
        if os.path.getsize(outfile) > 50 * 1024 * 1024:
            await msg.edit_text("❌ Video 50MB dan katta!")
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

# ============== KEYBOARDS ==============
def main_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔍 Qidirish", switch_inline_query_current_chat=""),
         InlineKeyboardButton("❤️ Sevimlilar", callback_data="my_fav")],
        [InlineKeyboardButton("🏆 Top 10", callback_data="top10"),
         InlineKeyboardButton("📜 Tarix", callback_data="history")],
        [InlineKeyboardButton("⚙️ Sozlamalar", callback_data="settings"),
         InlineKeyboardButton("ℹ️ Yordam", callback_data="help")],
    ])

# ============== HANDLERS ==============
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await update.message.reply_text(
        f"🎵 *Salom, {user.first_name}!*\n\n"
        "🎬 YouTube — mp3 + video\n"
        "🎵 SoundCloud — mp3\n\n"
        "📌 Qo'shiq nomi yoki link yuboring!",
        parse_mode="Markdown",
        reply_markup=main_keyboard()
    )

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    chat_id = update.message.chat_id
    user_id = update.effective_user.id

    # YouTube link
    if re.search(r"(youtube\.com|youtu\.be)", text):
        uid = url_to_id(text)
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🎵 MP3", callback_data=f"dl|{uid}"),
             InlineKeyboardButton("🎬 Video", callback_data=f"vid|{uid}")]
        ])
        await update.message.reply_text("YouTube link! Nima yuklamoqchisiz?", reply_markup=keyboard)
        return

    # Other links
    if re.search(r"https?://", text):
        await download_video(chat_id, text, context)
        return

    # Search
    db = load_db()
    user = get_user(db, user_id)
    limit = user["settings"]["results"]

    msg = await update.message.reply_text(f"🔍 *{text}* qidirilmoqda...", parse_mode="Markdown")

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
        buttons.append([InlineKeyboardButton(f"{nums[i]} {r['title'][:45]}", callback_data=f"dl|{r['uid']}")])

    await msg.edit_text(result_text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(buttons))

# ============== CALLBACK ==============
async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = update.effective_user.id
    chat_id = query.message.chat_id

    if data.startswith("dl|"):
        uid = data.split("|")[1]
        url = id_to_url(uid)
        if not url:
            await query.answer("❌ Muddati o'tgan. Qayta qidiring.", show_alert=True)
            return
        await download_audio(chat_id, url, "Qoshiq", context, user_id)

    elif data.startswith("vid|"):
        uid = data.split("|")[1]
        url = id_to_url(uid)
        if not url:
            await query.answer("❌ Muddati o'tgan. Qayta qidiring.", show_alert=True)
            return
        await download_video(chat_id, url, context)

    elif data.startswith("fav|"):
        parts = data.split("|")
        uid = parts[1]
        title = parts[2] if len(parts) > 2 else "Qoshiq"
        url = id_to_url(uid)
        if not url:
            await query.answer("❌ Muddati






