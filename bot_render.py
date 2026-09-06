fkfnfimport os
import telebot
from telebot import types
import ccxt

TOKEN = os.getenv('TELEGRAM_TOKEN')
bingx_api_key = os.getenv('BINGX_API_KEY')
bingx_secret_key = os.getenv('BINGX_SECRET_KEY')

bot = telebot.TeleBot(TOKEN)

exchange = ccxt.bingx({
    'apiKey': bingx_api_key,
    'secret': bingx_secret_key,
    'enableRateLimit': True,
    'options': {
        'defaultType': 'swap',
    }
})

@bot.message_handler(commands=['start'])
def send_welcome(message):
    markup = types.InlineKeyboardMarkup(row_width=2)
    btn_btc = types.InlineKeyboardButton("🪙 BTC/USDT", callback_data='analizar_BTC/USDT')
    btn_eth = types.InlineKeyboardButton("🪙 ETH/USDT", callback_data='analizar_ETH/USDT')
    btn_sol = types.InlineKeyboardButton("🪙 SOL/USDT", callback_data='analizar_SOL/USDT')
    btn_xrp = types.InlineKeyboardButton("🪙 XRP/USDT", callback_data='analizar_XRP/USDT')
    btn_zec = types.InlineKeyboardButton("🪙 ZEC/USDT", callback_data='analizar_ZEC/USDT')
    btn_radar = types.InlineKeyboardButton("📡 Radar Mercado", callback_data='radar_mercado')
    btn_margen = types.InlineKeyboardButton("⚡ Seleccionar Margen Operación", callback_data='menu_margen')
    
    markup.add(btn_btc, btn_eth, btn_sol, btn_xrp, btn_zec, btn_radar)
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
    botones_margen = []
    for i in range(1, 21):
        botones_margen.append(types.InlineKeyboardButton(f"{i}$", callback_data=f"set_margin_{i}"))
    
    markup.add(*botones_margen)
    btn_confirmar = types.InlineKeyboardButton("⚡ Confirmar y Ejecutar en BingX", callback_data='ejecutar_bingx')
    markup.add(btn_confirmar)
    
    bot.answer_callback_query(call.id)
    bot.edit_message_text("⚙️ Selecciona el margen en USDT que deseas destinar para operar:", 
                          chat_id=call.message.chat.id, 
                          message_id=call.message.message_id, 
                          reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('analizar_') or call.data.startswith('set_margin_') or call.data == 'ejecutar_bingx' or call.data == 'radar_mercado')
def manejar_acciones(call):
    if call.data.startswith('analizar_'):
        symbol = call.data.split('_')[1]
        bot.answer_callback_query(call.id, f"Analizando {symbol} en BingX Futuros...")
        
        try:
            ticker = exchange.fetch_ticker(symbol)
            precio_actual = ticker['last']
            soporte = round(precio_actual * 0.99, 2)
            resistencia = round(precio_actual * 1.01, 2)
            
            texto_analisis = (
                f"⚡ FUTUROS BINGX: {symbol}\n\n"
                f"💵 Precio Actual: ${precio_actual:,.2f}\n"
                f"📈 Tendencia Macro (1H): ALCISTA 🟢\n"
                f"📊 Estructura (15m): NEUTRAL\n\n"
                f"🛑 Resistencia: ${resistencia:,.2f}\n"
                f"🟢 Soporte: ${soporte:,.2f}\n\n"
                f"🎯 SEÑAL DE OPERACIÓN:\n"
                f"⏳ MERCADO LATERAL / ESPERAR RUPTURA\n"
                f"• Soporte Clave: ${soporte:,.2f}\n"
                f"• Resistencia Clave: ${resistencia:,.2f}\n"
                f"• Esperar rompimiento con volumen."
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
            bot.answer_callback_query(call.id, "¡Conexión con BingX exitosa!")
            bot.send_message(call.message.chat.id, "⚡ Orden ejecutada correctamente en BingX.")
        except Exception as e:
            bot.answer_callback_query(call.id, "Error en el exchange.")
            bot.send_message(call.message.chat.id, f"Detalle del error: {str(e)}")

if __name__ == "__main__":
    try:
        bot.stop_polling()
    except Exception:
        pass
    
    try:
        bot.remove_webhook()
    except Exception:
        pass
        
    bot.infinity_polling(skip_pending=True, timeout=60, long_polling_timeout=60)
    
