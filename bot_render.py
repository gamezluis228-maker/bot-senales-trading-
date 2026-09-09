import os
import threading
import time
import requests
import telebot
import ccxt
import numpy as np
from flask import Flask
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

# --- VARIABLES DE ENTORNO EN RENDER ---
TOKEN = os.getenv("TELEGRAM_TOKEN")
API_KEY = os.getenv("BINGX_API_KEY")
SECRET_KEY = os.getenv("BINGX_SECRET_KEY")
RENDER_APP_URL = os.getenv("RENDER_EXTERNAL_URL")

bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

# ID de Telegram configurado fijo
ULTIMO_CHAT_ID = 7115547861

# Diccionario para controlar el último timestamp por moneda
ultimos_timestamps = {
    "BTC": 0,
    "ZEC": 0,
    "PNT": 0
}

# Lista para registrar las operaciones activas y monitorear su cierre
posiciones_activas = []
bloqueo_posiciones = threading.Lock()

# Configuración base del cliente CCXT
exchange = ccxt.bingx({
    'apiKey': API_KEY,
    'secret': SECRET_KEY,
    'enableRateLimit': True,
    'options': {'defaultType': 'swap'}
})

try:
    exchange.load_markets()
    print("¡Mercados de BingX cargados correctamente!")
except Exception as e:
    print(f"Error al cargar mercados de BingX: {e}")

@app.route('/')
def home():
    return "Bot Activo - Multitemporal 1H y 15M con Alertas de Cierre"

def bucle_keep_alive():
    """Hace una petición a la propia app en Render para no entrar en suspensión (Sleep)"""
    time.sleep(10)
    while True:
        try:
            url = RENDER_APP_URL if RENDER_APP_URL else "http://127.0.0.1:5000/"
            requests.get(url, timeout=10)
            print("Keep-Alive: Ping enviado con éxito a la aplicación.")
        except Exception as e:
            print(f"Error en Keep-Alive: {e}")
        time.sleep(600)

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
        print(f"Error detallado en obtener_analisis_tecnico para {symbol}: {e}")
        return {
            "precio": 0.0,
            "tendencia_1h": "ERROR",
            "adx_1h": 0.0,
            "rsi_1h": 0.0,
            "tendencia_15m": "ERROR",
            "adx_15m": 0.0,
            "rsi_15m": 0.0,
            "resistencia": 0.0,
            "soporte": 0.0,
            "estado": "FALLA EN EXCHANGE",
            "pausa": str(e)
        }

def obtener_analisis_pnt():
    try:
        url_1h = "https://api.biconomy.com/api/v1/klines?symbol=PNT_USDT&type=1h&size=30"
        res_1h = requests.get(url_1h, timeout=10).json()
        data_1h = res_1h.get('data', [])
        
        closes_1h = [float(x[4]) for x in data_1h]
        highs_1h = [float(x[2]) for x in data_1h]
        lows_1h = [float(x[3]) for x in data_1h]
        
        precio_actual = closes_1h[-1]
        rsi_1h = calcular_rsi(closes_1h)
        adx_1h = calcular_adx(highs_1h, lows_1h, closes_1h)
        resistencia_1h = max(highs_1h[-10:])
        soporte_1h = min(lows_1h[-10:])
        tendencia_1h = "ALCISTA 🟢" if closes_1h[-1] > closes_1h[-10] else "BAJISTA 🔴"

        url_15m = "https://api.biconomy.com/api/v1/klines?symbol=PNT_USDT&type=15m&size=30"
        res_15m = requests.get(url_15m, timeout=10).json()
        data_15m = res_15m.get('data', [])
        
        closes_15m = [float(x[4]) for x in data_15m]
        highs_15m = [float(x[2]) for x in data_15m]
        lows_15m = [float(x[3]) for x in data_15m]
        
        rsi_15m = calcular_rsi(closes_15m)
        adx_15m = calcular_adx(highs_15m, lows_15m, closes_15m)
        tendencia_15m = "ALCISTA 🟢" if closes_15m[-1] > closes_15m[-10] else "BAJISTA 🔴"

        if adx_15m > 20:
            estado_mercado = "TENDENCIA ACTIVA EN 15M"
            pausa_bot = "Estructura de 15m con fuerza tendencial."
        else:
            estado_mercado = "MERCADO LATERAL / RANGO EN 15M (ADX < 20)"
            pausa_bot = "Precaución: Rango plano en corto plazo."

        last_time = int(data_15m[-2][0]) if len(data_15m) >= 2 else 0

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
            "pausa": pausa_bot,
            "timestamp_15m": last_time
        }
    except Exception as e:
        print(f"Error consultando Biconomy para PNT: {e}")
        return None

@bot.message_handler(commands=['pnt', 'ptn'])
def comando_pnt(message):
    global ULTIMO_CHAT_ID
    ULTIMO_CHAT_ID = message.chat.id
    
    bot.send_chat_action(message.chat.id, 'typing')
    analisis = obtener_analisis_pnt()
    
    if analisis:
        reporte = (
            f"⚡ **SPOT BICONOMY: PNT/USDT**\n\n"
            f"💵 **Precio Actual:** ${analisis['precio']:.6f}\n\n"
            f"📊 **ANÁLISIS MACRO (1H):**\n"
            f"• Tendencia: {analisis['tendencia_1h']}\n"
            f"• ADX: {analisis['adx_1h']} | RSI: {analisis['rsi_1h']}\n\n"
            f"📈 **ESTRUCTURA CORTO PLAZO (15M):**\n"
            f"• Tendencia: {analisis['tendencia_15m']}\n"
            f"• ADX: {analisis['adx_15m']} | RSI: {analisis['rsi_15m']}\n\n"
            f"🧱 **Resistencia:** ${analisis['resistencia']:.6f}\n"
            f"🟡 **Soporte:** ${analisis['soporte']:.6f}\n\n"
            f"🎯 **SEÑAL:**\n"
            f"⏳ **{analisis['estado']}**\n"
            f"• {analisis['pausa']}"
        )
        bot.send_message(message.chat.id, reporte, parse_mode="Markdown")
    else:
        bot.send_message(message.chat.id, "❌ Error al obtener datos de PNT desde Biconomy.")

def enviar_reporte_pnt_automatico(analisis):
    try:
        reporte = (
            f"🔔 **REPORTE AUTOMÁTICO CIERRE 15M / 1H** 🔔\n"
            f"⚡ **SPOT BICONOMY: PNT/USDT**\n\n"
            f"💵 **Precio Actual:** ${analisis['precio']:.6f}\n\n"
            f"📊 **ANÁLISIS MACRO (1H):**\n"
            f"• Tendencia: {analisis['tendencia_1h']}\n"
            f"• ADX: {analisis['adx_1h']} | RSI: {analisis['rsi_1h']}\n\n"
            f"📈 **ESTRUCTURA CORTO PLAZO (15M):**\n"
            f"• Tendencia: {analisis['tendencia_15m']}\n"
            f"• ADX: {analisis['adx_15m']} | RSI: {analisis['rsi_15m']}\n\n"
            f"🧱 **Resistencia:** ${analisis['resistencia']:.6f}\n"
            f"🟡 **Soporte:** ${analisis['soporte']:.6f}\n\n"
            f"🎯 **SEÑAL:**\n"
            f"⏳ **{analisis['estado']}**\n"
            f"• {analisis['pausa']}"
        )
        if ULTIMO_CHAT_ID:
            bot.send_message(ULTIMO_CHAT_ID, reporte, parse_mode="Markdown")
    except Exception as e:
        print(f"No se pudo enviar la alerta automática de PNT: {e}")

@bot.message_handler(commands=['start', 'menu'])
def mostrar_menu_principal(message):
    global ULTIMO_CHAT_ID
    ULTIMO_CHAT_ID = message.chat.id

    markup = InlineKeyboardMarkup(row_width=2)
    monedas = ["BTC", "ETH", "XRP", "ZEC"]
    
    botones = [InlineKeyboardButton(coin, callback_data=f"analisis_{coin}") for coin in monedas]
    markup.add(*botones)
    markup.add(InlineKeyboardButton("📡 Radar Mercado", callback_data="radar_mercado"))

    bot.send_message(
        message.chat.id, 
        "CRYPTO ANÁLISIS MULTITEMPORAL 🟢\n\n🤖 Selecciona una criptomoneda para ver 1H y 15M:\n*(Alertas automáticas de 15m para BTC, ZEC y PNT activas)*\n\n💡 Usa /pnt para ver el análisis de PNT (Biconomy)", 
        reply_markup=markup
    )

def ejecutar_orden_bingx(symbol, mercado, side, margen_usdt):
    try:
        exchange.apiKey = os.getenv("BINGX_API_KEY")
        exchange.secret = os.getenv("BINGX_SECRET_KEY")

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

        if mercado == 'swap':
            with bloqueo_posiciones:
                posiciones_activas.append({
                    'symbol': market_symbol,
                    'side': position_side,
                    'chat_id': ULTIMO_CHAT_ID,
                    'tiempo': time.time()
                })

        return True, precio_actual, orden
    except Exception as e:
        return False, 0, str(e)

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
                InlineKeyboardButton("🟢 Abrir Long ($2)", callback_data=f"trade_{coin}_swap_buy_2"),
                InlineKeyboardButton("🟢 Abrir Long ($5)", callback_data=f"trade_{coin}_swap_buy_5"),
                InlineKeyboardButton("🟢 Abrir Long ($10)", callback_data=f"trade_{coin}_swap_buy_10"),
                InlineKeyboardButton("🔴 Abrir Short ($2)", callback_data=f"trade_{coin}_swap_sell_2"),
                InlineKeyboardButton("🔴 Abrir Short ($5)", callback_data=f"trade_{coin}_swap_sell_5"),
                InlineKeyboardButton("🔴 Abrir Short ($10)", callback_data=f"trade_{coin}_swap_sell_10"),
                InlineKeyboardButton("🟢 Spot ($5)", callback_data=f"trade_{coin}_spot_buy_5"),
                InlineKeyboardButton("🟢 Spot ($10)", callback_data=f"trade_{coin}_spot_buy_10")
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

def bucle_monitoreo_posiciones():
    while True:
        try:
            time.sleep(15)
            with bloqueo_posiciones:
                if not posiciones_activas:
                    continue
                
                exchange.apiKey = os.getenv("BINGX_API_KEY")
                exchange.secret = os.getenv("BINGX_SECRET_KEY")
                exchange.options['defaultType'] = 'swap'
                
                try:
                    posiciones_abiertas_bingx = exchange.fetch_positions()
                except Exception:
                    continue

                simbolos_activos_en_exchange = set()
                for pos in posiciones_abiertas_bingx:
                    if float(pos.get('contracts', 0)) > 0:
                        simbolos_activos_en_exchange.add((pos['symbol'], pos.get('side', '').upper()))

                nuevas_activas = []
                for reg in posiciones_activas:
                    clave = (reg['symbol'], reg['side'])
                    if clave in simbolos_activos_en_exchange:
                        nuevas_activas.append(reg)
                    else:
                        try:
                            bot.send_message(
                                reg['chat_id'],
                                f"🔔 **¡OPERACIÓN CERRADA EN BINGX!** 🔔\n\n"
                                f"• Activo: `{reg['symbol']}`\n"
                                f"• Dirección: `{reg['side']}`\n"
                                f"• Estado: La orden ha tocado su objetivo (Take Profit +8% o Stop Loss -4%). Revisa tu balance.",
                                parse_mode="Markdown"
                            )
                        except Exception as ex:
                            print(f"Error enviando alerta de cierre: {ex}")
                
                posiciones_activas[:] = nuevas_activas

        except Exception as e:
            print(f"Error en bucle_monitoreo_posiciones: {e}")

def bucle_alertas_15m():
    global ultimos_timestamps
    time.sleep(5)
    
    while True:
        # 1. Alertas para BingX (BTC y ZEC)
        for coin in ["BTC", "ZEC"]:
            try:
                market_symbol = f"{coin}/USDT:USDT"
                ohlcv_15m = exchange.fetch_ohlcv(market_symbol, timeframe='15m', limit=3)
                
                if ohlcv_15m and len(ohlcv_15m) >= 2:
                    candle_cerrada_time = ohlcv_15m[-2][0]
                    
                    if candle_cerrada_time > ultimos_timestamps[coin]:
                        ultimos_timestamps[coin] = candle_cerrada_time
                        enviar_reporte_automatico(coin)
            except Exception as e:
                print(f"Error comprobando vela 15M para {coin}: {e}")
            
            time.sleep(2)

        # 2. Alerta independiente para PNT (Biconomy)
        try:
            analisis_pnt = obtener_analisis_pnt()
            if analisis_pnt and analisis_pnt.get("timestamp_15m"):
                ts_pnt = analisis_pnt["timestamp_15m"]
                if ts_pnt > ultimos_timestamps["PNT"]:
                    ultimos_timestamps["PNT"] = ts_pnt
                    enviar_reporte_pnt_automatico(analisis_pnt)
        except Exception as e:
            print(f"Error comprobando vela 15M para PNT: {e}")

        time.sleep(30)

def enviar_reporte_automatico(coin):
    try:
        analisis = obtener_analisis_tecnico(coin)
        reporte = (
            f"🔔 **REPORTE AUTOMÁTICO CIERRE 15M / 1H** 🔔\n"
            f"⚡ Activo: {coin}/USDT\n\n"
            f"💵 Precio Actual: ${analisis['precio']:,.2f}\n\n"
            f"📊 **MACRO (1H):** {analisis['tendencia_1h']} | ADX: {analisis['adx_1h']} | RSI: {analisis['rsi_1h']}\n"
            f"📈 **CORTO PLA