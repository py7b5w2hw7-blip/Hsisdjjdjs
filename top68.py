import asyncio
import sqlite3
import os
from datetime import datetime
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, Command
from aiogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton,
    LabeledPrice, CallbackQuery, Message
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

# ═══════════════════════════════════════════════════════
# КОНФИГ ИЗ ПЕРЕМЕННЫХ ОКРУЖЕНИЯ (НЕ ЗАШИТ В КОД)
# ═══════════════════════════════════════════════════════

BOT_TOKEN      = os.getenv("BOT_TOKEN")
BOT_USERNAME   = os.getenv("BOT_USERNAME", "berrynano6bot")
ADMIN_ID       = int(os.getenv("ADMIN_ID", "7950533047"))
CHANNEL_LINK   = os.getenv("CHANNEL_LINK", "https://t.me/+otgte7DKQF40YmMy")
STARS_BUY      = os.getenv("STARS_BUY", "https://split.tg/?ref=UQD06L7Gv3pWk1J8DJ1wUeNsflj30ZmUyuZnb3zknSmVy5J-")
REF_PERCENT    = int(os.getenv("REF_PERCENT", "40"))

PLANS = {
    "full":   {"label": "50 ГБ", "stars": 600, "crypto": "https://t.me/send?start=IVfBnFlf6v5b"},
    "medium": {"label": "15 ГБ", "stars": 400, "crypto": "https://t.me/send?start=IVCR8jU3BohU"},
    "small":  {"label": "5 ГБ",  "stars": 350, "crypto": None},
}
PLAN_NAMES = {"full": "50 ГБ", "medium": "15 ГБ", "small": "5 ГБ"}

if not BOT_TOKEN:
    raise ValueError("Ошибка: BOT_TOKEN не задан в переменных окружения!")

# ═══════════════════════════════════════════════════════
# БАЗА ДАННЫХ
# ═══════════════════════════════════════════════════════

DB = "tendo.db"

def db_init():
    con = sqlite3.connect(DB)
    cur = con.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id     INTEGER PRIMARY KEY,
            username    TEXT,
            first_name  TEXT,
            joined_at   TEXT,
            ref_by      INTEGER DEFAULT NULL
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS purchases (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER,
            plan        TEXT,
            stars       INTEGER,
            paid_at     TEXT,
            ref_owner   INTEGER DEFAULT NULL
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS ref_earnings (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_id    INTEGER,
            from_user   INTEGER,
            stars       INTEGER,
            earned      INTEGER,
            paid_at     TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS withdrawals (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER,
            amount      INTEGER,
            status      TEXT DEFAULT 'pending',
            requested_at TEXT
        )
    """)
    con.commit()
    con.close()

def db_add_user(user: types.User, ref_by: int = None):
    con = sqlite3.connect(DB)
    cur = con.cursor()
    cur.execute("""
        INSERT OR IGNORE INTO users (user_id, username, first_name, joined_at, ref_by)
        VALUES (?, ?, ?, ?, ?)
    """, (user.id, user.username, user.first_name,
          datetime.now().strftime("%Y-%m-%d %H:%M"), ref_by))
    con.commit()
    con.close()

def db_get_ref_by(user_id: int):
    con = sqlite3.connect(DB)
    cur = con.cursor()
    row = cur.execute("SELECT ref_by FROM users WHERE user_id=?", (user_id,)).fetchone()
    con.close()
    return row[0] if row else None

def db_add_purchase(user_id: int, plan: str, stars: int) -> int:
    ref_by = db_get_ref_by(user_id)
    con = sqlite3.connect(DB)
    cur = con.cursor()
    cur.execute("""
        INSERT INTO purchases (user_id, plan, stars, paid_at, ref_owner)
        VALUES (?, ?, ?, ?, ?)
    """, (user_id, plan, stars, datetime.now().strftime("%Y-%m-%d %H:%M"), ref_by))
    con.commit()
    con.close()
    if ref_by and ref_by != user_id:
        earned = int(stars * REF_PERCENT / 100)
        con = sqlite3.connect(DB)
        cur = con.cursor()
        cur.execute("""
            INSERT INTO ref_earnings (owner_id, from_user, stars, earned, paid_at)
            VALUES (?, ?, ?, ?, ?)
        """, (ref_by, user_id, stars, earned, datetime.now().strftime("%Y-%m-%d %H:%M")))
        con.commit()
        con.close()
        return ref_by
    return 0

def db_get_ref_stats(user_id: int):
    con = sqlite3.connect(DB)
    cur = con.cursor()
    invited = cur.execute(
        "SELECT COUNT(*) FROM users WHERE ref_by=?", (user_id,)
    ).fetchone()[0]
    buyers = cur.execute(
        "SELECT COUNT(DISTINCT from_user) FROM ref_earnings WHERE owner_id=?", (user_id,)
    ).fetchone()[0]
    total_earned = cur.execute(
        "SELECT COALESCE(SUM(earned),0) FROM ref_earnings WHERE owner_id=?", (user_id,)
    ).fetchone()[0]
    paid_out = cur.execute(
        "SELECT COALESCE(SUM(amount),0) FROM withdrawals WHERE user_id=? AND status='done'", (user_id,)
    ).fetchone()[0]
    pending_req = cur.execute(
        "SELECT COALESCE(SUM(amount),0) FROM withdrawals WHERE user_id=? AND status='pending'", (user_id,)
    ).fetchone()[0]
    balance = total_earned - paid_out - pending_req
    recent = cur.execute("""
        SELECT u.first_name, u.username, re.stars, re.earned, re.paid_at
        FROM ref_earnings re LEFT JOIN users u ON re.from_user = u.user_id
        WHERE re.owner_id=? ORDER BY re.id DESC LIMIT 5
    """, (user_id,)).fetchall()
    con.close()
    return {
        "invited": invited, "buyers": buyers,
        "total_earned": total_earned, "paid_out": paid_out,
        "pending": pending_req,
        "balance": balance, "recent": recent
    }

def db_get_stats():
    con = sqlite3.connect(DB)
    cur = con.cursor()
    today = datetime.now().strftime("%Y-%m-%d")
    s = {
        "total_users":     cur.execute("SELECT COUNT(*) FROM users").fetchone()[0],
        "today_users":     cur.execute("SELECT COUNT(*) FROM users WHERE joined_at LIKE ?", (f"{today}%",)).fetchone()[0],
        "total_purchases": cur.execute("SELECT COUNT(*) FROM purchases").fetchone()[0],
        "today_purchases": cur.execute("SELECT COUNT(*) FROM purchases WHERE paid_at LIKE ?", (f"{today}%",)).fetchone()[0],
        "total_stars":     cur.execute("SELECT COALESCE(SUM(stars),0) FROM purchases").fetchone()[0],
        "total_earned":    cur.execute("SELECT COALESCE(SUM(earned),0) FROM ref_earnings").fetchone()[0],
        "pending_withdrawals": cur.execute("SELECT COUNT(*) FROM withdrawals WHERE status='pending'").fetchone()[0],
        "recent":          cur.execute("""
            SELECT u.first_name, u.username, p.plan, p.stars, p.paid_at
            FROM purchases p LEFT JOIN users u ON p.user_id=u.user_id
            ORDER BY p.id DESC LIMIT 5
        """).fetchall(),
    }
    con.close()
    return s

def db_get_all_users():
    con = sqlite3.connect(DB)
    rows = con.execute("SELECT user_id FROM users").fetchall()
    con.close()
    return [r[0] for r in rows]

def db_get_top_refs():
    con = sqlite3.connect(DB)
    cur = con.cursor()
    rows = cur.execute("""
        SELECT re.owner_id, u.first_name, u.username,
               COUNT(DISTINCT re.from_user) as buyers,
               SUM(re.earned) as earned
        FROM ref_earnings re LEFT JOIN users u ON re.owner_id=u.user_id
        GROUP BY re.owner_id
        ORDER BY earned DESC LIMIT 10
    """).fetchall()
    con.close()
    return rows

def db_get_ref_detail(user_id: int):
    con = sqlite3.connect(DB)
    cur = con.cursor()
    user = cur.execute("SELECT first_name, username FROM users WHERE user_id=?", (user_id,)).fetchone()
    invited = cur.execute("SELECT COUNT(*) FROM users WHERE ref_by=?", (user_id,)).fetchone()[0]
    earnings = cur.execute("""
        SELECT u.first_name, u.username, re.stars, re.earned, re.paid_at
        FROM ref_earnings re LEFT JOIN users u ON re.from_user=u.user_id
        WHERE re.owner_id=? ORDER BY re.id DESC LIMIT 10
    """, (user_id,)).fetchall()
    total = cur.execute(
        "SELECT COALESCE(SUM(earned),0) FROM ref_earnings WHERE owner_id=?", (user_id,)
    ).fetchone()[0]
    paid = cur.execute(
        "SELECT COALESCE(SUM(amount),0) FROM withdrawals WHERE user_id=? AND status='done'", (user_id,)
    ).fetchone()[0]
    pending = cur.execute(
        "SELECT COALESCE(SUM(amount),0) FROM withdrawals WHERE user_id=? AND status='pending'", (user_id,)
    ).fetchone()[0]
    con.close()
    return {"user": user, "invited": invited, "earnings": earnings,
            "total": total, "paid": paid, "pending": pending, "balance": total - paid - pending}

def db_get_pending_withdrawals():
    con = sqlite3.connect(DB)
    cur = con.cursor()
    rows = cur.execute("""
        SELECT w.id, w.user_id, u.first_name, u.username, w.amount, w.requested_at
        FROM withdrawals w LEFT JOIN users u ON w.user_id=u.user_id
        WHERE w.status='pending' ORDER BY w.id
    """).fetchall()
    con.close()
    return rows

def db_set_withdrawal_status(wid: int, status: str):
    con = sqlite3.connect(DB)
    con.execute("UPDATE withdrawals SET status=? WHERE id=?", (status, wid))
    con.commit()
    con.close()

def db_request_withdrawal(user_id: int, amount: int):
    con = sqlite3.connect(DB)
    con.execute("""
        INSERT INTO withdrawals (user_id, amount, status, requested_at)
        VALUES (?, ?, 'pending', ?)
    """, (user_id, amount, datetime.now().strftime("%Y-%m-%d %H:%M")))
    con.commit()
    con.close()

# ═══════════════════════════════════════════════════════
# STATES
# ═══════════════════════════════════════════════════════

class BroadcastState(StatesGroup):
    waiting_text = State()

class AdminState(StatesGroup):
    ref_lookup = State()

# ═══════════════════════════════════════════════════════
# INIT
# ═══════════════════════════════════════════════════════

db_init()
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# ═══════════════════════════════════════════════════════
# KEYBOARDS
# ═══════════════════════════════════════════════════════

def kb_main():
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="⭐ Оплатить звёздами", callback_data="menu_stars"))
    kb.row(InlineKeyboardButton(text="🌐 Оплатить криптой",  callback_data="menu_crypto"))
    kb.row(InlineKeyboardButton(text="🤝 Реферальная программа", callback_data="ref_menu"))
    kb.row(InlineKeyboardButton(text="💫 Где купить звёзды?", url=STARS_BUY))
    return kb.as_markup()

def kb_admin():
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="📊 Статистика",          callback_data="adm_stats"))
    kb.row(InlineKeyboardButton(text="📋 Последние покупки",   callback_data="adm_recent"))
    kb.row(InlineKeyboardButton(text="🤝 Рефералы — топ",      callback_data="adm_refs"))
    kb.row(InlineKeyboardButton(text="🔍 Реферал по ID",       callback_data="adm_ref_lookup"))
    kb.row(InlineKeyboardButton(text="💸 Заявки на выплату",   callback_data="adm_withdrawals"))
    kb.row(InlineKeyboardButton(text="👥 Пользователи",        callback_data="adm_users"))
    kb.row(InlineKeyboardButton(text="📢 Рассылка",            callback_data="adm_broadcast"))
    kb.row(InlineKeyboardButton(text="❌ Закрыть",             callback_data="adm_close"))
    return kb.as_markup()

def kb_back_admin():
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="◀️ Назад в админ", callback_data="adm_back")
    ]])

# ═══════════════════════════════════════════════════════
# /start
# ═══════════════════════════════════════════════════════

@dp.message(CommandStart())
async def cmd_start(message: Message):
    args = message.text.split()
    ref_by = None
    if len(args) > 1 and args[1].startswith("ref"):
        try:
            ref_id = int(args[1][3:])
            if ref_id != message.from_user.id:
                ref_by = ref_id
        except ValueError:
            pass

    db_add_user(message.from_user, ref_by)

    if ref_by:
        try:
            ref_user = await bot.get_chat(ref_by)
            ref_name = ref_user.first_name
        except Exception:
            ref_name = "пользователь"
        await message.answer(
            f"👋 Вы пришли по реферальной ссылке от <b>{ref_name}</b>!\n"
            f"После вашей покупки он получит <b>{REF_PERCENT}%</b> бонус ⭐",
            parse_mode="HTML"
        )

    await message.answer(
        "🌿 <b>TENDO</b>\n\n"
        "✅ Автовыдача сразу после оплаты\n"
        "🔒 Безопасная оплата через Telegram Stars\n\n"
        "Выберите способ оплаты:",
        parse_mode="HTML",
        reply_markup=kb_main()
    )

# ═══════════════════════════════════════════════════════
# /admin
# ═══════════════════════════════════════════════════════

@dp.message(Command("admin"))
async def cmd_admin(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    await message.answer(
        "🛡 <b>Админ-панель TENDO</b>\n\nВыберите действие:",
        parse_mode="HTML",
        reply_markup=kb_admin()
    )

# ═══════════════════════════════════════════════════════
# РЕФЕРАЛЬНОЕ МЕНЮ
# ═══════════════════════════════════════════════════════

@dp.callback_query(F.data == "ref_menu")
async def ref_menu(call: CallbackQuery):
    uid = call.from_user.id
    link = f"https://t.me/{BOT_USERNAME}?start=ref{uid}"
    s = db_get_ref_stats(uid)

    recent_lines = ""
    if s["recent"]:
        lines = []
        for name, uname, stars, earned, at in s["recent"]:
            lines.append(f"  • {name or '?'} — {stars}⭐ покупка, вам +{earned}⭐ ({at[:10]})")
        recent_lines = "\n\n📜 <b>Последние начисления:</b>\n" + "\n".join(lines)

    text = (
        "⭐ <b>Реферальная программа</b>\n\n"
        f"💸 Приглашайте людей и получайте <b>{REF_PERCENT}%</b> с их покупок!\n"
        f"Если по вашей ссылке купят тариф за 600⭐ — вы получите <b>{int(600*REF_PERCENT/100)}⭐</b>!\n\n"
        f"🔗 <b>Ваша реферальная ссылка:</b>\n"
        f"<code>{link}</code>\n\n"
        f"📈 <b>Ваша статистика:</b>\n"
        f"👥 Приглашено: <b>{s['invited']}</b> чел.\n"
        f"💳 Из них купили: <b>{s['buyers']}</b> чел.\n"
        f"⭐ Всего заработано: <b>{s['total_earned']}</b> звёзд\n"
        f"✅ Выплачено: <b>{s['paid_out']}</b> звёзд\n"
        f"⏳ На рассмотрении: <b>{s['pending']}</b> звёзд\n"
        f"💰 Баланс: <b>{s['balance']}</b> звёзд"
        f"{recent_lines}"
    )

    kb = InlineKeyboardBuilder()
    if s["balance"] > 0:
        kb.row(InlineKeyboardButton(
            text=f"💸 Вывести {s['balance']}⭐", callback_data="ref_withdraw"
        ))
    kb.row(InlineKeyboardButton(text="◀️ Назад", callback_data="back_start"))

    await call.message.edit_text(text, parse_mode="HTML", reply_markup=kb.as_markup())

@dp.callback_query(F.data == "ref_withdraw")
async def ref_withdraw(call: CallbackQuery):
    uid = call.from_user.id
    s = db_get_ref_stats(uid)
    if s["balance"] <= 0:
        await call.answer("У вас нет доступного баланса", show_alert=True)
        return

    db_request_withdrawal(uid, s["balance"])

    uname = f"@{call.from_user.username}" if call.from_user.username else call.from_user.first_name
    try:
        await bot.send_message(
            ADMIN_ID,
            f"💸 <b>Заявка на вывод!</b>\n\n"
            f"👤 {uname} (ID: <code>{uid}</code>)\n"
            f"⭐ Сумма: <b>{s['balance']}</b> звёзд\n"
            f"🕐 {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"
            f"Проверь в админ-панели → Заявки на выплату",
            parse_mode="HTML"
        )
    except Exception:
        pass

    await call.answer("✅ Заявка отправлена! Ожидайте выплату.", show_alert=True)
    await ref_menu(call)

# ═══════════════════════════════════════════════════════
# ADMIN CALLBACKS
# ═══════════════════════════════════════════════════════

@dp.callback_query(lambda c: c.data and c.data.startswith("adm_"))
async def admin_handler(call: CallbackQuery, state: FSMContext):
    if call.from_user.id != ADMIN_ID:
        await call.answer("⛔ Нет доступа", show_alert=True)
        return

    action = call.data

    if action == "adm_stats":
        s = db_get_stats()
        text = (
            "📊 <b>Статистика TENDO</b>\n\n"
            f"👥 Всего пользователей: <b>{s['total_users']}</b>\n"
            f"🆕 Новых сегодня: <b>{s['today_users']}</b>\n\n"
            f"💳 Всего покупок: <b>{s['total_purchases']}</b>\n"
            f"📅 Покупок сегодня: <b>{s['today_purchases']}</b>\n"
            f"⭐ Всего звёзд получено: <b>{s['total_stars']}</b>\n\n"
            f"🤝 Реф. выплаты начислено: <b>{s['total_earned']}</b>⭐\n"
            f"💸 Заявок на вывод: <b>{s['pending_withdrawals']}</b>"
        )
        await call.message.edit_text(text, parse_mode="HTML", reply_markup=kb_back_admin())

    elif action == "adm_recent":
        s = db_get_stats()
        if not s["recent"]:
            text = "📋 Покупок ещё нет."
        else:
            lines = ["📋 <b>Последние 5 покупок:</b>\n"]
            for name, uname, plan, stars, at in s["recent"]:
                lines.append(
                    f"• {name or '?'} (@{uname or '—'})\n"
                    f"  📦 {PLAN_NAMES.get(plan, plan)} — {stars}⭐ — {at}"
                )
            text = "\n\n".join(lines)
        await call.message.edit_text(text, parse_mode="HTML", reply_markup=kb_back_admin())

    elif action == "adm_refs":
        rows = db_get_top_refs()
        if not rows:
            text = "🤝 Реферальных продаж ещё нет."
        else:
            lines = ["🤝 <b>Топ рефереров:</b>\n"]
            for i, (uid, name, uname, buyers, earned) in enumerate(rows, 1):
                lines.append(
                    f"{i}. {name or '?'} (@{uname or '—'}) — ID <code>{uid}</code>\n"
                    f"   💳 Покупателей: {buyers} | ⭐ Заработано: {earned}"
                )
            text = "\n\n".join(lines)
        await call.message.edit_text(text, parse_mode="HTML", reply_markup=kb_back_admin())

    elif action == "adm_ref_lookup":
        await state.set_state(AdminState.ref_lookup)
        await call.message.edit_text(
            "🔍 Введите Telegram ID пользователя для просмотра реф. статистики:\n\n"
            "Для отмены /cancel",
            parse_mode="HTML"
        )

    elif action == "adm_withdrawals":
        rows = db_get_pending_withdrawals()
        if not rows:
            await call.message.edit_text(
                "💸 Заявок на вывод нет.", reply_markup=kb_back_admin()
            )
        else:
            for wid, uid, name, uname, amount, req_at in rows:
                kb = InlineKeyboardMarkup(inline_keyboard=[[
                    InlineKeyboardButton(text="✅ Оплачено", callback_data=f"wdone_{wid}"),
                    InlineKeyboardButton(text="❌ Отклонить", callback_data=f"wdecline_{wid}"),
                ]])
                await bot.send_message(
                    ADMIN_ID,
                    f"💸 <b>Заявка #{wid}</b>\n"
                    f"👤 {name or '?'} (@{uname or '—'}) — ID <code>{uid}</code>\n"
                    f"⭐ Сумма: <b>{amount}</b> звёзд\n"
                    f"📅 {req_at}",
                    parse_mode="HTML",
                    reply_markup=kb
                )
            await call.message.edit_text(
                f"📋 Отправлено <b>{len(rows)}</b> заявок выше ↑",
                parse_mode="HTML",
                reply_markup=kb_back_admin()
            )

    elif action == "adm_users":
        con = sqlite3.connect(DB)
        rows = con.execute(
            "SELECT first_name, username, joined_at FROM users ORDER BY rowid DESC LIMIT 20"
        ).fetchall()
        con.close()
        if not rows:
            text = "👥 Пользователей нет."
        else:
            lines = [f"👥 <b>Последние {len(rows)} пользователей:</b>\n"]
            for name, uname, joined in rows:
                lines.append(f"• {name or '?'} @{uname or '—'} — {joined}")
            text = "\n".join(lines)
        await call.message.edit_text(text, parse_mode="HTML", reply_markup=kb_back_admin())

    elif action == "adm_broadcast":
        await state.set_state(BroadcastState.waiting_text)
        await call.message.edit_text(
            "📢 <b>Рассылка</b>\n\nОтправь текст (HTML поддерживается).\nДля отмены /cancel",
            parse_mode="HTML"
        )

    elif action == "adm_back":
        await state.clear()
        await call.message.edit_text(
            "🛡 <b>Админ-панель TENDO</b>\n\nВыберите действие:",
            parse_mode="HTML",
            reply_markup=kb_admin()
        )

    elif action == "adm_close":
        await call.message.delete()

    await call.answer()

# ═══════════════════════════════════════════════════════
# ВЫПЛАТЫ
# ═══════════════════════════════════════════════════════

@dp.callback_query(lambda c: c.data and (c.data.startswith("wdone_") or c.data.startswith("wdecline_")))
async def handle_withdrawal(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        return
    parts = call.data.split("_")
    action = parts[0]
    wid = int(parts[1])

    con = sqlite3.connect(DB)
    row = con.execute(
        "SELECT user_id, amount FROM withdrawals WHERE id=?", (wid,)
    ).fetchone()
    con.close()

    if not row:
        await call.answer("Заявка не найдена")
        return

    uid, amount = row

    if action == "wdone":
        db_set_withdrawal_status(wid, "done")
        await bot.send_message(
            uid,
            f"✅ <b>Выплата {amount}⭐ одобрена!</b>\n\n"
            f"Средства будут переведены в ближайшее время.",
            parse_mode="HTML"
        )
        await call.message.edit_text(f"✅ Заявка #{wid} — оплачено ({amount}⭐)")
    else:
        db_set_withdrawal_status(wid, "declined")
        await bot.send_message(
            uid,
            f"❌ <b>Заявка на вывод {amount}⭐ отклонена.</b>\n\n"
            f"Свяжитесь с администратором для уточнения.",
            parse_mode="HTML"
        )
        await call.message.edit_text(f"❌ Заявка #{wid} — отклонена")
    await call.answer()

# ═══════════════════════════════════════════════════════
# ПОИСК РЕФЕРАЛА ПО ID
# ═══════════════════════════════════════════════════════

@dp.message(AdminState.ref_lookup)
async def ref_lookup_handler(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    if message.text == "/cancel":
        await state.clear()
        await message.answer("Отменено.", reply_markup=kb_admin())
        return
    try:
        uid = int(message.text.strip())
    except ValueError:
        await message.answer("⚠️ Введите числовой ID")
        return

    await state.clear()
    d = db_get_ref_detail(uid)
    if not d["user"]:
        await message.answer("❌ Пользователь не найден в БД.", reply_markup=kb_admin())
        return

    name, uname = d["user"]
    lines = [
        f"🔍 <b>Реф. статистика: {name or '?'} (@{uname or '—'})</b>\n"
        f"ID: <code>{uid}</code>\n\n"
        f"👥 Приглашено: <b>{d['invited']}</b>\n"
        f"💳 Покупок от рефералов: <b>{len(d['earnings'])}</b>\n"
        f"⭐ Всего заработано: <b>{d['total']}</b>\n"
        f"✅ Выплачено: <b>{d['paid']}</b>\n"
        f"⏳ На рассмотрении: <b>{d['pending']}</b>\n"
        f"💰 Остаток: <b>{d['balance']}</b>\n"
    ]
    if d["earnings"]:
        lines.append("\n📜 <b>Покупки рефералов:</b>")
        for rname, runame, stars, earned, at in d["earnings"]:
            lines.append(f"  • {rname or '?'} — {stars}⭐ → +{earned}⭐ ({at[:10]})")

    await message.answer("\n".join(lines), parse_mode="HTML", reply_markup=kb_admin())

# ═══════════════════════════════════════════════════════
# РАССЫЛКА
# ═══════════════════════════════════════════════════════

@dp.message(BroadcastState.waiting_text)
async def broadcast_send(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    if message.text == "/cancel":
        await state.clear()
        await message.answer("❌ Рассылка отменена.", reply_markup=kb_admin())
        return

    await state.clear()
    users = db_get_all_users()
    ok, fail = 0, 0
    status = await message.answer(f"⏳ Рассылка... 0/{len(users)}")

    for uid in users:
        try:
            await bot.send_message(uid, message.text, parse_mode="HTML")
            ok += 1
        except Exception:
            fail += 1
        if (ok + fail) % 10 == 0:
            try:
                await status.edit_text(f"⏳ Рассылка... {ok+fail}/{len(users)}")
            except Exception:
                pass
        await asyncio.sleep(0.05)

    await status.edit_text(
        f"✅ <b>Рассылка завершена</b>\n📨 Отправлено: {ok}\n❌ Ошибок: {fail}",
        parse_mode="HTML",
        reply_markup=kb_back_admin()
    )

# ═══════════════════════════════════════════════════════
# ОПЛАТА ЗВЁЗДАМИ
# ═══════════════════════════════════════════════════════

@dp.callback_query(F.data == "menu_stars")
async def menu_stars(call: CallbackQuery):
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="50 ГБ — 600 ⭐", callback_data="stars_full"))
    kb.row(InlineKeyboardButton(text="15 ГБ — 400 ⭐", callback_data="stars_medium"))
    kb.row(InlineKeyboardButton(text="5 ГБ  — 350 ⭐", callback_data="stars_small"))
    kb.row(InlineKeyboardButton(text="💫 Где купить звёзды?", url=STARS_BUY))
    kb.row(InlineKeyboardButton(text="◀️ Назад", callback_data="back_start"))
    await call.message.edit_text(
        "⭐ <b>Оплата звёздами</b>\n\nПосле оплаты вы автоматически получите доступ.\nВыберите объём:",
        parse_mode="HTML",
        reply_markup=kb.as_markup()
    )

@dp.callback_query(F.data == "menu_crypto")
async def menu_crypto(call: CallbackQuery):
    kb = InlineKeyboardBuilder()
    if PLANS["full"]["crypto"]:
        kb.row(InlineKeyboardButton(text="50 ГБ — Оплатить", url=PLANS["full"]["crypto"]))
    if PLANS["medium"]["crypto"]:
        kb.row(InlineKeyboardButton(text="15 ГБ — Оплатить", url=PLANS["medium"]["crypto"]))
    if PLANS["small"]["crypto"]:
        kb.row(InlineKeyboardButton(text="5 ГБ — Оплатить", url=PLANS["small"]["crypto"]))
    kb.row(InlineKeyboardButton(text="◀️ Назад", callback_data="back_start"))
    await call.message.edit_text(
        "🌐 <b>Оплата криптой</b>\n\nПосле оплаты вы автоматически получите доступ.\nВыберите объём:",
        parse_mode="HTML",
        reply_markup=kb.as_markup()
    )

@dp.callback_query(lambda c: c.data and c.data.startswith("stars_"))
async def send_invoice(call: CallbackQuery):
    key = call.data.replace("stars_", "")
    plan = PLANS.get(key)
    if not plan:
        return
    await bot.send_invoice(
        chat_id=call.message.chat.id,
        title=f"TENDO — {plan['label']}",
        description=f"Доступ к контенту {plan['label']}. Автовыдача сразу после оплаты ✅",
        payload=f"tendo_{key}",
        provider_token="",
        currency="XTR",
        prices=[LabeledPrice(label="XTR", amount=plan["stars"])],
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text=f"⭐ Заплатить {plan['stars']} звёзд", pay=True)
        ]])
    )
    await call.answer()

@dp.pre_checkout_query()
async def pre_checkout(query: types.PreCheckoutQuery):
    await query.answer(ok=True)

@dp.message(lambda m: m.successful_payment is not None)
async def successful_payment(message: Message):
    key = message.successful_payment.invoice_payload.replace("tendo_", "")
    stars = message.successful_payment.total_amount
    ref_id = db_add_purchase(message.from_user.id, key, stars)

    if ref_id:
        earned = int(stars * REF_PERCENT / 100)
        buyer_name = message.from_user.first_name
        try:
            await bot.send_message(
                ref_id,
                f"🎉 <b>Ваш реферал совершил покупку!</b>\n\n"
                f"👤 {buyer_name}\n"
                f"📦 {PLAN_NAMES.get(key, key)} — {stars}⭐\n"
                f"💰 Вам начислено: <b>+{earned}⭐</b>\n\n"
                f"Проверь баланс в разделе «Реферальная программа» 🤝",
                parse_mode="HTML"
            )
        except Exception:
            pass

    uname = f"@{message.from_user.username}" if message.from_user.username else message.from_user.first_name
    try:
        await bot.send_message(
            ADMIN_ID,
            f"💰 <b>Новая покупка!</b>\n\n"
            f"👤 {uname} (ID: <code>{message.from_user.id}</code>)\n"
            f"📦 {PLAN_NAMES.get(key, key)} — {stars}⭐\n"
            f"{'🤝 Реферал от ID: ' + str(ref_id) if ref_id else '🔗 Без реферала'}\n"
            f"🕐 {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            parse_mode="HTML"
        )
    except Exception:
        pass

    await message.answer(
        "✅ <b>Оплата прошла успешно!</b>\n\nНажми кнопку ниже 👇",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="📁 Получить контент", url=CHANNEL_LINK)
        ]])
    )

@dp.callback_query(F.data == "back_start")
async def back_start(call: CallbackQuery):
    await call.message.edit_text(
        "🌿 <b>TENDO</b>\n\n"
        "✅ Автовыдача сразу после оплаты\n"
        "🔒 Безопасная оплата через Telegram Stars\n\n"
        "Выберите способ оплаты:",
        parse_mode="HTML",
        reply_markup=kb_main()
    )

# ═══════════════════════════════════════════════════════
# ЗАПУСК
# ═══════════════════════════════════════════════════════

async def main():
    print("✅ Бот TENDO запущен")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())