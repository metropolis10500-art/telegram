import asyncio
import sqlite3
import time
import uuid
import logging
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, CommandObject
from aiogram.utils.keyboard import InlineKeyboardBuilder
from yoomoney import Quickpay, Client

# --- КОНФИГУРАЦИЯ ---
BOT_TOKEN = "8800941405:AAH0TZbP48M5grkVxZ-tvP7lxK72eTSg4yc"
YOOMONEY_TOKEN = "5133D1719448E2A5E1083A0FC605E369944CBB992B1D4490F13E2D4636C03191"
YOOMONEY_WALLET = "4100118935779591"
ADMIN_ID = 12345678  # СЮДА ТВОЙ ID ДЛЯ ЗАЯВОК НА ВЫВОД
MIN_WITHDRAW = 3000  # МИНИМАЛКА НА ВЫВОД

# ТАРИФЫ: Название, Цена, Доход в час
TARIFS = {
    "bot_1": ["AI-Assistant v1.0", 1000, 8.5],    # ~200р в сутки
    "bot_2": ["Neural Engine v2.5", 5000, 52.0],   # ~1250р в сутки
    "bot_3": ["Quantum Cluster v4.0", 20000, 250.0] # ~6000р в сутки
}

REF_PERCENT = 0.10 # 10% от сбора реферала

logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
yoomoney_client = Client(YOOMONEY_TOKEN)

# --- БАЗА ДАННЫХ ---
def db_query(sql, params=(), fetch=False):
    with sqlite3.connect("autogram_ai.db") as conn:
        cur = conn.cursor()
        cur.execute(sql, params)
        res = cur.fetchall() if fetch else None
        conn.commit()
        return res

def init_db():
    db_query("""CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY, 
        balance REAL DEFAULT 0, 
        referred_by INTEGER,
        bot_1 INTEGER DEFAULT 0, bot_2 INTEGER DEFAULT 0, bot_3 INTEGER DEFAULT 0,
        last_collect INTEGER DEFAULT 0
    )""")

def get_user_stats(user_id):
    income_info = db_query("SELECT bot_1, bot_2, bot_3, last_collect, balance, referred_by FROM users WHERE id = ?", (user_id,), True)
    if not income_info: return None
    b1, b2, b3, last_t, bal, ref_by = income_info[0]
    
    now = int(time.time())
    diff_hours = (now - last_t) / 3600
    total_hourly = (b1 * TARIFS["bot_1"][2]) + (b2 * TARIFS["bot_2"][2]) + (b3 * TARIFS["bot_3"][2])
    
    pending_income = diff_hours * total_hourly
    return pending_income, now, bal, ref_by, (b1, b2, b3)

# --- ОБРАБОТЧИКИ ---
@dp.message(Command("start"))
async def cmd_start(message: types.Message, command: CommandObject):
    user = db_query("SELECT id FROM users WHERE id = ?", (message.from_user.id,), True)
    if not user:
        ref_id = int(command.args) if command.args and command.args.isdigit() else None
        db_query("INSERT INTO users (id, referred_by, last_collect) VALUES (?, ?, ?)", 
                 (message.from_user.id, ref_id, int(time.time())))
    
    kb = InlineKeyboardBuilder()
    kb.row(types.InlineKeyboardButton(text="🖥 Личный кабинет", callback_data="cabinet"))
    kb.row(types.InlineKeyboardButton(text="⚡️ Арендовать мощности", callback_data="shop"))
    kb.row(types.InlineKeyboardButton(text="🤝 Партнерство", callback_data="refs"))
    
    await message.answer(
        "<b>🤖 AutoGram AI — Автоматизация заработка</b>\n\n"
        "Добро пожаловать в систему облачных вычислений. Наши алгоритмы работают на вас 24/7.\n\n"
        "🔹 <b>Статус:</b> Система активна\n"
        "🔹 <b>Ваш ID:</b> <code>{}</code>".format(message.from_user.id),
        parse_mode="HTML", reply_markup=kb.as_markup()
    )

@dp.callback_query(F.data == "cabinet")
async def view_cabinet(callback: types.CallbackQuery):
    pending, _, bal, _, bots = get_user_stats(callback.from_user.id)
    
    text = (
        f"<b>💼 ЛИЧНЫЙ КАБИНЕТ AutoGram AI</b>\n\n"
        f"💰 На балансе: <b>{round(bal, 2)} ₽</b>\n"
        f"⏳ Намайнено: <b>{round(pending, 2)} ₽</b>\n\n"
        f"<b>Ваши алгоритмы:</b>\n"
        f"└ v1.0: {bots[0]} | v2.5: {bots[1]} | v4.0: {bots[2]}\n\n"
        f"<i>Минимальная сумма для вывода: {MIN_WITHDRAW} ₽</i>"
    )
    kb = InlineKeyboardBuilder()
    kb.row(types.InlineKeyboardButton(text="📥 Собрать прибыль", callback_data="collect"))
    kb.row(types.InlineKeyboardButton(text="➕ Пополнить", callback_data="deposit"))
    kb.row(types.InlineKeyboardButton(text="💸 Вывести", callback_data="withdraw"))
    kb.row(types.InlineKeyboardButton(text="⬅️ Назад", callback_data="back"))
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb.as_markup())

@dp.callback_query(F.data == "collect")
async def collect_money(callback: types.CallbackQuery):
    pending, now, bal, ref_by, _ = get_user_stats(callback.from_user.id)
    if pending < 1:
        return await callback.answer("❌ Слишком мало прибыли для сбора.", show_alert=True)
    
    db_query("UPDATE users SET balance = balance + ?, last_collect = ? WHERE id = ?", (pending, now, callback.from_user.id))
    
    if ref_by:
        bonus = pending * REF_PERCENT
        db_query("UPDATE users SET balance = balance + ? WHERE id = ?", (bonus, ref_by))
        try: await bot.send_message(ref_by, f"➕ Реферальный бонус: <b>{round(bonus, 2)}₽</b> за работу вашего партнера.")
        except: pass

    await callback.answer(f"✅ Собрано {round(pending, 2)}₽", show_alert=True)
    await view_cabinet(callback)

@dp.callback_query(F.data == "shop")
async def show_shop(callback: types.CallbackQuery):
    kb = InlineKeyboardBuilder()
    for key, val in TARIFS.items():
        kb.row(types.InlineKeyboardButton(text=f"Арендовать {val[0]} — {val[1]}₽", callback_data=f"buy_{key}"))
    kb.row(types.InlineKeyboardButton(text="⬅️ Назад", callback_data="back"))
    await callback.message.edit_text("<b>🛒 МАГАЗИН МОЩНОСТЕЙ AI</b>\n\nВыберите алгоритм для автоматизации:", parse_mode="HTML", reply_markup=kb.as_markup())

@dp.callback_query(F.data.startswith("buy_"))
async def buy_bot(callback: types.CallbackQuery):
    key = callback.data.split("_")[1] + "_" + callback.data.split("_")[2]
    name, price, _ = TARIFS[key]
    _, _, bal, _, _ = get_user_stats(callback.from_user.id)
    
    if bal < price:
        return await callback.answer("❌ Недостаточно средств на балансе!", show_alert=True)
    
    db_query(f"UPDATE users SET balance = balance - ?, {key} = {key} + 1 WHERE id = ?", (price, callback.from_user.id))
    await callback.answer(f"🚀 Алгоритм {name} успешно запущен!", show_alert=True)
    await show_shop(callback)

@dp.callback_query(F.data == "withdraw")
async def withdraw_request(callback: types.CallbackQuery):
    _, _, bal, _, _ = get_user_stats(callback.from_user.id)
    if bal < MIN_WITHDRAW:
        return await callback.answer(f"⚠️ Минимальная сумма вывода — {MIN_WITHDRAW}₽\nУ вас: {round(bal, 2)}₽", show_alert=True)
    
    await callback.message.answer("💬 Введите номер карты или ЮMoney кошелька для вывода:")
    # Для простоты здесь можно добавить State (состояния), но пока просто уведомление
    await bot.send_message(ADMIN_ID, f"🔔 <b>ЗАЯВКА НА ВЫВОД</b>\nUser ID: {callback.from_user.id}\nБаланс: {bal}₽")

@dp.callback_query(F.data == "deposit")
async def deposit_link(callback: types.CallbackQuery):
    label = f"dep_{callback.from_user.id}_{int(time.time())}"
    # Сумму пополнения можно сделать кнопками, тут для примера 1000р
    quickpay = Quickpay(receiver=YOOMONEY_WALLET, quickpay_form="shop", targets="AutoGram AI Deposit", 
                        paymentType="SB", sum=1000, label=label)
    
    kb = InlineKeyboardBuilder()
    kb.row(types.InlineKeyboardButton(text="💳 Оплатить 1000₽", url=quickpay.base_url))
    kb.row(types.InlineKeyboardButton(text="✅ Проверить оплату", callback_data=f"check_{label}"))
    await callback.message.answer("Сгенерирована ссылка на пополнение баланса:", reply_markup=kb.as_markup())

@dp.callback_query(F.data.startswith("check_"))
async def check_p(callback: types.CallbackQuery):
    label = callback.data.split("_")[1]
    history = yoomoney_client.operation_history(label=label)
    if history.operations and history.operations[-1].status == "success":
        amount = history.operations[-1].amount
        db_query("UPDATE users SET balance = balance + ? WHERE id = ?", (amount, callback.from_user.id))
        await callback.message.answer(f"✅ Баланс успешно пополнен на {amount}₽!")
    else:
        await callback.answer("❌ Транзакция не найдена или в обработке.", show_alert=True)

@dp.callback_query(F.data == "refs")
async def referral_menu(callback: types.CallbackQuery):
    me = await bot.get_me()
    link = f"https://t.me/{me.username}?start={callback.from_user.id}"
    count = db_query("SELECT COUNT(id) FROM users WHERE referred_by = ?", (callback.from_user.id,), True)[0][0]
    
    await callback.message.edit_text(
        f"<b>🤝 ПАРТНЕРСКАЯ ПРОГРАММА</b>\n\n"
        f"Приглашайте новых пользователей в <b>AutoGram AI</b> и получайте <b>10%</b> от каждого сбора их прибыли!\n\n"
        f"🔗 Ваша ссылка:\n<code>{link}</code>\n\n"
        f"👥 Приглашено партнеров: <b>{count}</b>",
        parse_mode="HTML", reply_markup=InlineKeyboardBuilder().row(types.InlineKeyboardButton(text="⬅️ Назад", callback_data="back")).as_markup()
    )

@dp.message(Command("admin"))
async def admin_stats(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    res = db_query("SELECT COUNT(id), SUM(balance) FROM users", fetch=True)[0]
    await message.answer(f"📊 <b>АДМИН-СТАТИСТИКА:</b>\n\nВсего юзеров: {res[0]}\nСумма на балансах: {round(res[1] or 0, 2)}₽", parse_mode="HTML")

@dp.callback_query(F.data == "back")
async def go_back_home(callback: types.CallbackQuery):
    await cmd_start(callback.message, CommandObject(command="start", args=None))

async def main():
    init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
