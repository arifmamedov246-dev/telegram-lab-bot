import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from telegram.ext import Application, CommandHandler

# =========================
# ENV
# =========================
BOT_TOKEN = os.getenv("BOT_TOKEN")
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")
SHEET_NAME = os.getenv("SHEET_NAME", "Ответы на форму")

PORT = int(os.getenv("PORT", 10000))  # Render сам подставит PORT

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN not set")

# =========================
# TELEGRAM
# =========================
async def start(update, context):
    await update.message.reply_text("Бот запущен ✅")

def run_bot():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.run_polling()

# =========================
# HTTP SERVER (для Render)
# =========================
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

def run_http():
    server = HTTPServer(("0.0.0.0", PORT), HealthHandler)
    server.serve_forever()

# =========================
# START BOTH
# =========================
if __name__ == "__main__":
    threading.Thread(target=run_http, daemon=True).start()
    run_bot()
