import os
import telebot
from telebot import types
import ccxt

TOKEN = os.getenv('TELEGRAM_TOKEN')
bingx_api_key = os.getenv('BINGX_API_KEY')
bingx_secret_key = os.getenv('BINGX_SECRET_KEY')

bot = telebot.TeleBot(TOKEN)

# Diccionario para recordar el margen que selecciona cada usuario
user_margins = {}

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
    # Creación de los botones del 1$ al 20$
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

# Comando rápido para verificar el balance y la conexión con BingX
@bot.message_handler(commands=['balance'])
def check_balance(message):
    try:
        if exchange is None:
            bot.reply_to(message, "❌ El exchange no está inicializado (revisa tus API Keys en Render).")
            return
        balance = exchange.fetch_balance()
        usdt_free = balance['USDT']['free'] if 'USDT' in balance else 0
        bot.reply_to(message, f"💵 Tu balance disponible en BingX es: ${usdt_free:.2f} USDT")
    except Exception as e:
        bot.reply_to(message, f"❌ Error al consultar el balance: {str(e)}")

@bot.callback_query_handler(func=lambda call: call.data.startswith('margen_'))
def seleccionar_margen(call):
    margen = call.data.split('_')[1]
    user_margins[call.message.chat.id] = margen
    bot.answer_callback_query(call.id, f"Margen seleccionado: {margen} USDT")
    bot.send_message(call.message.chat.id, f"Has seleccionado un margen de **{margen} USDT**. Presiona confirmar para proceder.", parse_mode="Markdown")

@bot.callback_query_handler(func=lambda call: call.data == 'operar_bingx')
def handle_callback_query(call):
    try:
        if exchange is None:
            raise Exception("El exchange no está inicializado correctamente (revisa las API keys).")
        
        chat_id = call.message.chat.id
        monto_elegido = user_margins.get(chat_id, "1") # Por defecto 1 si no seleccionó nada
        
        # Consulta rápida al exchange para verificar la respuesta en vivo
        balance = exchange.fetch_balance()
        usdt_free = balance['USDT']['free'] if 'USDT' in balance else 0
        
        bot.answer_callback_query(call.id, "¡Conexión con BingX exitosa!")
        bot.send_message(
            chat_id, 
            f"✅ Señal procesada con éxito.\n"
            f"📊 Margen asignado: **{monto_elegido} USDT**\n"
            f"💵 Saldo libre actual en BingX: ${usdt_free:.2f} USDT"
        )
    except Exception as e:
        bot.answer_callback_query(call.id, "Error en el exchange.")
        bot.send_message(call.message.chat.id, f"Detalle del error: {str(e)}")

if __name__ == "__main__":
    bot.remove_webhook()
    bot.infinity_polling(timeout=60, long_polling_timeout=60)
