import os
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import Update
from telegram.ext import Application, CommandHandler
from analisis import analyze_market, calculate_risk

class SimpleHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is active and running!")

def run_web_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), SimpleHandler)
    server.serve_forever()

threading.Thread(target=run_web_server, daemon=True).start()

# Token real y completo de tu bot
TOKEN = 8962151587:AAFZkPd73TnVDS_PZVfejFPGb1U_pbdPr1E


application = Application.builder().token(TOKEN).build()

async def start(update: Update, context):
    await update.message.reply_text("🤖 **¡Bot de Futuros KuCoin Activo!**\nUsa /btc, /eth o /sol", parse_mode="Markdown")

async def analyze_cmd(update: Update, context):
    q = "".join(context.args).upper() if context.args else update.message.text.replace("/", "").upper()
    sym = f"{q}/USDT" if q in ["BTC", "ETH", "SOL"] else "BTC/USDT"
    await update.message.reply_text(f"🔍 Analizando futuros para {sym}...")
    await update.message.reply_text(analyze_market(sym), parse_mode="Markdown")

async def risk_cmd(update: Update, context):
    cap = context.args[0] if context.args else "1000"
    await update.message.reply_text(calculate_risk(cap, 2), parse_mode="Markdown")

if __name__ == "__main__":
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler(["btc", "eth", "sol", "analisis"], analyze_cmd))
    application.add_handler(CommandHandler("riesgo", risk_cmd))
    application.run_polling()
