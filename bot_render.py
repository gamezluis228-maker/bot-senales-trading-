import os
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from analisis import analyze_market, calculate_risk

# Leer token y limpiar saltos de linea
TOKEN = os.getenv("TELEGRAM_TOKEN", "").replace('\n', '').replace('\r', '').replace(' ', '').strip()

# Crear aplicacion del bot
application = Application.builder().token(TOKEN).build()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_text = (
        "🤖 **¡Bot de Señales de Trading Activo!**\n\n"
        "Comandos disponibles:\n"
        "• `/btc` - Análisis técnico de Bitcoin\n"
        "• `/eth` - Análisis técnico de Ethereum\n"
        "• `/sol` - Análisis técnico de Solana\n"
        "• `/analisis <MONEDA>` - Análisis personalizado\n"
        "• `/riesgo <CAPITAL>` - Calculadora de riesgo"
    )
    await update.message.reply_text(welcome_text, parse_mode='Markdown')

async def analyze_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.args:
        symbol = context.args[0].upper()
    else:
        cmd = update.message.text.replace("/", "").upper()
        symbol = cmd if cmd in ["BTC", "ETH", "SOL"] else None
    
    if not symbol:
        await update.message.reply_text("🔍 Uso: /analisis <MONEDA> o /btc /eth /sol")
        return
        
    await update.message.reply_text(f"🔍 Analizando {symbol}...")
    result = analyze_market(symbol)
    await update.message.reply_text(result, parse_mode='Markdown')

async def risk_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("⚠️ Indica el capital: /riesgo <CAPITAL>")
        return

    capital = context.args[0]
    result = calculate_risk(capital)
    await update.message.reply_text(result, parse_mode='Markdown')

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/plain')
        self.end_headers()
        self.wfile.write("Bot de Senales de Trading Activo - Running".encode('utf-8'))
    
    def log_message(self, format, *args):
        pass  # Silenciar logs del servidor HTTP

def run_web_server():
    port = int(os.environ.get('PORT', 10000))
    server = HTTPServer(('0.0.0.0', port), HealthHandler)
    server.serve_forever()

if __name__ == "__main__":
    if not TOKEN:
        print("❌ Error: No se encontro el token del bot")
    else:
        # Iniciar servidor web en un thread de fondo
        web_thread = threading.Thread(target=run_web_server)
        web_thread.daemon = True
        web_thread.start()
        
        # Iniciar bot en el thread principal (donde asyncio funciona)
        print("🚀 Bot iniciado correctamente...")
        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler(["btc", "eth", "sol", "analisis"], analyze_cmd))
        application.add_handler(CommandHandler("riesgo", risk_cmd))
        application.run_polling()
