import os
import asyncio
import logging
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from yoomoney import Client, Quickpay
from datetime import datetime
import uuid

load_dotenv()

# ============== CONFIG ==============
BOT_TOKEN = os.getenv("BOT_TOKEN")
YOOMONEY_TOKEN = os.getenv("YOOMONEY_TOKEN")
YOOMONEY_WALLET = os.getenv("YOOMONEY_WALLET")
DB_NAME = "bot.db"
MIN_WITHDRAWAL = 500

# ============== INIT ==============
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
ym_client = Client(YOOMONEY_TOKEN)

db_lock = threading.Lock()
executor = ThreadPoolExecutor(max_workers=4)

# ============== DATABASE (sync функции) ==============
def _init_db():
    with db_lock:
        conn = sqlite3.connect(DB_NAME)
        cur = conn.cursor()
        cur.execute('''CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY, username TEXT, balance REAL DEFAULT 0,
            tariff TEXT, channels INTEGER DEFAULT 0,
            income_multiplier REAL DEFAULT 1.0, registered_at TEXT)''')
        cur.execute('''CREATE TABLE IF NOT EXISTS payments (
            payment_id TEXT PRIMARY KEY, user_id INTEGER, amount REAL,
            tariff TEXT, status TEXT DEFAULT 'pending', created_at TEXT)''')
        cur.execute('''CREATE TABLE IF NOT EXISTS withdrawals (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER,
            amount REAL, requisites TEXT, status TEXT DEFAULT 'pending',
            created_at TEXT)''')
        conn.commit()
        conn.close()

def _get_user(user_id):
    with db_lock:
        conn = sqlite3.connect(DB_NAME)
        cur = conn.cursor()
        cur.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        user = cur.fetchone()
        conn.close()
        return user

def _create_user(user_id, username):
    with db_lock:
        conn = sqlite3.connect(DB_NAME)
        cur = conn.cursor()
        cur.execute(
            "INSERT OR IGNORE INTO users (user_id, username, registered_at) VALUES (?, ?, ?)",
            (user_id, username, datetime.now().isoformat()))
        conn.commit()
        conn.close()

def _update_user_tariff(user_id, tariff, channels, multiplier):
    with db_lock:
        conn = sqlite3.connect(DB_NAME)
        cur = conn.cursor()
        cur.execute(
            "UPDATE users SET tariff=?, channels=?, income_multiplier=? WHERE user_id=?",
            (tariff, channels, multiplier, user_id))
        conn.commit()
        conn.close()

def _update_balance(user_id, amount):
    with db_lock:
        conn = sqlite3.connect(DB_NAME)
        cur = conn.cursor()
        cur.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
        conn.commit()
        conn.close()

def _set_balance(user_id, amount):
    with db_lock:
        conn = sqlite3.connect(DB_NAME)
        cur = conn.cursor()
        cur.execute("UPDATE users SET balance = ? WHERE user_id = ?", (amount, user_id))
        conn.commit()
        conn.close()

def _create_payment(payment_id, user_id, amount, tariff):
    with db_lock:
        conn = sqlite3.connect(DB_NAME)
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO payments VALUES (?, ?, ?, ?, ?, ?)",
            (payment_id, user_id, amount, tariff, 'pending', datetime.now().isoformat()))
        conn.commit()
        conn.close()

def _get_payment(payment_id):
    with db_lock:
        conn = sqlite3.connect(DB_NAME)
        cur = conn.cursor()
        cur.execute("SELECT * FROM payments WHERE payment_id = ?", (payment_id,))
        payment = cur.fetchone()
        conn.close()
        return payment

def _confirm_payment(payment_id):
    with db_lock:
        conn = sqlite3.connect(DB_NAME)
        cur = conn.cursor()
        cur.execute("UPDATE payments SET status = 'paid' WHERE payment_id = ?", (payment_id,))
        conn.commit()
        conn.close()

def _create_withdrawal(user_id, amount, requisites):
    with db_lock:
        conn = sqlite3.connect(DB_NAME)
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO withdrawals (user_id, amount, requisites, created_at) VALUES (?, ?, ?, ?)",
            (user_id, amount, requisites, datetime.now().isoformat()))
        conn.commit()
        conn.close()

# ============== ASYNC WRAPPERS ==============
async def run_db(func, *args):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(executor, func, *args)

async def init_db():
    await run_db(_init_db)

async def get_user(user_id):
    return await run_db(_get_user, user_id)

async def create_user(user_id, username):
    await run_db(_create_user, user_id, username)

async def update_user_tariff(user_id, tariff, channels, multiplier):
    await run_db(_update_user_tariff, user_id, tariff, channels, multiplier)

async def update_balance(user_id, amount):
    await run_db(_update_balance, user_id, amount)

async def set_balance(user_id, amount):
    await run_db(_set_balance, user_id, amount)

async def create_payment(payment_id, user_id, amount, tariff):
    await run_db(_create_payment, payment_id, user_id, amount, tariff)

async def get_payment(payment_id):
    return await run_db(_get_payment, payment_id)

async def confirm_payment(payment_id):
    await run_db(_confirm_payment, payment_id)

async def create_withdrawal(user_id, amount, requisites):
    await run_db(_create_withdrawal, user_id, amount, requisites)

# ============== STATES ==============
class WithdrawState(StatesGroup):
    waiting_requisites = State()

# ============== KEYBOARDS ==============
def main_menu_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚀 Начать зарабатывать", callback_data="start_earn")],
        [InlineKeyboardButton(text="📊 Тарифы", callback_data="tariffs")],
        [InlineKeyboardButton(text="💼 Мой кабинет", callback_data="profile")],
        [InlineKeyboardButton(text="ℹ️ Как это работает", callback_data="how")]
    ])

def tariffs_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💼 Бизнес — 5000₽", callback_data="buy_business")],
        [InlineKeyboardButton(text="👑 Премиум — 10000₽", callback_data="buy_premium")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_main")]
    ])

def profile_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💸 Вывести средства", callback_data="withdraw")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_main")]
    ])

def back_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад в меню", callback_data="back_main")]
    ])

# ============== HANDLERS ==============
@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    await create_user(message.from_user.id, message.from_user.username or "")
    text = (
        "🤖 <b>AutoGram AI — заработок на автоматизации</b>\n\n"
        "Превращаем Telegram в источник пассивного дохода с помощью AI.\n\n"
        "✅ 3 200+ пользователей уже зарабатывают\n"
        "✅ Полная автоматизация\n"
        "✅ Пассивный доход x3 от вложений\n\n"
        "Выберите действие:")
    await message.answer(text, parse_mode="HTML", reply_markup=main_menu_kb())

@dp.callback_query(F.data == "back_main")
async def back_main(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.clear()
    await callback.message.edit_text(
        "🤖 <b>AutoGram AI — заработок на автоматизации</b>\n\nГлавное меню:",
        parse_mode="HTML", reply_markup=main_menu_kb())

@dp.callback_query(F.data == "start_earn")
async def start_earn(callback: CallbackQuery):
    await callback.answer()
    await callback.message.edit_text(
        "🚀 <b>Начни зарабатывать прямо сейчас!</b>\n\n"
        "Выберите тариф и запустите процесс заработка.\n"
        "При покупке любого тарифа пассивная прибыль идёт в x3 раза!",
        parse_mode="HTML", reply_markup=tariffs_kb())

@dp.callback_query(F.data == "tariffs")
async def show_tariffs(callback: CallbackQuery):
    await callback.answer()
    text = (
        "📊 <b>Доступные тарифы:</b>\n\n"
        "💼 <b>БИЗНЕС — 5 000₽</b>\n├ 3 канала\n├ 🚀 Ускоренная мощность\n"
        "├ 🎁 Бесплатный тест продукта\n├ 💰 Программа монетизации\n"
        "├ 📊 AI-логи и аналитика\n└ 🌐 Прокси 20 шт.\n\n"
        "👑 <b>ПРЕМИУМ — 10 000₽</b>\n├ 5 каналов\n├ ⚡ Высокая мощность\n"
        "├ 🎁 Бесплатный тест продукта\n├ 💰 Программа монетизации\n"
        "├ 📊 AI-логи и аналитика\n└ 🌐 Прокси 20 шт.\n\n"
        "💸 <b>При покупке — пассивная прибыль x3!</b>")
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=tariffs_kb())

@dp.callback_query(F.data == "how")
async def how_it_works(callback: CallbackQuery):
    await callback.answer()
    text = (
        "ℹ️ <b>Как это работает?</b>\n\n"
        "<b>4 шага до первого дохода:</b>\n\n"
        "<b>01 — Регистрация</b>\nСоздайте аккаунт и выберите пакет\n\n"
        "<b>02 — AI создаёт канал</b>\nНейросеть оформляет и прогревает канал\n\n"
        "<b>03 — Запуск рекламы</b>\nAI запускает рекламные кампании\n\n"
        "<b>04 — Доход на автомате</b>\nВыводите заработок на карту")
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚀 Начать зарабатывать", callback_data="start_earn")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_main")]
    ]))

@dp.callback_query(F.data.in_({"buy_business", "buy_premium"}))
async def buy_tariff(callback: CallbackQuery):
    await callback.answer()
    tariff = "business" if callback.data == "buy_business" else "premium"
    amount = 5000 if tariff == "business" else 10000
    label = f"p{uuid.uuid4().hex[:8]}"
    
    quickpay = Quickpay(
        receiver=YOOMONEY_WALLET, quickpay_form="shop",
        targets=f"Тариф {tariff}", paymentType="AC",
        sum=amount, label=label)
    
    await create_payment(label, callback.from_user.id, amount, tariff)
    
    text = (
        f"💳 <b>Оплата тарифа {'Бизнес' if tariff == 'business' else 'Премиум'}</b>\n\n"
        f"Сумма: <b>{amount}₽</b>\n\n"
        f"Ссылка для оплаты:\n{quickpay.redirected_url}\n\n"
        f"После оплаты нажмите 'Проверить'.\nID: <code>{label}</code>")
    
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Проверить оплату", callback_data=f"c_{label}")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="tariffs")]
    ]))

@dp.callback_query(F.data.startswith("c_"))
async def check_payment(callback: CallbackQuery):
    await callback.answer("⏳ Проверяю...")
    label = callback.data[2:]
    logger.info(f"Checking payment: {label}")
    
    try:
        loop = asyncio.get_event_loop()
        history = await loop.run_in_executor(executor, ym_client.operation_history, label)
        
        if history.operations:
            for op in history.operations:
                if op.status == "success":
                    payment = await get_payment(label)
                    if payment and payment[4] == "pending":
                        await confirm_payment(label)
                        if payment[3] == "business":
                            await update_user_tariff(callback.from_user.id, "Бизнес", 3, 3.0)
                            await update_balance(callback.from_user.id, 15000)
                        else:
                            await update_user_tariff(callback.from_user.id, "Премиум", 5, 3.0)
                            await update_balance(callback.from_user.id, 30000)
                        
                        await callback.message.edit_text(
                            "✅ <b>Оплата прошла успешно!</b>\n\n"
                            "🎉 Тариф активирован!\n💰 Начислен доход x3",
                            parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                                [InlineKeyboardButton(text="💼 Кабинет", callback_data="profile")],
                                [InlineKeyboardButton(text="🔙 Меню", callback_data="back_main")]
                            ]))
                        return
        await callback.message.answer("❌ Оплата не найдена. Попробуйте позже.")
    except Exception as e:
        logger.error(f"Payment error: {e}")
        await callback.message.answer("❌ Ошибка проверки")

@dp.callback_query(F.data == "profile")
async def profile(callback: CallbackQuery):
    await callback.answer()
    user = await get_user(callback.from_user.id)
    if not user:
        await callback.message.answer("Сначала /start")
        return
    
    balance = user[2] or 0
    tariff = user[3] or "Не выбран"
    channels = user[4] or 0
    multiplier = user[5] or 1.0
    
    text = (
        "💼 <b>Личный кабинет</b>\n\n"
        f"👤 ID: <code>{user[0]}</code>\n"
        f"📊 Тариф: <b>{tariff}</b>\n"
        f"📡 Каналов: <b>{channels}</b>\n"
        f"📈 Множитель: <b>x{multiplier}</b>\n\n"
        f"💰 <b>Баланс: {balance:.2f}₽</b>\n\n"
        f"Мин. вывод: {MIN_WITHDRAWAL}₽")
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=profile_kb())

@dp.callback_query(F.data == "withdraw")
async def withdraw(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    user = await get_user(callback.from_user.id)
    balance = user[2] if user else 0
    
    if balance < MIN_WITHDRAWAL:
        await callback.message.answer(
            f"❌ Мин. сумма: {MIN_WITHDRAWAL}₽\nВаш баланс: {balance:.2f}₽")
        return
    
    await callback.message.edit_text(
        "💸 <b>Вывод средств</b>\n\n"
        f"Доступно: <b>{balance:.2f}₽</b>\n\n"
        "Отправьте реквизиты:\n<code>Карта: 2200 1234 5678 9012</code>",
        parse_mode="HTML", reply_markup=back_kb())
    await state.set_state(WithdrawState.waiting_requisites)

@dp.message(WithdrawState.waiting_requisites)
async def process_requisites(message: types.Message, state: FSMContext):
    user = await get_user(message.from_user.id)
    balance = user[2] if user else 0
    
    await create_withdrawal(message.from_user.id, balance, message.text)
    await set_balance(message.from_user.id, 0)
    await state.clear()
    
    await message.answer(
        f"✅ <b>Заявка создана!</b>\n\n"
        f"💰 Сумма: <b>{balance:.2f}₽</b>\n"
        f"📋 Реквизиты: <code>{message.text}</code>\n\n"
        "⏳ Зачисление в течение 24 часов.",
        parse_mode="HTML", reply_markup=main_menu_kb())

# ============== CATCH HANDLERS ==============
@dp.callback_query()
async def unknown_callback(callback: CallbackQuery):
    logger.warning(f"Unknown callback: {callback.data}")
    await callback.answer("⚠️ Ошибка", show_alert=True)

# ============== STARTUP ==============
async def on_startup():
    await init_db()
    logger.info("Bot started")

async def main():
    dp.startup.register(on_startup)
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())

if __name__ == "__main__":
    asyncio.run(main())
