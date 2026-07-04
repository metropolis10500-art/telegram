import asyncio
import os
import uuid
import re

from pyrogram import Client, filters
from pyrogram.errors import FloodWait
from pyrogram.types import InputMediaPhoto, InputMediaVideo, Message

# ==================== ЗАПОЛНИ ЭТИ ЗНАЧЕНИЯ ====================
API_ID = 36895411  # Твой API ID
API_HASH = "c3cba5f8e4f0143ac2976f6459a5b612"  # Твой API HASH
BOT_TOKEN = "8038462440:AAEoCfxTBFwfJhhDjRRJcOKhB9820rqGs6o"  # Токен бота-паблишера

# ВСТАВЬ СЮДА СТРОКУ ИЗ ФАЙЛА my_session_string.txt
SESSION_STRING = "AgIy-rMAIIIXzYvdcANhco5l7O30zrBnbtkgp-RuiY9InOJnsLNDT9Jiuqj-3WT0iSWrB3VYZ_-WpzD0PR1Cg4mpwpSGGbj_YJ9xLfMXT-SlRDR9qyFj-d8wma-93hxSX_mgU2KDEeTYVwcMKu_vjIRhwutuXIE1JRDunrB7su5n4yyBp5KJyhPwt6EXERfCtzjMbcqOFD3jbdN3VUel3gIIXonQ42q2KIg-SZUNSUBJJi5G98UKIjBZO3dLkrKzWUxltG0ipVUx2q5Xf7ju7k8GhgXC2nmNJ7ePxs38BqVNtKkXQki90HnN-l-7BYR-eIvd5j7xjHkWenPevza7qNmFskN2RAAAAAFHgBc7AA"

SOURCE_CHAT = "zakadrombriya"
TARGET_CHAT = "mukbang_natik"

INTERVAL = 180  # 3 минут между постами
# ==============================================================

DB_FILE = "progress.txt"
TEMP_DIR = "temp_downloads"

os.makedirs(TEMP_DIR, exist_ok=True)

if not all([API_ID, API_HASH, BOT_TOKEN, SESSION_STRING, SOURCE_CHAT, TARGET_CHAT]):
    raise ValueError("❌ Заполни ВСЕ настройки в начале файла bot.py!")

# ==================== КЛИЕНТЫ ====================
# Обрати внимание: здесь используется session_string
app = Client(
    name="my_userbot_string", 
    api_id=API_ID, 
    api_hash=API_HASH, 
    session_string=SESSION_STRING
)

bot = Client(
    name="publisher_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
)

posted_live_ids = set()

# ==================== ФУНКЦИИ ====================
def clean_text(text: str) -> str:
    if not text:
        return ""
    text = re.sub(rf"@{re.escape(SOURCE_CHAT)}\b", "", text, flags=re.IGNORECASE)
    text = re.sub(rf"https?://t\.me/{re.escape(SOURCE_CHAT)}\b", "", text, flags=re.IGNORECASE)
    text = re.sub(rf"t\.me/{re.escape(SOURCE_CHAT)}\b", "", text, flags=re.IGNORECASE)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()

def get_last_sent_id() -> int:
    try:
        with open(DB_FILE, "r", encoding="utf-8") as f:
            content = f.read().strip()
            return int(content) if content else 0
    except (FileNotFoundError, ValueError):
        return 0

def save_last_sent_id(message_id: int):
    with open(DB_FILE, "w", encoding="utf-8") as f:
        f.write(str(message_id))

async def try_send(action, *args, **kwargs):
    for attempt in range(3):
        try:
            return await action(*args, **kwargs)
        except FloodWait as e:
            print(f"[⚠️ FloodWait] Ждём {e.value} сек...")
            await asyncio.sleep(e.value)
        except Exception as e:
            print(f"[❌ Ошибка отправки] Попытка {attempt + 1}/3: {e}")
            if attempt == 2:
                return None
            await asyncio.sleep(2)
    return None

def cleanup_file(file_path: str | None):
    if file_path and os.path.exists(file_path):
        try:
            os.remove(file_path)
        except Exception:
            pass

async def download_to_file(client, message: Message) -> str | None:
    temp_path = os.path.join(TEMP_DIR, str(uuid.uuid4()))
    try:
        file_path = await asyncio.wait_for(
            client.download_media(message, file_name=temp_path), 
            timeout=120.0
        )
        if file_path is None:
            return None
        
        if os.path.getsize(file_path) == 0:
            cleanup_file(file_path)
            return None
            
        return file_path
        
    except asyncio.TimeoutError:
        print(f"[❌] Таймаут 120 сек! Файл не скачался.")
        cleanup_file(temp_path)
        return None
    except Exception as e:
        print(f"[❌] Ошибка скачивания на диск: {e}")
        cleanup_file(temp_path)
        return None

async def publish_single(msg: Message):
    caption = clean_text(msg.caption or msg.text or "")
    
    if not msg.media:
        return await try_send(bot.send_message, TARGET_CHAT, caption)
    
    file_path = await download_to_file(app, msg)
    
    if not file_path:
        if caption:
            return await try_send(bot.send_message, TARGET_CHAT, caption)
        return False
    
    try:
        if msg.photo:
            result = await try_send(bot.send_photo, TARGET_CHAT, file_path, caption=caption)
        elif msg.video:
            result = await try_send(bot.send_video, TARGET_CHAT, file_path, caption=caption)
        elif msg.animation:
            result = await try_send(bot.send_animation, TARGET_CHAT, file_path, caption=caption)
        elif msg.audio:
            result = await try_send(bot.send_audio, TARGET_CHAT, file_path, caption=caption)
        elif msg.voice:
            result = await try_send(bot.send_voice, TARGET_CHAT, file_path, caption=caption)
        elif msg.document:
            result = await try_send(bot.send_document, TARGET_CHAT, file_path, caption=caption)
        elif msg.video_note:
            result = await try_send(bot.send_video_note, TARGET_CHAT, file_path)
            if result and caption:
                await try_send(bot.send_message, TARGET_CHAT, caption)
        elif msg.sticker:
            result = await try_send(bot.send_sticker, TARGET_CHAT, file_path)
            if result and caption:
                await try_send(bot.send_message, TARGET_CHAT, caption)
        else:
            result = False
        return result
    finally:
        cleanup_file(file_path)

async def publish_album(messages: list[Message]):
    media_group = []
    downloaded_paths = []
    caption_used = False

    for m in messages:
        caption = clean_text(m.caption or "") if not caption_used else ""
        if caption:
            caption_used = True

        file_path = await download_to_file(app, m)
        if not file_path:
            continue

        downloaded_paths.append(file_path)

        if m.photo:
            media_group.append(InputMediaPhoto(media=file_path, caption=caption))
        elif m.video:
            media_group.append(InputMediaVideo(media=file_path, caption=caption))
        else:
            cleanup_file(file_path)
            if file_path in downloaded_paths:
                downloaded_paths.remove(file_path)

    try:
        if media_group:
            result = await try_send(bot.send_media_group, TARGET_CHAT, media=media_group)
            return result
        return False
    finally:
        for fp in downloaded_paths:
            cleanup_file(fp)

async def publish_clean_post(messages):
    if isinstance(messages, list):
        return await publish_album(messages)
    else:
        return await publish_single(messages)

# ==================== ИСТОРИЯ ====================
async def history_publisher():
    await asyncio.sleep(5)
    print("[📚] Запущен парсер истории...")
    empty_count = 0

    while True:
        last_id = get_last_sent_id()
        next_id = last_id + 1

        if next_id in posted_live_ids:
            save_last_sent_id(next_id)
            continue

        try:
            msg = await app.get_messages(SOURCE_CHAT, next_id)

            if not msg or msg.empty or not (msg.text or msg.media):
                empty_count += 1
                save_last_sent_id(next_id)
                if empty_count >= 50:
                    await asyncio.sleep(60)
                    empty_count = 0
                else:
                    await asyncio.sleep(0.5)
                continue
            
            empty_count = 0

            if msg.media_group_id:
                album = await app.get_media_group(SOURCE_CHAT, next_id)
                max_id = max(m.id for m in album)

                if any(m.id in posted_live_ids for m in album):
                    save_last_sent_id(max_id)
                    continue

                success = await publish_clean_post(album)
                save_last_sent_id(max_id)
                
                if success:
                    print(f"[📚] ✅ Отправлен альбом. Ждём {INTERVAL} сек...")
                    await asyncio.sleep(INTERVAL)
                else:
                    await asyncio.sleep(5)
            else:
                success = await publish_clean_post(msg)
                save_last_sent_id(msg.id)
                
                if success:
                    print(f"[📚] ✅ Отправлен пост. Ждём {INTERVAL} сек...")
                    await asyncio.sleep(INTERVAL)
                else:
                    await asyncio.sleep(5)

        except Exception as e:
            print(f"[📚] ⚠️ Ошибка: {e}")
            await asyncio.sleep(60)

# ==================== LIVE ====================
@app.on_message(filters.chat(SOURCE_CHAT))
async def live_publisher(client, message: Message):
    if message.empty or (not message.text and not message.media):
        return

    posted_live_ids.add(message.id)

    if message.media_group_id:
        await asyncio.sleep(2)
        try:
            album = await app.get_media_group(SOURCE_CHAT, message.id)
            for m in album:
                posted_live_ids.add(m.id)

            if message.id == min(m.id for m in album):
                await publish_clean_post(album)
        except Exception as e:
            print(f"[🔴 LIVE] ❌ Ошибка альбома: {e}")
    else:
        await publish_clean_post(message)

# ==================== ЗАПУСК ====================
async def main():
    print("🚀 Запуск бота...")
    
    await app.start()
    print("✅ Юзербот подключен (через SESSION_STRING)")
    
    await bot.start()
    print("✅ Бот-паблишер подключен")
    
    try:
        source = await app.get_chat(SOURCE_CHAT)
        print(f"✅ Источник доступен: {source.title}")
    except Exception as e:
        print(f"❌ НЕТ ДОСТУПА к источнику {SOURCE_CHAT}: {e}")
        return

    try:
        target = await bot.get_chat(TARGET_CHAT)
        print(f"✅ Целевой канал доступен: {target.title}")
    except Exception as e:
        print(f"❌ НЕТ ДОСТУПА к целевому каналу {TARGET_CHAT}: {e}")
        return

    asyncio.create_task(history_publisher())
    print("📚 Парсер истории запущен. Бот работает.")
    
    await asyncio.Event().wait()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n🛑 Бот остановлен")
    except Exception as e:
        print(f"\n💥 Критическая ошибка: {e}")
