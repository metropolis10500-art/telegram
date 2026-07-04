import os
import requests
import google.generativeai as genai
from pyrogram import Client, filters
from dotenv import load_dotenv

# ==================== ЗАГРУЗКА СЕКРЕТОВ ====================
# Загружаем переменные из файла .env
load_dotenv()

# Достаем ключи из окружения
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
BOT_TOKEN = os.getenv("BOT_TOKEN")
API_ID = os.getenv("API_ID")
API_HASH = os.getenv("API_HASH")

# Проверка, что ключи загрузились
if not all([GEMINI_API_KEY, BOT_TOKEN, API_ID, API_HASH]):
    raise ValueError("❌ ОШИБКА: Не все ключи найдены! Проверь файл .env")

API_ID = int(API_ID) # Pyrogram требует число
# ==========================================================

# Настройка Gemini
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-1.5-flash')

# Создаем клиента бота
app = Client("seo_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# Функция скачивания видео без вотермарки через tikwm
def download_tiktok(video_url):
    api_url = "https://www.tikwm.com/api/"
    response = requests.post(api_url, data={'url': video_url})
    data = response.json()
    
    if data['code'] == 0:
        no_watermark_url = data['data']['play']
        title = data['data']['title']
        return no_watermark_url, title
    else:
        return None, None

# Функция генерации SEO
def generate_youtube_seo(tiktok_description):
    prompt = f"""
    Я перезаливаю видео из TikTok про мукбанг (девушка ест суши, бургеры, скумбрию и т.д.) на YouTube Shorts.
    Оригинальное описание из TikTok: "{tiktok_description}".
    
    Задача: Создай максимально кликабельный и виральный пакет SEO для YouTube Shorts на русском языке.
    Используй психологию кликбейта, интригу и эмоции.
    
    Выдай результат строго в таком формате:
    🎯 Заголовок (до 60 символов, с интригой, используй 1-2 эмодзи)
    📝 Описание (короткий пересказ с сильным призывом к действию, чтобы смотрели до конца и подписывались)
    #Хештеги (10 релевантных хештегов для мукбанга и Shorts в столбик)
    """
    
    try:
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        return f"❌ Ошибка генерации SEO: {e}"

# Обработчик ссылок TikTok
@app.on_message(filters.regex(r"https://(vm|www).tiktok.com/") & filters.private)
async def handle_tiktok(client, message):
    processing_msg = await message.reply("⏳ Скачиваю видео и анализирую через ИИ...")
    
    video_url = message.text.strip()
    
    video_link, tiktok_title = download_tiktok(video_url)
    
    if not video_link:
        await processing_msg.edit("❌ Не удалось скачать видео. Проверь ссылку.")
        return
        
    seo_text = generate_youtube_seo(tiktok_title)
    
    try:
        await message.reply_video(video_link, caption="✅ Видео скачано (без водяного знака)")
        await message.reply(f"🤖 **SEO-пакет от Gemini:**\n\n{seo_text}")
        await processing_msg.delete()
    except Exception as e:
        await processing_msg.edit(f"❌ Ошибка при отправке: {e}")

print("🚀 SEO-Бот запущен! Кидай ему ссылки на TikTok.")
app.run()
