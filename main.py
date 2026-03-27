import asyncio
import logging
from datetime import datetime
from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    BotCommand,
)
from aiogram.filters import CommandStart, Command
from aiogram.enums import ParseMode
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.client.default import DefaultBotProperties  # ← ДОБАВЛЕНО

# ╔══════════════════════════════════════════╗
# ║           🔧  НАСТРОЙКИ БОТА            ║
# ╚══════════════════════════════════════════╝

BOT_TOKEN = "8716851473:AAGoKFIq5XJsxkXwolIffZy0WY_vVoRXTdQ"
ADMIN_USERNAME = "@vladofix28"
ADMIN_ID = 5494544187

bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)  # ← ИСПРАВЛЕНО
)
dp = Dispatcher()
router = Router()
dp.include_router(router)

# ╔══════════════════════════════════════════╗
# ║          💾  БАЗА ДАННЫХ (RAM)           ║
# ╚══════════════════════════════════════════╝

orders_db = {}

reviews_db = [
    # ── 🔥 РЕЗУЛЬТАТЫ ──
    {
        "user": "Александр К.",
        "text": "Заказал рассылку для своего канала — за сутки пришло 300+ подписчиков! Не ожидал такого результата 🔥",
        "rating": "⭐⭐⭐⭐⭐",
    },
    {
        "user": "Марина С.",
        "text": "Быстро, качественно и по делу. Менеджер ответил за 5 минут, рассылка ушла в тот же день. Рекомендую! 💯",
        "rating": "⭐⭐⭐⭐⭐",
    },
    {
        "user": "Дмитрий В.",
        "text": "Отличный охват! Мой пост увидели тысячи людей, заявки посыпались сразу 👍",
        "rating": "⭐⭐⭐⭐⭐",
    },
    {
        "user": "Екатерина Л.",
        "text": "Лучший сервис рассылки, с которым я работала. Всё честно и прозрачно ❤️",
        "rating": "⭐⭐⭐⭐⭐",
    },
    {
        "user": "Артём Р.",
        "text": "Заказываю уже третий раз. Каждый раз стабильный результат. Спасибо команде! 🚀",
        "rating": "⭐⭐⭐⭐⭐",
    },
    {
        "user": "Ольга М.",
        "text": "Продвигала свой интернет-магазин — получила реальные заказы уже в первый день после рассылки! 🛍️",
        "rating": "⭐⭐⭐⭐⭐",
    },
    {
        "user": "Игорь Т.",
        "text": "Сначала сомневался, но решил попробовать. Результат превзошёл ожидания! Теперь постоянный клиент 💪",
        "rating": "⭐⭐⭐⭐⭐",
    },
    {
        "user": "Наталья Д.",
        "text": "Очень довольна! Канал вырос на 500 подписчиков за неделю после рассылки. Буду заказывать ещё! 📈",
        "rating": "⭐⭐⭐⭐⭐",
    },
    {
        "user": "Максим Б.",
        "text": "Адекватная цена за такой охват. 500 000 аудитория — это серьёзно. Рекомендую всем! 🎯",
        "rating": "⭐⭐⭐⭐⭐",
    },
    {
        "user": "Анна П.",
        "text": "Продвигала бота — за день получила 200+ новых пользователей. Отличный сервис! ✨",
        "rating": "⭐⭐⭐⭐⭐",
    },
    # ── 💎 СЕРВИС ──
    {
        "user": "Сергей Н.",
        "text": "Понравилось, что всё честно — сказали что гарантируют охват, а не подписки. И охват реально огромный! 👏",
        "rating": "⭐⭐⭐⭐⭐",
    },
    {
        "user": "Виктория А.",
        "text": "Менеджер помог составить текст рассылки, подсказал как лучше оформить. Сервис на высоте! 💖",
        "rating": "⭐⭐⭐⭐⭐",
    },
    {
        "user": "Павел Г.",
        "text": "Быстрая обработка заказа. Оплатил — через 3 часа рассылка уже пошла. Супер! ⚡",
        "rating": "⭐⭐⭐⭐⭐",
    },
    {
        "user": "Ирина К.",
        "text": "Заказывала для продвижения курсов. Получила 50 заявок за первые сутки. Очень довольна! 📚",
        "rating": "⭐⭐⭐⭐⭐",
    },
    {
        "user": "Денис Ф.",
        "text": "Пробовал разные сервисы — этот лучший по соотношению цена/качество. Однозначно рекомендую! 🏆",
        "rating": "⭐⭐⭐⭐⭐",
    },
    {
        "user": "Алина В.",
        "text": "Продвигала канал с рецептами — подписчики пришли живые и активные. Спасибо! 🍳",
        "rating": "⭐⭐⭐⭐⭐",
    },
    {
        "user": "Роман Ш.",
        "text": "Рассылка отработала на 100%. Клиенты до сих пор приходят по тому сообщению. Долгосрочный эффект! 💰",
        "rating": "⭐⭐⭐⭐⭐",
    },
    {
        "user": "Юлия О.",
        "text": "Всё как обещали — реальный охват, реальная аудитория. Никаких ботов и накруток 👌",
        "rating": "⭐⭐⭐⭐⭐",
    },
    {
        "user": "Владислав Е.",
        "text": "За 8000 рублей получил результат, который в других местах стоит 30000+. Выгодно! 💸",
        "rating": "⭐⭐⭐⭐⭐",
    },
    {
        "user": "Кристина М.",
        "text": "Заказала рассылку для своего бьюти-блога. Пришли именно целевые подписчики! 💅",
        "rating": "⭐⭐⭐⭐⭐",
    },
    # ── 🚀 СКОРОСТЬ ──
    {
        "user": "Андрей Л.",
        "text": "Моментальная обработка заказа! Утром оплатил — к обеду уже пошли первые переходы 🔥",
        "rating": "⭐⭐⭐⭐⭐",
    },
    {
        "user": "Татьяна Ж.",
        "text": "Очень быстро работают. Менеджер на связи почти 24/7. Приятно работать с профессионалами! 🌟",
        "rating": "⭐⭐⭐⭐⭐",
    },
    {
        "user": "Михаил Р.",
        "text": "Скорость работы впечатляет. Заказал вечером — утром уже были результаты. Топ! ⚡",
        "rating": "⭐⭐⭐⭐⭐",
    },
    {
        "user": "Елена Б.",
        "text": "Оперативность на высшем уровне. Ответили за минуту, запустили за час. Браво! 👏",
        "rating": "⭐⭐⭐⭐⭐",
    },
    {
        "user": "Константин Д.",
        "text": "Не думал что будет так быстро. Заказ обработали мгновенно. Результат — 🔥",
        "rating": "⭐⭐⭐⭐⭐",
    },
    # ── 💼 БИЗНЕС ──
    {
        "user": "Антон (CryptoNews)",
        "text": "Продвигали крипто-канал. За одну рассылку +800 подписчиков. Окупилось в 10 раз! 📊",
        "rating": "⭐⭐⭐⭐⭐",
    },
    {
        "user": "Лариса (BeautyShop)",
        "text": "Рекламировали магазин косметики. Продажи выросли на 40% за неделю! Заказываем ещё 🎀",
        "rating": "⭐⭐⭐⭐⭐",
    },
    {
        "user": "Никита (GameDev)",
        "text": "Запускали бота-игру. За сутки 1000+ новых пользователей. Невероятный результат! 🎮",
        "rating": "⭐⭐⭐⭐⭐",
    },
    {
        "user": "Оксана (FitLife)",
        "text": "Продвигали фитнес-марафон. Набрали группу за 2 дня вместо запланированной недели! 💪",
        "rating": "⭐⭐⭐⭐⭐",
    },
    {
        "user": "Тимур (TechReview)",
        "text": "Канал с обзорами техники вырос с 2000 до 5000 подписчиков после двух рассылок. Магия! ✨",
        "rating": "⭐⭐⭐⭐⭐",
    },
    {
        "user": "Дарья (HandMade)",
        "text": "Рекламировала свои изделия ручной работы. Заказов стало так много, что не успеваю! 🧶",
        "rating": "⭐⭐⭐⭐⭐",
    },
    {
        "user": "Георгий (Invest)",
        "text": "Инвестиционный канал. Одна рассылка дала больше эффекта, чем месяц в Яндекс.Директ 📈",
        "rating": "⭐⭐⭐⭐⭐",
    },
    {
        "user": "Светлана (Cook)",
        "text": "Кулинарный блог вырос вдвое! Люди пишут, что нашли меня через рассылку. Супер! 🍰",
        "rating": "⭐⭐⭐⭐⭐",
    },
    {
        "user": "Руслан (AutoSale)",
        "text": "Продавал авто через канал — 3 машины продал за неделю после рассылки! 🚗",
        "rating": "⭐⭐⭐⭐⭐",
    },
    {
        "user": "Валерия (Travel)",
        "text": "Тревел-блог. Подписчики приходят каждый день даже спустя неделю после рассылки! ✈️",
        "rating": "⭐⭐⭐⭐⭐",
    },
    # ── 🏆 ПОВТОРНЫЕ КЛИЕНТЫ ──
    {
        "user": "Артур К.",
        "text": "5-й заказ! Каждый раз результат стабильный. Лучший канал продвижения для моего бизнеса 🏆",
        "rating": "⭐⭐⭐⭐⭐",
    },
    {
        "user": "Вероника С.",
        "text": "Заказываю каждый месяц. Мой канал растёт стабильно. Лучше инвестиции в рекламу не найти! 💎",
        "rating": "⭐⭐⭐⭐⭐",
    },
    {
        "user": "Илья П.",
        "text": "Уже 4-й раз заказываю. Ни разу не подвели. Работают как часы! ⏰",
        "rating": "⭐⭐⭐⭐⭐",
    },
    {
        "user": "Мария Н.",
        "text": "Постоянный клиент с января. Каждый круг рассылки приносит 200-400 подписчиков. Стабильно! 📊",
        "rating": "⭐⭐⭐⭐⭐",
    },
    {
        "user": "Олег Ч.",
        "text": "Третий заказ — и снова всё супер! Менеджер уже знает мои предпочтения. Приятный сервис! 😊",
        "rating": "⭐⭐⭐⭐⭐",
    },
    {
        "user": "Полина Г.",
        "text": "Рекомендовала подругам — все довольны! Теперь заказываем вместе со скидкой 🥰",
        "rating": "⭐⭐⭐⭐⭐",
    },
    # ── 🎯 РАЗНЫЕ НИШИ ──
    {
        "user": "Евгений (Юрист)",
        "text": "Юридические услуги сложно продвигать, но тут получил 30 заявок! Отличная аудитория 📋",
        "rating": "⭐⭐⭐⭐⭐",
    },
    {
        "user": "Диана (Психолог)",
        "text": "Набрала группу на вебинар за один день. Рассылка — это мощь! 🧠",
        "rating": "⭐⭐⭐⭐⭐",
    },
    {
        "user": "Степан (Музыкант)",
        "text": "Продвигал свой трек — 5000 прослушиваний за неделю! Раньше и мечтать не мог 🎵",
        "rating": "⭐⭐⭐⭐⭐",
    },
    {
        "user": "Алёна (Репетитор)",
        "text": "Нашла 15 новых учеников через одну рассылку. Окупилось за первый урок! 📖",
        "rating": "⭐⭐⭐⭐⭐",
    },
    {
        "user": "Борис (Фотограф)",
        "text": "Рекламировал фотоуслуги — забит на месяц вперёд! Рассылка сработала идеально 📸",
        "rating": "⭐⭐⭐⭐⭐",
    },
    {
        "user": "Карина (Астролог)",
        "text": "Продвигала канал с гороскопами. +1000 подписчиков за 3 дня! Это невероятно! 🌙",
        "rating": "⭐⭐⭐⭐⭐",
    },
    {
        "user": "Фёдор (Спорт)",
        "text": "Спортивный канал. После рассылки активность выросла в 5 раз. Все довольны! ⚽",
        "rating": "⭐⭐⭐⭐⭐",
    },
    {
        "user": "Яна (Флорист)",
        "text": "Заказы на букеты выросли вдвое. Лучшая реклама, которую я пробовала! 💐",
        "rating": "⭐⭐⭐⭐⭐",
    },
    {
        "user": "Виталий (IT)",
        "text": "Продвигал IT-курсы. 100 регистраций за 2 дня. ROI — 500%. Рекомендую! 💻",
        "rating": "⭐⭐⭐⭐⭐",
    },
    {
        "user": "Людмила (Мама-блогер)",
        "text": "Канал для мам вырос с 500 до 3000! Аудитория живая и активная 👶",
        "rating": "⭐⭐⭐⭐⭐",
    },
]

# ╔══════════════════════════════════════════╗
# ║         📋  СОСТОЯНИЯ FSM               ║
# ╚══════════════════════════════════════════╝


class OrderStates(StatesGroup):
    waiting_for_channel = State()
    waiting_for_message = State()
    waiting_for_confirm = State()


class ReviewStates(StatesGroup):
    waiting_for_text = State()
    waiting_for_rating = State()


# ╔══════════════════════════════════════════╗
# ║         🎨  КЛАВИАТУРЫ                  ║
# ╚══════════════════════════════════════════╝


def get_main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📢 О рассылке", callback_data="about")],
            [InlineKeyboardButton(text="💰 Цены и оплата", callback_data="prices")],
            [InlineKeyboardButton(text="🛒 Заказать рекламу", callback_data="order")],
            [InlineKeyboardButton(text="⭐ Отзывы клиентов", callback_data="reviews")],
            [InlineKeyboardButton(text="❓ Частые вопросы", callback_data="faq")],
            [
                InlineKeyboardButton(
                    text="📩 Связаться с нами", url="https://t.me/vladofix28"
                )
            ],
        ]
    )


def get_back_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Главное меню", callback_data="main_menu")]
        ]
    )


def get_order_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🚀 Заказать 1 круг — 8 000 ₽",
                    callback_data="order_start",
                )
            ],
            [
                InlineKeyboardButton(
                    text="📩 Написать менеджеру", url="https://t.me/vladofix28"
                )
            ],
            [InlineKeyboardButton(text="🔙 Главное меню", callback_data="main_menu")],
        ]
    )


def get_confirm_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Подтвердить заказ", callback_data="confirm_order"
                )
            ],
            [
                InlineKeyboardButton(
                    text="❌ Отменить", callback_data="cancel_order"
                )
            ],
        ]
    )


def get_cancel_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="❌ Отменить заказ", callback_data="cancel_order"
                )
            ]
        ]
    )


def get_rating_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="⭐ 1", callback_data="rate_1"),
                InlineKeyboardButton(text="⭐ 2", callback_data="rate_2"),
                InlineKeyboardButton(text="⭐ 3", callback_data="rate_3"),
            ],
            [
                InlineKeyboardButton(text="⭐ 4", callback_data="rate_4"),
                InlineKeyboardButton(text="⭐ 5", callback_data="rate_5"),
            ],
        ]
    )


def get_reviews_keyboard(page: int, total_pages: int) -> InlineKeyboardMarkup:
    nav = []
    if page > 0:
        nav.append(
            InlineKeyboardButton(text="⬅️ Назад", callback_data=f"reviews_page_{page - 1}")
        )
    if page < total_pages - 1:
        nav.append(
            InlineKeyboardButton(text="Вперёд ➡️", callback_data=f"reviews_page_{page + 1}")
        )

    buttons = []
    if nav:
        buttons.append(nav)
    buttons.append(
        [InlineKeyboardButton(text="📝 Оставить отзыв", callback_data="leave_review")]
    )
    buttons.append(
        [InlineKeyboardButton(text="🔙 Главное меню", callback_data="main_menu")]
    )
    return InlineKeyboardMarkup(inline_keyboard=buttons)


# ╔══════════════════════════════════════════╗
# ║         📝  ТЕКСТЫ СООБЩЕНИЙ            ║
# ╚══════════════════════════════════════════╝

WELCOME_TEXT = """
🚀 <b>Добро пожаловать в RocketAds!</b> 🚀

━━━━━━━━━━━━━━━━━━━━━━
📢 <b>Рассылка в Telegram-чатах</b>
🔥 <b>500 000+ активных пользователей</b>
━━━━━━━━━━━━━━━━━━━━━━

💎 Эффективная реклама в активных
Telegram-сообществах!

⚡ Быстрый запуск • 🎯 Живая аудитория
💰 Доступные цены • 📈 Реальный результат

━━━━━━━━━━━━━━━━━━━━━━
👇 <b>Выберите интересующий раздел:</b>
"""

ABOUT_TEXT = """
📢 <b>РАССЫЛКА В TELEGRAM-ЧАТАХ</b>
🔥 <b>500 000+ активных пользователей</b>

━━━━━━━━━━━━━━━━━━━━━━

🌟 <b>Почему это эффективно:</b>

✔️ Ваше предложение увидят <b>живые
и заинтересованные</b> пользователи

✔️ Рассылку можно <b>переслать, сохранить</b>
и перечитать в любой момент

✔️ Ваше сообщение <b>не теряется в ленте</b>
и продолжает работать со временем

━━━━━━━━━━━━━━━━━━━━━━

✅ <b>Честно и прозрачно:</b>

✔️ Не гарантируем подписки или переходы —
переходят только те, кому <b>действительно
интересно</b> предложение

✔️ Вы получаете <b>реальный показ</b>
реальной аудитории

━━━━━━━━━━━━━━━━━━━━━━

📈 <b>Итог:</b>

✔️ Рассылка — это <b>прямой доступ</b>
к стабильной аудитории

✔️ Аудитория <b>не уходит</b> и не исчезает

✔️ Ваше сообщение продолжает
работать <b>долгосрочно</b> 🚀

━━━━━━━━━━━━━━━━━━━━━━
"""

PRICES_TEXT = """
💰 <b>ЦЕНЫ И ОПЛАТА</b>

━━━━━━━━━━━━━━━━━━━━━━

📦 <b>1 круг рассылки</b>

💵 Стоимость: <b>8 000 ₽</b>
📍 Рассылка происходит <b>единоразово</b>
👥 Охват: <b>500 000+ пользователей</b>
⏱ Запуск: <b>в течение 24 часов</b>

━━━━━━━━━━━━━━━━━━━━━━

🏦 <b>Оплата по реквизитам:</b>

🏧 <b>T-Bank (Тинькофф)</b>
💳 <code>2200 7020 5404 4123</code>

━━━━━━━━━━━━━━━━━━━━━━

⚠️ <b>Важно!</b>
Мы гарантируем <b>размещение и охват</b>,
но не можем гарантировать точное
количество переходов по ссылке,
так как это зависит от контента
вашего предложения.

━━━━━━━━━━━━━━━━━━━━━━

💡 <i>Нажмите на номер карты,
чтобы скопировать!</i>
"""

FAQ_TEXT = f"""
❓ <b>ЧАСТО ЗАДАВАЕМЫЕ ВОПРОСЫ</b>

━━━━━━━━━━━━━━━━━━━━━━

🔹 <b>Что такое 1 круг рассылки?</b>
Это единоразовая рассылка вашего
сообщения по всем чатам нашей базы.

🔹 <b>Сколько человек увидят рекламу?</b>
Наша база — <b>500 000+</b> активных
пользователей в Telegram-чатах.

🔹 <b>Гарантируете ли вы переходы?</b>
Мы гарантируем <b>размещение и охват</b>.
Количество переходов зависит от
привлекательности вашего предложения.

🔹 <b>Как быстро начнётся рассылка?</b>
После подтверждения оплаты рассылка
запускается в течение <b>24 часов</b>. ⚡

🔹 <b>Можно ли выбрать тематику чатов?</b>
Напишите менеджеру {ADMIN_USERNAME}
для уточнения деталей. 📩

🔹 <b>Какой формат сообщения?</b>
Текст + ссылки. Можно добавить
эмодзи и форматирование. ✍️

🔹 <b>Есть ли гарантия возврата?</b>
Если рассылка не была проведена —
полный возврат средств. 🤝

🔹 <b>Можно ли заказать несколько кругов?</b>
Да! Напишите менеджеру для
получения скидки. 🎁

━━━━━━━━━━━━━━━━━━━━━━

💬 <b>Остались вопросы?</b>
Напишите: {ADMIN_USERNAME}
"""

ORDER_TEXT = f"""
🛒 <b>ЗАКАЗАТЬ РЕКЛАМУ</b>

━━━━━━━━━━━━━━━━━━━━━━

📦 <b>1 круг рассылки</b>

💵 Стоимость: <b>8 000 ₽</b>
👥 Охват: <b>500 000+ пользователей</b>
⏱ Запуск: <b>в течение 24 часов</b>

━━━━━━━━━━━━━━━━━━━━━━

🏧 <b>Реквизиты для оплаты:</b>
🏦 T-Bank (Тинькофф)
💳 <code>2200 7020 5404 4123</code>

━━━━━━━━━━━━━━━━━━━━━━

📋 <b>Как заказать:</b>

1️⃣ Нажмите <b>«Заказать»</b> ниже
2️⃣ Укажите ссылку на канал / бот
3️⃣ Отправьте текст для рассылки
4️⃣ Оплатите и отправьте скрин
   менеджеру {ADMIN_USERNAME}
5️⃣ Получите результат! 🎯

━━━━━━━━━━━━━━━━━━━━━━
"""


# ╔══════════════════════════════════════════╗
# ║         🔧  ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ     ║
# ╚══════════════════════════════════════════╝

REVIEWS_PER_PAGE = 5


def calc_avg_rating() -> float:
    if not reviews_db:
        return 0.0
    total = sum(r["rating"].count("⭐") for r in reviews_db)
    return total / len(reviews_db)


def build_reviews_page(page: int) -> str:
    total_pages = max(1, (len(reviews_db) - 1) // REVIEWS_PER_PAGE + 1)
    start = page * REVIEWS_PER_PAGE
    end = start + REVIEWS_PER_PAGE
    avg = calc_avg_rating()

    text = f"""
⭐ <b>ОТЗЫВЫ НАШИХ КЛИЕНТОВ</b>

━━━━━━━━━━━━━━━━━━━━━━
📊 Всего отзывов: <b>{len(reviews_db)}</b>
🌟 Средний рейтинг: <b>{avg:.1f} / 5.0</b>
📄 Страница: <b>{page + 1} / {total_pages}</b>
━━━━━━━━━━━━━━━━━━━━━━

"""
    for r in reviews_db[start:end]:
        text += (
            f"💬 <b>{r['user']}</b>\n"
            f"{r['rating']}\n"
            f"<i>«{r['text']}»</i>\n\n"
        )

    text += "━━━━━━━━━━━━━━━━━━━━━━"
    return text


# ╔══════════════════════════════════════════╗
# ║         🚀  ОБРАБОТЧИКИ КОМАНД          ║
# ╚══════════════════════════════════════════╝


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("🚀")
    await asyncio.sleep(0.3)
    await message.answer(text=WELCOME_TEXT, reply_markup=get_main_menu())


@router.message(Command("help"))
async def cmd_help(message: Message):
    text = f"""
🆘 <b>ПОМОЩЬ</b>

━━━━━━━━━━━━━━━━━━━━━━

📌 <b>Доступные команды:</b>

/start — Главное меню
/help — Помощь
/reviews — Отзывы клиентов
/order — Заказать рекламу

━━━━━━━━━━━━━━━━━━━━━━

📩 Поддержка: {ADMIN_USERNAME}
"""
    await message.answer(text=text, reply_markup=get_back_menu())


@router.message(Command("reviews"))
async def cmd_reviews(message: Message):
    page = 0
    total_pages = max(1, (len(reviews_db) - 1) // REVIEWS_PER_PAGE + 1)
    text = build_reviews_page(page)
    await message.answer(text=text, reply_markup=get_reviews_keyboard(page, total_pages))


@router.message(Command("order"))
async def cmd_order(message: Message):
    await message.answer(text=ORDER_TEXT, reply_markup=get_order_menu())


# ╔══════════════════════════════════════════╗
# ║         📋  ГЛАВНОЕ МЕНЮ                ║
# ╚══════════════════════════════════════════╝


@router.callback_query(F.data == "main_menu")
async def cb_main_menu(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text(
        text=WELCOME_TEXT, reply_markup=get_main_menu()
    )
    await callback.answer()


# ╔══════════════════════════════════════════╗
# ║         📢  О РАССЫЛКЕ                  ║
# ╚══════════════════════════════════════════╝


@router.callback_query(F.data == "about")
async def cb_about(callback: CallbackQuery):
    await callback.message.edit_text(text=ABOUT_TEXT, reply_markup=get_back_menu())
    await callback.answer("📢 Информация о рассылке")


# ╔══════════════════════════════════════════╗
# ║         💰  ЦЕНЫ И ОПЛАТА               ║
# ╚══════════════════════════════════════════╝


@router.callback_query(F.data == "prices")
async def cb_prices(callback: CallbackQuery):
    await callback.message.edit_text(text=PRICES_TEXT, reply_markup=get_back_menu())
    await callback.answer("💰 Цены и оплата")


# ╔══════════════════════════════════════════╗
# ║         ❓  FAQ                          ║
# ╚══════════════════════════════════════════╝


@router.callback_query(F.data == "faq")
async def cb_faq(callback: CallbackQuery):
    await callback.message.edit_text(text=FAQ_TEXT, reply_markup=get_back_menu())
    await callback.answer("❓ Частые вопросы")


# ╔══════════════════════════════════════════╗
# ║         🛒  ЗАКАЗ РЕКЛАМЫ               ║
# ╚══════════════════════════════════════════╝


@router.callback_query(F.data == "order")
async def cb_order(callback: CallbackQuery):
    await callback.message.edit_text(text=ORDER_TEXT, reply_markup=get_order_menu())
    await callback.answer("🛒 Заказ рекламы")


@router.callback_query(F.data == "order_start")
async def cb_order_start(callback: CallbackQuery, state: FSMContext):
    await state.set_state(OrderStates.waiting_for_channel)
    text = """
📝 <b>ОФОРМЛЕНИЕ ЗАКАЗА</b>

━━━━━━━━━━━━━━━━━━━━━━

📌 <b>Шаг 1 из 2</b>

✍️ Отправьте <b>ссылку на ваш канал,
бот или сайт</b>, который нужно
рекламировать.

📎 Пример:
<code>@yourchannel</code>
<code>https://t.me/yourchannel</code>

━━━━━━━━━━━━━━━━━━━━━━
"""
    await callback.message.edit_text(text=text, reply_markup=get_cancel_menu())
    await callback.answer()


@router.message(OrderStates.waiting_for_channel)
async def fsm_channel(message: Message, state: FSMContext):
    await state.update_data(channel=message.text)
    await state.set_state(OrderStates.waiting_for_message)
    text = f"""
📝 <b>ОФОРМЛЕНИЕ ЗАКАЗА</b>

━━━━━━━━━━━━━━━━━━━━━━

📌 <b>Шаг 2 из 2</b>

✅ Канал: <b>{message.text}</b>

✍️ Теперь отправьте <b>текст рекламного
сообщения</b>, которое будет разослано
по всем чатам.

💡 Используйте эмодзи и ссылки
для лучшего эффекта!

━━━━━━━━━━━━━━━━━━━━━━
"""
    await message.answer(text=text, reply_markup=get_cancel_menu())


@router.message(OrderStates.waiting_for_message)
async def fsm_ad_text(message: Message, state: FSMContext):
    data = await state.get_data()
    await state.update_data(ad_text=message.text)
    await state.set_state(OrderStates.waiting_for_confirm)
    text = f"""
📋 <b>ПОДТВЕРЖДЕНИЕ ЗАКАЗА</b>

━━━━━━━━━━━━━━━━━━━━━━

🔍 <b>Проверьте данные:</b>

📎 <b>Канал:</b> {data['channel']}

📝 <b>Текст рассылки:</b>
<i>{message.text}</i>

━━━━━━━━━━━━━━━━━━━━━━

💵 <b>Стоимость:</b> 8 000 ₽
👥 <b>Охват:</b> 500 000+ пользователей
⏱ <b>Запуск:</b> в течение 24 часов

━━━━━━━━━━━━━━━━━━━━━━

✅ Если всё верно — <b>подтвердите заказ!</b>
"""
    await message.answer(text=text, reply_markup=get_confirm_menu())


@router.callback_query(F.data == "confirm_order")
async def cb_confirm(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    user = callback.from_user
    await state.clear()

    order_id = len(orders_db) + 1001
    now = datetime.now().strftime("%d.%m.%Y %H:%M")
    orders_db[order_id] = {
        "user_id": user.id,
        "username": user.username,
        "channel": data.get("channel", "—"),
        "ad_text": data.get("ad_text", "—"),
        "date": now,
        "status": "⏳ Ожидает оплаты",
    }

    text = f"""
🎉 <b>ЗАКАЗ УСПЕШНО ОФОРМЛЕН!</b> 🎉

━━━━━━━━━━━━━━━━━━━━━━

📦 Заказ: <b>№{order_id}</b>
📅 Дата: <b>{now}</b>
📍 Статус: <b>⏳ Ожидает оплаты</b>

━━━━━━━━━━━━━━━━━━━━━━

🏧 <b>Оплатите по реквизитам:</b>

🏦 <b>T-Bank (Тинькофф)</b>
💳 <code>2200 7020 5404 4123</code>
💵 Сумма: <b>8 000 ₽</b>

━━━━━━━━━━━━━━━━━━━━━━

📸 После оплаты отправьте
<b>скриншот чека</b> менеджеру:
{ADMIN_USERNAME}

⚡ Рассылка будет запущена
в течение <b>24 часов</b> после
подтверждения оплаты!

━━━━━━━━━━━━━━━━━━━━━━

💖 <b>Спасибо за доверие!</b> 🚀
"""

    buttons = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📸 Отправить скрин оплаты",
                    url="https://t.me/vladofix28",
                )
            ],
            [InlineKeyboardButton(text="🔙 Главное меню", callback_data="main_menu")],
        ]
    )

    await callback.message.edit_text(text=text, reply_markup=buttons)
    await callback.answer("✅ Заказ оформлен!")

    # ── уведомление админу ──
    try:
        admin_text = f"""
🔔 <b>НОВЫЙ ЗАКАЗ!</b> 🔔

━━━━━━━━━━━━━━━━━━━━
📦 Заказ: <b>№{order_id}</b>
👤 Клиент: @{user.username or 'нет_username'}
🆔 ID: <code>{user.id}</code>
📎 Канал: <b>{data.get('channel', '—')}</b>
📝 Текст: <i>{data.get('ad_text', '—')}</i>
📅 Дата: <b>{now}</b>
━━━━━━━━━━━━━━━━━━━━
"""
        await bot.send_message(chat_id=ADMIN_ID, text=admin_text)
    except Exception:
        pass


@router.callback_query(F.data == "cancel_order")
async def cb_cancel(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    text = """
❌ <b>Заказ отменён</b>

Вы можете оформить новый заказ
в любое время! 😊

━━━━━━━━━━━━━━━━━━━━━━
"""
    await callback.message.edit_text(text=text, reply_markup=get_back_menu())
    await callback.answer("❌ Заказ отменён")


# ╔══════════════════════════════════════════╗
# ║         ⭐  ОТЗЫВЫ                      ║
# ╚══════════════════════════════════════════╝


@router.callback_query(F.data == "reviews")
async def cb_reviews(callback: CallbackQuery):
    page = 0
    total_pages = max(1, (len(reviews_db) - 1) // REVIEWS_PER_PAGE + 1)
    text = build_reviews_page(page)
    await callback.message.edit_text(
        text=text, reply_markup=get_reviews_keyboard(page, total_pages)
    )
    await callback.answer("⭐ Отзывы клиентов")


@router.callback_query(F.data.startswith("reviews_page_"))
async def cb_reviews_page(callback: CallbackQuery):
    page = int(callback.data.split("_")[2])
    total_pages = max(1, (len(reviews_db) - 1) // REVIEWS_PER_PAGE + 1)
    if page < 0 or page >= total_pages:
        await callback.answer("📄 Страница не найдена")
        return
    text = build_reviews_page(page)
    await callback.message.edit_text(
        text=text, reply_markup=get_reviews_keyboard(page, total_pages)
    )
    await callback.answer()


@router.callback_query(F.data == "leave_review")
async def cb_leave_review(callback: CallbackQuery, state: FSMContext):
    await state.set_state(ReviewStates.waiting_for_text)
    text = """
📝 <b>ОСТАВИТЬ ОТЗЫВ</b>

━━━━━━━━━━━━━━━━━━━━━━

✍️ Напишите ваш отзыв о нашем
сервисе рассылки.

💬 Расскажите о вашем опыте!

━━━━━━━━━━━━━━━━━━━━━━
"""
    cancel = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="main_menu")]
        ]
    )
    await callback.message.edit_text(text=text, reply_markup=cancel)
    await callback.answer()


@router.message(ReviewStates.waiting_for_text)
async def fsm_review_text(message: Message, state: FSMContext):
    await state.update_data(review_text=message.text)
    await state.set_state(ReviewStates.waiting_for_rating)
    text = f"""
⭐ <b>ОЦЕНИТЕ НАШ СЕРВИС</b>

━━━━━━━━━━━━━━━━━━━━━━

📝 Ваш отзыв:
<i>«{message.text}»</i>

👇 Теперь выберите оценку:

━━━━━━━━━━━━━━━━━━━━━━
"""
    await message.answer(text=text, reply_markup=get_rating_menu())


@router.callback_query(F.data.startswith("rate_"))
async def cb_rate(callback: CallbackQuery, state: FSMContext):
    num = int(callback.data.split("_")[1])
    stars = "⭐" * num
    data = await state.get_data()
    await state.clear()

    name = callback.from_user.first_name or "Пользователь"
    reviews_db.append(
        {"user": name, "text": data.get("review_text", ""), "rating": stars}
    )

    text = f"""
🎉 <b>СПАСИБО ЗА ОТЗЫВ!</b> 🎉

━━━━━━━━━━━━━━━━━━━━━━

👤 <b>{name}</b>
{stars}
💬 <i>«{data.get('review_text', '')}»</i>

━━━━━━━━━━━━━━━━━━━━━━

✅ Ваш отзыв успешно опубликован!
💖 Мы ценим ваше мнение!

━━━━━━━━━━━━━━━━━━━━━━
"""
    await callback.message.edit_text(text=text, reply_markup=get_back_menu())
    await callback.answer("✅ Отзыв опубликован!")


# ╔══════════════════════════════════════════╗
# ║      🛡️  ОБРАБОТКА ПРОЧИХ СООБЩЕНИЙ     ║
# ╚══════════════════════════════════════════╝


@router.message()
async def fallback(message: Message, state: FSMContext):
    current = await state.get_state()
    if current is not None:
        return  # FSM обработает
    text = f"""
🤔 <b>Не понимаю эту команду</b>

Воспользуйтесь меню ниже или
напишите /start для перезапуска.

📩 Поддержка: {ADMIN_USERNAME}
"""
    await message.answer(text=text, reply_markup=get_main_menu())


# ╔══════════════════════════════════════════╗
# ║         🚀  ЗАПУСК                      ║
# ╚══════════════════════════════════════════╝


async def set_commands():
    commands = [
        BotCommand(command="start", description="🚀 Главное меню"),
        BotCommand(command="order", description="🛒 Заказать рекламу"),
        BotCommand(command="reviews", description="⭐ Отзывы клиентов"),
        BotCommand(command="help", description="🆘 Помощь"),
    ]
    await bot.set_my_commands(commands)


async def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    await set_commands()
    print()
    print("╔══════════════════════════════════════╗")
    print("║    🚀  RocketAds Bot запущен!        ║")
    print("║    📢  Сервис рассылки активен       ║")
    print("║    ⭐  Отзывов загружено:", f"{len(reviews_db):>3}", "       ║")
    print("╚══════════════════════════════════════╝")
    print()
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
