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
PRICE = 8000

logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
yoomoney_client = Client(YOOMONEY_TOKEN)

# --- ТЕКСТЫ ---
MAIN_TEXT = (
    "<b>💎 ПРЕМИУМ ДОСТУП: ТАРИФ «НАВСЕГДА»</b>\n"
    "<i>Забудьте о ежемесячных платежах и блокировках</i>\n\n"
    "⚡️ <b>Один платеж — вечный доступ.</b>\n"
    "Вы инвестируете в свободу интернета один раз, и больше никогда не тратите ни рубля.\n\n"
    "🚀 <b>Ваши преимущества:</b>\n"
    "├ <b>Безлимит:</b> Скорость до 1 Гбит/с, трафик не ограничен.\n"
    "├ <b>Семья:</b> До 10 устройств на один ключ одновременно.\n"
    "└ <b>Стабильность:</b> Протоколы VLESS/Shadowsocks (не блокируются).\n\n"
    "💰 <b>Стоимость:</b> <code>8 000₽</code> (вместо <s>24 000₽</s> за несколько лет подписок)\n\n"
    "👇 <i>Выберите действие ниже:</i>"
)

SERVERS_TEXT = (
    "<b>🌍 НАШИ ЛОКАЦИИ И СЕРВЕРА:</b>\n\n"
    "📍 <b>Европа:</b> Польша, Австрия, Испания, Франция\n"
    "📍 <b>Азия:</b> Сингапур, Гонконг\n"
    "📍 <b>Америка:</b> США (Нью-Йорк)\n\n"
    "🔥 <b>Спец-узлы:</b>\n"
    "— <code>Оптимум:</code> Авто-выбор самой низкой задержки.\n"
    "— <code>Ультра (LTE):</code> Белые списки для мобильных операторов.\n\n"
    "<i>Все сервера работают на 10-гигабитных портах.</i>"
)

# --- КЛАВИАТУРЫ ---
def get_main_kb():
    kb = InlineKeyboardBuilder()
    kb.row(types.InlineKeyboardButton(text="💳 ОФОРМИТЬ ПОДПИСКУ", callback_data="buy_vpn"))
    kb.row(
        types.InlineKeyboardButton(text="🌍 Список локаций", callback_data="servers"),
        types.InlineKeyboardButton(text="🛡 Поддержка", url="https://t.me/твой_логин")
    )
    return kb.as_markup()

def get_payment_kb(url, label):
    kb = InlineKeyboardBuilder()
    kb.row(types.InlineKeyboardButton(text="🔗 Перейти к оплате (ЮMoney)", url=url))
    kb.row(types.InlineKeyboardButton(text="💎 Я ОПЛАТИЛ", callback_data=f"check_{label}"))
    kb.row(types.InlineKeyboardButton(text="⬅️ Назад", callback_data="back"))
    return kb.as_markup()

# --- ОБРАБОТЧИКИ ---
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    # Желательно загрузить картинку в телеграм и использовать её file_id
    await message.answer_photo(
        photo="https://i.imgur.com/8X5Q7pX.jpeg", # Поставь сюда крутой баннер
        caption=MAIN_TEXT,
        parse_mode="HTML",
        reply_markup=get_main_kb()
    )

@dp.callback_query(F.data == "servers")
async def show_servers(callback: types.CallbackQuery):
    await callback.answer() # Убирает "часики" моментально
    await callback.message.edit_caption(
        caption=SERVERS_TEXT,
        parse_mode="HTML",
        reply_markup=InlineKeyboardBuilder().row(
            types.InlineKeyboardButton(text="⬅️ Назад", callback_data="back")
        ).as_markup()
    )

@dp.callback_query(F.data == "buy_vpn")
async def buy_process(callback: types.CallbackQuery):
    await callback.answer()
    label = str(uuid.uuid4())
    quickpay = Quickpay(
        receiver=YOOMONEY_WALLET,
        quickpay_form="shop",
        targets="VPN Lifetime Access",
        paymentType="SB",
        sum=PRICE,
        label=label
    )
    
    await callback.message.edit_caption(
        caption=(
            "<b>💎 ОФОРМЛЕНИЕ ЗАКАЗА</b>\n\n"
            f"Вы покупаете: <b>VPN Тариф «Навсегда»</b>\n"
            f"К оплате: <b>{PRICE}₽</b>\n\n"
            "1. Нажмите кнопку ниже и оплатите счет.\n"
            "2. После оплаты нажмите «Я ОПЛАТИЛ».\n"
            "3. Бот мгновенно выдаст ваш ключ."
        ),
        parse_mode="HTML",
        reply_markup=get_payment_kb(quickpay.base_url, label)
    )

@dp.callback_query(F.data.startswith("check_"))
async def check_pay(callback: types.CallbackQuery):
    # ВАЖНО: сначала убираем загрузку с кнопки
    await callback.answer("Проверяем транзакцию...") 
    
    label = callback.data.split("_")[1]
    try:
        history = yoomoney_client.operation_history(label=label)
        if history.operations:
            operation = history.operations[-1]
            if operation.status == "success":
                await callback.message.answer(
                    "🎉 <b>ДОСТУП ОТКРЫТ!</b>\n\n"
                    "Ваш вечный ключ: <code>KEY_LIFETIME_SERVER_777</code>\n\n"
                    "Инструкция: https://telegra.ph/setup-vpn",
                    parse_mode="HTML"
                )
                return
    except Exception as e:
        logging.error(f"Ошибка ЮMoney: {e}")

    # Если оплаты нет, уведомляем всплывающим окном
    await callback.answer("❌ Оплата не найдена. Попробуйте через минуту.", show_alert=True)

@dp.callback_query(F.data == "back")
async def go_back(callback: types.CallbackQuery):
    await callback.answer()
    await callback.message.edit_caption(caption=MAIN_TEXT, parse_mode="HTML", reply_markup=get_main_kb())

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
