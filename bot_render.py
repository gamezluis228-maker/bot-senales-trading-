import os
import time
import threading
from flask import Flask
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from analisis import analyze_market, calculate_risk, radar_market

# 1. Servidor Flask para mantener vivo el Web Service en Render
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot de Trading Activo 24/7 🚀"

def run_flask():
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

# 2. Inicialización del Bot de Telegram
TOKEN = os.environ.get("TELEGRAM_TOKEN")
bot = telebot.TeleBot(TOKEN)

# Tu Chat ID personal de Telegram
TU_CHAT_ID = "7115547861"

@bot.message_handler(commands=['start'])
def send_welcome(message):
    markup = InlineKeyboardMarkup()
    markup.row_width = 2
    markup.add(
        InlineKeyboardButton("🪙 BTC/USDT", callback_data="analizar_BTC/USDT"),
        InlineKeyboardButton("🪙 ETH/USDT", callback_data="analizar_ETH/USDT"),
        InlineKeyboardButton("🪙 SOL/USDT", callback_data="analizar_SOL/USDT"),
        InlineKeyboardButton("🪙 XRP/USDT", callback_data="analizar_XRP/USDT")
    )
    bot.reply_to(
        message, 
        "🤖 **¡Panel de Control de Futuros KuCoin!**\n\n"
        "✅ Monitoreo automático de EMAs (15m) activado.\n"
        "Selecciona una criptomoneda o espera las alertas automáticas:", 
        reply_markup=markup,
        parse_mode='Markdown'
    )

@bot.message_handler(commands=['operar', 'analizar'])
def handle_operar(message):
    markup = InlineKeyboardMarkup()
    markup.row_width = 2
    markup.add(
        InlineKeyboardButton("🪙 BTC/USDT", callback_data="analizar_BTC/USDT"),
        InlineKeyboardButton("🪙 ETH/USDT", callback_data="analizar_ETH/USDT"),
        InlineKeyboardButton("🪙 SOL/USDT", callback_data="analizar_SOL/USDT"),
        InlineKeyboardButton("🪙 XRP/USDT", callback_data="analizar_XRP/USDT")
    )
    bot.send_message(
        message.chat.id, 
        "🤖 **Selecciona la criptomoneda a analizar:**", 
        reply_markup=markup, 
        parse_mode='Markdown'
    )

@bot.message_handler(commands=['radar'])
def handle_radar(message):
    bot.reply_to(message, "📡 *Escaneando el mercado institucional...*", parse_mode='Markdown')
    resultado_radar = radar_market()
    bot.reply_to(message, resultado_radar, parse_mode='Markdown')

@bot.callback_query_handler(func=lambda call: call.data.startswith("analizar_"))
def callback_analizar(call):
    symbol = call.data.split("_")[1]
    bot.answer_callback_query(call.id, f"Analizando {symbol}...")
    bot.send_message(call.message.chat.id, f"🔍 *Analizando EMAs (15m) y volumen para {symbol}...*", parse_mode='Markdown')
    
    resultado = analyze_market(symbol)
    bot.send_message(call.message.chat.id, resultado, parse_mode='Markdown')

@bot.message_handler(commands=['riesgo'])
def handle_riesgo(message):
    try:
        partes = message.text.split()
        margen = partes[1] if len(partes) > 1 else 10
        resultado = calculate_risk(margen_usdt=margen)
        bot.reply_to(message, resultado, parse_mode='Markdown')
    except Exception as e:
        bot.reply_to(message, "⚠️ Usa el formato correcto, por ejemplo: `/riesgo 10`", parse_mode='Markdown')

# 3. Tarea en segundo plano: Alarma automática cada 15 minutos
def background_auto_analyzer():
    # Espera 30 segundos a que el bot inicie correctamente
    time.sleep(30)
    while True:
        try:
            bot.send_message(TU_CHAT_ID, "⏰ **REPORTE AUTOMÁTICO (15M)**\n*Revisando cruce de EMAs y rupturas institucionales...*", parse_mode='Markdown')
            # Análisis automático de BTC/USDT en el reporte de 15m
            resultado_btc = analyze_market("BTC/USDT")
            bot.send_message(TU_CHAT_ID, resultado_btc, parse_mode='Markdown')
        except Exception as e:
            print(f"Error en tarea automática: {e}")
        
        # Duerme exactamente 15 minutos (900 segundos)
        time.sleep(900)

# 4. Ejecución concurrente (Flask + Bot + Hilo de 15 minutos)
if __name__ == '__main__':
    # Hilo para Flask
    t_flask = threading.Thread(target=run_flask)
    t_flask.daemon = True
    t_flask.start()

    # Hilo para el análisis automático de 15 minutos
    t_auto = threading.Thread(target=background_auto_analyzer)
    t_auto.daemon = True
    t_auto.start()
    
    print("🤖 Bot privado iniciado y operando 24/7 con alertas de 15m...")
    bot.infinity_polling(skip_pending=True)
