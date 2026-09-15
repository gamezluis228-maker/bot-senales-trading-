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
ultimos_timestamps = {"BTC": 0, "ZEC": 0}

LIMITE_PERDIDA_DIARIA = 10.0
perdida_acumulada_dia = 0.0
fecha_actual = time.strftime("%Y-%m-%d")
MODO_DEMO = False
MONTO_MINIMO_USDT = 5.0

ordenes_abiertas = []

MONEDAS_TRADING = ["BTC", "ETH", "SOL", "DOGE", "ZEC", "PEPE"]

def obtener_credenciales_mexc():
    api = (os.getenv("MEXC_API_KEY") or os.getenv("MEXC_KEY") or 
           os.getenv("MEXC_API") or "")
    secret = (os.getenv("MEXC_SECRET_KEY") or os.getenv("MEXC_SECRET") or 
              os.getenv("MEXC_SEC") or "")
    return api.strip(), secret.strip()

def crear_instancia_exchange(mercado='swap'):
    api, secret = obtener_credenciales_mexc()
    config = {
        'enableRateLimit': True,
        'options': {'defaultType': mercado, 'createMarketBuyOrderRequiresPrice': False}
    }
    if api:
        config['apiKey'] = api
    if secret:
        config['secret'] = secret
    return ccxt.mexc(config)

exchange_default = crear_instancia_exchange('swap')

def inicializar_mercados():
    try:
        exchange_default.load_markets()
        print("¡Mercados de MEXC cargados correctamente!")
    except Exception as e:
        print(f"Error al cargar mercados: {e}")

@app.route('/')
def home():
    return "Bot Activo - MEXC Conectados"

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

def obtener_analisis_mexc(symbol, mercado='swap'):
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

def detectar_rompimiento(symbol, mercado='swap'):
    try:
        ex = crear_instancia_exchange(mercado)
        market_symbol = f"{symbol}/USDT:USDT" if mercado == 'swap' else f"{symbol}/USDT"
        
        ohlcv_1h = ex.fetch_ohlcv(market_symbol, timeframe='1h', limit=30)
        closes_1h = [x[4] for x in ohlcv_1h]
        highs_1h = [x[2] for x in ohlcv_1h]
        lows_1h = [x[3] for x in ohlcv_1h]
        volumes_1h = [x[5] for x in ohlcv_1h]
        
        adx_1h = calcular_adx(highs_1h, lows_1h, closes_1h)
        rsi_1h = calcular_rsi(closes_1h)
        
        resistencia = max(highs_1h[-11:-1])
        soporte = min(lows_1h[-11:-1])
        
        volumen_promedio = sum(volumes_1h[-11:-1]) / 10
        volumen_actual = volumes_1h[-1]
        precio_actual = closes_1h[-1]
        
        if (precio_actual > resistencia and 
            adx_1h > 20 and 
            50 < rsi_1h < 70 and 
            volumen_actual > volumen_promedio):
            return {
                'tipo': 'COMPRA',
                'symbol': symbol,
                'precio': precio_actual,
                'resistencia': resistencia,
                'soporte': soporte,
                'adx': round(adx_1h, 1),
                'rsi': round(rsi_1h, 1),
                'volumen': volumen_actual,
                'volumen_promedio': volumen_promedio
            }
        
        if (precio_actual < soporte and 
            adx_1h > 20 and 
            30 < rsi_1h < 50 and 
            volumen_actual > volumen_promedio):
            return {
                'tipo': 'VENTA',
                'symbol': symbol,
                'precio': precio_actual,
                'resistencia': resistencia,
                'soporte': soporte,
                'adx': round(adx_1h, 1),
                'rsi': round(rsi_1h, 1),
                'volumen': volumen_actual,
                'volumen_promedio': volumen_promedio
            }
        
        return None
    except Exception as e:
        print(f"Error detectando rompimiento en {symbol}: {e}")
        return None

def bucle_reportes_automaticos():
    time.sleep(10)
    while True:
        try:
            tiempo_actual = time.localtime()
            if tiempo_actual.tm_min in [0, 15, 30, 45]:
                now_ts = time.time()
                for coin in ["BTC", "ZEC"]:
                    if now_ts - ultimos_timestamps.get(coin, 0) > 800:
                        ultimos_timestamps[coin] = now_ts
                        a = obtener_analisis_mexc(coin, 'swap')
                        titulo_activo = f"Activo MEXC: {coin}/USDT"

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

def bucle_trading_automatico():
    time.sleep(20)
    ultimo_analisis = {}
    while True:
        try:
            tiempo_actual = time.localtime()
            if tiempo_actual.tm_min in [0, 15, 30, 45]:
                now_ts = time.time()
                for coin in MONEDAS_TRADING:
                    if now_ts - ultimo_analisis.get(coin, 0) > 800:
                        ultimo_analisis[coin] = now_ts
                        señal = detectar_rompimiento(coin, 'swap')
                        if señal:
                            tipo = señal['tipo']
                            emoji = "🟢" if tipo == 'COMPRA' else "🔴"
                            if coin == "PEPE":
                                montos = [2, 5]
                            else:
                                montos = [2, 5, 10, 20]
                            m = InlineKeyboardMarkup(row_width=2)
                            botones = []
                            for monto in montos:
                                botones.append(InlineKeyboardButton(
                                    f"${monto}", 
                                    callback_data=f"aut_{coin}_{tipo}_{monto}"
                                ))
                            m.add(*botones)
                            m.add(InlineKeyboardButton("❌ Cancelar", callback_data="aut_cancelar"))
                            rep = (
                                f"🚨 **ROMPIMIENTO DETECTADO** 🚨\n\n"
                                f"{emoji} **Tipo:** {tipo}\n"
                                f"🪙 **Activo:** {coin}/USDT\n"
                                f"💵 **Precio Actual:** ${señal['precio']}\n\n"
                                f"🧱 **Resistencia:** ${señal['resistencia']}\n"
                                f"🟡 **Soporte:** ${señal['soporte']}\n\n"
                                f"📊 **ADX (1H):** {señal['adx']}\n"
                                f"📈 **RSI (1H):** {señal['rsi']}\n"
                                f"📊 **Volumen:** {señal['volumen']:.0f} (promedio: {señal['volumen_promedio']:.0f})\n\n"
                                f"🎯 **¿Autorizas la operación?**\n"
                                f"Elige el monto:"
                            )
                            if ULTIMO_CHAT_ID:
                                bot.send_message(ULTIMO_CHAT_ID, rep, reply_markup=m, parse_mode="Markdown")
                time.sleep(60)
        except Exception as e:
            print(f"Error en bucle de trading automático: {e}")
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
        InlineKeyboardButton("🟠 DOGE", callback_data="ver_DOGE"),
        InlineKeyboardButton("🟡 ZEC", callback_data="ver_ZEC"),
        InlineKeyboardButton("🐸 PEPE", callback_data="ver_PEPE")
    )
    bot.send_message(message.chat.id, "📈 **PANEL DE SEÑALES - MEXC** 🟢", reply_markup=markup, parse_mode="Markdown")

@bot.message_handler(commands=['operar'])
def menu_operar(message):
    global ULTIMO_CHAT_ID
    ULTIMO_CHAT_ID = message.chat.id
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("⚡ Futuros (MEXC)", callback_data="menu_futuros")
    )
    bot.send_message(message.chat.id, "⚙️ **CENTRAL DE OPERACIONES (FUTUROS PERPETUOS)** 🟢", reply_markup=markup, parse_mode="Markdown")

@bot.message_handler(commands=['analisis'])
def menu_analisis(message):
    global ULTIMO_CHAT_ID
    ULTIMO_CHAT_ID = message.chat.id
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("⚡ BTC", callback_data="ana_BTC"),
        InlineKeyboardButton("💎 ETH", callback_data="ana_ETH"),
        InlineKeyboardButton("🟣 SOL", callback_data="ana_SOL"),
        InlineKeyboardButton("🟠 DOGE", callback_data="ana_DOGE"),
        InlineKeyboardButton("🟡 ZEC", callback_data="ana_ZEC"),
        InlineKeyboardButton("🐸 PEPE", callback_data="ana_PEPE")
    )
    bot.send_message(message.chat.id, "🔍 **Selecciona el activo para análisis técnico:**", reply_markup=markup, parse_mode="Markdown")

def ejecutar_orden_con_gestion_riesgo_real(symbol, mercado, side, margen_usdt, apalancamiento=1, tipo_orden='market', zona_precio=None):
    try:
        ex = crear_instancia_exchange(mercado)
        ex.load_markets()
        market_symbol = f"{symbol}/USDT:USDT" if mercado == 'swap' else f"{symbol}/USDT"
        api, secret = obtener_credenciales_mexc()
        if not api or not secret:
            return False, 0, 0, 0, 0, 0, 0, "❌ **Error:** Faltan las credenciales de MEXC."
        
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

        analisis = obtener_analisis_mexc(symbol, mercado)
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
        perdida_acumulada_dia += 1.0
        if "minimum amount" in error_str or "minimum" in error_str:
            mensaje_amigable = "❌ **Error en MEXC:** El monto es menor al mínimo permitido (Mínimo requerido: 5 USDT)."
        elif "balance" in error_str.lower() or "insufficient" in error_str.lower():
            mensaje_amigable = "❌ **Error en MEXC:** Saldo insuficiente en la billetera."
        else:
            mensaje_amigable = f"❌ **Error en MEXC:** {error_str}"
        return False, 0, 0, 0, 0, 0, 0, mensaje_amigable

def bucle_monitoreo_ordenes():
    time.sleep(30)
    while True:
        try:
            if ordenes_abiertas:
                for orden_info in ordenes_abiertas[:]:
                    try:
                        ex = crear_instancia_exchange(orden_info['mercado'])
                        market_symbol = orden_info['market_symbol']
                        orden_actual = ex.fetch_order(orden_info['id'], market_symbol)
                        estado = orden_actual.get('status', 'open')
                        
                        if estado in ['closed', 'canceled', 'filled']:
                            precio_entrada = orden_info['precio_entrada']
                            precio_actual = orden_actual.get('price', 0) or orden_actual.get('average', 0) or precio_entrada
                            lado = orden_info['side']
                            margen = orden_info['margen']
                            apalancamiento = orden_info['apalancamiento']
                            
                            if lado == 'buy':
                                pnl_pct = ((precio_actual - precio_entrada) / precio_entrada) * 100
                            else:
                                pnl_pct = ((precio_entrada - precio_actual) / precio_entrada) * 100
                            
                            pnl_usdt = margen * apalancamiento * (pnl_pct / 100)
                            emoji_resultado = "🟢 GANANCIA" if pnl_usdt > 0 else "🔴 PÉRDIDA"
                            
                            reporte = (
                                f"🎯 **OPERACIÓN CERRADA** 🎯\n\n"
                                f"🪙 **Activo:** {orden_info['coin']}/USDT\n"
                                f"⚙️ **Mercado:** Futuros\n"
                                f"📈 **Dirección:** {'COMPRA (LONG) 🟢' if lado == 'buy' else 'VENTA (SHORT) 🔴'}\n"
                                f"💵 **Precio Entrada:** ${precio_entrada}\n"
                                f"💵 **Precio Salida:** ${precio_actual}\n"
                                f"💰 **Margen:** ${margen} USDT\n"
                                f"⚡ **Apalancamiento:** {apalancamiento}x\n\n"
                                f"{emoji_resultado}: **${pnl_usdt:.2f} USDT** ({pnl_pct:+.2f}%)\n\n"
                                f"🆔 **ID:** `{orden_info['id']}`"
                            )
                            
                            if ULTIMO_CHAT_ID:
                                bot.send_message(ULTIMO_CHAT_ID, reporte, parse_mode="Markdown")
                            
                            ordenes_abiertas.remove(orden_info)
                    except Exception as e:
                        print(f"Error monitoreando orden {orden_info.get('id', '?')}: {e}")
        except Exception as e:
            print(f"Error en bucle de monitoreo: {e}")
        time.sleep(180)

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
            analisis = obtener_analisis_mexc(coin, 'swap')
            titulo_activo = f"Activo MEXC: {coin}/USDT"
            
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

        elif accion == "ana" and len(datos) >= 2:
            coin = datos[1]
            bot.answer_callback_query(call.id, f"Analizando {coin}...")
            analisis = obtener_analisis_mexc(coin, 'swap')
            
            rep = (
                "🔔 ANÁLISIS TÉCNICO 🔔\n"
                f"⚡ Activo MEXC: {coin}/USDT\n\n"
                f"💵 Precio Actual: ${analisis['precio']}\n\n"
                f"📊 MACRO (1H): {analisis['tendencia_1h']} | ADX: {analisis['adx_1h']} | RSI: {analisis['rsi_1h']}\n"
                f"📈 CORTO PLAZO (15M): {analisis['tendencia_15m']} | ADX: {analisis['adx_15m']} | RSI: {analisis['rsi_15m']}\n\n"
                f"🧱 Resistencia: ${analisis['resistencia']}\n"
                f"🟡 Soporte: ${analisis['soporte']}\n\n"
                f"🎯 SEÑAL:\n• {analisis['estado']}\n• {analisis['pausa']}"
            )
            bot.send_message(call.message.chat.id, rep, parse_mode="Markdown")

        elif call.data == "menu_futuros":
            bot.answer_callback_query(call.id, "Futuros MEXC...")
            m = InlineKeyboardMarkup(row_width=2)
            m.add(*[InlineKeyboardButton(f"⚡ {c}", callback_data=f"opc_fut_{c}") for c in MONEDAS_TRADING])
            bot.send_message(call.message.chat.id, "⚡ **Selecciona Activo para Futuros (MEXC):**", reply_markup=m, parse_mode="Markdown")

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
                bot.send_message(call.message.chat.id, f"⚙️ **Elige Apalancamiento para {coin} (MEXC):**", reply_markup=m_lev, parse_mode="Markdown")

        elif accion == "lev" and len(datos) == 3:
            coin, lev = datos[1], int(datos[2])
            bot.answer_callback_query(call.id, f"Tipo de orden para {coin}...")
            m_tipo = InlineKeyboardMarkup(row_width=2)
            m_tipo.add(
                InlineKeyboardButton("🚀 Mercado (Instantánea)", callback_data=f"tipo_fut_{coin}_{lev}_market"),
                InlineKeyboardButton("⏳ Límite (Precio Objetivo)", callback_data=f"tipo_fut_{coin}_{lev}_limit")
            )
            bot.send_message(call.message.chat.id, f"⚙️ **Selecciona el Tipo de Orden para {coin} ({lev}x):**", reply_markup=m_tipo, parse_mode="Markdown")

        elif accion == "tipo" and len(datos) == 5:
            coin, lev, tipo_o = datos[2], int(datos[3]), datos[4]
            if tipo_o == "market":
                bot.answer_callback_query(call.id, "Selecciona margen...")
                m_mar_fut = InlineKeyboardMarkup(row_width=3)
                m_mar_fut.add(
                    InlineKeyboardButton("$5", callback_data=f"ejec_fut_{coin}_{lev}_market_none_5"),
                    InlineKeyboardButton("$10", callback_data=f"ejec_fut_{coin}_{lev}_market_none_10"),
                    InlineKeyboardButton("$20", callback_data=f"ejec_fut_{coin}_{lev}_market_none_20")
                )
                bot.send_message(call.message.chat.id, f"💵 **Elige Margen para Mercado {coin} ({lev}x):**", reply_markup=m_mar_fut, parse_mode="Markdown")
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
                ordenes_abiertas.append({
                    'id': resultado.get('id'),
                    'coin': coin,
                    'mercado': mercado_ccxt,
                    'market_symbol': f"{coin}/USDT:USDT" if mercado_ccxt == 'swap' else f"{coin}/USDT",
                    'side': 'buy' if zona in ['none', 'soporte'] else 'sell',
                    'precio_entrada': precio,
                    'margen': margen_usado,
                    'apalancamiento': lev_usado
                })
                rep = (
                    f"✅ **¡ORDEN EJECUTADA CON ÉXITO!** ✅\n\n"
                    f"🪙 **Activo:** {coin}/USDT\n"
                    f"⚙️ **Mercado:** Futuros\n"
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

        elif accion == "aut" and len(datos) >= 4:
            if datos[1] == "cancelar":
                bot.answer_callback_query(call.id, "Operación cancelada.")
                bot.send_message(call.message.chat.id, "❌ **Operación cancelada por el usuario.**", parse_mode="Markdown")
                return
            
            coin = datos[1]
            tipo = datos[2]
            monto = float(datos[3])
            
            bot.answer_callback_query(call.id, f"Ejecutando {tipo} de {coin}...")
            msg_espera = bot.send_message(call.message.chat.id, f"⏳ **Ejecutando orden {tipo} para {coin}...**\nPor favor espera.", parse_mode="Markdown")
            
            side = 'buy' if tipo == 'COMPRA' else 'sell'
            
            exito, precio, margen_usado, lev_usado, tipo_usado, sl, tp, resultado = ejecutar_orden_con_gestion_riesgo_real(
                symbol=coin,
                mercado='swap',
                side=side,
                margen_usdt=monto,
                apalancamiento=10,
                tipo_orden='market',
                zona_precio=None
            )
            
            bot.delete_message(call.message.chat.id, msg_espera.message_id)
            
            if exito:
                direccion = "COMPRA (LONG) 🟢" if side == 'buy' else "VENTA (SHORT) 🔴"
                ordenes_abiertas.append({
                    'id': resultado.get('id'),
                    'coin': coin,
                    'mercado': 'swap',
                    'market_symbol': f"{coin}/USDT:USDT",
                    'side': side,
                    'precio_entrada': precio,
                    'margen': margen_usado,
                    'apalancamiento': lev_usado
                })
                rep = (
                    f"✅ **¡ORDEN AUTOMÁTICA EJECUTADA!** ✅\n\n"
                    f"🪙 **Activo:** {coin}/USDT\n"
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
    hilo_monitoreo = threading.Thread(target=bucle_monitoreo_ordenes, daemon=True)
    hilo_monitoreo.start()
    hilo_trading = threading.Thread(target=bucle_trading_automatico, daemon=True)
    hilo_trading.start()

if __name__ == "__main__":
    print("Iniciando Bot...")
    inicializar_mercados()
    iniciar_hilos()
    hilo_bot = threading.Thread(target=lambda: bot.infinity_polling(), daemon=True)
    hilo_bot.start()
    puerto = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=puerto)      