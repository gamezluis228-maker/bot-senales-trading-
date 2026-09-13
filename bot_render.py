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
ultimos_timestamps = {"BTC": 0, "ZEC": 0, "PNT": 0}

LIMITE_PERDIDA_DIARIA = 10.0
perdida_acumulada_dia = 0.0
fecha_actual = time.strftime("%Y-%m-%d")
MODO_DEMO = True
MONTO_MINIMO_USDT = 5.0

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
            "resistencia": round(float(max(highs_1h[-10:])), 2),
            "soporte": round(float(min(lows_1h[-10:])), 2),
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
            ohlcv_1h = ex_bico.fetch_ohlcv(market_symbol, timeframe='1h', limit=30)
            closes_1h, highs_1h, lows_1h = [x[4] for x in ohlcv_1h], [x[2] for x in ohlcv_1h], [x[3] for x in ohlcv_1h]
            ohlcv_15m = ex_bico.fetch_ohlcv(market_symbol, timeframe='15m', limit=30)
            closes_15m, highs_15m, lows_15m = [x[4] for x in ohlcv_15m], [x[2] for x in ohlcv_15m], [x[3] for x in ohlcv_15m]
            adx_15m = calcular_adx(highs_15m, lows_15m, closes_15m)
            tendencia_15m = "ALCISTA 🟢" if closes_15m[-1] > closes_15m[-10] else "BAJISTA 🔴"
            tendencia_1h = "ALCISTA 🟢" if closes_1h[-1] > closes_1h[-10] else "BAJISTA 🔴"
            estado_mercado = "MERCADO LATERAL / RANGO EN 15M (ADX < 20)" if adx_15m < 20 else "TENDENCIA ACTIVA EN 15M"
            pausa_texto = "Estructura de 15m con fuerza tendencial." if adx_15m > 20 else "Precaución: Rango plano en corto plazo."
            return {
                "precio": precio_actual, 
                "tendencia_1h": tendencia_1h, 
                "adx_1h": round(calcular_adx(highs_1h, lows_1h, closes_1h), 1), 
                "rsi_1h": round(calcular_rsi(closes_1h), 1),
                "tendencia_15m": tendencia_15m, 
                "adx_15m": round(adx_15m, 1), 
                "rsi_15m": round(calcular_rsi(closes_15m), 1),
                "resistencia": round(float(max(highs_1h[-10:])), 6), 
                "soporte": round(float(min(lows_1h[-10:])), 6),
                "estado": estado_mercado, 
                "pausa": pausa_texto
            }
    except Exception as e:
        print(f"Error conectando a Biconomy: {e}")
    return {
        "precio": 0.364638, "tendencia_1h": "BAJISTA 🔴", "adx_1h": 25.4, "rsi_1h": 24.5,
        "tendencia_15m": "BAJISTA 🔴", "adx_15m": 12.1, "rsi_15m": 51.3,
        "resistencia": 0.393809, "soporte": 0.335467, "estado": "RANGO", "pausa": "Biconomy Respaldo"
    }

def bucle_reportes_automaticos():
    time.sleep(10)
    while True:
        try:
            tiempo_actual = time.localtime()
            if tiempo_actual.tm_min in [0, 15, 30, 45]:
                now_ts = time.time()
                for coin in ["BTC", "ZEC", "PNT"]:
                    if now_ts - ultimos_timestamps.get(coin, 0) > 800:
                        ultimos_timestamps[coin] = now_ts
                        if coin == "PNT":
                            a = obtener_analisis_pnt()
                            titulo_activo = "SPOT BICONOMY: PNT/USDT (Solo Lectura)"
                        else:
                            a = obtener_analisis_bitget(coin, 'swap')
                            titulo_activo = f"Activo Bitget: {coin}/USDT"

                        rep = (
                            "🔔 REPORTE AUTOMÁTICO CIERRE 15M / 1H 🔔\n"
                            f"⚡ {titulo_activo}\n\n"
                            f"💵 Precio Actual: ${a['precio']}\n\n"
                            f"📊 MACRO (1H): {a['tendencia_1h']} | ADX: {a['adx_1h']} | RSI: {a['rsi_1h']}\n"
                            f"📈 CORTO PLAZO (15M): {a['tendencia_15m']} | ADX: {a['adx_15m']} | RSI: {a['rsi_15m']}\n\n"
                            f"🧱 Resistencia: ${a['resistencia']}\n"
                            f"🟡 Soporte: ${a['soporte']}\n\n"
                            f"🎯 SEÑAL:\n• {a['estado']}\n• {a['pausa']}"
                        )

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
        InlineKeyboardButton("🌐 PNT (Solo Info)", callback_data="ver_PNT")
    )
    bot.send_message(message.chat.id, "📈 **PANEL DE SEÑALES - BITGET & BICONOMY** 🟢", reply_markup=markup, parse_mode="Markdown")

@bot.message_handler(commands=['operar'])
def menu_operar(message):
    global ULTIMO_CHAT_ID
    ULTIMO_CHAT_ID = message.chat.id
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("⚡ Futuros (Bitget)", callback_data="menu_futuros"),
        InlineKeyboardButton("🪙 Spot (Bitget)", callback_data="menu_spot")
    )
    bot.send_message(message.chat.id, "⚙️ **CENTRAL DE OPERACIONES (EXCLUSIVO BITGET)** 🟢", reply_markup=markup, parse_mode="Markdown")

@bot.message_handler(commands=['pnt', 'PNT'])
def comando_pnt(message):
    global ULTIMO_CHAT_ID
    ULTIMO_CHAT_ID = message.chat.id
    bot.send_message(message.chat.id, "🔍 **Analizando PNT/USDT en Biconomy...**\nPor favor espera unos segundos.", parse_mode="Markdown")
    
    analisis = obtener_analisis_pnt()
    
    rep = (
        "🔔 **ANÁLISIS TÉCNICO PNT/USDT (BICONOMY)** 🔔\n\n"
        f"💵 **Precio Actual:** ${analisis['precio']}\n\n"
        f"📊 **MACRO (1H):** {analisis['tendencia_1h']} | ADX: {analisis['adx_1h']} | RSI: {analisis['rsi_1h']}\n"
        f"📈 **CORTO PLAZO (15M):** {analisis['tendencia_15m']} | ADX: {analisis['adx_15m']} | RSI: {analisis['rsi_15m']}\n\n"
        f"🧱 **Resistencia:** ${analisis['resistencia']}\n"
        f"🟡 **Soporte:** ${analisis['soporte']}\n\n"
        f"🎯 **SEÑAL:**\n• {analisis['estado']}\n• {analisis['pausa']}"
    )
    bot.send_message(message.chat.id, rep, parse_mode="Markdown")

def ejecutar_orden_con_gestion_riesgo_real(symbol, mercado, side, margen_usdt, apalancamiento=1, tipo_orden='market', zona_precio=None):
    try:
        ex = crear_instancia_exchange(mercado)
        market_symbol = f"{symbol}/USDT:USDT" if mercado == 'swap' else f"{symbol}/USDT"
        api, secret, _ = obtener_credenciales_bitget()
        if not api or not secret:
            return False, 0, 0, 0, 0, 0, 0, "❌ **Error:** Faltan las credenciales de Bitget."
        
        global perdida_acumulada_dia, fecha_actual
        hoy = time.strftime("%Y-%m-%d")
        if hoy != fecha_actual:
            perdida_acumulada_dia = 0.0
            fecha_actual = hoy
        
        if perdida_acumulada_dia >= LIMITE_PERDIDA_DIARIA:
            return False, 0, 0, 0, 0, 0, 0, f"🛑 **BLOQUEO POR PÉRDIDA DIARIA:** Has alcanzado el límite de ${LIMITE_PERDIDA_DIARIA} USD. El bot no ejecutará más órdenes hasta mañana."
        
        if mercado == 'swap' and apalancamiento > 1:
            try:
                ex.set_leverage(apalancamiento, market_symbol)
            except Exception as e:
                print(f"Aviso de apalancamiento: {e}")

        analisis = obtener_analisis_bitget(symbol, mercado)
        precio_actual = analisis['precio']
        soporte = analisis['soporte']
        resistencia = analisis['resistencia']

        precio_objetivo = precio_actual
        if tipo_orden == 'limit' and zona_precio:
            if zona_precio == 'soporte':
                precio_objetivo = soporte
                side = 'buy'
            elif zona_precio == 'resistencia':
                precio_objetivo = resistencia
                side = 'sell'

        if side == 'buy':
            stop_loss = round(precio_objetivo * 0.96, 4)
            take_profit = round(precio_objetivo * 1.08, 4)
        else:
            stop_loss = round(precio_objetivo * 1.04, 4)
            take_profit = round(precio_objetivo * 0.92, 4)

        amount_tokens = (margen_usdt * apalancamiento) / precio_objetivo if tipo_orden == 'limit' else margen_usdt / precio_actual
        
        monto_total_operacion = margen_usdt * apalancamiento
        if monto_total_operacion < MONTO_MINIMO_USDT:
            return False, 0, 0, 0, 0, 0, 0, f"⚠️ **MONTO INSUFICIENTE:** El monto total de la operación (${monto_total_operacion:.2f} USDT) es menor al mínimo permitido (${MONTO_MINIMO_USDT} USDT). Aumenta el margen o el apalancamiento."
        
        if amount_tokens <= 0:
            return False, 0, 0, 0, 0, 0, 0, "⚠️ **ERROR DE CÁLCULO:** El monto en tokens es 0 o negativo. Verifica el margen y el precio."
        
        params = {}
        if mercado == 'swap':
            params = {
                'stopLoss': {'triggerPrice': stop_loss},
                'takeProfit': {'triggerPrice': take_profit}
            }
            if tipo_orden == 'market' and side == 'buy':
                params['createMarketBuyOrderRequiresPrice'] = False
        else:
            if tipo_orden == 'market' and side == 'buy':
                params = {'createMarketBuyOrderRequiresPrice': False}

        if MODO_DEMO:
            print(f"[MODO DEMO] Orden simulada: {side.upper()} {amount_tokens:.6f} {market_symbol} a precio {precio_objetivo if tipo_orden == 'limit' else precio_actual}")
            orden = {
                'id': f"DEMO-{int(time.time())}",
                'symbol': market_symbol,
                'side': side,
                'type': tipo_orden,
                'amount': amount_tokens,
                'price': precio_objetivo if tipo_orden == 'limit' else precio_actual,
                'status': 'simulated',
                'info': {'demo': True}
            }
        else:
            if tipo_orden == 'market':
                orden = ex.create_order(symbol=market_symbol, type='market', side=side, amount=ex.amount_to_precision(market_symbol, amount_tokens), params=params)
            else:
                params['price'] = ex.price_to_precision(market_symbol, precio_objetivo)
                orden = ex.create_order(symbol=market_symbol, type='limit', side=side, amount=ex.amount_to_precision(market_symbol, amount_tokens), params=params)
                precio_actual = precio_objetivo

        return True, precio_actual, margen_usdt, apalancamiento, tipo_orden, stop_loss, take_profit, orden
    except Exception as e:
        error_str = str(e)
        global perdida_acumulada_dia
        perdida_acumulada_dia += 1.0
        if "45110" in error_str or "minimum amount" in error_str:
            mensaje_amigable = "❌ **Error en Bitget:** El monto es menor al mínimo permitido (Mínimo requerido: 5 USDT)."
        elif "balance" in error_str.lower() or "insufficient" in error_str.lower():
            mensaje_amigable = "❌ **Error en Bitget:** Saldo insuficiente en la billetera."
        else:
            mensaje_amigable = f"❌ **Error en Bitget:** {error_str}"
        return False, 0, 0, 0, 0, 0, 0, mensaje_amigable

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
            
            titulo_activo = f"SPOT BICONOMY: {coin}/USDT (Solo Lectura)" if coin == "PNT" else f"Activo Bitget: {coin}/USDT"
            rep = (
                "🔔 REPORTE TÉCNICO 🔔\n"
                f"⚡ {titulo_activo}\n\n"
                f"💵 Precio Actual: ${analisis['precio']}\n\n"
                f"📊 MACRO (1H): {analisis['tendencia_1h']} | ADX: {analisis['adx_1h']} | RSI: {analisis['rsi_1h']}\n"
                f"📈 CORTO PLAZO (15M): {analisis['tendencia_15m']} | ADX: {analisis['adx_15m']} | RSI: {analisis['rsi_15m']}\n\n"
                f"🧱 Resistencia: ${analisis['resistencia']}\n"
                f"🟡 Soporte: ${analisis['soporte']}\n\n"
                f"🎯 SEÑAL:\n• {analisis['estado']}\n• {analisis['pausa']}"
            )
            bot.send_message(call.message.chat.id, rep, parse_mode="Markdown")

        elif call.data == "menu_futuros":
            bot.answer_callback_query(call.id, "Futuros Bitget...")
            m = InlineKeyboardMarkup(row_width=2)
            m.add(*[InlineKeyboardButton(f"⚡ {c}", callback_data=f"opc_fut_{c}") for c in ["BTC", "ETH", "SOL", "XRP", "ZEC", "DOGE"]])
            bot.send_message(call.message.chat.id, "⚡ **Selecciona Activo para Futuros (Bitget):**", reply_markup=m, parse_mode="Markdown")

        elif call.data == "menu_spot":
            bot.answer_callback_query(call.id, "Spot Bitget...")
            m = InlineKeyboardMarkup(row_width=2)
            m.add(*[InlineKeyboardButton(f"🪙 {c}", callback_data=f"opc_spot_{c}") for c in ["BTC", "ETH", "SOL", "XRP", "ZEC", "DOGE"]])
            bot.send_message(call.message.chat.id, "🪙 **Selecciona Activo para Spot (Bitget):**", reply_markup=m, parse_mode="Markdown")

        elif len(datos) == 3 and datos[0] == "opc":
            mercado_tipo, coin = datos[1], datos[2]
            if mercado_tipo == "fut":
    bot.answer_callback_query(call.id, f"Apalancamiento para {coin}...")
    m_lev = InlineKeyboardMarkup(row_width=3)
    m_lev.add(
        InlineKeyboardButton("1x", callback_data=f"lev_{coin}_1"),
        InlineKeyboardButton("5x", callback_data=f"lev_{coin}_5"),
        InlineKeyboardButton("10x", callback_data=f"lev_{coin}_10"),
        InlineKeyboardButton("20x", callback_data=f"lev_{coin}_20")
    )
    bot.send_message(call.message.chat.id, f"⚙️ **Elige Apalancamiento para {coin} (Bitget):**", reply_markup=m_lev, parse_mode="Markdown")
elif accion == "lev" and len(datos) == 3:
    bot.answer_callback_query(call.id, f"Margen para {coin}...")
    m_mar = InlineKeyboardMarkup(row_width=3)
    m_mar.add(
        InlineKeyboardButton("$5", callback_data=f"ejec_spot_{coin}_1_market_none_5"),
        InlineKeyboardButton("$10", callback_data=f"ejec_spot_{coin}_1_market_none_10"),
        InlineKeyboardButton("$20", callback_data=f"ejec_spot_{coin}_1_market_none_20")
    )
    bot.send_message(call.message.chat.id, f"💵 **Elige Margen para Spot Bitget {coin} (Mínimo $5):**", reply_markup=m_mar, parse_mode="Markdown") 
        elif accion == "tipo" and len(datos) == 5:
            coin, lev, tipo_o = datos[2], int(datos[3]), datos[4]
            if tipo_o == "market":
                bot.answer_callback_query(call.id, "Selecciona margen...")
                m_mar = InlineKeyboardMarkup(row_width=3)
                m_mar.add(
                    InlineKeyboardButton("$5", callback_data=f"ejec_fut_{coin}_{lev}_market_none_5"),
                    InlineKeyboardButton("$10", callback_data=f"ejec_fut_{coin}_{lev}_market_none_10"),
                    InlineKeyboardButton("$20", callback_data=f"ejec_fut_{coin}_{lev}_market_none_20")
                )
                bot.send_message(call.message.chat.id, f"💵 **Elige Margen para Mercado {coin} ({lev}x):**", reply_markup=m_mar, parse_mode="Markdown")
            else:
                bot.answer_callback_query(call.id, "Selecciona zona para orden Límite...")
                m_zona = InlineKeyboardMarkup(row_width=2)
                m_zona.add(
                    InlineKeyboardButton("🟢 Comprar en Soporte", callback_data=f"ejec_fut_{coin}_{lev}_limit_soporte_10"),
                    InlineKeyboardButton("🔴 Vender en Resistencia", callback_data=f"ejec_fut_{coin}_{lev}_limit_resistencia_10")
                )
                bot.send_message(call.message.chat.id, f"🎯 **Elige zona para orden Límite de {coin} ({lev}x):**\n\n*Nota: Se usarán $10 de margen por defecto para el cálculo.*", reply_markup=m_zona, parse_mode="Markdown")

        elif accion == "ejec" and len(datos) >= 7:
            mercado_tipo = datos[1]
            coin = datos[2]
            lev = int(datos[3]) if datos[3] != 'none' else 1
            tipo_orden = datos[4]
            zona = datos[5]
            margen = float(datos[6])

            msg_espera = bot.send_message(call.message.chat.id, f"⏳ **Ejecutando orden {tipo_orden.upper()} para {coin}...**\nPor favor espera.", parse_mode="Markdown")
            mercado_ccxt = 'swap' if mercado_tipo == 'fut' else 'spot'
            
            exito, precio, margen_usado, lev_usado, tipo_usado, sl, tp, resultado = ejecutar_orden_con_gestion_riesgo_real(
                symbol=coin,
                mercado=mercado_ccxt,
                side='buy' if zona in ['none', 'soporte'] else 'sell',
                margen_usdt=margen,
                apalancamiento=lev,
                tipo_orden=tipo_orden,
                zona_precio=zona if zona != 'none' else None
            )

            bot.delete_message(call.message.chat.id, msg_espera.message_id)

            if exito:
                direccion = "COMPRA (LONG) 🟢" if (zona in ['none', 'soporte'] or resultado['side'] == 'buy') else "VENTA (SHORT) 🔴"
                modo_texto = "🧪 **MODO DEMO (SIMULACIÓN)**" if MODO_DEMO else "✅ **¡ORDEN EJECUTADA CON ÉXITO!** ✅"
                rep = (
                    f"{modo_texto}\n\n"
                    f"🪙 **Activo:** {coin}/USDT\n"
                    f"⚙️ **Mercado:** {'Futuros' if mercado_tipo == 'fut' else 'Spot'}\n"
                    f"📈 **Dirección:** {direccion}\n"
                    f"💵 **Precio de Entrada:** ${precio}\n"
                    f"💰 **Margen:** ${margen_usado} USDT\n"
                    f"⚡ **Apalancamiento:** {lev_usado}x\n"
                    f"📋 **Tipo:** {tipo_usado.upper()}\n\n"
                    f"🛑 **Stop Loss:** ${sl}\n"
                    f"🎯 **Take Profit:** ${tp}\n\n"
                    f"🆔 **ID de Orden:** `{resultado.get('id', 'N/A')}`"
                )
                bot.send_message(call.message.chat.id, rep, parse_mode="Markdown")
            else:
                bot.send_message(call.message.chat.id, f"❌ **Fallo al ejecutar:**\n\n{resultado}", parse_mode="Markdown")

        else:
            bot.answer_callback_query(call.id, "Opción no reconocida.")
            
    except Exception as e:
        print(f"Error en callback: {e}")
        bot.send_message(call.message.chat.id, f"⚠️ **Error interno:** {str(e)}")

def iniciar_hilos():
    hilo_keep_alive = threading.Thread(target=bucle_keep_alive, daemon=True)
    hilo_keep_alive.start()
    hilo_reportes = threading.Thread(target=bucle_reportes_automaticos, daemon=True)
    hilo_reportes.start()

if __name__ == "__main__":
    print("Iniciando Bot...")
    inicializar_mercados()
    iniciar_hilos()
    puerto = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=puerto)
