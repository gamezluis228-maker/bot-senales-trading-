import os
import threading
import time
import telebot
import ccxt
import numpy as np
from flask import Flask
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

TOKEN = os.getenv("TELEGRAM_TOKEN")

# --- TUS CREDENCIALES DE BINGX INTEGRADAS ---
API_KEY = "2qLQDoat8RrAZWuwiY5O9jFeRNvT3hEQLA0wTP7O0kR1XQe7mcRkPDlkOUFSmFvKtVUKA3aWEgd2OkLm0g"
SECRET_KEY = "9szXjstK16f4HCp0Wd1TxuCtEJVRtwPmyndSFAs0mOKY8b84Qf5OjSmCM6sgNngef5DiFEV3nlWmBpfg"

bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

# ID de Telegram configurado de forma fija
ULTIMO_CHAT_ID = 7115547861
ultimo_timestamp_btc = 0
ultimo_timestamp_zec = 0

exchange = ccxt.bingx({
    'apiKey': API_KEY,
    'secret': SECRET_KEY,
    'enableRateLimit': True,
    'options': {'defaultType': 'swap'}
})

@app.route('/')
def home():
    return "Bot Activo - Multitemporal 1H y 15M"

# --- FUNCIONES DE CÁLCULO TÉCNICO REAL ---
def calcular_rsi(closes, period=14):
    if len(closes) < period + 1:
        return 50.0
    deltas = np.diff(closes)
    seed = deltas[:period+1]
    up = seed[seed >= 0].sum() / period
    down = -seed[seed < 0].sum() / period
    if down == 0:
        return 100.0
    rs = up / down
    rsi = 100 - (100 / (1 + rs))
    return float(rsi)

def calcular_adx(highs, lows, closes, period=14):
    if len(closes) < period + 1:
        return 15.0
    highs = np.array(highs)
    lows = np.array(lows)
    closes = np.array(closes)
    
    tr1 = highs[1:] - lows[1:]
    tr2 = np.abs(highs[1:] - closes[:-1])
    tr3 = np.abs(lows[1:] - closes[:-1])
    tr = np.max(np.array([tr1, tr2, tr3]), axis=0)
    
    atr = np.mean(tr[-period:])
    delta_high = np.diff(highs)
    delta_low = -np.diff(lows)
    
    plus_dm = np.where((delta_high > delta_low) & (delta_high > 0), delta_high, 0.0)
    minus_dm = np.where((delta_low > delta_high) & (delta_low > 0), delta_low, 0.0)
    
    plus_di = 100 * np.mean(plus_dm[-period:]) / (atr if atr != 0 else 1)
    minus_di = 100 * np.mean(minus_dm[-period:]) / (atr if atr != 0 else 1)
    
    dx = 100 * np.abs(plus_di - minus_di) / ((plus_di + minus_di) if (plus_di + minus_di) != 0 else 1)
    return float(dx)

def obtener_analisis_tecnico(symbol):
    try:
        market_symbol = f"{symbol}/USDT:USDT"
        
        # 1. Macro 1H
        ohlcv_1h = exchange.fetch_ohlcv(market_symbol, timeframe='1h', limit=30)
        closes_1h = [x[4] for x in ohlcv_1h]
        highs_1h = [x[2] for x in ohlcv_1h]
        lows_1h = [x[3] for x in ohlcv_1h]
        
        precio_actual = closes_1h[-1]
        rsi_1h = calcular_rsi(closes_1h)
        adx_1h = calcular_adx(highs_1h, lows_1h, closes_1h)
        resistencia_1h = max(highs_1h[-10:])
        soporte_1h = min(lows_1h[-10:])
        tendencia_1h = "ALCISTA 🟢" if closes_1h[-1] > closes_1h[-10] else "BAJISTA 🔴"

        # 2. Corto Plazo 15M
        ohlcv_15m = exchange.fetch_ohlcv(market_symbol, timeframe='15m', limit=30)
        closes_15m = [x[4] for x in ohlcv_15m]
        highs_15m = [x[2] for x in ohlcv_15m]
        lows_15m = [x[3] for x in ohlcv_15m]
        
        rsi_15m = calcular_rsi(closes_15m)
        adx_15m = calcular_adx(highs_15m, lows_15m, closes_15m)
        tendencia_15m = "ALCISTA 🟢" if closes_15m[-1] > closes_15m[-10] else "BAJISTA 🔴"

        if adx_15m > 20:
            estado_mercado = "TENDENCIA ACTIVA EN 15M"
            pausa_bot = "Estructura de 15m con fuerza tendencial."
        else:
            estado_mercado = "MERCADO LATERAL / RANGO EN 15M (ADX < 20)"
            pausa_bot = "Precaución: Rango plano en corto plazo."

        return {
            "precio": precio_actual,
            "tendencia_1h": tendencia_1h,
            "adx_1h": round(adx_1h, 1),
            "rsi_1h": round(rsi_1h, 1),
            "tendencia_15m": tendencia_15m,
            "adx_15m": round(adx_15m, 1),
            "rsi_15m": round(rsi_15m, 1),
            "resistencia": resistencia_1h,
            "soporte": soporte_1h,
            "estado": estado_mercado,
            "pausa": pausa_bot
        }
    except Exception as e:
        print(f"Error en obtener_analisis_tecnico para {symbol}: {e}")
        return {
            "precio": 1000.0,
            "tendencia_1h": "NEUTRAL",
            "adx_1h": 14.0,
            "rsi_1h": 50.0,
            "tendencia_15m": "NEUTRAL",
            "adx_15m": 14.0,
            "rsi_15m": 50.0,
            "resistencia": 1050.0,
            "soporte": 950.0,
            "estado": "MERCADO LATERAL",
            "pausa": "Error al consultar temporalidades."
        }

# --- 1. MENÚ PRINCIPAL ---
@bot.message_handler(commands=['start', 'menu'])
def mostrar_menu_principal(message):
    global ULTIMO_CHAT_ID
    ULTIMO_CHAT_ID = message.chat.id
    print(f"Comando /start recibido de el chat ID: {message.chat.id}")

    markup = InlineKeyboardMarkup(row_width=3)
    monedas = ["BTC", "ETH", "SOL", "XRP", "DOGE", "ADA", "AVAX", "LINK", "DOT", "NEAR", "MATIC", "UNI", "LTC", "ATOM", "ZEC"]
    
    botones = [InlineKeyboardButton(coin, callback_data=f"analisis_{coin}") for coin in monedas]
    markup.add(*botones)
    markup.add(InlineKeyboardButton("📡 Radar Mercado", callback_data="radar_mercado"))

    bot.send_message(
        message.chat.id, 
        "CRYPTO ANÁLISIS MULTITEMPORAL 🟢\n\n🤖 Selecciona una criptomoneda para ver 1H y 15M:\n*(Alertas automáticas de 15m para BTC y ZEC activas)*", 
        reply_markup=markup
    )

# --- 2. MOTOR DE EJECUCIÓN CON TP (8%) Y SL (4%) EN BINGX ---
def ejecutar_orden_bingx(symbol, mercado, side, margen_usdt):
    try:
        if mercado == 'swap':
            market_symbol = f"{symbol}/USDT:USDT"
            exchange.options['defaultType'] = 'swap'
            
            position_side = 'LONG' if side == 'buy' else 'SHORT'
            try:
                exchange.set_leverage(5, market_symbol, {'side': position_side, 'marginCoin': 'USDT'})
            except:
                pass
        else:
            market_symbol = f"{symbol}/USDT"
            exchange.options['defaultType'] = 'spot'
            position_side = None

        ticker = exchange.fetch_ticker(market_symbol)
        precio_actual = ticker['last']
        amount_tokens = margen_usdt / precio_actual

        params = {}
        if mercado == 'swap':
            if side == 'buy':
                stop_loss_price = precio_actual * (1 - 0.04)
                take_profit_price = precio_actual * (1 + 0.08)
            else:
                stop_loss_price = precio_actual * (1 + 0.04)
                take_profit_price = precio_actual * (1 - 0.08)
            
            params['stopLossPrice'] = exchange.price_to_precision(market_symbol, stop_loss_price)
            params['takeProfitPrice'] = exchange.price_to_precision(market_symbol, take_profit_price)
            params['positionSide'] = position_side

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

# --- 3. MANEJADOR DE CALLBACKS ---
@bot.callback_query_handler(func=lambda call: True)
def callback_query(call):
    global ULTIMO_CHAT_ID
    ULTIMO_CHAT_ID = call.message.chat.id

    try:
        datos = call.data.split("_")
        if not datos:
            return

        accion = datos[0]

        if accion == "analisis" and len(datos) >= 2:
            coin = datos[1]
            bot.answer_callback_query(call.id, f"Calculando temporalidades para {coin}...")
            
            analisis = obtener_analisis_tecnico(coin)

            reporte = (
                f"⚡ FUTUROS BINGX: {coin}/USDT\n\n"
                f"💵 Precio Actual: ${analisis['precio']:,.2f}\n\n"
                f"📊 **ANÁLISIS MACRO (1H):**\n"
                f"• Tendencia: {analisis['tendencia_1h']}\n"
                f"• ADX: {analisis['adx_1h']} | RSI: {analisis['rsi_1h']}\n\n"
                f"📈 **ESTRUCTURA CORTO PLAZO (15M):**\n"
                f"• Tendencia: {analisis['tendencia_15m']}\n"
                f"• ADX: {analisis['adx_15m']} | RSI: {analisis['rsi_15m']}\n\n"
                f"🧱 Resistencia: ${analisis['resistencia']:,.2f}\n"
                f"🟡 Soporte: ${analisis['soporte']:,.2f}\n\n"
                f"🎯 SEÑAL:\n"
                f"⏳ {analisis['estado']}\n"
                f"• {analisis['pausa']}\n\n"
                f"⚙️ **Selecciona margen y tipo de operación para {coin}:**"
            )

            markup_opciones = InlineKeyboardMarkup(row_width=2)
            markup_opciones.add(
                InlineKeyboardButton("🚀 Long ($5)", callback_data=f"trade_{coin}_swap_buy_5"),
                InlineKeyboardButton("🚀 Long ($10)", callback_data=f"trade_{coin}_swap_buy_10"),
                InlineKeyboardButton("📉 Short ($5)", callback_data=f"trade_{coin}_swap_sell_5"),
                InlineKeyboardButton("📉 Short ($10)", callback_data=f"trade_{coin}_swap_sell_10"),
                InlineKeyboardButton("🚀 Long ($15)", callback_data=f"trade_{coin}_swap_buy_15"),
                InlineKeyboardButton("🚀 Long ($20)", callback_data=f"trade_{coin}_swap_buy_20"),
                InlineKeyboardButton("📉 Short ($15)", callback_data=f"trade_{coin}_swap_sell_15"),
                InlineKeyboardButton("📉 Short ($20)", callback_data=f"trade_{coin}_swap_sell_20"),
                InlineKeyboardButton("🟢 Spot ($10)", callback_data=f"trade_{coin}_spot_buy_10"),
                InlineKeyboardButton("🟢 Spot ($20)", callback_data=f"trade_{coin}_spot_buy_20")
            )

            bot.send_message(call.message.chat.id, reporte, reply_markup=markup_opciones, parse_mode="Markdown")

        elif accion == "trade" and len(datos) >= 5:
            coin = datos[1]
            mercado = datos[2]
            side = datos[3]
            margen = float(datos[4])

            bot.answer_callback_query(call.id, f"Procesando ${margen} USDT...")
            exito, precio, resultado = ejecutar_orden_bingx(coin, mercado, side, margen)

            if exito:
                bot.send_message(
                    call.message.chat.id, 
                    f"✅ **¡Operación Ejecutada con Éxito!**\n\n"
                    f"• Activo: {coin}/USDT\n"
                    f"• Mercado: {mercado.upper()}\n"
                    f"• Margen: ${margen} USDT\n"
                    f"• Entrada: ${precio:,.2f}\n"
                    f"• Take Profit: +8% 🎯\n"
                    f"• Stop Loss: -4% 🛡️"
                )
            else:
                bot.send_message(call.message.chat.id, f"❌ Error en BingX:\n{resultado}")

        elif call.data == "radar_mercado":
            bot.answer_callback_query(call.id, "Radar activo")
            bot.send_message(call.message.chat.id, "📡 **Radar de Mercado:** Filtro multitemporal activo.")

    except Exception as e:
        bot.send_message(call.message.chat.id, f"❌ Error crítico: {str(e)}")

# --- 4. HILO DE ALERTAS CADA 15 MIN ---
def bucle_alertas_15m():
    global ultimo_timestamp_btc, ultimo_timestamp_zec
    while True:
        try:
            for coin in ["BTC", "ZEC"]:
                market_symbol = f"{coin}/USDT:USDT"
                ohlcv_15m = exchange.fetch_ohlcv(market_symbol, timeframe='15m', limit=5)
                if ohlcv_15m and len(ohlcv_15m) >= 2:
                    candle_cerrada_time = ohlcv_15m[-2][0]
                    
                    if coin == "BTC" and candle_cerrada_time != ultimo_timestamp_btc:
                        print(f"¡Disparando alerta 15m para BTC!")
                        ultimo_timestamp_btc = candle_cerrada_time
                        enviar_reporte_automatico(coin)
                    elif coin == "ZEC" and candle_cerrada_time != ultimo_timestamp_zec:
                        print(f"¡Disparando alerta 15m para ZEC!")
                        ultimo_timestamp_zec = candle_cerrada_time
                        enviar_reporte_automatico(coin)
        except Exception as e:
            print(f"Error crítico en bucle_alertas_15m: {e}")
        
        time.sleep(30)

def enviar_reporte_automatico(coin):
    try:
        analisis = obtener_analisis_tecnico(coin)
        reporte = (
            f"🔔 **REPORTE AUTOMÁTICO 15M / 1H** 🔔\n"
            f"⚡ Activo: {coin}/USDT\n\n"
            f"💵 Precio Actual: ${analisis['precio']:,.2f}\n\n"
            f"📊 **MACRO (1H):** {analisis['tendencia_1h']} | ADX: {analisis['adx_1h']} | RSI: {analisis['rsi_1h']}\n"
            f"📈 **CORTO PLAZO (15M):** {analisis['tendencia_15m']} | ADX: {analisis['adx_15m']} | RSI: {analisis['rsi_15m']}\n\n"
            f"🧱 Resistencia: ${analisis['resistencia']:,.2f}\n"
            f"🟡 Soporte: ${analisis['soporte']:,.2f}\n\n"
            f"⏳ Estado: {analisis['estado']}\n"
            f"• {analisis['pausa']}"
        )
        bot.send_message(ULTIMO_CHAT_ID, reporte, parse_mode="Markdown")
    except Exception as e:
        print(f"No se pudo enviar la alerta de {coin}: {e}")

# --- 5. ARRANQUE ---
def arrancar_bot_telegram():
    while True:
        try:
            bot.remove_webhook()
            print("Iniciando polling de Telegram...")
            bot.infinity_polling(skip_pending=True, timeout=60, long_polling_timeout=60)
        except Exception as e:
            print(f"Error crítico en polling de Telegram: {e}")
            time.sleep(10)

if __name__ == "__main__":
    hilo_bot = threading.Thread(target=arrancar_bot_telegram)
    hilo_bot.daemon = True
    hilo_bot.start()

    hilo_alertas = threading.Thread(target=bucle_alertas_15m)
    hilo_alertas.daemon = True
    hilo_alertas.start()

    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
