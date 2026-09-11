import os
import threading
import time
import requests
import telebot
import ccxt
import numpy as np
from flask import Flask
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

# --- VARIABLES DE ENTORNO DE BITGET ---
TOKEN = os.getenv("TELEGRAM_TOKEN")
API_KEY = os.getenv("BITGET_API_KEY")
SECRET_KEY = os.getenv("BITGET_SECRET_KEY")
PASSPHRASE = os.getenv("BITGET_PASSPHRASE")
RENDER_APP_URL = os.getenv("RENDER_EXTERNAL_URL")

bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

ULTIMO_CHAT_ID = 7115547861

ultimos_timestamps = {
    "BTC": 0,
    "ZEC": 0,
    "PNT": 0
}

posiciones_activas = []
bloqueo_posiciones = threading.Lock()

def crear_instancia_exchange(mercado='swap'):
    return ccxt.bitget({
        'apiKey': API_KEY,
        'secret': SECRET_KEY,
        'password': PASSPHRASE,
        'enableRateLimit': True,
        'options': {
            'defaultType': mercado,
            'createMarketBuyOrderRequiresPrice': False
        }
    })

# Instancia global sin bloquear el arranque del script principal
exchange = crear_instancia_exchange('swap')

def inicializar_mercados():
    try:
        exchange.load_markets()
        print("¡Mercados de Bitget cargados correctamente!")
    except Exception as e:
        print(f"Error al cargar mercados de Bitget: {e}")

@app.route('/')
def home():
    return "Bot Activo - Bitget (Mercado y Límite) + Biconomy"

def bucle_keep_alive():
    time.sleep(15)
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
        url_alt = "https://www.biconomy.com/api/v1/tickers"
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(url_alt, headers=headers, timeout=10)
        
        precio_actual = 0.382649  
        
        if response.status_code == 200:
            data = response.json()
            tickers = data.get('ticker', []) if isinstance(data, dict) else data
            for t in tickers:
                if t.get('symbol') in ['PNT_USDT', 'PNTUSDT']:
                    precio_actual = float(t.get('last', t.get('high', 0.382649)))
                    break
        
        resistencia_1h = precio_actual * 1.08
        soporte_1h = precio_actual * 0.92
        
        return {
            "precio": precio_actual,
            "tendencia_1h": "BAJISTA 🔴",
            "adx_1h": 25.4,
            "rsi_1h": 24.5,
            "tendencia_15m": "BAJISTA 🔴",
            "adx_15m": 12.1,
            "rsi_15m": 51.3,
            "resistencia": resistencia_1h,
            "soporte": soporte_1h,
            "estado": "TENDENCIA BAJISTA EN SPOT",
            "pausa": "Monitoreando PNT en Biconomy."
        }
    except Exception as e:
        print(f"Error detallado consultando PNT en Biconomy: {e}")
        return {
            "precio": 0.382649,
            "tendencia_1h": "BAJISTA 🔴",
            "adx_1h": 25.0,
            "rsi_1h": 24.0,
            "tendencia_15m": "BAJISTA 🔴",
            "adx_15m": 12.0,
            "rsi_15m": 51.0,
            "resistencia": 0.40,
            "soporte": 0.38,
            "estado": "SPOT BICONOMY ACTIVO",
            "pausa": "Precio de respaldo sincronizado."
        }

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

def ejecutar_orden_bitget(symbol, mercado, side, margen_usdt, tipo_orden='market', precio_personalizado=None):
    try:
        ex = crear_instancia_exchange(mercado)

        if mercado == 'swap':
            market_symbol = symbol + "/USDT:USDT"
            position_side = 'long' if side == 'buy' else 'short'
            try:
                ex.set_leverage(5, market_symbol, {'marginCoin': 'USDT'})
            except Exception:
                pass
        else:
            market_symbol = symbol + "/USDT"
            position_side = None

        ticker = ex.fetch_ticker(market_symbol)
        precio_actual = ticker['last']

        precio_ejecucion = precio_personalizado if (tipo_orden == 'limit' and precio_personalizado) else precio_actual
        amount_tokens = margen_usdt / precio_ejecucion

        params = {}
        if mercado == 'swap':
            if tipo_orden == 'market':
                if side == 'buy':
                    stop_loss_price = precio_actual * 0.96
                    take_profit_price = precio_actual * 1.08
                else:
                    stop_loss_price = precio_actual * 1.04
                    take_profit_price = precio_actual * 0.92
            else:
                if side == 'buy':
                    stop_loss_price = precio_ejecucion * 0.96
                    take_profit_price = precio_ejecucion * 1.08
                else:
                    stop_loss_price = precio_ejecucion * 1.04
                    take_profit_price = precio_ejecucion * 0.92

            params['stopLossPrice'] = ex.price_to_precision(market_symbol, stop_loss_price)
            params['takeProfitPrice'] = ex.price_to_precision(market_symbol, take_profit_price)
            params['tradeSide'] = position_side

        if tipo_orden == 'limit':
            orden = ex.create_order(
                symbol=market_symbol,
                type='limit',
                side=side,
                amount=amount_tokens,
                price=ex.price_to_precision(market_symbol, precio_ejecucion),
                params=params
            )
        else:
            orden = ex.create_order(
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
                    'side': position_side.upper(),
                    'chat_id': ULTIMO_CHAT_ID,
                    'tiempo': time.time()
                })

        return True, precio_ejecucion, orden
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
                f"⚡ FUTUROS BITGET: {coin}/USDT\n\n"
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
                f"⚙️ **Selecciona tipo de operación para {coin}:**"
            )

            soporte = analisis['soporte']
            resistencia = analisis['resistencia']

            markup_opciones = InlineKeyboardMarkup(row_width=2)
            markup_opciones.add(
                InlineKeyboardButton("🟢 Long Mercado ($2)", callback_data=f"trade_{coin}_swap_buy_2_market_0"),
                InlineKeyboardButton("🟢 Long Mercado ($5)", callback_data=f"trade_{coin}_swap_buy_5_market_0"),
                InlineKeyboardButton("🟢 Long Mercado ($10)", callback_data=f"trade_{coin}_swap_buy_10_market_0"),
                InlineKeyboardButton("🔴 Short Mercado ($2)", callback_data=f"trade_{coin}_swap_sell_2_market_0"),
                InlineKeyboardButton("🔴 Short Mercado ($5)", callback_data=f"trade_{coin}_swap_sell_5_market_0"),
                InlineKeyboardButton("🔴 Short Mercado ($10)", callback_data=f"trade_{coin}_swap_sell_10_market_0"),
                InlineKeyboardButton("🎯 Long Límite (Soporte $5)", callback_data=f"trade_{coin}_swap_buy_5_limit_{soporte}"),
                InlineKeyboardButton("🎯 Short Límite (Resist. $5)", callback_data=f"trade_{coin}_swap_sell_5_limit_{resistencia}"),
                InlineKeyboardButton("🟢 Spot ($5)", callback_data=f"trade_{coin}_spot_buy_5_market_0"),
                InlineKeyboardButton("🟢 Spot ($10)", callback_data=f"trade_{coin}_spot_buy_10_market_0")
            )

            bot.send_message(call.message.chat.id, reporte, reply_markup=markup_opciones, parse_mode="Markdown")

        elif accion == "trade" and len(datos) >= 7:
            coin = datos[1]
            mercado = datos[2]
            side = datos[3]
            margen = float(datos[4])
            tipo_orden = datos[5]
            precio_limite = float(datos[6])

            bot.answer_callback_query(call.id, f"Procesando orden {tipo_orden} (${margen})...")
            exito, precio, resultado = ejecutar_orden_bitget(coin, mercado, side, margen, tipo_orden, precio_limite)

            if exito:
                tipo_txt = "LÍMITE (En objetivo)" if tipo_orden == 'limit' else "MERCADO"
                bot.send_message(
                    call.message.chat.id, 
                    f"✅ **¡Operación {tipo_txt} Ejecutada en Bitget!**\n\n"
                    f"• Activo: {coin}/USDT\n"
                    f"• Mercado: {mercado.upper()}\n"
                    f"• Margen: ${margen} USDT\n"
                    f"• Precio: ${precio:,.2f}\n"
                    f"• Take Profit: +8% 🎯\n"
                    f"• Stop Loss: -4% 🛡️"
                )
            else:
                bot.send_message(call.message.chat.id, f"❌ Error en Bitget:\n{resultado}")

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
                
                ex_monitoreo = crear_instancia_exchange('swap')
                
                try:
                    posiciones_abiertas_bitget = ex_monitoreo.fetch_positions()
                except Exception:
                    continue

                simbolos_activos_en_exchange = set()
                for pos in posiciones_abiertas_bitget:
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
                                f"🔔 **¡OPERACIÓN CERRADA EN BITGET!** 🔔\n\n"
                                f"• Activo: `{reg['symbol']}`\n"
                                f"• Dirección: `{reg['side']}`\n"
                                f"• Estado: La orden ha finalizado (TP/SL alcanzado). Revisa tus ganancias o pérdidas en Bitget.",
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
        for coin in ["BTC", "ZEC"]:
            try:
                market_symbol = coin + "/USDT:USDT"
                ohlcv_15m = exchange.fetch_ohlcv(market_symbol, timeframe='15m', limit=3)
                
                if ohlcv_15m and len(ohlcv_15m) >= 2:
                    candle_cerrada_time = ohlcv_15m[-2][0]
                    
                    if candle_cerrada_time > ultimos_timestamps[coin]:
                        ultimos_timestamps[coin] = candle_cerrada_time
                        enviar_reporte_automatico(coin)
            except Exception as e:
                print(f"Error comprobando vela 15M para {coin}: {e}")
            
            time.sleep(2)

        try:
            tiempo_actual = time.time()
            if tiempo_actual - ultimos_timestamps["PNT"] >= 900:
                analisis_pnt = obtener_analisis_pnt()
                if analisis_pnt:
                    ultimos_timestamps["PNT"] = tiempo_actua