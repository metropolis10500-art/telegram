import asyncio
import logging
import os
import uuid
import random
from datetime import datetime, timedelta
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.enums import ParseMode
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
PROJECT_NAME = os.getenv("PROJECT_NAME", "AutoGram AI")
DB_PATH = "autogram.db"

# ============================================================
# ЭКОНОМИКА (настроена для хорошего заработка создателя)
# ============================================================
# Курс: 1₽ = 100 нейронов
NEURONS_PER_RUB = 100
MIN_WITHDRAW_RUB = 100  # минимальный вывод
WITHDRAW_FEE_PERCENT = 10  # комиссия 10% при выводе (твой заработок)

# Тарифы пополнения (с наценкой для заработка создателя)
DEPOSIT_PACKAGES = {
    "100":  {"neurons": 8000,   "bonus": 0,    "label": "Старт"},      # -20% от номинала
    "300":  {"neurons": 27000,  "bonus": 3000, "label": "Базовый"},    # -10% + бонус
    "500":  {"neurons": 50000,  "bonus": 7500, "label": "Стандарт"},   # бонус 15%
    "1000": {"neurons": 110000, "bonus": 25000,"label": "Профи"},      # +10% + бонус
    "3000": {"neurons": 360000, "bonus": 120000,"label": "Бизнес"},    # +20% + бонус
    "5000": {"neurons": 650000, "bonus": 250000,"label": "VIP"},       # +30% + бонус
    "10000":{"neurons": 1500000,"bonus": 700000,"label": "PREMIUM"}    # +50% + бонус
}

# Серверы (цена в нейронах, доход в нейронах в минуту)
# Доходность: от 0.3% до 1% в минуту = 43% - 1440% в сутки (психологически привлекательно)
SERVERS = {
    "raspberry": {"name": "🍓 Raspberry Pi",      "price": 500,      "income": 5,      "icon": "🍓", "desc": "Идеален для старта"},
    "laptop":    {"name": "💻 Игровой ноутбук",   "price": 5000,     "income": 60,     "icon": "💻", "desc": "Стабильный доход"},
    "pc":        {"name": "🖥 Игровой ПК",        "price": 50000,    "income": 700,    "icon": "🖥", "desc": "Серьёзная машина"},
    "server":    {"name": "🗄 Серверная стойка",  "price": 500000,   "income": 8000,   "icon": "🗄", "desc": "Для опытных"},
    "gpu":       {"name": "⚡ RTX 4090 Cluster",  "price": 5000000,  "income": 90000,  "icon": "⚡", "desc": "Мощь NVIDIA"},
    "datacenter":{"name": "🏢 Дата-центр",        "price": 50000000, "income": 1000000,"icon": "🏢", "desc": "Уровень корпорации"},
    "quantum":   {"name": "🔮 Квантовый компьютер","price": 500000000,"income": 12000000,"icon": "🔮", "desc": "Технологии будущего"}
}

# Сотрудники (множители к доходу)
EMPLOYEES = {
    "junior":   {"name": "👨‍💻 Junior Data Scientist",  "price": 1000,     "multiplier": 1.25, "icon": "👨‍💻"},
    "middle":   {"name": "👩‍💻 Middle ML Engineer",     "price": 15000,    "multiplier": 1.6,  "icon": "👩‍💻"},
    "senior":   {"name": "🧑‍💻 Senior AI Architect",   "price": 200000,   "multiplier": 2.2,  "icon": "🧑‍💻"},
    "lead":     {"name": "🎯 Lead AI Researcher",      "price": 3000000,  "multiplier": 3.5,  "icon": "🎯"},
    "cto":      {"name": "🤖 CTO с ИИ-усилителем",     "price": 50000000, "multiplier": 5.0,  "icon": "🤖"}
}

# Улучшения (разовые бусты)
UPGRADES = {
    "cooling":  {"name": "❄️ Система охлаждения", "price": 2000,       "multiplier": 1.15, "desc": "+15% к доходу навсегда"},
    "net":      {"name": "🌐 Оптимизация сети",   "price": 25000,      "multiplier": 1.20, "desc": "+20% к доходу навсегда"},
    "quantum":  {"name": "⚛ Квантовая оптимизация","price": 500000",   "multiplier": 1.30, "desc": "+30% к доходу навсегда"},
    "neural":   {"name": "🧠 Нейроинтерфейс",     "price": 15000000,   "multiplier": 1.50, "desc": "+50% к доходу навсегда"}
}

# Реферальная система
REF_LEVELS = {
    1: 7,   # 7% от пополнений
    2: 3,   # 3%
    3: 1    # 1%
}
REF_BONUS_NEURONS = 1000  # бонус за каждого приглашённого

# Ежедневный бонус (растущий)
DAILY_BONUS = [100, 250, 500, 1000, 2000, 4000, 8000, 15000, 30000, 50000]

# Рулетка
ROULETTE_PRIZES = [
    ("💰 100 нейронов",   100,    30),
    ("💰 500 нейронов",   500,    25),
    ("💰 1000 нейронов",  1000,   20),
    ("💰 5000 нейронов",  5000,   12),
    ("💎 15000 нейронов", 15000,  7),
    ("🚀 50000 нейронов", 50000,  4),
    ("❌ Ничего",         0,      2),
    ("🎰 x2 бонус",       "x2",   0)  # обрабатывается отдельно
]

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
                neurons INTEGER DEFAULT 500,
                total_deposited REAL DEFAULT 0,
                total_withdrawn REAL DEFAULT 0,
                total_earned INTEGER DEFAULT 0,
                total_spent INTEGER DEFAULT 0,
                referrer_id INTEGER,
                reg_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_bonus_date TEXT,
                bonus_streak INTEGER DEFAULT 0,
                premium INTEGER DEFAULT 0,
                roulette_streak INTEGER DEFAULT 0
            )
        ''')
        await db.execute('''
            CREATE TABLE IF NOT EXISTS user_servers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                server_type TEXT,
                purchase_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        await db.execute('''
            CREATE TABLE IF NOT EXISTS user_employees (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                emp_type TEXT,
                purchase_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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
            # Бонус рефереру
            if referrer_id and referrer_id != user_id:
                # Бонус рефереру
                await db.execute(
                    "UPDATE users SET neurons = neurons + ? WHERE user_id = ?",
                    (REF_BONUS_NEURONS, referrer_id)
                )
                # Сохраняем связь
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
    """Возвращает (доход_в_минуту, доход_в_час, доход_в_день)"""
    servers = await get_user_servers(user_id)
    employees = await get_user_employees(user_id)
    upgrades = await get_user_upgrades(user_id)
    
    base_income = sum(SERVERS[s]["income"] * count for s, count in servers.items())
    
    # Множители от сотрудников (перемножаются)
    emp_multiplier = 1.0
    for e, count in employees.items():
        emp_multiplier *= EMPLOYEES[e]["multiplier"] ** count
    
    # Множители от улучшений
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
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

# Хранилище активных операций
pending_payments = {}
pending_withdrawals = {}

# ============================================================
# ТЕКСТЫ
# ============================================================
WELCOME = """🧠 <b>Добро пожаловать в AutoGram AI!</b>

<b>Здесь ты можешь зарабатывать реальные деньги!</b> 💰

🚀 Что тебя ждёт:
• Строй собственную AI-империю
• Покупай серверы — они приносят доход КАЖДУЮ минуту
• Нанимай крутых сотрудников — множат твой доход
• Приглашай друзей — получай <b>7%</b> от их пополнений
• Выводи реальные рубли на карту любого банка РФ

💸 <b>Выплаты происходят вручную администратором</b> в течение 24 часов.
Минимальная сумма вывода: <b>100₽</b>

🎁 Стартовый бонус: <b>500 нейронов</b> уже на твоём счету!

👇 Нажми кнопку ниже, чтобы начать зарабатывать:"""

MAIN_MENU = """🧠 <b>AutoGram AI</b> — твоя нейросеть приносит деньги

💰 <b>Баланс:</b> {neurons:,} нейронов ({rubles}₽)
📈 <b>Доход:</b> {income_per_min}/мин · {income_per_hour}/час · {income_per_day}/день
⚡ <b>Множитель:</b> x{total_multiplier:.1f}

👥 <b>Рефералы:</b> {refs_1}·{refs_2}·{refs_3} (1·2·3 уровни)
🔥 <b>Streak:</b> {streak} дней

🛒 <b>Магазин мотивирует:</b>
💡 «Серверы окупаются за 100 минут и работают вечно!»
💡 «Купи сотрудника x{emp_x} и удвой доход!»

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

💸 <b>Приглашай друзей и получай:</b>
• 1 уровень — <b>7%</b> от их пополнений
• 2 уровень — <b>3%</b>
• 3 уровень — <b>1%</b>
+ <b>1 000 нейронов</b> за каждого друга сразу!"""

# ============================================================
# КЛАВИАТУРЫ
# ============================================================
def main_menu_kb():
    return types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="⛏ МАЙНИТЬ НЕЙРОНЫ (+10🧠)", callback_data="mine")],
        [types.InlineKeyboardButton(text="🖥 Магазин серверов", callback_data="shop_servers"),
         types.InlineKeyboardButton(text="👨‍💻 Сотрудники", callback_data="shop_employees")],
        [types.InlineKeyboardButton(text="⚡ Улучшения (БУСТ)", callback_data="shop_upgrades")],
        [types.InlineKeyboardButton(text="💰 Пополнить баланс", callback_data="deposit"),
         types.InlineKeyboardButton(text="💸 ВЫВЕСТИ ДЕНЬГИ", callback_data="withdraw")],
        [types.InlineKeyboardButton(text="👤 Профиль", callback_data="profile"),
         types.InlineKeyboardButton(text="🏆 Рейтинг ТОП", callback_data="top")],
        [types.InlineKeyboardButton(text="🎁 Ежедневный бонус", callback_data="daily"),
         types.InlineKeyboardButton(text="🎰 Рулетка", callback_data="roulette")],
        [types.InlineKeyboardButton(text="🤝 Рефералы", callback_data="referrals"),
         types.InlineKeyboardButton(text="📊 Статистика", callback_data="stats")]
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
            text=f"{can_buy} {srv['icon']} {srv['name']} — {srv['price']:,} 🧠 ({srv['income']}/мин)",
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
        is_owned = "✅ КУПЛЕНО" if key in owned else "🛒"
        if key not in owned:
            can_buy = "✅" if user_balance >= upg["price"] else "🔒"
            buttons.append([types.InlineKeyboardButton(
                text=f"{can_buy} {upg['name']} — {upg['price']:,} 🧠 ({upg['desc']})",
                callback_data=f"buy_upg_{key}"
            )])
        else:
            buttons.append([types.InlineKeyboardButton(
                text=f"{is_owned} {upg['name']} — {upg['desc']}",
                callback_data="noop"
            )])
    buttons.append([types.InlineKeyboardButton(text="◀️ В меню", callback_data="menu")])
    return types.InlineKeyboardMarkup(inline_keyboard=buttons)

def deposit_kb():
    buttons = []
    for amount, pkg in DEPOSIT_PACKAGES.items():
        bonus_text = f" +{pkg['bonus']:,}🧠 БОНУС" if pkg['bonus'] > 0 else ""
        buttons.append([types.InlineKeyboardButton(
            text=f"💳 {pkg['label']} — {amount}₽ ({pkg['neurons']:,}🧠{bonus_text})",
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

@dp.callback_query(F.data == "mine")
async def mine_callback(callback: types.CallbackQuery):
    user = await get_user(callback.from_user.id)
    # Множитель от покупок влияет и на клик
    _, _, _, _, _, _, _, _, _, _, _, _, streak = user
    bonus = min(streak * 2, 50)
    reward = 10 + bonus
    
    await update_balance(callback.from_user.id, reward)
    
    phrases = [
        f"⛏ Данные обработаны! +{reward} 🧠",
        f"⚡ Нейроны добыты! +{reward} 🧠",
        f"🧠 AI обучается! +{reward} 🧠",
        f"💎 Кристалл данных! +{reward} 🧠",
        f"🚀 Мегамайнинг! +{reward} 🧠"
    ]
    await callback.answer(random.choice(phrases), show_alert=False)

@dp.callback_query(F.data == "shop_servers")
async def shop_servers(callback: types.CallbackQuery):
    user = await get_user(callback.from_user.id)
    income_per_min, income_per_hour, income_per_day = await calculate_income(callback.from_user.id)
    servers = await get_user_servers(callback.from_user.id)
    
    text = f"""🖥 <b>Магазин серверов</b>

💰 Твой баланс: <b>{user[3]:,}</b> 🧠
📈 Текущий доход: <b>{income_per_min:,}/мин</b>

💡 <b>Почему стоит покупать?</b>
• Серверы окупаются за 100 минут работы
• Доход начисляется КАЖДУЮ минуту
• Работают 24/7 без твоего участия
• Чем больше серверов — тем больше прибыль

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
    
    income_per_min, _, _ = await calculate_income(callback.from_user.id)
    await callback.answer(
        f"✅ {srv['name']} куплен!\n📈 Новый доход: {income_per_min:,}/мин", 
        show_alert=True
    )
    
    user = await get_user(callback.from_user.id)
    text = f"""🖥 <b>Магазин серверов</b>

💰 Твой баланс: <b>{user[3]:,}</b> 🧠
📈 Текущий доход: <b>{income_per_min:,}/мин</b>

💡 <b>Почему стоит покупать?</b>
• Серверы окупаются за 100 минут работы
• Доход начисляется КАЖДУЮ минуту

🔥 <b>Твои серверы:</b> {sum((await get_user_servers(callback.from_user.id)).values())} шт.

✅ Куплено: {srv['name']}!"""
    await callback.message.edit_text(text, reply_markup=servers_shop_kb(user[3]))

@dp.callback_query(F.data == "shop_employees")
async def shop_employees(callback: types.CallbackQuery):
    user = await get_user(callback.from_user.id)
    employees = await get_user_employees(callback.from_user.id)
    
    text = f"""👨‍💻 <b>Кадровое агентство AI</b>

💰 Твой баланс: <b>{user[3]:,}</b> 🧠

💡 <b>Зачем нанимать сотрудников?</b>
• Они УМНОЖАЮТ доход от серверов
• Работают постоянно
• Окупаются за считанные минуты
• Можно нанять несколько одинаковых!

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
        f"✅ {emp['name']} нанят!\n📈 Доход x{emp['multiplier']}!\n💵 Теперь: {income_per_min:,}/мин", 
        show_alert=True
    )

@dp.callback_query(F.data == "shop_upgrades")
async def shop_upgrades(callback: types.CallbackQuery):
    user = await get_user(callback.from_user.id)
    owned = await get_user_upgrades(callback.from_user.id)
    
    text = f"""⚡ <b>Улучшения императора</b>

💰 Твой баланс: <b>{user[3]:,}</b> 🧠

💡 <b>Что дают улучшения?</b>
• Постоянный буст к доходу НАВСЕГДА
• Не нужно обслуживать
• Складываются с другими бонусами
• Лучшая инвестиция в игре!

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
    text = f"""💰 <b>Пополнение баланса</b>

Курс: <b>1₽ = {NEURONS_PER_RUB} нейронов</b>

💎 <b>Выбери тариф — чем больше, тем выгоднее!</b>

🔥 При пополнении от 500₽ — бонусные нейроны!
💎 При пополнении от 3000₽ — до +20% бонус!
🚀 При пополнении от 10000₽ — статус VIP!

⚡ <b>Зачем пополнять?</b>
• Серверы приносят доход 24/7
• За 1 час работы сервера ты получаешь до 60₽ чистыми
• 100% окупаемость за 1.5 часа
• Реальные деньги на карту

Выбирай тариф:"""
    
    await callback.message.edit_text(text, reply_markup=deposit_kb())
    await callback.answer()

@dp.callback_query(F.data.startswith("dep_"))
async def deposit_amount(callback: types.CallbackQuery):
    if callback.data == "dep_custom":
        await callback.message.edit_text(
            "💬 <b>Введи свою сумму:</b>\n\n"
            "Отправь сообщение с суммой в рублях (от 50₽).\n"
            "Пример: <code>2500</code>",
            reply_markup=back_kb()
        )
        pending_payments[callback.from_user.id] = {"waiting": "custom_amount"}
        return
    
    amount = int(callback.data.split("_")[1])
    pkg = DEPOSIT_PACKAGES.get(str(amount))
    if not pkg:
        return
    
    label = f"dep_{callback.from_user.id}_{uuid.uuid4().hex[:10]}"
    pending_payments[label] = {
        "user_id": callback.from_user.id,
        "amount": amount,
        "neurons": pkg["neurons"],
        "bonus": pkg["bonus"]
    }
    
    # Сохраняем в БД
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO deposits (user_id, amount_rub, neurons_amount, label) VALUES (?, ?, ?, ?)",
            (callback.from_user.id, amount, pkg["neurons"] + pkg["bonus"], label)
        )
        await db.commit()
    
    pay_url = f"https://yoomoney.ru/transfer?quickpay=shop&receiver={YOOMONEY_WALLET}&sum={amount}&label={label}"
    
    bonus_text = f"\n🎁 <b>Бонус:</b> +{pkg['bonus']:,} 🧠" if pkg["bonus"] > 0 else ""
    total_neurons = pkg["neurons"] + pkg["bonus"]
    
    text = f"""💳 <b>Оплата {amount}₽</b> ({pkg['label']})

К зачислению: <b>{total_neurons:,} 🧠</b>{bonus_text}

💡 <b>При пополнении {amount}₽ ты получишь {total_neurons:,} нейронов.</b>
Сможешь купить серверы и начать зарабатывать!

📲 <b>Инструкция:</b>
1. Нажми кнопку «Оплатить»
2. Оплати удобным способом
3. Вернись сюда и нажми «Проверить оплату»
4. Нейроны зачислятся автоматически

⏱ Оплата действительна 30 минут"""
    
    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="💳 Оплатить", url=pay_url)],
        [types.InlineKeyboardButton(text="✅ Проверить оплату", callback_data=f"check_{label}")],
        [types.InlineKeyboardButton(text="❌ Отменить", callback_data=f"cancel_{label}")],
        [types.InlineKeyboardButton(text="◀️ В меню", callback_data="menu")]
    ])
    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()

@dp.callback_query(F.data.startswith("check_"))
async def check_payment(callback: types.CallbackQuery):
    label = callback.data.replace("check_", "")
    
    if label not in pending_payments:
        await callback.answer("⏳ Оплата не найдена. Если вы оплатили — подождите 1-2 минуты.", show_alert=True)
        return
    
    payment = pending_payments[label]
    
    # Проверка через API
    try:
        from yoomoney import Client
        client = Client(YOOMONEY_TOKEN)
        history = client.operation_history(label=label)
        
        for op in history.operations:
            if op.status == "success":
                total_neurons = payment["neurons"] + payment["bonus"]
                await update_balance(payment["user_id"], total_neurons)
                
                # Обновляем статистику пополнений
                async with aiosqlite.connect(DB_PATH) as db:
                    await db.execute(
                        "UPDATE users SET total_deposited = total_deposited + ? WHERE user_id = ?",
                        (payment["amount"], payment["user_id"])
                    )
                    await db.execute(
                        "UPDATE deposits SET status = 'success' WHERE label = ?",
                        (label,)
                    )
                    
                    # Реферальные начисления
                    cur = await db.execute("SELECT referrer_id FROM users WHERE user_id = ?", (payment["user_id"],))
                    row = await cur.fetchone()
                    if row and row[0]:
                        ref_id = row[0]
                        bonus_ref = int(payment["amount"] * NEURONS_PER_RUB * REF_LEVELS[1] / 100)
                        await db.execute(
                            "UPDATE users SET neurons = neurons + ? WHERE user_id = ?",
                            (bonus_ref, ref_id)
                        )
                        # Уведомление рефереру
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
        
        await callback.answer("⏳ Оплата ещё не поступила. Подожди 30 секунд.", show_alert=True)
    except Exception as e:
        await callback.answer(f"❌ Ошибка: {str(e)[:50]}", show_alert=True)

@dp.callback_query(F.data.startswith("cancel_"))
async def cancel_payment(callback: types.CallbackQuery):
    label = callback.data.replace("cancel_", "")
    pending_payments.pop(label, None)
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
        await callback.message.edit_text(
            f"💸 <b>Вывод средств</b>\n\n"
            f"💰 Доступно: <b>{gross_rub}₽</b> ({neurons:,} 🧠)\n"
            f"❌ Минимальная сумма вывода: <b>{MIN_WITHDRAW_RUB}₽</b>\n\n"
            f"📊 Нужно ещё: <b>{MIN_WITHDRAW_RUB - gross_rub}₽</b>\n\n"
            f"💡 Пополни баланс или заработай майнингом!",
            reply_markup=back_kb()
        )
    else:
        text = f"""💸 <b>Вывод средств</b>

💰 На балансе: <b>{neurons:,} нейронов</b>

Это эквивалент <b>{gross_rub}₽</b>.

Комиссия сервиса ({WITHDRAW_FEE_PERCENT}%): <b>{fee}₽</b>
К выплате: <b>{net_rub}₽</b>

❓ <b>Хотите вывести эти средства?</b>

Выплата производится администратором <b>вручную в течение 24 часов</b> на карту любого банка РФ."""
        
        kb = types.InlineKeyboardMarkup(inline_keyboard=[
            [types.InlineKeyboardButton(text="✅ ДА, ХОЧУ ВЫВЕСТИ", callback_data="withdraw_confirm")],
            [types.InlineKeyboardButton(text="◀️ Отмена", callback_data="menu")]
        ])
        await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()

@dp.callback_query(F.data == "withdraw_confirm")
async def withdraw_confirm(callback: types.CallbackQuery):
    pending_withdrawals[callback.from_user.id] = {"step": "wallet"}
    await callback.message.edit_text(
        "💳 <b>Введи номер карты или кошелька для перевода:</b>\n\n"
        "Пример: <code>2200123456789012</code>\n"
        "или ЮMoney: <code>4100118935779591</code>",
        reply_markup=types.InlineKeyboardMarkup(inline_keyboard=[
            [types.InlineKeyboardButton(text="◀️ Отмена", callback_data="menu")]
        ])
    )
    await callback.answer()

@dp.message()
async def handle_withdraw_input(message: types.Message):
    user_id = message.from_user.id
    
    # Кастомная сумма пополнения
    if user_id in pending_payments and pending_payments[user_id].get("waiting") == "custom_amount":
        try:
            amount = int(message.text)
            if amount < 50:
                await message.answer("❌ Минимум 50₽")
                return
            # Рассчитываем нейроны по среднему курсу
            neurons = int(amount * NEURONS_PER_RUB * 0.9)  # -10% скидка за кастом
            label = f"dep_{user_id}_{uuid.uuid4().hex[:10]}"
            pending_payments[label] = {
                "user_id": user_id,
                "amount": amount,
                "neurons": neurons,
                "bonus": 0
            }
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute(
                    "INSERT INTO deposits (user_id, amount_rub, neurons_amount, label) VALUES (?, ?, ?, ?)",
                    (user_id, amount, neurons, label)
                )
                await db.commit()
            
            pay_url = f"https://yoomoney.ru/transfer?quickpay=shop&receiver={YOOMONEY_WALLET}&sum={amount}&label={label}"
            kb = types.InlineKeyboardMarkup(inline_keyboard=[
                [types.InlineKeyboardButton(text="💳 Оплатить", url=pay_url)],
                [types.InlineKeyboardButton(text="✅ Проверить", callback_data=f"check_{label}")],
                [types.InlineKeyboardButton(text="◀️ В меню", callback_data="menu")]
            ])
            await message.answer(
                f"💳 Оплата <b>{amount}₽</b>\nК зачислению: <b>{neurons:,} 🧠</b>",
                reply_markup=kb
            )
            pending_payments.pop(user_id, None)
        except ValueError:
            await message.answer("❌ Введи число")
        return
    
    # Ввод реквизитов для вывода
    if user_id in pending_withdrawals:
        data = pending_withdrawals[user_id]
        if data["step"] == "wallet":
            data["wallet"] = message.text.strip()
            data["step"] = "bank"
            await message.answer(
                f"💳 Карта/кошелёк: <code>{data['wallet']}</code>\n\n"
                "🏦 <b>Теперь укажи название банка:</b>\n\n"
                "Пример: <code>Сбербанк</code>, <code>Тинькофф</code>, <code>ЮMoney</code>",
                reply_markup=types.InlineKeyboardMarkup(inline_keyboard=[
                    [types.InlineKeyboardButton(text="◀️ Отмена", callback_data="menu")]
                ])
            )
        elif data["step"] == "bank":
            data["bank"] = message.text.strip()
            
            user = await get_user(user_id)
            neurons = user[3]
            gross_rub = neurons // NEURONS_PER_RUB
            fee = int(gross_rub * WITHDRAW_FEE_PERCENT / 100)
            net_rub = gross_rub - fee
            
            # Списываем нейроны
            await update_balance(user_id, -(net_rub * NEURONS_PER_RUB + fee * NEURONS_PER_RUB))
            
            # Сохраняем заявку
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
                    f"💳 Карта/кошелёк: <code>{data['wallet']}</code>\n"
                    f"🏦 Банк: {data['bank']}\n"
                    f"📅 Заявка: {datetime.now().strftime('%d.%m.%Y %H:%M')}\n\n"
                    f"<b>Оплати вручную в течение 24 часов!</b>",
                    parse_mode="HTML"
                )
            except:
                pass
            
            await message.answer(
                f"✅ <b>Заявка #{wid} создана!</b>\n\n"
                f"💰 Сумма к выплате: <b>{net_rub}₽</b>\n"
                f"💳 Карта: <code>{data['wallet']}</code>\n"
                f"🏦 Банк: {data['bank']}\n\n"
                f"⏱ <b>Выплата в течение 24 часов.</b>\n"
                f"С твоего баланса списано: {(net_rub + fee) * NEURONS_PER_RUB:,} 🧠\n"
                f"Комиссия {WITHDRAW_FEE_PERCENT}% ({fee}₽) удержана.",
                reply_markup=main_menu_kb()
            )
            pending_withdrawals.pop(user_id, None)
        return

@dp.callback_query(F.data == "daily")
async def daily_callback(callback: types.CallbackQuery):
    user = await get_user(callback.from_user.id)
    last_bonus_str = user[10]  # last_bonus_date
    streak = user[11] or 0
    
    now = datetime.now()
    today = now.date().isoformat()
    
    if last_bonus_str == today:
        await callback.answer("⏳ Бонус уже получен сегодня! Приходи завтра.", show_alert=True)
        return
    
    new_streak = 1
    if last_bonus_str:
        last_date = datetime.fromisoformat(last_bonus_str).date()
        if (now.date() - last_date).days == 1:
            new_streak = streak + 1
        # Если пропустил день - streak сбрасывается
    
    streak_idx = min(new_streak - 1, len(DAILY_BONUS) - 1)
    bonus = DAILY_BONUS[streak_idx]
    
    async with aiosqlite.connect(DB_PATH) as db:
        await update_balance(callback.from_user.id, bonus)
        await db.execute(
            "UPDATE users SET last_bonus_date = ?, bonus_streak = ? WHERE user_id = ?",
            (today, new_streak, callback.from_user.id)
        )
        await db.commit()
    
    day_text = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
    await callback.answer(
        f"🎁 {day_text[streak_idx]} День: +{bonus:,} 🧠\n🔥 Streak: {new_streak} дней!",
        show_alert=True
    )

@dp.callback_query(F.data == "roulette")
async def roulette_callback(callback: types.CallbackQuery):
    user = await get_user(callback.from_user.id)
    
    if user[3] < 100:
        await callback.answer("❌ Нужно минимум 100 нейронов для ставки!", show_alert=True)
        return
    
    # Списываем ставку
    await update_balance(callback.from_user.id, -100)
    
    # Выбираем приз
    prizes = [p for p in ROULETTE_PRIZES]
    weights = [p[2] for p in prizes]
    prize = random.choices(prizes, weights=weights)[0]
    
    if prize[0] == "❌ Ничего":
        text = f"🎰 <b>Рулетка</b>\n\n😔 К сожалению, ты ничего не выиграл.\nПопробуй ещё раз!"
    elif prize[1] == "x2":
        # x2 бонус к следующему клику
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "UPDATE users SET roulette_streak = roulette_streak + 1 WHERE user_id = ?",
                (callback.from_user.id,)
            )
            await db.commit()
        text = f"🎰 <b>Рулетка</b>\n\n🎉 <b>ТЫ ВЫИГРАЛ x2 БОНУС!</b>\nСледующие 10 кликов дают x2 нейронов!"
    else:
        await update_balance(callback.from_user.id, prize[1])
        text = f"🎰 <b>Рулетка</b>\n\n🎉 <b>ТЫ ВЫИГРАЛ!</b>\n\n{prize[0]}\n💰 Зачислено на баланс!"
    
    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="🎰 Крутить ещё (100🧠)", callback_data="roulette")],
        [types.InlineKeyboardButton(text="◀️ В меню", callback_data="menu")]
    ])
    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()

@dp.callback_query(F.data == "referrals")
async def referrals_callback(callback: types.CallbackQuery):
    user = await get_user(callback.from_user.id)
    me = await bot.get_me()
    refs = await get_referrals_count(callback.from_user.id)
    
    text = f"""🤝 <b>Реферальная система</b>

💰 <b>Твоя ссылка:</b>
<code>https://t.me/{me.username}?start={callback.from_user.id}</code>

📊 <b>Зарабатывай с нами:</b>
• 1 уровень — <b>7%</b> от пополнений рефералов
• 2 уровень — <b>3%</b>
• 3 уровень — <b>1%</b>
+ <b>1 000 🧠</b> за каждого приглашённого!

📈 <b>Твои рефералы:</b>
• 1 уровень: <b>{refs.get(1, 0)}</b> чел.
• 2 уровень: <b>{refs.get(2, 0)}</b> чел.
• 3 уровень: <b>{refs.get(3, 0)}</b> чел.

💡 <b>Пример:</b> Если твой реферал пополнит на 1000₽, ты получишь <b>7 000 🧠 (70₽)</b> моментально!

🔗 Поделись ссылкой с друзьями и зарабатывай!"""
    
    await callback.message.edit_text(text, reply_markup=back_kb())
    await callback.answer()

@dp.callback_query(F.data == "top")
async def top_callback(callback: types.CallbackQuery):
    top = await get_top(10)
    user = await get_user(callback.from_user.id)
    user_rank = "—"
    
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT COUNT(*) + 1 FROM users WHERE total_earned > ?",
            (user[6],)
        )
        user_rank = (await cur.fetchone())[0]
    
    text = f"🏆 <b>ТОП-10 игроков</b>\nТвоё место: <b>#{user_rank}</b>\n\n"
    
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
    
    text = f"""📊 <b>Твоя статистика</b>

💰 Баланс: <b>{user[3]:,}</b> 🧠
📈 Доход/мин: <b>{income_per_min:,}</b> 🧠
⏳ Доход/час: <b>{income_per_hour:,}</b> 🧠
📅 Доход/день: <b>{income_per_day:,}</b> 🧠

💎 Всего заработано: <b>{user[6]:,}</b> 🧠
💸 Всего пополнено: <b>{user[4]:,}</b>₽
💰 Всего выведено: <b>{user[5]:,}</b>₽

🌐 <b>Глобальная статистика:</b>
👥 Игроков онлайн: <b>{total_users}</b>
💰 Всего нейронов в игре: <b>{total_neurons or 0:,}</b>
💵 Всего пополнено: <b>{total_dep or 0:,}</b>₽"""
    
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
    
    servers = await get_user_servers(user_id)
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
        streak=user[11] or 0,
        emp_x=5
    )
    
    if edit:
        await message.edit_text(text, reply_markup=main_menu_kb())
    else:
        await message.answer(text, reply_markup=main_menu_kb())

# ============================================================
# ФОНОВЫЕ ЗАДАЧИ
# ============================================================
async def income_loop():
    """Начисление дохода каждую минуту"""
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
