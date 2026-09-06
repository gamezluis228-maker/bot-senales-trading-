import os
import threading
import telebot
import ccxt
from flask import Flask

TOKEN = os.getenv("TELEGRAM_TOKEN")
API_KEY = os.getenv("BINGX_API_KEY")
SECRET_KEY = os.getenv("BINGX_SECRET_KEY")

bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

exchange = ccxt.bingx({
    'apiKey': API_KEY,
    'secret': SECRET_KEY,
    'enableRateLimit': True,
    'options': {'defaultType': 'swap'}
})

@app.route('/')
def home():
    return "Bot Activo"

@bot.message_handler(commands=['start', 'help'])
def enviar_bienvenida(message):
    bot.reply_to(message, "¡Hola! El bot está activo y listo para operar.")

@bot.callback_query_handler(func=lambda call: True)
def callback_query(call):
    try:
        datos = call.data.split("_")
        if len(datos) < 4:
            bot.answer_callback_query(call.id, "Formato no válido.")
            return

        simbolo = datos[0]
        mercado = datos[1]
        accion = datos[2]
        margen = float(datos[3])

        bot.answer_callback_query(call.id, "Procesando...")

        if mercado == 'swap':
            market_symbol = f"{simbolo}:USDT"
            exchange.options['defaultType'] = 'swap'
            exchange.set_leverage(5, market_symbol)
        else:
            market_symbol = simbolo
            exchange.options['defaultType'] = 'spot'

        ticker = exchange.fetch_ticker(market_symbol)
        precio_actual = ticker['last']
        amount_tokens = margen / precio_actual

        params = {}
        if mercado == 'swap':
            if accion == 'buy':
                stop_loss_price = precio_actual * (1 - 0.04)
            else:
                stop_loss_price = precio_actual * (1 + 0.04)
            params['stopLossPrice'] = exchange.price_to_precision(market_symbol, stop_loss_price)

        exchange.create_order(
            symbol=market_symbol,
            type='market',
            side=accion,
            amount=amount_tokens,
            params=params
        )

        bot.send_message(
            call.message.chat.id,
            f"✅ **¡Operación Ejecutada!**\n\n"
            f"• Activo: {simbolo}\n"
            f"• Mercado: {mercado.upper()}\n"
            f"• Margen: ${margen} USDT\n"
            f"• Entrada: {precio_actual}\n"
            f"• Stop Loss: 4%"
        )
    except Exception as e:
        bot.send_message(call.message.chat.id, f"❌ Error: {str(e)}")

def arrancar_bot():
    try:
        bot.remove_webhook()
        bot.infinity_polling(skip_pending=True)
    except Exception as e:
        print(f"Error en bot: {e}")

if __name__ == "__main__":
    t = threading.Thread(target=arrancar_bot)
    t.daemon = True
    t.start()

    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
    
