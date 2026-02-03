# bot.py
# Python 3.12 | python-telegram-bot 21.x
# Render-ready | Google Sheets via GOOGLE_CREDS_JSON

from __future__ import annotations

import os
import json
import logging
from datetime import datetime
from typing import List, Dict

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
# ENV
# =========================
BOT_TOKEN = "8559573847:AAFEpjXHi94q9vS8UvQ1OfV2MHJCkwW2T1g"
SPREADSHEET_ID = "19vQeKbB3jnbAFYwram8RLbeWYacI5O1rmgurjtqJ0fY"
SHEET_NAME = "Ответы на форму (1)"
GOOGLE_CREDS_FILE = "service_account.json"

# =========================
# КОЛОНКИ (0-based)
# =========================
COL_DOCTOR = 1        # B
COL_WORKTYPE = 2      # C
COL_UNITS = 3         # D
COL_TECH = 5          # F
COL_BEAM_TYPE = 9     # J
COL_BEAM_QTY = 10     # K
COL_BASE_QTY = 11     # L
COL_STATUS = 23       # X
COL_UPDATED = 26      # AA

STATUS_FREE = "Свободна"
STATUS_WORK = "В работе"
STATUS_DONE = "Завершена"

# =========================
# LOGS
# =========================
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("lab_bot")

# =========================
# GOOGLE
# =========================
def open_sheet():
    if not GOOGLE_CREDS_JSON:
        raise RuntimeError("GOOGLE_CREDS_JSON not set")

    data = json.loads(GOOGLE_CREDS_JSON)

    if "\\n" in data.get("private_key", ""):
        data["private_key"] = data["private_key"].replace("\\n", "\n")

    creds = Credentials.from_service_account_info(
        data,
        scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(SPREADSHEET_ID)
    return sh.worksheet(SHEET_NAME)

# =========================
# UTILS
# =========================
def now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def norm(v):
    return (v or "").strip()

def get_tech(update: Update) -> str:
    u = update.effective_user
    if u.username:
        return u.username
    return f"{u.first_name or ''} {u.last_name or ''}".strip()

def safe(row, idx):
    return row[idx] if idx < len(row) else ""

# =========================
# READ DATA
# =========================
def read_items(ws) -> List[Dict]:
    rows = ws.get_all_values()
    items = []

    for i, r in enumerate(rows[1:], start=2):
        status = norm(safe(r, COL_STATUS)) or STATUS_FREE

        items.append({
            "row": i,
            "doctor": norm(safe(r, COL_DOCTOR)),
            "work_type": norm(safe(r, COL_WORKTYPE)),
            "units": norm(safe(r, COL_UNITS)),
            "tech": norm(safe(r, COL_TECH)),
            "beam_type": norm(safe(r, COL_BEAM_TYPE)),
            "beam_qty": int(norm(safe(r, COL_BEAM_QTY)) or 0),
            "base_qty": int(norm(safe(r, COL_BASE_QTY)) or 0),
            "status": status,
        })

    return items

# =========================
# UPDATE STATUS
# =========================
def update_status(ws, row: int, status: str, tech: str | None):
    if tech is not None:
        ws.update_cell(row, 6, tech)       # F
    ws.update_cell(row, 24, status)        # X
    ws.update_cell(row, 27, now_str())     # AA

# =========================
# FORMAT
# =========================
def format_item(it):
    text = (
        f"🧾 Работа (строка {it['row']})\n"
        f"👨‍⚕️ Врач: {it['doctor']}\n"
        f"🦷 Вид: {it['work_type']}\n"
        f"🔢 Ед: {it['units']}\n"
    )

    if it["beam_type"] and it["beam_qty"] > 0:
        text += f"🧱 Балка: {it['beam_type']} × {it['beam_qty']}\n"

    if it["base_qty"] > 0:
        text += f"⚙️ Основания: {it['base_qty']}\n"

    text += f"\n📍 Статус: *{it['status']}*"
    return text

def item_kb(it, me):
    kb = []

    if it["status"] == STATUS_FREE:
        kb.append([InlineKeyboardButton("✅ Взять", callback_data=f"take:{it['row']}")])

    if it["status"] == STATUS_WORK and it["tech"] == me:
        kb.append([
            InlineKeyboardButton("♻️ Передать", callback_data=f"release:{it['row']}"),
            InlineKeyboardButton("🏁 Завершить", callback_data=f"finish:{it['row']}"),
        ])

    kb.append([InlineKeyboardButton("⬅️ Меню", callback_data="menu")])
    return InlineKeyboardMarkup(kb)

def main_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📌 Свободные", callback_data="free"),
         InlineKeyboardButton("🧰 Мои", callback_data="mine")],
        [InlineKeyboardButton("🧱 С балками", callback_data="beam"),
         InlineKeyboardButton("⚙️ С основаниями", callback_data="base")],
    ])

# =========================
# HANDLERS
# =========================
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Меню:", reply_markup=main_menu())

async def show(update, ctx, mode):
    ws = open_sheet()
    items = read_items(ws)
    me = get_tech(update)

    if mode == "free":
        items = [i for i in items if i["status"] == STATUS_FREE]
    elif mode == "mine":
        items = [i for i in items if i["status"] == STATUS_WORK and i["tech"] == me]
    elif mode == "beam":
        items = [i for i in items if i["beam_qty"] > 0]
    elif mode == "base":
        items = [i for i in items if i["base_qty"] > 0]

    if not items:
        await update.effective_message.reply_text("Ничего нет.", reply_markup=main_menu())
        return

    for it in items[:10]:
        await update.effective_message.reply_text(
            format_item(it),
            reply_markup=item_kb(it, me),
            parse_mode="Markdown"
        )

async def on_menu(update: Update, ctx):
    q = update.callback_query
    await q.answer()

    if q.data == "menu":
        await q.message.reply_text("Меню:", reply_markup=main_menu())
    else:
        await show(update, ctx, q.data)

async def on_take(update: Update, ctx):
    q = update.callback_query
    await q.answer()
    row = int(q.data.split(":")[1])

    ws = open_sheet()
    update_status(ws, row, STATUS_WORK, get_tech(update))
    await q.message.reply_text("Взято в работу.", reply_markup=main_menu())

async def on_release(update: Update, ctx):
    q = update.callback_query
    await q.answer()
    row = int(q.data.split(":")[1])

    ws = open_sheet()
    update_status(ws, row, STATUS_FREE, "")
    await q.message.reply_text("Работа снова свободна.", reply_markup=main_menu())

async def on_finish(update: Update, ctx):
    q = update.callback_query
    await q.answer()
    row = int(q.data.split(":")[1])

    ws = open_sheet()
    update_status(ws, row, STATUS_DONE, get_tech(update))
    await q.message.reply_text("Работа завершена.", reply_markup=main_menu())

# =========================
# MAIN
# =========================
def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(on_menu, pattern="^(free|mine|beam|base|menu)$"))
    app.add_handler(CallbackQueryHandler(on_take, pattern="^take:"))
    app.add_handler(CallbackQueryHandler(on_release, pattern="^release:"))
    app.add_handler(CallbackQueryHandler(on_finish, pattern="^finish:"))

    log.info("Bot started")
    app.run_polling()

if __name__ == "__main__":
    main()
