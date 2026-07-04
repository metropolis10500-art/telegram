import asyncio
import io
import re
from pyrogram import Client, filters
from pyrogram.errors import FloodWait
from pyrogram.types import InputMediaPhoto, InputMediaVideo, Message

# --- НАСТРОЙКИ ---
API_ID = 36895411  # Твой API ID
API_HASH = "c3cba5f8e4f0143ac2976f6459a5b612"  # Твой API HASH
BOT_TOKEN = "8038462440:AAEoCfxTBFwfJhhDjRRJcOKhB9820rqGs6o"  # Токен бота

SOURCE_CHAT = "zakadrombriya"
TARGET_CHAT = "mukbang_natik"

DB_FILE = "progress.txt"
INTERVAL = 900  # 15 минут (900 секунд)

app = Client("my_userbot", api_id=API_ID, api_hash=API_HASH)
bot = Client("my_bot_publisher", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

posted_live_ids = set()


# Функция очистки текста от ссылок на оригинальный канал
def clean_text(text: str) -> str:
    if not text:
        return ""
    text = re.sub(rf"@{SOURCE_CHAT}\b", "", text, flags=re.IGNORECASE)
    text = re.sub(
        rf"https?://t\.me/{SOURCE_CHAT}/\S*", "", text, flags=re.IGNORECASE
    )
    text = re.sub(rf"t\.me/{SOURCE_CHAT}", "", text, flags=re.IGNORECASE)
    return text.strip()


def get_last_sent_id():
    try:
        with open(DB_FILE, "r") as f:
            return int(f.read().strip())
    except FileNotFoundError:
        return 0


def save_last_sent_id(message_id):
    with open(DB_FILE, "w") as f:
        f.write(str(message_id))


# Безопасное выполнение запросов с защитой от лимитов (FloodWait)
async def safe_send(action, *args, **kwargs):
    while True:
        try:
            return await action(*args, **kwargs)
        except FloodWait as e:
            print(f"[Предупреждение] Лимит запросов! Ждем {e.value} сек...")
            await asyncio.sleep(e.value)
        except Exception as e:
            print(f"[Ошибка] Не удалось отправить: {e}")
            return None


# Функция для скачивания файла в оперативную память
async def download_to_memory(client, message):
    try:
        file_buffer = io.BytesIO()
        await client.download_media(message, in_memory=file_buffer)
        file_buffer.seek(0)  # Сбрасываем указатель в начало файла
        return file_buffer
    except Exception as e:
        print(f"[Ошибка] Не удалось скачать медиа из поста {message.id}: {e}")
        return None


# Новая функция чистой публикации (без плашки "Переслано от...")
async def publish_clean_post(messages):
    # Если на вход пришел ОДИНОЧНЫЙ пост
    if not isinstance(messages, list):
        msg = messages
        new_caption = clean_text(msg.text or msg.caption)

        if msg.media:
            # Скачиваем файл в ОЗУ
            file_data = await download_to_memory(app, msg)
            if not file_data:
                return False

            # Определяем тип медиа и публикуем его "чистым" способом
            if msg.photo:
                return await safe_send(
                    bot.send_photo,
                    chat_id=TARGET_CHAT,
                    photo=file_data,
                    caption=new_caption,
                )
            elif msg.video:
                return await safe_send(
                    bot.send_video,
                    chat_id=TARGET_CHAT,
                    video=file_data,
                    caption=new_caption,
                )
            elif msg.animation:  # GIF-анимации
                return await safe_send(
                    bot.send_animation,
                    chat_id=TARGET_CHAT,
                    animation=file_data,
                    caption=new_caption,
                )
            elif msg.voice:  # Голосовые сообщения
                return await safe_send(
                    bot.send_voice,
                    chat_id=TARGET_CHAT,
                    voice=file_data,
                    caption=new_caption,
                )
        elif msg.text:
            # Если это просто текст
            return await safe_send(
                bot.send_message, chat_id=TARGET_CHAT, text=new_caption
            )
        return False

    # Если на вход пришел АЛЬБОМ (медиагруппа)
    media_album = []
    text_copied = False
    downloaded_files = []  # Храним буферы, чтобы они не стерлись из памяти во время отправки

    for m in messages:
        caption = clean_text(m.caption) if not text_copied else ""
        if caption:
            text_copied = True

        file_data = await download_to_memory(app, m)
        if not file_data:
            continue
        downloaded_files.append(file_data)

        if m.photo:
            media_album.append(
                InputMediaPhoto(media=file_data, caption=caption)
            )
        elif m.video:
            media_album.append(
                InputMediaVideo(media=file_data, caption=caption)
            )

    if media_album:
        success = await safe_send(
            bot.send_media_group, chat_id=TARGET_CHAT, media=media_album
        )
        return success
    return False


# --- ЧАСТЬ 1: ИСТОРИЯ ---
async def history_publisher():
    await asyncio.sleep(10)
    print("[История] Скрипт запущен.")

    while True:
        last_sent_id = get_last_sent_id()
        next_msg_id = last_sent_id + 1

        if next_msg_id in posted_live_ids:
            print(
                f"[История] Пост {next_msg_id} уже был опубликован через LIVE. Пропуск."
            )
            save_last_sent_id(next_msg_id)
            continue

        try:
            message = await app.get_messages(SOURCE_CHAT, next_msg_id)

            if (
                message
                and not message.empty
                and (message.text or message.media)
            ):

                if message.media_group_id:
                    album = await app.get_media_group(
                        SOURCE_CHAT, next_msg_id
                    )
                    max_album_id = max(m.id for m in album)

                    print(
                        f"[История] Публикуем альбом из {len(album)} файлов (ID {next_msg_id} - {max_album_id}) от имени канала..."
                    )
                    success = await publish_clean_post(album)

                    if success:
                        save_last_sent_id(max_album_id)
                        print(f"[История] Успешно. Ждем {INTERVAL} секунд...")
                        await asyncio.sleep(INTERVAL)
                else:
                    print(
                        f"[История] Публикуем пост ID {message.id} от имени канала..."
                    )
                    success = await publish_clean_post(message)
                    if success:
                        save_last_sent_id(message.id)
                        print(f"[История] Успешно. Ждем {INTERVAL} секунд...")
                        await asyncio.sleep(INTERVAL)
            else:
                save_last_sent_id(next_msg_id)
                await asyncio.sleep(0.5)

        except Exception as e:
            print(
                f"[История] Ожидание новых постов в источнике (ошибка/конец: {e})"
            )
            await asyncio.sleep(60)


# --- ЧАСТЬ 2: LIVE СЛУШАТЕЛЬ ---
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
                print(f"[LIVE] Публикуем новый альбом от имени канала...")
                await publish_clean_post(album)
        except Exception as e:
            print(f"[LIVE] Ошибка обработки альбома: {e}")
    else:
        print(
            f"[LIVE] Публикуем одиночный пост ID {message.id} от имени канала..."
        )
        await publish_clean_post(message)


async def main():
    print("Запуск...")
    await app.start()
    await bot.start()
    print("Бот и Юзербот успешно запущены!")

    asyncio.create_task(history_publisher())
    await asyncio.Event().wait()


if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())
