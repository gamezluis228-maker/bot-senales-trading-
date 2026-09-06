import os
import threading
import telebot
import ccxt
from flask import Flask
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

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
    return "Bot de Trading y Análisis Activo"

# --- MENÚ PRINCIPAL Y BOTONES DESPLEGABLES ---
@bot.message_handler(commands=['start', 'menu'])
def mostrar_menu(message):
    markup = InlineKeyboardMarkup(row_width=2)
    # Formato del callback_data: SIMBOLO_MERCADO_ACCION_MARGEN
    markup.add(
        InlineKeyboardButton("🚀 Comprar ZEC Futuros ($10)", callback_data="ZEC_swap_buy_10"),
        InlineKeyboardButton("📉 Vender ZEC Futuros ($10)", callback_data="ZEC_swap_sell_10"),
        InlineKeyboardButton("🟢 Comprar ZEC Spot ($10)", callback_data="ZEC_spot_buy_10")
    )
    bot.send_message(
        message.chat.id, 
        "📊 **PANEL DE SEÑALES Y ANÁLISIS BINGX**\n\n"
        "Selecciona una operación rápida o espera las alertas automáticas:", 
        reply_markup=markup, 
        parse_mode="Markdown"
    )

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

# --- MANEJADOR DE BOTONES INTERACTIVOS (BLINDADO) ---
@bot.callback_query_handler(func=lambda call: True)
def callback_query(call):
    try:
        datos = call.data.split("_")
        
        if len(datos) < 4:
            bot.answer_callback_query(call.id, "Formato de botón no válido.")
            return

        simbolo = datos[0]
        mercado = datos[1]  # 'swap' o 'spot'
        accion = datos[2]   # 'buy' o 'sell'
        margen = float(datos[3])  # Entre 1 y 20 USDT

        bot.answer_callback_query(call.id, "Ejecutando orden en BingX...")

        exito, precio, resultado = procesar_operacion_segura(simbolo, mercado, accion, margen)

        if exito:
            bot.send_message(
                call.message.chat.id, 
                f"✅ **¡Operación Ejecutada con Éxito!**\n\n"
                f"• Activo: {simbolo}\n"
                f"• Mercado: {mercado.upper()}\n"
                f"• Margen: ${margen} USDT\n"
                f"• Entrada: {precio}\n"
                f"• Stop Loss: 4% 🛡️"
            )
        else:
            bot.send_message(call.message.chat.id, f"❌ Error en el exchange:\n{resultado}")
            
    except Exception as e:
        bot.send_message(call.message.chat.id, f"❌ Error crítico: {str(e)}")

# --- ARRANQUE EN SEGUNDO PLANO (FLASK + BOT) ---
def iniciar_bot():
    try:
        bot.remove_webhook()
        bot.infinity_polling(skip_pending=True)
    except Exception as e:
        print(f"Error en bot: {e}")

if __name__ == "__main__":
    t = threading.Thread(target=iniciar_bot)
    t.daemon = True
    t.start()

    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
    
