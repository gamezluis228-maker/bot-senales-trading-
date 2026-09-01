import os
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler
from analisis import analyze_market, calculate_risk

# Servidor web para mantener vivo el bot en Render 24/7
class SimpleHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is active and running 24/7!")

def run_web_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), SimpleHandler)
    server.serve_forever()

threading.Thread(target=run_web_server, daemon=True).start()

# Token de tu bot
TOKEN = "8962151587:AAFZkPd73TnVDS_PZVfejFPGb1U_pbdPr1E"
application = Application.builder().token(TOKEN).build()

# Comando /start o /operar con botones interactivos
async def start(update: Update, context):
    keyboard = [
        [
            InlineKeyboardButton("₿ BTC/USDT", callback_data="BTC"),
            InlineKeyboardButton("Ξ ETH/USDT", callback_data="ETH")
        ],
        [
            InlineKeyboardButton("☀️ SOL/USDT", callback_data="SOL"),
            InlineKeyboardButton("✕ XRP/USDT", callback_data="XRP")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    texto = (
        "🤖 **¡Panel de Control de Futuros KuCoin!**\n\n"
        "Selecciona la criptomoneda que deseas operar o analizar a continuación:"
    )
    
    if update.message:
        await update.message.reply_text(texto, reply_markup=reply_markup, parse_mode="Markdown")
    elif update.callback_query:
        await update.callback_query.message.reply_text(texto, reply_markup=reply_markup, parse_mode="Markdown")

# Manejador cuando presionan los botones de los recuadros
async def button_handler(update: Update, context):
    query = update.callback_query
    await query.answer()
    
    symbol = query.data # "BTC", "ETH", "SOL" o "XRP"
    pair = f"{symbol}/USDT"
    
    await query.message.reply_text(f"🔍 Analizando doble temporalidad (1H y 15m) para {pair}...")
    resultado = analyze_market(pair)
    await query.message.reply_text(resultado, parse_mode="Markdown")

# Comandos directos por texto (/btc, /eth, /sol, /xrp)
async def analyze_cmd(update: Update, context):
    q = "".join(context.args).upper() if context.args else update.message.text.replace("/", "").upper()
    sym = f"{q}/USDT" if q in ["BTC", "ETH", "SOL", "XRP"] else "BTC/USDT"
    await update.message.reply_text(f"🔍 Analizando futuros para {sym}...")
    await update.message.reply_text(analyze_market(sym), parse_mode="Markdown")

async def risk_cmd(update: Update, context):
    cap = context.args[0] if context.args else "1000"
    await update.message.reply_text(calculate_risk(cap, 1), parse_mode="Markdown")

if __name__ == "__main__":
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("operar", start))
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(CommandHandler(["btc", "eth", "sol", "xrp", "analisis"], analyze_cmd))
    application.add_handler(CommandHandler("riesgo", risk_cmd))
    
    print("🤖 Bot iniciado y operando 24/7...")
    application.run_polling()
