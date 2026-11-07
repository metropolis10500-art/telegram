import asyncio
import logging
import sqlite3
import uuid
from datetime import datetime, timedelta
import aiohttp

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

# =====================================================================
# ⚙️ НАСТРОЙКИ БОТА И ПЛАТЕЖНОЙ СИСТЕМЫ ЮMONEY
# =====================================================================
BOT_TOKEN = "9280804384:AAEYyYr2JowksZMfvmXQX9EY2eDm4WpVFug"
ADMIN_IDS = [5494544187]  # Твой Telegram ID (узнать в @userinfobot)
SUPPORT_URL = "https://t.me/vladofix97"  # Ссылка на поддержку/отзывы

YOOMONEY_WALLET = "4100118935779591"  # Номер кошелька ЮMoney
YOOMONEY_TOKEN = "8BE176DEFDE0ED619164EB32845C863D58EDF5A49E9B0416A90FCEE9D298D24D"  # Токен API ЮMoney

# Конфигурация платных статусов (Монетизация)
TIERS = {
    "free": {
        "name": "Базовый",
        "icon": "⚪️",
        "price": 0,
        "multiplier": 1.0,       # Стандартная оплата x1
        "withdraw_fee": 10,      # Комиссия на вывод 10%
        "min_withdraw": 300,     # Мин. вывод 300 ₽
        "ref_percent": 10,       # 10% с дохода рефералов
        "daily_bonus": 3,        # Ежедневный бонус 3 ₽
        "vip_access": False,
    },
    "pro": {
        "name": "PRO Аккаунт",
        "icon": "🔥",
        "price": 490,
        "multiplier": 1.5,       # +50% к оплате за все задания
        "withdraw_fee": 2,       # Комиссия на вывод всего 2%
        "min_withdraw": 150,     # Мин. вывод 150 ₽
        "ref_percent": 20,       # 20% с дохода и покупок рефералов
        "daily_bonus": 15,       # Ежедневный бонус 15 ₽
        "vip_access": True,
    },
    "vip": {
        "name": "VIP Бизнес",
        "icon": "💎",
        "price": 1490,
        "multiplier": 2.0,       # x2.0 оплата за все задания
        "withdraw_fee": 0,       # 0% комиссия на вывод
        "min_withdraw": 50,      # Мин. вывод от 50 ₽
        "ref_percent": 35,       # 35% с дохода и покупок рефералов
        "daily_bonus": 45,       # Ежедневный бонус 45 ₽
        "vip_access": True,
    },
}

DB_PATH = "workhub_bot.db"
router = Router()


# =====================================================================
# 🗄 БАЗА ДАННЫХ И ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# =====================================================================
def fmt(val: float | int) -> str:
    if isinstance(val, float):
        return f"{val:,.2f}".replace(",", " ")
    return f"{val:,}".replace(",", " ")


def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                balance REAL DEFAULT 0.0,
                total_earned REAL DEFAULT 0.0,
                completed_count INTEGER DEFAULT 0,
                tier TEXT DEFAULT 'free',
                tier_until TEXT DEFAULT 'Бессрочно',
                referrer_id INTEGER DEFAULT 0,
                referrals_count INTEGER DEFAULT 0,
                ref_earned REAL DEFAULT 0.0,
                last_bonus_date TEXT DEFAULT '',
                joined_at TEXT
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                creator_id INTEGER,
                title TEXT,
                description TEXT,
                task_type TEXT,          -- 'channel' (автопроверка) или 'link' (по клику/отчету)
                target_url TEXT,         -- ссылка https://t.me/...
                channel_username TEXT,   -- @username канала для проверки подписки
                reward REAL,
                is_vip INTEGER DEFAULT 0,
                remaining_runs INTEGER DEFAULT 100
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS completed_tasks (
                user_id INTEGER,
                task_id INTEGER,
                completed_at TEXT,
                PRIMARY KEY (user_id, task_id)
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS payments (
                label TEXT PRIMARY KEY,
                user_id INTEGER,
                amount REAL,
                status TEXT DEFAULT 'pending',
                created_at TEXT
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS withdrawals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                amount REAL,
                net_amount REAL,
                details TEXT,
                status TEXT DEFAULT 'pending',
                created_at TEXT
            )
        """)

        # Создадим стартовые задания для демонстрации, если таблица пуста
        c.execute("SELECT COUNT(*) FROM tasks")
        if c.fetchone()[0] == 0:
            sample_tasks = [
                (0, "Подписка на новостной канал", "Подпишитесь на канал спонсора и не отписывайтесь минимум 3 дня.", "link", "https://t.me/telegram", "@telegram", 12.0, 0, 500),
                (0, "Просмотр партнерского поста", "Перейдите по ссылке, ознакомьтесь с публикацией и вернитесь в бот для подтверждения.", "link", "https://t.me/durov", "", 8.5, 0, 500),
                (0, "Оценка приложения спонсора", "Перейдите на страницу проекта и нажмите кнопку запуска.", "link", "https://t.me/BotFather", "", 15.0, 0, 300),
                (0, "💎 [VIP] Тестирование крипто-сервиса", "Премиум задание с повышенной ставкой для владельцев статуса PRO и VIP.", "link", "https://t.me/wallet", "", 65.0, 1, 200),
                (0, "💎 [VIP] Отзыв о партнерском проекте", "Ознакомьтесь с презентацией сервиса по ссылке и подтвердите выполнение.", "link", "https://t.me/premium", "", 85.0, 1, 150),
            ]
            c.executemany("""
                INSERT INTO tasks (creator_id, title, description, task_type, target_url, channel_username, reward, is_vip, remaining_runs)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, sample_tasks)
        conn.commit()


def get_user(user_id: int, username: str = "", referrer_id: int = 0) -> dict:
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        row = c.fetchone()
        if not row:
            now = datetime.now().strftime("%d.%m.%Y")
            valid_ref = referrer_id if (referrer_id and referrer_id != user_id) else 0
            c.execute(
                "INSERT INTO users (user_id, username, referrer_id, joined_at) VALUES (?, ?, ?, ?)",
                (user_id, username or "User", valid_ref, now),
            )
            if valid_ref:
                c.execute("UPDATE users SET referrals_count = referrals_count + 1 WHERE user_id = ?", (valid_ref,))
            conn.commit()
            c.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
            row = c.fetchone()
        return dict(row)


def update_user(user_id: int, **kwargs):
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        for k, v in kwargs.items():
            c.execute(f"UPDATE users SET {k} = ? WHERE user_id = ?", (v, user_id))
        conn.commit()


def credit_referrer(user_id: int, base_amount: float):
    """Начисление реферального вознаграждения пригласившему пользователю"""
    u = get_user(user_id)
    ref_id = u.get("referrer_id", 0)
    if not ref_id:
        return
    ref_user = get_user(ref_id)
    tier_cfg = TIERS.get(ref_user["tier"], TIERS["free"])
    bonus = round(base_amount * (tier_cfg["ref_percent"] / 100), 2)
    if bonus > 0:
        update_user(
            ref_id,
            balance=round(ref_user["balance"] + bonus, 2),
            total_earned=round(ref_user["total_earned"] + bonus, 2),
            ref_earned=round(ref_user["ref_earned"] + bonus, 2),
        )


# =====================================================================
# 📋 СОСТОЯНИЯ ВВОДА (FSM)
# =====================================================================
class FormStates(StatesGroup):
    deposit_amount = State()
    withdraw_amount = State()
    withdraw_details = State()
    new_task_title = State()
    new_task_url = State()
    new_task_reward = State()
    new_task_count = State()
    admin_give_bal = State()


# =====================================================================
# 🏠 ГЛАВНОЕ МЕНЮ И ЛИЧНЫЙ КАБИНЕТ
# =====================================================================
def render_main_menu(u: dict) -> tuple[str, InlineKeyboardMarkup]:
    t = TIERS.get(u["tier"], TIERS["free"])
    text = (
        f"💼 <b>ПАНЕЛЬ ЗАРАБОТКА | ЛИЧНЫЙ КАБИНЕТ</b>\n\n"
        f"<blockquote>"
        f"🆔 <b>Ваш ID:</b> <code>{u['user_id']}</code>\n"
        f"💳 <b>Доступный баланс:</b> <code>{fmt(u['balance'])} ₽</code>\n"
        f"📈 <b>Заработано всего:</b> <code>{fmt(u['total_earned'])} ₽</code>\n"
        f"✅ <b>Выполнено заданий:</b> <code>{u['completed_count']}</code>"
        f"</blockquote>\n\n"
        f"👑 <b>Ваш статус:</b> {t['icon']} <b>{t['name']}</b> (до: {u['tier_until']})\n"
        f"├ <b>Множитель дохода:</b> <code>x{t['multiplier']}</code> к каждому заданию\n"
        f"├ <b>Реферальная ставка:</b> <code>{t['ref_percent']}%</code>\n"
        f"├ <b>Ежедневный бонус:</b> <code>+{t['daily_bonus']} ₽</code>\n"
        f"└ <b>Комиссия на вывод:</b> <code>{t['withdraw_fee']}%</code> (от {t['min_withdraw']} ₽)\n\n"
        f"<i>💡 Подключите статус <b>PRO</b> или <b>VIP</b>, чтобы зарабатывать до 2 раз больше за те же действия и выводить средства без комиссии!</i>"
    )

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💸 Заработать на заданиях", callback_data="tasks_list")],
            [
                InlineKeyboardButton(text="🔥 PRO / VIP Привилегии", callback_data="shop_tiers:pro"),
                InlineKeyboardButton(text="🎁 Ежедневный бонус", callback_data="daily_bonus"),
            ],
            [
                InlineKeyboardButton(text="👥 Партнерская сеть", callback_data="referrals"),
                InlineKeyboardButton(text="📢 Разместить задание", callback_data="create_task"),
            ],
            [
                InlineKeyboardButton(text="💳 Пополнить (ЮMoney)", callback_data="deposit_menu"),
                InlineKeyboardButton(text="📤 Вывести деньги", callback_data="withdraw_menu"),
            ],
            [
                InlineKeyboardButton(text="🏆 Топ участников", callback_data="leaderboard"),
                InlineKeyboardButton(text="💬 Поддержка / Отзывы", url=SUPPORT_URL),
            ],
        ]
    )
    return text, kb


@router.message(CommandStart())
async def cmd_start(message: Message, command: CommandObject, state: FSMContext):
    await state.clear()
    ref_id = 0
    if command.args and command.args.startswith("ref_"):
        part = command.args.replace("ref_", "")
        if part.isdigit():
            ref_id = int(part)

    u = get_user(message.from_user.id, message.from_user.username, referrer_id=ref_id)
    text, kb = render_main_menu(u)
    await message.answer(text, reply_markup=kb)


@router.callback_query(F.data == "nav_home")
async def cb_nav_home(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    u = get_user(callback.from_user.id)
    text, kb = render_main_menu(u)
    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()


# =====================================================================
# 💸 БИРЖА ЗАДАНИЙ (С УМНОЖЕНИЕМ ДОХОДА ДЛЯ PRO/VIP)
# =====================================================================
@router.callback_query(F.data == "tasks_list")
async def cb_tasks_list(callback: CallbackQuery):
    u = get_user(callback.from_user.id)
    t = TIERS.get(u["tier"], TIERS["free"])

    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("""
            SELECT * FROM tasks
            WHERE remaining_runs > 0
            AND id NOT IN (SELECT task_id FROM completed_tasks WHERE user_id = ?)
            ORDER BY is_vip DESC, reward DESC LIMIT 10
        """, (callback.from_user.id,))
        available = c.fetchall()

    if not available:
        text = (
            "🎉 <b>Вы выполнили все доступные задания!</b>\n\n"
            "Новые задания от рекламодателей появляются каждый час. "
            "А пока вы можете приглашать друзей по партнерской ссылке и получать до 35% от их дохода!"
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 В личный кабинет", callback_data="nav_home")]])
        await callback.message.edit_text(text, reply_markup=kb)
        await callback.answer()
        return

    buttons = []
    for task in available:
        actual_reward = round(task["reward"] * t["multiplier"], 2)
        vip_tag = "💎 [VIP] " if task["is_vip"] else "⚡️ "
        btn_text = f"{vip_tag}{task['title']} — +{fmt(actual_reward)} ₽"
        buttons.append([InlineKeyboardButton(text=btn_text, callback_data=f"view_task:{task['id']}")])

    buttons.append([InlineKeyboardButton(text="🔥 Увеличить оплату в 2 раза (VIP)", callback_data="shop_tiers:vip")])
    buttons.append([InlineKeyboardButton(text="🔙 В личный кабинет", callback_data="nav_home")])

    text = (
        f"💸 <b>ДОСТУПНЫЕ ЗАДАНИЯ ({len(available)} шт.)</b>\n"
        f"👑 Ваш множитель дохода: <b>x{t['multiplier']} ({t['name']})</b>\n\n"
        f"Выберите задание из списка ниже, выполните условие и получите моментальное зачисление на баланс:"
    )
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()


@router.callback_query(F.data.startswith("view_task:"))
async def cb_view_task(callback: CallbackQuery):
    task_id = int(callback.data.split(":")[1])
    u = get_user(callback.from_user.id)
    t = TIERS.get(u["tier"], TIERS["free"])

    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
        task = c.fetchone()

    if not task or task["remaining_runs"] <= 0:
        await callback.answer("❌ Это задание уже завершено!", show_alert=True)
        await cb_tasks_list(callback)
        return

    if task["is_vip"] and not t["vip_access"]:
        await callback.answer(
            "🔒 Это закрытое высокооплачиваемое VIP-задание! Для доступа подключите статус PRO или VIP.",
            show_alert=True,
        )
        return

    base_r = task["reward"]
    your_r = round(base_r * t["multiplier"], 2)
    vip_r = round(base_r * 2.0, 2)

    text = (
        f"📋 <b>ЗАДАНИЕ #{task['id']}: {task['title']}</b>\n\n"
        f"📝 <b>Инструкция:</b>\n{task['description']}\n\n"
        f"💰 <b>Ваша награда:</b> <code>+{fmt(your_r)} ₽</code> <i>(Базовая: {fmt(base_r)} ₽, с VIP: {fmt(vip_r)} ₽)</i>\n"
        f"⏳ <b>Осталось мест:</b> <code>{task['remaining_runs']}</code>\n\n"
        f"1️⃣ Нажмите <b>«Перейти к выполнению»</b>.\n"
        f"2️⃣ Выполните условие и нажмите <b>«Проверить и получить оплату»</b>."
    )

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔗 1. Перейти к выполнению", url=task["target_url"])],
            [InlineKeyboardButton(text=f"✅ 2. Проверить и получить +{fmt(your_r)} ₽", callback_data=f"check_task:{task['id']}")],
            [InlineKeyboardButton(text="🔙 Назад к списку заданий", callback_data="tasks_list")],
        ]
    )
    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data.startswith("check_task:"))
async def cb_check_task(callback: CallbackQuery):
    task_id = int(callback.data.split(":")[1])
    uid = callback.from_user.id
    u = get_user(uid)
    t = TIERS.get(u["tier"], TIERS["free"])

    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT 1 FROM completed_tasks WHERE user_id = ? AND task_id = ?", (uid, task_id))
        if c.fetchone():
            await callback.answer("✅ Вы уже получили оплату за это задание!", show_alert=True)
            await cb_tasks_list(callback)
            return

        c.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
        task = c.fetchone()

    if not task or task["remaining_runs"] <= 0:
        await callback.answer("❌ Лимит выполнений этого задания исчерпан.", show_alert=True)
        await cb_tasks_list(callback)
        return

    # Если задание требует подписку на канал и указан @username, проверяем через Telegram API
    if task["task_type"] == "channel" and task["channel_username"]:
        try:
            member = await callback.bot.get_chat_member(task["channel_username"], uid)
            if member.status in ("left", "kicked"):
                await callback.answer("❌ Вы еще не подписались на канал! Подпишитесь и нажмите проверку снова.", show_alert=True)
                return
        except Exception:
            # Если бот еще не добавлен в админы проверяемого канала — пропускаем по клику
            pass

    reward = round(task["reward"] * t["multiplier"], 2)
    now_str = datetime.now().strftime("%d.%m.%Y %H:%M")

    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("INSERT INTO completed_tasks (user_id, task_id, completed_at) VALUES (?, ?, ?)", (uid, task_id, now_str))
        c.execute("UPDATE tasks SET remaining_runs = remaining_runs - 1 WHERE id = ?", (task_id,))
        conn.commit()

    update_user(
        uid,
        balance=round(u["balance"] + reward, 2),
        total_earned=round(u["total_earned"] + reward, 2),
        completed_count=u["completed_count"] + 1,
    )
    credit_referrer(uid, reward)

    await callback.answer(f"🎉 Задание выполнено! На ваш баланс зачислено +{fmt(reward)} ₽", show_alert=True)
    await cb_tasks_list(callback)


# =====================================================================
# 🔥 МАГАЗИН ПЛАТНЫХ ФУНКЦИЙ (PRO / VIP ТАРИФЫ)
# =====================================================================
@router.callback_query(F.data.startswith("shop_tiers:"))
async def cb_shop_tiers(callback: CallbackQuery):
    selected = callback.data.split(":")[1]
    t = TIERS[selected]
    u = get_user(callback.from_user.id)

    text = (
        f"💎 <b>МАГАЗИН ПЛАТНЫХ ПРИВИЛЕГИЙ</b>\n"
        f"💳 Ваш баланс: <code>{fmt(u['balance'])} ₽</code>\n\n"
        f"{t['icon']} <b>Тариф «{t['name']}» — {fmt(t['price'])} ₽ / 30 дней</b>\n\n"
        f"<b>Преимущества статуса:</b>\n"
        f"✅ <b>Множитель заработка x{t['multiplier']}</b> (+{int((t['multiplier']-1)*100)}% за каждое задание)\n"
        f"✅ <b>Доступ к закрытым VIP-заданиям</b> (до 150 ₽ за 1 задание)\n"
        f"✅ <b>Комиссия на вывод: {t['withdraw_fee']}%</b> (вместо 10%)\n"
        f"✅ <b>Минимальная сумма вывода: от {t['min_withdraw']} ₽</b>\n"
        f"✅ <b>Повышенный реферальный доход: {t['ref_percent']}%</b>\n"
        f"✅ <b>Ежедневный бонус: +{t['daily_bonus']} ₽ каждый день</b>\n\n"
        f"<i>Окупаемость статуса при активной работе составляет 1–3 дня!</i>"
    )

    tab_row = [
        InlineKeyboardButton(
            text=f"{'🔘' if selected == 'pro' else '⚪️'} 🔥 PRO (490 ₽)",
            callback_data="shop_tiers:pro",
        ),
        InlineKeyboardButton(
            text=f"{'🔘' if selected == 'vip' else '⚪️'} 💎 VIP Бизнес (1 490 ₽)",
            callback_data="shop_tiers:vip",
        ),
    ]

    if u["tier"] == selected:
        buy_btn = InlineKeyboardButton(text=f"✅ Статус «{t['name']}» уже активен", callback_data="noop")
    elif u["balance"] < t["price"]:
        diff = int(t["price"] - u["balance"]) + 1
        buy_btn = InlineKeyboardButton(
            text=f"💳 Пополнить и подключить ({fmt(t['price'])} ₽)",
            callback_data=f"fast_pay:{t['price']}",
        )
    else:
        buy_btn = InlineKeyboardButton(
            text=f"🚀 Активировать «{t['name']}» за {fmt(t['price'])} ₽",
            callback_data=f"activate_tier:{selected}",
        )

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            tab_row,
            [buy_btn],
            [InlineKeyboardButton(text="🔙 В личный кабинет", callback_data="nav_home")],
        ]
    )
    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data.startswith("activate_tier:"))
async def cb_activate_tier(callback: CallbackQuery):
    t_key = callback.data.split(":")[1]
    t = TIERS[t_key]
    u = get_user(callback.from_user.id)

    if u["balance"] < t["price"]:
        await callback.answer("❌ Недостаточно средств на балансе!", show_alert=True)
        return

    until_str = (datetime.now() + timedelta(days=30)).strftime("%d.%m.%Y")
    update_user(
        callback.from_user.id,
        balance=round(u["balance"] - t["price"], 2),
        tier=t_key,
        tier_until=until_str,
    )
    credit_referrer(callback.from_user.id, t["price"])
    await callback.answer(f"🎉 Статус «{t['name']}» успешно активирован на 30 дней!", show_alert=True)
    await cb_nav_home(callback, state=None)


# =====================================================================
# 🎁 ЕЖЕДНЕВНЫЙ БОНУС И 👥 ПАРТНЕРСКАЯ ПРОГРАММА
# =====================================================================
@router.callback_query(F.data == "daily_bonus")
async def cb_daily_bonus(callback: CallbackQuery):
    u = get_user(callback.from_user.id)
    today = datetime.now().strftime("%Y-%m-%d")

    if u["last_bonus_date"] == today:
        await callback.answer("⏳ Вы уже получали бонус сегодня! Возвращайтесь завтра.", show_alert=True)
        return

    t = TIERS.get(u["tier"], TIERS["free"])
    bonus = t["daily_bonus"]
    update_user(
        callback.from_user.id,
        balance=round(u["balance"] + bonus, 2),
        total_earned=round(u["total_earned"] + bonus, 2),
        last_bonus_date=today,
    )
    await callback.answer(f"🎁 Ежедневный бонус +{bonus} ₽ зачислен на ваш баланс!", show_alert=True)
    await cb_nav_home(callback, state=None)


@router.callback_query(F.data == "referrals")
async def cb_referrals(callback: CallbackQuery):
    u = get_user(callback.from_user.id)
    t = TIERS.get(u["tier"], TIERS["free"])
    bot_info = await callback.bot.get_me()
    ref_link = f"https://t.me/{bot_info.username}?start=ref_{u['user_id']}"

    text = (
        f"👥 <b>ПАРТНЕРСКАЯ ПРОГРАММА</b>\n\n"
        f"Приглашайте друзей и получайте пассивный доход от каждого выполненного ими задания и каждой покупки платного статуса!\n\n"
        f"<blockquote>"
        f"👑 <b>Ваш реферальный процент:</b> <code>{t['ref_percent']}%</code> ({t['name']})\n"
        f"👤 <b>Приглашено партнеров:</b> <code>{u['referrals_count']} чел.</code>\n"
        f"💰 <b>Заработано на партнерах:</b> <code>{fmt(u['ref_earned'])} ₽</code>"
        f"</blockquote>\n\n"
        f"🔗 <b>Ваша персональная ссылка для приглашений:</b>\n"
        f"<code>{ref_link}</code>\n\n"
        f"<i>📈 На тарифе PRO вы получаете 20%, а на тарифе VIP Бизнес — целых 35% от всех доходов и оплат ваших рефералов!</i>"
    )
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔥 Повысить процент до 35%", callback_data="shop_tiers:vip")],
            [InlineKeyboardButton(text="🔙 В личный кабинет", callback_data="nav_home")],
        ]
    )
    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()


# =====================================================================
# 📢 КАБИНЕТ РЕКЛАМОДАТЕЛЯ (СОЗДАНИЕ СВОИХ ЗАДАНИЙ)
# =====================================================================
@router.callback_query(F.data == "create_task")
async def cb_create_task(callback: CallbackQuery, state: FSMContext):
    await state.set_state(FormStates.new_task_title)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Отмена", callback_data="nav_home")]])
    await callback.message.edit_text(
        "📢 <b>СОЗДАНИЕ РЕКЛАМНОГО ЗАДАНИЯ (Шаг 1 из 4)</b>\n\n"
        "Хотите раскрутить свой Telegram-канал, бота или проект? Создайте задание для тысяч наших исполнителей!\n\n"
        "✍️ <b>Введите краткое название задания</b> (например: <i>Подписка на крипто-канал</i>):",
        reply_markup=kb,
    )
    await callback.answer()


@router.message(FormStates.new_task_title)
async def msg_task_title(message: Message, state: FSMContext):
    await state.update_data(title=message.text[:60])
    await state.set_state(FormStates.new_task_url)
    await message.answer(
        "🔗 <b>Шаг 2 из 4: Отправьте ссылку</b> на ваш канал, пост или сайт (начинается с <code>https://</code>):"
    )


@router.message(FormStates.new_task_url)
async def msg_task_url(message: Message, state: FSMContext):
    if not message.text or not message.text.startswith("http"):
        await message.answer("❌ Ссылка должна начинаться с <code>https://</code>. Попробуйте еще раз:")
        return
    await state.update_data(url=message.text.strip())
    await state.set_state(FormStates.new_task_reward)
    await message.answer("💵 <b>Шаг 3 из 4: Введите оплату исполнителю за 1 выполнение в рублях</b> (минимум 5 ₽):")


@router.message(FormStates.new_task_reward)
async def msg_task_reward(message: Message, state: FSMContext):
    if not message.text or not message.text.isdigit() or int(message.text) < 5:
        await message.answer("❌ Минимальная цена за выполнение — 5 ₽. Введите целое число:")
        return
    await state.update_data(reward=float(message.text))
    await state.set_state(FormStates.new_task_count)
    await message.answer("👥 <b>Шаг 4 из 4: Сколько выполнений вам нужно?</b> (минимум 10):")


@router.message(FormStates.new_task_count)
async def msg_task_count(message: Message, state: FSMContext):
    if not message.text or not message.text.isdigit() or int(message.text) < 10:
        await message.answer("❌ Минимальный заказ — 10 выполнений. Введите число:")
        return

    count = int(message.text)
    data = await state.get_data()
    total_cost = round(data["reward"] * count, 2)
    u = get_user(message.from_user.id)

    await state.clear()
    if u["balance"] < total_cost:
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text=f"💳 Пополнить баланс на {fmt(total_cost)} ₽", callback_data=f"fast_pay:{int(total_cost)}")],
                [InlineKeyboardButton(text="🔙 В личный кабинет", callback_data="nav_home")],
            ]
        )
        await message.answer(
            f"⚠️ <b>Недостаточно средств для запуска кампании!</b>\n"
            f"Стоимость {count} выполнений по {data['reward']} ₽ составляет <b>{fmt(total_cost)} ₽</b>.\n"
            f"Ваш баланс: <code>{fmt(u['balance'])} ₽</code>",
            reply_markup=kb,
        )
        return

    update_user(message.from_user.id, balance=round(u["balance"] - total_cost, 2))
    with sqlite3.connect(DB_PATH) as conn:
        conn.cursor().execute(
            """INSERT INTO tasks (creator_id, title, description, task_type, target_url, channel_username, reward, is_vip, remaining_runs)
               VALUES (?, ?, 'Перейдите по ссылке рекламодателя и выполните целевое действие.', 'link', ?, '', ?, 0, ?)""",
            (message.from_user.id, data["title"], data["url"], data["reward"], count),
        )
        conn.commit()

    u = get_user(message.from_user.id)
    text, kb = render_main_menu(u)
    await message.answer(f"✅ <b>Ваше задание «{data['title']}» успешно размещено на {count} выполнений!</b>")
    await message.answer(text, reply_markup=kb)


# =====================================================================
# 💳 ПОПОЛНЕНИЕ БАЛАНСА (ЮMONEY) И 📤 ВЫВОД СРЕДСТВ
# =====================================================================
@router.callback_query(F.data == "deposit_menu")
async def cb_deposit_menu(callback: CallbackQuery, state: FSMContext):
    await state.set_state(FormStates.deposit_amount)
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🔥 490 ₽ (Тариф PRO)", callback_data="fast_pay:490"),
                InlineKeyboardButton(text="💎 1 490 ₽ (Тариф VIP)", callback_data="fast_pay:1490"),
            ],
            [InlineKeyboardButton(text="🔙 В личный кабинет", callback_data="nav_home")],
        ]
    )
    await callback.message.edit_text(
        "💳 <b>ПОПОЛНЕНИЕ БАЛАНСА (ЮMoney / Карта РФ)</b>\n\n"
        "Выберите сумму быстрого пополнения кнопкой ниже или напишите любую сумму в чат (от 100 ₽):",
        reply_markup=kb,
    )
    await callback.answer()


async def send_yoomoney_invoice(message_or_cb, user_id: int, amount: int):
    label = f"wh_{user_id}_{uuid.uuid4().hex[:8]}"
    now = datetime.now().strftime("%d.%m.%Y %H:%M")

    with sqlite3.connect(DB_PATH) as conn:
        conn.cursor().execute(
            "INSERT INTO payments (label, user_id, amount, status, created_at) VALUES (?, ?, ?, 'pending', ?)",
            (label, user_id, amount, now),
        )
        conn.commit()

    pay_url = (
        f"https://yoomoney.ru/quickpay/confirm.xml?"
        f"receiver={YOOMONEY_WALLET}&quickpay-form=shop&targets=Пополнение+баланса+{label}&"
        f"paymentType=AC&sum={amount}&label={label}"
    )

    text = (
        f"🧾 <b>СЧЕТ НА ПОПОЛНЕНИЕ #{label.upper()}</b>\n\n"
        f"💰 <b>Сумма к оплате:</b> <code>{fmt(amount)} ₽</code>\n"
        f"💳 <b>Метод оплаты:</b> Банковская карта / ЮMoney\n\n"
        f"1. Нажмите кнопку <b>«Оплатить счет»</b> ниже.\n"
        f"2. После завершения оплаты нажмите <b>«Проверить платеж»</b> — баланс пополнится автоматически."
    )
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=f"🔗 Оплатить счет ({fmt(amount)} ₽)", url=pay_url)],
            [InlineKeyboardButton(text="🔄 Проверить платеж", callback_data=f"chk_pay:{label}")],
            [InlineKeyboardButton(text="🔙 В личный кабинет", callback_data="nav_home")],
        ]
    )

    if isinstance(message_or_cb, CallbackQuery):
        await message_or_cb.message.edit_text(text, reply_markup=kb)
    else:
        await message_or_cb.answer(text, reply_markup=kb)


@router.callback_query(F.data.startswith("fast_pay:"))
async def cb_fast_pay(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    amount = int(callback.data.split(":")[1])
    await send_yoomoney_invoice(callback, callback.from_user.id, amount)
    await callback.answer()


@router.message(FormStates.deposit_amount)
async def msg_deposit_amount(message: Message, state: FSMContext):
    if not message.text or not message.text.isdigit() or int(message.text) < 100:
        await message.answer("❌ Минимальная сумма пополнения — 100 ₽. Введите число:")
        return
    await state.clear()
    await send_yoomoney_invoice(message, message.from_user.id, int(message.text))


@router.callback_query(F.data.startswith("chk_pay:"))
async def cb_chk_pay(callback: CallbackQuery):
    label = callback.data.split(":")[1]
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT * FROM payments WHERE label = ?", (label,))
        pay = c.fetchone()

    if not pay or pay["status"] == "paid":
        await callback.answer("✅ Этот платеж уже зачислен!", show_alert=True)
        return

    headers = {
        "Authorization": f"Bearer {YOOMONEY_TOKEN}",
        "Content-Type": "application/x-www-form-urlencoded",
    }
    paid = False
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://yoomoney.ru/api/operation-history",
                headers=headers,
                data={"label": label},
                timeout=8,
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    paid = any(op.get("status") == "success" for op in data.get("operations", []))
    except Exception:
        paid = False

    if paid:
        u = get_user(callback.from_user.id)
        with sqlite3.connect(DB_PATH) as conn:
            c = conn.cursor()
            c.execute("UPDATE payments SET status = 'paid' WHERE label = ?", (label,))
            c.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (pay["amount"], callback.from_user.id))
            conn.commit()
        await callback.answer(f"🎉 Оплата получена! Ваш баланс пополнен на +{fmt(pay['amount'])} ₽", show_alert=True)
        await cb_nav_home(callback, state=None)
    else:
        await callback.answer("⏳ Оплата еще не найдена. Подождите 15 секунд и повторите проверку.", show_alert=True)


# ================= ВЫВОД СРЕДСТВ С МОДЕРАЦИЕЙ АДМИНА =================
@router.callback_query(F.data == "withdraw_menu")
async def cb_withdraw_menu(callback: CallbackQuery, state: FSMContext):
    u = get_user(callback.from_user.id)
    t = TIERS.get(u["tier"], TIERS["free"])

    if u["balance"] < t["min_withdraw"]:
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="💎 Снизить лимит вывода до 50 ₽ (VIP)", callback_data="shop_tiers:vip")],
                [InlineKeyboardButton(text="🔙 В личный кабинет", callback_data="nav_home")],
            ]
        )
        await callback.message.edit_text(
            f"📤 <b>ВЫВОД СРЕДСТВ</b>\n\n"
            f"💳 Ваш баланс: <code>{fmt(u['balance'])} ₽</code>\n"
            f"⚠️ Минимальная сумма вывода на вашем тарифе ({t['name']}): <b>{t['min_withdraw']} ₽</b>\n\n"
            f"<i>Выполните еще несколько заданий или подключите статус PRO / VIP для снижения минимального порога и 0% комиссии!</i>",
            reply_markup=kb,
        )
        await callback.answer()
        return

    await state.set_state(FormStates.withdraw_amount)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Отмена", callback_data="nav_home")]])
    await callback.message.edit_text(
        f"📤 <b>ЗАЯВКА НА ВЫВОД СРЕДСТВ</b>\n\n"
        f"💳 Доступно: <code>{fmt(u['balance'])} ₽</code>\n"
        f"📉 Комиссия шлюза ({t['name']}): <code>{t['withdraw_fee']}%</code>\n\n"
        f"Введите сумму для вывода (от {t['min_withdraw']} ₽):",
        reply_markup=kb,
    )
    await callback.answer()


@router.message(FormStates.withdraw_amount)
async def msg_withdraw_amount(message: Message, state: FSMContext):
    u = get_user(message.from_user.id)
    t = TIERS.get(u["tier"], TIERS["free"])

    if not message.text or not message.text.isdigit():
        await message.answer("❌ Введите сумму целым числом:")
        return

    amt = float(message.text)
    if amt < t["min_withdraw"] or amt > u["balance"]:
        await message.answer(f"❌ Введите сумму от {t['min_withdraw']} до {fmt(u['balance'])} ₽:")
        return

    await state.update_data(wd_amount=amt)
    await state.set_state(FormStates.withdraw_details)
    await message.answer("💳 <b>Укажите реквизиты для выплаты</b> (номер карты РФ, СБП + банк или кошелек ЮMoney):")


@router.message(FormStates.withdraw_details)
async def msg_withdraw_details(message: Message, state: FSMContext):
    data = await state.get_data()
    amt = data["wd_amount"]
    details = (message.text or "").strip()
    u = get_user(message.from_user.id)
    t = TIERS.get(u["tier"], TIERS["free"])

    await state.clear()
    if u["balance"] < amt:
        await message.answer("❌ Недостаточно средств на балансе.")
        return

    net_amt = round(amt * (1 - t["withdraw_fee"] / 100), 2)
    now = datetime.now().strftime("%d.%m.%Y %H:%M")
    update_user(message.from_user.id, balance=round(u["balance"] - amt, 2))

    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute(
            "INSERT INTO withdrawals (user_id, amount, net_amount, details, status, created_at) VALUES (?, ?, ?, ?, 'pending', ?)",
            (message.from_user.id, amt, net_amt, details, now),
        )
        wd_id = c.lastrowid
        conn.commit()

    # Отправляем интерактивную карточку администраторам
    adm_kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Подтвердить выплату", callback_data=f"adm_wd:ok:{wd_id}"),
                InlineKeyboardButton(text="❌ Отклонить (вернуть)", callback_data=f"adm_wd:reject:{wd_id}"),
            ]
        ]
    )
    for adm in ADMIN_IDS:
        try:
            await message.bot.send_message(
                adm,
                f"📤 <b>Заявка на вывод #{wd_id}</b>\n"
                f"👤 Пользователь: @{u['username']} (<code>{u['user_id']}</code>)\n"
                f"👑 Статус: {t['name']}\n"
                f"💰 Списано: {fmt(amt)} ₽ | <b>К выплате: {fmt(net_amt)} ₽</b>\n"
                f"💳 Реквизиты: <code>{details}</code>",
                reply_markup=adm_kb,
            )
        except Exception:
            pass

    u = get_user(message.from_user.id)
    text, kb = render_main_menu(u)
    await message.answer(
        f"✅ <b>Заявка на вывод #{wd_id} создана!</b>\n"
        f"Сумма к зачислению на ваши реквизиты: <b>{fmt(net_amt)} ₽</b>.\n"
        f"Вы получите уведомление сразу после обработки оператором."
    )
    await message.answer(text, reply_markup=kb)


# =====================================================================
# 🏆 ТОП УЧАСТНИКОВ (СОЦИАЛЬНОЕ ДОКАЗАТЕЛЬСТВО ДЛЯ ДОВЕРИЯ)
# =====================================================================
@router.callback_query(F.data == "leaderboard")
async def cb_leaderboard(callback: CallbackQuery):
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT * FROM users ORDER BY total_earned DESC LIMIT 10")
        rows = c.fetchall()

    medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
    lines = []
    for idx, r in enumerate(rows):
        t_icon = TIERS.get(r["tier"], TIERS["free"])["icon"]
        masked_id = str(r["user_id"])[:4] + "***"
        lines.append(
            f"{medals[idx]} {t_icon} <b>ID {masked_id}</b> — Заработано: <code>{fmt(r['total_earned'])} ₽</code> ({r['completed_count']} заданий)"
        )

    text = (
        "🏆 <b>ТОП-10 ИСПОЛНИТЕЛЕЙ ПЛАТФОРМЫ</b>\n"
        "<i>Самые активные участники, зарабатывающие с повышенными коэффициентами PRO и VIP:</i>\n\n"
        + "\n".join(lines)
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 В личный кабинет", callback_data="nav_home")]])
    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data == "noop")
async def cb_noop(callback: CallbackQuery):
    await callback.answer("Этот статус уже подключен на вашем аккаунте!")


# =====================================================================
# 👑 АДМИН-ПАНЕЛЬ (/admin) И ОБРАБОТКА ВЫПЛАТ
# =====================================================================
@router.message(Command("admin"))
async def cmd_admin(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        return

    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        users_cnt = c.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        vip_cnt = c.execute("SELECT COUNT(*) FROM users WHERE tier != 'free'").fetchone()[0]
        tasks_cnt = c.execute("SELECT COUNT(*) FROM tasks WHERE remaining_runs > 0").fetchone()[0]
        deps_sum = c.execute("SELECT COALESCE(SUM(amount), 0) FROM payments WHERE status = 'paid'").fetchone()[0]

    text = (
        "👑 <b>ПАНЕЛЬ УПРАВЛЕНИЯ ПРОЕКТОМ</b>\n\n"
        f"👥 Всего пользователей: <b>{users_cnt}</b>\n"
        f"💎 Активных PRO/VIP: <b>{vip_cnt}</b>\n"
        f"📋 Активных заданий: <b>{tasks_cnt}</b>\n"
        f"💰 Оплачено через ЮMoney: <b>{fmt(deps_sum)} ₽</b>"
    )
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💵 Начислить баланс пользователю", callback_data="adm_add_bal")],
            [InlineKeyboardButton(text="🔙 В главное меню", callback_data="nav_home")],
        ]
    )
    await message.answer(text, reply_markup=kb)


@router.callback_query(F.data == "adm_add_bal")
async def cb_adm_add_bal(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        return
    await state.set_state(FormStates.admin_give_bal)
    await callback.message.edit_text("Введите <code>ID_пользователя Сумму</code> через пробел (например: <code>123456789 500</code>):")


@router.message(FormStates.admin_give_bal)
async def msg_adm_give_bal(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return
    parts = (message.text or "").split()
    if len(parts) == 2 and parts[0].isdigit():
        uid, amt = int(parts[0]), float(parts[1])
        u = get_user(uid)
        update_user(uid, balance=round(u["balance"] + amt, 2))
        await state.clear()
        await message.answer(f"✅ Баланс пользователя <code>{uid}</code> пополнен на <b>{fmt(amt)} ₽</b>!")
    else:
        await message.answer("❌ Неверный формат. Введите ID и сумму через пробел.")


@router.callback_query(F.data.startswith("adm_wd:"))
async def cb_adm_withdraw_decision(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return
    _, action, wd_id_str = callback.data.split(":")
    wd_id = int(wd_id_str)

    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT * FROM withdrawals WHERE id = ?", (wd_id,))
        wd = c.fetchone()

        if not wd or wd["status"] != "pending":
            await callback.answer("Заявка уже обработана!", show_alert=True)
            return

        if action == "ok":
            c.execute("UPDATE withdrawals SET status = 'paid' WHERE id = ?", (wd_id,))
            conn.commit()
            try:
                await callback.bot.send_message(
                    wd["user_id"],
                    f"✅ <b>Ваша заявка на вывод #{wd_id} исполнена!</b>\n"
                    f"Сумма <b>{fmt(wd['net_amount'])} ₽</b> отправлена на реквизиты <code>{wd['details']}</code>.",
                )
            except Exception:
                pass
            await callback.message.edit_text(callback.message.text + "\n\n✅ <b>СТАТУС: ВЫПЛАЧЕНО</b>")
        else:
            c.execute("UPDATE withdrawals SET status = 'rejected' WHERE id = ?", (wd_id,))
            c.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (wd["amount"], wd["user_id"]))
            conn.commit()
            try:
                await callback.bot.send_message(
                    wd["user_id"],
                    f"❌ <b>Заявка на вывод #{wd_id} отклонена оператором.</b>\n"
                    f"Средства в размере <b>{fmt(wd['amount'])} ₽</b> возвращены на ваш баланс. Проверьте корректность реквизитов.",
                )
            except Exception:
                pass
            await callback.message.edit_text(callback.message.text + "\n\n❌ <b>СТАТУС: ОТКЛОНЕНО (Возврат на баланс)</b>")


# =====================================================================
# 🏁 ЗАПУСК БОТА
# =====================================================================
async def main():
    logging.basicConfig(level=logging.INFO)
    init_db()
    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    dp.include_router(router)
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
