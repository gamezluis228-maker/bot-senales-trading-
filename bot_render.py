import json
import os
import re
import threading
import time

import ccxt
import numpy as np
import requests
import telebot
from flask import Flask
from telebot.types import InlineKeyboardButton, InlineKeyboardMarkup

# ---------------------------------------------------------------------------
# Secretos (Render "Secret Files" en /etc/secrets)
# ---------------------------------------------------------------------------
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

# ---------------------------------------------------------------------------
# Configuración
# ---------------------------------------------------------------------------
def _env_bool(nombre, defecto=False):
    valor = os.getenv(nombre)
    if valor is None:
        return defecto
    return valor.strip().lower() in ("1", "true", "yes", "si", "sí", "on")


def _env_int(nombres, defecto):
    for nombre in nombres:
        valor = os.getenv(nombre)
        if valor:
            try:
                return int(valor.strip())
            except ValueError:
                print(f"Aviso: {nombre} no es un número válido, se ignora.")
    return defecto


# ÚNICO usuario de Telegram que puede operar y recibir alertas.
# Se puede cambiar con la variable de entorno TELEGRAM_CHAT_ID.
CHAT_ID_AUTORIZADO = _env_int(["TELEGRAM_CHAT_ID", "CHAT_ID_AUTORIZADO"], 7115547861)
ULTIMO_CHAT_ID = CHAT_ID_AUTORIZADO

# MODO_DEMO=true  -> no se envía ninguna orden real a MEXC (todo simulado).
MODO_DEMO = _env_bool("MODO_DEMO", False)
# Margen aislado limita la pérdida de cada operación a su margen.
MODO_MARGEN = os.getenv("MODO_MARGEN", "isolated").strip().lower()
if MODO_MARGEN not in ("isolated", "cross"):
    MODO_MARGEN = "isolated"

LIMITE_PERDIDA_DIARIA = 10.0
MONTO_MINIMO_USDT = 5.0
SL_PCT = 0.04
TP_PCT = 0.08
TRAILING_PCT = 0.04
INTERVALO_MONITOREO = 20
VELAS = 100  # historial suficiente para RSI/ADX con suavizado de Wilder

MONEDAS_TRADING = ["BTC", "ETH", "SOL", "DOGE", "ZEC", "PEPE"]
MONEDAS_PREDICCION = ["BTC", "ETH", "SOL"]

ARCHIVO_ESTADO = "estado_bot.json"
ARCHIVO_REGISTRO = "registro_operaciones.txt"

# ---------------------------------------------------------------------------
# Estado compartido entre hilos
# ---------------------------------------------------------------------------
lock_estado = threading.RLock()
ordenes_abiertas = []
perdida_acumulada_dia = 0.0
fecha_actual = time.strftime("%Y-%m-%d")
ultimos_timestamps = {"BTC": 0, "ZEC": 0}
_clicks_recientes = {}


def guardar_estado():
    try:
        with lock_estado:
            datos = {
                "ordenes_abiertas": ordenes_abiertas,
                "perdida_acumulada_dia": perdida_acumulada_dia,
                "fecha_actual": fecha_actual,
            }
            tmp = ARCHIVO_ESTADO + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(datos, f)
            os.replace(tmp, ARCHIVO_ESTADO)
    except Exception as e:
        print(f"Error guardando estado: {e}")


def cargar_estado():
    global perdida_acumulada_dia, fecha_actual
    if not os.path.exists(ARCHIVO_ESTADO):
        return
    try:
        with open(ARCHIVO_ESTADO, "r", encoding="utf-8") as f:
            datos = json.load(f)
        with lock_estado:
            ordenes_abiertas[:] = datos.get("ordenes_abiertas", [])
            if datos.get("fecha_actual") == time.strftime("%Y-%m-%d"):
                perdida_acumulada_dia = float(datos.get("perdida_acumulada_dia", 0.0))
                fecha_actual = datos["fecha_actual"]
        print(f"Estado recuperado: {len(ordenes_abiertas)} orden(es) en seguimiento.")
    except Exception as e:
        print(f"Error cargando estado: {e}")


def _rotar_dia_si_corresponde():
    """Reinicia el contador de pérdidas al cambiar de día. Llamar con lock_estado tomado."""
    global perdida_acumulada_dia, fecha_actual
    hoy = time.strftime("%Y-%m-%d")
    if hoy != fecha_actual:
        perdida_acumulada_dia = 0.0
        fecha_actual = hoy


def limite_diario_alcanzado():
    with lock_estado:
        _rotar_dia_si_corresponde()
        return perdida_acumulada_dia >= LIMITE_PERDIDA_DIARIA


def registrar_perdida(monto):
    """Suma al contador diario SOLO pérdidas reales de operaciones cerradas."""
    global perdida_acumulada_dia
    if monto <= 0:
        return
    with lock_estado:
        _rotar_dia_si_corresponde()
        perdida_acumulada_dia += monto
    guardar_estado()


def anti_doble_click(clave, segundos=10):
    """Evita que un doble toque en un botón ejecute dos órdenes reales."""
    ahora = time.time()
    with lock_estado:
        for k in [k for k, t in _clicks_recientes.items() if ahora - t > 60]:
            del _clicks_recientes[k]
        if ahora - _clicks_recientes.get(clave, 0) < segundos:
            return False
        _clicks_recientes[clave] = ahora
        return True


# ---------------------------------------------------------------------------
# Utilidades de formato y mensajes
# ---------------------------------------------------------------------------
def fp(x):
    """Formatea precios sin perder decimales en monedas baratas (PEPE, DOGE)."""
    try:
        x = float(x)
    except (TypeError, ValueError):
        return str(x)
    if x == 0:
        return "0"
    if abs(x) >= 1:
        return f"{x:,.4f}".rstrip("0").rstrip(".")
    return f"{x:.8f}".rstrip("0").rstrip(".")


def redondear_sig(x, cifras=6):
    """Redondea a cifras significativas (round(x, 2) convertía el precio de PEPE en 0.0)."""
    try:
        return float(f"{float(x):.{cifras}g}")
    except (TypeError, ValueError):
        return 0.0


def enviar(chat_id, texto, **kwargs):
    """Envía con Markdown de Telegram (las **negritas** se convierten a *negritas*).
    Si Telegram rechaza el formato, reenvía en texto plano para no perder el aviso."""
    texto_md = re.sub(r"\*\*(.+?)\*\*", r"*\1*", texto, flags=re.S)
    try:
        return bot.send_message(chat_id, texto_md, parse_mode="Markdown", **kwargs)
    except Exception as e:
        print(f"Aviso: Markdown rechazado ({e}); reenviando como texto plano.")
        try:
            return bot.send_message(chat_id, texto.replace("**", "").replace("`", ""), **kwargs)
        except Exception as e2:
            print(f"Error enviando mensaje: {e2}")
            return None


def borrar_mensaje(chat_id, msg):
    if msg is None:
        return
    try:
        bot.delete_message(chat_id, msg.message_id)
    except Exception as e:
        print(f"No se pudo borrar el mensaje: {e}")


# ---------------------------------------------------------------------------
# Exchange
# ---------------------------------------------------------------------------
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
    ex = ccxt.mexc(config)
    # Reutiliza los mercados ya descargados para no pedirlos en cada instancia.
    base = globals().get("exchange_default")
    if base is not None and getattr(base, "markets", None):
        try:
            ex.set_markets(base.markets, getattr(base, "currencies", None))
        except Exception as e:
            print(f"Aviso al reutilizar mercados: {e}")
    return ex


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
            puerto = os.environ.get("PORT", 10000)
            url = RENDER_APP_URL if RENDER_APP_URL else f"http://127.0.0.1:{puerto}/"
            requests.get(url, timeout=10)
        except Exception as e:
            print(f"Error en Keep-Alive: {e}")
        time.sleep(600)


# ---------------------------------------------------------------------------
# Indicadores (suavizado de Wilder, sobre los datos MÁS RECIENTES)
# ---------------------------------------------------------------------------
def calcular_rsi(closes, period=14):
    closes = np.asarray(closes, dtype=float)
    if len(closes) < period + 1:
        return 50.0
    deltas = np.diff(closes)
    ganancias = np.where(deltas > 0, deltas, 0.0)
    perdidas = np.where(deltas < 0, -deltas, 0.0)
    prom_g = ganancias[:period].mean()
    prom_p = perdidas[:period].mean()
    for g, p in zip(ganancias[period:], perdidas[period:]):
        prom_g = (prom_g * (period - 1) + g) / period
        prom_p = (prom_p * (period - 1) + p) / period
    if prom_p == 0:
        return 100.0 if prom_g > 0 else 50.0
    rs = prom_g / prom_p
    return float(100 - (100 / (1 + rs)))


def calcular_adx(highs, lows, closes, period=14):
    """ADX real: DX suavizado con el método de Wilder. Necesita >= 2*period+1 velas."""
    highs = np.asarray(highs, dtype=float)
    lows = np.asarray(lows, dtype=float)
    closes = np.asarray(closes, dtype=float)
    if len(closes) < period * 2 + 1:
        return 15.0

    sube = highs[1:] - highs[:-1]
    baja = lows[:-1] - lows[1:]
    plus_dm = np.where((sube > baja) & (sube > 0), sube, 0.0)
    minus_dm = np.where((baja > sube) & (baja > 0), baja, 0.0)
    tr = np.maximum.reduce([
        highs[1:] - lows[1:],
        np.abs(highs[1:] - closes[:-1]),
        np.abs(lows[1:] - closes[:-1]),
    ])

    def dx_de(s_tr, s_p, s_m):
        if s_tr == 0:
            return 0.0
        pdi = 100 * s_p / s_tr
        mdi = 100 * s_m / s_tr
        suma = pdi + mdi
        return 0.0 if suma == 0 else 100 * abs(pdi - mdi) / suma

    s_tr, s_p, s_m = tr[:period].sum(), plus_dm[:period].sum(), minus_dm[:period].sum()
    dxs = [dx_de(s_tr, s_p, s_m)]
    for i in range(period, len(tr)):
        s_tr = s_tr - s_tr / period + tr[i]
        s_p = s_p - s_p / period + plus_dm[i]
        s_m = s_m - s_m / period + minus_dm[i]
        dxs.append(dx_de(s_tr, s_p, s_m))

    adx = float(np.mean(dxs[:period]))
    for dx in dxs[period:]:
        adx = (adx * (period - 1) + dx) / period
    return float(adx)


def obtener_tendencia_4h(symbol, mercado='swap'):
    try:
        ex = crear_instancia_exchange(mercado)
        market_symbol = f"{symbol}/USDT:USDT" if mercado == 'swap' else f"{symbol}/USDT"
        ohlcv_4h = ex.fetch_ohlcv(market_symbol, timeframe='4h', limit=VELAS)
        closes_4h = [x[4] for x in ohlcv_4h]
        highs_4h = [x[2] for x in ohlcv_4h]
        lows_4h = [x[3] for x in ohlcv_4h]
        tendencia_4h = "ALCISTA 🟢" if closes_4h[-1] > closes_4h[-10] else "BAJISTA 🔴"
        adx_4h = calcular_adx(highs_4h, lows_4h, closes_4h)
        rsi_4h = calcular_rsi(closes_4h)
        return {"tendencia": tendencia_4h, "adx": round(adx_4h, 1), "rsi": round(rsi_4h, 1), "precio": closes_4h[-1]}
    except Exception as e:
        print(f"Error obteniendo tendencia 4H de {symbol}: {e}")
        return {"tendencia": "ERROR", "adx": 0.0, "rsi": 0.0, "precio": 0.0}


def obtener_sentimiento_mercado():
    try:
        url = "https://api.alternative.me/fng/?limit=1"
        response = requests.get(url, timeout=10)
        data = response.json()
        if data and 'data' in data and len(data['data']) > 0:
            valor = int(data['data'][0]['value'])
            clasificacion = data['data'][0]['value_classification']
            traduccion = {
                "Extreme Fear": "MIEDO EXTREMO 😱",
                "Fear": "MIEDO 😨",
                "Neutral": "NEUTRAL 😐",
                "Greed": "CODICIA 🤑",
                "Extreme Greed": "CODICIA EXTREMA 🚀"
            }
            return {"valor": valor, "clasificacion": traduccion.get(clasificacion, clasificacion)}
    except Exception as e:
        print(f"Error obteniendo sentimiento: {e}")
    return {"valor": 50, "clasificacion": "NEUTRAL 😐"}


def calcular_trailing_stop(precio_entrada, precio_actual, lado, porcentaje_trailing=TRAILING_PCT):
    if lado == 'buy':
        trailing_sl = precio_actual * (1 - porcentaje_trailing)
        return max(trailing_sl, precio_entrada * (1 - SL_PCT))
    trailing_sl = precio_actual * (1 + porcentaje_trailing)
    return min(trailing_sl, precio_entrada * (1 + SL_PCT))


def registrar_operacion(coin, tipo_orden, lado, precio_entrada, margen, apalancamiento, sl, tp, id_orden, estado='ABIERTA'):
    try:
        fecha = time.strftime("%Y-%m-%d %H:%M:%S")
        linea = (f"{fecha} | {coin} | {tipo_orden} | {lado} | Entrada: {precio_entrada} | Margen: {margen} | "
                 f"Apal: {apalancamiento}x | SL: {sl} | TP: {tp} | ID: {id_orden} | Estado: {estado}\n")
        with open(ARCHIVO_REGISTRO, "a", encoding="utf-8") as f:
            f.write(linea)
        print(f"Operación registrada: {coin} - {lado}")
    except Exception as e:
        print(f"Error al registrar operación: {e}")


# ---------------------------------------------------------------------------
# Análisis y señales
# ---------------------------------------------------------------------------
def obtener_analisis_mexc(symbol, mercado='swap'):
    try:
        ex = crear_instancia_exchange(mercado)
        market_symbol = f"{symbol}/USDT:USDT" if mercado == 'swap' else f"{symbol}/USDT"
        ohlcv_1h = ex.fetch_ohlcv(market_symbol, timeframe='1h', limit=VELAS)
        closes_1h, highs_1h, lows_1h = [x[4] for x in ohlcv_1h], [x[2] for x in ohlcv_1h], [x[3] for x in ohlcv_1h]
        ohlcv_15m = ex.fetch_ohlcv(market_symbol, timeframe='15m', limit=VELAS)
        closes_15m, highs_15m, lows_15m = [x[4] for x in ohlcv_15m], [x[2] for x in ohlcv_15m], [x[3] for x in ohlcv_15m]
        adx_15m = calcular_adx(highs_15m, lows_15m, closes_15m)
        lateral = adx_15m < 20
        estado_mercado = "MERCADO LATERAL / RANGO EN 15M (ADX < 20)" if lateral else "TENDENCIA ACTIVA EN 15M"
        pausa_texto = "Precaución: Rango plano en corto plazo." if lateral else "Estructura de 15m con fuerza tendencial."
        return {
            "precio": closes_1h[-1],
            "tendencia_1h": "ALCISTA 🟢" if closes_1h[-1] > closes_1h[-10] else "BAJISTA 🔴",
            "adx_1h": round(calcular_adx(highs_1h, lows_1h, closes_1h), 1),
            "rsi_1h": round(calcular_rsi(closes_1h), 1),
            "tendencia_15m": "ALCISTA 🟢" if closes_15m[-1] > closes_15m[-10] else "BAJISTA 🔴",
            "adx_15m": round(adx_15m, 1),
            "rsi_15m": round(calcular_rsi(closes_15m), 1),
            "resistencia": redondear_sig(max(highs_1h[-10:])),
            "soporte": redondear_sig(min(lows_1h[-10:])),
            "estado": estado_mercado,
            "pausa": pausa_texto
        }
    except Exception as e:
        return {"precio": 0.0, "tendencia_1h": "ERROR", "adx_1h": 0.0, "rsi_1h": 0.0, "tendencia_15m": "ERROR", "adx_15m": 0.0, "rsi_15m": 0.0, "resistencia": 0.0, "soporte": 0.0, "estado": "FALLA EN EXCHANGE", "pausa": str(e)}


def detectar_rompimiento(symbol, mercado='swap'):
    """
    Detecta 4 escenarios con 3 filtros, siempre sobre la ÚLTIMA VELA CERRADA de 1H
    (la vela en formación se descarta: su volumen y mechas aún no son definitivos).
    1. Rompimiento REAL de resistencia -> COMPRA (LONG)
    2. Rompimiento REAL de soporte -> VENTA (SHORT)
    3. Falso rompimiento de resistencia (mecha arriba) -> VENTA (SHORT)
    4. Falso rompimiento de soporte (mecha abajo) -> COMPRA (LONG)

    Filtros aplicados:
    - RSI: no compra si >75, no venta si <25
    - Mecha: no compra si mecha sup grande, no venta si mecha inf grande
    - Extensión: no compra si ya subió >3% en 3 velas, no venta si ya bajó >3%
    """
    try:
        ex = crear_instancia_exchange(mercado)
        market_symbol = f"{symbol}/USDT:USDT" if mercado == 'swap' else f"{symbol}/USDT"

        ohlcv_1h = ex.fetch_ohlcv(market_symbol, timeframe='1h', limit=VELAS)
        ohlcv_1h = ohlcv_1h[:-1]  # descarta la vela aún abierta
        if len(ohlcv_1h) < 30:
            return None

        marcas_tiempo = [x[0] for x in ohlcv_1h]
        opens_1h = [x[1] for x in ohlcv_1h]
        highs_1h = [x[2] for x in ohlcv_1h]
        lows_1h = [x[3] for x in ohlcv_1h]
        closes_1h = [x[4] for x in ohlcv_1h]
        volumes_1h = [x[5] for x in ohlcv_1h]

        adx_1h = calcular_adx(highs_1h, lows_1h, closes_1h)
        rsi_1h = calcular_rsi(closes_1h)

        resistencia = max(highs_1h[-11:-1])
        soporte = min(lows_1h[-11:-1])

        volumen_promedio = sum(volumes_1h[-11:-1]) / 10
        volumen_actual = volumes_1h[-1]
        precio_actual = closes_1h[-1]
        precio_anterior = closes_1h[-2]
        high_actual = highs_1h[-1]
        low_actual = lows_1h[-1]
        open_actual = opens_1h[-1]

        cuerpo = abs(precio_actual - open_actual)
        mecha_superior = high_actual - max(precio_actual, open_actual)
        mecha_inferior = min(precio_actual, open_actual) - low_actual

        precio_hace3 = closes_1h[-4]
        cambio_3_velas = ((precio_actual - precio_hace3) / precio_hace3) * 100

        t4h = obtener_tendencia_4h(symbol, mercado)

        info_base = {
            'symbol': symbol,
            'ts_vela': marcas_tiempo[-1],
            'precio': precio_actual,
            'precio_anterior': precio_anterior,
            'resistencia': resistencia,
            'soporte': soporte,
            'adx': round(adx_1h, 1),
            'rsi': round(rsi_1h, 1),
            'volumen': volumen_actual,
            'volumen_promedio': volumen_promedio,
            'tendencia_4h': t4h['tendencia'],
            'adx_4h': t4h['adx'],
            'rsi_4h': t4h['rsi'],
            'high_actual': high_actual,
            'low_actual': low_actual,
            'mecha_superior': mecha_superior,
            'mecha_inferior': mecha_inferior,
            'cuerpo': cuerpo,
            'cambio_3_velas': round(cambio_3_velas, 2)
        }

        # ESCENARIO 1: ROMPIMIENTO REAL DE RESISTENCIA -> COMPRA
        if (precio_actual > resistencia and
                precio_anterior <= resistencia and
                volumen_actual > volumen_promedio and
                mecha_superior < cuerpo * 1.5 and
                rsi_1h < 75 and
                cambio_3_velas < 3.0):
            info_base['tipo'] = 'COMPRA'
            info_base['subtipo'] = 'ROMPIMIENTO_REAL_RESISTENCIA'
            info_base['direccion'] = 'LONG'
            info_base['emoji'] = '🟢'
            info_base['descripcion'] = 'Rompió resistencia REAL con volumen alto'
            return info_base

        # ESCENARIO 2: ROMPIMIENTO REAL DE SOPORTE -> VENTA
        if (precio_actual < soporte and
                precio_anterior >= soporte and
                volumen_actual > volumen_promedio and
                mecha_inferior < cuerpo * 1.5 and
                rsi_1h > 25 and
                cambio_3_velas > -3.0):
            info_base['tipo'] = 'VENTA'
            info_base['subtipo'] = 'ROMPIMIENTO_REAL_SOPORTE'
            info_base['direccion'] = 'SHORT'
            info_base['emoji'] = '🔴'
            info_base['descripcion'] = 'Rompió soporte REAL con volumen alto'
            return info_base

        # ESCENARIO 3: FALSO ROMPIMIENTO DE RESISTENCIA -> VENTA
        if (high_actual > resistencia and
                precio_actual < resistencia and
                precio_anterior < resistencia and
                mecha_superior > cuerpo * 1.5):
            info_base['tipo'] = 'VENTA'
            info_base['subtipo'] = 'FALSO_ROMPIMIENTO_RESISTENCIA'
            info_base['direccion'] = 'SHORT'
            info_base['emoji'] = '🔴'
            info_base['descripcion'] = 'Falso rompimiento de resistencia (mecha arriba) → VENTA'
            return info_base

        # ESCENARIO 4: FALSO ROMPIMIENTO DE SOPORTE -> COMPRA
        if (low_actual < soporte and
                precio_actual > soporte and
                precio_anterior > soporte and
                mecha_inferior > cuerpo * 1.5):
            info_base['tipo'] = 'COMPRA'
            info_base['subtipo'] = 'FALSO_ROMPIMIENTO_SOPORTE'
            info_base['direccion'] = 'LONG'
            info_base['emoji'] = '🟢'
            info_base['descripcion'] = 'Falso rompimiento de soporte (mecha abajo) → COMPRA'
            return info_base

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
                        t4h = obtener_tendencia_4h(coin, 'swap')
                        sentimiento = obtener_sentimiento_mercado()
                        titulo_activo = f"Activo MEXC: {coin}/USDT"

                        rep = (
                            "🔔 REPORTE AUTOMÁTICO CIERRE 15M / 1H 🔔\n"
                            f"⚡ {titulo_activo}\n\n"
                            f"💵 Precio Actual: ${fp(a['precio'])}\n\n"
                            f"📊 MACRO (1H): {a['tendencia_1h']} | ADX: {a['adx_1h']} | RSI: {a['rsi_1h']}\n"
                            f"📈 MACRO (4H): {t4h['tendencia']} | ADX: {t4h['adx']} | RSI: {t4h['rsi']}\n"
                            f"📉 CORTO PLAZO (15M): {a['tendencia_15m']} | ADX: {a['adx_15m']} | RSI: {a['rsi_15m']}\n\n"
                            f"😱 **SENTIMIENTO:** {sentimiento['clasificacion']} ({sentimiento['valor']}/100)\n\n"
                            f"🧱 Resistencia: ${fp(a['resistencia'])}\n"
                            f"🟡 Soporte: ${fp(a['soporte'])}\n\n"
                            f"🎯 SEÑAL:\n• {a['estado']}\n• {a['pausa']}"
                        )

                        if ULTIMO_CHAT_ID:
                            enviar(ULTIMO_CHAT_ID, rep)
                time.sleep(60)
        except Exception as e:
            print(f"Error en bucle automático: {e}")
        time.sleep(15)


def bucle_trading_automatico():
    time.sleep(20)
    ultima_senal = {}  # coin -> (timestamp de la vela, subtipo) ya avisado
    while True:
        try:
            tiempo_actual = time.localtime()
            if tiempo_actual.tm_min in [0, 15, 30, 45]:
                now_ts = time.time()
                for coin in MONEDAS_TRADING:
                    senal = detectar_rompimiento(coin, 'swap')
                    if not senal or senal['tipo'] not in ['COMPRA', 'VENTA']:
                        continue
                    # Una misma vela cerrada no debe avisar 4 veces por hora.
                    clave = (senal['ts_vela'], senal['subtipo'])
                    if ultima_senal.get(coin) == clave:
                        continue
                    ultima_senal[coin] = clave

                    tipo = senal['tipo']
                    t4h = obtener_tendencia_4h(coin, 'swap')
                    sentimiento = obtener_sentimiento_mercado()
                    emoji = "🟢" if tipo == 'COMPRA' else "🔴"
                    direccion = "COMPRA (LONG)" if tipo == 'COMPRA' else "VENTA (SHORT)"

                    m = InlineKeyboardMarkup(row_width=2)
                    m.add(
                        InlineKeyboardButton("✅ Sí, operar", callback_data=f"conf_{coin}_{tipo}"),
                        InlineKeyboardButton("❌ No operar", callback_data=f"conf_no_{coin}_{tipo}")
                    )
                    rep = (
                        f"🚨 **SEÑAL DETECTADA** 🚨\n\n"
                        f"{emoji} **{senal['descripcion']}**\n"
                        f"🪙 **Activo:** {coin}/USDT\n"
                        f"💵 **Precio (cierre 1H):** ${fp(senal['precio'])}\n\n"
                        f"🧱 **Resistencia:** ${fp(senal['resistencia'])}\n"
                        f"🟡 **Soporte:** ${fp(senal['soporte'])}\n\n"
                        f"📊 **ADX (1H):** {senal['adx']} | **RSI (1H):** {senal['rsi']}\n"
                        f"📊 **Volumen:** {senal['volumen']:.0f} (promedio: {senal['volumen_promedio']:.0f})\n"
                        f"📏 **Mecha Sup:** {fp(senal['mecha_superior'])} | **Mecha Inf:** {fp(senal['mecha_inferior'])}\n"
                        f"📈 **Cambio 3 velas:** {senal['cambio_3_velas']}%\n\n"
                        f"📈 **Tendencia 4H:** {t4h['tendencia']} (ADX: {t4h['adx']} | RSI: {t4h['rsi']})\n"
                        f"😱 **Sentimiento:** {sentimiento['clasificacion']} ({sentimiento['valor']}/100)\n\n"
                        f"🎯 **Dirección sugerida:** {direccion}\n\n"
                        f"¿Quieres operar?"
                    )
                    if ULTIMO_CHAT_ID:
                        enviar(ULTIMO_CHAT_ID, rep, reply_markup=m)
                time.sleep(60)
        except Exception as e:
            print(f"Error en bucle de trading automático: {e}")
        time.sleep(15)


def analizar_prediccion_5m(symbol):
    try:
        ex = crear_instancia_exchange('swap')
        market_symbol = f"{symbol}/USDT:USDT"

        ohlcv_5m = ex.fetch_ohlcv(market_symbol, timeframe='5m', limit=VELAS)
        closes_5m = [x[4] for x in ohlcv_5m]
        highs_5m = [x[2] for x in ohlcv_5m]
        lows_5m = [x[3] for x in ohlcv_5m]
        volumes_5m = [x[5] for x in ohlcv_5m]

        adx_5m = calcular_adx(highs_5m, lows_5m, closes_5m)
        rsi_5m = calcular_rsi(closes_5m)

        precio_actual = closes_5m[-1]
        precio_anterior = closes_5m[-2]
        precio_hace5 = closes_5m[-6]

        volumen_promedio = sum(volumes_5m[-11:-1]) / 10
        volumen_actual = volumes_5m[-1]

        sma5 = sum(closes_5m[-5:]) / 5
        sma10 = sum(closes_5m[-10:]) / 10

        puntos_alcista = 0
        puntos_bajista = 0

        if precio_actual > sma5:
            puntos_alcista += 1
        else:
            puntos_bajista += 1

        if sma5 > sma10:
            puntos_alcista += 1
        else:
            puntos_bajista += 1

        if rsi_5m > 55:
            puntos_alcista += 1
        elif rsi_5m < 45:
            puntos_bajista += 1

        if adx_5m > 20:
            if precio_actual > precio_anterior:
                puntos_alcista += 1
            else:
                puntos_bajista += 1

        if volumen_actual > volumen_promedio:
            if precio_actual > precio_anterior:
                puntos_alcista += 1
            else:
                puntos_bajista += 1

        if precio_actual > precio_hace5:
            puntos_alcista += 1
        else:
            puntos_bajista += 1

        if puntos_alcista > puntos_bajista:
            prediccion = "VA A SUBIR 📈"
            emoji = "🟢"
        elif puntos_bajista > puntos_alcista:
            prediccion = "VA A BAJAR 📉"
            emoji = "🔴"
        else:
            prediccion = "LATERAL / SIN DIRECCIÓN CLARA 😐"
            emoji = "🟡"

        return {
            'symbol': symbol,
            'precio': precio_actual,
            'prediccion': prediccion,
            'emoji': emoji,
            'rsi': round(rsi_5m, 1),
            'adx': round(adx_5m, 1),
            'sma5': redondear_sig(sma5),
            'sma10': redondear_sig(sma10),
            'puntos_alcista': puntos_alcista,
            'puntos_bajista': puntos_bajista,
            'volumen': volumen_actual,
            'volumen_promedio': volumen_promedio
        }
    except Exception as e:
        print(f"Error en predicción 5m de {symbol}: {e}")
        return None


# ---------------------------------------------------------------------------
# Ejecución de órdenes
# ---------------------------------------------------------------------------
def ejecutar_orden_con_gestion_riesgo_real(symbol, mercado, side, margen_usdt, apalancamiento=1, tipo_orden='market', zona_precio=None):
    """Devuelve un dict. Éxito: {'ok': True, ...datos de la orden...}. Fallo: {'ok': False, 'error': texto}."""
    try:
        api, secret = obtener_credenciales_mexc()
        if not MODO_DEMO and (not api or not secret):
            return {'ok': False, 'error': "❌ **Error:** Faltan las credenciales de MEXC."}

        if limite_diario_alcanzado():
            return {'ok': False, 'error': f"🛑 **BLOQUEO POR PÉRDIDA DIARIA:** Has alcanzado el límite de ${LIMITE_PERDIDA_DIARIA} USD."}

        ex = crear_instancia_exchange(mercado)
        ex.load_markets()
        market_symbol = f"{symbol}/USDT:USDT" if mercado == 'swap' else f"{symbol}/USDT"

        analisis = obtener_analisis_mexc(symbol, mercado)
        precio_actual = analisis['precio']
        if not precio_actual or precio_actual <= 0:
            return {'ok': False, 'error': f"⚠️ **Sin precio:** no se pudo leer el precio de {symbol} ({analisis['pausa']})."}

        precio_objetivo = precio_actual
        if tipo_orden == 'limit' and zona_precio:
            if zona_precio == 'soporte':
                precio_objetivo = analisis['soporte']
                side = 'buy'
            elif zona_precio == 'resistencia':
                precio_objetivo = analisis['resistencia']
                side = 'sell'
        if not precio_objetivo or precio_objetivo <= 0:
            return {'ok': False, 'error': "⚠️ **Precio objetivo inválido** para la orden límite."}

        if side == 'buy':
            stop_loss = float(ex.price_to_precision(market_symbol, precio_objetivo * (1 - SL_PCT)))
            take_profit = float(ex.price_to_precision(market_symbol, precio_objetivo * (1 + TP_PCT)))
        else:
            stop_loss = float(ex.price_to_precision(market_symbol, precio_objetivo * (1 + SL_PCT)))
            take_profit = float(ex.price_to_precision(market_symbol, precio_objetivo * (1 - TP_PCT)))

        # Tamaño: el margen se multiplica por el apalancamiento (antes la orden de mercado lo ignoraba).
        monto_total_operacion = margen_usdt * apalancamiento
        if monto_total_operacion < MONTO_MINIMO_USDT:
            return {'ok': False, 'error': f"⚠️ **MONTO INSUFICIENTE:** El monto total (${monto_total_operacion:.2f} USDT) es menor al mínimo (${MONTO_MINIMO_USDT} USDT)."}

        # En futuros MEXC la cantidad va en CONTRATOS, no en tokens.
        tamano_contrato = float(ex.market(market_symbol).get('contractSize') or 1)
        cantidad_contratos = monto_total_operacion / precio_objetivo / tamano_contrato
        cantidad = float(ex.amount_to_precision(market_symbol, cantidad_contratos))
        if cantidad <= 0:
            return {'ok': False, 'error': "⚠️ **ERROR DE CÁLCULO:** El monto es menor que el tamaño mínimo de contrato de este activo."}

        if mercado == 'swap' and not MODO_DEMO:
            try:
                ex.set_leverage(apalancamiento, market_symbol, {
                    'openType': 1 if MODO_MARGEN == 'isolated' else 2,
                    'positionType': 1 if side == 'buy' else 2,
                })
            except Exception as e:
                print(f"Aviso de apalancamiento: {e}")

        params = {}
        if mercado == 'swap':
            params = {
                'leverage': apalancamiento,
                'marginMode': MODO_MARGEN,
                'stopLoss': {'triggerPrice': stop_loss},
                'takeProfit': {'triggerPrice': take_profit},
            }

        if MODO_DEMO:
            orden = {'id': f"DEMO-{int(time.time() * 1000)}"}
        elif tipo_orden == 'market':
            orden = ex.create_order(market_symbol, 'market', side, cantidad, None, params)
        else:
            precio_limite = float(ex.price_to_precision(market_symbol, precio_objetivo))
            orden = ex.create_order(market_symbol, 'limit', side, cantidad, precio_limite, params)

        if tipo_orden == 'market':
            precio_entrada = float(orden.get('average') or orden.get('price') or precio_actual)
        else:
            precio_entrada = float(precio_objetivo)

        return {
            'ok': True,
            'demo': MODO_DEMO,
            'id': orden.get('id') or 'N/A',
            'side': side,
            'precio': precio_entrada,
            'margen': margen_usdt,
            'apalancamiento': apalancamiento,
            'tipo': tipo_orden,
            'sl': stop_loss,
            'tp': take_profit,
            'cantidad': cantidad,
            'estado': 'ABIERTA' if tipo_orden == 'market' else 'PENDIENTE',
        }
    except Exception as e:
        error_str = str(e)
        if "minimum amount" in error_str or "minimum" in error_str:
            mensaje_amigable = "❌ **Error en MEXC:** El monto es menor al mínimo permitido (5 USDT)."
        elif "balance" in error_str.lower() or "insufficient" in error_str.lower():
            mensaje_amigable = "❌ **Error en MEXC:** Saldo insuficiente en la billetera."
        else:
            mensaje_amigable = f"❌ **Error en MEXC:** {error_str}"
        return {'ok': False, 'error': mensaje_amigable}


def registrar_orden_abierta(coin, mercado, res):
    info = {
        'id': res['id'],
        'coin': coin,
        'mercado': mercado,
        'market_symbol': f"{coin}/USDT:USDT" if mercado == 'swap' else f"{coin}/USDT",
        'side': res['side'],
        'precio_entrada': res['precio'],
        'margen': res['margen'],
        'apalancamiento': res['apalancamiento'],
        'sl_inicial': res['sl'],
        'sl_actual': res['sl'],
        'tp': res['tp'],
        'cantidad': res['cantidad'],
        'estado': res['estado'],
        'demo': res['demo'],
        'abierta_ts': time.time(),
        'fallos_posicion': 0,
    }
    with lock_estado:
        ordenes_abiertas.append(info)
    guardar_estado()
    registrar_operacion(coin, res['tipo'], res['side'], res['precio'], res['margen'],
                        res['apalancamiento'], res['sl'], res['tp'], res['id'], res['estado'])


def texto_orden_ejecutada(coin, res, titulo):
    direccion = "COMPRA (LONG) 🟢" if res['side'] == 'buy' else "VENTA (SHORT) 🔴"
    demo = "🧪 **MODO DEMO — no se envió ninguna orden real**\n\n" if res['demo'] else ""
    estado = "⏳ Pendiente (orden límite esperando precio)" if res['estado'] == 'PENDIENTE' else "🟢 Abierta"
    return (
        f"{titulo}\n\n{demo}"
        f"🪙 **Activo:** {coin}/USDT\n"
        f"📈 **Dirección:** {direccion}\n"
        f"💵 **Precio de Entrada:** ${fp(res['precio'])}\n"
        f"💰 **Margen:** ${res['margen']} USDT\n"
        f"⚡ **Apalancamiento:** {res['apalancamiento']}x\n"
        f"📋 **Tipo:** {res['tipo'].upper()}\n"
        f"📌 **Estado:** {estado}\n\n"
        f"🛑 **Stop Loss:** ${fp(res['sl'])}\n"
        f"🎯 **Take Profit:** ${fp(res['tp'])}\n"
        f"📊 **Trailing Stop:** ACTIVO ({TRAILING_PCT * 100:.0f}%, lo gestiona el bot)\n\n"
        f"🆔 **ID de Orden:** `{res['id']}`"
    )


# ---------------------------------------------------------------------------
# Seguimiento de posiciones (trailing stop gestionado por el bot)
# ---------------------------------------------------------------------------
def precio_ultimo(ex, market_symbol):
    return float(ex.fetch_ticker(market_symbol)['last'])


def cerrar_posicion_mercado(info, ex):
    """Cierra la posición a mercado (reduceOnly). Devuelve el precio de salida."""
    if info.get('demo'):
        return precio_ultimo(ex, info['market_symbol'])
    side_cierre = 'sell' if info['side'] == 'buy' else 'buy'
    orden = ex.create_order(info['market_symbol'], 'market', side_cierre, info['cantidad'], None, {'reduceOnly': True})
    precio = orden.get('average') or orden.get('price')
    if not precio:
        precio = precio_ultimo(ex, info['market_symbol'])
    return float(precio)


def quitar_orden(info):
    with lock_estado:
        if info in ordenes_abiertas:
            ordenes_abiertas.remove(info)
    guardar_estado()


def finalizar_orden(info, precio_salida, motivo, estimado=False):
    lado = info['side']
    entrada = info['precio_entrada']
    if lado == 'buy':
        pnl_pct = ((precio_salida - entrada) / entrada) * 100
    else:
        pnl_pct = ((entrada - precio_salida) / entrada) * 100
    pnl_usdt = info['margen'] * info['apalancamiento'] * (pnl_pct / 100)
    emoji_resultado = "🟢 GANANCIA" if pnl_usdt > 0 else "🔴 PÉRDIDA"

    if pnl_usdt < 0:
        registrar_perdida(-pnl_usdt)

    demo = "🧪 **MODO DEMO**\n\n" if info.get('demo') else ""
    aprox = " (estimado)" if estimado else ""
    reporte = (
        f"🎯 **OPERACIÓN CERRADA** 🎯\n\n{demo}"
        f"🪙 **Activo:** {info['coin']}/USDT\n"
        f"📌 **Motivo:** {motivo}\n"
        f"📈 **Dirección:** {'COMPRA (LONG) 🟢' if lado == 'buy' else 'VENTA (SHORT) 🔴'}\n"
        f"💵 **Precio Entrada:** ${fp(entrada)}\n"
        f"💵 **Precio Salida:** ${fp(precio_salida)}{aprox}\n"
        f"💰 **Margen:** ${info['margen']} USDT\n"
        f"⚡ **Apalancamiento:** {info['apalancamiento']}x\n\n"
        f"{emoji_resultado}: **${pnl_usdt:.2f} USDT** ({pnl_pct:+.2f}%)\n\n"
        f"🆔 **ID:** `{info['id']}`"
    )
    if ULTIMO_CHAT_ID:
        enviar(ULTIMO_CHAT_ID, reporte)

    registrar_operacion(info['coin'], 'market', lado, entrada, info['margen'], info['apalancamiento'],
                        info.get('sl_actual', 0), info.get('tp', 0), info['id'], 'CERRADA')
    quitar_orden(info)

    if limite_diario_alcanzado() and ULTIMO_CHAT_ID:
        enviar(ULTIMO_CHAT_ID, f"🛑 **Límite de pérdida diaria alcanzado (${LIMITE_PERDIDA_DIARIA}).** "
                               "No se abrirán nuevas operaciones hasta mañana.")


def revisar_orden(info):
    ex = crear_instancia_exchange(info['mercado'])
    sym = info['market_symbol']
    lado = info['side']
    ahora = time.time()
    precio = precio_ultimo(ex, sym)

    # --- Orden límite aún sin llenar ---
    if info.get('estado') == 'PENDIENTE':
        if info.get('demo'):
            lleno = precio <= info['precio_entrada'] if lado == 'buy' else precio >= info['precio_entrada']
            entrada = info['precio_entrada']
        else:
            orden = ex.fetch_order(info['id'], sym)
            estado = orden.get('status')
            if estado in ('canceled', 'cancelled', 'expired', 'rejected'):
                if ULTIMO_CHAT_ID:
                    enviar(ULTIMO_CHAT_ID, f"⚠️ La orden límite de {info['coin']} fue cancelada en MEXC sin ejecutarse.")
                registrar_operacion(info['coin'], 'limit', lado, info['precio_entrada'], info['margen'],
                                    info['apalancamiento'], info['sl_inicial'], info.get('tp', 0), info['id'], 'CANCELADA')
                quitar_orden(info)
                return
            lleno = estado == 'closed'
            entrada = float(orden.get('average') or orden.get('price') or info['precio_entrada'])
        if not lleno:
            return
        info['estado'] = 'ABIERTA'
        info['precio_entrada'] = entrada
        info['abierta_ts'] = ahora
        info['fallos_posicion'] = 0
        guardar_estado()
        if ULTIMO_CHAT_ID:
            enviar(ULTIMO_CHAT_ID, f"✅ **Orden límite ejecutada:** {info['coin']} entró a ${fp(entrada)}. Trailing Stop activo.")
        return

    # --- Posición abierta: trailing stop y take profit ---
    nuevo_sl = calcular_trailing_stop(info['precio_entrada'], precio, lado, TRAILING_PCT)
    sl_actual = info.get('sl_actual', info['sl_inicial'])
    if (lado == 'buy' and nuevo_sl > sl_actual) or (lado == 'sell' and nuevo_sl < sl_actual):
        print(f"Trailing Stop {info['coin']}: {fp(sl_actual)} → {fp(nuevo_sl)}")
        info['sl_actual'] = nuevo_sl
        sl_actual = nuevo_sl
        guardar_estado()

    tp = info.get('tp')
    motivo = None
    if lado == 'buy':
        if precio <= sl_actual:
            motivo = "Stop Loss / Trailing Stop"
        elif tp and precio >= tp:
            motivo = "Take Profit"
    else:
        if precio >= sl_actual:
            motivo = "Stop Loss / Trailing Stop"
        elif tp and precio <= tp:
            motivo = "Take Profit"

    if motivo:
        try:
            precio_salida = cerrar_posicion_mercado(info, ex)
        except Exception as e:
            print(f"Error cerrando {info['coin']}: {e}")
            if not info.get('aviso_error_cierre') and ULTIMO_CHAT_ID:
                info['aviso_error_cierre'] = True
                enviar(ULTIMO_CHAT_ID, f"⚠️ **No pude cerrar {info['coin']} ({motivo}).** Revisa la posición en MEXC. Error: {e}")
            return
        finalizar_orden(info, precio_salida, motivo)
        return

    # --- ¿La posición ya no existe en MEXC (SL/TP del exchange o cierre manual)? ---
    if info['mercado'] == 'swap' and not info.get('demo') and ahora - info.get('abierta_ts', 0) > 30:
        try:
            posiciones = ex.fetch_positions([sym])
            lado_pos = 'long' if lado == 'buy' else 'short'
            sigue = any(float(p.get('contracts') or 0) > 0 and p.get('side') == lado_pos for p in posiciones)
        except Exception as e:
            print(f"No se pudo consultar la posición de {info['coin']}: {e}")
            return
        if sigue:
            info['fallos_posicion'] = 0
        else:
            info['fallos_posicion'] = info.get('fallos_posicion', 0) + 1
            if info['fallos_posicion'] >= 2:
                finalizar_orden(info, precio, "Cerrada en MEXC (SL/TP del exchange o manual)", estimado=True)


def bucle_monitoreo_ordenes():
    time.sleep(30)
    while True:
        try:
            with lock_estado:
                lista = list(ordenes_abiertas)
            for info in lista:
                try:
                    revisar_orden(info)
                except Exception as e:
                    print(f"Error monitoreando orden {info.get('id', '?')}: {e}")
        except Exception as e:
            print(f"Error en bucle de monitoreo: {e}")
        time.sleep(INTERVALO_MONITOREO)


# ---------------------------------------------------------------------------
# Telegram: autorización y comandos
# ---------------------------------------------------------------------------
def autorizado_mensaje(message):
    usuario = getattr(message, 'from_user', None)
    if usuario is not None and usuario.id == CHAT_ID_AUTORIZADO:
        return True
    print(f"Acceso denegado a usuario {getattr(usuario, 'id', '?')}")
    try:
        bot.send_message(message.chat.id, "⛔ No autorizado.")
    except Exception:
        pass
    return False


@bot.message_handler(commands=['start', 'menu'])
def mostrar_menu_principal(message):
    if not autorizado_mensaje(message):
        return
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("⚡ BTC", callback_data="ver_BTC"),
        InlineKeyboardButton("💎 ETH", callback_data="ver_ETH"),
        InlineKeyboardButton("🟣 SOL", callback_data="ver_SOL"),
        InlineKeyboardButton("🟠 DOGE", callback_data="ver_DOGE"),
        InlineKeyboardButton("🟡 ZEC", callback_data="ver_ZEC"),
        InlineKeyboardButton("🐸 PEPE", callback_data="ver_PEPE")
    )
    modo = "🧪 MODO DEMO (sin órdenes reales)" if MODO_DEMO else "💵 MODO REAL"
    enviar(message.chat.id, f"📈 **PANEL DE SEÑALES - MEXC** 🟢\n{modo}\n\nComandos:\n• /menu - Panel\n• /operar - Operar manual\n• /analisis - Análisis técnico\n• /predicciones - Predicciones 5 min", reply_markup=markup)


@bot.message_handler(commands=['operar'])
def menu_operar(message):
    if not autorizado_mensaje(message):
        return
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("⚡ Futuros (MEXC)", callback_data="menu_futuros")
    )
    enviar(message.chat.id, "⚙️ **CENTRAL DE OPERACIONES (FUTUROS PERPETUOS)** 🟢", reply_markup=markup)


@bot.message_handler(commands=['analisis'])
def menu_analisis(message):
    if not autorizado_mensaje(message):
        return
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("⚡ BTC", callback_data="ana_BTC"),
        InlineKeyboardButton("💎 ETH", callback_data="ana_ETH"),
        InlineKeyboardButton("🟣 SOL", callback_data="ana_SOL"),
        InlineKeyboardButton("🟠 DOGE", callback_data="ana_DOGE"),
        InlineKeyboardButton("🟡 ZEC", callback_data="ana_ZEC"),
        InlineKeyboardButton("🐸 PEPE", callback_data="ana_PEPE")
    )
    enviar(message.chat.id, "🔍 **Selecciona el activo para análisis técnico:**", reply_markup=markup)


@bot.message_handler(commands=['predicciones'])
def menu_predicciones(message):
    if not autorizado_mensaje(message):
        return
    markup = InlineKeyboardMarkup(row_width=3)
    markup.add(*[InlineKeyboardButton(f"🔮 {c}", callback_data=f"pred_{c}") for c in MONEDAS_PREDICCION])
    enviar(message.chat.id, "🔮 **PREDICCIONES 5 MINUTOS** 🔮\n\nElige el activo para analizar:", reply_markup=markup)


def texto_reporte(titulo, coin, analisis, t4h, sentimiento):
    return (
        f"{titulo}\n"
        f"⚡ Activo MEXC: {coin}/USDT\n\n"
        f"💵 Precio Actual: ${fp(analisis['precio'])}\n\n"
        f"📊 MACRO (1H): {analisis['tendencia_1h']} | ADX: {analisis['adx_1h']} | RSI: {analisis['rsi_1h']}\n"
        f"📈 MACRO (4H): {t4h['tendencia']} | ADX: {t4h['adx']} | RSI: {t4h['rsi']}\n"
        f"📉 CORTO PLAZO (15M): {analisis['tendencia_15m']} | ADX: {analisis['adx_15m']} | RSI: {analisis['rsi_15m']}\n\n"
        f"😱 **SENTIMIENTO:** {sentimiento['clasificacion']} ({sentimiento['valor']}/100)\n\n"
        f"🧱 Resistencia: ${fp(analisis['resistencia'])}\n"
        f"🟡 Soporte: ${fp(analisis['soporte'])}\n\n"
        f"🎯 SEÑAL:\n• {analisis['estado']}\n• {analisis['pausa']}"
    )


@bot.callback_query_handler(func=lambda call: True)
def callback_query(call):
    if call.from_user.id != CHAT_ID_AUTORIZADO:
        print(f"Callback denegado a usuario {call.from_user.id}")
        try:
            bot.answer_callback_query(call.id, "⛔ No autorizado", show_alert=True)
        except Exception:
            pass
        return

    chat_id = call.message.chat.id
    try:
        datos = call.data.split("_")
        if not datos:
            return
        accion = datos[0]

        # === PREDICCIONES 5M ===
        if accion == "pred" and len(datos) >= 2:
            coin = datos[1]
            bot.answer_callback_query(call.id, f"Analizando {coin} en 5m...")
            msg = enviar(chat_id, f"🔮 **Analizando {coin} en gráfico de 5 minutos...**")

            pred = analizar_prediccion_5m(coin)
            borrar_mensaje(chat_id, msg)

            if pred:
                rep = (
                    f"🔮 **PREDICCIÓN 5 MINUTOS** 🔮\n\n"
                    f"🪙 **Activo:** {coin}/USDT\n"
                    f"💵 **Precio Actual:** ${fp(pred['precio'])}\n\n"
                    f"{pred['emoji']} **PREDICCIÓN:** {pred['prediccion']}\n\n"
                    f"📊 **RSI (5m):** {pred['rsi']}\n"
                    f"📊 **ADX (5m):** {pred['adx']}\n"
                    f"📈 **SMA5:** ${fp(pred['sma5'])}\n"
                    f"📉 **SMA10:** ${fp(pred['sma10'])}\n"
                    f"📊 **Volumen:** {pred['volumen']:.0f} (prom: {pred['volumen_promedio']:.0f})\n\n"
                    f"🎯 **Puntos Alcistas:** {pred['puntos_alcista']}\n"
                    f"🎯 **Puntos Bajistas:** {pred['puntos_bajista']}\n\n"
                    f"⚠️ *Este análisis es informativo, el bot no ejecuta órdenes aquí.*"
                )
                enviar(chat_id, rep)
            else:
                enviar(chat_id, f"❌ No se pudo analizar {coin}.")

        # === REPORTE TÉCNICO / ANÁLISIS TÉCNICO ===
        elif accion in ("ver", "ana") and len(datos) >= 2:
            coin = datos[1]
            bot.answer_callback_query(call.id, f"Analizando {coin}...")
            analisis = obtener_analisis_mexc(coin, 'swap')
            t4h = obtener_tendencia_4h(coin, 'swap')
            sentimiento = obtener_sentimiento_mercado()
            titulo = "🔔 REPORTE TÉCNICO 🔔" if accion == "ver" else "🔔 ANÁLISIS TÉCNICO 🔔"
            enviar(chat_id, texto_reporte(titulo, coin, analisis, t4h, sentimiento))

        # === CONFIRMACIÓN TRADING AUTOMÁTICO (Sí/No) ===
        elif accion == "conf" and len(datos) >= 3:
            if datos[1] == "no":
                coin = datos[2]
                bot.answer_callback_query(call.id, "Operación descartada.")
                enviar(chat_id, f"❌ **Operación descartada para {coin}.** El bot sigue monitoreando.")
                return

            coin = datos[1]
            tipo = datos[2]

            bot.answer_callback_query(call.id, "Selecciona el monto...")
            montos = [5, 10, 20] if coin != "PEPE" else [5, 10]
            m = InlineKeyboardMarkup(row_width=3)
            m.add(*[InlineKeyboardButton(f"${monto}", callback_data=f"mont_{coin}_{tipo}_{monto}") for monto in montos])
            m.add(InlineKeyboardButton("❌ Cancelar", callback_data=f"conf_no_{coin}_{tipo}"))

            rep = (
                f"🎯 **AUTORIZADO:** {coin}/USDT\n"
                f"📈 **Dirección:** {'COMPRA (LONG)' if tipo == 'COMPRA' else 'VENTA (SHORT)'}\n\n"
                f"💰 **Elige el monto a operar:**\n"
                f"⚡ Apalancamiento: **5x**"
            )
            enviar(chat_id, rep, reply_markup=m)

        # === MONTO SELECCIONADO (ejecutar con 5x) ===
        elif accion == "mont" and len(datos) >= 4:
            coin = datos[1]
            tipo = datos[2]
            monto = float(datos[3])

            if not anti_doble_click(("mont", coin, tipo, monto)):
                bot.answer_callback_query(call.id, "Ya se envió esa orden, espera unos segundos.")
                return
            bot.answer_callback_query(call.id, f"Ejecutando {tipo} de {coin}...")
            msg_espera = enviar(chat_id, f"⏳ **Ejecutando orden {tipo} para {coin}...**\nPor favor espera.")

            side = 'buy' if tipo == 'COMPRA' else 'sell'
            res = ejecutar_orden_con_gestion_riesgo_real(
                symbol=coin, mercado='swap', side=side, margen_usdt=monto,
                apalancamiento=5, tipo_orden='market', zona_precio=None
            )
            borrar_mensaje(chat_id, msg_espera)

            if res['ok']:
                registrar_orden_abierta(coin, 'swap', res)
                enviar(chat_id, texto_orden_ejecutada(coin, res, "✅ **¡ORDEN AUTOMÁTICA EJECUTADA!** ✅"))
            else:
                enviar(chat_id, f"❌ **Fallo al ejecutar:**\n\n{res['error']}")

        # === MENÚ FUTUROS ===
        elif call.data == "menu_futuros":
            bot.answer_callback_query(call.id, "Futuros MEXC...")
            m = InlineKeyboardMarkup(row_width=2)
            m.add(*[InlineKeyboardButton(f"⚡ {c}", callback_data=f"opc_fut_{c}") for c in MONEDAS_TRADING])
            enviar(chat_id, "⚡ **Selecciona Activo para Futuros (MEXC):**", reply_markup=m)

        # === SELECCIÓN DE MONEDA FUTUROS ===
        elif len(datos) == 3 and accion == "opc":
            bot.answer_callback_query(call.id)
            mercado_tipo, coin = datos[1], datos[2]
            if mercado_tipo == "fut":
                m_lev = InlineKeyboardMarkup(row_width=3)
                m_lev.add(
                    InlineKeyboardButton("1x", callback_data=f"lev_{coin}_1"),
                    InlineKeyboardButton("5x", callback_data=f"lev_{coin}_5"),
                    InlineKeyboardButton("10x", callback_data=f"lev_{coin}_10"),
                    InlineKeyboardButton("20x", callback_data=f"lev_{coin}_20")
                )
                enviar(chat_id, f"⚙️ **Elige Apalancamiento para {coin} (MEXC):**", reply_markup=m_lev)

        # === SELECCIÓN DE APALANCAMIENTO ===
        elif accion == "lev" and len(datos) == 3:
            coin, lev = datos[1], int(datos[2])
            bot.answer_callback_query(call.id, f"Tipo de orden para {coin}...")
            m_tipo = InlineKeyboardMarkup(row_width=2)
            m_tipo.add(
                InlineKeyboardButton("🚀 Mercado", callback_data=f"tipo_fut_{coin}_{lev}_market"),
                InlineKeyboardButton("⏳ Límite", callback_data=f"tipo_fut_{coin}_{lev}_limit")
            )
            enviar(chat_id, f"⚙️ **Tipo de Orden para {coin} ({lev}x):**", reply_markup=m_tipo)

        # === SELECCIÓN DE TIPO DE ORDEN ===
        elif accion == "tipo" and len(datos) == 5:
            coin, lev, tipo_o = datos[2], int(datos[3]), datos[4]
            if tipo_o == "market":
                bot.answer_callback_query(call.id, "Selecciona dirección y margen...")
                m_mar_fut = InlineKeyboardMarkup(row_width=3)
                m_mar_fut.add(
                    InlineKeyboardButton("🟢 LONG $5", callback_data=f"ejec_fut_{coin}_{lev}_market_none_5"),
                    InlineKeyboardButton("🟢 LONG $10", callback_data=f"ejec_fut_{coin}_{lev}_market_none_10"),
                    InlineKeyboardButton("🟢 LONG $20", callback_data=f"ejec_fut_{coin}_{lev}_market_none_20"),
                    InlineKeyboardButton("🔴 SHORT $5", callback_data=f"ejec_fut_{coin}_{lev}_market_short_5"),
                    InlineKeyboardButton("🔴 SHORT $10", callback_data=f"ejec_fut_{coin}_{lev}_market_short_10"),
                    InlineKeyboardButton("🔴 SHORT $20", callback_data=f"ejec_fut_{coin}_{lev}_market_short_20")
                )
                enviar(chat_id, f"💵 **Dirección y margen para Mercado {coin} ({lev}x):**", reply_markup=m_mar_fut)
            else:
                bot.answer_callback_query(call.id, "Selecciona zona...")
                m_zona = InlineKeyboardMarkup(row_width=2)
                m_zona.add(
                    InlineKeyboardButton("🟢 Comprar en Soporte", callback_data=f"ejec_fut_{coin}_{lev}_limit_soporte_10"),
                    InlineKeyboardButton("🔴 Vender en Resistencia", callback_data=f"ejec_fut_{coin}_{lev}_limit_resistencia_10")
                )
                enviar(chat_id, f"🎯 **Zona para orden Límite de {coin} ({lev}x):**", reply_markup=m_zona)

        # === EJECUCIÓN MANUAL ===
        elif accion == "ejec" and len(datos) >= 7:
            mercado_tipo = datos[1]
            coin = datos[2]
            lev = int(datos[3]) if datos[3] != 'none' else 1
            tipo_orden = datos[4]
            zona = datos[5]
            margen = float(datos[6])
            side = 'sell' if zona in ('resistencia', 'short') else 'buy'

            if not anti_doble_click(("ejec", coin, lev, tipo_orden, zona, margen)):
                bot.answer_callback_query(call.id, "Ya se envió esa orden, espera unos segundos.")
                return
            bot.answer_callback_query(call.id, "Ejecutando orden...")

            msg_espera = enviar(chat_id, f"⏳ **Ejecutando orden {tipo_orden.upper()} para {coin}...**")
            mercado_ccxt = 'swap' if mercado_tipo == 'fut' else 'spot'

            res = ejecutar_orden_con_gestion_riesgo_real(
                symbol=coin, mercado=mercado_ccxt, side=side, margen_usdt=margen,
                apalancamiento=lev, tipo_orden=tipo_orden,
                zona_precio=zona if zona not in ('none', 'short') else None
            )
            borrar_mensaje(chat_id, msg_espera)

            if res['ok']:
                registrar_orden_abierta(coin, mercado_ccxt, res)
                enviar(chat_id, texto_orden_ejecutada(coin, res, "✅ **¡ORDEN EJECUTADA CON ÉXITO!** ✅"))
            else:
                enviar(chat_id, f"❌ **Fallo al ejecutar:**\n\n{res['error']}")

        else:
            bot.answer_callback_query(call.id, "Opción no reconocida.")

    except Exception as e:
        print(f"Error en callback: {e}")
        try:
            bot.send_message(chat_id, f"⚠️ Error interno: {e}")
        except Exception:
            pass


def iniciar_hilos():
    for objetivo in (bucle_keep_alive, bucle_reportes_automaticos, bucle_monitoreo_ordenes, bucle_trading_automatico):
        threading.Thread(target=objetivo, daemon=True).start()


if __name__ == "__main__":
    print("Iniciando Bot...")
    if not TOKEN:
        print("⚠️ No se encontró el token de Telegram (TEL_TOKEN / TELEGRAM_TOKEN / TOKEN / TELKEY).")
    if MODO_DEMO:
        print("🧪 MODO DEMO ACTIVO: no se enviarán órdenes reales.")
    cargar_estado()
    inicializar_mercados()
    iniciar_hilos()
    hilo_bot = threading.Thread(target=lambda: bot.infinity_polling(), daemon=True)
    hilo_bot.start()
    puerto = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=puerto)
