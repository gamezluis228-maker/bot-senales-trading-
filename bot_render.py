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

# Iniciar servidor web para abrir el puerto de Render inmediatamente
web_thread = threading.Thread(target=run_web_server)
web_thread.daemon = True
web_thread.start()

# Token directo blindado
TOKEN = "8962151587:AAEtHJvaDuEdThn20jTU6pCtZjjZtS1"

application = Application.builder().token(TOKEN).build()

async def start(update: Update, context):
    welcome_text = (
        "🤖 **¡Bot de Señales de Trading KuCoin Activo!**\n\n"
        "Comandos:\n"
        "• `/btc` - Análisis técnico y señal de Bitcoin\n"
        "• `/eth` - Análisis técnico y señal de Ethereum\n"
        "• `/sol` - Análisis técnico y señal de Solana\n"
        "• `/riesgo <CAPITAL>` - Gestión de riesgo\n"
    )
    await update.message.reply_text(welcome_text, parse_mode="Markdown")

async def analyze_cmd(update: Update, context):
    query = "".join(context.args).upper() if context.args else update.message.text.replace("/", "").upper()
    symbol = f"{query}/USDT" if query in ["BTC", "ETH", "SOL"] else "BTC/USDT"
    await update.message.reply_text(f"🔍 Analizando mercado en KuCoin para {symbol}...")
    resultado = analyze_market(symbol)
    await update.message.reply_text(resultado, parse_mode="Markdown")

async def risk_cmd(update: Update, context):
    if not context.args:
        await update.message.reply_text("⚠️ Uso correcto: `/riesgo 1000`", parse_mode="Markdown")
        return
    capital = context.args[0]
    resultado = calculate_risk(capital, 2)
    await update.message.reply_text(resultado, parse_mode="Markdown")

if __name__ == "__main__":
    print("🚀 Iniciando bot...")
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler(["btc", "eth", "sol", "analisis"], analyze_cmd))
    application.add_handler(CommandHandler("riesgo", risk_cmd))
    application.run_polling()
