import os
import time
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler
from analisis import analyze_market, calculate_risk

# Conjunto para almacenar los chats que recibirán las alertas automáticas
ACTIVE_CHATS = set()

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

# --- ESCÁNER AUTOMÁTICO CADA 15 MINUTOS ---
def background_market_scanner(app):
    # Esperamos 1 minuto a que arrancar el bot antes de hacer el primer escaneo
    time.sleep(60)
    simbolos = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "XRP/USDT"]
    
    while True:
        try:
            if ACTIVE_CHATS:
                print("🔍 Ejecutando análisis automático de 15m...")
                for symbol in simbolos:
                    resultado = analyze_market(symbol)
                    
                    # Si el análisis detecta una entrada real (no está lateral esperando)
                    if "MERCADO LATERAL" not in resultado and "❌" not in resultado:
                        for chat_id in ACTIVE_CHATS:
                            try:
                                mensaje_alerta = f"🚨 **¡ALERTA AUTOMÁTICA DE ENTRADA!** 🚨\n\n{resultado}"
                                # Usamos un loop de eventos de asyncio para enviar el mensaje desde el hilo
                                app.bot.send_message(chat_id=chat_id, text=mensaje_alerta, parse_mode="Markdown")
                            except Exception as e:
                                print(f"Error enviando alerta al chat {chat_id}: {e}")
                    
                    # Pausa breve entre cada cripto para evitar saturar la API de KuCoin
                    time.sleep(5)
            
            # Esperar 15 minutos (900 segundos) para la siguiente vela de 15m
            time.sleep(900)
        except Exception as e:
            print(f"Error en el escáner automático: {e}")
            time.sleep(60)

# Comando /start o /operar con botones interactivos
async def start(update: Update, context):
    chat_id = update.effective_chat.id
    ACTIVE_CHATS.add(chat_id) # Guardamos tu chat para las alertas automáticas
    
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
        "✅ *Has activado las alertas automáticas cada 15m.*\n"
        "Selecciona la criptomoneda que deseas operar o analizar a continuación:"
    )
    
    if update.message:
        await update.message.reply_text(texto, reply_markup=reply_markup, parse_mode="Markdown")
    elif update.callback_query:
        await update.callback_query.message.reply_text(texto, reply_markup=reply_markup, parse_mode="Markdown")

# Manejador cuando presionan los botones
async def button_handler(update: Update, context):
    query = update.callback_query
    await query.answer()
    
    chat_id = update.effective_chat.id
    ACTIVE_CHATS.add(chat_id)
    
    symbol = query.data 
    pair = f"{symbol}/USDT"
    
    await query.message.reply_text(f"🔍 Analizando doble temporalidad (1H y 15m) para {pair}...")
    resultado = analyze_market(pair)
    await query.message.reply_text(resultado, parse_mode="Markdown")

async def analyze_cmd(update: Update, context):
    chat_id = update.effective_chat.id
    ACTIVE_CHATS.add(chat_id)
    
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
    
    # Lanzar el hilo del escáner automático en segundo plano
    scanner_thread = threading.Thread(target=background_market_scanner, args=(application,), daemon=True)
    scanner_thread.start()
    
    print("🤖 Bot iniciado con alertas automáticas 24/7...")
    application.run_polling()
