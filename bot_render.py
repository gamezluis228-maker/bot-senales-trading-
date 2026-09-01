import os
import time
import threading
import telebot
from flask import Flask
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from analisis import analyze_market, calculate_risk, radar_market

TOKEN = os.environ.get("TELEGRAM_TOKEN")
TU_CHAT_ID = os.environ.get("CHAT_ID", "tu_chat_id_real")

bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot de Trading activo y operando 24/7 en la nube."

@bot.message_handler(commands=['start', 'operar'])
def handle_start(message):
    # Creamos la cuadrícula de botones tal como la tenías
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("🪙 BTC/USDT", callback_data="analisis_BTC/USDT"),
        InlineKeyboardButton("🪙 ETH/USDT", callback_data="analisis_ETH/USDT"),
        InlineKeyboardButton("🪙 SOL/USDT", callback_data="analisis_SOL/USDT"),
        InlineKeyboardButton("🪙 XRP/USDT", callback_data="analisis_XRP/USDT"),
        InlineKeyboardButton("📡 Radar Mercado", callback_data="cmd_radar"),
        InlineKeyboardButton("⚠️ Riesgo 10U", callback_data="cmd_riesgo")
    )
    
    bot.reply_to(
        message, 
        "🤖 **Selecciona la criptomoneda o función a analizar:**", 
        reply_markup=markup, 
        parse_mode='Markdown'
    )

@bot.message_handler(commands=['analisis'])
def handle_analisis(message):
    try:
        partes = message.text.split()
        symbol = partes[1].upper() if len(partes) > 1 else "BTC/USDT"
        if not symbol.endswith("/USDT"):
            symbol += "/USDT"
            
        bot.reply_to(message, f"🔍 Analizando {symbol} en KuCoin Futuros...", parse_mode='Markdown')
        resultado = analyze_market(symbol)
        bot.reply_to(message, resultado, parse_mode='Markdown')
    except Exception as e:
        bot.reply_to(message, "⚠️ Uso correcto: `/analisis ETH/USDT`", parse_mode='Markdown')

@bot.message_handler(commands=['riesgo'])
def handle_riesgo(message):
    try:
        partes = message.text.split()
        margen = partes[1] if len(partes) > 1 else "10"
        symbol = partes[2].upper() if len(partes) > 2 else "BTC/USDT"
        if not symbol.endswith("/USDT"):
            symbol += "/USDT"
            
        resultado = calculate_risk(margen_usdt=margen, symbol=symbol)
        bot.reply_to(message, resultado, parse_mode='Markdown')
    except Exception as e:
        bot.reply_to(message, "⚠️ Usa el formato correcto, por ejemplo: `/riesgo 10`", parse_mode='Markdown')

@bot.message_handler(commands=['radar'])
def handle_radar(message):
    bot.reply_to(message, "📡 *Escaneando el mercado institucional...*", parse_mode='Markdown')
    resultado_radar = radar_market()
    
    if resultado_radar:
        bot.reply_to(message, resultado_radar, parse_mode='Markdown')
    else:
        bot.reply_to(message, "📡 **RADAR DE MERCADO**: Las altcoins están en rango o sin suficiente volumen institucional en este momento.", parse_mode='Markdown')

# Manejador para los toques en la cuadrícula de botones
@bot.callback_query_handler(func=lambda call: True)
def callback_query(call):
    try:
        if call.data.startswith("analisis_"):
            symbol = call.data.split("_")[1]
            bot.answer_callback_query(call.id, f"Analizando {symbol}...")
            bot.send_message(call.message.chat.id, f"🔍 Analizando {symbol} en KuCoin Futuros...", parse_mode='Markdown')
            resultado = analyze_market(symbol)
            bot.send_message(call.message.chat.id, resultado, parse_mode='Markdown')
            
        elif call.data == "cmd_radar":
            bot.answer_callback_query(call.id, "Escaneando mercado...")
            bot.send_message(call.message.chat.id, "📡 *Escaneando el mercado institucional...*", parse_mode='Markdown')
            resultado_radar = radar_market()
            if resultado_radar:
                bot.send_message(call.message.chat.id, resultado_radar, parse_mode='Markdown')
            else:
                bot.send_message(call.message.chat.id, "📡 **RADAR**: Las altcoins están en rango actualmente.", parse_mode='Markdown')
                
        elif call.data == "cmd_riesgo":
            bot.answer_callback_query(call.id, "Calculando riesgo...")
            resultado = calculate_risk(margen_usdt=10, symbol="BTC/USDT")
            bot.send_message(call.message.chat.id, resultado, parse_mode='Markdown')
    except Exception as e:
        print(f"Error en callback: {e}")

def background_auto_analyzer():
    time.sleep(30)
    while True:
        try:
            if TU_CHAT_ID and TU_CHAT_ID != "tu_chat_id_real":
                bot.send_message(TU_CHAT_ID, "⏰ **REPORTE AUTOMÁTICO (15M)**\n*Revisando pulso de Bitcoin...*", parse_mode='Markdown')
                resultado_btc = analyze_market("BTC/USDT")
                bot.send_message(TU_CHAT_ID, resultado_btc, parse_mode='Markdown')
        except Exception as e:
            print(f"Error en tarea automática: {e}")
        time.sleep(900)

def run_telegram_bot():
    time.sleep(3)
    while True:
        try:
            print("Limpiando webhooks y sesiones previas de Telegram...")
            bot.remove_webhook()
            # skip_pending=True descarta peticiones viejas colgadas y evita el Error 409
            bot.infinity_polling(timeout=20, long_polling_timeout=10, skip_pending=True)
        except Exception as e:
            print(f"Conflicto o desconexión detectada. Reintentando en 15 segundos... Detalles: {e}")
            time.sleep(15)

if __name__ == '__main__':
    hilo_bot = threading.Thread(target=run_telegram_bot, daemon=True)
    hilo_bot.start()
    
    hilo_auto = threading.Thread(target=background_auto_analyzer, daemon=True)
    hilo_auto.start()
    
    print("Hilos iniciados. Levantando servidor web Flask...")
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
