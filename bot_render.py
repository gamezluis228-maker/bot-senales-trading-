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

@bot.message_handler(commands=['start'])
def send_welcome(message):
    markup = types.InlineKeyboardMarkup()
    btn_operar = types.InlineKeyboardButton("Ejecutar Señal BingX", callback_data='operar_bingx')
    markup.add(btn_operar)
    bot.reply_to(message, "¡Bot de Trading Activo! Selecciona una opción:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data == 'operar_bingx')
def handle_callback_query(call):
    try:
        balance = exchange.fetch_balance()
        bot.answer_callback_query(call.id, "¡Conexión con BingX exitosa!")
        bot.send_message(call.message.chat.id, "Señal procesada correctamente.")
    except Exception as e:
        bot.answer_callback_query(call.id, "Error en el exchange.")
        bot.send_message(call.message.chat.id, f"Detalle del error: {str(e)}")

if __name__ == "__main__":
    bot.remove_webhook()
    bot.infinity_polling(none_stop=True, skip_pending=True)
    
