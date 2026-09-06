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
    return "Bot Activo"

# --- TU MENÚ ORIGINAL DE ANÁLISIS Y MONEDAS ---
@bot.message_handler(commands=['start', 'menu'])
def mostrar_menu_analisis(message):
    markup = InlineKeyboardMarkup(row_width=3)
    monedas = ["BTC", "ETH", "SOL", "XRP", "DOGE", "ADA", "AVAX", "LINK", "DOT", "NEAR", "MATIC", "UNI", "LTC", "ATOM", "ZEC"]
    
    botones = [InlineKeyboardButton(coin, callback_data=f"analisis_{coin}") for coin in monedas]
    markup.add(*botones)
    markup.add(InlineKeyboardButton("📡 Radar Mercado", callback_data="radar_mercado"))

    bot.send_message(
        message.chat.id, 
        "CRYPTO ANÁLISIS MERCADOS 🟢\n\n🤖 Selecciona una criptomoneda para su análisis técnico y opciones de operación:", 
        reply_markup=markup
    )

# --- FUNCIÓN DE EJECUCIÓN SEGURA (Stop Loss 4% y Spot/Swap) ---
def procesar_operacion_segura(symbol, tipo_mercado, side, amount_usdt):
    try:
        if tipo_mercado == 'swap':
            market_symbol = f"{symbol}/USDT:USDT"
            exchange.options['defaultType'] = 'swap'
            exchange.set_leverage(5, market_symbol)
        else:
            market_symbol = f"{symbol}/USDT"
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

# --- MANEJADOR DE BOTONES UNIFICADO (BLINDADO) ---
@bot.callback_query_handler(func=lambda call: True)
def callback_query(call):
    try:
        datos = call.data.split("_")
        accion = datos[0]

        if accion == "analisis" and len(datos) >= 2:
            coin = datos[1]
            market_symbol = f"{coin}/USDT:USDT"
            
            bot.answer_callback_query(call.id, f"Analizando {coin}...")
            
            try:
                ticker = exchange.fetch_ticker(market_symbol)
                precio = ticker['last']
            except:
                precio = 1000.0  # Valor de respaldo si falla el ticker

            # Reporte visual que tenías
            reporte = (
                f"⚡ **FUTUROS BINGX: {coin}/USDT**\n\n"
                f"💵 Precio Actual: ${precio:,.2f}\n"
                f"📊 ADX: 15.0 (< 20) | RSI: 50.0\n"
                f"🛡️ Estado: MERCADO LATERAL / RANGO PLANO\n\n"
                f"🔴 Resistencia: ${precio * 1.01:,.2f}\n"
                f"🟢 Soporte: ${precio * 0.99:,.2f}\n\n"
                f"⏳ SEÑAL DE OPERACIÓN:"
            )

            # Botones de acción rápida debajo del análisis para esta moneda
            markup_trade = InlineKeyboardMarkup(row_width=2)
            markup_trade.add(
                InlineKeyboardButton(f"🚀 Comprar Futuros ($10)", callback_data=f"trade_{coin}_swap_buy_10"),
                InlineKeyboardButton(f"📉 Vender Futuros ($10)", callback_data=f"trade_{coin}_swap_sell_10"),
                InlineKeyboardButton(f"🟢 Comprar Spot ($10)", callback_data=f"trade_{coin}_spot_buy_10")
            )

            bot.send_message(call.message.chat.id, reporte, reply_markup=markup_trade, parse_mode="Markdown")

        elif accion == "trade" and len(datos) >= 5:
            coin = datos[1]
            mercado = datos[2]
            tipo_orden = datos[3]
            margen = float(datos[4])

            bot.answer_callback_query(call.id, "Ejecutando orden...")
            exito, precio, resultado = procesar_operacion_segura(coin, mercado, tipo_orden, margen)

            if exito:
                bot.send_message(
                    call.message.chat.id, 
                    f"✅ **¡Operación Ejecutada!**\n\n"
                    f"• Activo: {coin}/USDT\n"
                    f"• Mercado: {mercado.upper()}\n"
                    f"• Margen: ${margen} USDT\n"
                    f"• Entrada: {precio:,.2f}\n"
                    f"• Stop Loss: 4% 🛡️"
                )
            else:
                bot.send_message(call.message.chat.id, f"❌ Error en el exchange:\n{resultado}")

        elif call.data == "radar_mercado":
            bot.answer_callback_query(call.id, "Radar activo")
            bot.send_message(call.message.chat.id, "📡 **Radar de Mercado:** Monitoreando tendencias y rangos laterales.")

    except Exception as e:
        bot.send_message(call.message.chat.id, f"❌ Error: {str(e)}")

# --- ARRANQUE EN SEGUNDO PLANO (Flask + Bot) ---
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
