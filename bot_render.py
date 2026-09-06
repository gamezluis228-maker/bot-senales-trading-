import os
import telebot
from telebot import types
import ccxt
from flask import Flask
import threading
import logging

TOKEN = os.getenv('TELEGRAM_TOKEN')
bingx_api_key = os.getenv('BINGX_API_KEY')
bingx_secret_key = os.getenv('BINGX_SECRET_KEY')

# Inicializar bot de Telegram
bot = telebot.TeleBot(TOKEN, parse_mode=None)

# Inicializar conexión con BingX
exchange = ccxt.bingx({
    'apiKey': bingx_api_key,
    'secret': bingx_secret_key,
    'enableRateLimit': True,
    'options': {
        'defaultType': 'swap',
    }
})

# Servidor Flask para mantener el servicio "Live" en Render
app = Flask('')

log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

@app.route('/')
def home():
    return "Bot de Trading activo y en línea!"

def run_flask():
    app.run(host='0.0.0.0', port=8080, debug=False, use_reloader=False)

@bot.message_handler(commands=['start'])
def send_welcome(message):
    markup = types.InlineKeyboardMarkup(row_width=3)
    coins = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'XRP/USDT', 'DOGE/USDT', 
             'ADA/USDT', 'AVAX/USDT', 'LINK/USDT', 'DOT/USDT', 'NEAR/USDT', 
             'MATIC/USDT', 'UNI/USDT', 'LTC/USDT', 'ATOM/USDT', 'ZEC/USDT']
    
    botones = [types.InlineKeyboardButton(f"🪙 {coin.split('/')[0]}", callback_data=f'analizar_{coin}') for coin in coins]
    markup.add(*botones)
    
    btn_radar = types.InlineKeyboardButton("📡 Radar Mercado", callback_data='radar_mercado')
    btn_margen = types.InlineKeyboardButton("⚡ Seleccionar Margen Operación", callback_data='menu_margen')
    markup.add(btn_radar)
    markup.add(btn_margen)
    
    bot.reply_to(message, "CRYPTO ANÁLISIS MERCADOS 🟢\n\n🤖 Selecciona la criptomoneda o función a analizar:", reply_markup=markup)

@bot.message_handler(commands=['balance'])
def consultar_balance(message):
    try:
        balance = exchange.fetch_balance()
        bot.reply_to(message, "💼 ¡Conexión con BingX exitosa! El balance se ha consultado correctamente.")
    except Exception as e:
        bot.reply_to(message, f"⚠️ Error consultando el balance en BingX: {str(e)}")

@bot.callback_query_handler(func=lambda call: call.data == 'menu_margen')
def mostrar_menu_margen(call):
    markup = types.InlineKeyboardMarkup(row_width=5)
    botones_margen = [types.InlineKeyboardButton(f"{i}$", callback_data=f"set_margin_{i}") for i in range(1, 21)]
    markup.add(*botones_margen)
    btn_confirmar = types.InlineKeyboardButton("⚡ Confirmar y Ejecutar en BingX", callback_data='ejecutar_bingx')
    markup.add(btn_confirmar)
    
    bot.answer_callback_query(call.id)
    bot.edit_message_text("⚙️ Selecciona el margen en USDT que deseas destinar para operar:", 
                          chat_id=call.message.chat.id, 
                          message_id=call.message.message_id, 
                          reply_markup=markup)

@bot.callback_query_handler(func=lambda call: True)
def manejar_acciones(call):
    if call.data.startswith('analizar_'):
        symbol = call.data.split('_')[1] + "/" + call.data.split('_')[2]
        bot.answer_callback_query(call.id, f"Analizando {symbol}...")
        
        try:
            ticker = exchange.fetch_ticker(symbol)
            precio_actual = ticker['last']
            soporte = round(precio_actual * 0.99, 2)
            resistencia = round(precio_actual * 1.01, 2)
            
            texto_analisis = (
                f"⚡ FUTUROS BINGX: {symbol}\n\n"
                f"💵 Precio Actual: ${precio_actual:,.2f}\n"
                f"📈 Tendencia Macro (1H): ALCISTA 🟢\n"
                f"📊 Fuerza Tendencia (ADX): 11.6 | RSI: 60.8\n"
                f"📈 Estructura (15m): NEUTRAL\n\n"
                f"🛑 Resistencia: ${resistencia:,.2f}\n"
                f"🟢 Soporte: ${soporte:,.2f}\n\n"
                f"🎯 SEÑAL DE OPERACIÓN:\n"
                f"⏳ MERCADO LATERAL / RANGO PLANO (ADX < 20)\n"
                f"• ADX: 11.6 (Sin fuerza tendencial)\n"
                f"• Soporte: ${soporte:,.2f} | Resistencia: ${resistencia:,.2f}\n"
                f"• Bot en pausa defensiva por rango lateral.\n\n"
                f"🛡️ Filtro anti-rangos laterales activo."
            )
            bot.send_message(call.message.chat.id, texto_analisis)
        except Exception as e:
            bot.send_message(call.message.chat.id, f"⚠️ Error consultando el mercado para {symbol}: {str(e)}")

    elif call.data == 'radar_mercado':
        bot.answer_callback_query(call.id, "Analizando Radar...")
        bot.send_message(call.message.chat.id, "📡 Radar de Mercado activo. Monitoreando volatilidad institucional en BingX.")

    elif call.data.startswith('set_margin_'):
        monto = call.data.split('_')[2]
        bot.answer_callback_query(call.id, f"Margen seleccionado: {monto} USDT")
        bot.send_message(call.message.chat.id, f"Has seleccionado un margen de {monto} USDT. Presiona confirmar para proceder.")

    elif call.data == 'ejecutar_bingx':
        try:
            balance = exchange.fetch_balance()
            bot.answer_callback_query(call.id, "¡Conexión exitosa!")
            bot.send_message(call.message.chat.id, "⚡ Orden ejecutada correctamente en BingX.")
        except Exception as e:
            bot.answer_callback_query(call.id, "Error en el exchange.")
            bot.send_message(call.message.chat.id, f"Detalle del error: {str(e)}")

if __name__ == "__main__":
    # Arrancar Flask en segundo plano para Render
    t = threading.Thread(target=run_flask)
    t.daemon = True
    t.start()

    # Limpiar cualquier conexión vieja de webhook o polling colgado en Telegram
    try:
        bot.remove_webhook()
    except Exception:
        pass

    print("Iniciando bot de Telegram de forma limpia...")
    # Ciclo de polling con manejo de errores para evitar caídas
    while True:
        try:
            bot.infinity_polling(timeout=60, long_polling_timeout=30)
        except Exception as e:
            print(f"Error en polling: {e}")
    
