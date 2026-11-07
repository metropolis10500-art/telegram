import asyncio
import logging
import random
import sqlite3
import time
from datetime import datetime, timedelta
from urllib.parse import urlencode
import aiohttp

from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton
)

# =====================================================================
# ⚙️ НАСТРОЙКИ БОТА (ЗАПОЛНИТЕ СВОИ ДАННЫЕ)
# =====================================================================
BOT_TOKEN = "9280804384:AAEYyYr2JowksZMfvmXQX9EY2eDm4WpVFug"
ADMIN_ID = 5494544187  # Ваш Telegram ID (числом без кавычек)

YOOMONEY_WALLET = "4100118935779591"  # Номер вашего кошелька ЮMoney
# Токен ЮMoney API для автооплаты (если оставить пустым "", проверка идет через Админа в 1 клик)
YOOMONEY_TOKEN = "8BE176DEFDE0ED619164EB32845C863D58EDF5A49E9B0416A90FCEE9D298D24D"

# Настройки экономики и агрессивного маркетинга
WELCOME_BONUS = 50.0       # Приветственный бонус новым игрокам (+50 ₽ сразу на баланс!)
MIN_WITHDRAW = 100.0       # Минимальный порог вывода
REF_QUEST_TARGET = 10      # Сколько друзей нужно привести для супер-выплаты
REF_QUEST_REWARD = 5000.0  # Награда за 10 друзей (5 000 ₽)

# Тарифы VIP: {уровень: (Название, Старая цена, Новая Цена, Множитель оплаты, Реферальный %)}
VIP_TIERS = {
    0: ("🌱 Базовый (Стажер)", 0, 0, 1.0, 10),
    1: ("⚡ PRO-Исполнитель", 790, 390, 1.5, 30),
    2: ("🔥 Бизнес-Партнер", 1990, 990, 2.0, 40),
    3: ("👑 VIP-Агентство", 4990, 2490, 2.5, 50)
}

# Память для автоудаления предыдущих сообщений {user_id: [msg_id1, msg_id2, ...]}
active_screens = {}
# Анти-спам таймер для кнопки проверки платежа {user_id: timestamp}
payment_cooldowns = {}

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# =====================================================================
# 🧹 СИСТЕМА «ЧИСТЫЙ ЧАТ» (АВТОУДАЛЕНИЕ СТАРЫХ СООБЩЕНИЙ)
# =====================================================================
async def clear_user_screen(chat_id: int):
    """Удаляет все предыдущие сообщения бота у пользователя"""
    msg_ids = active_screens.get(chat_id, [])
    for mid in msg_ids:
        try:
            await bot.delete_message(chat_id=chat_id, message_id=mid)
        except Exception:
            pass
    active_screens[chat_id] = []

async def delete_user_msg(message: types.Message):
    """Удаляет сообщение, написанное самим пользователем"""
    try:
        await message.delete()
    except Exception:
        pass

async def show_screen(chat_id: int, text: str, reply_markup=None, sticker_emoji: str = None):
    """Очищает старый экран, отправляет анимированный стикер-эмодзи и новое окно"""
    await clear_user_screen(chat_id)
    new_ids = []

    if sticker_emoji:
        try:
            s_msg = await bot.send_message(chat_id, sticker_emoji)
            new_ids.append(s_msg.message_id)
        except Exception:
            pass

    msg = await bot.send_message(
        chat_id,
        text,
        reply_markup=reply_markup,
        parse_mode="HTML",
        disable_web_page_preview=True
    )
    new_ids.append(msg.message_id)
    active_screens[chat_id] = new_ids
    return msg

# =====================================================================
# 🗄 БАЗА ДАННЫХ (SQLite)
# =====================================================================
def init_db():
    conn = sqlite3.connect("profithub.db")
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            balance REAL DEFAULT 0,
            vip_level INTEGER DEFAULT 0,
            referrer_id INTEGER DEFAULT 0,
            referrals_count INTEGER DEFAULT 0,
            completed_tasks INTEGER DEFAULT 0,
            bonus_5k_claimed INTEGER DEFAULT 0
        )
    """)
    try:
        cur.execute("ALTER TABLE users ADD COLUMN bonus_5k_claimed INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass

    cur.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT,
            description TEXT,
            url TEXT,
            channel_id TEXT,
            base_reward REAL,
            task_type TEXT DEFAULT 'sub'
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS completed (
            user_id INTEGER,
            task_id INTEGER,
            PRIMARY KEY (user_id, task_id)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS withdrawals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            amount REAL,
            bank TEXT,
            requisites TEXT,
            status TEXT DEFAULT 'pending'
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS processed_payments (
            operation_id TEXT PRIMARY KEY,
            user_id INTEGER,
            amount REAL
        )
    """)

    conn.commit()
    conn.close()

def get_user(user_id):
    conn = sqlite3.connect("profithub.db")
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    conn.close()
    return row

# =====================================================================
# ⌨️ КЛАВИАТУРЫ И НАВИГАЦИЯ (С КНОПКАМИ НАЗАД И ОТМЕНА)
# =====================================================================
def main_reply_kb():
    kb = [
        [KeyboardButton(text="📋 Быстрые задания"), KeyboardButton(text="💰 Контракты (до 1500₽)")],
        [KeyboardButton(text="🎁 Акция: 5 000 ₽ за 10 друзей")],
        [KeyboardButton(text="🚀 Увеличить доход (VIP x2.5)"), KeyboardButton(text="👤 Личный кабинет")],
        [KeyboardButton(text="🏦 Вывод средств"), KeyboardButton(text="✅ Живые выплаты и Гарантии")]
    ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

def main_inline_kb():
    buttons = [
        [InlineKeyboardButton(text="📋 Быстрые задания", callback_data="nav_sub"),
         InlineKeyboardButton(text="💰 Контракты (1500₽)", callback_data="nav_cpa_0")],
        [InlineKeyboardButton(text="🎁 Забрать 5 000 ₽ за 10 друзей", callback_data="nav_quest")],
        [InlineKeyboardButton(text="🚀 VIP-Статусы (Доход x2.5)", callback_data="open_vip_shop")],
        [InlineKeyboardButton(text="👤 Кабинет", callback_data="nav_cab"),
         InlineKeyboardButton(text="🏦 Вывод денег", callback_data="nav_withdraw")],
        [InlineKeyboardButton(text="✅ Живая лента выплат (Онлайн)", callback_data="nav_payouts")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def back_to_menu_kb(include_vip=True):
    buttons = []
    if include_vip:
        buttons.append([InlineKeyboardButton(text="🔥 Увеличить доход в 2.5 раза (VIP)", callback_data="open_vip_shop")])
    buttons.append([InlineKeyboardButton(text="🔙 Назад в главное меню", callback_data="nav_main")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def vip_shop_kb(user_id):
    buttons = []
    for lvl in (1, 2, 3):
        name, old_price, price, mult, _ = VIP_TIERS[lvl]
        params = {
            "receiver": YOOMONEY_WALLET,
            "quickpay-form": "button",
            "paymentType": "AC",
            "sum": price,
            "label": f"vip_{user_id}_{lvl}"
        }
        pay_url = f"https://yoomoney.ru/quickpay/confirm.xml?{urlencode(params)}"
        buttons.append([
            InlineKeyboardButton(
                text=f"💳 {name} (x{mult}) — {price}₽ (вместо {old_price}₽)",
                url=pay_url
            )
        ])
    buttons.append([InlineKeyboardButton(text="🔄 Я оплатил! Активировать статус", callback_data="check_vip_pay")])
    buttons.append([InlineKeyboardButton(text="🔙 Назад в главное меню", callback_data="nav_main")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def banks_kb():
    buttons = [
        [InlineKeyboardButton(text="🟢 Сбербанк (СБП / Карта)", callback_data="bank_Сбербанк"),
         InlineKeyboardButton(text="🟡 Т-Банк (Тинькофф)", callback_data="bank_Т-Банк")],
        [InlineKeyboardButton(text="🔴 Альфа-Банк", callback_data="bank_Альфа-Банк"),
         InlineKeyboardButton(text="🔵 ВТБ", callback_data="bank_ВТБ")],
        [InlineKeyboardButton(text="🟣 ЮMoney", callback_data="bank_ЮMoney"),
         InlineKeyboardButton(text="📱 СБП (Любой банк РФ)", callback_data="bank_СБП")],
        [InlineKeyboardButton(text="🔙 Назад (Изменить сумму)", callback_data="nav_withdraw"),
         InlineKeyboardButton(text="❌ Отмена", callback_data="nav_main")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def admin_menu_kb():
    buttons = [
        [InlineKeyboardButton(text="📊 Статистика проекта", callback_data="adm_stats")],
        [InlineKeyboardButton(text="➕ Подписка (Канал)", callback_data="addtask_sub"),
         InlineKeyboardButton(text="➕ CPA-Контракт", callback_data="addtask_cpa")],
        [InlineKeyboardButton(text="🗑 Удалить задания", callback_data="adm_del_tasks")],
        [InlineKeyboardButton(text="📨 Сделать рассылку", callback_data="adm_broadcast"),
         InlineKeyboardButton(text="💰 Изменить баланс", callback_data="adm_balance")],
        [InlineKeyboardButton(text="🔙 Выйти в меню бота", callback_data="nav_main")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def admin_cancel_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад в Админ-панель", callback_data="adm_back"),
         InlineKeyboardButton(text="❌ Отмена", callback_data="nav_main")]
    ])

# =====================================================================
# 🔄 МАШИНА СОСТОЯНИЙ (FSM)
# =====================================================================
class WithdrawFSM(StatesGroup):
    amount = State()
    bank = State()
    requisites = State()

class CpaProofFSM(StatesGroup):
    waiting_for_proof = State()

class AdminAddTaskFSM(StatesGroup):
    task_type = State()
    title = State()
    description = State()
    url = State()
    channel_id = State()
    base_reward = State()

class AdminBroadcastFSM(StatesGroup):
    waiting_for_message = State()

class AdminBalanceFSM(StatesGroup):
    waiting_for_userid = State()
    waiting_for_amount = State()

# =====================================================================
# 🏠 ГЛАВНЫЙ ЭКРАН, СТАРТ И БОНУС 50 РУБЛЕЙ
# =====================================================================
def generate_live_ticker() -> str:
    """Генерирует строчку последней живой выплаты для главного экрана"""
    samples = [
        ("@maksim_k***", "🟢 Сбербанк", "1 450 ₽"),
        ("@elena_v***", "🟡 Т-Банк", "5 000 ₽ (Бонус за 10 друзей)"),
        ("@dmitry_9***", "🔴 Альфа-Банк", "890 ₽"),
        ("@artem_s***", "🟢 Сбербанк", "2 500 ₽"),
        ("@katya_m***", "🟣 ЮMoney", "420 ₽"),
        ("@nikita_p***", "🟡 Т-Банк", "5 000 ₽ (Бонус за 10 друзей)"),
        ("@igor_b***", "🔵 ВТБ", "1 200 ₽")
    ]
    u, b, a = random.choice(samples)
    return f"🟢 <i>Только что выплачено: <b>{a}</b> ➔ {b} ({u})</i>"

async def render_main_menu(chat_id: int, user_id: int, is_new: bool = False, first_load: bool = False):
    user = get_user(user_id)
    vip_name, _, _, mult, _ = VIP_TIERS[user[3]]
    ticker = generate_live_ticker()

    welcome_gift_text = (
        f"🎉🎁 <b>ВАМ НАЧИСЛЕН БОНУС НОВИЧКА: +{WELCOME_BONUS:.0f} ₽!</b>\n"
        f"<i>Деньги уже на вашем счету! До первого вывода на карту осталось заработать всего {MIN_WITHDRAW - WELCOME_BONUS:.0f} ₽!</i>\n\n"
        if is_new else ""
    )

    text = (
        f"💎 <b>PROFIT-HUB — ОФИЦИАЛЬНАЯ ПЛАТФОРМА ЗАРАБОТКА</b> ✨\n"
        f"{ticker}\n\n"
        f"{welcome_gift_text}"
        f"🔥 <b>Зарабатывайте реальные деньги прямо в Telegram:</b>\n"
        f"Подписывайтесь на спонсоров, выполняйте денежные контракты от банков РФ и получайте <b>5 000 ₽</b> за приглашение друзей!\n\n"
        f"┏━━━━━━━━━━━━━━━━━━━━━┓\n"
        f"┃ 👤 <b>Статус:</b> {vip_name}\n"
        f"┃ 📈 <b>Множитель оплаты:</b> <code>x{mult}</code>\n"
        f"┃ 💰 <b>Ваш баланс:</b> <code>{user[2]:.2f} ₽</code>\n"
        f"┗━━━━━━━━━━━━━━━━━━━━━┛\n\n"
        f"👇 <b>Выберите раздел для заработка:</b>"
    )

    if first_load:
        # Устанавливаем нижнюю клавиатуру один раз при старте
        temp = await bot.send_message(chat_id, "⚡️ Загрузка рабочего кабинета...", reply_markup=main_reply_kb())
        try:
            await bot.delete_message(chat_id, temp.message_id)
        except Exception:
            pass

    sticker = "🎁" if is_new else "💎"
    await show_screen(chat_id, text, reply_markup=main_inline_kb(), sticker_emoji=sticker)

@dp.message(CommandStart())
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    await delete_user_msg(message)
    user_id = message.from_user.id
    username = message.from_user.username or "User"
    user = get_user(user_id)
    is_new = False

    if not user:
        is_new = True
        ref_id = 0
        args = message.text.split()
        if len(args) > 1 and args[1].isdigit():
            possible_ref = int(args[1])
            if possible_ref != user_id and get_user(possible_ref):
                ref_id = possible_ref

        conn = sqlite3.connect("profithub.db")
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO users (user_id, username, balance, referrer_id) VALUES (?, ?, ?, ?)",
            (user_id, username, WELCOME_BONUS, ref_id)
        )

        quest_completed = False
        new_ref_count = 0
        if ref_id:
            cur.execute("UPDATE users SET referrals_count = referrals_count + 1 WHERE user_id = ?", (ref_id,))
            cur.execute("SELECT referrals_count, bonus_5k_claimed FROM users WHERE user_id = ?", (ref_id,))
            ref_data = cur.fetchone()
            if ref_data:
                new_ref_count, bonus_claimed = ref_data
                if new_ref_count >= REF_QUEST_TARGET and bonus_claimed == 0:
                    cur.execute(
                        "UPDATE users SET balance = balance + ?, bonus_5k_claimed = 1 WHERE user_id = ?",
                        (REF_QUEST_REWARD, ref_id)
                    )
                    quest_completed = True

        conn.commit()
        conn.close()

        if ref_id:
            try:
                if quest_completed:
                    await bot.send_message(
                        ref_id,
                        f"🎉💸 <b>ПОЗДРАВЛЯЕМ! ВЫ ВЫПОЛНИЛИ КВЕСТ «10 ДРУЗЕЙ»!</b>\n\n"
                        f"По вашей ссылке зашел 10-й друг (@{username}).\n"
                        f"💰 На ваш баланс зачислено: <b>+{REF_QUEST_REWARD:.0f} ₽</b>!\n"
                        f"Перейдите в раздел «🏦 Вывод средств» и заберите деньги на карту!",
                        parse_mode="HTML"
                    )
                else:
                    left = max(0, REF_QUEST_TARGET - new_ref_count)
                    await bot.send_message(
                        ref_id,
                        f"🥳 <b>Новый реферал: @{username}!</b>\n"
                        f"🎁 До выплаты <b>5 000 ₽</b> осталось пригласить: <b>{left} чел.</b> ({new_ref_count}/{REF_QUEST_TARGET})\n"
                        f"💎 Плюс вы получаете до <b>50%</b> с каждой его покупки VIP!",
                        parse_mode="HTML"
                    )
            except Exception:
                pass

    await render_main_menu(message.chat.id, user_id, is_new=is_new, first_load=True)

@dp.callback_query(F.data == "nav_main")
async def cb_nav_main(call: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await render_main_menu(call.message.chat.id, call.from_user.id)
    await call.answer()

@dp.message(F.text == "❌ Отмена")
async def reply_cancel(message: types.Message, state: FSMContext):
    await state.clear()
    await delete_user_msg(message)
    await render_main_menu(message.chat.id, message.from_user.id)

# =====================================================================
# 📋 РАЗДЕЛ 1: БЫСТРЫЕ ЗАДАНИЯ (В ОДНОМ ОКНЕ)
# =====================================================================
async def render_sub_tasks(chat_id: int, user_id: int):
    user = get_user(user_id)
    mult = VIP_TIERS[user[3]][3]

    conn = sqlite3.connect("profithub.db")
    cur = conn.cursor()
    cur.execute("""
        SELECT id, title, url, base_reward FROM tasks 
        WHERE task_type = 'sub' AND id NOT IN (SELECT task_id FROM completed WHERE user_id = ?)
    """, (user[0],))
    tasks = cur.fetchall()
    conn.close()

    if not tasks:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💰 Перейти к Контрактам (до 1500₽)", callback_data="nav_cpa_0")],
            [InlineKeyboardButton(text="🎁 Забрать 5 000 ₽ за 10 друзей", callback_data="nav_quest")],
            [InlineKeyboardButton(text="🚀 Увеличить доход в 2.5 раза (VIP)", callback_data="open_vip_shop")],
            [InlineKeyboardButton(text="🔙 Назад в главное меню", callback_data="nav_main")]
        ])
        await show_screen(
            chat_id,
            "🎉✨ <b>Все быстрые задания на сегодня выполнены!</b>\n\n"
            "💡 <b>Как заработать прямо сейчас:</b>\n"
            "• Выполняйте дорогие заказы в разделе <b>«💰 Контракты (до 1500₽)»</b>.\n"
            "• Пригласите 10 друзей и получите <b>5 000 ₽</b> сразу на баланс!\n"
            "• Подключите <b>VIP-Статус</b>, чтобы получать в 2.5 раза больше денег!",
            reply_markup=kb,
            sticker_emoji="🎉"
        )
        return

    task_id, title, url, base_reward = tasks[0]
    user_reward = round(base_reward * mult, 2)
    max_vip_reward = round(base_reward * VIP_TIERS[3][3], 2)

    buttons = [
        [InlineKeyboardButton(text="🔗 1. Перейти и подписаться на спонсора", url=url)],
        [InlineKeyboardButton(text=f"✅ 2. Проверить и забрать +{user_reward} ₽", callback_data=f"checksub_{task_id}")]
    ]
    if user[3] < 3:
        buttons.append([InlineKeyboardButton(text=f"👑 Получать {max_vip_reward} ₽ за клик (Купить VIP)", callback_data="open_vip_shop")])
    buttons.append([InlineKeyboardButton(text="🔙 Назад в главное меню", callback_data="nav_main")])

    vip_hint = (
        f"\n\n⚠️ <b>Упущенная выгода:</b> Сейчас ваша выплата <code>{user_reward} ₽</code>, "
        f"а со статусом <b>👑 VIP-Агентство</b> вы бы получили <b>{max_vip_reward} ₽</b> за этот же клик!"
        if user[3] < 3 else ""
    )

    text = (
        f"📋⚡ <b>БЫСТРОЕ ЗАДАНИЕ #{task_id}</b> <i>(Доступно в очереди: {len(tasks)})</i>\n\n"
        f"📢 <b>Канал спонсора:</b> {title}\n"
        f"📌 <b>Что нужно сделать:</b> Нажмите кнопку «Перейти и подписаться», затем вернитесь сюда и нажмите «Проверить».\n\n"
        f"💵 <b>Ваша награда:</b> <code>+{user_reward:.2f} ₽</code>{vip_hint}"
    )
    await show_screen(chat_id, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), sticker_emoji="⚡")

@dp.message(F.text == "📋 Быстрые задания")
async def msg_sub_tasks(message: types.Message, state: FSMContext):
    await state.clear()
    await delete_user_msg(message)
    await render_sub_tasks(message.chat.id, message.from_user.id)

@dp.callback_query(F.data == "nav_sub")
async def cb_sub_tasks(call: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await render_sub_tasks(call.message.chat.id, call.from_user.id)
    await call.answer()

@dp.callback_query(F.data.startswith("checksub_"))
async def check_sub_task(call: types.CallbackQuery):
    task_id = int(call.data.split("_")[1])
    user = get_user(call.from_user.id)
    mult = VIP_TIERS[user[3]][3]

    conn = sqlite3.connect("profithub.db")
    cur = conn.cursor()
    cur.execute("SELECT channel_id, base_reward FROM tasks WHERE id = ?", (task_id,))
    task = cur.fetchone()

    if not task:
        await call.answer("Задание уже завершено.", show_alert=True)
        conn.close()
        await render_sub_tasks(call.message.chat.id, call.from_user.id)
        return

    channel_id, base_reward = task
    if channel_id != "0":
        try:
            member = await bot.get_chat_member(chat_id=channel_id, user_id=call.from_user.id)
            if member.status in ("left", "kicked"):
                await call.answer("❌ Вы еще не подписались! Подпишитесь на канал и нажмите кнопку снова.", show_alert=True)
                conn.close()
                return
        except Exception:
            pass

    reward = round(base_reward * mult, 2)
    try:
        cur.execute("INSERT INTO completed (user_id, task_id) VALUES (?, ?)", (user[0], task_id))
        cur.execute("UPDATE users SET balance = balance + ?, completed_tasks = completed_tasks + 1 WHERE user_id = ?", (reward, user[0]))
        conn.commit()
    except sqlite3.IntegrityError:
        await call.answer("Оплата уже была получена!", show_alert=True)
        conn.close()
        return

    conn.close()
    await call.answer(f"💸 Зачислено +{reward:.2f} ₽ на ваш баланс!", show_alert=True)
    # Автоматически загружаем следующее задание в этом же чистом окне!
    await render_sub_tasks(call.message.chat.id, call.from_user.id)

# =====================================================================
# 💰 РАЗДЕЛ 2: CPA-КОНТРАКТЫ (ЛИСТАНИЕ В ОДНОМ ОКНЕ + СКРИНШОТЫ)
# =====================================================================
async def render_cpa_tasks(chat_id: int, user_id: int, index: int = 0):
    user = get_user(user_id)
    mult = VIP_TIERS[user[3]][3]

    conn = sqlite3.connect("profithub.db")
    cur = conn.cursor()
    cur.execute("""
        SELECT id, title, description, url, base_reward FROM tasks 
        WHERE task_type = 'cpa' AND id NOT IN (SELECT task_id FROM completed WHERE user_id = ?)
    """, (user[0],))
    tasks = cur.fetchall()
    conn.close()

    if not tasks:
        await show_screen(
            chat_id,
            "⏳💼 <b>Все контракты на текущий час разобраны исполнителями!</b>\n\n"
            "Рекламодатели пополняют баланс контрактов каждый день.\n"
            "🔥 А пока заберите <b>5 000 ₽</b> за приглашение 10 друзей или повысьте статус до VIP!",
            reply_markup=back_to_menu_kb(include_vip=True),
            sticker_emoji="💼"
        )
        return

    index = max(0, min(index, len(tasks) - 1))
    t_id, title, desc, url, base_rew = tasks[index]
    user_rew = round(base_rew * mult, 0)
    vip_rew = round(base_rew * VIP_TIERS[3][3], 0)
    diff = vip_rew - user_rew

    buttons = [
        [InlineKeyboardButton(text="🔗 1. Перейти к выполнению контракта", url=url)],
        [InlineKeyboardButton(text=f"📸 2. Отправить отчет и получить +{user_rew:.0f} ₽", callback_data=f"cpaproof_{t_id}")]
    ]

    # Кнопки перелистывания контрактов в одном окне
    nav_row = []
    if index > 0:
        nav_row.append(InlineKeyboardButton(text="⬅️ Пред. контракт", callback_data=f"nav_cpa_{index - 1}"))
    if index < len(tasks) - 1:
        nav_row.append(InlineKeyboardButton(text="След. контракт ➡️", callback_data=f"nav_cpa_{index + 1}"))
    if nav_row:
        buttons.append(nav_row)

    if user[3] < 3:
        buttons.append([InlineKeyboardButton(text=f"👑 Взять VIP и получить {vip_rew:.0f} ₽ (+{diff:.0f} ₽)", callback_data="open_vip_shop")])
    buttons.append([InlineKeyboardButton(text="🔙 Назад в главное меню", callback_data="nav_main")])

    vip_note = (
        f"\n🔥 <b>Выплата с VIP-Агентство:</b> <code>{vip_rew:.0f} ₽</code>\n"
        f"⚠️ <i>Без VIP-статуса вы теряете <b>{diff:.0f} ₽</b> чистой прибыли на этом задании!</i>"
        if user[3] < 3 else ""
    )

    text = (
        f"💰🔥 <b>ДЕНЕЖНЫЙ КОНТРАКТ #{t_id}</b> <i>({index + 1} из {len(tasks)})</i>\n\n"
        f"📌 <b>Заказчик:</b> {title}\n"
        f"📝 <b>Инструкция:</b>\n{desc}\n\n"
        f"💵 <b>Ваша выплата:</b> <code>+{user_rew:.0f} ₽</code>{vip_note}"
    )
    await show_screen(chat_id, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), sticker_emoji="💰")

@dp.message(F.text == "💰 Контракты (до 1500₽)")
async def msg_cpa_tasks(message: types.Message, state: FSMContext):
    await state.clear()
    await delete_user_msg(message)
    await render_cpa_tasks(message.chat.id, message.from_user.id, 0)

@dp.callback_query(F.data.startswith("nav_cpa_"))
async def cb_cpa_tasks(call: types.CallbackQuery, state: FSMContext):
    await state.clear()
    idx = int(call.data.split("_")[2])
    await render_cpa_tasks(call.message.chat.id, call.from_user.id, idx)
    await call.answer()

@dp.callback_query(F.data.startswith("cpaproof_"))
async def ask_cpa_proof(call: types.CallbackQuery, state: FSMContext):
    task_id = int(call.data.split("_")[1])
    await state.update_data(task_id=task_id)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад к контрактам", callback_data="nav_cpa_0"),
         InlineKeyboardButton(text="❌ Отмена", callback_data="nav_main")]
    ])
    await show_screen(
        call.message.chat.id,
        f"📸📩 <b>ОТПРАВКА ОТЧЕТА ПО КОНТРАКТУ #{task_id}</b>\n\n"
        f"Отправьте в чат <b>скриншот (фотографию)</b> выполненного задания или напишите данные для проверки текстом (например: имя, время оформления или последние 4 цифры).\n\n"
        f"👇 <i>Если передумали, нажмите «🔙 Назад» или «❌ Отмена»:</i>",
        reply_markup=kb,
        sticker_emoji="📸"
    )
    await state.set_state(CpaProofFSM.waiting_for_proof)
    await call.answer()

@dp.message(CpaProofFSM.waiting_for_proof)
async def receive_cpa_proof(message: types.Message, state: FSMContext):
    data = await state.get_data()
    task_id = data["task_id"]
    user = get_user(message.from_user.id)
    mult = VIP_TIERS[user[3]][3]

    conn = sqlite3.connect("profithub.db")
    cur = conn.cursor()
    cur.execute("SELECT title, base_reward FROM tasks WHERE id = ?", (task_id,))
    task = cur.fetchone()
    conn.close()

    if not task:
        await delete_user_msg(message)
        await state.clear()
        await render_main_menu(message.chat.id, message.from_user.id)
        return

    title, base_rew = task
    reward = round(base_rew * mult, 0)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"✅ Одобрить (+{reward:.0f}₽)", callback_data=f"cpaok_{user[0]}_{task_id}_{reward}")],
        [InlineKeyboardButton(text="❌ Отклонить отчет", callback_data=f"cpano_{user[0]}_{task_id}")]
    ])

    proof_text = message.text or message.caption or "Скриншот без текста"
    admin_caption = (
        f"📋 <b>Отчет по CPA-контракту #{task_id} ({title})</b>\n"
        f"От: @{user[1]} (ID: <code>{user[0]}</code>)\n"
        f"К выплате: <b>{reward:.0f} ₽</b>\n\n"
        f"💬 <b>Данные отчета:</b>\n{proof_text}"
    )

    if message.photo:
        await bot.send_photo(ADMIN_ID, photo=message.photo[-1].file_id, caption=admin_caption, reply_markup=kb, parse_mode="HTML")
    else:
        await bot.send_message(ADMIN_ID, admin_caption, reply_markup=kb, parse_mode="HTML")

    await delete_user_msg(message)
    await state.clear()

    done_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💰 К другим контрактам", callback_data="nav_cpa_0")],
        [InlineKeyboardButton(text="🔙 Назад в главное меню", callback_data="nav_main")]
    ])
    await show_screen(
        message.chat.id,
        f"✅🎉 <b>Ваш отчет по Контракту #{task_id} отправлен на проверку!</b>\n\n"
        f"💵 Сумма к зачислению: <b>+{reward:.0f} ₽</b>\n"
        f"⏳ После подтверждения заявки рекламодателем деньги автоматически поступят на ваш баланс!",
        reply_markup=done_kb,
        sticker_emoji="🎉"
    )

@dp.callback_query(F.data.startswith("cpaok_"))
async def admin_approve_cpa(call: types.CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        return
    _, target_id, task_id, reward = call.data.split("_")
    target_id, task_id, reward = int(target_id), int(task_id), float(reward)

    conn = sqlite3.connect("profithub.db")
    cur = conn.cursor()
    cur.execute("INSERT OR IGNORE INTO completed (user_id, task_id) VALUES (?, ?)", (target_id, task_id))
    cur.execute("UPDATE users SET balance = balance + ?, completed_tasks = completed_tasks + 1 WHERE user_id = ?", (reward, target_id))
    conn.commit()
    conn.close()

    if call.message.photo:
        await call.message.edit_caption(caption=(call.message.caption or "") + "\n\n✅ <b>ОДОБРЕНО</b>", parse_mode="HTML")
    else:
        await call.message.edit_text((call.message.text or "") + "\n\n✅ <b>ОДОБРЕНО</b>", parse_mode="HTML")

    try:
        await bot.send_message(target_id, f"🎉💸 <b>Контракт #{task_id} одобрен!</b>\nНа ваш баланс зачислено: <b>+{reward:.2f} ₽</b>!", parse_mode="HTML")
    except Exception:
        pass

@dp.callback_query(F.data.startswith("cpano_"))
async def admin_reject_cpa(call: types.CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        return
    _, target_id, task_id = call.data.split("_")
    if call.message.photo:
        await call.message.edit_caption(caption=(call.message.caption or "") + "\n\n❌ <b>ОТКЛОНЕНО</b>", parse_mode="HTML")
    else:
        await call.message.edit_text((call.message.text or "") + "\n\n❌ <b>ОТКЛОНЕНО</b>", parse_mode="HTML")
    try:
        await bot.send_message(int(target_id), f"⚠️ Отчет по контракту #{task_id} отклонен. Условия рекламодателя не выполнены.")
    except Exception:
        pass

# =====================================================================
# 🎁 РАЗДЕЛ 3: АКЦИЯ «5 000 ₽ ЗА 10 ДРУЗЕЙ»
# =====================================================================
async def render_quest_screen(chat_id: int, user_id: int):
    user = get_user(user_id)
    bot_info = await bot.get_me()
    ref_link = f"https://t.me/{bot_info.username}?start={user[0]}"

    ref_count = user[5]
    claimed = user[7]
    ref_p = VIP_TIERS[user[3]][4]

    filled = min(REF_QUEST_TARGET, ref_count)
    empty = REF_QUEST_TARGET - filled
    progress_bar = "🟩" * filled + "⬜" * empty

    status_line = (
        "✅🎉 <b>ВЫ УЖЕ ПОЛУЧИЛИ 5 000 ₽! Продолжайте приглашать и забирайте до 50% с покупок!</b>"
        if claimed else
        f"🔥 Осталось пригласить всего: <b>{empty} чел.</b> до автовыплаты <b>5 000 ₽ на баланс</b>!"
    )

    share_url = f"https://t.me/share/url?url={ref_link}&text=🔥%20Забирай%20+50%20рублей%20на%20баланс%20за%20вход%20и%20до%201500%20рублей%20за%20простые%20задания%20в%20Telegram!"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📲 Отправить ссылку друзьям в 1 клик", url=share_url)],
        [InlineKeyboardButton(text="👑 Поднять реферальный доход до 50% (VIP)", callback_data="open_vip_shop")],
        [InlineKeyboardButton(text="🔙 Назад в главное меню", callback_data="nav_main")]
    ])

    text = (
        f"🎁💸 <b>АКЦИЯ: 5 000 ₽ НА КАРТУ ЗА 10 ДРУЗЕЙ!</b>\n\n"
        f"Пригласите <b>10 друзей</b> по своей персональной ссылке (им даже не обязательно ничего покупать — достаточно просто запустить бота), и система автоматически начислит вам <b>5 000 ₽</b>!\n\n"
        f"📊 <b>Ваш прогресс выполнения ({ref_count} из {REF_QUEST_TARGET}):</b>\n"
        f"{progress_bar}\n"
        f"{status_line}\n\n"
        f"💎 <b>Пожизненный пассивный доход до 50%:</b>\n"
        f"С каждой покупки VIP-статуса приглашенным другом вы мгновенно получаете <b>{ref_p}%</b> на баланс для вывода!\n"
        f"<i>(Со статусом «👑 VIP-Агентство» вы забираете 50% — до 1 245 ₽ с одного человека!)</i>\n\n"
        f"🔗 <b>Ваша ссылка для приглашения (нажмите, чтобы скопировать):</b>\n"
        f"<code>{ref_link}</code>"
    )
    await show_screen(chat_id, text, reply_markup=kb, sticker_emoji="🎁")

@dp.message(F.text == "🎁 Акция: 5 000 ₽ за 10 друзей")
async def msg_quest(message: types.Message, state: FSMContext):
    await state.clear()
    await delete_user_msg(message)
    await render_quest_screen(message.chat.id, message.from_user.id)

@dp.callback_query(F.data == "nav_quest")
async def cb_quest(call: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await render_quest_screen(call.message.chat.id, call.from_user.id)
    await call.answer()

# =====================================================================
# 🚀 РАЗДЕЛ 4: АГРЕССИВНЫЙ VIP-МАГАЗИН + АВТООПЛАТА ЮMONEY
# =====================================================================
async def render_vip_shop(chat_id: int, user_id: int):
    text = (
        "👑🚀 <b>VIP-СТАТУСЫ: УВЕЛИЧЬТЕ ДОХОД В 2.5 РАЗА!</b>\n"
        "🔥 <i>Внимание: действует спецпредложение — скидка -50% на все пакеты повышения дохода!</i>\n\n"
        "Владельцы VIP-аккаунтов подключены к <b>приоритетному пулу рекламодателей</b>, получают до <b>2.5 раз больше денег</b> за те же самые клики и выводят средства на карту <b>без очереди</b>!\n\n"
        "⚡ <b>PRO-Исполнитель — 390 ₽</b> (вместо <s>790 ₽</s>)\n"
        "├ Оплата за все задания и контракты: <b>x1.5 (+50% к доходу)</b>\n"
        "├ Реферальный процент с покупок: <b>30%</b>\n"
        "└ 💡 <i>Окупается за 15 минут с первого же контракта!</i>\n\n"
        "🔥 <b>Бизнес-Партнер — 990 ₽</b> (вместо <s>1 990 ₽</s>) <b>[ХИТ ПРОДАЖ]</b>\n"
        "├ Оплата за все задания и контракты: <b>x2.0 (ДВОЙНОЙ ДОХОД!)</b>\n"
        "├ Реферальный процент с покупок: <b>40%</b>\n"
        "└ Ускоренная проверка отчетов и приоритетный вывод средств.\n\n"
        "👑 <b>VIP-Агентство — 2 490 ₽</b> (вместо <s>4 990 ₽</s>) <b>[МАКСИМУМ]</b>\n"
        "├ Максимальная ставка оплаты: <b>x2.5 (до 1 500 ₽ за 1 задание!)</b>\n"
        "├ Максимальная партнерка: <b>50% С КАЖДОЙ ОПЛАТЫ ДРУЗЕЙ!</b>\n"
        "└ Мгновенный автовывод средств по СБП 24/7 без лимитов.\n\n"
        "🔒 <i>Оплата проходит через защищенный шлюз <b>ЮMoney</b> (любые карты РФ / СБП). Выберите тариф ниже, оплатите и нажмите «🔄 Я оплатил!»:</i>"
    )
    await show_screen(chat_id, text, reply_markup=vip_shop_kb(user_id), sticker_emoji="👑")

@dp.message(F.text == "🚀 Увеличить доход (VIP x2.5)")
async def msg_vip_shop(message: types.Message, state: FSMContext):
    await state.clear()
    await delete_user_msg(message)
    await render_vip_shop(message.chat.id, message.from_user.id)

@dp.callback_query(F.data == "open_vip_shop")
async def cb_vip_shop(call: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await render_vip_shop(call.message.chat.id, call.from_user.id)
    await call.answer()

async def activate_user_vip(target_id: int, lvl: int, price: float):
    user = get_user(target_id)
    if not user:
        return
    conn = sqlite3.connect("profithub.db")
    cur = conn.cursor()
    cur.execute("UPDATE users SET vip_level = ? WHERE user_id = ?", (lvl, target_id))

    ref_id = user[4]
    if ref_id:
        ref_user = get_user(ref_id)
        if ref_user:
            ref_perc = VIP_TIERS[ref_user[3]][4]
            ref_bonus = round(price * (ref_perc / 100.0), 2)
            cur.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (ref_bonus, ref_id))
            try:
                await bot.send_message(
                    ref_id,
                    f"💸🥳 <b>ПАРТНЕРСКАЯ ВЫПЛАТА!</b>\n"
                    f"Ваш реферал приобрел VIP-статус за {price:.0f} ₽.\n"
                    f"По вашему тарифу ({ref_perc}%) вам зачислено: <b>+{ref_bonus:.2f} ₽</b> на вывод!",
                    parse_mode="HTML"
                )
            except Exception:
                pass

    conn.commit()
    conn.close()

    vip_name, _, _, mult, ref_p = VIP_TIERS[lvl]
    try:
        await show_screen(
            target_id,
            f"🎉👑 <b>ПОЗДРАВЛЯЕМ! ВАМ АКТИВИРОВАН СТАТУС «{vip_name}»!</b>\n\n"
            f"📈 Ваша ставка оплаты за все задания увеличена до <b>x{mult}</b>!\n"
            f"👥 Ваша реферальная комиссия увеличена до <b>{ref_p}%</b>!\n"
            f"🏦 Вам открыт приоритетный вывод средств без очереди!",
            reply_markup=back_to_menu_kb(include_vip=False),
            sticker_emoji="🥳"
        )
    except Exception:
        pass

@dp.callback_query(F.data == "check_vip_pay")
async def check_vip_payment(call: types.CallbackQuery):
    uid = call.from_user.id
    now = time.time()

    if uid in payment_cooldowns and now - payment_cooldowns[uid] < 60:
        wait_sec = int(60 - (now - payment_cooldowns[uid]))
        await call.answer(f"⏳ Подождите {wait_sec} сек. перед повторной проверкой!", show_alert=True)
        return
    payment_cooldowns[uid] = now

    if YOOMONEY_TOKEN.strip():
        headers = {
            "Authorization": f"Bearer {YOOMONEY_TOKEN.strip()}",
            "Content-Type": "application/x-www-form-urlencoded"
        }
        found_lvl = None
        found_price = 0
        found_op_id = None

        conn = sqlite3.connect("profithub.db")
        cur = conn.cursor()

        try:
            async with aiohttp.ClientSession() as session:
                for lvl in (3, 2, 1):
                    label = f"vip_{uid}_{lvl}"
                    _, _, price, _, _ = VIP_TIERS[lvl]
                    async with session.post(
                        "https://yoomoney.ru/api/operation-history",
                        headers=headers,
                        data={"label": label, "type": "deposition", "records": 5}
                    ) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            for op in data.get("operations", []):
                                op_id = str(op.get("operation_id"))
                                if op.get("status") == "success":
                                    cur.execute("SELECT 1 FROM processed_payments WHERE operation_id = ?", (op_id,))
                                    if not cur.fetchone():
                                        found_lvl = lvl
                                        found_price = price
                                        found_op_id = op_id
                                        break
                    if found_lvl:
                        break
        except Exception as e:
            logging.error(f"YooMoney API error: {e}")

        if found_lvl and found_op_id:
            cur.execute("INSERT INTO processed_payments (operation_id, user_id, amount) VALUES (?, ?, ?)", (found_op_id, uid, found_price))
            conn.commit()
            conn.close()
            await call.answer("✅ Оплата найдена! Статус активирован!", show_alert=True)
            await activate_user_vip(uid, found_lvl, found_price)
            await bot.send_message(ADMIN_ID, f"💰 <b>АВТООПЛАТА VIP!</b>\nИгрок @{call.from_user.username} (<code>{uid}</code>) купил VIP #{found_lvl} за {found_price} ₽!", parse_mode="HTML")
            return
        conn.close()
        await call.answer("❌ Платеж еще не поступил в ЮMoney. Если вы оплатили, подождите 1 минуту и нажмите кнопку снова.", show_alert=True)
        return

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⚡ Выдать PRO (390₽)", callback_data=f"setvip_{uid}_1_390")],
        [InlineKeyboardButton(text="🔥 Выдать Бизнес (990₽)", callback_data=f"setvip_{uid}_2_990")],
        [InlineKeyboardButton(text="👑 Выдать Агентство (2490₽)", callback_data=f"setvip_{uid}_3_2490")]
    ])
    await bot.send_message(
        ADMIN_ID,
        f"💳 <b>Запрос на проверку оплаты VIP!</b>\n"
        f"Игрок: @{call.from_user.username} (ID: <code>{uid}</code>)\n"
        f"Метка платежа: <code>vip_{uid}_...</code>",
        reply_markup=kb,
        parse_mode="HTML"
    )
    await call.answer("⏳ Заявка отправлена! Статус автоматически включится после подтверждения транзакции (1-5 мин).", show_alert=True)

@dp.callback_query(F.data.startswith("setvip_"))
async def admin_confirm_vip(call: types.CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        return
    _, target_id, lvl, price = call.data.split("_")
    target_id, lvl, price = int(target_id), int(lvl), float(price)

    await activate_user_vip(target_id, lvl, price)
    vip_name = VIP_TIERS[lvl][0]
    await call.message.edit_text(f"✅ Выдан статус <b>{vip_name}</b> пользователю <code>{target_id}</code>.", parse_mode="HTML")

# =====================================================================
# 👤 РАЗДЕЛ 5: ЛИЧНЫЙ КАБИНЕТ И ВСТРОЕННЫЙ ШЛЮЗ ЖИВЫХ ВЫПЛАТ
# =====================================================================
async def render_cabinet(chat_id: int, user_id: int):
    user = get_user(user_id)
    vip_name, _, _, mult, ref_p = VIP_TIERS[user[3]]
    quest_left = max(0, REF_QUEST_TARGET - user[5])

    buttons = []
    if user[3] < 3:
        buttons.append([InlineKeyboardButton(text="🚀 Повысить доход до x2.5 (VIP)", callback_data="open_vip_shop")])
    buttons.append([InlineKeyboardButton(text="🏦 Вывести средства на карту", callback_data="nav_withdraw")])
    buttons.append([InlineKeyboardButton(text="🔙 Назад в главное меню", callback_data="nav_main")])

    text = (
        f"👤💼 <b>ЛИЧНЫЙ КАБИНЕТ ИСПОЛНИТЕЛЯ #{user[0]}</b>\n\n"
        f"┏━━━━━━━━━━━━━━━━━━━━━┓\n"
        f"┃ 🌟 <b>Ваш тариф:</b> {vip_name}\n"
        f"┃ 📈 <b>Ставка оплаты:</b> <code>x{mult}</code>\n"
        f"┃ ✅ <b>Выполнено заданий:</b> {user[6]} шт.\n"
        f"┃ 👥 <b>Приглашено друзей:</b> {user[5]} чел.\n"
        f"┃ 💎 <b>Реферальный бонус:</b> <code>{ref_p}%</code>\n"
        f"┗━━━━━━━━━━━━━━━━━━━━━┛\n\n"
        f"🎁 <b>Квест на 5 000 ₽:</b> осталось пригласить <b>{quest_left} чел.</b>\n"
        f"💳 <b>Доступный баланс:</b> <code>{user[2]:.2f} ₽</code> <i>(Вывод от {MIN_WITHDRAW:.0f} ₽)</i>"
    )
    await show_screen(chat_id, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), sticker_emoji="👤")

@dp.message(F.text == "👤 Личный кабинет")
async def msg_cabinet(message: types.Message, state: FSMContext):
    await state.clear()
    await delete_user_msg(message)
    await render_cabinet(message.chat.id, message.from_user.id)

@dp.callback_query(F.data == "nav_cab")
async def cb_cabinet(call: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await render_cabinet(call.message.chat.id, call.from_user.id)
    await call.answer()

async def render_live_payouts(chat_id: int):
    """Генерирует реалистичный онлайн-реестр выплат прямо внутри бота (без внешних каналов)"""
    now = datetime.now()
    pool = [
        ("@alex_k***", "🟢 Сбербанк (СБП)", "1 450.00 ₽", "👑 VIP"),
        ("@marina_8***", "🟡 Т-Банк", "5 000.00 ₽", "🎁 Бонус 10 друзей"),
        ("@denis_v***", "🔴 Альфа-Банк", "920.00 ₽", "🔥 Бизнес"),
        ("@sergey_m***", "🟢 Сбербанк (СБП)", "2 750.00 ₽", "👑 VIP"),
        ("@olga_t***", "🟣 ЮMoney", "340.00 ₽", "⚡ PRO"),
        ("@vlad_p***", "🟡 Т-Банк", "5 000.00 ₽", "🎁 Бонус 10 друзей"),
        ("@kirill_s***", "🔵 ВТБ (СБП)", "1 800.00 ₽", "👑 VIP"),
        ("@anna_l***", "🟢 Сбербанк (СБП)", "610.00 ₽", "⚡ PRO"),
        ("@roman_g***", "🔴 Альфа-Банк", "3 100.00 ₽", "👑 VIP"),
        ("@timur_a***", "🟡 Т-Банк", "490.00 ₽", "🌱 Стажер")
    ]
    selected = random.sample(pool, 6)
    lines = []
    offset_min = 1
    for uname, bank, amt, badge in selected:
        t_str = (now - timedelta(minutes=offset_min)).strftime("%H:%M")
        offset_min += random.randint(2, 6)
        lines.append(f"✅ <code>[{t_str}]</code> <b>{amt}</b> ➔ {bank} ({uname} | {badge})")

    feed_text = "\n".join(lines)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Обновить онлайн-шлюз выплат", callback_data="nav_payouts")],
        [InlineKeyboardButton(text="🚀 Подключить VIP (Вывод без очереди)", callback_data="open_vip_shop")],
        [InlineKeyboardButton(text="🔙 Назад в главное меню", callback_data="nav_main")]
    ])

    text = (
        f"🛡✅ <b>ОНЛАЙН-ШЛЮЗ ВЫПЛАТ И ГАРАНТИИ PROFIT-HUB</b>\n\n"
        f"📡 <b>Статус платежного шлюза СБП / ЮMoney:</b> 🟢 <code>РАБОТАЕТ В ШТАТНОМ РЕЖИМЕ</code>\n"
        f"💳 <b>Выплачено за сегодня:</b> <code>482 950 ₽</code>\n\n"
        f"📊 <b>Последние автоматические транзакции:</b>\n"
        f"{feed_text}\n\n"
        f"❓ <b>Почему нам доверяют более 45 000 исполнителей:</b>\n"
        f"1️⃣ Мы работаем напрямую с рекламными бюджетами банков РФ и крупных Telegram-проектов.\n"
        f"2️⃣ Каждый новый участник сразу получает <b>+50 ₽</b> на баланс при старте.\n"
        f"3️⃣ Вывод средств от <b>100 ₽</b> на любую карту РФ без скрытых комиссий!"
    )
    await show_screen(chat_id, text, reply_markup=kb, sticker_emoji="🛡️")

@dp.message(F.text == "✅ Живые выплаты и Гарантии")
async def msg_payouts(message: types.Message, state: FSMContext):
    await state.clear()
    await delete_user_msg(message)
    await render_live_payouts(message.chat.id)

@dp.callback_query(F.data == "nav_payouts")
async def cb_payouts(call: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await render_live_payouts(call.message.chat.id)
    await call.answer("🔄 Данные платежного шлюза обновлены!")

# =====================================================================
# 🏦 РАЗДЕЛ 6: ВЫВОД СРЕДСТВ (С ПОШАГОВЫМ ВОЗВРАТОМ «НАЗАД»)
# =====================================================================
async def render_withdraw_start(chat_id: int, user_id: int, state: FSMContext):
    user = get_user(user_id)
    if user[2] < MIN_WITHDRAW:
        need = MIN_WITHDRAW - user[2]
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🚀 Заработать в 2.5 раза быстрее (VIP)", callback_data="open_vip_shop")],
            [InlineKeyboardButton(text="🎁 Забрать 5 000 ₽ за 10 друзей", callback_data="nav_quest")],
            [InlineKeyboardButton(text="🔙 Назад в главное меню", callback_data="nav_main")]
        ])
        await show_screen(
            chat_id,
            f"🏦💳 <b>ОТДЕЛ ВЫПЛАТ PROFIT-HUB</b>\n\n"
            f"💰 Ваш баланс: <code>{user[2]:.2f} ₽</code>\n"
            f"⚠️ Минимальная сумма для вывода: <b>{MIN_WITHDRAW:.0f} ₽</b>\n"
            f"🔥 <i>Вам осталось заработать всего <b>{need:.2f} ₽</b> до первой выплаты на карту!</i>\n\n"
            f"💡 <b>Как мгновенно набрать сумму для вывода:</b>\n"
            f"• Подключите <b>VIP-Статус</b> и получайте до 1 500 ₽ за 1 контракт!\n"
            f"• Пригласите 10 друзей и заберите <b>5 000 ₽</b>!",
            reply_markup=kb,
            sticker_emoji="🏦"
        )
        return

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад в главное меню", callback_data="nav_main"),
         InlineKeyboardButton(text="❌ Отмена", callback_data="nav_main")]
    ])
    await show_screen(
        chat_id,
        f"🏦💸 <b>ОФОРМЛЕНИЕ ВЫПЛАТЫ НА КАРТУ</b> (Шаг 1 из 3)\n\n"
        f"💳 Доступно к выводу: <code>{user[2]:.2f} ₽</code>\n"
        f"✍️ <b>Отправьте в чат сумму, которую хотите вывести (числом в рублях):</b>",
        reply_markup=kb,
        sticker_emoji="🏦"
    )
    await state.set_state(WithdrawFSM.amount)

@dp.message(F.text == "🏦 Вывод средств")
async def msg_withdraw(message: types.Message, state: FSMContext):
    await state.clear()
    await delete_user_msg(message)
    await render_withdraw_start(message.chat.id, message.from_user.id, state)

@dp.callback_query(F.data == "nav_withdraw")
async def cb_withdraw(call: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await render_withdraw_start(call.message.chat.id, call.from_user.id, state)
    await call.answer()

@dp.message(WithdrawFSM.amount)
async def withdraw_amount_step(message: types.Message, state: FSMContext):
    await delete_user_msg(message)
    user = get_user(message.from_user.id)
    try:
        amt = float(message.text.replace(",", ".").strip())
    except ValueError:
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Отмена", callback_data="nav_main")]])
        await show_screen(message.chat.id, "❌ <b>Ошибка! Введите сумму цифрами</b> (например: <code>500</code>):", reply_markup=kb)
        return

    if amt < MIN_WITHDRAW or amt > user[2]:
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Отмена", callback_data="nav_main")]])
        await show_screen(message.chat.id, f"❌ <b>Укажите сумму от {MIN_WITHDRAW:.0f} до {user[2]:.2f} ₽:</b>", reply_markup=kb)
        return

    await state.update_data(amount=amt)
    await show_screen(
        message.chat.id,
        f"🏦💳 <b>ВЫБОР БАНКА ПОЛУЧАТЕЛЯ</b> (Шаг 2 из 3)\n\n"
        f"💵 Сумма к выводу: <b>{amt:.2f} ₽</b>\n"
        f"👇 <b>Выберите ваш банк из списка ниже:</b>",
        reply_markup=banks_kb()
    )
    await state.set_state(WithdrawFSM.bank)

@dp.callback_query(F.data == "back_to_banks")
async def cb_back_to_banks(call: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    amt = data.get("amount", MIN_WITHDRAW)
    await show_screen(
        call.message.chat.id,
        f"🏦💳 <b>ВЫБОР БАНКА ПОЛУЧАТЕЛЯ</b> (Шаг 2 из 3)\n\n"
        f"💵 Сумма к выводу: <b>{amt:.2f} ₽</b>\n"
        f"👇 <b>Выберите ваш банк из списка ниже:</b>",
        reply_markup=banks_kb()
    )
    await state.set_state(WithdrawFSM.bank)
    await call.answer()

@dp.callback_query(WithdrawFSM.bank, F.data.startswith("bank_"))
async def withdraw_bank_step(call: types.CallbackQuery, state: FSMContext):
    bank = call.data.split("_")[1]
    await state.update_data(bank=bank)
    data = await state.get_data()
    amt = data["amount"]

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад (Выбрать другой банк)", callback_data="back_to_banks")],
        [InlineKeyboardButton(text="❌ Отменить вывод", callback_data="nav_main")]
    ])
    await show_screen(
        call.message.chat.id,
        f"🏦✍️ <b>ВВОД РЕКВИЗИТОВ ПОЛУЧАТЕЛЯ</b> (Шаг 3 из 3)\n\n"
        f"💵 Сумма: <b>{amt:.2f} ₽</b>\n"
        f"🏦 Банк: <b>{bank}</b>\n\n"
        f"✍️ <b>Отправьте в чат номер карты или телефона (СБП) и Имя получателя:</b>",
        reply_markup=kb
    )
    await state.set_state(WithdrawFSM.requisites)
    await call.answer()

@dp.message(WithdrawFSM.requisites)
async def withdraw_finish_step(message: types.Message, state: FSMContext):
    reqs = message.text
    await delete_user_msg(message)
    data = await state.get_data()
    amt, bank = data["amount"], data["bank"]
    uid = message.from_user.id

    conn = sqlite3.connect("profithub.db")
    cur = conn.cursor()
    cur.execute("UPDATE users SET balance = balance - ? WHERE user_id = ?", (amt, uid))
    cur.execute("INSERT INTO withdrawals (user_id, amount, bank, requisites) VALUES (?, ?, ?, ?)", (uid, amt, bank, reqs))
    w_id = cur.lastrowid
    conn.commit()
    conn.close()
    await state.clear()

    user = get_user(uid)
    priority_text = (
        "⚡ <b>Приоритет: VIP-Экспресс</b> (Зачисление вне очереди)"
        if user[3] > 0 else
        "⏳ <b>Приоритет: Стандартная очередь</b> <i>(С VIP-статусом выплаты приходят мгновенно вне очереди)</i>"
    )

    await show_screen(
        message.chat.id,
        f"✅🎉 <b>ЗАЯВКА НА ВЫПЛАТУ #{w_id} ПРИНЯТА!</b>\n\n"
        f"💵 Сумма выплаты: <b>{amt:.2f} ₽</b>\n"
        f"🏦 Банк: <b>{bank}</b>\n"
        f"💳 Реквизиты: <code>{reqs}</code>\n\n"
        f"{priority_text}",
        reply_markup=back_to_menu_kb(include_vip=(user[3] == 0)),
        sticker_emoji="💸"
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Выплачено", callback_data=f"wd_ok_{w_id}_{uid}_{amt}")],
        [InlineKeyboardButton(text="❌ Отклонить (Возврат)", callback_data=f"wd_no_{w_id}_{uid}_{amt}")]
    ])
    await bot.send_message(
        ADMIN_ID,
        f"🏦 <b>ЗАЯВКА НА ВЫВОД #{w_id}</b>\n"
        f"От: @{message.from_user.username} (ID: <code>{uid}</code> | VIP: {user[3]})\n"
        f"Сумма: <b>{amt:.2f} ₽</b>\n"
        f"Банк: <b>{bank}</b>\n"
        f"Реквизиты: <code>{reqs}</code>",
        reply_markup=kb,
        parse_mode="HTML"
    )

@dp.callback_query(F.data.startswith("wd_"))
async def admin_wd_action(call: types.CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        return
    _, act, w_id, uid, amt = call.data.split("_")
    w_id, uid, amt = int(w_id), int(uid), float(amt)

    conn = sqlite3.connect("profithub.db")
    cur = conn.cursor()
    if act == "ok":
        cur.execute("UPDATE withdrawals SET status = 'paid' WHERE id = ?", (w_id,))
        await call.message.edit_text(call.message.text + "\n\n✅ <b>ВЫПЛАЧЕНО</b>", parse_mode="HTML")
        try:
            await bot.send_message(uid, f"🎉💸 <b>Выплата #{w_id} на сумму {amt:.2f} ₽ успешно отправлена по вашим реквизитам!</b>", parse_mode="HTML")
        except Exception:
            pass
    else:
        cur.execute("UPDATE withdrawals SET status = 'rejected' WHERE id = ?", (w_id,))
        cur.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amt, uid))
        await call.message.edit_text(call.message.text + "\n\n❌ <b>ОТКЛОНЕНО (ВОЗВРАТ)</b>", parse_mode="HTML")
        try:
            await bot.send_message(uid, f"⚠️ Заявка #{w_id} возвращена на баланс ({amt:.2f} ₽). Проверьте реквизиты.")
        except Exception:
            pass
    conn.commit()
    conn.close()

# =====================================================================
# 🛠 АДМИН-ПАНЕЛЬ (/admin) С АВТООЧИСТКОЙ И НАВИГАЦИЕЙ
# =====================================================================
@dp.message(Command("admin"))
async def admin_panel(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    await state.clear()
    await delete_user_msg(message)
    await show_screen(
        message.chat.id,
        "🛠⚙️ <b>АДМИН-ПАНЕЛЬ УПРАВЛЕНИЯ PROFIT-HUB</b>\nВыберите нужное действие:",
        reply_markup=admin_menu_kb(),
        sticker_emoji="⚙️"
    )

@dp.callback_query(F.data == "adm_back")
async def admin_back_cb(call: types.CallbackQuery, state: FSMContext):
    if call.from_user.id != ADMIN_ID:
        return
    await state.clear()
    await show_screen(
        call.message.chat.id,
        "🛠⚙️ <b>АДМИН-ПАНЕЛЬ УПРАВЛЕНИЯ PROFIT-HUB</b>\nВыберите нужное действие:",
        reply_markup=admin_menu_kb()
    )
    await call.answer()

@dp.callback_query(F.data == "adm_stats")
async def admin_stats(call: types.CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        return
    conn = sqlite3.connect("profithub.db")
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*), SUM(balance), SUM(completed_tasks) FROM users")
    total_users, total_bal, total_completed = cur.fetchone()
    cur.execute("SELECT COUNT(*) FROM users WHERE vip_level > 0")
    vip_users = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM tasks")
    active_tasks = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*), SUM(amount) FROM withdrawals WHERE status = 'pending'")
    pending_wd_count, pending_wd_sum = cur.fetchone()
    conn.close()

    text = (
        f"📊📈 <b>СТАТИСТИКА ПРОЕКТА PROFIT-HUB:</b>\n\n"
        f"👥 Всего пользователей: <b>{total_users or 0}</b>\n"
        f"👑 Купили VIP-статус: <b>{vip_users or 0}</b>\n"
        f"✅ Выполнено заданий: <b>{total_completed or 0}</b>\n"
        f"📋 Активных заданий: <b>{active_tasks or 0}</b>\n"
        f"💳 Сумма на балансах: <b>{total_bal or 0:.2f} ₽</b>\n"
        f"⏳ Ожидают вывода: <b>{pending_wd_count or 0} шт.</b> ({pending_wd_sum or 0:.2f} ₽)"
    )
    await show_screen(call.message.chat.id, text, reply_markup=admin_menu_kb())
    await call.answer()

@dp.callback_query(F.data == "adm_del_tasks")
async def admin_list_tasks_to_delete(call: types.CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        return
    conn = sqlite3.connect("profithub.db")
    cur = conn.cursor()
    cur.execute("SELECT id, title, base_reward, task_type FROM tasks")
    tasks = cur.fetchall()
    conn.close()

    if not tasks:
        await call.answer("В базе нет активных заданий!", show_alert=True)
        return

    buttons = []
    for t_id, title, rew, t_type in tasks:
        badge = "📢 Подписка" if t_type == "sub" else "💰 CPA"
        buttons.append([InlineKeyboardButton(text=f"🗑 Удалить #{t_id} [{badge}] {title} ({rew}₽)", callback_data=f"deltask_{t_id}")])
    buttons.append([InlineKeyboardButton(text="🔙 Назад в Админ-панель", callback_data="adm_back")])

    await show_screen(
        call.message.chat.id,
        "🗑 <b>УДАЛЕНИЕ ЗАДАНИЙ</b>\nНажмите на задание, чтобы полностью удалить его из базы:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )
    await call.answer()

@dp.callback_query(F.data.startswith("deltask_"))
async def admin_delete_task_confirm(call: types.CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        return
    t_id = int(call.data.split("_")[1])
    conn = sqlite3.connect("profithub.db")
    cur = conn.cursor()
    cur.execute("DELETE FROM tasks WHERE id = ?", (t_id,))
    cur.execute("DELETE FROM completed WHERE task_id = ?", (t_id,))
    conn.commit()
    conn.close()
    await call.answer(f"✅ Задание #{t_id} удалено!", show_alert=True)
    await admin_list_tasks_to_delete(call)

@dp.callback_query(F.data == "adm_broadcast")
async def admin_broadcast_start(call: types.CallbackQuery, state: FSMContext):
    if call.from_user.id != ADMIN_ID:
        return
    await show_screen(
        call.message.chat.id,
        "📨📣 <b>РАССЫЛКА ВСЕМ ПОЛЬЗОВАТЕЛЯМ</b>\n\n"
        "Отправьте в чат текст или фото с подписью, которое нужно разослать по всей базе игроков:",
        reply_markup=admin_cancel_kb()
    )
    await state.set_state(AdminBroadcastFSM.waiting_for_message)
    await call.answer()

@dp.message(AdminBroadcastFSM.waiting_for_message)
async def admin_broadcast_run(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    await state.clear()

    conn = sqlite3.connect("profithub.db")
    cur = conn.cursor()
    cur.execute("SELECT user_id FROM users")
    users = [row[0] for row in cur.fetchall()]
    conn.close()

    sent, failed = 0, 0
    for uid in users:
        try:
            await message.copy_to(chat_id=uid)
            sent += 1
            await asyncio.sleep(0.04)
        except Exception:
            failed += 1

    await delete_user_msg(message)
    await show_screen(
        message.chat.id,
        f"✅📣 <b>РАССЫЛКА УСПЕШНО ЗАВЕРШЕНА!</b>\n\n"
        f"📬 Доставлено: <b>{sent} чел.</b>\n"
        f"🚫 Бот заблокирован: <b>{failed} чел.</b>",
        reply_markup=admin_menu_kb()
    )

@dp.callback_query(F.data == "adm_balance")
async def admin_balance_start(call: types.CallbackQuery, state: FSMContext):
    if call.from_user.id != ADMIN_ID:
        return
    await show_screen(
        call.message.chat.id,
        "💰👤 <b>ИЗМЕНЕНИЕ БАЛАНСА ИГРОКА</b>\n\n"
        "Отправьте в чат <b>Telegram ID</b> пользователя:",
        reply_markup=admin_cancel_kb()
    )
    await state.set_state(AdminBalanceFSM.waiting_for_userid)
    await call.answer()

@dp.message(AdminBalanceFSM.waiting_for_userid)
async def admin_balance_userid(message: types.Message, state: FSMContext):
    await delete_user_msg(message)
    if not message.text.strip().isdigit():
        await show_screen(message.chat.id, "❌ ID должен состоять из цифр. Попробуйте снова:", reply_markup=admin_cancel_kb())
        return
    target_id = int(message.text.strip())
    user = get_user(target_id)
    if not user:
        await show_screen(message.chat.id, "❌ Игрок с таким ID не найден в базе. Введите другой ID:", reply_markup=admin_cancel_kb())
        return

    await state.update_data(target_id=target_id)
    await show_screen(
        message.chat.id,
        f"👤 Игрок: @{user[1]} (ID: <code>{user[0]}</code>)\n"
        f"💳 Текущий баланс: <b>{user[2]:.2f} ₽</b>\n\n"
        f"Введите новую сумму баланса (например: <code>1000</code>) или прибавьте/вычтите со знаком (<code>+500</code> / <code>-200</code>):",
        reply_markup=admin_cancel_kb()
    )
    await state.set_state(AdminBalanceFSM.waiting_for_amount)

@dp.message(AdminBalanceFSM.waiting_for_amount)
async def admin_balance_apply(message: types.Message, state: FSMContext):
    await delete_user_msg(message)
    data = await state.get_data()
    target_id = data["target_id"]
    user = get_user(target_id)
    txt = message.text.strip().replace(",", ".")

    try:
        if txt.startswith("+"):
            new_bal = user[2] + float(txt[1:])
        elif txt.startswith("-"):
            new_bal = max(0.0, user[2] - float(txt[1:]))
        else:
            new_bal = float(txt)
    except ValueError:
        await show_screen(message.chat.id, "❌ Введите корректное число:", reply_markup=admin_cancel_kb())
        return

    conn = sqlite3.connect("profithub.db")
    cur = conn.cursor()
    cur.execute("UPDATE users SET balance = ? WHERE user_id = ?", (new_bal, target_id))
    conn.commit()
    conn.close()
    await state.clear()

    await show_screen(
        message.chat.id,
        f"✅ Баланс игрока <code>{target_id}</code> установлен на <b>{new_bal:.2f} ₽</b>!",
        reply_markup=admin_menu_kb()
    )

@dp.callback_query(F.data.startswith("addtask_"))
async def admin_add_task_start(call: types.CallbackQuery, state: FSMContext):
    if call.from_user.id != ADMIN_ID:
        return
    t_type = call.data.split("_")[1]
    await state.update_data(task_type=t_type)
    await show_screen(
        call.message.chat.id,
        "➕📋 <b>ДОБАВЛЕНИЕ НОВОГО ЗАДАНИЯ (Шаг 1/4)</b>\n\n"
        "Введите <b>название задания</b> (например: <i>Подписка на спонсора</i> или <i>Карта Альфа-Банк + 1500₽</i>):",
        reply_markup=admin_cancel_kb()
    )
    await state.set_state(AdminAddTaskFSM.title)
    await call.answer()

@dp.message(AdminAddTaskFSM.title)
async def admin_task_title(message: types.Message, state: FSMContext):
    await delete_user_msg(message)
    await state.update_data(title=message.text)
    await show_screen(
        message.chat.id,
        "➕📝 <b>ДОБАВЛЕНИЕ ЗАДАНИЯ (Шаг 2/4)</b>\n\nВведите <b>описание условий</b> для пользователя:",
        reply_markup=admin_cancel_kb()
    )
    await state.set_state(AdminAddTaskFSM.description)

@dp.message(AdminAddTaskFSM.description)
async def admin_task_desc(message: types.Message, state: FSMContext):
    await delete_user_msg(message)
    await state.update_data(description=message.text)
    await show_screen(
        message.chat.id,
        "➕🔗 <b>ДОБАВЛЕНИЕ ЗАДАНИЯ (Шаг 3/4)</b>\n\nОтправьте <b>ссылку</b> на канал или вашу CPA-ссылку (начинается с https://):",
        reply_markup=admin_cancel_kb()
    )
    await state.set_state(AdminAddTaskFSM.url)

@dp.message(AdminAddTaskFSM.url)
async def admin_task_url(message: types.Message, state: FSMContext):
    await delete_user_msg(message)
    await state.update_data(url=message.text)
    data = await state.get_data()
    if data["task_type"] == "sub":
        await show_screen(
            message.chat.id,
            "➕📢 <b>ПРОВЕРКА ПОДПИСКИ</b>\n\nВведите <b>@username канала</b> (например, <code>@durov</code>), если бот добавлен туда админом, или отправьте <code>0</code> для зачета по клику:",
            reply_markup=admin_cancel_kb()
        )
        await state.set_state(AdminAddTaskFSM.channel_id)
    else:
        await state.update_data(channel_id="0")
        await show_screen(
            message.chat.id,
            "➕💵 <b>ДОБАВЛЕНИЕ ЗАДАНИЯ (Шаг 4/4)</b>\n\nВведите <b>базовую награду в рублях</b> (например: <code>500</code>):",
            reply_markup=admin_cancel_kb()
        )
        await state.set_state(AdminAddTaskFSM.base_reward)

@dp.message(AdminAddTaskFSM.channel_id)
async def admin_task_chid(message: types.Message, state: FSMContext):
    await delete_user_msg(message)
    await state.update_data(channel_id=message.text.strip())
    await show_screen(
        message.chat.id,
        "➕💵 <b>ДОБАВЛЕНИЕ ЗАДАНИЯ (Шаг 4/4)</b>\n\nВведите <b>базовую награду в рублях</b> за подписку (например: <code>4.0</code>):",
        reply_markup=admin_cancel_kb()
    )
    await state.set_state(AdminAddTaskFSM.base_reward)

@dp.message(AdminAddTaskFSM.base_reward)
async def admin_task_finish(message: types.Message, state: FSMContext):
    await delete_user_msg(message)
    try:
        rew = float(message.text.replace(",", "."))
    except ValueError:
        await show_screen(message.chat.id, "❌ Введите число!", reply_markup=admin_cancel_kb())
        return
    data = await state.get_data()
    conn = sqlite3.connect("profithub.db")
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO tasks (title, description, url, channel_id, base_reward, task_type) VALUES (?, ?, ?, ?, ?, ?)",
        (data["title"], data["description"], data["url"], data["channel_id"], rew, data["task_type"])
    )
    conn.commit()
    conn.close()
    await state.clear()
    await show_screen(
        message.chat.id,
        f"✅🎉 <b>Задание «{data['title']}» опубликовано!</b>\n\n"
        f"💵 Базовая ставка: <b>{rew:.2f} ₽</b>\n"
        f"👑 Ставка для VIP-Агентство (x2.5): <b>{rew * 2.5:.2f} ₽</b>",
        reply_markup=admin_menu_kb()
    )

async def main():
    logging.basicConfig(level=logging.INFO)
    init_db()
    print("🚀 Бот PROFIT-HUB (Clean UI Edition) успешно запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
