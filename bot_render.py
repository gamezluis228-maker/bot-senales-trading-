import os
import telebot
from telebot import types
import ccxt

# Lee los datos de forma segura desde las variables de entorno de Render
TOKEN = os.getenv('TELEGRAM_TOKEN')
bingx_api_key = os.getenv('BINGX_API_KEY')
bingx_secret_key = os.getenv('BINGX_SECRET_KEY')

bot = telebot.TeleBot(TOKEN)

# Inicializa la conexión con BingX usando las credenciales de Render
exchange = ccxt.bingx({
    'apiKey': bingx_api_key,
    'secret': bingx_secret_key,
    'enableRateLimit': True,
    'options': {
        'defaultType': 'swap',  # Configurado para futuros/perpetuos
    }
})

@bot.message_handler(commands=['start'])
def send_welcome(message):
    markup = types.InlineKeyboardMarkup()
    # Botón para ejecutar tu operación o señal
    btn_operar = types.InlineKeyboardButton("Ejecutar Señal BingX", callback_data='operar_bingx')
    markup.add(btn_operar)
    bot.reply_to(message, "¡Bot activo y conectado! Selecciona una opción:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data == 'operar_bingx')
def handle_callback_query(call):
    try:
        # Ejemplo básico de prueba de conexión con el balance de la cuenta
        balance = exchange.fetch_balance()
        bot.answer_callback_query(call.id, "¡Conexión exitosa con BingX!")
        bot.send_message(call.message.chat.id, "Señal recibida. Las órdenes se procesarán correctamente.")
    except Exception as e:
        bot.answer_callback_query(call.id, "Error al conectar con el exchange.")
        bot.send_message(call.message.chat.id, f"Error técnico: {str(e)}")

if __name__ == "__main__":
    # Evita conflictos y mantiene una única sesión activa en la nube
    bot.infinity_polling(none_stop=True)
