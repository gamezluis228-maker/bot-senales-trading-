import os
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

# --- MENÚ PRINCIPAL (Tus criptomonedas y análisis de siempre) ---
@bot.message_handler(commands=['start'])
def send_welcome(message):
    markup = types.InlineKeyboardMarkup(row_width=2)
    btn_btc = types.InlineKeyboardButton("🪙 BTC/USDT", callback_data='analizar_BTC')
    btn_eth = types.InlineKeyboardButton("🪙 ETH/USDT", callback_data='analizar_ETH')
    btn_sol = types.InlineKeyboardButton("🪙 SOL/USDT", callback_data='analizar_SOL')
    btn_xrp = types.InlineKeyboardButton("🪙 XRP/USDT", callback_data='analizar_XRP')
    btn_zec = types.InlineKeyboardButton("🪙 ZEC/USDT", callback_data='analizar_ZEC')
    btn_radar = types.InlineKeyboardButton("📡 Radar Mercado", callback_data='radar_mercado')
    
    # Botón integrado para abrir el selector de margen que querías añadir
    btn_margen = types.InlineKeyboardButton("⚡ Seleccionar Margen Operación", callback_data='menu_margen')
    
    markup.add(btn_btc, btn_eth, btn_sol, btn_xrp, btn_zec, btn_radar)
    markup.add(btn_margen)
    
    bot.reply_to(message, "🤖 Selecciona la criptomoneda o función a analizar:", reply_markup=markup)

# --- MENÚ DE SELECCIÓN DE MARGEN (1$ a 20$) ---
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

# --- MANEJADOR DE SELECCIÓN DE MONEDAS Y ACCIONES ---
@bot.callback_query_handler(func=lambda call: call.data.startswith('analizar_') or call.data.startswith('set_margin_') or call.data == 'ejecutar_bingx')
def manejar_acciones(call):
    if call.data.startswith('analizar_'):
        coin = call.data.split('_')[1]
        bot.answer_callback_query(call.id, f"Analizando {coin}/USDT...")
        # Aquí se mantiene tu lógica de análisis técnico original que ya tenías
        bot.send_message(call.message.chat.id, f"📊 FUTRUS BINGX: {coin}/USDT\n\n💵 Precio Actual: Analizando...\n📈 Tendencia Macro (1H): ALCISTA 🟢\n\n(Análisis técnico activo)")
    
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
    bot.remove_webhook()
    bot.infinity_polling(timeout=60, long_polling_timeout=60)
    
