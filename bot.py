import asyncio
import logging
import uuid
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from yoomoney import Quickpay, Client

# --- КОНФИГУРАЦИЯ ---
BOT_TOKEN = "8800941405:AAH0TZbP48M5grkVxZ-tvP7lxK72eTSg4yc"
YOOMONEY_TOKEN = "5133D1719448E2A5E1083A0FC605E369944CBB992B1D4490F13E2D4636C03191"
YOOMONEY_WALLET = "4100118935779591"
PRICE = 8000  # Цена в рублях

# Настройка логирования
logging.basicConfig(level=logging.INFO)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
yoomoney_client = Client(YOOMONEY_TOKEN)

# Текст объявления
AD_TEXT = (
    "<b>Забудьте о подписках навсегда! 🔒✨</b>\n\n"
    "Устали каждый месяц платить за VPN? Мы подготовили для вас ультимативное решение — "
    "тариф <b>«Навсегда»</b>. Один раз купили — и доступ к свободному интернету с вами всю жизнь!\n\n"
    "<b>Что вы получаете:</b>\n"
    "🚀 <b>Полный безлимит:</b> Никаких ограничений по трафику и скорости. Смотрите 4K-видео и скачивайте файлы.\n"
    "📱 <b>Свобода:</b> До 10 устройств одновременно (телефон, ноутбук, планшет — хватит всем!).\n"
    "🌍 <b>Весь мир:</b> Польша, Австрия, США, Испания, Франция, Сингапур, Гонконг, Оптимум и Ультра (LTE).\n\n"
    "🛡 <b>Поддержка:</b> Мы остаемся на связи 24/7. Ваша стабильная работа — наш приоритет.\n\n"
    f"💰 <b>Цена вопроса: {PRICE}₽.</b> Один раз и навсегда!"
)

# Главное меню
def main_keyboard():
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="💎 Купить тариф «Навсегда»", callback_data="buy_vpn"))
    builder.row(types.InlineKeyboardButton(text="🆘 Поддержка", url="https://t.me/твой_логин")) # ЗАМЕНИ НА СВОЙ ЛОГИН
    return builder.as_markup()

# Обработчик команды /start
@dp.message(Command("start"))
async def start_cmd(message: types.Message):
    await message.answer_photo(
        photo="https://i.imgur.com/8X5Q7pX.jpeg", # Можно заменить на свою картинку
        caption=AD_TEXT,
        parse_mode="HTML",
        reply_markup=main_keyboard()
    )

# Обработка нажатия кнопки "Купить"
@dp.callback_query(F.data == "buy_vpn")
async def create_order(callback: types.CallbackQuery):
    label = str(uuid.uuid4()) # Уникальный ID платежа
    
    quickpay = Quickpay(
        receiver=YOOMONEY_WALLET,
        quickpay_form="shop",
        targets="VPN Тариф Навсегда",
        paymentType="SB", # Оплата картой или кошельком
        sum=PRICE,
        label=label
    )

    kb = InlineKeyboardBuilder()
    kb.row(types.InlineKeyboardButton(text="💳 Перейти к оплате", url=quickpay.base_url))
    kb.row(types.InlineKeyboardButton(text="✅ Проверить оплату", callback_data=f"check_{label}"))
    kb.row(types.InlineKeyboardButton(text="⬅️ Назад", callback_data="back"))

    await callback.message.edit_caption(
        caption=f"<b>Оформление заказа</b>\n\nК оплате: <b>{PRICE}₽</b>\n\n"
                "После оплаты нажмите кнопку «Проверить оплату» ниже. "
                "Ваш личный ключ будет выдан мгновенно.",
        parse_mode="HTML",
        reply_markup=kb.as_markup()
    )

# Проверка оплаты
@dp.callback_query(F.data.startswith("check_"))
async def check_payment(callback: types.CallbackQuery):
    label = callback.data.split("_")[1]
    history = yoomoney_client.operation_history(label=label)
    
    if history.operations:
        operation = history.operations[-1]
        if operation.status == "success":
            # ТУТ ВСТАВЬ ТВОЙ КЛЮЧ ИЛИ ЛОГИКУ ВЫДАЧИ
            vpn_key = "YOUR_VPN_KEY_ABC123" 
            
            await callback.message.answer(
                f"🎉 <b>Оплата прошла успешно!</b>\n\n"
                f"Ваш вечный ключ: <code>{vpn_key}</code>\n\n"
                f"Инструкция по настройке: [ССЫЛКА]",
                parse_mode="HTML"
            )
            await callback.answer()
        else:
            await callback.answer("❌ Оплата еще не поступила.", show_alert=True)
    else:
        await callback.answer("❌ Платеж не найден. Если вы оплатили, подождите 1-2 минуты.", show_alert=True)

@dp.callback_query(F.data == "back")
async def go_back(callback: types.CallbackQuery):
    await callback.message.edit_caption(caption=AD_TEXT, parse_mode="HTML", reply_markup=main_keyboard())

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
