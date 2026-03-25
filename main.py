#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🧽 SpongeBob Money Bot — Инвестиционная игра с персонажами Бикини Боттом
"""

import telebot
from telebot import types
import sqlite3
import threading
import time
import datetime
import traceback

# ══════════════════════════════════════════════════════════════
#                     КОНФИГУРАЦИЯ
# ══════════════════════════════════════════════════════════════

BOT_TOKEN = "8782136903:AAGw-984UI9HShcyE9DFF_8U-w_UhJ_nAYg"
ADMIN_IDS = [5494544187]  # Замените на ваш Telegram ID

MIN_DEPOSIT = 500
MIN_WITHDRAWAL = 500
WITHDRAWAL_FEE = 10        # Комиссия вывода %
REFERRAL_BONUS = 7          # Реферальный бонус % от депозита

PAYMENT_DETAILS = (
    "💳 Карта: <code>5599 0020 9055 3779</code>\n"
    "🏦 Банк: Сбербанк\n"
    "👤 Получатель: Роман В."
)

# ══════════════════════════════════════════════════════════════
#             ТАРИФЫ (ПЕРСОНАЖИ)
# ══════════════════════════════════════════════════════════════
#
#  Экономика: пользователь покупает персонажа с баланса,
#  персонаж начисляет ежедневный доход в течение N дней.
#  Оператор контролирует депозиты/выводы вручную.
#  Комиссия 10 % при выводе → чистая прибыль оператора.
#
#  При 100 активных юзерах со средним депозитом 5 000 ₽
#  вы получаете ≈ 50 000 ₽ комиссий + маржу ≈ 250 000+ ₽/мес
#  (> $3 000).  Масштабируется через реферальную программу.
# ══════════════════════════════════════════════════════════════

TARIFFS = {
    "spongebob": {
        "name": "🧽 Губка Боб",
        "price": 500,
        "daily": 17,
        "days": 35,           # итого 595 ₽  (+19 %)
        "desc": "Работник месяца Красти Крабс!\nСтабильный старт для новичков.",
    },
    "patrick": {
        "name": "⭐ Патрик Стар",
        "price": 2_000,
        "daily": 80,
        "days": 35,           # итого 2 800 ₽  (+40 %)
        "desc": "Не такой глупый, как кажется!\nУмеет находить деньги там, где другие не видят.",
    },
    "squidward": {
        "name": "🎵 Сквидвард",
        "price": 5_000,
        "daily": 220,
        "days": 35,           # итого 7 700 ₽  (+54 %)
        "desc": "Талантливый музыкант и тайный бизнесмен!\nЕго инвестиции всегда в плюсе.",
    },
    "sandy": {
        "name": "🐿 Сэнди Чикс",
        "price": 15_000,
        "daily": 700,
        "days": 35,           # итого 24 500 ₽ (+63 %)
        "desc": "Гениальный учёный из Техаса!\nЕё технологии генерируют серьёзный доход.",
    },
    "mrkrabs": {
        "name": "🦀 Мистер Крабс",
        "price": 50_000,
        "daily": 2_600,
        "days": 35,           # итого 91 000 ₽ (+82 %)
        "desc": "Легенда бизнеса Бикини Боттом!\nМаксимальный доход для серьёзных инвесторов.",
    },
}

DB_NAME = "spongebob_bot.db"
db_lock = threading.Lock()

# ══════════════════════════════════════════════════════════════
#                      БАЗА ДАННЫХ
# ══════════════════════════════════════════════════════════════

def _conn():
    c = sqlite3.connect(DB_NAME)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    return c


def init_db():
    with db_lock:
        c = _conn()
        c.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            user_id       INTEGER PRIMARY KEY,
            username      TEXT DEFAULT '',
            first_name    TEXT DEFAULT '',
            balance       REAL DEFAULT 0,
            total_earned  REAL DEFAULT 0,
            total_dep     REAL DEFAULT 0,
            total_wdr     REAL DEFAULT 0,
            ref_id        INTEGER DEFAULT 0,
            ref_count     INTEGER DEFAULT 0,
            ref_earn      REAL DEFAULT 0,
            reg_at        TEXT,
            banned        INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS investments (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id       INTEGER,
            tkey          TEXT,
            tname         TEXT,
            amount        REAL,
            daily         REAL,
            days_total    INTEGER,
            days_done     INTEGER DEFAULT 0,
            earned        REAL DEFAULT 0,
            active        INTEGER DEFAULT 1,
            created       TEXT
        );
        CREATE TABLE IF NOT EXISTS deposits (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id       INTEGER,
            amount        REAL,
            status        TEXT DEFAULT 'pending',
            created       TEXT,
            processed     TEXT
        );
        CREATE TABLE IF NOT EXISTS withdrawals (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id       INTEGER,
            amount        REAL,
            fee           REAL,
            net           REAL,
            wallet        TEXT,
            status        TEXT DEFAULT 'pending',
            created       TEXT,
            processed     TEXT
        );
        """)
        c.commit()
        c.close()


def get_user(uid):
    with db_lock:
        c = _conn()
        r = c.execute("SELECT * FROM users WHERE user_id=?", (uid,)).fetchone()
        c.close()
        return r


def create_user(uid, uname, fname, ref=0):
    with db_lock:
        c = _conn()
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            c.execute(
                "INSERT INTO users(user_id,username,first_name,ref_id,reg_at)"
                " VALUES(?,?,?,?,?)",
                (uid, uname or "", fname or "", ref, now),
            )
            if ref:
                c.execute(
                    "UPDATE users SET ref_count=ref_count+1 WHERE user_id=?",
                    (ref,),
                )
            c.commit()
        except sqlite3.IntegrityError:
            pass
        c.close()


def add_balance(uid, val):
    with db_lock:
        c = _conn()
        c.execute("UPDATE users SET balance=balance+? WHERE user_id=?", (val, uid))
        c.commit()
        c.close()


def get_investments(uid, active=True):
    with db_lock:
        c = _conn()
        if active:
            rows = c.execute(
                "SELECT * FROM investments WHERE user_id=? AND active=1", (uid,)
            ).fetchall()
        else:
            rows = c.execute(
                "SELECT * FROM investments WHERE user_id=?", (uid,)
            ).fetchall()
        c.close()
        return rows


def buy_invest(uid, tkey):
    t = TARIFFS[tkey]
    with db_lock:
        c = _conn()
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        c.execute(
            "INSERT INTO investments(user_id,tkey,tname,amount,daily,days_total,created)"
            " VALUES(?,?,?,?,?,?,?)",
            (uid, tkey, t["name"], t["price"], t["daily"], t["days"], now),
        )
        c.execute(
            "UPDATE users SET balance=balance-? WHERE user_id=?", (t["price"], uid)
        )
        c.commit()
        c.close()


def mk_deposit(uid, amount):
    with db_lock:
        c = _conn()
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cur = c.cursor()
        cur.execute(
            "INSERT INTO deposits(user_id,amount,created) VALUES(?,?,?)",
            (uid, amount, now),
        )
        did = cur.lastrowid
        c.commit()
        c.close()
        return did


def pending_deps():
    with db_lock:
        c = _conn()
        rows = c.execute(
            "SELECT d.*,u.username,u.first_name FROM deposits d"
            " JOIN users u ON d.user_id=u.user_id WHERE d.status='pending'"
        ).fetchall()
        c.close()
        return rows


def approve_dep(did):
    with db_lock:
        c = _conn()
        d = c.execute("SELECT * FROM deposits WHERE id=?", (did,)).fetchone()
        if not d or d["status"] != "pending":
            c.close()
            return None
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        c.execute(
            "UPDATE deposits SET status='approved',processed=? WHERE id=?",
            (now, did),
        )
        c.execute(
            "UPDATE users SET balance=balance+?, total_dep=total_dep+? WHERE user_id=?",
            (d["amount"], d["amount"], d["user_id"]),
        )
        u = c.execute(
            "SELECT ref_id FROM users WHERE user_id=?", (d["user_id"],)
        ).fetchone()
        if u and u["ref_id"]:
            bonus = d["amount"] * REFERRAL_BONUS / 100
            c.execute(
                "UPDATE users SET balance=balance+?, ref_earn=ref_earn+? WHERE user_id=?",
                (bonus, bonus, u["ref_id"]),
            )
        c.commit()
        c.close()
        return d


def reject_dep(did):
    with db_lock:
        c = _conn()
        d = c.execute("SELECT * FROM deposits WHERE id=?", (did,)).fetchone()
        if not d or d["status"] != "pending":
            c.close()
            return None
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        c.execute(
            "UPDATE deposits SET status='rejected',processed=? WHERE id=?",
            (now, did),
        )
        c.commit()
        c.close()
        return d


def mk_withdrawal(uid, amount, wallet):
    fee = round(amount * WITHDRAWAL_FEE / 100, 2)
    net = round(amount - fee, 2)
    with db_lock:
        c = _conn()
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        c.execute(
            "UPDATE users SET balance=balance-? WHERE user_id=?", (amount, uid)
        )
        cur = c.cursor()
        cur.execute(
            "INSERT INTO withdrawals(user_id,amount,fee,net,wallet,created)"
            " VALUES(?,?,?,?,?,?)",
            (uid, amount, fee, net, wallet, now),
        )
        wid = cur.lastrowid
        c.commit()
        c.close()
        return wid, net


def pending_wds():
    with db_lock:
        c = _conn()
        rows = c.execute(
            "SELECT w.*,u.username,u.first_name FROM withdrawals w"
            " JOIN users u ON w.user_id=u.user_id WHERE w.status='pending'"
        ).fetchall()
        c.close()
        return rows


def approve_wd(wid):
    with db_lock:
        c = _conn()
        w = c.execute("SELECT * FROM withdrawals WHERE id=?", (wid,)).fetchone()
        if not w or w["status"] != "pending":
            c.close()
            return None
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        c.execute(
            "UPDATE withdrawals SET status='approved',processed=? WHERE id=?",
            (now, wid),
        )
        c.execute(
            "UPDATE users SET total_wdr=total_wdr+? WHERE user_id=?",
            (w["net"], w["user_id"]),
        )
        c.commit()
        c.close()
        return w


def reject_wd(wid):
    with db_lock:
        c = _conn()
        w = c.execute("SELECT * FROM withdrawals WHERE id=?", (wid,)).fetchone()
        if not w or w["status"] != "pending":
            c.close()
            return None
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        c.execute(
            "UPDATE withdrawals SET status='rejected',processed=? WHERE id=?",
            (now, wid),
        )
        c.execute(
            "UPDATE users SET balance=balance+? WHERE user_id=?",
            (w["amount"], w["user_id"]),
        )
        c.commit()
        c.close()
        return w


def stats():
    with db_lock:
        c = _conn()
        s = {}
        s["users"] = c.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        s["dep"] = c.execute(
            "SELECT COALESCE(SUM(amount),0) FROM deposits WHERE status='approved'"
        ).fetchone()[0]
        s["wdr"] = c.execute(
            "SELECT COALESCE(SUM(net),0) FROM withdrawals WHERE status='approved'"
        ).fetchone()[0]
        s["fees"] = c.execute(
            "SELECT COALESCE(SUM(fee),0) FROM withdrawals WHERE status='approved'"
        ).fetchone()[0]
        s["pdep"] = c.execute(
            "SELECT COUNT(*) FROM deposits WHERE status='pending'"
        ).fetchone()[0]
        s["pwd"] = c.execute(
            "SELECT COUNT(*) FROM withdrawals WHERE status='pending'"
        ).fetchone()[0]
        s["ainv"] = c.execute(
            "SELECT COUNT(*) FROM investments WHERE active=1"
        ).fetchone()[0]
        s["tinv"] = c.execute(
            "SELECT COALESCE(SUM(amount),0) FROM investments"
        ).fetchone()[0]
        s["profit"] = s["dep"] - s["wdr"]
        c.close()
        return s


def accrue_income():
    """Ежедневное начисление дохода по активным инвестициям."""
    with db_lock:
        c = _conn()
        rows = c.execute("SELECT * FROM investments WHERE active=1").fetchall()
        for inv in rows:
            if inv["days_done"] < inv["days_total"]:
                c.execute(
                    "UPDATE users SET balance=balance+?, total_earned=total_earned+?"
                    " WHERE user_id=?",
                    (inv["daily"], inv["daily"], inv["user_id"]),
                )
                new_done = inv["days_done"] + 1
                finished = 1 if new_done >= inv["days_total"] else 0
                c.execute(
                    "UPDATE investments SET days_done=?, earned=earned+?,"
                    " active=CASE WHEN ?>=days_total THEN 0 ELSE 1 END WHERE id=?",
                    (new_done, inv["daily"], new_done, inv["id"]),
                )
        c.commit()
        c.close()
        print(f"[{datetime.datetime.now()}] Accrued income for {len(rows)} investments")


# ══════════════════════════════════════════════════════════════
#                    ПЛАНИРОВЩИК ДОХОДА
# ══════════════════════════════════════════════════════════════

def scheduler():
    last_date = None
    while True:
        today = datetime.date.today()
        if last_date != today:
            try:
                accrue_income()
                last_date = today
            except Exception as e:
                print(f"Scheduler error: {e}")
                traceback.print_exc()
        time.sleep(60)


# ══════════════════════════════════════════════════════════════
#                        БОТ
# ══════════════════════════════════════════════════════════════

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")
user_state = {}


# ---------- Клавиатуры ----------

def kb_main():
    k = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    k.add("🎮 Персонажи", "💰 Профиль")
    k.add("📊 Мои вложения", "👥 Рефералы")
    k.add("📥 Пополнить", "📤 Вывести")
    k.add("ℹ️ Инфо")
    return k


def kb_tariffs():
    k = types.InlineKeyboardMarkup(row_width=1)
    for key, t in TARIFFS.items():
        total = t["daily"] * t["days"]
        k.add(
            types.InlineKeyboardButton(
                f'{t["name"]}  {t["price"]:,}₽ ➜ {total:,}₽',
                callback_data=f"t_{key}",
            )
        )
    return k


def kb_admin():
    k = types.InlineKeyboardMarkup(row_width=2)
    k.add(
        types.InlineKeyboardButton("📊 Статистика", callback_data="a_stats"),
        types.InlineKeyboardButton("📥 Депозиты", callback_data="a_deps"),
    )
    k.add(
        types.InlineKeyboardButton("📤 Выводы", callback_data="a_wds"),
        types.InlineKeyboardButton("📢 Рассылка", callback_data="a_bc"),
    )
    k.add(
        types.InlineKeyboardButton("👤 Найти юзера", callback_data="a_find"),
        types.InlineKeyboardButton("💰 Начислить", callback_data="a_add"),
    )
    k.add(
        types.InlineKeyboardButton("⚡ Начислить доход сейчас", callback_data="a_accrue"),
    )
    return k


# ---------- /start ----------

@bot.message_handler(commands=["start"])
def cmd_start(msg):
    uid = msg.from_user.id
    ref = 0
    parts = msg.text.split()
    if len(parts) > 1:
        try:
            ref = int(parts[1])
            if ref == uid:
                ref = 0
        except ValueError:
            ref = 0

    if not get_user(uid):
        create_user(uid, msg.from_user.username, msg.from_user.first_name, ref)
        if ref:
            try:
                bot.send_message(
                    ref,
                    f"🎉 По вашей ссылке пришёл новый игрок: "
                    f"<b>{msg.from_user.first_name}</b>!",
                )
            except Exception:
                pass

    bot.send_message(
        msg.chat.id,
        f"🧽 <b>Добро пожаловать в SpongeBob Money!</b>\n\n"
        f"Привет, <b>{msg.from_user.first_name}</b>!\n\n"
        f"🌊 Погрузись в мир Бикини Боттом и зарабатывай "
        f"вместе с любимыми персонажами!\n\n"
        f"<b>Как играть:</b>\n"
        f"1️⃣ Пополни баланс\n"
        f"2️⃣ Купи персонажа‑работника\n"
        f"3️⃣ Получай доход каждый день\n"
        f"4️⃣ Выводи на карту\n\n"
        f"Нажми 🎮 <b>Персонажи</b> чтобы начать!",
        reply_markup=kb_main(),
    )


@bot.message_handler(commands=["admin"])
def cmd_admin(msg):
    if msg.from_user.id in ADMIN_IDS:
        bot.send_message(msg.chat.id, "🔧 <b>Админ‑панель</b>", reply_markup=kb_admin())
    else:
        bot.send_message(msg.chat.id, "⛔ Нет доступа")


# ---------- Главное меню ----------

@bot.message_handler(func=lambda m: m.text == "🎮 Персонажи")
def h_tariffs(msg):
    if not get_user(msg.from_user.id):
        return cmd_start(msg)
    bot.send_message(
        msg.chat.id,
        "🎮 <b>Персонажи Бикини Боттом</b>\n\n"
        "Выбери персонажа‑работника.\n"
        "💡 <i>Дороже персонаж — больше доход!</i>",
        reply_markup=kb_tariffs(),
    )


@bot.message_handler(func=lambda m: m.text == "💰 Профиль")
def h_profile(msg):
    u = get_user(msg.from_user.id)
    if not u:
        return cmd_start(msg)
    invs = get_investments(msg.from_user.id)
    daily = sum(i["daily"] for i in invs)
    bot.send_message(
        msg.chat.id,
        f"💰 <b>Ваш профиль</b>\n\n"
        f"👤 <b>{u['first_name']}</b>  "
        f"(@{u['username'] or '—'})\n"
        f"🆔 <code>{u['user_id']}</code>\n\n"
        f"💵 Баланс: <b>{u['balance']:.2f} ₽</b>\n"
        f"📈 Заработано: <b>{u['total_earned']:.2f} ₽</b>\n"
        f"📥 Пополнено: <b>{u['total_dep']:.2f} ₽</b>\n"
        f"📤 Выведено: <b>{u['total_wdr']:.2f} ₽</b>\n\n"
        f"🎮 Активных персонажей: <b>{len(invs)}</b>\n"
        f"💰 Доход/день: <b>{daily:.0f} ₽</b>\n\n"
        f"👥 Рефералов: <b>{u['ref_count']}</b>\n"
        f"🎁 С рефералов: <b>{u['ref_earn']:.2f} ₽</b>",
    )


@bot.message_handler(func=lambda m: m.text == "📊 Мои вложения")
def h_invests(msg):
    u = get_user(msg.from_user.id)
    if not u:
        return cmd_start(msg)
    invs = get_investments(msg.from_user.id)
    if not invs:
        bot.send_message(
            msg.chat.id,
            "📊 <b>Мои вложения</b>\n\n"
            "У вас пока нет персонажей.\n"
            "Нажмите 🎮 <b>Персонажи</b> для покупки!",
        )
        return
    txt = "📊 <b>Мои активные персонажи</b>\n"
    for i in invs:
        pct = i["days_done"] / i["days_total"] * 100
        left = i["days_total"] - i["days_done"]
        bar = "▓" * int(pct / 10) + "░" * (10 - int(pct / 10))
        txt += (
            f"\n{i['tname']}\n"
            f"├ 💰 Вложено: {i['amount']:.0f} ₽\n"
            f"├ 📈 Доход/день: {i['daily']:.0f} ₽\n"
            f"├ 💵 Получено: {i['earned']:.0f} ₽\n"
            f"├ 📅 Осталось: {left} дн.\n"
            f"└ [{bar}] {pct:.0f}%\n"
        )
    bot.send_message(msg.chat.id, txt)


@bot.message_handler(func=lambda m: m.text == "👥 Рефералы")
def h_refs(msg):
    u = get_user(msg.from_user.id)
    if not u:
        return cmd_start(msg)
    me = bot.get_me()
    link = f"https://t.me/{me.username}?start={msg.from_user.id}"
    k = types.InlineKeyboardMarkup()
    k.add(
        types.InlineKeyboardButton(
            "📤 Поделиться",
            url=(
                f"https://t.me/share/url?url={link}"
                f"&text=🧽 Заходи в SpongeBob Money! "
                f"Зарабатывай с персонажами Бикини Боттом!"
            ),
        )
    )
    bot.send_message(
        msg.chat.id,
        f"👥 <b>Реферальная программа</b>\n\n"
        f"Приглашай друзей — получай <b>{REFERRAL_BONUS}%</b> "
        f"от каждого их пополнения!\n\n"
        f"🔗 Твоя ссылка:\n<code>{link}</code>\n\n"
        f"👥 Приглашено: <b>{u['ref_count']}</b>\n"
        f"💰 Заработано: <b>{u['ref_earn']:.2f} ₽</b>",
        reply_markup=k,
    )


@bot.message_handler(func=lambda m: m.text == "ℹ️ Инфо")
def h_info(msg):
    txt = (
        "ℹ️ <b>SpongeBob Money — Правила</b>\n\n"
        "🧽 Инвестиционная игра с персонажами Губки Боба.\n\n"
        "<b>Как играть:</b>\n"
        f"1. Пополните баланс (от {MIN_DEPOSIT} ₽)\n"
        "2. Купите персонажа в разделе 🎮\n"
        "3. Он будет приносить доход каждый день\n"
        f"4. Выводите от {MIN_WITHDRAWAL} ₽ "
        f"(комиссия {WITHDRAWAL_FEE}%)\n"
        f"5. Приглашайте друзей — бонус {REFERRAL_BONUS}%\n\n"
        "<b>Персонажи:</b>\n"
    )
    for t in TARIFFS.values():
        total = t["daily"] * t["days"]
        roi = (total - t["price"]) / t["price"] * 100
        txt += (
            f"\n{t['name']}\n"
            f"  {t['price']:,}₽ → {total:,}₽ за {t['days']} дн. "
            f"(+{roi:.0f}%)\n"
        )
    bot.send_message(msg.chat.id, txt)


# ---------- Пополнение ----------

@bot.message_handler(func=lambda m: m.text == "📥 Пополнить")
def h_dep(msg):
    if not get_user(msg.from_user.id):
        return cmd_start(msg)
    m = bot.send_message(
        msg.chat.id,
        f"📥 <b>Пополнение баланса</b>\n\n"
        f"Минимум: <b>{MIN_DEPOSIT} ₽</b>\n\n"
        f"Введите сумму:",
    )
    bot.register_next_step_handler(m, step_dep_amount)


def step_dep_amount(msg):
    try:
        amt = float(msg.text.replace(",", ".").strip())
        assert amt >= MIN_DEPOSIT
    except (ValueError, AssertionError):
        bot.send_message(
            msg.chat.id,
            f"❌ Минимальная сумма: {MIN_DEPOSIT} ₽. Попробуйте снова.",
        )
        return
    user_state[msg.from_user.id] = {"dep": amt}
    k = types.InlineKeyboardMarkup()
    k.add(
        types.InlineKeyboardButton("✅ Я оплатил", callback_data=f"paid_{amt}"),
        types.InlineKeyboardButton("❌ Отмена", callback_data="dep_cancel"),
    )
    bot.send_message(
        msg.chat.id,
        f"📥 <b>Пополнение {amt:.0f} ₽</b>\n\n"
        f"Переведите <b>точно {amt:.0f} ₽</b> по реквизитам:\n\n"
        f"{PAYMENT_DETAILS}\n\n"
        f"⚠️ Переводите <b>точную сумму</b>!\n"
        f"После перевода нажмите «✅ Я оплатил».",
        reply_markup=k,
    )


# ---------- Вывод ----------

@bot.message_handler(func=lambda m: m.text == "📤 Вывести")
def h_wd(msg):
    u = get_user(msg.from_user.id)
    if not u:
        return cmd_start(msg)
    if u["balance"] < MIN_WITHDRAWAL:
        bot.send_message(
            msg.chat.id,
            f"❌ Минимум для вывода: {MIN_WITHDRAWAL} ₽\n"
            f"Баланс: {u['balance']:.2f} ₽",
        )
        return
    m = bot.send_message(
        msg.chat.id,
        f"📤 <b>Вывод средств</b>\n\n"
        f"💰 Баланс: <b>{u['balance']:.2f} ₽</b>\n"
        f"📌 Минимум: <b>{MIN_WITHDRAWAL} ₽</b>\n"
        f"💸 Комиссия: <b>{WITHDRAWAL_FEE}%</b>\n\n"
        f"Введите сумму вывода:",
    )
    bot.register_next_step_handler(m, step_wd_amount)


def step_wd_amount(msg):
    u = get_user(msg.from_user.id)
    try:
        amt = float(msg.text.replace(",", ".").strip())
        assert amt >= MIN_WITHDRAWAL
        assert amt <= u["balance"]
    except (ValueError, AssertionError):
        bot.send_message(
            msg.chat.id,
            f"❌ Сумма от {MIN_WITHDRAWAL} до {u['balance']:.0f} ₽",
        )
        return
    fee = amt * WITHDRAWAL_FEE / 100
    net = amt - fee
    user_state[msg.from_user.id] = {"wd": amt}
    m = bot.send_message(
        msg.chat.id,
        f"📤 <b>Вывод {amt:.0f} ₽</b>\n\n"
        f"💸 Комиссия ({WITHDRAWAL_FEE}%): {fee:.0f} ₽\n"
        f"✅ К получению: <b>{net:.0f} ₽</b>\n\n"
        f"Введите реквизиты (номер карты / кошелька):",
    )
    bot.register_next_step_handler(m, step_wd_wallet)


def step_wd_wallet(msg):
    uid = msg.from_user.id
    st = user_state.get(uid)
    if not st or "wd" not in st:
        bot.send_message(msg.chat.id, "❌ Ошибка, начните заново.")
        return
    u = get_user(uid)
    amt = st["wd"]
    if amt > u["balance"]:
        bot.send_message(msg.chat.id, "❌ Недостаточно средств.")
        return
    wallet = msg.text.strip()
    wid, net = mk_withdrawal(uid, amt, wallet)
    user_state.pop(uid, None)
    bot.send_message(
        msg.chat.id,
        f"✅ <b>Заявка #{wid} создана!</b>\n\n"
        f"💰 Сумма: {amt:.0f} ₽\n"
        f"✅ К получению: {net:.0f} ₽\n"
        f"💳 Реквизиты: <code>{wallet}</code>\n\n"
        f"⏳ Обработка до 24 часов.",
    )
    for aid in ADMIN_IDS:
        try:
            k = types.InlineKeyboardMarkup()
            k.add(
                types.InlineKeyboardButton("✅", callback_data=f"aw_{wid}"),
                types.InlineKeyboardButton("❌", callback_data=f"rw_{wid}"),
            )
            bot.send_message(
                aid,
                f"🔔 <b>Вывод #{wid}</b>\n\n"
                f"👤 {u['first_name']} (@{u['username']}) "
                f"[<code>{uid}</code>]\n"
                f"💰 {amt:.0f} ₽ → {net:.0f} ₽\n"
                f"💳 <code>{wallet}</code>",
                reply_markup=k,
            )
        except Exception:
            pass


# ══════════════════════════════════════════════════════════════
#                 CALLBACK ОБРАБОТЧИК
# ══════════════════════════════════════════════════════════════

@bot.callback_query_handler(func=lambda c: True)
def on_callback(call):
    uid = call.from_user.id
    d = call.data

    try:
        # ---- Тарифы ----
        if d.startswith("t_"):
            key = d[2:]
            if key not in TARIFFS:
                return
            t = TARIFFS[key]
            total = t["daily"] * t["days"]
            roi = (total - t["price"]) / t["price"] * 100
            k = types.InlineKeyboardMarkup()
            k.add(
                types.InlineKeyboardButton(
                    f"🛒 Купить за {t['price']:,} ₽",
                    callback_data=f"buy_{key}",
                )
            )
            k.add(
                types.InlineKeyboardButton("⬅️ Назад", callback_data="back_t")
            )
            bot.edit_message_text(
                f"{t['name']}\n\n"
                f"{t['desc']}\n\n"
                f"💰 Цена: <b>{t['price']:,} ₽</b>\n"
                f"📈 Доход/день: <b>{t['daily']:,} ₽</b>\n"
                f"📅 Срок: <b>{t['days']} дней</b>\n"
                f"💵 Итого: <b>{total:,} ₽</b>\n"
                f"📊 Прибыль: <b>+{roi:.0f}%</b>",
                call.message.chat.id,
                call.message.message_id,
                reply_markup=k,
            )

        elif d.startswith("buy_"):
            key = d[4:]
            t = TARIFFS[key]
            u = get_user(uid)
            if u["balance"] < t["price"]:
                bot.answer_callback_query(
                    call.id,
                    f"❌ Нужно {t['price']} ₽, у вас {u['balance']:.0f} ₽",
                    show_alert=True,
                )
                return
            k = types.InlineKeyboardMarkup()
            k.add(
                types.InlineKeyboardButton(
                    "✅ Подтвердить", callback_data=f"cf_{key}"
                ),
                types.InlineKeyboardButton(
                    "❌ Отмена", callback_data=f"t_{key}"
                ),
            )
            bot.edit_message_text(
                f"🛒 <b>Подтверждение покупки</b>\n\n"
                f"{t['name']}\n"
                f"💰 Цена: <b>{t['price']:,} ₽</b>\n"
                f"💵 Баланс: <b>{u['balance']:.0f} ₽</b>\n\n"
                f"Подтвердить?",
                call.message.chat.id,
                call.message.message_id,
                reply_markup=k,
            )

        elif d.startswith("cf_"):
            key = d[3:]
            t = TARIFFS[key]
            u = get_user(uid)
            if u["balance"] < t["price"]:
                bot.answer_callback_query(
                    call.id, "❌ Недостаточно средств!", show_alert=True
                )
                return
            buy_invest(uid, key)
            total = t["daily"] * t["days"]
            k = types.InlineKeyboardMarkup()
            k.add(
                types.InlineKeyboardButton(
                    "🎮 Купить ещё", callback_data="back_t"
                )
            )
            bot.edit_message_text(
                f"🎉 <b>Покупка совершена!</b>\n\n"
                f"{t['name']} теперь работает на вас!\n\n"
                f"📈 Доход: <b>{t['daily']:,} ₽/день</b>\n"
                f"📅 Срок: <b>{t['days']} дней</b>\n"
                f"💵 Ожидаемый доход: <b>{total:,} ₽</b>\n\n"
                f"Начисления происходят ежедневно ✨",
                call.message.chat.id,
                call.message.message_id,
                reply_markup=k,
            )

        elif d == "back_t":
            bot.edit_message_text(
                "🎮 <b>Персонажи Бикини Боттом</b>\n\n"
                "Выбери персонажа:",
                call.message.chat.id,
                call.message.message_id,
                reply_markup=kb_tariffs(),
            )

        # ---- Депозит ----
        elif d.startswith("paid_"):
            amt = float(d[5:])
            u = get_user(uid)
            did = mk_deposit(uid, amt)
            bot.edit_message_text(
                f"⏳ <b>Заявка #{did}</b>\n\n"
                f"💰 Сумма: {amt:.0f} ₽\n"
                f"Статус: ожидает подтверждения\n\n"
                f"Обычно до 30 минут.",
                call.message.chat.id,
                call.message.message_id,
            )
            for aid in ADMIN_IDS:
                try:
                    k = types.InlineKeyboardMarkup()
                    k.add(
                        types.InlineKeyboardButton(
                            "✅", callback_data=f"ad_{did}"
                        ),
                        types.InlineKeyboardButton(
                            "❌", callback_data=f"rd_{did}"
                        ),
                    )
                    bot.send_message(
                        aid,
                        f"🔔 <b>Депозит #{did}</b>\n\n"
                        f"👤 {u['first_name']} (@{u['username']}) "
                        f"[<code>{uid}</code>]\n"
                        f"💰 <b>{amt:.0f} ₽</b>",
                        reply_markup=k,
                    )
                except Exception:
                    pass

        elif d == "dep_cancel":
            bot.edit_message_text(
                "❌ Пополнение отменено.",
                call.message.chat.id,
                call.message.message_id,
            )

        # ---- Админ: депозиты ----
        elif d.startswith("ad_") and uid in ADMIN_IDS:
            dep = approve_dep(int(d[3:]))
            if dep:
                bot.edit_message_text(
                    f"✅ Депозит #{dep['id']} — {dep['amount']:.0f} ₽ подтверждён.",
                    call.message.chat.id,
                    call.message.message_id,
                )
                try:
                    bot.send_message(
                        dep["user_id"],
                        f"✅ <b>Пополнение подтверждено!</b>\n\n"
                        f"💰 <b>{dep['amount']:.0f} ₽</b> зачислено!\n"
                        f"Покупайте персонажа в 🎮",
                    )
                except Exception:
                    pass
            else:
                bot.answer_callback_query(
                    call.id, "Уже обработано", show_alert=True
                )

        elif d.startswith("rd_") and uid in ADMIN_IDS:
            dep = reject_dep(int(d[3:]))
            if dep:
                bot.edit_message_text(
                    f"❌ Депозит #{dep['id']} отклонён.",
                    call.message.chat.id,
                    call.message.message_id,
                )
                try:
                    bot.send_message(
                        dep["user_id"],
                        f"❌ <b>Заявка на пополнение отклонена.</b>\n"
                        f"Сумма: {dep['amount']:.0f} ₽\n"
                        f"Обратитесь в поддержку.",
                    )
                except Exception:
                    pass
            else:
                bot.answer_callback_query(
                    call.id, "Уже обработано", show_alert=True
                )

        # ---- Админ: выводы ----
        elif d.startswith("aw_") and uid in ADMIN_IDS:
            w = approve_wd(int(d[3:]))
            if w:
                bot.edit_message_text(
                    f"✅ Вывод #{w['id']} одобрен — {w['net']:.0f} ₽\n"
                    f"💳 <code>{w['wallet']}</code>",
                    call.message.chat.id,
                    call.message.message_id,
                )
                try:
                    bot.send_message(
                        w["user_id"],
                        f"✅ <b>Вывод одобрен!</b>\n\n"
                        f"💰 {w['net']:.0f} ₽ на <code>{w['wallet']}</code>\n"
                        f"Поступят в течение 24 ч.",
                    )
                except Exception:
                    pass
            else:
                bot.answer_callback_query(
                    call.id, "Уже обработано", show_alert=True
                )

        elif d.startswith("rw_") and uid in ADMIN_IDS:
            w = reject_wd(int(d[3:]))
            if w:
                bot.edit_message_text(
                    f"❌ Вывод #{w['id']} отклонён. Средства возвращены.",
                    call.message.chat.id,
                    call.message.message_id,
                )
                try:
                    bot.send_message(
                        w["user_id"],
                        f"❌ <b>Вывод отклонён.</b>\n"
                        f"Средства ({w['amount']:.0f} ₽) вернулись на баланс.",
                    )
                except Exception:
                    pass
            else:
                bot.answer_callback_query(
                    call.id, "Уже обработано", show_alert=True
                )

        # ---- Админ: панель ----
        elif d == "a_stats" and uid in ADMIN_IDS:
            s = stats()
            k = types.InlineKeyboardMarkup()
            k.add(types.InlineKeyboardButton("⬅️ Назад", callback_data="a_back"))
            bot.edit_message_text(
                f"📊 <b>Статистика</b>\n\n"
                f"👥 Пользователей: <b>{s['users']}</b>\n"
                f"📥 Депозитов: <b>{s['dep']:,.0f} ₽</b>\n"
                f"📤 Выводов: <b>{s['wdr']:,.0f} ₽</b>\n"
                f"💸 Комиссий: <b>{s['fees']:,.0f} ₽</b>\n\n"
                f"💰 <b>Профит: {s['profit']:,.0f} ₽</b>\n\n"
                f"🎮 Активных: {s['ainv']}\n"
                f"💵 Инвестировано: {s['tinv']:,.0f} ₽\n\n"
                f"⏳ Ожидают:\n"
                f"  Депозитов: {s['pdep']}\n"
                f"  Выводов: {s['pwd']}",
                call.message.chat.id,
                call.message.message_id,
                reply_markup=k,
            )

        elif d == "a_deps" and uid in ADMIN_IDS:
            deps = pending_deps()
            if not deps:
                bot.answer_callback_query(
                    call.id, "Нет ожидающих депозитов", show_alert=True
                )
                return
            for dp in deps[:15]:
                k = types.InlineKeyboardMarkup()
                k.add(
                    types.InlineKeyboardButton(
                        "✅", callback_data=f"ad_{dp['id']}"
                    ),
                    types.InlineKeyboardButton(
                        "❌", callback_data=f"rd_{dp['id']}"
                    ),
                )
                bot.send_message(
                    call.message.chat.id,
                    f"📥 #{dp['id']}  |  {dp['first_name']} "
                    f"(@{dp['username']})  "
                    f"[<code>{dp['user_id']}</code>]\n"
                    f"💰 <b>{dp['amount']:.0f} ₽</b>  |  {dp['created']}",
                    reply_markup=k,
                )

        elif d == "a_wds" and uid in ADMIN_IDS:
            wds = pending_wds()
            if not wds:
                bot.answer_callback_query(
                    call.id, "Нет ожидающих выводов", show_alert=True
                )
                return
            for w in wds[:15]:
                k = types.InlineKeyboardMarkup()
                k.add(
                    types.InlineKeyboardButton(
                        "✅", callback_data=f"aw_{w['id']}"
                    ),
                    types.InlineKeyboardButton(
                        "❌", callback_data=f"rw_{w['id']}"
                    ),
                )
                bot.send_message(
                    call.message.chat.id,
                    f"📤 #{w['id']}  |  {w['first_name']} "
                    f"(@{w['username']})  "
                    f"[<code>{w['user_id']}</code>]\n"
                    f"💰 {w['amount']:.0f} → {w['net']:.0f} ₽\n"
                    f"💳 <code>{w['wallet']}</code>",
                    reply_markup=k,
                )

        elif d == "a_bc" and uid in ADMIN_IDS:
            m = bot.send_message(
                call.message.chat.id, "📢 Введите текст рассылки:"
            )
            bot.register_next_step_handler(m, do_broadcast)

        elif d == "a_find" and uid in ADMIN_IDS:
            m = bot.send_message(
                call.message.chat.id, "👤 Введите ID пользователя:"
            )
            bot.register_next_step_handler(m, do_find_user)

        elif d == "a_add" and uid in ADMIN_IDS:
            m = bot.send_message(
                call.message.chat.id,
                "💰 Формат: <code>ID СУММА</code>\n"
                "Пример: <code>123456789 1000</code>",
            )
            bot.register_next_step_handler(m, do_add_balance)

        elif d == "a_accrue" and uid in ADMIN_IDS:
            accrue_income()
            bot.answer_callback_query(
                call.id, "✅ Доход начислен!", show_alert=True
            )

        elif d == "a_back" and uid in ADMIN_IDS:
            bot.edit_message_text(
                "🔧 <b>Админ‑панель</b>",
                call.message.chat.id,
                call.message.message_id,
                reply_markup=kb_admin(),
            )

        elif d.startswith("ban_") and uid in ADMIN_IDS:
            tid = int(d[4:])
            with db_lock:
                c = _conn()
                row = c.execute(
                    "SELECT banned FROM users WHERE user_id=?", (tid,)
                ).fetchone()
                if row:
                    nv = 0 if row["banned"] else 1
                    c.execute(
                        "UPDATE users SET banned=? WHERE user_id=?", (nv, tid)
                    )
                    c.commit()
                    st = "🔒 Заблокирован" if nv else "🔓 Разблокирован"
                    bot.answer_callback_query(call.id, st, show_alert=True)
                c.close()

        bot.answer_callback_query(call.id)

    except Exception as e:
        print(f"CB error: {e}")
        traceback.print_exc()
        try:
            bot.answer_callback_query(call.id, "⚠️ Ошибка")
        except Exception:
            pass


# ── Админ: step‑handlers ──────────────────────────────────

def do_broadcast(msg):
    if msg.from_user.id not in ADMIN_IDS:
        return
    text = msg.text or msg.caption or ""
    with db_lock:
        c = _conn()
        users = c.execute(
            "SELECT user_id FROM users WHERE banned=0"
        ).fetchall()
        c.close()
    ok = fail = 0
    for u in users:
        try:
            bot.send_message(u["user_id"], text, parse_mode="HTML")
            ok += 1
        except Exception:
            fail += 1
        time.sleep(0.04)
    bot.send_message(
        msg.chat.id,
        f"📢 <b>Рассылка завершена</b>\n✅ {ok}  ❌ {fail}",
    )


def do_find_user(msg):
    if msg.from_user.id not in ADMIN_IDS:
        return
    try:
        tid = int(msg.text.strip())
    except ValueError:
        bot.send_message(msg.chat.id, "❌ Введите числовой ID")
        return
    u = get_user(tid)
    if not u:
        bot.send_message(msg.chat.id, "❌ Не найден")
        return
    invs = get_investments(tid)
    k = types.InlineKeyboardMarkup()
    label = "🔓 Разбан" if u["banned"] else "🔒 Забанить"
    k.add(types.InlineKeyboardButton(label, callback_data=f"ban_{tid}"))
    bot.send_message(
        msg.chat.id,
        f"👤 <b>Пользователь</b>\n\n"
        f"🆔 <code>{u['user_id']}</code>\n"
        f"👤 {u['first_name']} (@{u['username'] or '—'})\n"
        f"💰 Баланс: {u['balance']:.2f} ₽\n"
        f"📈 Заработано: {u['total_earned']:.2f} ₽\n"
        f"📥 Пополнено: {u['total_dep']:.2f} ₽\n"
        f"📤 Выведено: {u['total_wdr']:.2f} ₽\n"
        f"👥 Рефералов: {u['ref_count']}\n"
        f"🎮 Активных: {len(invs)}\n"
        f"📅 Рег.: {u['reg_at']}\n"
        f"🚫 Бан: {'Да' if u['banned'] else 'Нет'}",
        reply_markup=k,
    )


def do_add_balance(msg):
    if msg.from_user.id not in ADMIN_IDS:
        return
    try:
        parts = msg.text.strip().split()
        tid = int(parts[0])
        val = float(parts[1])
    except (ValueError, IndexError):
        bot.send_message(msg.chat.id, "❌ Формат: ID СУММА")
        return
    if not get_user(tid):
        bot.send_message(msg.chat.id, "❌ Пользователь не найден")
        return
    add_balance(tid, val)
    bot.send_message(msg.chat.id, f"✅ Баланс {tid} изменён на {val:+.0f} ₽")
    if val > 0:
        try:
            bot.send_message(
                tid, f"💰 Вам начислено <b>{val:.0f} ₽</b> администратором!"
            )
        except Exception:
            pass


# ══════════════════════════════════════════════════════════════
#                         ЗАПУСК
# ══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("🧽 SpongeBob Money Bot")
    init_db()

    t = threading.Thread(target=scheduler, daemon=True)
    t.start()
    print("⏰ Планировщик дохода запущен")

    print("🚀 Бот работает!")
    while True:
        try:
            bot.infinity_polling(timeout=60, long_polling_timeout=60)
        except Exception as e:
            print(f"Polling error: {e}")
            time.sleep(5)