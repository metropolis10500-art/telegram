import asyncio
import logging
import os
import uuid
from datetime import datetime, timedelta
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from yoomoney import Client

import aiosqlite

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN") or "8800941405:AAH0TZbP48M5grkVxZ-tvP7lxK72eTSg4yc"
ADMIN_ID = int(os.getenv("ADMIN_ID", "5494544187"))
YOOMONEY_WALLET = "4100118935779591"
YOOMONEY_TOKEN = "5133D1719448E2A5E1083A0FC605E369944CBB992B1D4490F13E2D4636C03191"
DB_PATH = "autogram.db"

NEURONS_PER_RUB = 100
MIN_WITHDRAW_RUB = 3000
WITHDRAW_FEE_PERCENT = 15

# ТАРИФЫ
DEPOSIT_PACKAGES = {
    "1000":  {"neurons": 80000,    "bonus": 0,      "label": "🟢 СТАРТ",     "income_per_day": 12000,  "popular": False},
    "3000":  {"neurons": 270000,   "bonus": 30000,  "label": "🔵 БАЗОВЫЙ",   "income_per_day": 40000,  "popular": True},
    "5000":  {"neurons": 500000,   "bonus": 100000, "label": "🟣 СТАНДАРТ",  "income_per_day": 72000,  "popular": False},
    "10000": {"neurons": 1100000,  "bonus": 300000, "label": "🟠 ПРОФИ",     "income_per_day": 150000, "popular": False},
    "30000": {"neurons": 3600000,  "bonus": 1200000,"label": "🔴 БИЗНЕС",    "income_per_day": 500000, "popular": False},
    "50000": {"neurons": 6500000,  "bonus": 2500000,"label": "⚫ VIP",        "income_per_day": 900000, "popular": False}
}

SERVERS = {
    "raspberry":  {"name": "🍓 Raspberry Pi",        "price": 5000,        "income": 80},
    "laptop":     {"name": "💻 Игровой ноутбук",     "price": 50000,       "income": 900},
    "pc":         {"name": "🖥 Игровой ПК",          "price": 500000,      "income": 10000},
    "server":     {"name": "🗄 Серверная стойка",    "price": 5000000,     "income": 120000},
    "gpu":        {"name": "⚡ RTX 4090",            "price": 50000000,    "income": 1500000},
    "datacenter": {"name": "🏢 Дата-центр",          "price": 500000000,   "income": 18000000}
}

EMPLOYEES = {
    "junior":   {"name": "👨‍💻 Junior",   "price": 10000,        "multiplier": 1.5},
    "middle":   {"name": "👩‍💻 Middle",   "price": 200000,       "multiplier": 2.0},
    "senior":   {"name": "🧑‍💻 Senior",   "price": 3000000,      "multiplier": 3.0},
    "lead":     {"name": "🎯 Lead",      "price": 50000000,     "multiplier": 5.0},
    "cto":      {"name": "🤖 CTO",       "price": 1000000000,   "multiplier": 10.0}
}

UPGRADES = {
    "cooling":  {"name": "❄️ Охлаждение",   "price": 30000,      "multiplier": 1.20, "desc": "+20%"},
    "net":      {"name": "🌐 Сеть",         "price": 500000,     "multiplier": 1.30, "desc": "+30%"},
    "quantum":  {"name": "⚛️ Квант",       "price": 10000000,   "multiplier": 1.50, "desc": "+50%"},
    "neural":   {"name": "🧠 Нейро",       "price": 250000000,  "multiplier": 2.00, "desc": "+100%"}
}

REF_LEVELS = {1: 10, 2: 5, 3: 2}
REF_BONUS_NEURONS = 5000
DAILY_BONUS = [500, 1000, 2500, 5000, 10000, 25000, 50000, 100000, 250000, 500000]

# ============================================================
# FSM Состояния (Машина состояний)
# ============================================================
class WithdrawState(StatesGroup):
    waiting_for_wallet = State()
    waiting_for_bank = State()

class DepositState(StatesGroup):
    waiting_for_amount = State()

# ============================================================
# БАЗА ДАННЫХ
# ============================================================
async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('''CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY, username TEXT, first_name TEXT,
            neurons INTEGER DEFAULT 1000, total_deposited REAL DEFAULT 0,
            total_withdrawn REAL DEFAULT 0, total_earned INTEGER DEFAULT 0,
            total_spent INTEGER DEFAULT 0, referrer_id INTEGER,
            reg_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_bonus_date TEXT, bonus_streak INTEGER DEFAULT 0
        )''')
        await db.execute('''CREATE TABLE IF NOT EXISTS user_servers (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, server_type TEXT
        )''')
        await db.execute('''CREATE TABLE IF NOT EXISTS user_employees (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, emp_type TEXT
        )''')
        await db.execute('''CREATE TABLE IF NOT EXISTS user_upgrades (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, upgrade_type TEXT,
            UNIQUE(user_id, upgrade_type)
        )''')
        await db.execute('''CREATE TABLE IF NOT EXISTS withdrawals (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER,
            amount_rub REAL, neurons_amount INTEGER, wallet TEXT, bank TEXT,
            status TEXT DEFAULT 'pending', request_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        await db.execute('''CREATE TABLE IF NOT EXISTS deposits (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER,
            amount_rub REAL, neurons_amount INTEGER, label TEXT UNIQUE,
            status TEXT DEFAULT 'pending', created TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        await db.execute('''CREATE TABLE IF NOT EXISTS referrals (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER,
            level INTEGER, referral_id INTEGER,
            UNIQUE(user_id, level, referral_id)
        )''')
        await db.commit()

async def get_user(user_id):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        return await cur.fetchone()

async def add_user(user_id, username, first_name, referrer_id=None):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,))
        if not await cur.fetchone():
            await db.execute(
                "INSERT INTO users (user_id, username, first_name, referrer_id) VALUES (?, ?, ?, ?)",
                (user_id, username or "", first_name or "Игрок", referrer_id)
            )
            if referrer_id and referrer_id != user_id:
                await db.execute("UPDATE users SET neurons = neurons + ? WHERE user_id = ?", (REF_BONUS_NEURONS, referrer_id))
                cur2 = await db.execute("SELECT referrer_id FROM users WHERE user_id = ?", (referrer_id,))
                ref2 = await cur2.fetchone()
                if ref2 and ref2[0]:
                    cur3 = await db.execute("SELECT referrer_id FROM users WHERE user_id = ?", (ref2[0],))
                    ref3 = await cur3.fetchone()
                    if ref3 and ref3[0]:
                        await db.execute("INSERT OR IGNORE INTO referrals (user_id, level, referral_id) VALUES (?, ?, ?)", (ref3[0], 3, user_id))
                await db.execute("INSERT OR IGNORE INTO referrals (user_id, level, referral_id) VALUES (?, ?, ?)", (referrer_id, 1, user_id))
                if ref2 and ref2[0] and ref2[0] != user_id:
                    await db.execute("INSERT OR IGNORE INTO referrals (user_id, level, referral_id) VALUES (?, ?, ?)", (ref2[0], 2, user_id))
        await db.commit()

async def update_balance(user_id, delta):
    async with aiosqlite.connect(DB_PATH) as db:
        if delta > 0:
            await db.execute("UPDATE users SET neurons = neurons + ?, total_earned = total_earned + ? WHERE user_id = ?", (delta, delta, user_id))
        else:
            await db.execute("UPDATE users SET neurons = neurons + ?, total_spent = total_spent + ? WHERE user_id = ?", (delta, abs(delta), user_id))
        await db.commit()

async def get_user_servers(user_id):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT server_type, COUNT(*) FROM user_servers WHERE user_id = ? GROUP BY server_type", (user_id,))
        return dict(await cur.fetchall())

async def get_user_employees(user_id):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT emp_type, COUNT(*) FROM user_employees WHERE user_id = ? GROUP BY emp_type", (user_id,))
        return dict(await cur.fetchall())

async def get_user_upgrades(user_id):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT upgrade_type FROM user_upgrades WHERE user_id = ?", (user_id,))
        return set(row[0] for row in await cur.fetchall())

async def calculate_income(user_id):
    servers = await get_user_servers(user_id)
    employees = await get_user_employees(user_id)
    upgrades = await get_user_upgrades(user_id)
    
    base_income = sum(SERVERS[s]["income"] * count for s, count in servers.items())
    emp_mult = 1.0
    for e, count in employees.items():
        emp_mult *= EMPLOYEES[e]["multiplier"] ** count
    upg_mult = 1.0
    for u in upgrades:
        upg_mult *= UPGRADES[u]["multiplier"]
    
    final = int(base_income * emp_mult * upg_mult)
    return final, final * 60, final * 60 * 24

async def get_referrals_count(user_id):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT level, COUNT(*) FROM referrals WHERE user_id = ? GROUP BY level", (user_id,))
        return dict(await cur.fetchall())

async def get_top(limit=10):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT first_name, username, total_earned FROM users ORDER BY total_earned DESC LIMIT ?", (limit,))
        return await cur.fetchall()

# ============================================================
# БОТ
# ============================================================
logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

# ============================================================
# ТЕКСТЫ И КЛАВИАТУРЫ
# ============================================================
WELCOME = """🧠 <b>AutoGram AI</b> — зарабатывай на нейросетях!

💰 <b>Здесь зарабатывают реальные деньги!</b>

<b>Как это работает:</b>
1️⃣ Пополни баланс
2️⃣ Купи серверы — они генерируют нейроны 24/7
3️⃣ Нейроны = реальные рубли
4️⃣ Выводи от 3000₽ на карту

🚀 <b>Стартовый бонус: 1000 нейронов!</b>

👇 Нажми «Пополнить» чтобы начать:"""

MAIN_MENU = """🧠 <b>AutoGram AI</b>

💰 <b>Баланс:</b> {neurons:,} нейронов ({rubles}₽)
📈 <b>Доход:</b> {income_per_min:,}/мин · {income_per_hour:,}/час
⚡ <b>Множитель:</b> x{total_multiplier:.2f}
👥 <b>Рефералы:</b> {refs_1}·{refs_2}·{refs_3}"""

def main_menu_kb():
    return types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="💰 ПОПОЛНИТЬ", callback_data="deposit"),
         types.InlineKeyboardButton(text="💸 ВЫВЕСТИ", callback_data="withdraw")],
        [types.InlineKeyboardButton(text="🖥 Серверы (доход)", callback_data="shop_servers")],
        [types.InlineKeyboardButton(text="👨‍💻 Сотрудники (x множитель)", callback_data="shop_employees")],
        [types.InlineKeyboardButton(text="⚡ Улучшения (навсегда)", callback_data="shop_upgrades")],
        [types.InlineKeyboardButton(text="👤 Профиль", callback_data="profile"),
         types.InlineKeyboardButton(text="🏆 ТОП", callback_data="top")],
        [types.InlineKeyboardButton(text="🎁 Бонус", callback_data="daily"),
         types.InlineKeyboardButton(text="🤝 Рефералы", callback_data="referrals")]
    ])

def back_kb():
    return types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="◀️ Назад", callback_data="menu")]
    ])

def servers_shop_kb(user_balance):
    buttons = []
    for key, srv in SERVERS.items():
        can_buy = "✅" if user_balance >= srv["price"] else "🔒"
        income_day = srv["income"] * 60 * 24
        buttons.append([types.InlineKeyboardButton(
            text=f"{can_buy} {srv['name']} | {srv['price']:,}🧠 → +{income_day:,}🧠/день",
            callback_data=f"buy_srv_{key}"
        )])
    buttons.append([types.InlineKeyboardButton(text="◀️ Назад", callback_data="menu")])
    return types.InlineKeyboardMarkup(inline_keyboard=buttons)

def employees_shop_kb(user_balance):
    buttons = []
    for key, emp in EMPLOYEES.items():
        can_buy = "✅" if user_balance >= emp["price"] else "🔒"
        buttons.append([types.InlineKeyboardButton(
            text=f"{can_buy} {emp['name']} | {emp['price']:,}🧠 → x{emp['multiplier']}",
            callback_data=f"buy_emp_{key}"
        )])
    buttons.append([types.InlineKeyboardButton(text="◀️ Назад", callback_data="menu")])
    return types.InlineKeyboardMarkup(inline_keyboard=buttons)

def upgrades_shop_kb(user_balance, owned):
    buttons = []
    for key, upg in UPGRADES.items():
        if key not in owned:
            can_buy = "✅" if user_balance >= upg["price"] else "🔒"
            buttons.append([types.InlineKeyboardButton(
                text=f"{can_buy} {upg['name']} | {upg['price']:,}🧠 → {upg['desc']}",
                callback_data=f"buy_upg_{key}"
            )])
        else:
            buttons.append([types.InlineKeyboardButton(text=f"✅ {upg['name']} (куплено)", callback_data="noop")])
    buttons.append([types.InlineKeyboardButton(text="◀️ Назад", callback_data="menu")])
    return types.InlineKeyboardMarkup(inline_keyboard=buttons)

def deposit_kb():
    buttons = []
    for amount, pkg in DEPOSIT_PACKAGES.items():
        total_neurons = pkg["neurons"] + pkg["bonus"]
        income_rub_day = pkg["income_per_day"] // 100
        popular = " 🔥" if pkg["popular"] else ""
        text = f"{pkg['label']}{popular}\n💎 {amount}₽ → {total_neurons:,}🧠\n📈 ~{income_rub_day}₽/день"
        buttons.append([types.InlineKeyboardButton(text=text, callback_data=f"dep_{amount}")])
    
    # ДОБАВЛЕНО: Кнопка ввода своей суммы
    buttons.append([types.InlineKeyboardButton(text="✍️ Ввести свою сумму", callback_data="dep_custom")])
    buttons.append([types.InlineKeyboardButton(text="◀️ Назад", callback_data="menu")])
    return types.InlineKeyboardMarkup(inline_keyboard=buttons)

# ============================================================
# ХЕНДЛЕРЫ
# ============================================================
@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    args = message.text.split()
    referrer_id = None
    if len(args) > 1 and args[1].isdigit():
        ref = int(args[1])
        if ref != message.from_user.id:
            referrer_id = ref
    
    user = await get_user(message.from_user.id)
    if not user:
        await add_user(message.from_user.id, message.from_user.username, message.from_user.first_name, referrer_id)
        if referrer_id:
            try:
                await bot.send_message(referrer_id, f"🎉 Новый реферал: {message.from_user.first_name}\n💰 Бонус: +{REF_BONUS_NEURONS:,} 🧠")
            except: pass
    
    await message.answer(WELCOME, reply_markup=main_menu_kb())

@dp.callback_query(F.data == "menu")
async def menu_callback(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await show_main_menu(callback.message, callback.from_user.id, edit=True)
    await callback.answer()

# === МАГАЗИНЫ === (Оставлены как есть, логика работает верно)
@dp.callback_query(F.data == "shop_servers")
async def shop_servers(callback: types.CallbackQuery):
    user = await get_user(callback.from_user.id)
    _, income_per_hour, _ = await calculate_income(callback.from_user.id)
    text = f"🖥 <b>МАГАЗИН СЕРВЕРОВ</b>\n💰 Баланс: <b>{user[3]:,}</b> 🧠\n📈 Сейчас качаешь: <b>{income_per_hour:,}</b> 🧠/час\n\nСервер работает ВЕЧНО и приносит доход каждую минуту."
    await callback.message.edit_text(text, reply_markup=servers_shop_kb(user[3]))

@dp.callback_query(F.data.startswith("buy_srv_"))
async def buy_server(callback: types.CallbackQuery):
    srv_type = callback.data.split("_")[2]
    srv = SERVERS.get(srv_type)
    if not srv: return
    user = await get_user(callback.from_user.id)
    
    if user[3] < srv["price"]:
        await callback.answer(f"❌ Не хватает {srv['price'] - user[3]:,} 🧠", show_alert=True)
        return
    
    async with aiosqlite.connect(DB_PATH) as db:
        await update_balance(callback.from_user.id, -srv["price"])
        await db.execute("INSERT INTO user_servers (user_id, server_type) VALUES (?, ?)", (callback.from_user.id, srv_type))
        await db.commit()
    
    _, new_hour, _ = await calculate_income(callback.from_user.id)
    await callback.answer(f"✅ {srv['name']} куплен!\n📈 Новый доход: {new_hour:,} 🧠/час", show_alert=True)
    await shop_servers(callback) # Обновляем клавиатуру

@dp.callback_query(F.data == "shop_employees")
async def shop_employees(callback: types.CallbackQuery):
    user = await get_user(callback.from_user.id)
    text = f"👨‍💻 <b>СОТРУДНИКИ</b>\n💰 Баланс: <b>{user[3]:,}</b> 🧠\n\nСотрудники УМНОЖАЮТ доход от серверов!"
    await callback.message.edit_text(text, reply_markup=employees_shop_kb(user[3]))

@dp.callback_query(F.data.startswith("buy_emp_"))
async def buy_employee(callback: types.CallbackQuery):
    emp_type = callback.data.split("_")[2]
    emp = EMPLOYEES.get(emp_type)
    if not emp: return
    user = await get_user(callback.from_user.id)
    
    if user[3] < emp["price"]:
        await callback.answer(f"❌ Не хватает {emp['price'] - user[3]:,} 🧠", show_alert=True)
        return
    
    async with aiosqlite.connect(DB_PATH) as db:
        await update_balance(callback.from_user.id, -emp["price"])
        await db.execute("INSERT INTO user_employees (user_id, emp_type) VALUES (?, ?)", (callback.from_user.id, emp_type))
        await db.commit()
    
    new_min, _, _ = await calculate_income(callback.from_user.id)
    await callback.answer(f"✅ {emp['name']} нанят! Множитель x{emp['multiplier']}\n💵 Доход: {new_min:,} 🧠/мин", show_alert=True)
    await shop_employees(callback)

@dp.callback_query(F.data == "shop_upgrades")
async def shop_upgrades(callback: types.CallbackQuery):
    user = await get_user(callback.from_user.id)
    owned = await get_user_upgrades(callback.from_user.id)
    text = f"⚡ <b>УЛУЧШЕНИЯ</b>\n💰 Баланс: <b>{user[3]:,}</b> 🧠\n\nПостоянный буст к доходу НАВСЕГДА!"
    await callback.message.edit_text(text, reply_markup=upgrades_shop_kb(user[3], owned))

@dp.callback_query(F.data.startswith("buy_upg_"))
async def buy_upgrade(callback: types.CallbackQuery):
    upg_type = callback.data.split("_")[2]
    upg = UPGRADES.get(upg_type)
    if not upg: return
    user = await get_user(callback.from_user.id)
    owned = await get_user_upgrades(callback.from_user.id)
    
    if upg_type in owned:
        await callback.answer("❌ Уже куплено!", show_alert=True)
        return
    if user[3] < upg["price"]:
        await callback.answer(f"❌ Не хватает {upg['price'] - user[3]:,} 🧠", show_alert=True)
        return
    
    async with aiosqlite.connect(DB_PATH) as db:
        await update_balance(callback.from_user.id, -upg["price"])
        await db.execute("INSERT INTO user_upgrades (user_id, upgrade_type) VALUES (?, ?)", (callback.from_user.id, upg_type))
        await db.commit()
    
    await callback.answer(f"✅ {upg['name']} установлен! {upg['desc']} к доходу", show_alert=True)
    await shop_upgrades(callback)

# ============================================================
# ПОПОЛНЕНИЕ (ИСПРАВЛЕНО)
# ============================================================
@dp.callback_query(F.data == "deposit")
async def deposit_callback(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    text = "💰 <b>ПОПОЛНЕНИЕ БАЛАНСА</b>\n\n🎯 <b>Выбери тариф — чем больше, тем выгоднее:</b>"
    await callback.message.edit_text(text, reply_markup=deposit_kb())

@dp.callback_query(F.data.startswith("dep_"))
async def deposit_amount(callback: types.CallbackQuery, state: FSMContext):
    if callback.data == "dep_custom":
        await callback.message.edit_text("💬 <b>Введи сумму в рублях (от 1000₽):</b>", reply_markup=back_kb())
        await state.set_state(DepositState.waiting_for_amount)
        return
    
    amount_str = callback.data.split("_")[1]
    amount = int(amount_str)
    pkg = DEPOSIT_PACKAGES.get(amount_str)
    
    label = f"autogr_{uuid.uuid4().hex[:12]}"
    total_neurons = pkg["neurons"] + pkg["bonus"]
    
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO deposits (user_id, amount_rub, neurons_amount, label) VALUES (?, ?, ?, ?)",
                         (callback.from_user.id, amount, total_neurons, label))
        await db.commit()
    
    pay_url = f"https://yoomoney.ru/transfer?quickpay=shop&receiver={YOOMONEY_WALLET}&sum={amount}&label={label}"
    bonus_text = f"\n🎁 Бонус: +{pkg['bonus']:,} 🧠" if pkg["bonus"] > 0 else ""
    
    # ИСПРАВЛЕНИЕ: Добавлена кнопка "Проверить оплату"
    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text=f"💳 ОПЛАТИТЬ {amount}₽", url=pay_url)],
        [types.InlineKeyboardButton(text="🔄 Проверить оплату", callback_data=f"check_{label}")],
        [types.InlineKeyboardButton(text="◀️ К тарифам", callback_data="deposit")]
    ])
    await callback.message.edit_text(f"💳 <b>ОПЛАТА {amount}₽</b>\n📦 Получишь: <b>{total_neurons:,} 🧠</b>{bonus_text}", reply_markup=kb, disable_web_page_preview=True)

@dp.message(DepositState.waiting_for_amount)
async def custom_amount_handler(message: types.Message, state: FSMContext):
    try:
        amount = int(message.text.strip())
        if amount < 1000:
            await message.answer("❌ Минимальная сумма пополнения — 1000₽. Введите другую сумму:")
            return
        
        neurons = int(amount * NEURONS_PER_RUB * 0.85) # Немного меньше выгоды, чем в пакетах
        label = f"autogr_{uuid.uuid4().hex[:12]}"
        
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("INSERT INTO deposits (user_id, amount_rub, neurons_amount, label) VALUES (?, ?, ?, ?)",
                             (message.from_user.id, amount, neurons, label))
            await db.commit()
        
        pay_url = f"https://yoomoney.ru/transfer?quickpay=shop&receiver={YOOMONEY_WALLET}&sum={amount}&label={label}"
        kb = types.InlineKeyboardMarkup(inline_keyboard=[
            [types.InlineKeyboardButton(text=f"💳 ОПЛАТИТЬ {amount}₽", url=pay_url)],
            [types.InlineKeyboardButton(text="🔄 Проверить оплату", callback_data=f"check_{label}")],
            [types.InlineKeyboardButton(text="◀️ Назад", callback_data="deposit")]
        ])
        await message.answer(f"💳 <b>ОПЛАТА {amount}₽</b>\n\n📦 Получишь: <b>{neurons:,} 🧠</b>", reply_markup=kb)
        await state.clear()
    except ValueError:
        await message.answer("❌ Пожалуйста, введите число (например, 1500).")

# ============================================================
# ПРОВЕРКА ОПЛАТЫ (ИСПРАВЛЕНО)
# ============================================================
@dp.callback_query(F.data.startswith("check_"))
async def check_payment(callback: types.CallbackQuery):
    label = callback.data.replace("check_", "")
    
    # Берем данные из БД вместо оперативной памяти (устойчиво к перезапускам)
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT amount_rub, neurons_amount, status FROM deposits WHERE label = ? AND user_id = ?", (label, callback.from_user.id))
        deposit = await cur.fetchone()
        
        if not deposit:
            await callback.answer("❌ Платёж не найден.", show_alert=True)
            return
        
        amount, neurons, status = deposit
        if status == 'success':
            await callback.answer("✅ Этот платёж уже зачислен!", show_alert=True)
            return

    try:
        client = Client(YOOMONEY_TOKEN)
        history = client.operation_history(label=label)
        
        for op in history.operations:
            if op.status == "success":
                async with aiosqlite.connect(DB_PATH) as db:
                    await db.execute("UPDATE deposits SET status = 'success' WHERE label = ?", (label,))
                    await db.execute("UPDATE users SET total_deposited = total_deposited + ? WHERE user_id = ?", (amount, callback.from_user.id))
                    await update_balance(callback.from_user.id, neurons)
                    
                    # Начисление рефералам
                    cur = await db.execute("SELECT referrer_id FROM users WHERE user_id = ?", (callback.from_user.id,))
                    row = await cur.fetchone()
                    if row and row[0]:
                        ref_bonus = int(amount * NEURONS_PER_RUB * REF_LEVELS[1] / 100)
                        await db.execute("UPDATE users SET neurons = neurons + ? WHERE user_id = ?", (ref_bonus, row[0]))
                    await db.commit()
                
                await callback.answer(f"✅ Оплата получена! Баланс пополнен на {neurons:,} 🧠", show_alert=True)
                await show_main_menu(callback.message, callback.from_user.id, edit=True)
                return
                
        await callback.answer("⏳ Оплата ещё не поступила. Подожди 30-60 секунд и нажми снова.", show_alert=True)
    except Exception as e:
        await callback.answer(f"❌ Ошибка проверки YooMoney: {str(e)[:80]}", show_alert=True)

# ============================================================
# ВЫВОД СРЕДСТВ (ПЕРЕВЕДЕН НА FSM)
# ============================================================
@dp.callback_query(F.data == "withdraw")
async def withdraw_callback(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    user = await get_user(callback.from_user.id)
    neurons = user[3]
    gross_rub = neurons // NEURONS_PER_RUB
    fee = int(gross_rub * WITHDRAW_FEE_PERCENT / 100)
    net_rub = gross_rub - fee
    
    if gross_rub < MIN_WITHDRAW_RUB:
        needed = MIN_WITHDRAW_RUB - gross_rub
        await callback.message.edit_text(
            f"💸 <b>ВЫВОД СРЕДСТВ</b>\n\n💰 Доступно: <b>{gross_rub}₽</b>\n❌ Минимум для вывода: <b>{MIN_WITHDRAW_RUB}₽</b>\n\n📊 Нужно ещё: <b>{needed}₽</b>", reply_markup=back_kb())
    else:
        text = f"💸 <b>ВЫВОД СРЕДСТВ</b>\n\n💰 Баланс: <b>{neurons:,}</b> 🧠\n💵 К выплате: <b>{net_rub}₽</b> (комиссия {fee}₽)\n\n<b>Хочешь вывести?</b>"
        kb = types.InlineKeyboardMarkup(inline_keyboard=[
            [types.InlineKeyboardButton(text=f"✅ ДА, ВЫВЕСТИ {net_rub}₽", callback_data="withdraw_confirm")],
            [types.InlineKeyboardButton(text="◀️ Отмена", callback_data="menu")]
        ])
        await callback.message.edit_text(text, reply_markup=kb)

@dp.callback_query(F.data == "withdraw_confirm")
async def withdraw_confirm(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(WithdrawState.waiting_for_wallet)
    await callback.message.edit_text("💳 <b>Введи номер карты или кошелька:</b>", reply_markup=back_kb())

@dp.message(WithdrawState.waiting_for_wallet)
async def withdraw_wallet_step(message: types.Message, state: FSMContext):
    wallet = message.text.strip()
    if len(wallet) < 10:
        await message.answer("❌ Слишком короткий номер. Введите корректный номер карты/кошелька:")
        return
    
    await state.update_data(wallet=wallet)
    await state.set_state(WithdrawState.waiting_for_bank)
    await message.answer(f"💳 Карта: <code>{wallet}</code>\n\n🏦 <b>Укажи название банка (например, Сбербанк):</b>", reply_markup=back_kb())

@dp.message(WithdrawState.waiting_for_bank)
async def withdraw_bank_step(message: types.Message, state: FSMContext):
    bank = message.text.strip()
    data = await state.get_data()
    wallet = data['wallet']
    user_id = message.from_user.id
    
    user = await get_user(user_id)
    neurons = user[3]
    gross_rub = neurons // NEURONS_PER_RUB
    fee = int(gross_rub * WITHDRAW_FEE_PERCENT / 100)
    net_rub = gross_rub - fee
    
    if gross_rub < MIN_WITHDRAW_RUB: # Защита от изменения баланса во время ввода
        await message.answer("❌ Ошибка: Недостаточно средств на балансе.")
        await state.clear()
        return

    # Списываем баланс
    await update_balance(user_id, -(neurons)) # Списываем все нейроны
    
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "INSERT INTO withdrawals (user_id, amount_rub, neurons_amount, wallet, bank) VALUES (?, ?, ?, ?, ?) RETURNING id",
            (user_id, net_rub, neurons, wallet, bank))
        wid = (await cur.fetchone())[0]
        await db.execute("UPDATE users SET total_withdrawn = total_withdrawn + ? WHERE user_id = ?", (net_rub, user_id))
        await db.commit()
    
    try:
        await bot.send_message(ADMIN_ID, f"🔔 <b>ЗАЯВКА НА ВЫВОД #{wid}</b>\n\n👤 {user[2]} (@{user[1] or '—'})\n🆔 <code>{user_id}</code>\n💰 Сумма: <b>{net_rub}₽</b>\n💳 Карта: <code>{wallet}</code>\n🏦 Банк: {bank}\n\n<b>⚠️ Оплати в течение 24 часов!</b>")
    except: pass
    
    await message.answer(f"✅ <b>Заявка #{wid} создана!</b>\n\n💸 К выплате: <b>{net_rub}₽</b>\n💳 Карта: <code>{wallet}</code>\n🏦 Банк: {bank}\n\n⏱ Ожидайте выплату в течение 24 часов.", reply_markup=main_menu_kb())
    await state.clear()


# Остальные функции (daily, referrals, top, profile) остаются без изменений
@dp.callback_query(F.data == "profile")
async def profile_callback(callback: types.CallbackQuery):
    user = await get_user(callback.from_user.id)
    me = await bot.get_me()
    text = f"👤 <b>Профиль</b>\n🆔 ID: <code>{user[0]}</code>\n👤 {user[2]} (@{user[1] or 'нет'})\n\n💰 Баланс: <b>{user[3]:,}</b> 🧠\n💎 Заработано: {user[6]:,} 🧠\n\n🤝 <b>Реферальная ссылка:</b>\n<code>https://t.me/{me.username}?start={user[0]}</code>"
    await callback.message.edit_text(text, reply_markup=back_kb())

@dp.callback_query(F.data == "daily")
async def daily_callback(callback: types.CallbackQuery):
    user = await get_user(callback.from_user.id)
    today = datetime.now().date().isoformat()
    if user[10] == today:
        await callback.answer("⏳ Уже получил сегодня!", show_alert=True)
        return
    
    new_streak = (user[11] + 1) if user[10] and (datetime.now().date() - datetime.fromisoformat(user[10]).date()).days == 1 else 1
    bonus = DAILY_BONUS[min(new_streak - 1, len(DAILY_BONUS) - 1)]
    
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET last_bonus_date = ?, bonus_streak = ?, neurons = neurons + ? WHERE user_id = ?", (today, new_streak, bonus, callback.from_user.id))
        await db.commit()
    await callback.answer(f"🎁 День {new_streak}: +{bonus:,} 🧠", show_alert=True)

@dp.callback_query(F.data == "referrals")
async def referrals_callback(callback: types.CallbackQuery):
    me = await bot.get_me()
    refs = await get_referrals_count(callback.from_user.id)
    text = f"🤝 <b>РЕФЕРАЛЫ</b>\n💰 <b>Твоя ссылка:</b>\n<code>https://t.me/{me.username}?start={callback.from_user.id}</code>\n\nУровни: 1 ур: {refs.get(1, 0)}, 2 ур: {refs.get(2, 0)}, 3 ур: {refs.get(3, 0)}"
    await callback.message.edit_text(text, reply_markup=back_kb())

@dp.callback_query(F.data == "top")
async def top_callback(callback: types.CallbackQuery):
    top = await get_top(10)
    text = "🏆 <b>ТОП-10 ИГРОКОВ</b>\n\n"
    for i, (name, username, earned) in enumerate(top, 1):
        text += f"{i}. {name} — <b>{earned:,}</b> 🧠\n"
    await callback.message.edit_text(text, reply_markup=back_kb())

@dp.callback_query(F.data == "noop")
async def noop(callback: types.CallbackQuery):
    await callback.answer()

async def show_main_menu(message, user_id, edit=False):
    user = await get_user(user_id)
    income_per_min, income_per_hour, _ = await calculate_income(user_id)
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
        neurons=user[3], rubles=rubles, income_per_min=income_per_min, income_per_hour=income_per_hour,
        total_multiplier=total_mult, refs_1=refs.get(1, 0), refs_2=refs.get(2, 0), refs_3=refs.get(3, 0)
    )
    
    if edit: await message.edit_text(text, reply_markup=main_menu_kb())
    else: await message.answer(text, reply_markup=main_menu_kb())

# ============================================================
# ФОНОВЫЕ ЗАДАЧИ
# ============================================================
async def income_loop():
    """Фоновое начисление баланса. Оптимизировано для снижения нагрузки на БД."""
    while True:
        try:
            # Делаем всё внутри ОДНОЙ сессии БД, а не открываем/закрываем её для каждого юзера
            async with aiosqlite.connect(DB_PATH) as db:
                cur = await db.execute("SELECT user_id FROM users")
                users = await cur.fetchall()
                
                for (user_id,) in users:
                    income, _, _ = await calculate_income(user_id)
                    if income > 0:
                        await db.execute("UPDATE users SET neurons = neurons + ?, total_earned = total_earned + ? WHERE user_id = ?", (income, income, user_id))
                await db.commit()
        except Exception as e:
            logging.error(f"Income loop error: {e}")
        await asyncio.sleep(60)

async def main():
    print("🚀 Запуск AutoGram AI...")
    await init_db()
    asyncio.create_task(income_loop())
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
