import os
import requests
import google.generativeai as genai
from pyrogram import Client, filters

# ==================== НАСТРОЙКИ ====================
# 1. Вставь СЮДА свой НОВЫЙ ключ Gemini (никому его не показывай!)
GEMINI_API_KEY = "AQ.Ab8RN6ISnwRPEa2FbglFu38uJYvrayoMUdxXUm3KHjiURLvJtg"

# 2. Токен твоего бота из @BotFather
BOT_TOKEN = "8038462440:AAEoCfxTBFwfJhhDjRRJcOKhB9820rqGs6o"

# 3. Твой API ID и API HASH (которые ты использовал для сессии)
API_ID = 36895411  # Твой API ID
API_HASH = "c3cba5f8e4f0143ac2976f6459a5b612"  # Твой API HASH
# ===================================================

# Настройка Gemini
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-pro')

# Создаем клиента бота
app = Client("seo_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# Функция скачивания видео без вотермарки через tikwm
def download_tiktok(video_url):
    api_url = "https://www.tikwm.com/api/"
    response = requests.post(api_url, data={'url': video_url})
    data = response.json()
    
    if data['code'] == 0:
        # Получаем ссылку на видео без водяного знака
        no_watermark_url = data['data']['play']
        # Получаем оригинальное описание из TikTok
        title = data['data']['title']
        return no_watermark_url, title
    else:
        return None, None

# Функция генерации SEO через Gemini
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
    # Сообщаем, что бот начал работу
    processing_msg = await message.reply("⏳ Скачиваю видео и анализирую через ИИ... Подожди немного.")
    
    video_url = message.text.strip()
    
    # 1. Скачиваем видео и достаем описание
    video_link, tiktok_title = download_tiktok(video_url)
    
    if not video_link:
        await processing_msg.edit("❌ Не удалось скачать видео. Проверь ссылку.")
        return
        
    # 2. Генерируем SEO через Gemini
    seo_text = generate_youtube_seo(tiktok_title)
    
    # 3. Отправляем результат пользователю
    try:
        # Сначала отправляем само видео, чтобы его можно было скачать
        await message.reply_video(video_link, caption="✅ Видео скачано (без водяного знака)")
        
        # Затем отправляем сгенерированный SEO-текст
        await message.reply(f"🤖 **SEO-пакет от Gemini:**\n\n{seo_text}")
        
        # Удаляем сообщение "Подожди немного"
        await processing_msg.delete()
    except Exception as e:
        await processing_msg.edit(f"❌ Ошибка при отправке: {e}")

print("🚀 SEO-Бот запущен! Кидай ему ссылки на TikTok.")
app.run()
