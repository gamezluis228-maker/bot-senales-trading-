import os
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import Update
from telegram.ext import Application, CommandHandler, CallbackQueryHandler
from analisis import analyze_market, calculate_risk

# --- SERVIDOR WEB PARA RENDER ---
class SimpleHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is active and running!")

def run_web_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), SimpleHandler)
    server.serve_forever()

# --- CONFIGURACIÓN DEL BOT ---
TOKEN = "8962151587:AAEtHJvaDuEdThn20jTU6pCtZjjZtS1"

application = Application.builder().token(TOKEN).build()

# --- COMANDOS Y FUNCIONES ---
async def start(update: Update, context):
    welcome_text = (
        "🤖 **¡Bot de Señales de Trading Activo!**\n\n"
        "Comandos disponibles:\n"
        "• `/btc` - Análisis técnico de Bitcoin\n"
        "• `/eth` - Análisis técnico de Ethereum\n"
        "• `/sol` - Análisis técnico de Solana\n"
        "• `/analisis <MONEDA>` - Análisis personalizado\n"
        "• `/riesgo <CAPITAL>` - Calculadora de riesgo\n"
    )
    await update.message.reply_text(welcome_text, parse_mode="Markdown")

async def analyze_cmd(update: Update, context):
    query = "".join(context.args).upper() if context.args else update.message.text.replace("/", "").upper()
    if query in ["BTC", "ETH", "SOL"]:
        symbol = f"{query}/USDT"
    else:
        symbol = "BTC/USDT"
    
    await update.message.reply_text(f"🔍 Analizando {symbol}...")
    resultado = analyze_market(symbol)
    await update.message.reply_text(resultado, parse_mode="Markdown")

async def risk_cmd(update: Update, context):
    if not context.args:
        await update.message.reply_text("⚠️ Uso correcto: `/riesgo 1000` (indica tu capital)", parse_mode="Markdown")
        return
    capital = context.args[0]
    resultado = calculate_risk(capital, 2)
    await update.message.reply_text(resultado, parse_mode="Markdown")

async def button_handler(update: Update, context):
    query = update.callback_query
    await query.answer()

# --- EJECUCIÓN PRINCIPAL ---
if __name__ == "__main__":
    # 1. Arrancar servidor web en segundo plano para Render
    web_thread = threading.Thread(target=run_web_server)
    web_thread.daemon = True
    web_thread.start()
    
    print("🚀 Bot iniciado correctamente con token directo...")
    
    # 2. Registrar manejadores
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler(["btc", "eth", "sol", "analisis"], analyze_cmd))
    application.add_handler(CommandHandler("riesgo", risk_cmd))
    application.add_handler(CallbackQueryHandler(button_handler))
    
    # 3. Arrancar bot
    application.run_polling()
