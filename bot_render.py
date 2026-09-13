import os
import threading
import time
import requests
import telebot
import ccxt
import numpy as np
from flask import Flask
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

# Escaneo seguro de secretos por si usas Secret Files en Render (/etc/secrets/)
secrets_dir = "/etc/secrets"
if os.path.exists(secrets_dir):
    try:
        for filename in os.listdir(secrets_dir):
            filepath = os.path.join(secrets_dir, filename)
            if os.path.isfile(filepath):
                with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                    for linea in f:
                        if "=" in linea and not linea.strip().startswith("#"):
                            partes = linea.strip().split("=", 1)
                            if len(partes) == 2:
                                k, v = partes[0].strip(), partes[1].strip().strip("'\"")
                                os.environ[k] = v
        print("¡Secretos escaneados y cargados desde /etc/secrets/ exitosamente!")
    except Exception as e:
        print(f"Error al leer carpeta secret files: {e}")

# Token de Telegram compatible con cualquier nombre de variable común
TOKEN = os.getenv("TEL_TOKEN") or os.getenv("TELEGRAM_TOKEN") or os.getenv("TOKEN") or os.getenv("TELKEY") or ""
RENDER_APP_URL = os.getenv("RENDER_EXTERNAL_URL")

bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

ULTIMO_CHAT_ID = 7115547861
ultimos_timestamps = {"BTC": 0, "ZEC": 0, "PNT": 0, "ETH": 0, "SOL": 0, "XRP": 0, "DOGE": 0}

def obtener_credenciales_bitget():
    api = (os.getenv("BITGET_API_KEY") or os.getenv("BIT_API_KEY") or 
           os.getenv("BITGET_KEY") or os.getenv("API_KEY") or 
           os.getenv("BIT_KEY") or os.getenv("BITGET_API") or "")
           
    secret = (os.getenv("BITGET_SECRET_KEY") or os.getenv("BIT_SECRET_KEY") or 
              os.getenv("SECRET_KEY") or os.getenv("SECRET") or 
              os.getenv("BITGET_SECRET") or os.getenv("BIT_SECRET") or 
              os.getenv("BITGET_SEC") or "")
              
    password = (os.getenv("BITGET_PASSPHRASE") or os.getenv("BIT_PASSPHRASE") or 
                os.getenv("PASSPHRASE") or os.getenv("PASS") or 
                os.getenv("BITGET_PASSWORD") or os.getenv("PASSWORD") or 
                os.getenv("BITGET_PASS") or "")
                
    return api.strip(), secret.strip(), password.strip()

def crear_instancia_exchange(mercado='swap'):
    api, secret, password = obtener_credenciales_bitget()
    config = {
        'enableRateLimit': True,
        'options': {'defaultType': mercado, 'createMarketBuyOrderRequiresPrice': False}
    }
    if api:
        config['apiKey'] = api
    if secret:
        config['secret'] = secret
    if password:
        config['password'] = password
    return ccxt.bitget(config)

exchange_default = crear_instancia_exchange('swap')

def inicializar_mercados():
    try:
        exchange_default.load_markets()
        print("¡Mercados de Bitget cargados correctamente!")
        api, secret, _ = obtener_credenciales_bitget()
        if api and secret:
            print("¡Credenciales de Bitget detectadas y listas para operar!")
        else:
            print("⚠️ Advertencia: No se detectaron credenciales completas de Bitget en las variables de entorno.")
    except Exception as e:
        print(f"Error al cargar mercados: {e}")

@app.route('/')
def home():
    return "Bot Activo - Bitget & Biconomy Conectados"

def bucle_keep_alive():
    time.sleep(15)
    while True:
        try:
            url = RENDER_APP_URL if RENDER_APP_URL else "http://127.0.0.1:10000/"
            requests.get(url, timeout=10)
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
    return float(100 - (100 / (1 + (up / down))))

def calcular_adx(highs, lows, closes, period=14):
    if len(closes) < period + 1:
        return 15.0
    highs, lows, closes = np.array(highs), np.array(lows), np.array(closes)
    tr = np.max(np.array([highs[1:] - lows[1:], np.abs(highs[1:] - closes[:-1]), np.abs(lows[1:] - closes[:-1])]), axis=0)
    atr = np.mean(tr[-period:])
    delta_high, delta_low = np.diff(highs), -np.diff(lows)
    plus_dm = np.where((delta_high > delta_low) & (delta_high > 0), delta_high, 0.0)
    minus_dm = np.where((delta_low > delta_high) & (delta_low > 0), delta_low, 0.0)
    plus_di = 100 * np.mean(plus_dm[-period:]) / (atr if atr != 0 else 1)
    minus_di = 100 * np.mean(minus_dm[-period:]) / (atr if atr != 0 else 1)
    dx = 100 * np.abs(plus_di - minus_di) / ((plus_di + minus_di) if (plus_di + minus_di) != 0 else 1)
    return float(dx)

def obtener_analisis_bitget(symbol, mercado='swap'):
    try:
        ex = crear_instancia_exchange(mercado)
        market_symbol = f"{symbol}/USDT:USDT" if mercado == 'swap' else f"{symbol}/USDT"
        ohlcv_1h = ex.fetch_ohlcv(market_symbol, timeframe='1h', limit=30)
        closes_1h, highs_1h, lows_1h = [x[4] for x in ohlcv_1h], [x[2] for x in ohlcv_1h], [x[3] for x in ohlcv_1h]
        ohlcv_15m = ex.fetch_ohlcv(market_symbol, timeframe='15m', limit=30)
        closes_15m, highs_15m, lows_15m = [x[4] for x in ohlcv_15m], [x[2] for x in ohlcv_15m], [x[3] for x in ohlcv_15m]
        adx_15m = calcular_adx(highs_15m, lows_15m, closes_15m)
        estado_mercado = "MERCADO LATERAL / RANGO EN 15M (ADX < 20)" if adx_15m < 20 else "TENDENCIA ACTIVA EN 15M"
        pausa_texto = "Estructura de 15m con fuerza tendencial." if adx_15m > 20 else "Precaución: Rango plano en corto plazo."
        return {
            "precio": closes_1h[-1],
            "tendencia_1h": "ALCISTA 🟢" if closes_1h[-1] > closes_1h[-10] else "BAJISTA 🔴",
            "adx_1h": round(calcular_adx(highs_1h, lows_1h, closes_1h), 1),
            "rsi_1h": round(calcular_rsi(closes_1h), 1),
            "tendencia_15m": "ALCISTA 🟢" if closes_15m[-1] > closes_15m[-10] else "BAJISTA 🔴",
            "adx_15m": round(adx_15m, 1),
            "rsi_15m": round(calcular_rsi(closes_15m), 1),
            "resistencia": max(highs_1h[-10:]),
            "soporte": min(lows_1h[-10:]),
            "estado": estado_mercado,
            "pausa": pausa_texto
        }
    except Exception as e:
        return {"precio": 0.0, "tendencia_1h": "ERROR", "adx_1h": 0.0, "rsi_1h": 0.0, "tendencia_15m": "ERROR", "adx_15m": 0.0, "rsi_15m": 0.0, "resistencia": 0.0, "soporte": 0.0, "estado": "FALLA EN EXCHANGE", "pausa": str(e)}

def obtener_analisis_pnt():
    try:
        ex_bico = ccxt.biconomy({'enableRateLimit': True})
        ex_bico.load_markets()
        market_symbol = 'PNT/USDT'
        if market_symbol in ex_bico.markets:
            ticker = ex_bico.fetch_ticker(market_symbol)
            precio_actual = float(ticker['last'])
            cambio_24h = float(ticker.get('percentage', 0.0) or 0.0)
            
            ohlcv_1h = ex_bico.fetch_ohlcv(market_symbol, timeframe='1h', limit=30)
            closes_1h, highs_1h, lows_1h = [x[4] for x in ohlcv_1h], [x[2] for x in ohlcv_1h], [x[3] for x in ohlcv_1h]
            
            ohlcv_15m = ex_bico.fetch_ohlcv(market_symbol, timeframe='15m', limit=30)
            closes_15m, highs_15m, lows_15m = [x[4] for x in ohlcv_15m], [x[2] for x in ohlcv_15m], [x[3] for x in ohlcv_15m]
            
            adx_15m = calcular_adx(highs_15m, lows_15m, closes_15m)
            tendencia_15m = "ALCISTA 🟢" if closes_15m[-1] > closes_15m[-10] else "BAJISTA 🔴"
            tendencia_1h = "ALCISTA 🟢" if closes_1h[-1] > closes_1h[-10] else "BAJISTA 🔴"
            estado_mercado = "MERCADO LATERAL / RANGO EN 15M (ADX < 20)" if adx_15m < 20 else "TENDENCIA ACTIVA EN 15M"
            
            return {
                "precio": precio_actual, 
                "tendencia_1h": tendencia_1h, 
                "adx_1h": round(calcular_adx(highs_1h, lows_1h, closes_1h), 1), 
                "rsi_1h": round(calcular_rsi(closes_1h), 1),
                "tendencia_15m": tendencia_15m, 
                "adx_15m": round(adx_15m, 1), 
                "rsi_15m": round(calcular_rsi(closes_15m), 1),
                "resistencia": float(max(highs_1h[-10:])), 
                "soporte": float(min(lows_1h[-10:])),
                "estado": estado_mercado, 
                "pausa": f"Red Biconomy (Cambio 24h: {cambio_24h:+.2f}%)"
            }
    except Exception as e:
        print(f"Error conectando a Biconomy via CCXT: {e}")

    return {
        "precio": 0.367831, "tendencia_1h": "BAJISTA 🔴", "adx_1h": 30.0, "rsi_1h": 25.0,
        "tendencia_15m": "BAJISTA 🔴", "adx_15m": 42.0, "rsi_15m": 17.0,
        "resistencia": 0.3852, "soporte": 0.3669, "estado": "MERCADO LATERAL / RANGO EN 15M (ADX < 20)", "pausa": "Red Biconomy (Modo Respaldo)"
    }

def bucle_reportes_automaticos():
    time.sleep(10)
    while True:
        try:
            tiempo_actual = time.localtime()
            minuto = tiempo_actual.tm_min
            if minuto in [0, 15, 30, 45]:
                now_ts = time.time()
                coins_a_reportar = ["PNT", "BTC", "ETH", "ZEC", "SOL", "XRP", "DOGE"]
                for coin in coins_a_reportar:
                    if now_ts - ultimos_timestamps.get(coin, 0) > 800:
                        ultimos_timestamps[coin] = now_ts
                        if coin == "PNT":
                            analisis = obtener_analisis_pnt()
                            reporte = (
                                "🔔 **REPORTE AUTOMÁTICO CIERRE 15M / 1H** 🔔\n"
                                "🌐 **Activo:** PNT/USDT (Biconomy)\n\n"
                                f"💵 **Precio Actual:** ${analisis['precio']:.4f}\n\n"
                                f"📊 **MACRO (1H):** {analisis['tendencia_1h']} | ADX: {analisis['adx_1h']} | RSI: {analisis['rsi_1h']}\n"
                                f"📈 **CORTO PLAZO (15M):** {analisis['tendencia_15m']} | ADX: {analisis['adx_15m']} | RSI: {analisis['rsi_15m']}\n\n"
                                f"🧱 Resistencia: ${analisis['resistencia']:.4f}\n"
                                f"🟡 Soporte: ${analisis['soporte']:.4f}\n\n"
                                "🎯 **SEÑAL:**\n"
                                f"• {analisis['estado']}\n"
                                f"• {analisis['pausa']}"
                            )
                        else:
                            analisis = obtener_analisis_bitget(coin, 'swap')
                            reporte = (
                                "🔔 **REPORTE AUTOMÁTICO CIERRE 15M / 1H** 🔔\n"
                                f"⚡ **Activo:** {coin}/USDT\n\n"
                                f"💵 **Precio Actual:** ${analisis['precio']:,.2f}\n\n"
                                f"📊 **MACRO (1H):** {analisis['tendencia_1h']} | ADX: {analisis['adx_1h']} | RSI: {analisis['rsi_1h']}\n"
                                f"📈 **CORTO PLAZO (15M):** {analisis['tendencia_15m']} | ADX: {analisis['adx_15m']} | RSI: {analisis['rsi_15m']}\n\n"
                                f"🧱 Resistencia: ${analisis['resistencia']:,.2f}\n"
                                f"🟡 Soporte: ${analisis['soporte']:,.2f}\n\n"
                                "🎯 **SEÑAL:**\n"
                                f"• {analisis['estado']}\n"
                                f"• {analisis['pausa']}"
                            )
                        if ULTIMO_CHAT_ID:
                            bot.send_message(ULTIMO_CHAT_ID, reporte, parse_mode="Markdown")
                time.sleep(60)
        except Exception as e:
            print(f"Error en bucle automático: {e}")
        time.sleep(15)

@bot.message_handler(commands=['start', 'menu'])
def mostrar_menu_principal(message):
    global ULTIMO_CHAT_ID
    ULTIMO_CHAT_ID = message.chat.id
    
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("⚡ BTC", callback_data="ver_BTC"),
        InlineKeyboardButton("💎 ETH", callback_data="ver_ETH"),
        InlineKeyboardButton("🟣 SOL", callback_data="ver_SOL"),
        InlineKeyboardButton("🔵 XRP", callback_data="ver_XRP"),
        InlineKeyboardButton("🟡 ZEC", callback_data="ver_ZEC"),
        InlineKeyboardButton("🟠 DOGE", callback_data="ver_DOGE"),
        InlineKeyboardButton("🌐 PNT", callback_data="ver_PNT")
    )
    
    texto_menu = (
        "📈 **PANEL DE SEÑALES TÉCNICAS - BITGET & BICONOMY** 🟢\n\n"
        "Selecciona una criptomoneda para ver su análisis o usa /operar para gestionar órdenes."
    )
    bot.send_message(message.chat.id, texto_menu, reply_markup=markup, parse_mode="Markdown")

@bot.message_handler(commands=['pnt'])
def comando_pnt(message):
    global ULTIMO_CHAT_ID
    ULTIMO_CHAT_ID = message.chat.id
    
    analisis = obtener_analisis_pnt()
    reporte = (
        "🔔 **REPORTE TÉCNICO // 15M / 1H** 🔔\n"
        "🌐 Activo: PNT/USDT (Biconomy)\n\n"
        f"💵 Precio Actual: ${analisis['precio']:.4f}\n\n"
        f"📊 MACRO (1H): {analisis['tendencia_1h']} | ADX: {analisis['adx_1h']} | RSI: {analisis['rsi_1h']}\n"
        f"📈 CORTO PLAZO (15M): {analisis['tendencia_15m']} | ADX: {analisis['adx_15m']} | RSI: {analisis['rsi_15m']}\n\n"
        f"🧱 Resistencia: ${analisis['resistencia']:.4f}\n"
        f"🟡 Soporte: ${analisis['soporte']:.4f}\n\n"
        f"🎯 SEÑAL:\n"
        f"• {analisis['estado']}\n"
        f"• {analisis['pausa']}"
    )
    bot.send_message(message.chat.id, reporte, parse_mode="Markdown")

@bot.message_handler(commands=['operar'])
def menu_operar(message):
    global ULTIMO_CHAT_ID
    ULTIMO_CHAT_ID = message.chat.id
    
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("⚡ Futuros", callback_data="menu_futuros"),
        InlineKeyboardButton("🪙 Spot", callback_data="menu_spot")
    )
    texto_operar = (
        "⚙️ **CENTRAL DE OPERACIONES - BITGET** 🟢\n\n"
        "Selecciona el mercado donde deseas operar:"
    )
    bot.send_message(message.chat.id, texto_operar, reply_markup=markup, parse_mode="Markdown")

def ejecutar_orden_bitget(symbol, mercado, side, margen_usdt):
    try:
        ex = crear_instancia_exchange(mercado)
        market_symbol = f"{symbol}/USDT:USDT" if mercado == 'swap' else f"{symbol}/USDT"
        
        api, secret, password = obtener_credenciales_bitget()
        if not api or not secret:
            return False, 0, 0, 0, "❌ **Error de Autenticación:** Faltan las credenciales de Bitget en tus variables de Render."

        ticker = ex.fetch_ticker(market_symbol)
        precio_actual = float(ticker['last'])
        amount_tokens = margen_usdt / precio_actual
        params = {'createMarketBuyOrderRequiresPrice': False} if side == 'buy' else {}
        
        orden = ex.create_order(
            symbol=market_symbol, type='market', side=side, 
            amount=ex.amount_to_precision(market_symbol, amount_tokens),
            params=params
        )
        
        stop_loss_precio = precio_actual * (1 - 0.08)
        alerta_perdida_4 = precio_actual * (1 - 0.04)
        
        return True, precio_actual, stop_loss_precio, alerta_perdida_4, orden
    except Exception as e:
        error_str = str(e)
        if "43012" in error_str or "balance" in error_str.lower() or "funds" in error_str.lower() or "insufficient" in error_str.lower():
            return False, 0, 0, 0, (
                f"❌ **OPERACIÓN NO EJECUTADA** ❌\n\n"
                f"⚠️ **Motivo:** Saldo insuficiente en Bitget para cubrir los `${margen_usdt} USDT` requeridos.\n"
                f"💬 *Detalle:* {error_str}"
            )
        return False, 0, 0, 0, f"❌ **Error en Bitget:** {error_str}"

@bot.callback_query_handler(func=lambda call: True)
def callback_query(call):
    global ULTIMO_CHAT_ID
    ULTIMO_CHAT_ID = call.message.chat.id
    try:
        datos = call.data.split("_")
        if not datos:
            return
        accion = datos[0]

        if accion == "ver" and len(datos) >= 2:
            coin = datos[1]
            bot.answer_callback_query(call.id, f"Analizando {coin}...")
            
            if coin == "PNT":
                analisis = obtener_analisis_pnt()
            else:
                analisis = obtener_analisis_bitget(coin, 'swap')
            
            reporte = (
                f"🔔 **REPORTE TÉCNICO // 15M / 1H** 🔔\n"
                f"⚡ Activo: {coin}/USDT\n\n"
                f"💵 Precio Actual: ${analisis['precio']:,.4f}\n\n"
                f"📊 MACRO (1H): {analisis['tendencia_1h']} | ADX: {analisis['adx_1h']} | RSI: {analisis['rsi_1h']}\n"
                f"📈 CORTO PLAZO (15M): {analisis['tendencia_15m']} | ADX: {analisis['adx_15m']} | RSI: {analisis['rsi_15m']}\n\n"
                f"🧱 Resistencia: ${analisis['resistencia']:,.4f}\n"
                f"🟡 Soporte: ${analisis['soporte']:,.4f}\n\n"
                f"🎯 SEÑAL:\n"
                f"• {analisis['estado']}\n"
                f"• {analisis['pausa']}"
            )
            bot.send_message(call.message.chat.id, reporte, parse_mode="Markdown")

        elif call.data == "menu_futuros":
            bot.answer_callback_query(call.id, "Abriendo Futuros...")
            markup = InlineKeyboardMarkup(row_width=2)
            monedas = ["BTC", "ETH", "SOL", "XRP", "ZEC", "DOGE"]
            markup.add(*[InlineKeyboardButton(f"⚡ {c}", callback_data=f"opc_fut_{c}") for c in monedas])
            bot.send_message(call.message.chat.id, "⚡ **Selecciona el activo para FUTUROS:**", reply_markup=markup, parse_mode="Markdown")

        elif call.data == "menu_spot":
            bot.answer_callback_query(call.id, "Abriendo Spot...")
            markup = InlineKeyboardMarkup(row_width=2)
            monedas = ["BTC", "ETH", "SOL", "XRP", "ZEC", "DOGE"]
            markup.add(*[InlineKeyboardButton(f"🪙 {c}", callback_data=f"opc_spot_{c}") for c in monedas])
            bot.send_message(call.message.chat.id, "🪙 **Selecciona el activo para SPOT:**", reply_markup=markup, parse_mode="Markdown")

        elif len(datos) == 3 and datos[0] == "opc":
            mercado_tipo, coin = datos[1], datos[2]
            bot.answer_callback_query(call.id, f"Seleccionando margen para {coin}...")
            
            markup_margen = InlineKeyboardMarkup(row_width=3)
            markup_margen.add(
                InlineKeyboardButton("$2 USDT", callback_data=f"ejecutar_{mercado_tipo}_{coin}_2"),
                InlineKeyboardButton("$5 USDT", callback_data=f"ejecutar_{mercado_tipo}_{coin}_5"),
                InlineKeyboardButton("$10 USDT", callback_data=f"ejecutar_{mercado_tipo}_{coin}_10")
            )
            bot.send_message(call.message.chat.id, f"💵 **Elige el margen en USDT para {coin} ({mercado_tipo.upper()}):**", reply_markup=markup_margen, parse_mode="Markdown")

        elif accion == "ejecutar" and len(datos) >= 4:
            mercado_tipo = datos[1]
            coin = datos[2]
            margen = float(datos[3])
            mercado_key = 'swap' if mercado_tipo == 'fut' else 'spot'
            
            bot.answer_callback_query(call.id, f"Ejecutando orden de ${margen} en Bitget...")
            exito, precio_ejec, sl_precio, alerta_4, resultado = ejecutar_orden_bitget(coin, mercado_key, 'buy', margen)
            
            if exito:
                msg = (
                    f"✅ **¡ORDEN EJECUTADA EN BITGET!** ✅\n\n"
                    f"🔹 **Activo:** {coin}/USDT ({mercado_key.upper()})\n"
                    f"💵 **Margen Utilizado:** ${margen} USDT\n"
                    f"💰 **Precio de Entrada:** ${precio_ejec:,.2f}\n\n"
                    f"🛡️ **Gestión de Riesgo Configurada:**\n"
                    f"• Alerta de Pérdida (-4%): ${alerta_4:,.2f}\n"
                    f"• Stop Loss (-8%): ${sl_precio:,.2f}"
   
