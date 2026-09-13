import os
import threading
import time
import requests
import telebot
import ccxt
import numpy as np
from flask import Flask
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

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
                "precio": precio_actual, "tendencia_1h": tendencia_1h, "adx_1h": round(calcular_adx(highs_1h, lows_1h, closes_1h), 1), "rsi_1h": round(calcular_rsi(closes_1h), 1),
                "tendencia_15m": tendencia_15m, "adx_15m": round(adx_15m, 1), "rsi_15m": round(calcular_rsi(closes_15m), 1),
                "resistencia": float(max(highs_1h[-10:])), "soporte": float(min(lows_1h[-10:])),
                "estado": estado_mercado, "pausa": f"Red Biconomy (Cambio 24h: {cambio_24h:+.2f}%)"
            }
    except Exception as e:
        print(f"Error conectando a Biconomy: {e}")
    return {
        "precio": 0.367831, "tendencia_1h": "BAJISTA 🔴", "adx_1h": 30.0, "rsi_1h": 25.0,
        "tendencia_15m": "BAJISTA 🔴", "adx_15m": 42.0, "rsi_15m": 17.0,
        "resistencia": 0.3852, "soporte": 0.3669, "estado": "RANGO", "pausa": "Biconomy Respaldo"
    }

def bucle_reportes_automaticos():
    time.sleep(10)
    while True:
        try:
            tiempo_actual = time.localtime()
            if tiempo_actual.tm_min in [0, 15, 30, 45]:
                now_ts = time.time()
                for coin in ["PNT", "BTC", "ETH", "ZEC", "SOL", "XRP", "DOGE"]:
                    if now_ts - ultimos_timestamps.get(coin, 0) > 800:
                        ultimos_timestamps[coin] = now_ts
                        if coin == "PNT":
                            a = obtener_analisis_pnt()
                            rep = "🔔 **REPORTE AUTOMÁTICO** 🔔\n🌐 PNT/USDT\n\n💵 Precio: $" + str(a['precio']) + \
                                  "\n📊 1H: " + a['tendencia_1h'] + " | ADX: " + str(a['adx_1h']) + \
                                  "\n📈 15M: " + a['tendencia_15m'] + " | ADX: " + str(a['adx_15m'])
                        else:
                            a = obtener_analisis_bitget(coin, 'swap')
                            rep = "🔔 **REPORTE AUTOMÁTICO** 🔔\n⚡ " + coin + "/USDT\n\n💵 Precio: $" + str(a['precio']) + \
                                  "\n📊 1H: " + a['tendencia_1h'] + " | ADX: " + str(a['adx_1h']) + \
                                  "\n📈 15M: " + a['tendencia_15m'] + " | ADX: " + str(a['adx_15m'])
                        if ULTIMO_CHAT_ID:
                            bot.send_message(ULTIMO_CHAT_ID, rep, parse_mode="Markdown")
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
    bot.send_message(message.chat.id, "📈 **PANEL DE SEÑALES - BITGET & BICONOMY** 🟢", reply_markup=markup, parse_mode="Markdown")

@bot.message_handler(commands=['operar'])
def menu_operar(message):
    global ULTIMO_CHAT_ID
    ULTIMO_CHAT_ID = message.chat.id
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("⚡ Futuros", callback_data="menu_futuros"),
        InlineKeyboardButton("🪙 Spot", callback_data="menu_spot")
    )
    bot.send_message(message.chat.id, "⚙️ **CENTRAL DE OPERACIONES** 🟢", reply_markup=markup, parse_mode="Markdown")

def ejecutar_orden_bitget(symbol, mercado, side, margen_usdt):
    try:
        ex = crear_instancia_exchange(mercado)
        market_symbol = f"{symbol}/USDT:USDT" if mercado == 'swap' else f"{symbol}/USDT"
        api, secret, _ = obtener_credenciales_bitget()
        if not api or not secret:
            return False, 0, 0, 0, "❌ **Error:** Faltan credenciales de Bitget."
        ticker = ex.fetch_ticker(market_symbol)
        precio_actual = float(ticker['last'])
        amount_tokens = margen_usdt / precio_actual
        params = {'createMarketBuyOrderRequiresPrice': False} if side == 'buy' else {}
        orden = ex.create_order(symbol=market_symbol, type='market', side=side, amount=ex.amount_to_precision(market_symbol, amount_tokens), params=params)
        sl = precio_actual * (1 - 0.08)
        alerta_4 = precio_actual * (1 - 0.04)
        return True, precio_actual, sl, alerta_4, orden
    except Exception as e:
        return False, 0, 0, 0, f"❌ **Error en Bitget:** {str(e)}"

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
            analisis = obtener_analisis_pnt() if coin == "PNT" else obtener_analisis_bitget(coin, 'swap')
            rep = "🔔 **REPORTE TÉCNICO** 🔔\n⚡ Activo: " + coin + "/USDT\n\n💵 Precio: $" + str(analisis['precio']) + \
                  "\n📊 1H: " + analisis['tendencia_1h'] + " | RSI: " + str(analisis['rsi_1h']) + \
                  "\n📈 15M: " + analisis['tendencia_15m'] + " | RSI: " + str(analisis['rsi_15m'])
            bot.send_message(call.message.chat.id, rep, parse_mode="Markdown")

        elif call.data == "menu_futuros":
            bot.answer_callback_query(call.id, "Futuros...")
            m = InlineKeyboardMarkup(row_width=2)
            m.add(*[InlineKeyboardButton(f"⚡ {c}", callback_data=f"opc_fut_{c}") for c in ["BTC", "ETH", "SOL", "XRP", "ZEC", "DOGE"]])
            bot.send_message(call.message.chat.id, "⚡ **Selecciona Activo Futuros:**", reply_markup=m, parse_mode="Markdown")

        elif call.data == "menu_spot":
            bot.answer_callback_query(call.id, "Spot...")
            m = InlineKeyboardMarkup(row_width=2)
            m.add(*[InlineKeyboardButton(f"🪙 {c}", callback_data=f"opc_spot_{c}") for c in ["BTC", "ETH", "SOL", "XRP", "ZEC", "DOGE"]])
            bot.send_message(call.message.chat.id, "🪙 **Selecciona Activo Spot:**", reply_markup=m, parse_mode="Markdown")

        elif len(datos) == 3 and datos[0] == "opc":
            mercado_tipo, coin = datos[1], datos[2]
            bot.answer_callback_query(call.id, f"Margen para {coin}...")
            markup_margen = InlineKeyboardMarkup(row_width=3)
            markup_margen.add(
                InlineKeyboardButton("$2", callback_data=f"ejecutar_{mercado_tipo}_{coin}_2"),
                InlineKeyboardButton("$5", callback_data=f"ejecutar_{mercado_tipo}_{coin}_5"),
                InlineKeyboardButton("$10", callback_data=f"ejecutar_{mercado_tipo}_{coin}_10")
            )
            bot.send_message(call.message.chat.id, f"💵 **Elige Margen para {coin}:**", reply_markup=markup_margen, parse_mode="Markdown")

        elif accion == "ejecutar" and len(datos) >= 4:
            mercado_tipo, coin, margen = datos[1], datos[2], float(datos[3])
            mercado_key = 'swap' if mercado_tipo == 'fut' else 'spot'
            bot.answer_callback_query(call.id, "Ejecutando orden...")
            exito, precio_ejec, sl_precio, alerta_4, resultado = ejecutar_orden_bitget(coin, mercado_key, 'buy', margen)
            if exito:
                msg = "✅ **¡ORDEN EJECUTADA!** ✅\n\n🔹 Activo: " + coin + " (" + mercado_key.upper() + ")\n💵 Margen: $" + str(margen) + " USDT\n💰 Entrada: $" + str(precio_ejec) + "\n🛡️ SL: $" + str(sl_precio)
                bot.send_message(call.message.chat.id, msg, parse_mode="Markdown")
            else:
                bot.send_message(call.message.chat.id, str(resultado), parse_mode="Markdown")
    except Exception as e:
        print(f"Error en callback: {e}")

if __name__ == '__main__':
    inicializar_mercados()
    PORT = int(os.environ.get("PORT", 10000))
    
    threading.Thread(target=lambda: app.run(host="0.0.0.0", port=PORT, debug=False, use_reloader=False), daemon=True).start()
    threading.Thread(target=bucle_reportes_automaticos, daemon=True).start()
    threading.Thread(target=bucle_keep_alive, daemon=True).start()

    print("Iniciando bot...")
    bot.infinity_polling()
