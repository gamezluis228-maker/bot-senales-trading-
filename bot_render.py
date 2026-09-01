import os
import time
import datetime
import threading
import telebot
from flask import Flask
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from analisis import analyze_market, calculate_risk, radar_market

TOKEN = os.environ.get("TELEGRAM_TOKEN")
TU_CHAT_ID = "7115547861"  # Chat ID configurado directamente

bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot de Trading activo y operando 24/7 en la nube."

@bot.message_handler(commands=['start', 'operar'])
def handle_start(message):
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
    # Pequeña pausa inicial al arrancar el bot
    time.sleep(10)
    while True:
        try:
            # Sincronización matemática con el cierre exacto de la vela de 15 minutos
            now = datetime.datetime.now()
            current_minute = now.minute
            current_second = now.second
            
            remainder = 15 - (current_minute % 15)
            seconds_to_wait = (remainder * 60) - current_second
            if seconds_to_wait <= 0:
                seconds_to_wait += 900
                
            print(f"⏰ Esperando {seconds_to_wait} segundos para sincronizar con el cierre de la vela de 15m...")
            time.sleep(seconds_to_wait)
            
            if TU_CHAT_ID:
                bot.send_message(TU_CHAT_ID, "⏰ **REPORTE AUTOMÁTICO (Cierre Vela 15M)**\n*Analizando pulso de Bitcoin al cierre de vela...*", parse_mode='Markdown')
                resultado_btc = analyze_market("BTC/USDT")
                bot.send_message(TU_CHAT_ID, resultado_btc, parse_mode='Markdown')
        except Exception as e:
            print(f"Error en tarea automática: {e}")
            time.sleep(60)

def run_telegram_bot():
    time.sleep(3)
    while True:
        try:
            print("Iniciando conexión con Telegram...")
            bot.remove_webhook()
            bot.infinity_polling(timeout=60, long_polling_timeout=30, skip_pending=True)
        except Exception as e:
            print(f"⚠️ El bot de Telegram se desconectó: {e}")
            print("Intentando reconectar en 5 segundos...")
            time.sleep(5)

if __name__ == '__main__':
    hilo_bot = threading.Thread(target=run_telegram_bot, daemon=True)
    hilo_bot.start()
    
    hilo_auto = threading.Thread(target=background_auto_analyzer, daemon=True)
    hilo_auto.start()
    
    print("Hilos de trading y Telegram iniciados. Levantando servidor web Flask...")
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
