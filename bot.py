# bot.py
# Python 3.12 + python-telegram-bot 21.6
# gspread + google-auth
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List, Optional
from datetime import datetime

import gspread
from google.oauth2.service_account import Credentials

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

# =========================
# НАСТРОЙКИ (ВСТАВЬ СВОИ)
# =========================
BOT_TOKEN = "8559573847:AAFEpjXHi94q9vS8UvQ1OfV2MHJCkwW2T1g"
SPREADSHEET_ID = "19vQeKbB3jnbAFYwram8RLbeWYacI5O1rmgurjtqJ0fY"
SHEET_NAME = "Ответы на форму (1)"
GOOGLE_CREDS_FILE = "service_account.json"

# =========================
# КОЛОНКИ (0-based индексы)
# =========================
# B врач, C вид работы, D кол-во ед, F техник, I номер работы, P статус
COL_DOCTOR = 1    # B
COL_WORKTYPE = 2  # C
COL_UNITS = 3     # D
COL_TECH = 5      # F
COL_WORKNO = 8    # I
COL_STATUS = 15   # P

# Балка/основания
# J тип балки, K количество балок
COL_BEAM_TYPE = 9   # J
COL_BEAM_QTY = 10   # K

# Основания: если у тебя количество оснований в L — поставь 11
# Если в другой колонке — поменяй индекс
COL_BASE_QTY = 11   # L  <-- ПРОВЕРЬ

# Дата обновления статуса: W = индекс 22 (0-based)
COL_UPDATED = 22    # W

# =========================
# Статусы
# =========================
STATUS_NEW = "Не начата"
STATUS_IN_WORK = "В работе"
STATUS_DONE = "Завершена"

# =========================
# ЛОГИ
# =========================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
log = logging.getLogger("lab_bot")


@dataclass
class WorkItem:
    row: int               # строка в Google Sheets (1-based)
    work_no: str
    doctor: str
    work_type: str
    units: str
    tech: str
    status: str
    beam_type: str
    beam_qty: str
    base_qty: str
    updated: str


def now_str() -> str:
    # можешь поменять формат, если хочешь
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def norm(s: str) -> str:
    return (s or "").strip()


def safe_cell(row: List[str], idx: Optional[int]) -> str:
    if idx is None:
        return ""
    return row[idx] if idx < len(row) else ""


def get_user_tech_name(update: Update) -> str:
    u = update.effective_user
    if not u:
        return "Unknown"
    if u.username:
        return u.username  # без @
    full = f"{u.first_name or ''} {u.last_name or ''}".strip()
    return full if full else str(u.id)


def open_sheet() -> gspread.Worksheet:
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_file(GOOGLE_CREDS_FILE, scopes=scopes)
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(SPREADSHEET_ID)
    return sh.worksheet(SHEET_NAME)


def normalize_status(raw: str) -> str:
    """
    Делает статус устойчивым:
    - пусто/непонятно -> Не начата (чтобы бот видел свободные)
    - "в работе" -> В работе
    - "завершена" -> Завершена
    """
    s = norm(raw).lower()
    if not s:
        return STATUS_NEW
    if "зав" in s:
        return STATUS_DONE
    if "работ" in s:
        return STATUS_IN_WORK
    if "не" in s and "нач" in s:
        return STATUS_NEW
    return STATUS_NEW


def read_all_items(ws: gspread.Worksheet) -> List[WorkItem]:
    values = ws.get_all_values()
    if not values or len(values) < 2:
        return []

    items: List[WorkItem] = []
    for i, row in enumerate(values[1:], start=2):
        doctor = norm(safe_cell(row, COL_DOCTOR))
        work_type = norm(safe_cell(row, COL_WORKTYPE))
        units = norm(safe_cell(row, COL_UNITS))
        tech = norm(safe_cell(row, COL_TECH))
        work_no = norm(safe_cell(row, COL_WORKNO))

        status_raw = safe_cell(row, COL_STATUS)
        status = normalize_status(status_raw)

        beam_type = norm(safe_cell(row, COL_BEAM_TYPE))
        beam_qty = norm(safe_cell(row, COL_BEAM_QTY))
        base_qty = norm(safe_cell(row, COL_BASE_QTY))
        updated = norm(safe_cell(row, COL_UPDATED))

        # пропускаем полностью пустые строки
        if not any([doctor, work_type, units, tech, work_no, status_raw, beam_type, beam_qty, base_qty, updated]):
            continue

        items.append(
            WorkItem(
                row=i,
                work_no=work_no,
                doctor=doctor,
                work_type=work_type,
                units=units,
                tech=tech,
                status=status,
                beam_type=beam_type,
                beam_qty=beam_qty,
                base_qty=base_qty,
                updated=updated,
            )
        )
    return items


def is_available(item: WorkItem) -> bool:
    # СВОБОДНАЯ = только по статусу, техника игнорим
    return normalize_status(item.status) == STATUS_NEW


def is_in_work(item: WorkItem) -> bool:
    return normalize_status(item.status) == STATUS_IN_WORK


def is_done(item: WorkItem) -> bool:
    return normalize_status(item.status) == STATUS_DONE


def make_main_menu() -> InlineKeyboardMarkup:
    kb = [
        [
            InlineKeyboardButton("📌 Свободные", callback_data="menu:available"),
            InlineKeyboardButton("🧰 Мои", callback_data="menu:my"),
        ],
        [InlineKeyboardButton("🔄 Обновить", callback_data="menu:refresh")],
    ]
    return InlineKeyboardMarkup(kb)


def make_item_text(item: WorkItem) -> str:
    # Балка
    if item.beam_type and item.beam_qty:
        beam_info = f"{item.beam_type} × {item.beam_qty}"
    elif item.beam_type:
        beam_info = item.beam_type
    else:
        beam_info = "—"

    # Основания
    base_info = item.base_qty if item.base_qty else "—"

    upd = item.updated or "—"

    return (
        f"🧾 *Работа №*: `{item.work_no or '—'}`\n"
        f"👨‍⚕️ *Врач*: {item.doctor or '—'}\n"
        f"🦷 *Вид*: {item.work_type or '—'}\n"
        f"🔢 *Кол-во ед*: {item.units or '—'}\n"
        f"🧱 *Балка*: {beam_info}\n"
        f"⚙️ *Основания*: {base_info}\n"
        f"👤 *Техник (F)*: {item.tech or '—'}\n"
        f"📍 *Статус*: *{item.status}*\n"
        f"🕒 *Обновлено*: {upd}\n"
    )


def make_item_kb(item: WorkItem, viewer_tech: str) -> InlineKeyboardMarkup:
    buttons: List[List[InlineKeyboardButton]] = []

    if is_available(item):
        buttons.append([InlineKeyboardButton("✅ Взять", callback_data=f"take:{item.row}")])

    if is_in_work(item) and norm(item.tech).lower() == norm(viewer_tech).lower():
        buttons.append([InlineKeyboardButton("♻️ Передать в свободные", callback_data=f"release:{item.row}")])
        buttons.append([InlineKeyboardButton("🏁 Завершить", callback_data=f"finish:{item.row}")])

    buttons.append([InlineKeyboardButton("⬅️ Меню", callback_data="menu:home")])
    return InlineKeyboardMarkup(buttons)


def update_status_and_tech(
    ws: gspread.Worksheet,
    row_num: int,
    *,
    status: Optional[str] = None,
    tech_name: Optional[str] = None,
) -> None:
    """
    Запись в Google Sheets (update_cell использует 1-based):
    - F = техник (6)
    - P = статус (16)
    - W = обновлено (23)
    """
    if tech_name is not None:
        ws.update_cell(row_num, 6, tech_name)  # F

    if status is not None:
        ws.update_cell(row_num, 16, status)          # P
        ws.update_cell(row_num, 23, now_str())       # W (обновлено)


# =========================
# COMMANDS
# =========================
async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    tech = get_user_tech_name(update)
    text = (
        f"Привет! Ты определён как техник: *{tech}*\n\n"
        "Кнопки:\n"
        "• 📌 Свободные — показать свободные\n"
        "• 🧰 Мои — показать твои (в работе)\n"
        "• 🔄 Обновить — перечитать таблицу\n"
    )
    await update.message.reply_text(text, reply_markup=make_main_menu(), parse_mode="Markdown")


async def available_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    ws = open_sheet()
    items = read_all_items(ws)
    tech = get_user_tech_name(update)

    available = [it for it in items if is_available(it)]
    if not available:
        await update.effective_message.reply_text("Свободных работ нет.", reply_markup=make_main_menu())
        return

    for it in available[:10]:
        await update.effective_message.reply_text(
            make_item_text(it),
            reply_markup=make_item_kb(it, tech),
            parse_mode="Markdown",
        )


async def my_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    ws = open_sheet()
    items = read_all_items(ws)
    tech = get_user_tech_name(update)

    mine = [it for it in items if is_in_work(it) and norm(it.tech).lower() == norm(tech).lower()]
    if not mine:
        await update.effective_message.reply_text(
            "У тебя пока нет работ *в работе*.",
            reply_markup=make_main_menu(),
            parse_mode="Markdown",
        )
        return

    for it in mine[:10]:
        await update.effective_message.reply_text(
            make_item_text(it),
            reply_markup=make_item_kb(it, tech),
            parse_mode="Markdown",
        )


async def on_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    data = query.data or ""
    if data == "menu:home":
        await query.edit_message_text("Меню:", reply_markup=make_main_menu())
        return

    if data == "menu:available":
        await query.message.reply_text("Свободные работы:", reply_markup=make_main_menu())
        await available_cmd(update, context)
        return

    if data == "menu:my":
        await query.message.reply_text("Мои работы:", reply_markup=make_main_menu())
        await my_cmd(update, context)
        return

    if data == "menu:refresh":
        await query.message.reply_text("Обновил список.", reply_markup=make_main_menu())
        return


async def on_take(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    tech = get_user_tech_name(update)
    try:
        _, row_s = (query.data or "").split(":", 1)
        row_num = int(row_s)
    except Exception:
        await query.message.reply_text("Ошибка данных кнопки.", reply_markup=make_main_menu())
        return

    ws = open_sheet()
    row = ws.row_values(row_num)
    current_status = normalize_status(safe_cell(row, COL_STATUS))

    if current_status == STATUS_DONE:
        await query.message.reply_text("Эта работа уже завершена.", reply_markup=make_main_menu())
        return
    if current_status == STATUS_IN_WORK:
        await query.message.reply_text("Эта работа уже *в работе*.", reply_markup=make_main_menu(), parse_mode="Markdown")
        return

    update_status_and_tech(ws, row_num, status=STATUS_IN_WORK, tech_name=tech)
    await query.message.reply_text(f"✅ Взято в работу: *{tech}*", reply_markup=make_main_menu(), parse_mode="Markdown")


async def on_release(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Передать в свободные:
    - статус => Не начата
    - техника НЕ чистим (оставляем, т.к. из формы и/или последний кто брал)
      (ты именно так и хотел)
    """
    query = update.callback_query
    await query.answer()

    tech = get_user_tech_name(update)
    try:
        _, row_s = (query.data or "").split(":", 1)
        row_num = int(row_s)
    except Exception:
        await query.message.reply_text("Ошибка данных кнопки.", reply_markup=make_main_menu())
        return

    ws = open_sheet()
    row = ws.row_values(row_num)
    current_tech = norm(safe_cell(row, COL_TECH))
    current_status = normalize_status(safe_cell(row, COL_STATUS))

    if current_status != STATUS_IN_WORK:
        await query.message.reply_text("Передать можно только если статус *В работе*.", reply_markup=make_main_menu(), parse_mode="Markdown")
        return

    if norm(current_tech).lower() != norm(tech).lower():
        await query.message.reply_text(
            f"❌ Передать может только текущий техник: *{current_tech or '—'}*",
            reply_markup=make_main_menu(),
            parse_mode="Markdown",
        )
        return

    # статус меняем, технику НЕ трогаем
    update_status_and_tech(ws, row_num, status=STATUS_NEW, tech_name=None)
    await query.message.reply_text("♻️ Работа снова в *Свободных*.", reply_markup=make_main_menu(), parse_mode="Markdown")


async def on_finish(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    tech = get_user_tech_name(update)
    try:
        _, row_s = (query.data or "").split(":", 1)
        row_num = int(row_s)
    except Exception:
        await query.message.reply_text("Ошибка данных кнопки.", reply_markup=make_main_menu())
        return

    ws = open_sheet()
    row = ws.row_values(row_num)

    current_tech = norm(safe_cell(row, COL_TECH))
    current_status = normalize_status(safe_cell(row, COL_STATUS))

    if current_status != STATUS_IN_WORK:
        await query.message.reply_text("Эта работа не в статусе *В работе*.", reply_markup=make_main_menu(), parse_mode="Markdown")
        return

    if norm(current_tech).lower() != norm(tech).lower():
        await query.message.reply_text(
            f"❌ Завершить может только текущий техник: *{current_tech or '—'}*",
            reply_markup=make_main_menu(),
            parse_mode="Markdown",
        )
        return

    update_status_and_tech(ws, row_num, status=STATUS_DONE, tech_name=current_tech)
    await query.message.reply_text("🏁 Работа отмечена как *Завершена*.", reply_markup=make_main_menu(), parse_mode="Markdown")


def main() -> None:
    if not BOT_TOKEN or "ВСТАВЬ" in BOT_TOKEN:
        raise RuntimeError("Заполни BOT_TOKEN в коде.")
    if not SPREADSHEET_ID or "ВСТАВЬ" in SPREADSHEET_ID:
        raise RuntimeError("Заполни SPREADSHEET_ID в коде.")
    if not SHEET_NAME:
        raise RuntimeError("Заполни SHEET_NAME в коде.")
    if not GOOGLE_CREDS_FILE:
        raise RuntimeError("Заполни GOOGLE_CREDS_FILE в коде.")

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("available", available_cmd))
    app.add_handler(CommandHandler("my", my_cmd))

    app.add_handler(CallbackQueryHandler(on_menu, pattern=r"^menu:"))
    app.add_handler(CallbackQueryHandler(on_take, pattern=r"^take:"))
    app.add_handler(CallbackQueryHandler(on_release, pattern=r"^release:"))
    app.add_handler(CallbackQueryHandler(on_finish, pattern=r"^finish:"))

    log.info("Bot started...")
    app.run_polling(close_loop=False)


if __name__ == "__main__":
    main()
