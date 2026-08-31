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

# Iniciar servidor web en segundo plano para abrir el puerto de Render
threading.Thread(target=run_web_server, daemon=True).start()

# Token real y completo de tu bot de Telegram (@mibotxrp_bot)
TOKEN = '8962151587:AAFZkPd7TnVDS_PZVFejFPGb1U_pbdPr1E'

application = Application.builder().token(TOKEN).build()

async def start(update: Update, context):
    welcome_text = (
        "🤖 **¡Bot de Señales de Trading KuCoin Activo!**\n\n"
        "Comandos disponibles:\n"
        "• `/btc` - Análisis técnico y señal de Bitcoin\n"
        "• `/eth` - Análisis técnico y señal de Ethereum\n"
        "• `/sol` - Análisis técnico y señal de Solana\n"
        "• `/riesgo <CAPITAL>` - Calculadora de gestión de riesgo\n"
    )
    await update.message.reply_text(welcome_text, parse_mode="Markdown")

async def analyze_cmd(update: Update, context):
    q = "".join(context.args).upper() if context.args else update.message.text.replace("/", "").upper()
    sym = f"{q}/USDT" if q in ["BTC", "ETH", "SOL"] else "BTC/USDT"
    await update.message.reply_text(f"🔍 Analizando mercado en KuCoin para {sym}...")
    resultado = analyze_market(sym)
    await update.message.reply_text(resultado, parse_mode="Markdown")

async def risk_cmd(update: Update, context):
    if not context.args:
        await update.message.reply_text("⚠️ Uso correcto: `/riesgo 1000`", parse_mode="Markdown")
        return
    cap = context.args[0]
    resultado = calculate_risk(cap, 2)
    await update.message.reply_text(resultado, parse_mode="Markdown")

if __name__ == "__main__":
    print("🚀 Iniciando bot con análisis de KuCoin...")
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler(["btc", "eth", "sol", "analisis"], analyze_cmd))
    application.add_handler(CommandHandler("riesgo", risk_cmd))
    application.run_polling()
