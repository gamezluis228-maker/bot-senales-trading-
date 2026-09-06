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

# --- FUNCIÓN DE EJECUCIÓN SEGURA (Stop Loss 4% y Spot/Swap) ---
def procesar_operacion_segura(symbol, tipo_mercado, side, amount_usdt):
    try:
        if tipo_mercado == 'swap':
            market_symbol = f"{symbol}:USDT"
            exchange.options['defaultType'] = 'swap'
            exchange.set_leverage(5, market_symbol)
        else:
            market_symbol = symbol
            exchange.options['defaultType'] = 'spot'

        ticker = exchange.fetch_ticker(market_symbol)
        precio_actual = ticker['last']
        amount_tokens = amount_usdt / precio_actual

        params = {}
        if tipo_mercado == 'swap':
            if side == 'buy':
                stop_loss_price = precio_actual * (1 - 0.04)
            else:
                stop_loss_price = precio_actual * (1 + 0.04)
            params['stopLossPrice'] = exchange.price_to_precision(market_symbol, stop_loss_price)

        orden = exchange.create_order(
            symbol=market_symbol,
            type='market',
            side=side,
            amount=amount_tokens,
            params=params
        )
        return True, precio_actual, orden
    except Exception as e:
        return False, 0, str(e)


# --- MANEJADOR DE TELEGRAM BLINDADO CONTRA ERRORES DE LISTA ---
@bot.callback_query_handler(func=lambda call: True)
def callback_query(call):
    try:
        datos = call.data.split("_")
        
        # Validar que el botón tenga el formato correcto de 4 partes (ej: APT_swap_buy_10)
        if len(datos) < 4:
            bot.answer_callback_query(call.id, "Acción no reconocida o formato antiguo.")
            return

        simbolo = datos[0]
        mercado = datos[1]  # 'swap' o 'spot'
        accion = datos[2]   # 'buy' o 'sell'
        margen = float(datos[3])  # Entre 1 y 20 USDT

        bot.answer_callback_query(call.id, "Procesando orden...")

        exito, precio, resultado = procesar_operacion_segura(simbolo, mercado, accion, margen)

        if exito:
            bot.send_message(
                call.message.chat.id, 
                f"✅ **¡Operación Ejecutada!**\n\n"
                f"• Activo: {simbolo}\n"
                f"• Mercado: {mercado.upper()}\n"
                f"• Margen: ${margen} USDT\n"
                f"• Entrada: {precio}\n"
                f"• Stop Loss: 4%"
            )
        else:
            bot.send_message(call.message.chat.id, f"❌ Error en el exchange:\n{resultado}")
            
    except Exception as e:
        bot.send_message(call.message.chat.id, f"❌ Error: {str(e)}")


# --- ARRANQUE EN SEGUNDO PLANO ---
def iniciar_bot():
    bot.remove_webhook()
    bot.infinity_polling(skip_pending=True)

if __name__ == "__main__":
    hilo_bot = threading.Thread(target=iniciar_bot)
    hilo_bot.daemon = True
    hilo_bot.start()

    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
