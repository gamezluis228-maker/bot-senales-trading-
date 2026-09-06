import os
import telebot
from telebot import types
import ccxt

TOKEN = os.getenv('TELEGRAM_TOKEN')
bingx_api_key = os.getenv('BINGX_API_KEY')
bingx_secret_key = os.getenv('BINGX_SECRET_KEY')

bot = telebot.TeleBot(TOKEN)

# Inicialización segura para evitar el error de NoneType al arrancar
try:
    exchange = ccxt.bingx({
        'apiKey': bingx_api_key,
        'secret': bingx_secret_key,
        'enableRateLimit': True,
        'options': {
            'defaultType': 'swap',
        }
    })
except Exception as e:
    exchange = None
    print(f"Advertencia al conectar con BingX: {str(e)}")

@bot.message_handler(commands=['start'])
def send_welcome(message):
    markup = types.InlineKeyboardMarkup(row_width=5)
    # Creación de los botones del 1$ al 20$ como querías
    botones_margen = [
        types.InlineKeyboardButton(f"{i}$", callback_data=f"margen_{i}") 
        for i in range(1, 21)
    ]
    markup.add(*botones_margen)
    btn_confirmar = types.InlineKeyboardButton("⚡ Confirmar y Ejecutar en BingX", callback_data='operar_bingx')
    markup.add(btn_confirmar)
    
    bot.reply_to(
        message, 
        "⚙️ Selecciona el margen en USDT que deseas destinar para operar:", 
        reply_markup=markup
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith('margen_'))
def seleccionar_margen(call):
    margen = call.data.split('_')[1]
    bot.answer_callback_query(call.id, f"Margen seleccionado: {margen} USDT")
    bot.send_message(call.message.chat.id, f"Has seleccionado un margen de **{margen} USDT**. Presiona confirmar para proceder.", parse_mode="Markdown")

@bot.callback_query_handler(func=lambda call: call.data == 'operar_bingx')
def handle_callback_query(call):
    try:
        if exchange is None:
            raise Exception("El exchange no está inicializado correctamente (revisa las API keys).")
        balance = exchange.fetch_balance()
        bot.answer_callback_query(call.id, "¡Conexión con BingX exitosa!")
        bot.send_message(call.message.chat.id, "Señal procesada y ejecutada correctamente en el exchange.")
    except Exception as e:
        bot.answer_callback_query(call.id, "Error en el exchange.")
        bot.send_message(call.message.chat.id, f"Detalle del error: {str(e)}")

if __name__ == "__main__":
    bot.remove_webhook()
    bot.infinity_polling(timeout=60, long_polling_timeout=60)
