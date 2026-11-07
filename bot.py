import asyncio
import logging
import os
import sqlite3
from datetime import datetime, timezone
from urllib.parse import urlparse

from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)

# ============================================================
# НАСТРОЙКИ
# ============================================================

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_ID_RAW = os.getenv("ADMIN_ID", "").strip()

DB_PATH = "profit_quest.db"

# 300 000 копеек = 3 000 рублей
MIN_WITHDRAW_KOPECKS = 300_000

# XP за одну подтверждённую миссию
XP_PER_MISSION = 100


def load_admin_id() -> int:
    if not ADMIN_ID_RAW.isdigit():
        raise RuntimeError(
            "Укажите ADMIN_ID в переменных окружения как целое число."
        )
    return int(ADMIN_ID_RAW)


if not BOT_TOKEN:
    raise RuntimeError("Укажите BOT_TOKEN в переменных окружения.")

ADMIN_ID = load_admin_id()

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Бот работает только в личных сообщениях.
dp.message.filter(F.chat.type == "private")


# ============================================================
# СОСТОЯНИЯ
# ============================================================

class MissionProof(StatesGroup):
    waiting_for_text = State()


# ============================================================
# БАЗА ДАННЫХ
# ============================================================

def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def init_db() -> None:
    with get_connection() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT NOT NULL DEFAULT '',
                balance_kopecks INTEGER NOT NULL DEFAULT 0
                    CHECK (balance_kopecks >= 0),
                xp INTEGER NOT NULL DEFAULT 0
                    CHECK (xp >= 0),
                completed_missions INTEGER NOT NULL DEFAULT 0
                    CHECK (completed_missions >= 0),
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS missions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                description TEXT NOT NULL,
                url TEXT NOT NULL,
                reward_kopecks INTEGER NOT NULL
                    CHECK (reward_kopecks > 0),
                active INTEGER NOT NULL DEFAULT 1
                    CHECK (active IN (0, 1)),
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS mission_submissions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                mission_id INTEGER NOT NULL,
                proof TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'approved', 'rejected')),
                created_at TEXT NOT NULL,
                reviewed_at TEXT,
                UNIQUE(user_id, mission_id),
                FOREIGN KEY(user_id) REFERENCES users(user_id),
                FOREIGN KEY(mission_id) REFERENCES missions(id)
            );

            CREATE TABLE IF NOT EXISTS withdrawals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                amount_kopecks INTEGER NOT NULL
                    CHECK (amount_kopecks > 0),
                status TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'paid', 'rejected')),
                created_at TEXT NOT NULL,
                reviewed_at TEXT,
                FOREIGN KEY(user_id) REFERENCES users(user_id)
            );

            CREATE TABLE IF NOT EXISTS ledger (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                amount_kopecks INTEGER NOT NULL,
                kind TEXT NOT NULL,
                reference_id INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(kind, reference_id),
                FOREIGN KEY(user_id) REFERENCES users(user_id)
            );
            """
        )


def ensure_user(user: types.User) -> None:
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO users (user_id, username, created_at)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id)
            DO UPDATE SET username = excluded.username
            """,
            (user.id, user.username or "", now_utc()),
        )


def get_user(user_id: int):
    with get_connection() as conn:
        return conn.execute(
            "SELECT * FROM users WHERE user_id = ?",
            (user_id,),
        ).fetchone()


def format_rubles(kopecks: int) -> str:
    sign = "-" if kopecks < 0 else ""
    value = abs(kopecks)
    rubles, cents = divmod(value, 100)
    return f"{sign}{rubles:,}".replace(",", " ") + f",{cents:02d} ₽"


def player_level(xp: int) -> int:
    return xp // 500 + 1


def is_admin(user_id: int) -> bool:
    return user_id == ADMIN_ID


async def notify_admin(text: str) -> None:
    try:
        await bot.send_message(ADMIN_ID, text)
    except Exception:
        # Данные уже сохранены в БД. Администратор может посмотреть /queue.
        logging.exception("Не удалось отправить уведомление администратору")


async def notify_user(user_id: int, text: str) -> None:
    try:
        await bot.send_message(user_id, text)
    except Exception:
        logging.exception("Не удалось отправить уведомление пользователю %s", user_id)


# ============================================================
# КЛАВИАТУРЫ
# ============================================================

def main_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🗺 Карта миссий",
                    callback_data="missions",
                )
            ],
            [
                InlineKeyboardButton(
                    text="👤 Профиль",
                    callback_data="profile",
                ),
                InlineKeyboardButton(
                    text="💳 Вывод",
                    callback_data="withdraw",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="📜 Как работает игра",
                    callback_data="rules",
                )
            ],
        ]
    )


def back_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔙 Главное меню",
                    callback_data="home",
                )
            ]
        ]
    )


# ============================================================
# СТАРТ И МЕНЮ
# ============================================================

async def show_home(message: types.Message, user_id: int) -> None:
    user = get_user(user_id)

    if user is None:
        await message.answer("Сначала отправьте команду /start.")
        return

    text = (
        "🎮 PROFIT QUEST\n\n"
        "Здесь можно заработать деньги, выполняя реальные миссии "
        "от рекламодателей и партнёров.\n\n"
        "Как это работает:\n"
        "1. Выберите доступную миссию.\n"
        "2. Выполните её условия и отправьте отчёт.\n"
        "3. После проверки получите указанную награду и игровой опыт.\n\n"
        "💡 Доход зависит от доступности заданий и результатов проверки. "
        "Гарантированного заработка нет.\n\n"
        f"🏆 Ваш уровень: {player_level(user['xp'])}\n"
        f"⭐ Опыт: {user['xp']} XP\n"
        f"💳 Подтверждённый баланс: "
        f"{format_rubles(user['balance_kopecks'])}\n"
        f"🏦 Минимальный вывод: "
        f"{format_rubles(MIN_WITHDRAW_KOPECKS)}\n\n"
        "Для заработка и подачи заявки на вывод покупать ничего не нужно."
    )

    await message.answer(text, reply_markup=main_keyboard())


@dp.message(CommandStart())
async def start(message: types.Message, state: FSMContext) -> None:
    await state.clear()
    ensure_user(message.from_user)
    await show_home(message, message.from_user.id)


@dp.callback_query(F.data == "home")
async def home_callback(
    callback: types.CallbackQuery,
    state: FSMContext,
) -> None:
    await state.clear()
    ensure_user(callback.from_user)
    await callback.answer()
    await show_home(callback.message, callback.from_user.id)


@dp.callback_query(F.data == "rules")
async def show_rules(callback: types.CallbackQuery) -> None:
    await callback.answer()

    await callback.message.answer(
        "📜 ПРАВИЛА ИГРЫ\n\n"
        "• Миссии добавляет администратор на основании реальных заданий.\n"
        "• До выполнения проверьте условия и сумму награды.\n"
        "• Отправка отчёта не означает автоматическое одобрение.\n"
        "• Рубли начисляются только после подтверждения задания.\n"
        "• XP — игровые очки; их нельзя вывести как деньги.\n"
        "• Подать заявку на вывод можно от 3 000 ₽.\n"
        "• Заявки обрабатываются вручную. Срок выплаты согласовывается "
        "с администратором.\n"
        "• Не отправляйте в бот пароли, коды из СМС, CVV карты "
        "или фотографии документов.\n\n"
        "Если миссий нет, заработок временно недоступен.",
        reply_markup=back_keyboard(),
    )


# ============================================================
# МИССИИ
# ============================================================

@dp.callback_query(F.data == "missions")
async def list_missions(callback: types.CallbackQuery) -> None:
    ensure_user(callback.from_user)

    with get_connection() as conn:
        missions = conn.execute(
            """
            SELECT
                m.id,
                m.title,
                m.reward_kopecks,
                s.status AS submission_status
            FROM missions m
            LEFT JOIN mission_submissions s
                ON s.mission_id = m.id
                AND s.user_id = ?
            WHERE m.active = 1
            ORDER BY m.id DESC
            LIMIT 20
            """,
            (callback.from_user.id,),
        ).fetchall()

    await callback.answer()

    if not missions:
        await callback.message.answer(
            "🗺 Сейчас доступных миссий нет.\n\n"
            "Новые задания появятся здесь, когда администратор "
            "добавит реальные предложения.",
            reply_markup=back_keyboard(),
        )
        return

    buttons = []

    for mission in missions:
        status = mission["submission_status"]

        if status == "pending":
            prefix = "⏳"
        elif status == "approved":
            prefix = "✅"
        elif status == "rejected":
            prefix = "🔄"
        else:
            prefix = "🎯"

        title = mission["title"][:40]
        reward = format_rubles(mission["reward_kopecks"])

        buttons.append(
            [
                InlineKeyboardButton(
                    text=f"{prefix} {title} — {reward}",
                    callback_data=f"mission:{mission['id']}",
                )
            ]
        )

    buttons.append(
        [
            InlineKeyboardButton(
                text="🔙 Главное меню",
                callback_data="home",
            )
        ]
    )

    await callback.message.answer(
        "🗺 КАРТА МИССИЙ\n\n"
        "🎯 — доступна\n"
        "⏳ — отчёт на проверке\n"
        "✅ — подтверждена\n"
        "🔄 — отчёт отклонён, можно отправить заново\n\n"
        "Нажмите на миссию, чтобы прочитать условия.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )


@dp.callback_query(F.data.startswith("mission:"))
async def show_mission(callback: types.CallbackQuery) -> None:
    try:
        mission_id = int(callback.data.split(":", 1)[1])
    except (ValueError, IndexError):
        await callback.answer("Некорректная миссия.", show_alert=True)
        return

    with get_connection() as conn:
        mission = conn.execute(
            "SELECT * FROM missions WHERE id = ? AND active = 1",
            (mission_id,),
        ).fetchone()

        submission = conn.execute(
            """
            SELECT status
            FROM mission_submissions
            WHERE user_id = ? AND mission_id = ?
            """,
            (callback.from_user.id, mission_id),
        ).fetchone()

    if mission is None:
        await callback.answer("Миссия больше недоступна.", show_alert=True)
        return

    status = submission["status"] if submission else None

    status_text = {
        None: "Можно выполнять",
        "pending": "Отчёт ожидает проверки",
        "approved": "Миссия подтверждена",
        "rejected": "Отчёт отклонён; можно отправить новый",
    }[status]

    buttons = [
        [
            InlineKeyboardButton(
                text="🔗 Открыть задание",
                url=mission["url"],
            )
        ]
    ]

    if status in (None, "rejected"):
        buttons.append(
            [
                InlineKeyboardButton(
                    text="📩 Отправить отчёт",
                    callback_data=f"proof:{mission_id}",
                )
            ]
        )

    buttons.append(
        [
            InlineKeyboardButton(
                text="🔙 К миссиям",
                callback_data="missions",
            )
        ]
    )

    await callback.answer()

    await callback.message.answer(
        f"🎯 МИССИЯ #{mission['id']}\n\n"
        f"{mission['title']}\n\n"
        f"📋 Условия:\n{mission['description']}\n\n"
        f"💰 Награда после подтверждения: "
        f"{format_rubles(mission['reward_kopecks'])}\n"
        f"⭐ Игровой опыт: {XP_PER_MISSION} XP\n"
        f"📌 Статус: {status_text}\n\n"
        "Не отправляйте пароли, коды из СМС, CVV или данные документов.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )


@dp.callback_query(F.data.startswith("proof:"))
async def request_proof(
    callback: types.CallbackQuery,
    state: FSMContext,
) -> None:
    try:
        mission_id = int(callback.data.split(":", 1)[1])
    except (ValueError, IndexError):
        await callback.answer("Некорректная миссия.", show_alert=True)
        return

    with get_connection() as conn:
        mission = conn.execute(
            "SELECT id FROM missions WHERE id = ? AND active = 1",
            (mission_id,),
        ).fetchone()

        submission = conn.execute(
            """
            SELECT status
            FROM mission_submissions
            WHERE user_id = ? AND mission_id = ?
            """,
            (callback.from_user.id, mission_id),
        ).fetchone()

    if mission is None:
        await callback.answer("Миссия больше недоступна.", show_alert=True)
        return

    if submission and submission["status"] in ("pending", "approved"):
        await callback.answer(
            "Отчёт уже отправлен или миссия подтверждена.",
            show_alert=True,
        )
        return

    await state.set_state(MissionProof.waiting_for_text)
    await state.update_data(mission_id=mission_id)

    await callback.answer()
    await callback.message.answer(
        f"📩 Отчёт по миссии #{mission_id}\n\n"
        "Отправьте текстовое описание результата: например, "
        "идентификатор заявки, который разрешено передавать для проверки.\n\n"
        "Не отправляйте пароли, коды из СМС, CVV, полные реквизиты "
        "карт или фотографии документов.\n\n"
        "Для отмены отправьте /cancel.",
    )


@dp.message(Command("cancel"))
async def cancel_action(
    message: types.Message,
    state: FSMContext,
) -> None:
    await state.clear()
    ensure_user(message.from_user)
    await message.answer("Действие отменено.")
    await show_home(message, message.from_user.id)


@dp.message(MissionProof.waiting_for_text)
async def receive_proof(
    message: types.Message,
    state: FSMContext,
) -> None:
    if not message.text:
        await message.answer(
            "В этой версии принимается только текстовый отчёт. "
            "Попробуйте ещё раз или отправьте /cancel."
        )
        return

    proof = message.text.strip()

    if not 3 <= len(proof) <= 1000:
        await message.answer("Длина отчёта должна быть от 3 до 1000 символов.")
        return

    data = await state.get_data()
    mission_id = data.get("mission_id")

    if not isinstance(mission_id, int):
        await state.clear()
        await message.answer("Не удалось определить миссию. Выберите её снова.")
        return

    ensure_user(message.from_user)

    conn = get_connection()

    try:
        conn.execute("BEGIN IMMEDIATE")

        mission = conn.execute(
            "SELECT * FROM missions WHERE id = ? AND active = 1",
            (mission_id,),
        ).fetchone()

        if mission is None:
            conn.rollback()
            await state.clear()
            await message.answer("Миссия больше недоступна.")
            return

        existing = conn.execute(
            """
            SELECT id, status
            FROM mission_submissions
            WHERE user_id = ? AND mission_id = ?
            """,
            (message.from_user.id, mission_id),
        ).fetchone()

        if existing and existing["status"] in ("pending", "approved"):
            conn.rollback()
            await state.clear()
            await message.answer("Отчёт уже находится на проверке или одобрен.")
            return

        if existing:
            conn.execute(
                """
                UPDATE mission_submissions
                SET proof = ?, status = 'pending',
                    created_at = ?, reviewed_at = NULL
                WHERE id = ? AND status = 'rejected'
                """,
                (proof, now_utc(), existing["id"]),
            )
            submission_id = existing["id"]
        else:
            cursor = conn.execute(
                """
                INSERT INTO mission_submissions
                    (user_id, mission_id, proof, status, created_at)
                VALUES (?, ?, ?, 'pending', ?)
                """,
                (message.from_user.id, mission_id, proof, now_utc()),
            )
            submission_id = cursor.lastrowid

        conn.commit()

    except Exception:
        conn.rollback()
        logging.exception("Ошибка сохранения отчёта")
        await message.answer("Не удалось сохранить отчёт. Попробуйте позже.")
        return
    finally:
        conn.close()

    await state.clear()

    await message.answer(
        f"✅ Отчёт #{submission_id} отправлен на проверку.\n\n"
        f"Миссия: {mission['title']}\n"
        f"Возможная награда: {format_rubles(mission['reward_kopecks'])}\n\n"
        "Рубли и XP начислятся только после подтверждения.",
        reply_markup=back_keyboard(),
    )

    await notify_admin(
        f"📩 Новый отчёт #{submission_id}\n"
        f"Пользователь: {message.from_user.id}\n"
        f"Миссия: #{mission_id} — {mission['title']}\n"
        f"Награда: {format_rubles(mission['reward_kopecks'])}\n\n"
        f"Отчёт:\n{proof}\n\n"
        f"Одобрить: /approve {submission_id}\n"
        f"Отклонить: /rejectmission {submission_id}"
    )


# ============================================================
# ПРОФИЛЬ И ВЫВОД
# ============================================================

@dp.callback_query(F.data == "profile")
async def profile(callback: types.CallbackQuery) -> None:
    ensure_user(callback.from_user)
    user = get_user(callback.from_user.id)

    with get_connection() as conn:
        pending = conn.execute(
            """
            SELECT COUNT(*) AS total
            FROM mission_submissions
            WHERE user_id = ? AND status = 'pending'
            """,
            (callback.from_user.id,),
        ).fetchone()["total"]

    await callback.answer()

    await callback.message.answer(
        "👤 ПРОФИЛЬ ИГРОКА\n\n"
        f"🆔 ID: {user['user_id']}\n"
        f"🏆 Уровень: {player_level(user['xp'])}\n"
        f"⭐ Опыт: {user['xp']} XP\n"
        f"✅ Подтверждено миссий: {user['completed_missions']}\n"
        f"⏳ Отчётов на проверке: {pending}\n"
        f"💳 Доступно к выводу: "
        f"{format_rubles(user['balance_kopecks'])}\n\n"
        "XP — игровые очки. Вывести можно только рублёвый баланс.",
        reply_markup=back_keyboard(),
    )


@dp.callback_query(F.data == "withdraw")
async def withdrawal_screen(callback: types.CallbackQuery) -> None:
    ensure_user(callback.from_user)
    user = get_user(callback.from_user.id)
    balance = user["balance_kopecks"]

    await callback.answer()

    if balance < MIN_WITHDRAW_KOPECKS:
        missing = MIN_WITHDRAW_KOPECKS - balance

        await callback.message.answer(
            "🏦 ВЫВОД СРЕДСТВ\n\n"
            f"Доступно: {format_rubles(balance)}\n"
            f"Минимальная сумма: "
            f"{format_rubles(MIN_WITHDRAW_KOPECKS)}\n"
            f"До минимальной суммы: {format_rubles(missing)}\n\n"
            "Покупать платные функции для вывода не нужно.",
            reply_markup=back_keyboard(),
        )
        return

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📨 Подать заявку на весь баланс",
                    callback_data="withdraw_confirm",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔙 Главное меню",
                    callback_data="home",
                )
            ],
        ]
    )

    await callback.message.answer(
        "🏦 ВЫВОД СРЕДСТВ\n\n"
        f"Доступно: {format_rubles(balance)}\n"
        f"Минимальная сумма: "
        f"{format_rubles(MIN_WITHDRAW_KOPECKS)}\n\n"
        "В этой версии заявка оформляется на весь доступный баланс "
        "и обрабатывается вручную.\n\n"
        "После подачи администратор свяжется с вами для согласования "
        "способа выплаты. Не отправляйте боту номер карты, CVV, "
        "пароли или коды из СМС.",
        reply_markup=keyboard,
    )


@dp.callback_query(F.data == "withdraw_confirm")
async def create_withdrawal(callback: types.CallbackQuery) -> None:
    ensure_user(callback.from_user)

    conn = get_connection()

    try:
        conn.execute("BEGIN IMMEDIATE")

        user = conn.execute(
            "SELECT balance_kopecks FROM users WHERE user_id = ?",
            (callback.from_user.id,),
        ).fetchone()

        balance = user["balance_kopecks"]

        if balance < MIN_WITHDRAW_KOPECKS:
            conn.rollback()
            await callback.answer(
                "На балансе меньше 3 000 ₽.",
                show_alert=True,
            )
            return

        cursor = conn.execute(
            """
            UPDATE users
            SET balance_kopecks = balance_kopecks - ?
            WHERE user_id = ? AND balance_kopecks >= ?
            """,
            (balance, callback.from_user.id, balance),
        )

        if cursor.rowcount != 1:
            conn.rollback()
            await callback.answer(
                "Не удалось зарезервировать баланс.",
                show_alert=True,
            )
            return

        cursor = conn.execute(
            """
            INSERT INTO withdrawals
                (user_id, amount_kopecks, status, created_at)
            VALUES (?, ?, 'pending', ?)
            """,
            (callback.from_user.id, balance, now_utc()),
        )

        withdrawal_id = cursor.lastrowid

        conn.execute(
            """
            INSERT INTO ledger
                (user_id, amount_kopecks, kind, reference_id, created_at)
            VALUES (?, ?, 'withdrawal_reserve', ?, ?)
            """,
            (
                callback.from_user.id,
                -balance,
                withdrawal_id,
                now_utc(),
            ),
        )

        conn.commit()

    except Exception:
        conn.rollback()
        logging.exception("Ошибка создания заявки на вывод")
        await callback.answer("Ошибка. Попробуйте позже.", show_alert=True)
        return
    finally:
        conn.close()

    await callback.answer("Заявка создана.")

    await callback.message.answer(
        f"✅ Заявка на вывод #{withdrawal_id} создана.\n"
        f"Сумма: {format_rubles(balance)}\n"
        "Статус: ожидает обработки администратором.\n\n"
        "Сумма зарезервирована. Если заявка будет отклонена, "
        "она вернётся на баланс.",
        reply_markup=back_keyboard(),
    )

    await notify_admin(
        f"🏦 Новая заявка на вывод #{withdrawal_id}\n"
        f"Пользователь: {callback.from_user.id}\n"
        f"Сумма: {format_rubles(balance)}\n\n"
        "После фактического перевода:\n"
        f"/paid {withdrawal_id}\n\n"
        "Отклонить и вернуть деньги на баланс:\n"
        f"/returnwithdraw {withdrawal_id}"
    )


# ============================================================
# АДМИН-ПАНЕЛЬ
# ============================================================

@dp.message(Command("admin"))
async def admin_help(message: types.Message) -> None:
    if not is_admin(message.from_user.id):
        return

    await message.answer(
        "🛠 АДМИН-ПАНЕЛЬ\n\n"
        "Создать миссию:\n"
        "/newtask Название | Награда в целых рублях | "
        "Описание условий | https://ссылка\n\n"
        "Пример:\n"
        "/newtask Тест приложения | 300 | "
        "Пройдите тест и укажите ID заявки | https://example.com\n\n"
        "Показать ожидающие отчёты и выплаты:\n"
        "/queue\n\n"
        "Одобрить отчёт:\n"
        "/approve ID_отчёта\n\n"
        "Отклонить отчёт:\n"
        "/rejectmission ID_отчёта\n\n"
        "Закрыть миссию для новых отчётов:\n"
        "/closetask ID_миссии\n\n"
        "Отметить фактически отправленную выплату:\n"
        "/paid ID_выплаты\n\n"
        "Отклонить выплату и вернуть деньги:\n"
        "/returnwithdraw ID_выплаты\n\n"
        "Публикуйте только реальные задания с обеспеченным "
        "бюджетом на вознаграждения."
    )


@dp.message(Command("newtask"))
async def create_mission(message: types.Message) -> None:
    if not is_admin(message.from_user.id):
        return

    raw = message.text.partition(" ")[2].strip()
    parts = [part.strip() for part in raw.split("|")]

    if len(parts) != 4:
        await message.answer(
            "Формат:\n"
            "/newtask Название | Награда в рублях | Описание | https://ссылка"
        )
        return

    title, reward_text, description, url = parts

    if not 3 <= len(title) <= 100:
        await message.answer("Название должно содержать от 3 до 100 символов.")
        return

    if not 5 <= len(description) <= 1500:
        await message.answer("Описание должно содержать от 5 до 1500 символов.")
        return

    if not reward_text.isdigit():
        await message.answer("Награду укажите целым числом рублей.")
        return

    reward_rubles = int(reward_text)

    if not 1 <= reward_rubles <= 1_000_000:
        await message.answer("Награда должна быть от 1 до 1 000 000 ₽.")
        return

    parsed = urlparse(url)

    if parsed.scheme != "https" or not parsed.netloc:
        await message.answer("Ссылка должна начинаться с https://")
        return

    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO missions
                (title, description, url, reward_kopecks, active, created_at)
            VALUES (?, ?, ?, ?, 1, ?)
            """,
            (
                title,
                description,
                url,
                reward_rubles * 100,
                now_utc(),
            ),
        )
        mission_id = cursor.lastrowid

    await message.answer(
        f"✅ Миссия #{mission_id} добавлена.\n"
        f"Название: {title}\n"
        f"Награда: {format_rubles(reward_rubles * 100)}\n\n"
        "Убедитесь, что бюджет рассчитан на всех участников: "
        "эта версия бота не ограничивает число выполнений."
    )


def parse_command_id(text: str) -> int | None:
    parts = text.split()

    if len(parts) != 2 or not parts[1].isdigit():
        return None

    value = int(parts[1])
    return value if value > 0 else None


@dp.message(Command("closetask"))
async def close_mission(message: types.Message) -> None:
    if not is_admin(message.from_user.id):
        return

    mission_id = parse_command_id(message.text)

    if mission_id is None:
        await message.answer("Формат: /closetask ID_миссии")
        return

    with get_connection() as conn:
        cursor = conn.execute(
            "UPDATE missions SET active = 0 WHERE id = ? AND active = 1",
            (mission_id,),
        )

    if cursor.rowcount:
        await message.answer(f"Миссия #{mission_id} закрыта для новых отчётов.")
    else:
        await message.answer("Миссия не найдена или уже закрыта.")


@dp.message(Command("queue"))
async def admin_queue(message: types.Message) -> None:
    if not is_admin(message.from_user.id):
        return

    with get_connection() as conn:
        submissions = conn.execute(
            """
            SELECT s.id, s.user_id, s.mission_id, s.proof,
                   m.title, m.reward_kopecks
            FROM mission_submissions s
            JOIN missions m ON m.id = s.mission_id
            WHERE s.status = 'pending'
            ORDER BY s.id
            LIMIT 10
            """
        ).fetchall()

        withdrawals = conn.execute(
            """
            SELECT id, user_id, amount_kopecks
            FROM withdrawals
            WHERE status = 'pending'
            ORDER BY id
            LIMIT 10
            """
        ).fetchall()

    if not submissions and not withdrawals:
        await message.answer("Очередь пуста.")
        return

    await message.answer(
        "📋 Очередь: показаны до 10 отчётов и до 10 заявок на вывод."
    )

    for item in submissions:
        await message.answer(
            f"📩 Отчёт #{item['id']}\n"
            f"Пользователь: {item['user_id']}\n"
            f"Миссия #{item['mission_id']}: {item['title']}\n"
            f"Награда: {format_rubles(item['reward_kopecks'])}\n"
            f"Отчёт: {item['proof']}\n\n"
            f"/approve {item['id']}\n"
            f"/rejectmission {item['id']}"
        )

    for item in withdrawals:
        await message.answer(
            f"🏦 Вывод #{item['id']}\n"
            f"Пользователь: {item['user_id']}\n"
            f"Сумма: {format_rubles(item['amount_kopecks'])}\n\n"
            f"/paid {item['id']}\n"
            f"/returnwithdraw {item['id']}"
        )


# ============================================================
# ПРОВЕРКА ОТЧЁТОВ
# ============================================================

@dp.message(Command("approve"))
async def approve_submission(message: types.Message) -> None:
    if not is_admin(message.from_user.id):
        return

    submission_id = parse_command_id(message.text)

    if submission_id is None:
        await message.answer("Формат: /approve ID_отчёта")
        return

    conn = get_connection()

    try:
        conn.execute("BEGIN IMMEDIATE")

        submission = conn.execute(
            """
            SELECT s.*, m.title, m.reward_kopecks
            FROM mission_submissions s
            JOIN missions m ON m.id = s.mission_id
            WHERE s.id = ?
            """,
            (submission_id,),
        ).fetchone()

        if submission is None or submission["status"] != "pending":
            conn.rollback()
            await message.answer("Ожидающий отчёт не найден.")
            return

        cursor = conn.execute(
            """
            UPDATE mission_submissions
            SET status = 'approved', reviewed_at = ?
            WHERE id = ? AND status = 'pending'
            """,
            (now_utc(), submission_id),
        )

        if cursor.rowcount != 1:
            conn.rollback()
            await message.answer("Отчёт уже обработан.")
            return

        conn.execute(
            """
            UPDATE users
            SET balance_kopecks = balance_kopecks + ?,
                xp = xp + ?,
                completed_missions = completed_missions + 1
            WHERE user_id = ?
            """,
            (
                submission["reward_kopecks"],
                XP_PER_MISSION,
                submission["user_id"],
            ),
        )

        conn.execute(
            """
            INSERT INTO ledger
                (user_id, amount_kopecks, kind, reference_id, created_at)
            VALUES (?, ?, 'mission_reward', ?, ?)
            """,
            (
                submission["user_id"],
                submission["reward_kopecks"],
                submission_id,
                now_utc(),
            ),
        )

        conn.commit()

    except Exception:
        conn.rollback()
        logging.exception("Ошибка одобрения отчёта")
        await message.answer("Не удалось обработать отчёт.")
        return
    finally:
        conn.close()

    await message.answer(
        f"✅ Отчёт #{submission_id} одобрен. Награда начислена."
    )

    await notify_user(
        submission["user_id"],
        f"🎉 Миссия «{submission['title']}» подтверждена!\n\n"
        f"💰 Начислено: "
        f"{format_rubles(submission['reward_kopecks'])}\n"
        f"⭐ Получено: {XP_PER_MISSION} XP",
    )


@dp.message(Command("rejectmission"))
async def reject_submission(message: types.Message) -> None:
    if not is_admin(message.from_user.id):
        return

    submission_id = parse_command_id(message.text)

    if submission_id is None:
        await message.answer("Формат: /rejectmission ID_отчёта")
        return

    conn = get_connection()

    try:
        conn.execute("BEGIN IMMEDIATE")

        submission = conn.execute(
            """
            SELECT s.user_id, s.status, m.title
            FROM mission_submissions s
            JOIN missions m ON m.id = s.mission_id
            WHERE s.id = ?
            """,
            (submission_id,),
        ).fetchone()

        if submission is None or submission["status"] != "pending":
            conn.rollback()
            await message.answer("Ожидающий отчёт не найден.")
            return

        conn.execute(
            """
            UPDATE mission_submissions
            SET status = 'rejected', reviewed_at = ?
            WHERE id = ? AND status = 'pending'
            """,
            (now_utc(), submission_id),
        )

        conn.commit()

    except Exception:
        conn.rollback()
        logging.exception("Ошибка отклонения отчёта")
        await message.answer("Не удалось обработать отчёт.")
        return
    finally:
        conn.close()

    await message.answer(f"Отчёт #{submission_id} отклонён.")

    await notify_user(
        submission["user_id"],
        f"Отчёт по миссии «{submission['title']}» отклонён.\n"
        "Проверьте условия и при необходимости отправьте новый отчёт.",
    )


# ============================================================
# ОБРАБОТКА ВЫПЛАТ
# ============================================================

@dp.message(Command("paid"))
async def mark_paid(message: types.Message) -> None:
    if not is_admin(message.from_user.id):
        return

    withdrawal_id = parse_command_id(message.text)

    if withdrawal_id is None:
        await message.answer("Формат: /paid ID_выплаты")
        return

    conn = get_connection()

    try:
        conn.execute("BEGIN IMMEDIATE")

        withdrawal = conn.execute(
            "SELECT * FROM withdrawals WHERE id = ?",
            (withdrawal_id,),
        ).fetchone()

        if withdrawal is None or withdrawal["status"] != "pending":
            conn.rollback()
            await message.answer("Ожидающая заявка не найдена.")
            return

        conn.execute(
            """
            UPDATE withdrawals
            SET status = 'paid', reviewed_at = ?
            WHERE id = ? AND status = 'pending'
            """,
            (now_utc(), withdrawal_id),
        )

        conn.commit()

    except Exception:
        conn.rollback()
        logging.exception("Ошибка обновления выплаты")
        await message.answer("Не удалось обновить выплату.")
        return
    finally:
        conn.close()

    await message.answer(
        f"Заявка #{withdrawal_id} отмечена как оплаченная.\n"
        "Помните: команда сама не переводит деньги."
    )

    await notify_user(
        withdrawal["user_id"],
        f"✅ Администратор отметил заявку #{withdrawal_id} "
        f"как оплаченную.\n"
        f"Сумма: {format_rubles(withdrawal['amount_kopecks'])}\n\n"
        "Если деньги не поступили, свяжитесь с поддержкой проекта.",
    )


@dp.message(Command("returnwithdraw"))
async def return_withdrawal(message: types.Message) -> None:
    if not is_admin(message.from_user.id):
        return

    withdrawal_id = parse_command_id(message.text)

    if withdrawal_id is None:
        await message.answer("Формат: /returnwithdraw ID_выплаты")
        return

    conn = get_connection()

    try:
        conn.execute("BEGIN IMMEDIATE")

        withdrawal = conn.execute(
            "SELECT * FROM withdrawals WHERE id = ?",
            (withdrawal_id,),
        ).fetchone()

        if withdrawal is None or withdrawal["status"] != "pending":
            conn.rollback()
            await message.answer("Ожидающая заявка не найдена.")
            return

        cursor = conn.execute(
            """
            UPDATE withdrawals
            SET status = 'rejected', reviewed_at = ?
            WHERE id = ? AND status = 'pending'
            """,
            (now_utc(), withdrawal_id),
        )

        if cursor.rowcount != 1:
            conn.rollback()
            await message.answer("Заявка уже обработана.")
            return

        conn.execute(
            """
            UPDATE users
            SET balance_kopecks = balance_kopecks + ?
            WHERE user_id = ?
            """,
            (withdrawal["amount_kopecks"], withdrawal["user_id"]),
        )

        conn.execute(
            """
            INSERT INTO ledger
                (user_id, amount_kopecks, kind, reference_id, created_at)
            VALUES (?, ?, 'withdrawal_return', ?, ?)
            """,
            (
                withdrawal["user_id"],
                withdrawal["amount_kopecks"],
                withdrawal_id,
                now_utc(),
            ),
        )

        conn.commit()

    except Exception:
        conn.rollback()
        logging.exception("Ошибка возврата выплаты")
        await message.answer("Не удалось вернуть сумму.")
        return
    finally:
        conn.close()

    await message.answer(
        f"Заявка #{withdrawal_id} отклонена. Деньги возвращены на баланс."
    )

    await notify_user(
        withdrawal["user_id"],
        f"Заявка на вывод #{withdrawal_id} отклонена.\n"
        f"На баланс возвращено: "
        f"{format_rubles(withdrawal['amount_kopecks'])}.",
    )


# ============================================================
# ЗАПУСК
# ============================================================

async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    init_db()

    logging.info("Profit Quest запущен")

    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
