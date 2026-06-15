import asyncio
import logging
import os
import uuid
import random
from datetime import datetime, timedelta
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.client.default import DefaultBotProperties
import aiosqlite

load_dotenv()

# ============================================================
# КОНФИГУРАЦИЯ
# ============================================================
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
YOOMONEY_WALLET = os.getenv("YOOMONEY_WALLET")
YOOMONEY_TOKEN = os.getenv("YOOMONEY_TOKEN")
DB_PATH = "autogram.db"

# ============================================================
# ЭКОНОМИКА
# ============================================================
NEURONS_PER_RUB = 100
MIN_WITHDRAW_RUB = 3000  # Минимум 3000₽
WITHDRAW_FEE_PERCENT = 15  # Комиссия 15%

# Тарифы пополнения (от 1000₽ — серьёзные инвестиции)
DEPOSIT_PACKAGES = {
    "1000":  {"neurons": 80000,    "bonus": 0,      "label": "Стартовый",  "desc": "Идеально для старта"},
    "3000":  {"neurons": 270000,   "bonus": 30000,  "label": "Базовый",    "desc": "Окупаемость за 1 день"},
    "5000":  {"neurons": 500000,   "bonus": 100000, "label": "Стандарт",   "desc": "+20% бонус"},
    "10000": {"neurons": 1100000,  "bonus": 300000, "label": "Профи",      "desc": "+27% бонус"},
    "30000": {"neurons": 3600000,  "bonus": 1200000,"label": "Бизнес",     "desc": "+33% бонус + VIP"},
    "50000": {"neurons": 6500000,  "bonus": 2500000,"label": "VIP",        "desc": "+38% бонус + Premium"},
    "100000":{"neurons": 15000000, "bonus": 7000000,"label": "PREMIUM",    "desc": "+46% бонус + Premium+"}
}

# Серверы (доходность психологически завышена)
SERVERS = {
    "raspberry":  {"name": "🍓 Raspberry Pi",        "price": 5000,        "income": 80,      "icon": "🍓", "desc": "Идеален для старта"},
    "laptop":     {"name": "💻 Игровой ноутбук",     "price": 50000,       "income": 900,     "icon": "💻", "desc": "Стабильный доход"},
    "pc":         {"name": "🖥 Игровой ПК",          "price": 500000,      "income": 10000,   "icon": "🖥", "desc": "Серьёзная машина"},
    "server":     {"name": "🗄 Серверная стойка",    "price": 5000000,     "income": 120000,  "icon": "🗄", "desc": "Для опытных"},
    "gpu":        {"name": "⚡ RTX 4090 Cluster",    "price": 50000000,    "income": 1500000, "icon": "⚡", "desc": "Мощь NVIDIA"},
    "datacenter": {"name": "🏢 Дата-центр",          "price": 500000000,   "income": 18000000,"icon": "🏢", "desc": "Уровень корпорации"},
    "quantum":    {"name": "🔮 Квантовый компьютер", "price": 5000000000,  "income": 220000000,"icon": "🔮", "desc": "Технологии будущего"}
}

# Сотрудники
EMPLOYEES = {
    "junior":   {"name": "👨‍💻 Junior Data Scientist",  "price": 10000,     "multiplier": 1.5,  "icon": "👨‍💻"},
    "middle":   {"name": "👩‍💻 Middle ML Engineer",     "price": 200000,    "multiplier": 2.0,  "icon": "👩‍💻"},
    "senior":   {"name": "🧑‍💻 Senior AI Architect",   "price": 3000000,   "multiplier": 3.0,  "icon": "🧑‍💻"},
    "lead":     {"name": "🎯 Lead AI Researcher",      "price": 50000000,  "multiplier": 5.0,  "icon": "🎯"},
    "cto":      {"name": "🤖 CTO с ИИ-усилителем",     "price": 1000000000,"multiplier": 10.0, "icon": "🤖"}
}

# Улучшения
UPGRADES = {
    "cooling":  {"name": "❄️ Система охлаждения",   "price": 30000,      "multiplier": 1.20, "desc": "+20% к доходу навсегда"},
    "net":      {"name": "🌐 Оптимизация сети",     "price": 500000,     "multiplier": 1.30, "desc": "+30% к доходу навсегда"},
    "quantum":  {"name": "⚛️ Квантовая оптимизация","price": 10000000,   "multiplier": 1.50, "desc": "+50% к доходу навсегда"},
    "neural":   {"name": "🧠 Нейроинтерфейс",       "price": 250000000,  "multiplier": 2.00, "desc": "+100% к доходу навсегда"}
}

# Реферальная система
REF_LEVELS = {1: 10, 2: 5, 3: 2}  # Увеличены проценты
REF_BONUS_NEURONS = 5000  # Больше бонус за реферала

# Ежедневный бонус
DAILY_BONUS = [500, 1000, 2500, 5000, 10000, 25000, 50000, 100000, 250000, 500000]

# ============================================================
# БАЗА ДАННЫХ
# ============================================================
async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                neurons INTEGER DEFAULT 1000,
                total_deposited REAL DEFAULT 0,
                total_withdrawn REAL DEFAULT 0,
                total_earned INTEGER DEFAULT 0,
                total_spent INTEGER DEFAULT 0,
                referrer_id INTEGER,
                reg_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_bonus_date TEXT,
                bonus_streak INTEGER DEFAULT 0
            )
        ''')
        await db.execute('''
            CREATE TABLE IF NOT EXISTS user_servers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                server_type TEXT
            )
        ''')
        await db.execute('''
            CREATE TABLE IF NOT EXISTS user_employees (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                emp_type TEXT
            )
        ''')
        await db.execute('''
            CREATE TABLE IF NOT EXISTS user_upgrades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                upgrade_type TEXT,
                UNIQUE(user_id, upgrade_type)
            )
        ''')
        await db.execute('''
            CREATE TABLE IF NOT EXISTS withdrawals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                amount_rub REAL,
                neurons_amount INTEGER,
                wallet TEXT,
                bank TEXT,
                status TEXT DEFAULT 'pending',
                request_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        await db.execute('''
            CREATE TABLE IF NOT EXISTS deposits (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                amount_rub REAL,
                neurons_amount INTEGER,
                label TEXT UNIQUE,
                status TEXT DEFAULT 'pending',
                created TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        await db.execute('''
            CREATE TABLE IF NOT EXISTS referrals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                level INTEGER,
                referral_id INTEGER,
                UNIQUE(user_id, level, referral_id)
            )
        ''')
        await db.commit()

async def get_user(user_id):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        return await cur.fetchone()

async def add_user(user_id, username, first_name, referrer_id=None):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,))
        exists = await cur.fetchone()
        if not exists:
            await db.execute(
                "INSERT INTO users (user_id, username, first_name, referrer_id) VALUES (?, ?, ?, ?)",
                (user_id, username or "", first_name or "Игрок", referrer_id)
            )
            if referrer_id and referrer_id != user_id:
                # Бонус рефереру
                await db.execute(
                    "UPDATE users SET neurons = neurons + ? WHERE user_id = ?",
                    (REF_BONUS_NEURONS, referrer_id)
                )
                # Записываем связи
                cur2 = await db.execute("SELECT referrer_id FROM users WHERE user_id = ?", (referrer_id,))
                ref2 = await cur2.fetchone()
                if ref2 and ref2[0]:
                    cur3 = await db.execute("SELECT referrer_id FROM users WHERE user_id = ?", (ref2[0],))
                    ref3 = await cur3.fetchone()
                    if ref3 and ref3[0]:
                        await db.execute(
                            "INSERT OR IGNORE INTO referrals (user_id, level, referral_id) VALUES (?, ?, ?)",
                            (ref3[0], 3, user_id)
                        )
                await db.execute(
                    "INSERT OR IGNORE INTO referrals (user_id, level, referral_id) VALUES (?, ?, ?)",
                    (referrer_id, 1, user_id)
                )
                if ref2 and ref2[0] and ref2[0] != user_id:
                    await db.execute(
                        "INSERT OR IGNORE INTO referrals (user_id, level, referral_id) VALUES (?, ?, ?)",
                        (ref2[0], 2, user_id)
                    )
        await db.commit()

async def update_balance(user_id, delta):
    async with aiosqlite.connect(DB_PATH) as db:
        if delta > 0:
            await db.execute(
                "UPDATE users SET neurons = neurons + ?, total_earned = total_earned + ? WHERE user_id = ?",
                (delta, delta, user_id)
            )
        else:
            await db.execute(
                "UPDATE users SET neurons = neurons + ?, total_spent = total_spent + ? WHERE user_id = ?",
                (delta, abs(delta), user_id)
            )
        await db.commit()

async def get_user_servers(user_id):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT server_type, COUNT(*) FROM user_servers WHERE user_id = ? GROUP BY server_type",
            (user_id,)
        )
        return dict(await cur.fetchall())

async def get_user_employees(user_id):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT emp_type, COUNT(*) FROM user_employees WHERE user_id = ? GROUP BY emp_type",
            (user_id,)
        )
        return dict(await cur.fetchall())

async def get_user_upgrades(user_id):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT upgrade_type FROM user_upgrades WHERE user_id = ?",
            (user_id,)
        )
        return set(row[0] for row in await cur.fetchall())

async def calculate_income(user_id):
    servers = await get_user_servers(user_id)
    employees = await get_user_employees(user_id)
    upgrades = await get_user_upgrades(user_id)
    
    base_income = sum(SERVERS[s]["income"] * count for s, count in servers.items())
    
    emp_multiplier = 1.0
    for e, count in employees.items():
        emp_multiplier *= EMPLOYEES[e]["multiplier"] ** count
    
    upgrade_multiplier = 1.0
    for u in upgrades:
        upgrade_multiplier *= UPGRADES[u]["multiplier"]
    
    total_multiplier = emp_multiplier * upgrade_multiplier
    final_income = int(base_income * total_multiplier)
    
    return final_income, final_income * 60, final_income * 60 * 24

async def get_referrals_count(user_id):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT level, COUNT(*) FROM referrals WHERE user_id = ? GROUP BY level",
            (user_id,)
        )
        return dict(await cur.fetchall())

async def get_top(limit=10):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT first_name, username, total_earned FROM users ORDER BY total_earned DESC LIMIT ?",
            (limit,)
        )
        return await cur.fetchall()

async def get_total_stats():
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT COUNT(*), SUM(neurons), SUM(total_deposited) FROM users")
        return await cur.fetchone()

# ============================================================
# БОТ
# ============================================================
logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()

pending_payments = {}
pending_withdrawals = {}

# ============================================================
# ТЕКСТЫ
# ============================================================
WELCOME = """🧠 <b>Добро пожаловать в AutoGram AI!</b>

<b>Здесь ты можешь зарабатывать реальные деньги!</b> 💰

🚀 <b>Как зарабатывать:</b>
• 💰 Пополни баланс от 1000₽
• 🖥 Купи серверы — они приносят доход КАЖДУЮ минуту
• 👨‍💻 Нанимай сотрудников — множат доход
• ⚡ Покупай улучшения — буст навсегда
• 🤝 Приглашай друзей — получай <b>10%</b> от их пополнений
• 💸 Выводи реальные рубли от 3000₽

💸 <b>Выплаты в течение 24 часов</b> на карту любого банка РФ

🎁 Стартовый бонус: <b>1 000 нейронов</b>!

👇 Нажми кнопку, чтобы начать:"""

MAIN_MENU = """🧠 <b>AutoGram AI</b>

💰 <b>Баланс:</b> {neurons:,} нейронов ({rubles}₽)
📈 <b>Доход:</b> {income_per_min:,}/мин · {income_per_hour:,}/час · {income_per_day:,}/день
⚡ <b>Множитель:</b> x{total_multiplier:.2f}

👥 <b>Рефералы:</b> {refs_1}·{refs_2}·{refs_3}
🔥 <b>Streak:</b> {streak} дней

💎 <b>Совет:</b> Чем больше тариф — тем выше множитель!
🚀 <b>При пополнении от 30 000₽</b> — VIP статус и +33% бонус!

Выбирай действие 👇"""

PROFILE = """👤 <b>Твой профиль</b>

🆔 ID: <code>{user_id}</code>
👤 Имя: {first_name}
📱 Username: @{username}

💰 <b>Баланс:</b> {neurons:,} нейронов ({rubles}₽)
💎 Всего заработано: {total_earned:,} 🧠
💸 Всего потрачено: {total_spent:,} 🧠
📅 В игре с: {reg_date}

🤝 <b>Твоя реферальная ссылка:</b>
<code>https://t.me/{bot_username}?start={user_id}</code>

💸 <b>Зарабатывай с нами:</b>
• 1 уровень — <b>10%</b> от пополнений
• 2 уровень — <b>5%</b>
• 3 уровень — <b>2%</b>
+ <b>5 000 нейронов</b> за каждого друга!"""

# ============================================================
# КЛАВИАТУРЫ
# ============================================================
def main_menu_kb():
    return types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="🖥 МАГАЗИН СЕРВЕРОВ", callback_data="shop_servers")],
        [types.InlineKeyboardButton(text="👨‍💻 СОТРУДНИКИ (множители)", callback_data="shop_employees")],
        [types.InlineKeyboardButton(text="⚡ УЛУЧШЕНИЯ (буст навсегда)", callback_data="shop_upgrades")],
        [types.InlineKeyboardButton(text="💰 ПОПОЛНИТЬ БАЛАНС", callback_data="deposit"),
         types.InlineKeyboardButton(text="💸 ВЫВЕСТИ ДЕНЬГИ", callback_data="withdraw")],
        [types.InlineKeyboardButton(text="👤 Профиль", callback_data="profile"),
         types.InlineKeyboardButton(text="🏆 Рейтинг ТОП", callback_data="top")],
        [types.InlineKeyboardButton(text="🎁 Ежедневный бонус", callback_data="daily"),
         types.InlineKeyboardButton(text="🤝 Рефералы", callback_data="referrals")],
        [types.InlineKeyboardButton(text="📊 Статистика", callback_data="stats")]
    ])

def back_kb():
    return types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="◀️ В меню", callback_data="menu")]
    ])

def servers_shop_kb(user_balance):
    buttons = []
    for key, srv in SERVERS.items():
        can_buy = "✅" if user_balance >= srv["price"] else "🔒"
        buttons.append([types.InlineKeyboardButton(
            text=f"{can_buy} {srv['icon']} {srv['name']} — {srv['price']:,} 🧠 ({srv['income']:,}/мин)",
            callback_data=f"buy_srv_{key}"
        )])
    buttons.append([types.InlineKeyboardButton(text="◀️ В меню", callback_data="menu")])
    return types.InlineKeyboardMarkup(inline_keyboard=buttons)

def employees_shop_kb(user_balance):
    buttons = []
    for key, emp in EMPLOYEES.items():
        can_buy = "✅" if user_balance >= emp["price"] else "🔒"
        buttons.append([types.InlineKeyboardButton(
            text=f"{can_buy} {emp['icon']} {emp['name']} — {emp['price']:,} 🧠 (x{emp['multiplier']})",
            callback_data=f"buy_emp_{key}"
        )])
    buttons.append([types.InlineKeyboardButton(text="◀️ В меню", callback_data="menu")])
    return types.InlineKeyboardMarkup(inline_keyboard=buttons)

def upgrades_shop_kb(user_balance, owned):
    buttons = []
    for key, upg in UPGRADES.items():
        if key not in owned:
            can_buy = "✅" if user_balance >= upg["price"] else "🔒"
            buttons.append([types.InlineKeyboardButton(
                text=f"{can_buy} {upg['name']} — {upg['price']:,} 🧠 ({upg['desc']})",
                callback_data=f"buy_upg_{key}"
            )])
        else:
            buttons.append([types.InlineKeyboardButton(
                text=f"✅ КУПЛЕНО: {upg['name']}",
                callback_data="noop"
            )])
    buttons.append([types.InlineKeyboardButton(text="◀️ В меню", callback_data="menu")])
    return types.InlineKeyboardMarkup(inline_keyboard=buttons)

def deposit_kb():
    buttons = []
    for amount, pkg in DEPOSIT_PACKAGES.items():
        total = pkg["neurons"] + pkg["bonus"]
        bonus_text = f" +{pkg['bonus']:,}🧠 БОНУС" if pkg['bonus'] > 0 else ""
        buttons.append([types.InlineKeyboardButton(
            text=f"💎 {pkg['label']} — {amount}₽ ({total:,}🧠{bonus_text})",
            callback_data=f"dep_{amount}"
        )])
    buttons.append([types.InlineKeyboardButton(text="💬 Другая сумма", callback_data="dep_custom")])
    buttons.append([types.InlineKeyboardButton(text="◀️ В меню", callback_data="menu")])
    return types.InlineKeyboardMarkup(inline_keyboard=buttons)

# ============================================================
# ХЕНДЛЕРЫ
# ============================================================
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    args = message.text.split()
    referrer_id = None
    if len(args) > 1 and args[1].isdigit():
        ref = int(args[1])
        if ref != message.from_user.id:
            referrer_id = ref
    
    user = await get_user(message.from_user.id)
    if not user:
        await add_user(
            message.from_user.id,
            message.from_user.username,
            message.from_user.first_name,
            referrer_id
        )
        if referrer_id:
            try:
                await bot.send_message(
                    referrer_id,
                    f"🎉 <b>По твоей ссылке зарегистрировался новый игрок!</b>\n"
                    f"👤 {message.from_user.first_name}\n"
                    f"💰 Тебе начислено: <b>+{REF_BONUS_NEURONS:,} нейронов</b>"
                )
            except:
                pass
    
    await message.answer(WELCOME, reply_markup=main_menu_kb())

@dp.callback_query(F.data == "menu")
async def menu_callback(callback: types.CallbackQuery):
    await show_main_menu(callback.message, callback.from_user.id, edit=True)
    await callback.answer()

@dp.callback_query(F.data == "profile")
async def profile_callback(callback: types.CallbackQuery):
    user = await get_user(callback.from_user.id)
    user_id, username, first_name, neurons, total_dep, total_with, total_earned, total_spent, referrer_id, reg_date, *_ = user
    
    rubles = neurons // NEURONS_PER_RUB
    me = await bot.get_me()
    
    text = PROFILE.format(
        user_id=user_id,
        first_name=first_name,
        username=username or "не указан",
        neurons=neurons,
        rubles=rubles,
        total_earned=total_earned,
        total_spent=total_spent,
        reg_date=reg_date[:10] if reg_date else "сегодня",
        bot_username=me.username
    )
    await callback.message.edit_text(text, reply_markup=back_kb())
    await callback.answer()

@dp.callback_query(F.data == "shop_servers")
async def shop_servers(callback: types.CallbackQuery):
    user = await get_user(callback.from_user.id)
    income_per_min, income_per_hour, income_per_day = await calculate_income(callback.from_user.id)
    servers = await get_user_servers(callback.from_user.id)
    
    text = f"""🖥 <b>МАГАЗИН СЕРВЕРОВ</b>

💰 Твой баланс: <b>{user[3]:,}</b> 🧠
📈 Текущий доход: <b>{income_per_min:,}/мин</b> ({income_per_hour:,}/час)

💎 <b>Почему нужно покупать серверы:</b>

🔥 <b>🍓 Raspberry Pi</b> за 5 000 🧠:
   • Приносит 80 🧠/мин
   • За сутки: <b>115 200 🧠</b> = 1 152₽
   • <b>Окупаемость: 1 час!</b>

🔥 <b>💻 Игровой ноутбук</b> за 50 000 🧠:
   • Приносит 900 🧠/мин
   • За сутки: <b>1 296 000 🧠</b> = 12 960₽
   • <b>Окупаемость: 1 час!</b>

🔥 <b>🖥 Игровой ПК</b> за 500 000 🧠:
   • Приносит 10 000 🧠/мин
   • За сутки: <b>14 400 000 🧠</b> = 144 000₽
   • <b>Окупаемость: 50 минут!</b>

⚡ <b>Купи несколько — доход суммируется!</b>
🚀 <b>Совет:</b> начни с Raspberry Pi, докупай каждый час!

🔥 <b>Твои серверы:</b> {sum(servers.values()) if servers else 0} шт.

Выбирай сервер:"""
    
    await callback.message.edit_text(text, reply_markup=servers_shop_kb(user[3]))
    await callback.answer()

@dp.callback_query(F.data.startswith("buy_srv_"))
async def buy_server(callback: types.CallbackQuery):
    srv_type = callback.data.split("_")[2]
    if srv_type not in SERVERS:
        await callback.answer("❌ Ошибка", show_alert=True)
        return
    
    srv = SERVERS[srv_type]
    user = await get_user(callback.from_user.id)
    
    if user[3] < srv["price"]:
        await callback.answer(f"❌ Не хватает {srv['price'] - user[3]:,} нейронов!", show_alert=True)
        return
    
    async with aiosqlite.connect(DB_PATH) as db:
        await update_balance(callback.from_user.id, -srv["price"])
        await db.execute(
            "INSERT INTO user_servers (user_id, server_type) VALUES (?, ?)",
            (callback.from_user.id, srv_type)
        )
        await db.commit()
    
    income_per_min, income_per_hour, _ = await calculate_income(callback.from_user.id)
    await callback.answer(
        f"✅ {srv['name']} куплен!\n📈 Новый доход: {income_per_min:,}/мин ({income_per_hour:,}/час)", 
        show_alert=True
    )

@dp.callback_query(F.data == "shop_employees")
async def shop_employees(callback: types.CallbackQuery):
    user = await get_user(callback.from_user.id)
    employees = await get_user_employees(callback.from_user.id)
    
    text = f"""👨‍💻 <b>КАДРОВОЕ АГЕНТСТВО</b>

💰 Твой баланс: <b>{user[3]:,}</b> 🧠

💎 <b>Зачем нанимать сотрудников?</b>

• Они <b>УМНОЖАЮТ</b> доход от серверов
• Один Senior умножает доход в 3 раза!
• Два Senior — в 9 раз!
• Работают 24/7 без выходных
• Окупаются за минуты

🔥 <b>Примеры:</b>
• Junior (x1.5) — доход +50%
• Middle (x2) — доход x2
• Senior (x3) — доход x3
• CTO (x10) — доход x10 🔥

⚡ <b>Можно нанимать несколько!</b>
⚡ <b>Все множители перемножаются!</b>

🔥 <b>Твоя команда:</b> {sum(employees.values()) if employees else 0} чел.

Выбирай специалиста:"""
    
    await callback.message.edit_text(text, reply_markup=employees_shop_kb(user[3]))
    await callback.answer()

@dp.callback_query(F.data.startswith("buy_emp_"))
async def buy_employee(callback: types.CallbackQuery):
    emp_type = callback.data.split("_")[2]
    if emp_type not in EMPLOYEES:
        return
    
    emp = EMPLOYEES[emp_type]
    user = await get_user(callback.from_user.id)
    
    if user[3] < emp["price"]:
        await callback.answer(f"❌ Не хватает {emp['price'] - user[3]:,} нейронов!", show_alert=True)
        return
    
    async with aiosqlite.connect(DB_PATH) as db:
        await update_balance(callback.from_user.id, -emp["price"])
        await db.execute(
            "INSERT INTO user_employees (user_id, emp_type) VALUES (?, ?)",
            (callback.from_user.id, emp_type)
        )
        await db.commit()
    
    income_per_min, _, _ = await calculate_income(callback.from_user.id)
    await callback.answer(
        f"✅ {emp['name']} нанят!\n📈 Множитель: x{emp['multiplier']}\n💵 Новый доход: {income_per_min:,}/мин", 
        show_alert=True
    )

@dp.callback_query(F.data == "shop_upgrades")
async def shop_upgrades(callback: types.CallbackQuery):
    user = await get_user(callback.from_user.id)
    owned = await get_user_upgrades(callback.from_user.id)
    
    text = f"""⚡ <b>УЛУЧШЕНИЯ ИМПЕРИИ</b>

💰 Твой баланс: <b>{user[3]:,}</b> 🧠

💎 <b>Лучшая инвестиция в игре!</b>

• Постоянный буст к доходу <b>НАВСЕГДА</b>
• Не нужно обслуживать
• Складываются с множителями сотрудников
• Покупаешь один раз — работает вечно

🔥 <b>Доступные улучшения:</b>
❄️ Система охлаждения — +20% к доходу
🌐 Оптимизация сети — +30% к доходу
⚛️ Квантовая оптимизация — +50% к доходу
🧠 Нейроинтерфейс — +100% к доходу!

⚡ <b>Все улучшения перемножаются!</b>

Выбирай улучшение:"""
    
    await callback.message.edit_text(text, reply_markup=upgrades_shop_kb(user[3], owned))
    await callback.answer()

@dp.callback_query(F.data.startswith("buy_upg_"))
async def buy_upgrade(callback: types.CallbackQuery):
    upg_type = callback.data.split("_")[2]
    if upg_type not in UPGRADES:
        return
    
    upg = UPGRADES[upg_type]
    user = await get_user(callback.from_user.id)
    owned = await get_user_upgrades(callback.from_user.id)
    
    if upg_type in owned:
        await callback.answer("❌ Уже куплено!", show_alert=True)
        return
    
    if user[3] < upg["price"]:
        await callback.answer(f"❌ Не хватает {upg['price'] - user[3]:,} нейронов!", show_alert=True)
        return
    
    async with aiosqlite.connect(DB_PATH) as db:
        await update_balance(callback.from_user.id, -upg["price"])
        await db.execute(
            "INSERT INTO user_upgrades (user_id, upgrade_type) VALUES (?, ?)",
            (callback.from_user.id, upg_type)
        )
        await db.commit()
    
    await callback.answer(f"✅ {upg['name']} установлен!\n{upg['desc']}", show_alert=True)

@dp.callback_query(F.data == "deposit")
async def deposit_callback(callback: types.CallbackQuery):
    text = f"""💰 <b>ПОПОЛНЕНИЕ БАЛАНСА</b>

💎 <b>Курс:</b> 1₽ = {NEURONS_PER_RUB} нейронов

🚀 <b>ВЫБЕРИ ТАРИФ — чем больше, тем выгоднее:</b>

💎 <b>1000₽</b> — 80 000 🧠 (старт)
💎 <b>3000₽</b> — 300 000 🧠 +30 000 БОНУС
💎 <b>5000₽</b> — 600 000 🧠 +100 000 БОНУС
💎 <b>10000₽</b> — 1 400 000 🧠 +300 000 БОНУС
🔥 <b>30000₽</b> — 4 800 000 🧠 +1 200 000 БОНУС + VIP
🔥 <b>50000₽</b> — 9 000 000 🧠 +2 500 000 БОНУС + Premium
🔥 <b>100000₽</b> — 22 000 000 🧠 +7 000 000 БОНУС + Premium+

💎 <b>Примеры дохода:</b>
• Купи 1 сервер «Игровой ПК» (500 000 🧠) → доход 10 000/мин
• Это <b>600 000 🧠/час</b> = 6 000₽/час
• За сутки: <b>144 000₽</b> 💰

⚡ <b>Зачем пополнять больше?</b>
• Серверы приносят доход 24/7
• Реальные деньги на карту
• Окупаемость от 1 часа

Выбирай тариф:"""
    
    await callback.message.edit_text(text, reply_markup=deposit_kb())
    await callback.answer()

@dp.callback_query(F.data.startswith("dep_"))
async def deposit_amount(callback: types.CallbackQuery):
    if callback.data == "dep_custom":
        await callback.message.edit_text(
            "💬 <b>Введи свою сумму:</b>\n\n"
            "Отправь сообщение с суммой в рублях (от 1000₽).\n"
            "Пример: <code>2500</code>",
            reply_markup=back_kb()
        )
        pending_payments[callback.from_user.id] = {"waiting": "custom_amount"}
        await callback.answer()
        return
    
    amount_str = callback.data.split("_")[1]
    if not amount_str.isdigit():
        return
    
    amount = int(amount_str)
    pkg = DEPOSIT_PACKAGES.get(amount_str)
    if not pkg:
        await callback.answer("❌ Неверный тариф", show_alert=True)
        return
    
    # Генерируем уникальный label
    label = f"autogr_{uuid.uuid4().hex[:12]}"
    
    # Сохраняем в БД
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO deposits (user_id, amount_rub, neurons_amount, label) VALUES (?, ?, ?, ?)",
            (callback.from_user.id, amount, pkg["neurons"] + pkg["bonus"], label)
        )
        await db.commit()
    
    pending_payments[label] = {
        "user_id": callback.from_user.id,
        "amount": amount,
        "neurons": pkg["neurons"],
        "bonus": pkg["bonus"]
    }
    
    # Формируем ссылку на оплату ЮMoney
    pay_url = (
        f"https://yoomoney.ru/transfer?"
        f"quickpay=shop&"
        f"receiver={YOOMONEY_WALLET}&"
        f"sum={amount}&"
        f"label={label}"
    )
    
    total_neurons = pkg["neurons"] + pkg["bonus"]
    bonus_text = f"\n🎁 <b>Бонус:</b> +{pkg['bonus']:,} 🧠" if pkg["bonus"] > 0 else ""
    
    text = f"""💳 <b>ОПЛАТА {amount}₽</b> — {pkg['label']}

📦 <b>К зачислению:</b> {total_neurons:,} 🧠{bonus_text}

💳 <b>Реквизиты для оплаты:</b>
   💎 Кошелёк: <code>{YOOMONEY_WALLET}</code>
   💰 Сумма: <b>{amount}₽</b>
   📝 Комментарий: <code>{label}</code>

📲 <b>Как оплатить:</b>

<b>Способ 1 (быстрый):</b>
👇 Нажми кнопку «Оплатить» ниже

<b>Способ 2 (вручную):</b>
1. Открой <a href="https://yoomoney.ru/transfer">yoomoney.ru/transfer</a>
2. Введи кошелёк: <code>{YOOMONEY_WALLET}</code>
3. Сумма: <b>{amount}₽</b>
4. В комментарии укажи: <code>{label}</code>
5. Нажми «Проверить оплату» в боте

⏱ <b>Оплата действительна 30 минут</b>"""
    
    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text=f"💳 Оплатить {amount}₽", url=pay_url)],
        [types.InlineKeyboardButton(text="✅ Проверить оплату", callback_data=f"check_{label}")],
        [types.InlineKeyboardButton(text="❌ Отменить", callback_data=f"cancel_{label}")],
        [types.InlineKeyboardButton(text="◀️ В меню", callback_data="menu")]
    ])
    await callback.message.edit_text(text, reply_markup=kb, disable_web_page_preview=True)
    await callback.answer()

@dp.callback_query(F.data.startswith("check_"))
async def check_payment(callback: types.CallbackQuery):
    label = callback.data.replace("check_", "")
    
    if label not in pending_payments:
        await callback.answer("⏳ Платёж не найден или уже обработан. Подожди 1-2 минуты.", show_alert=True)
        return
    
    payment = pending_payments[label]
    
    try:
        from yoomoney import Client
        client = Client(YOOMONEY_TOKEN)
        history = client.operation_history(label=label)
        
        found = False
        for op in history.operations:
            if op.status == "success":
                found = True
                total_neurons = payment["neurons"] + payment["bonus"]
                await update_balance(payment["user_id"], total_neurons)
                
                async with aiosqlite.connect(DB_PATH) as db:
                    await db.execute(
                        "UPDATE users SET total_deposited = total_deposited + ? WHERE user_id = ?",
                        (payment["amount"], payment["user_id"])
                    )
                    await db.execute(
                        "UPDATE deposits SET status = 'success' WHERE label = ?",
                        (label,)
                    )
                    
                    # Реферальный бонус
                    cur = await db.execute("SELECT referrer_id FROM users WHERE user_id = ?", (payment["user_id"],))
                    row = await cur.fetchone()
                    if row and row[0]:
                        ref_id = row[0]
                        bonus_ref = int(payment["amount"] * NEURONS_PER_RUB * REF_LEVELS[1] / 100)
                        await db.execute(
                            "UPDATE users SET neurons = neurons + ? WHERE user_id = ?",
                            (bonus_ref, ref_id)
                        )
                        try:
                            await bot.send_message(
                                ref_id,
                                f"💰 <b>Реферальный бонус!</b>\n\n"
                                f"Твой реферал пополнил баланс на {payment['amount']}₽\n"
                                f"Ты получил: <b>+{bonus_ref:,} 🧠</b> ({REF_LEVELS[1]}%)"
                            )
                        except:
                            pass
                    await db.commit()
                
                pending_payments.pop(label, None)
                await callback.answer(f"✅ Оплата получена! +{total_neurons:,} 🧠", show_alert=True)
                await show_main_menu(callback.message, callback.from_user.id, edit=True)
                return
        
        if not found:
            await callback.answer("⏳ Оплата ещё не поступила. Подожди 30-60 секунд и попробуй ещё раз.", show_alert=True)
    except Exception as e:
        await callback.answer(f"❌ Ошибка проверки: {str(e)[:100]}", show_alert=True)

@dp.callback_query(F.data.startswith("cancel_"))
async def cancel_payment(callback: types.CallbackQuery):
    label = callback.data.replace("cancel_", "")
    pending_payments.pop(label, None)
    
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE deposits SET status = 'cancelled' WHERE label = ?", (label,))
        await db.commit()
    
    await callback.answer("❌ Платёж отменён", show_alert=False)
    await show_main_menu(callback.message, callback.from_user.id, edit=True)

@dp.callback_query(F.data == "withdraw")
async def withdraw_callback(callback: types.CallbackQuery):
    user = await get_user(callback.from_user.id)
    neurons = user[3]
    gross_rub = neurons // NEURONS_PER_RUB
    fee = int(gross_rub * WITHDRAW_FEE_PERCENT / 100)
    net_rub = gross_rub - fee
    
    if gross_rub < MIN_WITHDRAW_RUB:
        needed = MIN_WITHDRAW_RUB - gross_rub
        await callback.message.edit_text(
            f"💸 <b>ВЫВОД СРЕДСТВ</b>\n\n"
            f"💰 Доступно: <b>{gross_rub}₽</b> ({neurons:,} 🧠)\n"
            f"❌ Минимальная сумма вывода: <b>{MIN_WITHDRAW_RUB}₽</b>\n\n"
            f"📊 Нужно ещё: <b>{needed}₽</b>\n\n"
            f"💎 <b>Совет:</b> Купи серверы и заработай!\n"
            f"🍓 Raspberry Pi приносит 80 🧠/мин = 4 800₽/час\n\n"
            f"🚀 Или пополни баланс и крути оборот!",
            reply_markup=back_kb()
        )
    else:
        text = f"""💸 <b>ВЫВОД СРЕДСТВ</b>

💰 На балансе: <b>{neurons:,} нейронов</b>
💵 Это эквивалент: <b>{gross_rub}₽</b>

━━━━━━━━━━━━━━━━━━━━
💎 <b>РАСЧЁТ ВЫПЛАТЫ:</b>
   Сумма: <b>{gross_rub}₽</b>
   Комиссия ({WITHDRAW_FEE_PERCENT}%): <b>{fee}₽</b>
   ━━━━━━━━━━━━━━━━━━━
   💸 <b>К выплате: {net_rub}₽</b>
━━━━━━━━━━━━━━━━━━━━

❓ <b>Хотите вывести эти средства?</b>

💳 Выплата на карту любого банка РФ
⏱ Срок: <b>до 24 часов</b> (вручную администратором)
🔒 Безопасно и надёжно

Нажми «ДА» для продолжения:"""
        
        kb = types.InlineKeyboardMarkup(inline_keyboard=[
            [types.InlineKeyboardButton(text=f"✅ ДА, ВЫВЕСТИ {net_rub}₽", callback_data="withdraw_confirm")],
            [types.InlineKeyboardButton(text="◀️ Отмена", callback_data="menu")]
        ])
        await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()

@dp.callback_query(F.data == "withdraw_confirm")
async def withdraw_confirm(callback: types.CallbackQuery):
    pending_withdrawals[callback.from_user.id] = {"step": "wallet"}
    await callback.message.edit_text(
        "💳 <b>Шаг 1/2: Введи номер карты или кошелька</b>\n\n"
        "💎 Форматы:\n"
        "• Банковская карта: <code>2200123456789012</code>\n"
        "• ЮMoney: <code>4100118935779591</code>\n"
        "• Телефон (СБП): <code>+79991234567</code>\n\n"
        "⚠️ <b>Внимательно проверь номер!</b>\n"
        "Деньги отправим именно сюда.",
        reply_markup=types.InlineKeyboardMarkup(inline_keyboard=[
            [types.InlineKeyboardButton(text="◀️ Отмена", callback_data="menu")]
        ])
    )
    await callback.answer()

@dp.message()
async def handle_text_input(message: types.Message):
    user_id = message.from_user.id
    
    # Кастомная сумма пополнения
    if user_id in pending_payments and pending_payments[user_id].get("waiting") == "custom_amount":
        try:
            amount = int(message.text)
            if amount < 1000:
                await message.answer("❌ Минимальная сумма пополнения: <b>1000₽</b>")
                return
            
            neurons = int(amount * NEURONS_PER_RUB * 0.85)
            label = f"autogr_{uuid.uuid4().hex[:12]}"
            
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute(
                    "INSERT INTO deposits (user_id, amount_rub, neurons_amount, label) VALUES (?, ?, ?, ?)",
                    (user_id, amount, neurons, label)
                )
                await db.commit()
            
            pending_payments[label] = {
                "user_id": user_id, "amount": amount, "neurons": neurons, "bonus": 0
            }
            
            pay_url = f"https://yoomoney.ru/transfer?quickpay=shop&receiver={YOOMONEY_WALLET}&sum={amount}&label={label}"
            kb = types.InlineKeyboardMarkup(inline_keyboard=[
                [types.InlineKeyboardButton(text=f"💳 Оплатить {amount}₽", url=pay_url)],
                [types.InlineKeyboardButton(text="✅ Проверить", callback_data=f"check_{label}")],
                [types.InlineKeyboardButton(text="◀️ В меню", callback_data="menu")]
            ])
            await message.answer(
                f"💳 <b>Оплата {amount}₽</b>\n\n"
                f"💎 Кошелёк: <code>{YOOMONEY_WALLET}</code>\n"
                f"📝 Комментарий: <code>{label}</code>\n\n"
                f"К зачислению: <b>{neurons:,} 🧠</b>",
                reply_markup=kb
            )
            pending_payments.pop(user_id, None)
        except ValueError:
            await message.answer("❌ Введи целое число")
        return
    
    # Ввод реквизитов для вывода
    if user_id in pending_withdrawals:
        data = pending_withdrawals[user_id]
        if data["step"] == "wallet":
            wallet = message.text.strip()
            if len(wallet) < 10:
                await message.answer("❌ Слишком короткий номер. Попробуй ещё раз:")
                return
            data["wallet"] = wallet
            data["step"] = "bank"
            await message.answer(
                f"💳 Карта/кошелёк: <code>{wallet}</code>\n\n"
                "🏦 <b>Шаг 2/2: Укажи название банка</b>\n\n"
                "Примеры:\n"
                "• <code>Сбербанк</code>\n"
                "• <code>Тинькофф</code>\n"
                "• <code>Альфа-Банк</code>\n"
                "• <code>ЮMoney</code>",
                reply_markup=types.InlineKeyboardMarkup(inline_keyboard=[
                    [types.InlineKeyboardButton(text="◀️ Отмена", callback_data="menu")]
                ])
            )
        elif data["step"] == "bank":
            bank = message.text.strip()
            data["bank"] = bank
            
            user = await get_user(user_id)
            neurons = user[3]
            gross_rub = neurons // NEURONS_PER_RUB
            fee = int(gross_rub * WITHDRAW_FEE_PERCENT / 100)
            net_rub = gross_rub - fee
            
            await update_balance(user_id, -(net_rub * NEURONS_PER_RUB + fee * NEURONS_PER_RUB))
            
            async with aiosqlite.connect(DB_PATH) as db:
                cur = await db.execute(
                    "INSERT INTO withdrawals (user_id, amount_rub, neurons_amount, wallet, bank) VALUES (?, ?, ?, ?, ?) RETURNING id",
                    (user_id, net_rub, net_rub * NEURONS_PER_RUB, data["wallet"], data["bank"])
                )
                wid = (await cur.fetchone())[0]
                await db.execute(
                    "UPDATE users SET total_withdrawn = total_withdrawn + ? WHERE user_id = ?",
                    (net_rub, user_id)
                )
                await db.commit()
            
            # Уведомление админу
            try:
                await bot.send_message(
                    ADMIN_ID,
                    f"🔔 <b>НОВАЯ ЗАЯВКА НА ВЫВОД #{wid}</b>\n\n"
                    f"👤 Игрок: {user[2]} (@{user[1] or '—'})\n"
                    f"🆔 ID: <code>{user_id}</code>\n"
                    f"💰 Сумма к выплате: <b>{net_rub}₽</b>\n"
                    f"💳 Кошелёк: <code>{data['wallet']}</code>\n"
                    f"🏦 Банк: {data['bank']}\n"
                    f"📅 Заявка: {datetime.now().strftime('%d.%m.%Y %H:%M')}\n\n"
                    f"<b>⚠️ Оплати вручную в течение 24 часов!</b>",
                    parse_mode="HTML"
                )
            except:
                pass
            
            await message.answer(
                f"✅ <b>ЗАЯВКА #{wid} СОЗДАНА!</b>\n\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"💸 Сумма к выплате: <b>{net_rub}₽</b>\n"
                f"💳 Кошелёк: <code>{data['wallet']}</code>\n"
                f"🏦 Банк: {data['bank']}\n"
                f"━━━━━━━━━━━━━━━━━━━━\n\n"
                f"⏱ <b>Выплата в течение 24 часов</b>\n"
                f"📞 Если что-то не так — напиши @username\n\n"
                f"💎 Списано с баланса: {(net_rub + fee) * NEURONS_PER_RUB:,} 🧠\n"
                f"💰 Комиссия {WITHDRAW_FEE_PERCENT}%: {fee}₽",
                reply_markup=main_menu_kb()
            )
            pending_withdrawals.pop(user_id, None)
        return

@dp.callback_query(F.data == "daily")
async def daily_callback(callback: types.CallbackQuery):
    user = await get_user(callback.from_user.id)
    last_bonus_str = user[10]
    streak = user[11] or 0
    
    now = datetime.now()
    today = now.date().isoformat()
    
    if last_bonus_str == today:
        tomorrow = (now + timedelta(days=1)).strftime("%d.%m.%Y %H:%M")
        await callback.answer(f"⏳ Бонус уже получен сегодня!\nСледующий доступен завтра в 00:00", show_alert=True)
        return
    
    new_streak = 1
    if last_bonus_str:
        last_date = datetime.fromisoformat(last_bonus_str).date()
        if (now.date() - last_date).days == 1:
            new_streak = streak + 1
    
    streak_idx = min(new_streak - 1, len(DAILY_BONUS) - 1)
    bonus = DAILY_BONUS[streak_idx]
    
    async with aiosqlite.connect(DB_PATH) as db:
        await update_balance(callback.from_user.id, bonus)
        await db.execute(
            "UPDATE users SET last_bonus_date = ?, bonus_streak = ? WHERE user_id = ?",
            (today, new_streak, callback.from_user.id)
        )
        await db.commit()
    
    await callback.answer(
        f"🎁 День {new_streak}: +{bonus:,} 🧠\n🔥 Streak: {new_streak} дней!\n💎 Завтра будет ещё больше!",
        show_alert=True
    )

@dp.callback_query(F.data == "referrals")
async def referrals_callback(callback: types.CallbackQuery):
    user = await get_user(callback.from_user.id)
    me = await bot.get_me()
    refs = await get_referrals_count(callback.from_user.id)
    
    text = f"""🤝 <b>РЕФЕРАЛЬНАЯ СИСТЕМА</b>

💰 <b>Твоя ссылка:</b>
<code>https://t.me/{me.username}?start={callback.from_user.id}</code>

📊 <b>Зарабатывай с нами:</b>

🥇 1 уровень — <b>{REF_LEVELS[1]}%</b> от пополнений
🥈 2 уровень — <b>{REF_LEVELS[2]}%</b>
🥉 3 уровень — <b>{REF_LEVELS[3]}%</b>

+ <b>{REF_BONUS_NEURONS:,} 🧠</b> за каждого приглашённого!

📈 <b>Твои рефералы:</b>
• 1 уровень: <b>{refs.get(1, 0)}</b> чел.
• 2 уровень: <b>{refs.get(2, 0)}</b> чел.
• 3 уровень: <b>{refs.get(3, 0)}</b> чел.

💎 <b>Пример:</b>
Твой реферал пополнил на 10 000₽
Ты получаешь: <b>{REF_LEVELS[1]}% × 10 000₽ = {REF_LEVELS[1] * 100:,} 🧠 = {REF_LEVELS[1] * 100 // 100}₽</b> моментально!

⚡ <b>Чем больше рефералов — тем больше доход!</b>

🔗 Поделись ссылкой и зарабатывай пассивно!"""
    
    await callback.message.edit_text(text, reply_markup=back_kb())
    await callback.answer()

@dp.callback_query(F.data == "top")
async def top_callback(callback: types.CallbackQuery):
    top = await get_top(10)
    user = await get_user(callback.from_user.id)
    
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT COUNT(*) + 1 FROM users WHERE total_earned > ?",
            (user[6],)
        )
        user_rank = (await cur.fetchone())[0]
    
    text = f"🏆 <b>ТОП-10 ИГРОКОВ</b>\nТвоё место: <b>#{user_rank}</b>\n\n"
    
    medals = ["🥇", "🥈", "🥉"]
    for i, (name, username, earned) in enumerate(top, 1):
        medal = medals[i-1] if i <= 3 else f"{i}."
        text += f"{medal} {name} — <b>{earned:,}</b> 🧠\n"
    
    if not top:
        text += "<i>Пока никто не играл. Будь первым!</i>"
    
    await callback.message.edit_text(text, reply_markup=back_kb())
    await callback.answer()

@dp.callback_query(F.data == "stats")
async def stats_callback(callback: types.CallbackQuery):
    total_users, total_neurons, total_dep = await get_total_stats()
    user = await get_user(callback.from_user.id)
    income_per_min, income_per_hour, income_per_day = await calculate_income(callback.from_user.id)
    
    text = f"""📊 <b>ТВОЯ СТАТИСТИКА</b>

💰 Баланс: <b>{user[3]:,}</b> 🧠
📈 Доход/мин: <b>{income_per_min:,}</b> 🧠
⏳ Доход/час: <b>{income_per_hour:,}</b> 🧠
📅 Доход/день: <b>{income_per_day:,}</b> 🧠

💎 Всего заработано: <b>{user[6]:,}</b> 🧠
💸 Всего пополнено: <b>{user[4]:,}</b>₽
💰 Всего выведено: <b>{user[5]:,}</b>₽

━━━━━━━━━━━━━━━━━━━━
🌐 <b>Глобальная статистика:</b>
👥 Игроков: <b>{total_users}</b>
💰 Нейронов в игре: <b>{total_neurons or 0:,}</b>
💵 Пополнено всего: <b>{total_dep or 0:,}</b>₽"""
    
    await callback.message.edit_text(text, reply_markup=back_kb())
    await callback.answer()

@dp.callback_query(F.data == "noop")
async def noop(callback: types.CallbackQuery):
    await callback.answer()

async def show_main_menu(message, user_id, edit=False):
    user = await get_user(user_id)
    income_per_min, income_per_hour, income_per_day = await calculate_income(user_id)
    rubles = user[3] // NEURONS_PER_RUB
    refs = await get_referrals_count(user_id)
    
    employees = await get_user_employees(user_id)
    upgrades = await get_user_upgrades(user_id)
    
    emp_mult = 1.0
    for e, count in employees.items():
        emp_mult *= EMPLOYEES[e]["multiplier"] ** count
    upg_mult = 1.0
    for u in upgrades:
        upg_mult *= UPGRADES[u]["multiplier"]
    total_mult = emp_mult * upg_mult
    
    text = MAIN_MENU.format(
        neurons=user[3],
        rubles=rubles,
        income_per_min=income_per_min,
        income_per_hour=income_per_hour,
        income_per_day=income_per_day,
        total_multiplier=total_mult,
        refs_1=refs.get(1, 0),
        refs_2=refs.get(2, 0),
        refs_3=refs.get(3, 0),
        streak=user[11] or 0
    )
    
    if edit:
        await message.edit_text(text, reply_markup=main_menu_kb())
    else:
        await message.answer(text, reply_markup=main_menu_kb())

# ============================================================
# ФОНОВЫЕ ЗАДАЧИ
# ============================================================
async def income_loop():
    while True:
        try:
            async with aiosqlite.connect(DB_PATH) as db:
                cur = await db.execute("SELECT user_id FROM users")
                users = await cur.fetchall()
            
            for (user_id,) in users:
                income, _, _ = await calculate_income(user_id)
                if income > 0:
                    await update_balance(user_id, income)
        except Exception as e:
            logging.error(f"Income loop error: {e}")
        
        await asyncio.sleep(60)

# ============================================================
# ЗАПУСК
# ============================================================
async def main():
    await init_db()
    asyncio.create_task(income_loop())
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
