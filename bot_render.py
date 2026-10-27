import json
import os
import threading
import time
from datetime import datetime, timezone, timedelta
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
import requests
import telebot
import ccxt
import numpy as np
from flask import Flask
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

import indicadores
import senales
import posiciones
import prediccion
import historial
import avisos
import modos
import backtest

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

# ID de Telegram del ÚNICO usuario autorizado. Puede sobreescribirse en Render con la
# variable de entorno TELEGRAM_OWNER_ID (sin necesidad de tocar el código).
DUENO_ID = int(os.getenv("TELEGRAM_OWNER_ID", "8886788683"))
ULTIMO_CHAT_ID = DUENO_ID
ultimos_timestamps = {"BTC": 0, "ETH": 0, "ZEC": 0}

LIMITE_PERDIDA_DIARIA = 3.0
perdida_acumulada_dia = 0.0
fecha_actual = time.strftime("%Y-%m-%d")
MODO_DEMO = False
MONTO_MINIMO_USDT = 5.0  # mínimo del tamaño total de la posición (margen x apalancamiento)

# --- Parámetros de operación (cuenta real, montos pequeños) ---
APALANCAMIENTO_AUTO = 20          # apalancamiento de las señales automáticas
MONTOS_PERMITIDOS = [1.0, 2.0, 3.0]  # botones de margen en USDT
MARGEN_MAXIMO_USDT = float(os.getenv("MARGEN_MAXIMO_USDT", "5"))  # tope de seguridad por operación
# 1 = margen aislado (lo máximo que pierdes es el margen de la operación), 2 = cruzado.
TIPO_MARGEN_MEXC = int(os.getenv("MEXC_OPEN_TYPE", "1"))
# A 20x la liquidación ocurre cerca de -5%, por eso el SL nunca puede ser de 4%.
SL_PORCENTAJE = 1.5               # SL por defecto (operaciones manuales o sin señal vigente)
SENAL_VIGENCIA_SEG = 5400         # una señal se puede operar con los botones durante 90 min
SENAL_MAX_DESVIO_PCT = 0.8        # si el precio se movió más que esto desde la señal, no se opera
INTERVALO_AVISOS_SEG = 120         # el bot busca oportunidades y niveles vigilados cada 2 min
lider_btc = {'tipo': None, 'ts': 0.0}   # última señal de BTC (el líder): COMPRA / VENTA
INTERVALO_GESTION_SEG = 20        # cada cuánto el bot revisa el precio de tus posiciones
GRACIA_POSICION_SEG = 90          # tiempo para que MEXC muestre una posición recién abierta
INTERVALO_DETECCION_SEG = 60      # cada cuánto busca posiciones abiertas que el bot no gestiona (p. ej. las tuyas)
INTERVALO_EVAL_SALIDA_SEG = 300   # cada cuánto evalúa si conviene sugerirte salir de una posición

# --- Adoptar solas las posiciones manuales (solo operables; BTC nunca se opera, solo es indicador) ---
AJUSTES_PATH = os.getenv("AJUSTES_PATH", "ajustes_bot.json")

def _leer_ajustes():
    try:
        with open(AJUSTES_PATH, "r", encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}

def _escribir_ajustes(d):
    try:
        tmp = AJUSTES_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f)
        os.replace(tmp, AJUSTES_PATH)
    except OSError:
        pass

ADOPTAR_MANUALES_AUTO = bool(_leer_ajustes().get("adoptar_manuales", False))  # OFF por defecto

def cambiar_adoptar_manuales():
    """Enciende/apaga la adopción automática de manuales. Devuelve el nuevo estado."""
    global ADOPTAR_MANUALES_AUTO
    ADOPTAR_MANUALES_AUTO = not ADOPTAR_MANUALES_AUTO
    d = _leer_ajustes()
    d["adoptar_manuales"] = ADOPTAR_MANUALES_AUTO
    _escribir_ajustes(d)
    return ADOPTAR_MANUALES_AUTO

posiciones_gestionadas = {}       # moneda -> estado de la posición (stop que sigue al precio)
posiciones_avisadas = {}          # moneda -> (lado, entrada) de la posición ya ofrecida para gestionar
ultima_orden_ts = {}              # moneda -> cuándo el bot envió su última orden (evita ofrecer lo que acaba de abrir)
_lock_pos = threading.RLock()
senales_pendientes = {}           # (moneda, tipo) -> señal que puedes operar con los botones
avisos_hoy = {'fecha': '', 'n': 0}  # contador diario de avisos de entrada (anti-ruido)
ultima_zona = {}                  # (moneda, tipo) -> hora del último aviso de zona
senales_enviadas = {}             # (moneda, subtipo) -> vela ya notificada (evita repetidas)

MONEDAS_TRADING = ["BTC", "ETH", "ZEC", "PAXG", "UKOIL"]  # Señales y alertas: BTC + operables (PAXG = oro, UKOIL = Brent)
MONEDAS_OPERABLES = ["ETH", "ZEC", "PAXG", "UKOIL"]   # Solo estas se pueden OPERAR; BTC da señales y alertas pero no se opera
SIN_FILTRO_BTC = ["PAXG", "UKOIL"]  # Oro y Brent: SIN filtro BTC y SIN avisos de "BTC manda" (muchas veces se mueven al revés de BTC)

# --- Red pública de noticias: el bot lee noticias cripto y avisa, NUNCA pausa señales ---
# Fuentes RSS públicas, sin claves. Si una noticia importante y reciente puede mover a BTC,
# se añade una advertencia a las señales y se manda un aviso. Las señales siempre se mandan.
FUENTES_NOTICIAS = [
    "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "https://cointelegraph.com/rss",
]
PALABRAS_NOTICIA = ["fed", "fomc", "powell", "cpi", "ppi", "inflation", "interest rate",
                    "rate hike", "rate cut", "sec", "etf", "tariff", "hack", "bankrupt",
                    "liquidation", "payroll", "gdp", "recession"]
VENTANA_NOTICIA_MIN = 120
_cache_noticias = {"ts": 0.0, "titulares": []}
_vistas_noticias = None

def _leer_noticias():
    """Titulares recientes (<= VENTANA_NOTICIA_MIN) que pueden mover a BTC. Cache 10 min.
    Si las fuentes fallan, devuelve lo último en cache (o vacío): nunca rompe las señales."""
    ahora = time.time()
    if ahora - _cache_noticias["ts"] < 600:
        return _cache_noticias["titulares"]
    titulares = []
    for url in FUENTES_NOTICIAS:
        try:
            r = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
            raiz = ET.fromstring(r.content)
            for item in raiz.iter("item"):
                titulo = (item.findtext("title") or "").strip()
                fecha = (item.findtext("pubDate") or "").strip()
                if not titulo or not fecha:
                    continue
                try:
                    pub = parsedate_to_datetime(fecha)
                except Exception:
                    continue
                if pub is None:
                    continue
                if pub.tzinfo is None:
                    pub = pub.replace(tzinfo=timezone.utc)
                edad_min = (datetime.now(timezone.utc) - pub.astimezone(timezone.utc)).total_seconds() / 60.0
                if 0 <= edad_min <= VENTANA_NOTICIA_MIN:
                    bajo = titulo.lower()
                    if any(p in bajo for p in PALABRAS_NOTICIA):
                        titulares.append(titulo)
        except Exception as e:
            print(f"No pude leer noticias de {url}: {e}")
    _cache_noticias["ts"] = ahora
    _cache_noticias["titulares"] = titulares
    return titulares

def contexto_noticias():
    """Primer titular importante reciente, o None."""
    t = _leer_noticias()
    return t[0] if t else None

def avisar_noticias_nuevas():
    """Avisa una sola vez por titular nuevo importante. La primera lectura solo marca, no avisa."""
    global _vistas_noticias
    actuales = set(_leer_noticias())
    if _vistas_noticias is None:
        _vistas_noticias = actuales
        return
    nuevas = [t for t in actuales if t not in _vistas_noticias]
    _vistas_noticias = actuales
    if len(_vistas_noticias) > 100:
        _vistas_noticias = set(list(_vistas_noticias)[-50:])
    for t in nuevas[:3]:
        avisar(f"📰 Noticia importante para BTC:\n{t}\nEl bot sigue mandando señales; opera con cuidado.")
MONEDAS_REPORTE = ["BTC", "ETH", "ZEC", "PAXG", "UKOIL"]
MONEDAS_PREDICCION = ["BTC", "ETH", "ZEC", "SOL"]


def es_dueno(obj):
    """True solo si el mensaje/botón viene del dueño y desde un chat privado con el bot."""
    try:
        user = getattr(obj, "from_user", None)
        if user is None or user.id != DUENO_ID:
            return False
        chat = getattr(obj, "chat", None)
        if chat is None:
            chat = getattr(getattr(obj, "message", None), "chat", None)
        return chat is not None and chat.type == "private"
    except Exception:
        return False


def obtener_credenciales_mexc():
    api = (os.getenv("MEXC_API_KEY") or os.getenv("MEXC_KEY") or 
           os.getenv("MEXC_API") or "")
    secret = (os.getenv("MEXC_SECRET_KEY") or os.getenv("MEXC_SECRET") or 
              os.getenv("MEXC_SEC") or "")
    return api.strip(), secret.strip()

_hilo_local = threading.local()

def crear_instancia_exchange(mercado='swap'):
    """Una instancia de ccxt por hilo y por mercado (evita recargar los mercados en cada llamada)."""
    cache = getattr(_hilo_local, "instancias", None)
    if cache is None:
        cache = _hilo_local.instancias = {}
    if mercado not in cache:
        api, secret = obtener_credenciales_mexc()
        config = {
            'enableRateLimit': True,
            'options': {'defaultType': mercado, 'createMarketBuyOrderRequiresPrice': False}
        }
        if api:
            config['apiKey'] = api
        if secret:
            config['secret'] = secret
        cache[mercado] = ccxt.mexc(config)
    return cache[mercado]

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
    return indicadores.rsi(closes, period)

def calcular_adx(highs, lows, closes, period=14):
    return indicadores.adx(highs, lows, closes, period)

def etiqueta_tendencia(t):
    return {"ALCISTA": "ALCISTA 🟢", "BAJISTA": "BAJISTA 🔴"}.get(t, "NEUTRAL 🟡")

def _p(x):
    """Redondea un precio para mostrarlo (más decimales en monedas baratas como PEPE)."""
    try:
        x = float(x)
    except Exception:
        return x
    return round(x, 2) if abs(x) >= 1 else round(x, 8)

def obtener_tendencia_4h(symbol, mercado='swap'):
    try:
        ex = crear_instancia_exchange(mercado)
        market_symbol = f"{symbol}/USDT:USDT" if mercado == 'swap' else f"{symbol}/USDT"
        ohlcv_4h = ex.fetch_ohlcv(market_symbol, timeframe='4h', limit=120)
        closes_4h = [x[4] for x in ohlcv_4h]
        highs_4h = [x[2] for x in ohlcv_4h]
        lows_4h = [x[3] for x in ohlcv_4h]
        # Tendencia por EMA 20/50 de 4H (antes: solo comparaba contra el cierre de hace 10 velas)
        tendencia_4h = etiqueta_tendencia(senales.tendencia(closes_4h))
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

def registrar_operacion(coin, tipo_orden, lado, precio_entrada, margen, apalancamiento, sl, tp, id_orden, estado='ABIERTA'):
    try:
        archivo = "registro_operaciones.txt"
        fecha = time.strftime("%Y-%m-%d %H:%M:%S")
        linea = f"{fecha} | {coin} | {tipo_orden} | {lado} | Entrada: {precio_entrada} | Margen: {margen} | Apal: {apalancamiento}x | SL: {sl} | TP: {tp} | ID: {id_orden} | Estado: {estado}\n"
        with open(archivo, "a", encoding="utf-8") as f:
            f.write(linea)
        print(f"Operación registrada: {coin} - {lado}")
    except Exception as e:
        print(f"Error al registrar operación: {e}")

def obtener_analisis_mexc(symbol, mercado='swap'):
    try:
        ex = crear_instancia_exchange(mercado)
        market_symbol = f"{symbol}/USDT:USDT" if mercado == 'swap' else f"{symbol}/USDT"
        ohlcv_1h = ex.fetch_ohlcv(market_symbol, timeframe='1h', limit=260)
        closes_1h, highs_1h, lows_1h = [x[4] for x in ohlcv_1h], [x[2] for x in ohlcv_1h], [x[3] for x in ohlcv_1h]
        ohlcv_15m = ex.fetch_ohlcv(market_symbol, timeframe='15m', limit=100)
        closes_15m, highs_15m, lows_15m = [x[4] for x in ohlcv_15m], [x[2] for x in ohlcv_15m], [x[3] for x in ohlcv_15m]
        adx_15m = calcular_adx(highs_15m, lows_15m, closes_15m)
        estado_mercado = "MERCADO LATERAL / RANGO EN 15M (ADX < 20)" if adx_15m < 20 else "TENDENCIA ACTIVA EN 15M"
        pausa_texto = "Estructura de 15m con fuerza tendencial." if adx_15m >= 20 else "Precaución: Rango plano en corto plazo."

        ema9_15m = indicadores.ultima_ema(closes_15m, 9)
        ema21_15m = indicadores.ultima_ema(closes_15m, 21)
        atr_1h = indicadores.atr(highs_1h, lows_1h, closes_1h)
        # Niveles: máximo/mínimo de las últimas 24 velas de 1H ya cerradas (mismo criterio que las señales)
        resistencia, soporte, _, _ = indicadores.niveles(highs_1h[:-1], lows_1h[:-1], atr_1h, senales.VENTANA_NIVEL)
        return {
            "precio": closes_1h[-1],
            "tendencia_1h": etiqueta_tendencia(senales.tendencia(closes_1h)),
            "adx_1h": round(calcular_adx(highs_1h, lows_1h, closes_1h), 1),
            "rsi_1h": round(calcular_rsi(closes_1h), 1),
            "tendencia_15m": "ALCISTA 🟢" if ema9_15m > ema21_15m else "BAJISTA 🔴",
            "adx_15m": round(adx_15m, 1),
            "rsi_15m": round(calcular_rsi(closes_15m), 1),
            "ema9_15m": _p(ema9_15m), "ema21_15m": _p(ema21_15m),
            "ema20_1h": _p(indicadores.ultima_ema(closes_1h, 20)),
            "ema50_1h": _p(indicadores.ultima_ema(closes_1h, 50)),
            "ema200_1h": _p(indicadores.ultima_ema(closes_1h, 200)),
            "resistencia": _p(resistencia),
            "soporte": _p(soporte),
            "estado": estado_mercado,
            "pausa": pausa_texto
        }
    except Exception as e:
        return {"precio": 0.0, "tendencia_1h": "ERROR", "adx_1h": 0.0, "rsi_1h": 0.0, "tendencia_15m": "ERROR", "adx_15m": 0.0, "rsi_15m": 0.0, "resistencia": 0.0, "soporte": 0.0, "estado": "FALLA EN EXCHANGE", "pausa": str(e)}

def detectar_rompimiento(symbol, mercado='swap'):
    """Evalúa la última vela CERRADA de 1H y devuelve una lista de señales (la mejor primero).
    Cada señal trae veredicto (VERDADERO / PROBABLE / DEBIL), puntaje y verificación detallada.
    Ver senales.py para las reglas (volumen, cierre, EMAs 1H/4H, ADX, RSI, extensión, toques, BTC,
    retest y falso rompimiento)."""
    try:
        ex = crear_instancia_exchange(mercado)
        market_symbol = f"{symbol}/USDT:USDT" if mercado == 'swap' else f"{symbol}/USDT"
        ahora = int(time.time() * 1000)
        v1h = senales.solo_cerradas(ex.fetch_ohlcv(market_symbol, timeframe='1h', since=ahora - 300 * 3600000, limit=300), 3600000, ahora)
        v4h = senales.solo_cerradas(ex.fetch_ohlcv(market_symbol, timeframe='4h', since=ahora - 120 * 14400000, limit=120), 14400000, ahora)
        vbtc = None
        if symbol != 'BTC' and symbol not in SIN_FILTRO_BTC:
            try:
                btc_symbol = "BTC/USDT:USDT" if mercado == 'swap' else "BTC/USDT"
                vbtc = senales.solo_cerradas(ex.fetch_ohlcv(btc_symbol, timeframe='1h', since=ahora - 120 * 3600000, limit=120), 3600000, ahora)
            except Exception as e:
                print(f"No pude leer BTC como contexto: {e}")
        return senales.evaluar(symbol, v1h, v4h, vbtc)
    except Exception as e:
        print(f"Error detectando rompimiento en {symbol}: {e}")
        return []
def obtener_analisis_con_reintentos(symbol, mercado='swap', intentos=3, espera=3):
    """MEXC a veces responde 503 ('service not available'). Reintenta antes de rendirse."""
    a = None
    for _ in range(intentos):
        a = obtener_analisis_mexc(symbol, mercado)
        if a.get('estado') != "FALLA EN EXCHANGE":
            return a
        time.sleep(espera)
    return a

def construir_reporte(titulo, coin, a, t4h, sentimiento):
    """Mismo formato de siempre, con las EMAs agregadas debajo de las tendencias."""
    return (
        f"{titulo}\n"
        f"⚡ Activo MEXC: {coin}/USDT\n\n"
        f"💵 Precio Actual: ${a['precio']}\n\n"
        f"📊 MACRO (1H): {a['tendencia_1h']} | ADX: {a['adx_1h']} | RSI: {a['rsi_1h']}\n"
        f"📈 MACRO (4H): {t4h['tendencia']} | ADX: {t4h['adx']} | RSI: {t4h['rsi']}\n"
        f"📉 CORTO PLAZO (15M): {a['tendencia_15m']} | ADX: {a['adx_15m']} | RSI: {a['rsi_15m']}\n"
        f"📐 EMA 20/50/200 (1H): ${a['ema20_1h']} / ${a['ema50_1h']} / ${a['ema200_1h']}\n"
        f"📐 EMA 9/21 (15M): ${a['ema9_15m']} / ${a['ema21_15m']}\n\n"
        f"😱 **SENTIMIENTO:** {sentimiento['clasificacion']} ({sentimiento['valor']}/100)\n\n"
        f"🧱 Resistencia: ${a['resistencia']}\n"
        f"🟡 Soporte: ${a['soporte']}\n\n"
        f"🎯 SEÑAL:\n• {a['estado']}\n• {a['pausa']}"
    )

def bucle_reportes_automaticos():
    time.sleep(10)
    while True:
        try:
            tiempo_actual = time.localtime()
            if tiempo_actual.tm_min in [0, 15, 30, 45]:
                now_ts = time.time()
                for coin in MONEDAS_REPORTE:
                    if now_ts - ultimos_timestamps.get(coin, 0) > 800:
                        ultimos_timestamps[coin] = now_ts
                        a = obtener_analisis_con_reintentos(coin, 'swap')
                        if a.get('estado') == "FALLA EN EXCHANGE":
                            print(f"MEXC no respondió para {coin}: {a.get('pausa')}")
                            if ULTIMO_CHAT_ID:
                                bot.send_message(ULTIMO_CHAT_ID, f"⚠️ MEXC no respondió para {coin}/USDT (error temporal del exchange). Reintento en el próximo ciclo de 15 min.")
                            continue
                        t4h = obtener_tendencia_4h(coin, 'swap')
                        sentimiento = obtener_sentimiento_mercado()
                        rep = construir_reporte("🔔 REPORTE AUTOMÁTICO CIERRE 15M / 1H 🔔", coin, a, t4h, sentimiento)
                        if ULTIMO_CHAT_ID:
                            bot.send_message(ULTIMO_CHAT_ID, rep, parse_mode="Markdown")
                time.sleep(60)
        except Exception as e:
            print(f"Error en bucle automático: {e}")
        time.sleep(15)

def construir_mensaje_senal(coin, s, sentimiento, hay_posicion=False):
    accionable = s['veredicto'] in ('VERDADERO', 'PROBABLE') and not hay_posicion
    lineas = [
        "🚨 SEÑAL DETECTADA 🚨" if accionable else "ℹ️ AVISO DE MERCADO (sin operación sugerida)",
        "",
        f"{s['emoji']} {s['titulo']}",
        f"📌 {s['descripcion']}",
        f"🪙 Activo: {coin}/USDT",
        f"💵 Precio (cierre {s.get('tf', '1H')}): ${_p(s['precio'])} | Nivel: ${_p(s['nivel'])}",
        f"🏁 Calidad: {s['puntos']}/{s['total']} puntos",
        "",
        "Verificación:",
    ]
    for ok, txt in s['checklist']:
        lineas.append(f"{'✅' if ok else '❌'} {txt}")
    lineas += [
        "",
        f"📐 EMA 20/50/200 (1H): ${_p(s['ema20'])} / ${_p(s['ema50'])} / ${_p(s['ema200'])}",
        f"📊 RSI ({s.get('tf', '1H')}): {s['rsi']} | ADX (1H): {s['adx']}",
        f"📈 Tendencia 4H (EMA 20/50): {s['tendencia_4h']}",
        f"😱 Sentimiento: {sentimiento['clasificacion']} ({sentimiento['valor']}/100)",
        "",
    ]
    if accionable:
        direccion = "COMPRA (LONG)" if s['tipo'] == 'COMPRA' else "VENTA (SHORT)"
        lineas += [
            f"🎯 Dirección sugerida: {direccion}",
            f"🛡️ Plan: SL {s['sl_pct']}% | TP techo {s['tp_pct']}% | el stop sube con el precio | {APALANCAMIENTO_AUTO}x",
            "",
            "👇 Elige con cuánto operar (un toque abre la orden real con stop y take profit):",
        ]
    elif hay_posicion:
        lineas.append("Ya hay una posición abierta de esta moneda.")
    else:
        lineas.append("Calidad insuficiente: no se recomienda operar esta señal.")
    return "\n".join(lineas)

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
                        for senal in detectar_rompimiento(coin, 'swap'):
                            # Una misma vela cerrada solo se notifica una vez
                            clave = (coin, senal['subtipo'])
                            if senales_enviadas.get(clave) == senal['ts']:
                                continue
                            senales_enviadas[clave] = senal['ts']
                            hay_posicion = coin in posiciones_gestionadas
                            registrar_senal_historial(coin, senal)      # todas se registran (para /aciertos)
                            cfg = avisos.config()
                            if not cfg['activo'] or not avisos.pasa_filtro(senal['veredicto'], cfg['sensibilidad']) or not _cupo_avisos():
                                continue
                            markup = None
                            if not hay_posicion:
                                senales_pendientes[(coin, senal['tipo'])] = dict(senal, creada=time.time())
                                markup = teclado_entrada(coin, senal['tipo'])
                            lider = None if coin in SIN_FILTRO_BTC else (lider_btc['tipo'] if time.time() - lider_btc['ts'] < 10800 else None)
                            texto = "🚨 SEÑAL 1H 🚨\n\n" + avisos.texto_alerta(coin, senal, lider)
                            ctx = contexto_noticias()
                            if ctx:
                                texto += f"\n\n📰 Noticia que puede mover {'al mercado' if coin in SIN_FILTRO_BTC else 'a BTC'}: {ctx}"
                            if hay_posicion:
                                texto += f"\n\nℹ️ Ya tienes una posición de {coin}: no abro otra encima."
                            if ULTIMO_CHAT_ID:
                                enviar_senal_con_grafico(ULTIMO_CHAT_ID, coin, senal, texto, markup, timeframe="1h")
                            avisos_hoy['n'] += 1
                            if coin == 'BTC':
                                lider_btc.update(tipo=senal['tipo'], ts=time.time())
                                _avisar_lider(crear_instancia_exchange('swap'), senal)
                time.sleep(60)
        except Exception as e:
            print(f"Error en bucle de trading automático: {e}")
        time.sleep(15)

def teclado_entrada(coin, tipo):
    """El monto solo PIDE confirmación ('pre_'); la orden real sale únicamente con el botón Confirmar ('mont_').
    BTC da señales y alertas como siempre, pero NO se opera: sus mensajes no llevan botones Operar
    (el bloqueo de ejecución en la orden queda como segunda capa)."""
    m = InlineKeyboardMarkup(row_width=3)
    if coin in MONEDAS_OPERABLES:
        m.add(*[InlineKeyboardButton(f"Operar ${x:g}", callback_data=f"pre_{coin}_{tipo}_{x}") for x in MONTOS_PERMITIDOS])
    m.add(InlineKeyboardButton("📊 Ver análisis", callback_data=f"ver_{coin}"),
          InlineKeyboardButton("❌ Ignorar", callback_data=f"conf_no_{coin}_{tipo}"))
    return m

def _cupo_avisos():
    hoy = time.strftime("%Y-%m-%d")
    if avisos_hoy['fecha'] != hoy:
        avisos_hoy.update(fecha=hoy, n=0)
    return avisos.cupo_disponible(avisos_hoy['n'])

def obtener_velas_zona(coin, ex=None):
    """Velas CERRADAS para evaluar el punto de entrada: 15m, 1H, 4H y BTC 1H (contexto)."""
    ex = ex or crear_instancia_exchange('swap')
    ahora = int(time.time() * 1000)
    ms = f"{coin}/USDT:USDT"
    v15 = senales.solo_cerradas(ex.fetch_ohlcv(ms, timeframe='15m', since=ahora - 250 * 900000, limit=250), 900000, ahora)
    v1h = senales.solo_cerradas(ex.fetch_ohlcv(ms, timeframe='1h', since=ahora - 300 * 3600000, limit=300), 3600000, ahora)
    v4h = senales.solo_cerradas(ex.fetch_ohlcv(ms, timeframe='4h', since=ahora - 120 * 14400000, limit=120), 14400000, ahora)
    vbtc = None
    if coin != 'BTC' and coin not in SIN_FILTRO_BTC:
        try:
            vbtc = senales.solo_cerradas(ex.fetch_ohlcv("BTC/USDT:USDT", timeframe='1h', since=ahora - 120 * 3600000, limit=120), 3600000, ahora)
        except Exception as e:
            print(f"No pude leer BTC como contexto: {e}")
    return v15, v1h, v4h, vbtc

def _posicion_real(ex, coin):
    """Lado ('buy'/'sell') de la posición abierta en MEXC de esa moneda (la abra quien la abra), o None."""
    try:
        p = leer_posicion(ex, f"{coin}/USDT:USDT")
        return posiciones.lado_orden(p['lado']) if p else None
    except Exception as e:
        print(f"No pude leer la posición de {coin}: {e}")
        return None

def _avisar_lider(ex, s):
    """BTC manda: si BTC va con fuerza en un sentido y tienes ETH/ZEC abiertas en contra, te lo dice y ofrece cerrar.
    No aplica a PAXG ni UKOIL: el oro y el Brent muchas veces se mueven al revés de BTC."""
    lado_btc = 'buy' if s['tipo'] == 'COMPRA' else 'sell'
    for coin in MONEDAS_TRADING:
        if coin == 'BTC' or coin in SIN_FILTRO_BTC:
            continue
        lado_real = _posicion_real(ex, coin)
        clave = ('lider', coin, s['tipo'])
        if lado_real and lado_real != lado_btc and avisos.puede_repetir(ultima_zona.get(clave), time.time()):
            ultima_zona[clave] = time.time()
            m = InlineKeyboardMarkup(row_width=2)
            m.add(InlineKeyboardButton(f"❌ Cerrar mi {coin}", callback_data=f"pos_cl_{coin}"),
                  InlineKeyboardButton("✋ Mantener", callback_data=f"pos_clno_{coin}"))
            enviar_dueno(f"👑 BTC {'SUBE' if lado_btc == 'buy' else 'CAE'} con fuerza y tu {coin} {'LONG' if lado_real == 'buy' else 'SHORT'} va EN CONTRA.\n"
                         "Si BTC sigue, las demás lo acompañan. ¿Cierras?", m)

def revisar_zonas(ex):
    """Busca oportunidades en ETH y ZEC: (1) punto de entrada por retroceso a la EMA 21 y (2) movimiento fuerte
    en curso (caída o subida que las EMAs lentas aún no ven). Avisa con botones; si ya tienes posición de esa
    moneda en el mismo sentido calla, y si es en sentido contrario te lo dice y te ofrece cerrarla."""
    cfg = avisos.config()
    if not cfg['activo']:
        return
    for coin in MONEDAS_TRADING:
        try:
            v15, v1h, v4h, vbtc = obtener_velas_zona(coin, ex)
            candidatas = avisos.evaluar_zona(coin, v15, v1h, v4h, vbtc) + avisos.evaluar_movimiento(coin, v15, v1h, v4h, vbtc) + avisos.rupturas_15m(coin, v15, v1h, vbtc)
            lado_real = None
            leida = False
            for s in candidatas:
                clave = (coin, s['tipo'], s['subtipo'])
                ahora = time.time()
                if not avisos.pasa_filtro(s['veredicto'], 'normal') or not avisos.puede_repetir(ultima_zona.get(clave), ahora):
                    continue
                if not leida:
                    lado_real, leida = _posicion_real(ex, coin), True
                lado_senal = 'buy' if s['tipo'] == 'COMPRA' else 'sell'
                if lado_real == lado_senal:
                    continue                      # ya estás dentro en ese sentido
                ultima_zona[clave] = ahora
                registrar_senal_historial(coin, s)
                if not avisos.pasa_filtro(s['veredicto'], cfg['sensibilidad']) or not _cupo_avisos():
                    continue
                texto = avisos.encabezado(s) + "\n\n"
                lider = None if coin in SIN_FILTRO_BTC else (lider_btc['tipo'] if time.time() - lider_btc['ts'] < 10800 else None)
                texto += avisos.texto_alerta(coin, s, lider)
                ctx = contexto_noticias()
                if ctx:
                    texto += f"\n\n📰 Noticia que puede mover {'al mercado' if coin in SIN_FILTRO_BTC else 'a BTC'}: {ctx}"
                if lado_real:                     # señal contraria a tu posición abierta: no se abre otra, se ofrece cerrar
                    m = InlineKeyboardMarkup(row_width=2)
                    m.add(InlineKeyboardButton(f"❌ Cerrar mi {coin}", callback_data=f"pos_cl_{coin}"),
                          InlineKeyboardButton("✋ Ignorar", callback_data=f"pos_clno_{coin}"))
                    texto += (f"\n\n⚠️ Tienes una posición de {coin} {'LONG' if lado_real == 'buy' else 'SHORT'} y esta señal va EN CONTRA. "
                              "No abro otra encima: ¿quieres cerrar la tuya?")
                    enviar_dueno(texto, m)
                else:
                    senales_pendientes[(coin, s['tipo'])] = dict(s, creada=ahora)
                    enviar_senal_con_grafico(DUENO_ID, coin, s, texto, teclado_entrada(coin, s['tipo']), velas=v15)
                avisos_hoy['n'] += 1
                if coin == 'BTC' and avisos.pasa_filtro(s['veredicto'], cfg['sensibilidad']):
                    lider_btc.update(tipo=s['tipo'], ts=time.time())
                    _avisar_lider(ex, s)
        except Exception as e:
            print(f"Error buscando oportunidades en {coin}: {e}")

def revisar_vigilancias_bot(ex):
    cfg = avisos.config()
    if not cfg['vigilancias']:
        return
    precios = {}
    for coin in {v['coin'] for v in cfg['vigilancias']}:
        try:
            precios[coin] = float(ex.fetch_ticker(f"{coin}/USDT:USDT")['last'])
        except Exception as e:
            print(f"No pude leer el precio de {coin}: {e}")
    for v in avisos.revisar_vigilancias(precios):
        enviar_dueno(f"🔔 {v['coin']} llegó a tu nivel ${_p(v['nivel'])} (ahora ${_p(v['precio'])}).\nMira /mercado para ver si hay punto de entrada.")

def bucle_avisos_dinamicos():
    time.sleep(45)
    while True:
        try:
            ex = crear_instancia_exchange('swap')
            avisar_noticias_nuevas()
            revisar_vigilancias_bot(ex)
            revisar_zonas(ex)
        except Exception as e:
            print(f"Error en avisos dinámicos: {e}")
        time.sleep(INTERVALO_AVISOS_SEG)

def analizar_prediccion_5m(symbol):
    """Misma pantalla de siempre, ahora con probabilidades de subir/bajar (ver prediccion.py)."""
    try:
        ex = crear_instancia_exchange('swap')
        market_symbol = f"{symbol}/USDT:USDT"
        ahora = int(time.time() * 1000)
        crudas5 = ex.fetch_ohlcv(market_symbol, timeframe='5m', since=ahora - 130 * 300000, limit=130)
        crudas15 = ex.fetch_ohlcv(market_symbol, timeframe='15m', since=ahora - 80 * 900000, limit=80)
        crudas1h = ex.fetch_ohlcv(market_symbol, timeframe='1h', since=ahora - 100 * 3600000, limit=100)
        est = prediccion.estimar(
            senales.solo_cerradas(crudas5, 300000, ahora),
            senales.solo_cerradas(crudas15, 900000, ahora),
            senales.solo_cerradas(crudas1h, 3600000, ahora))
        if est is None:
            return None
        etiquetas = {"SUBE": ("VA A SUBIR 📈", "🟢"), "BAJA": ("VA A BAJAR 📉", "🔴"),
                     "LATERAL": ("LATERAL / SIN DIRECCIÓN CLARA 😐", "🟡")}
        texto, emoji = etiquetas[est['direccion']]
        closes = [x[4] for x in crudas5]
        res15 = sop15 = None
        try:
            c15 = senales.solo_cerradas(crudas15, 900000, ahora)
            if len(c15) >= 30:
                a15 = np.asarray(c15, dtype=float)
                atr15 = indicadores.atr(a15[:, 2], a15[:, 3], a15[:, 4], 14)
                res15, sop15, _, _ = indicadores.niveles(a15[:, 2], a15[:, 3], atr15, 24, 0.25)
        except Exception as e:
            print(f"No pude calcular niveles 15m de {symbol}: {e}")
        return {
            'res15': res15, 'sop15': sop15,
            'symbol': symbol,
            'precio': closes[-1],
            'prediccion': texto,
            'emoji': emoji,
            'rsi': round(est['rsi'], 1),
            'adx': round(est['adx'], 1),
            'sma5': round(sum(closes[-5:]) / 5, 4),
            'sma10': round(sum(closes[-10:]) / 10, 4),
            'puntos_alcista': est['puntos_alcista'],
            'puntos_bajista': est['puntos_bajista'],
            'volumen': est['volumen'],
            'volumen_promedio': est['volumen_promedio'],
            'prob_sube': est['prob_sube'],
            'prob_baja': est['prob_baja'],
            'confianza': est['confianza'],
            'atr_pct': est['atr_pct'],
            'lateral': est['lateral'],
            'factores': est['factores'],
            'direccion': est['direccion'],
        }
    except Exception as e:
        print(f"Error en predicción 5m de {symbol}: {e}")
        return None
def _rotar_dia():
    global perdida_acumulada_dia, fecha_actual
    hoy = time.strftime("%Y-%m-%d")
    if hoy != fecha_actual:
        perdida_acumulada_dia = 0.0
        fecha_actual = hoy

def registrar_resultado(pnl_usdt):
    """Suma al límite diario solo las pérdidas REALES (antes se sumaba $1 por cada error de la API)."""
    global perdida_acumulada_dia
    _rotar_dia()
    if pnl_usdt < 0:
        perdida_acumulada_dia += -pnl_usdt

def avisar(texto):
    try:
        if ULTIMO_CHAT_ID:
            bot.send_message(ULTIMO_CHAT_ID, texto)
    except Exception as e:
        print(f"No pude enviar aviso a Telegram: {e}")

def leer_posicion(ex, market_symbol):
    """Posición abierta en MEXC para ese símbolo, o None si no hay (ver posiciones.parsear_posicion)."""
    for p in ex.fetch_positions([market_symbol]) or []:
        if p.get('symbol') != market_symbol:
            continue
        d = posiciones.parsear_posicion(p)
        if d:
            return d
    return None

def leer_todas_las_posiciones(ex):
    """Todas las posiciones abiertas en MEXC (cualquier moneda), incluidas las que abriste a mano."""
    salida = []
    for p in ex.fetch_positions() or []:
        d = posiciones.parsear_posicion(p)
        if d and d['coin']:
            salida.append(d)
    return salida

def ejecutar_orden_con_gestion_riesgo_real(symbol, mercado, side, margen_usdt, apalancamiento=1, tipo_orden='market',
                                           zona_precio=None, sl_pct=None, tp_pct=None, precio_referencia=None):
    try:
        ex = crear_instancia_exchange(mercado)
        ex.load_markets()
        market_symbol = f"{symbol}/USDT:USDT" if mercado == 'swap' else f"{symbol}/USDT"
        api, secret = obtener_credenciales_mexc()
        if not api or not secret:
            return False, 0, 0, 0, 0, 0, 0, "❌ **Error:** Faltan las credenciales de MEXC."

        _rotar_dia()
        if perdida_acumulada_dia >= LIMITE_PERDIDA_DIARIA:
            return False, 0, 0, 0, 0, 0, 0, f"🛑 **BLOQUEO POR PÉRDIDA DIARIA:** Has alcanzado el límite de ${LIMITE_PERDIDA_DIARIA} USD."

        # Candados de seguridad: solo ETH/ZEC en futuros, tope de margen y una posición por moneda
        if mercado != 'swap' or symbol not in MONEDAS_OPERABLES:
            return False, 0, 0, 0, 0, 0, 0, f"🔒 **Bloqueado:** solo se permite operar {', '.join(MONEDAS_OPERABLES)} en Futuros."
        if margen_usdt <= 0 or margen_usdt > MARGEN_MAXIMO_USDT:
            return False, 0, 0, 0, 0, 0, 0, f"🔒 **Bloqueado:** el margen máximo permitido por operación es ${MARGEN_MAXIMO_USDT}."
        if symbol in posiciones_gestionadas:
            return False, 0, 0, 0, 0, 0, 0, f"🔒 **Bloqueado:** ya hay una posición abierta de {symbol} gestionada por el bot."
        try:
            if leer_posicion(ex, market_symbol):
                return False, 0, 0, 0, 0, 0, 0, f"🔒 **Bloqueado:** ya tienes una posición abierta de {symbol} en MEXC; no abro otra encima."
        except Exception as e:
            print(f"Aviso: no pude verificar posiciones abiertas de {symbol}: {e}")

        sl_pct = float(sl_pct) if sl_pct else SL_PORCENTAJE
        tp_pct = float(tp_pct) if tp_pct else round(sl_pct * senales.TP_MULTIPLO_R, 2)

        precio_actual = float(ex.fetch_ticker(market_symbol)['last'])
        if precio_referencia:
            desvio = abs(precio_actual - precio_referencia) / precio_referencia * 100
            if desvio > SENAL_MAX_DESVIO_PCT:
                return False, 0, 0, 0, 0, 0, 0, (f"⏱️ **Señal vencida:** el precio se movió {desvio:.2f}% desde la señal "
                                                  f"(${_p(precio_referencia)} → ${_p(precio_actual)}). Espera una señal nueva.")

        precio_objetivo = precio_actual
        if tipo_orden == 'limit' and zona_precio in ('soporte', 'resistencia'):
            analisis = obtener_analisis_mexc(symbol, mercado)
            if analisis.get('estado') == "FALLA EN EXCHANGE":
                return False, 0, 0, 0, 0, 0, 0, "❌ **Error en MEXC:** no pude leer el soporte/resistencia. Intenta de nuevo."
            if zona_precio == 'soporte':
                precio_objetivo = float(analisis['soporte'])
                side = 'buy'
            else:
                precio_objetivo = float(analisis['resistencia'])
                side = 'sell'

        # Apalancamiento y tipo de margen (MEXC exige openType y positionType)
        lev_ok = True
        if mercado == 'swap':
            try:
                ex.set_leverage(apalancamiento, market_symbol,
                                params={'openType': TIPO_MARGEN_MEXC, 'positionType': 1 if side == 'buy' else 2})
            except Exception as e:
                lev_ok = False
                print(f"Aviso de apalancamiento: {e}")

        sl_f, tp_f = sl_pct / 100, tp_pct / 100
        if side == 'buy':
            stop_loss = float(ex.price_to_precision(market_symbol, precio_objetivo * (1 - sl_f)))
            take_profit = float(ex.price_to_precision(market_symbol, precio_objetivo * (1 + tp_f)))
        else:
            stop_loss = float(ex.price_to_precision(market_symbol, precio_objetivo * (1 + sl_f)))
            take_profit = float(ex.price_to_precision(market_symbol, precio_objetivo * (1 - tp_f)))

        # Stop de emergencia en MEXC: más lejos que el stop normal del bot, para que el bot te CONSULTE al tocar el normal
        if tipo_orden == 'market':
            f_duro = (sl_pct + posiciones.EXTRA_STOP_DURO_PCT) / 100
            stop_mexc = float(ex.price_to_precision(market_symbol, precio_objetivo * (1 - f_duro) if side == 'buy' else precio_objetivo * (1 + f_duro)))
        else:
            stop_mexc = stop_loss

        # MEXC opera en CONTRATOS (p. ej. 1 contrato de ETH = 0.01 ETH), no en monedas
        info_mercado = ex.market(market_symbol)
        tam_contrato = float(info_mercado.get('contractSize') or 1.0)
        min_contratos = float(((info_mercado.get('limits') or {}).get('amount') or {}).get('min') or 1.0)
        contratos, error_tam = senales.dimensionar_contratos(
            margen_usdt, apalancamiento, precio_objetivo, tam_contrato, min_contratos, MARGEN_MAXIMO_USDT)
        if error_tam:
            return False, 0, 0, 0, 0, 0, 0, f"⚠️ **TAMAÑO INSUFICIENTE:** {error_tam}"
        cantidad = float(ex.amount_to_precision(market_symbol, contratos))
        if cantidad <= 0:
            return False, 0, 0, 0, 0, 0, 0, "⚠️ **ERROR DE CÁLCULO:** el tamaño quedó en 0 contratos. Sube el margen."
        nocional = cantidad * tam_contrato * precio_objetivo
        margen_real = nocional / apalancamiento
        if nocional < MONTO_MINIMO_USDT:
            return False, 0, 0, 0, 0, 0, 0, f"⚠️ **MONTO INSUFICIENTE:** el monto total (${nocional:.2f} USDT) es menor al mínimo (${MONTO_MINIMO_USDT} USDT)."

        params = {}
        if mercado == 'swap':
            # ccxt NO traduce {'stopLoss': {...}} en MEXC swap (el stop no llegaba al exchange).
            # Los campos propios de la API de MEXC son stopLossPrice / takeProfitPrice, y en margen
            # aislado (openType=1) ccxt exige además 'leverage'.
            params = {
                'openType': TIPO_MARGEN_MEXC,
                'leverage': int(apalancamiento),
                'stopLossPrice': stop_mexc,
                'takeProfitPrice': take_profit,
                'lossTrend': 1, 'profitTrend': 1,
            }
        ultima_orden_ts[symbol] = time.time()
        if tipo_orden == 'market':
            orden = ex.create_order(market_symbol, 'market', side, cantidad, None, params)
        else:
            precio_limite = float(ex.price_to_precision(market_symbol, precio_objetivo))
            orden = ex.create_order(market_symbol, 'limit', side, cantidad, precio_limite, params)
            precio_actual = precio_objetivo

        precio_entrada = precio_actual
        confirmada = None
        if tipo_orden == 'market':
            for _ in range(3):
                try:
                    confirmada = leer_posicion(ex, market_symbol)
                except Exception as e:
                    print(f"Aviso: no pude confirmar la posición: {e}")
                if confirmada:
                    break
                time.sleep(1)
            if confirmada and confirmada['entrada'] > 0:
                precio_entrada = confirmada['entrada']
            elif orden.get('average'):
                precio_entrada = float(orden['average'])
            # El stop que sigue al precio vive en el bot y se calcula desde el precio real de entrada
            sl_virtual = precio_entrada * (1 - sl_f) if side == 'buy' else precio_entrada * (1 + sl_f)
            pos = senales.nueva_posicion(side, precio_entrada, sl_virtual, take_profit)
            pos.update({
                'coin': symbol, 'market_symbol': market_symbol, 'margen': margen_real,
                'apalancamiento': apalancamiento,
                'contratos': confirmada['contratos'] if confirmada else cantidad,
                'abierta_ts': time.time(), 'id': orden.get('id'),
                'ultimo_precio': precio_entrada, 'sl_notificado': sl_virtual, 'aviso_error': 0,
                'open_type': TIPO_MARGEN_MEXC, 'modo': 'trailing',
                'liquidacion': (confirmada or {}).get('liquidacion'),
                'position_id': (confirmada or {}).get('position_id'),
            })
            posiciones_gestionadas[symbol] = pos
            modos.guardar(symbol, side, precio_entrada, 'trailing')

        orden['_extra'] = {'contratos': cantidad, 'nocional': nocional, 'lev_ok': lev_ok,
                           'sl_pct': sl_pct, 'tp_pct': tp_pct, 'confirmada': bool(confirmada)}
        return True, precio_entrada, margen_real, apalancamiento, tipo_orden, stop_loss, take_profit, orden
    except Exception as e:
        error_str = str(e)
        if "minimum amount" in error_str or "minimum" in error_str:
            mensaje_amigable = "❌ **Error en MEXC:** el tamaño es menor al mínimo permitido."
        elif "balance" in error_str.lower() or "insufficient" in error_str.lower():
            mensaje_amigable = "❌ **Error en MEXC:** Saldo insuficiente en la billetera."
        else:
            mensaje_amigable = f"❌ **Error en MEXC:** {error_str}"
        return False, 0, 0, 0, 0, 0, 0, mensaje_amigable

def texto_orden_ejecutada(titulo, coin, side, precio, margen_usado, lev_usado, tipo_usado, sl, tp, resultado):
    extra = resultado.get('_extra', {}) if isinstance(resultado, dict) else {}
    direccion = "COMPRA (LONG) 🟢" if side == 'buy' else "VENTA (SHORT) 🔴"
    lineas = [
        f"✅ **{titulo}** ✅", "",
        f"🪙 **Activo:** {coin}/USDT",
        f"📈 **Dirección:** {direccion}",
        f"💵 **Precio de Entrada:** ${_p(precio)}",
        f"💰 **Margen:** ${margen_usado:.2f} USDT",
        f"⚡ **Apalancamiento:** {lev_usado}x",
    ]
    if extra.get('contratos'):
        lineas.append(f"📦 **Tamaño:** {extra['contratos']:g} contrato(s) (≈ ${extra['nocional']:.2f})")
    lineas += [
        f"📋 **Tipo:** {tipo_usado.upper()}", "",
        f"🛑 **Stop Loss:** ${sl} ({extra.get('sl_pct', SL_PORCENTAJE)}%)",
        f"🎯 **Take Profit (techo):** ${tp}",
    ]
    if tipo_usado == 'market':
        lineas.append("📊 **Trailing Stop:** ACTIVO. El bot sube el stop con el precio. Revisa en MEXC que también aparezcan el SL y el TP.")
        if not extra.get('confirmada', True):
            lineas.append("⚠️ No pude ver la posición en MEXC todavía. Revisa la app del exchange.")
    else:
        lineas.append("📊 **Trailing Stop:** al ejecutarse la orden límite te ofreceré gestionarla con trailing (SL y TP fijos mientras tanto).")
    if not extra.get('lev_ok', True):
        lineas.append("⚠️ No pude confirmar el apalancamiento en MEXC; se usa el que tengas configurado ahí.")
    lineas += ["", f"🆔 **ID de Orden:** `{resultado.get('id', 'N/A')}`"]
    return "\n".join(lineas)

def finalizar_posicion(coin, pos, precio_salida, motivo):
    with _lock_pos:
        if pos.get('finalizada'):
            return          # ya se reportó (p. ej. el botón y el stop coincidieron)
        pos['finalizada'] = True
    pct, pnl = senales.pnl_estimado(pos['lado'], pos['entrada'], precio_salida, pos['margen'], pos['apalancamiento'])
    registrar_resultado(pnl)
    emoji = "🟢 GANANCIA" if pnl > 0 else "🔴 PÉRDIDA"
    reporte = (
        f"🎯 **OPERACIÓN CERRADA** 🎯\n\n"
        f"🪙 **Activo:** {coin}/USDT\n"
        f"📈 **Dirección:** {'COMPRA (LONG) 🟢' if pos['lado'] == 'buy' else 'VENTA (SHORT) 🔴'}\n"
        f"💵 **Entrada:** ${_p(pos['entrada'])}\n"
        f"💵 **Salida (aprox.):** ${_p(precio_salida)}\n"
        f"📌 **Motivo:** {motivo}\n"
        f"💰 **Margen:** ${pos['margen']:.2f} USDT | ⚡ {pos['apalancamiento']}x\n\n"
        f"{emoji}: **${pnl:.2f} USDT** ({pct:+.2f}% del precio, estimado antes de comisiones)\n"
        f"📉 Pérdida acumulada hoy: ${perdida_acumulada_dia:.2f} / ${LIMITE_PERDIDA_DIARIA:.2f}"
    )
    try:
        if ULTIMO_CHAT_ID:
            bot.send_message(ULTIMO_CHAT_ID, reporte, parse_mode="Markdown")
    except Exception as e:
        print(f"No pude enviar el reporte de cierre: {e}")
    registrar_operacion(coin, 'market', pos['lado'], pos['entrada'], pos['margen'], pos['apalancamiento'],
                        pos['sl'], 0, pos.get('id', 'N/A'), 'CERRADA')
    with _lock_pos:
        if posiciones_gestionadas.get(coin) is pos:
            posiciones_gestionadas.pop(coin, None)

def cerrar_posicion_mercado(ex, pos):
    """Cierra la posición con una orden de mercado que solo reduce (no puede abrir una contraria).
    Usa el tipo de margen real de la posición (aislado/cruzado) y su id si MEXC lo informó."""
    lado_cierre = 'sell' if pos['lado'] == 'buy' else 'buy'
    params = {'reduceOnly': True,
              'openType': pos.get('open_type') or TIPO_MARGEN_MEXC,
              'leverage': int(pos.get('apalancamiento') or APALANCAMIENTO_AUTO)}
    if pos.get('position_id'):
        params['positionId'] = pos['position_id']
    ex.create_order(pos['market_symbol'], 'market', lado_cierre, pos['contratos'], None, params)

def _pasado(lado, precio, nivel):
    """El precio ya está en el nivel o más allá, en contra de la posición."""
    return precio <= nivel if lado == 'buy' else precio >= nivel

def _a_favor_de(lado, precio, nivel, distancia):
    return precio >= nivel + distancia if lado == 'buy' else precio <= nivel - distancia

def _cerrar_y_finalizar(ex, coin, pos, precio, motivo):
    try:
        cerrar_posicion_mercado(ex, pos)
    except Exception as e:
        print(f"Error cerrando {coin}: {e}")
        if time.time() - pos.get('aviso_error', 0) > 300:
            pos['aviso_error'] = time.time()
            avisar(f"🚨 {coin}: el stop se activó ({motivo}) pero NO pude cerrar la posición: {e}\nCiérrala manualmente en MEXC.")
        return False
    finalizar_posicion(coin, pos, precio, motivo)
    return True

def evaluar_stop(coin, pos):
    """Lee el mercado y devuelve el diagnóstico (cambio real vs respiro), o None si no pudo."""
    try:
        v15, v1h, v4h, vbtc = obtener_velas_zona(coin)
        r = posiciones.rasgos_stop(pos['lado'], v15, v1h, v4h, vbtc)
        return posiciones.diagnostico_stop(pos['lado'], r) if r else None
    except Exception as e:
        print(f"No pude evaluar el stop de {coin}: {e}")
        return None

def activar_stop_duro(coin, pos, auto=False):
    """«Mantener»: el stop pasa al nivel de emergencia (EXTRA_STOP_DURO_PCT más lejos)."""
    extra = pos['entrada'] * posiciones.EXTRA_STOP_DURO_PCT / 100
    pos['sl_blando'] = pos['sl']
    pos['sl_duro'] = pos['sl'] - extra if pos['lado'] == 'buy' else pos['sl'] + extra
    pos['sl_duro_activo'] = True
    pos.pop('consulta', None)
    m = InlineKeyboardMarkup(row_width=1)
    m.add(InlineKeyboardButton("✅ Cerrar ahora", callback_data=f"pos_clok_{coin}"))
    enviar_dueno(("🤖 No respondiste, así que NO cierro nada: " if auto else "✋ ") + f"mantengo {coin}. "
                 f"El único cierre automático es el stop de emergencia en ${_p(pos['sl_duro'])} (tu límite de pérdida). "
                 "Si el precio se recupera, vuelvo al stop normal. Puedes cerrar tú cuando quieras:", m)

def decidir_cierre(coin, pos, precio, motivo):
    """Cuando el precio toca el stop: CONSULTA primero. Devuelve el motivo si hay que cerrar YA, o None."""
    ahora = time.time()
    extra = pos['entrada'] * posiciones.EXTRA_STOP_DURO_PCT / 100
    sl_duro = pos['sl'] - extra if pos['lado'] == 'buy' else pos['sl'] + extra
    c = pos.get('consulta')
    if c is None:
        d = evaluar_stop(coin, pos) or {'recomendacion': 'DUDA', 'contra': [], 'respiro': [], 'score': 0, 'sin_datos': True}
        pos['consulta'] = {'ts': ahora, 'rec': d['recomendacion']}
        m = InlineKeyboardMarkup(row_width=2)
        m.add(InlineKeyboardButton("✅ Cerrar ahora", callback_data=f"pos_clok_{coin}"),
              InlineKeyboardButton("✋ Mantener", callback_data=f"pos_mt_{coin}"))
        enviar_dueno(posiciones.texto_consulta(coin, pos, precio, d, sl_duro, motivo, gestion_en_mexc=not pos.get('adoptada')), m)
        return None
    if _pasado(pos['lado'], precio, sl_duro):
        return "STOP DE EMERGENCIA (el precio siguió en contra mientras esperaba tu respuesta)"
    if ahora - c['ts'] >= posiciones.CONSULTA_ESPERA_SEG:
        activar_stop_duro(coin, pos, auto=True)      # sin tu OK el bot NO cierra: queda el stop de emergencia
    return None

def gestionar_posicion(ex, coin, pos):
    ms = pos['market_symbol']
    try:
        precio = float(ex.fetch_ticker(ms)['last'])
    except Exception as e:
        pos['errores_precio'] = pos.get('errores_precio', 0) + 1
        print(f"Error leyendo precio de {coin}: {e}")
        if pos['errores_precio'] == 5:
            avisar(f"⚠️ No puedo leer el precio de {coin} en MEXC. El SL/TP que quedó puesto en MEXC sigue activo; revisa tu posición.")
        return
    pos['errores_precio'] = 0
    pos['ultimo_precio'] = precio

    leida, real = False, None
    try:
        real = leer_posicion(ex, ms)
        leida = True
    except Exception as e:
        print(f"Error leyendo la posición de {coin}: {e}")
    if leida and real is None and time.time() - pos['abierta_ts'] > GRACIA_POSICION_SEG:
        finalizar_posicion(coin, pos, precio, "Cerrada en MEXC (SL/TP del exchange o cierre manual)")
        return
    if real:
        pos['contratos'] = real['contratos']
        pos['liquidacion'] = real.get('liquidacion')

    if pos.get('modo', 'trailing') == 'vigilar':
        vigilar_movimiento(coin, pos, precio)      # solo avisa; no cierra nada por su cuenta
        return

    if pos.get('sl_duro_activo'):
        if _pasado(pos['lado'], precio, pos['sl_duro']):
            _cerrar_y_finalizar(ex, coin, pos, precio, "STOP DE EMERGENCIA (decidiste mantener y el precio siguió en contra)")
            return
        if _a_favor_de(pos['lado'], precio, pos['sl_blando'], 0.5 * pos['riesgo']):
            pos['sl_duro_activo'] = False
            pos['sl'] = pos['sl_blando']
            enviar_dueno(f"✅ {coin}: el precio se recuperó. Vuelvo al stop normal (${_p(pos['sl'])}).")
        else:
            vigilar_movimiento(coin, pos, precio)
            return

    accion, motivo = senales.avanzar_posicion(pos, precio)
    if accion != 'CERRAR' and pos.get('consulta'):
        pos.pop('consulta', None)
        enviar_dueno(f"✅ {coin}: el precio volvió por encima del stop. Falsa alarma; sigo vigilando.")
    if accion == 'CERRAR':
        cerrar_con = decidir_cierre(coin, pos, precio, motivo)
        if cerrar_con:
            _cerrar_y_finalizar(ex, coin, pos, precio, cerrar_con)
        return
    if accion == 'SUBIR_SL':
        mejora = abs(pos['sl'] - pos['sl_notificado'])
        if mejora >= 0.25 * pos['riesgo']:
            pos['sl_notificado'] = pos['sl']
            protegido = pos['sl'] >= pos['entrada'] if pos['lado'] == 'buy' else pos['sl'] <= pos['entrada']
            avisar(f"📈 {coin}: stop ajustado a ${_p(pos['sl'])} "
                   f"({'ganancia protegida ✅' if protegido else 'riesgo reducido'}). Precio actual: ${_p(precio)}")
    vigilar_movimiento(coin, pos, precio)

def bucle_gestion_posiciones():
    """Cada INTERVALO_GESTION_SEG revisa tus posiciones: mueve el stop, avisa de lo que sube o baja y
    sugiere salidas. Cada INTERVALO_DETECCION_SEG busca posiciones abiertas que el bot no conoce."""
    time.sleep(30)
    ultima_deteccion = 0.0
    while True:
        try:
            ex = crear_instancia_exchange('swap')
            if time.time() - ultima_deteccion >= INTERVALO_DETECCION_SEG:
                ultima_deteccion = time.time()
                try:
                    detectar_posiciones_nuevas(ex)
                except Exception as e:
                    print(f"Error buscando posiciones nuevas: {e}")
            for coin, pos in list(posiciones_gestionadas.items()):
                try:
                    gestionar_posicion(ex, coin, pos)
                except Exception as e:
                    print(f"Error gestionando {coin}: {e}")
        except Exception as e:
            print(f"Error en bucle de gestión de posiciones: {e}")
        time.sleep(INTERVALO_GESTION_SEG)

def margen_de_posicion(ex, p):
    if p['margen'] > 0:
        return p['margen']
    lev = p['apalancamiento'] or APALANCAMIENTO_AUTO
    tam = float(ex.market(p['market_symbol']).get('contractSize') or 1.0)
    return p['contratos'] * tam * p['entrada'] / lev

def enviar_dueno(texto, markup=None):
    try:
        bot.send_message(DUENO_ID, texto, reply_markup=markup)
    except Exception as e:
        print(f"No pude enviar el mensaje a Telegram: {e}")


def enviar_senal_con_grafico(chat_id, coin, senal, texto, markup=None, velas=None, timeframe="15m"):
    """Señal de entrada con el dibujo de la operación (velas, EMAs, entrada/stop/meta,
    soporte/resistencia). Si el dibujo o la foto fallan, manda solo el texto: la señal
    nunca se pierde por el dibujo. Sin velas, las busca en MEXC (250 cerradas)."""
    try:
        import io
        import grafico
        if velas is None:
            ex = crear_instancia_exchange('swap')
            ahora = int(time.time() * 1000)
            tf_ms = {"15m": 900000, "1h": 3600000}.get(timeframe, 900000)
            velas = senales.solo_cerradas(
                ex.fetch_ohlcv(f"{coin}/USDT:USDT", timeframe=timeframe,
                               since=ahora - 250 * tf_ms, limit=250), tf_ms, ahora)
        png = grafico.dibujar_operacion(coin, velas, senal)
        foto = io.BytesIO(png)
        foto.name = f"{coin}_operacion.png"
        if len(texto) <= 1024:
            bot.send_photo(chat_id, foto, caption=texto, reply_markup=markup)
        else:
            fmt = lambda x: f"{x:,.2f}" if abs(x) >= 1 else f"{x:.6f}"
            p = float(senal["precio"])
            largo = senal["direccion"] == "LONG"
            sl = p * (1 - senal["sl_pct"] / 100) if largo else p * (1 + senal["sl_pct"] / 100)
            tp = p * (1 + senal["tp_pct"] / 100) if largo else p * (1 - senal["tp_pct"] / 100)
            bot.send_photo(chat_id, foto,
                           caption=f"📊 {coin} {senal['tipo']} — Entrada ${fmt(p)} · Stop ${fmt(sl)} · Meta ${fmt(tp)}")
            bot.send_message(chat_id, texto, reply_markup=markup)
        return
    except Exception as e:
        print(f"No pude enviar la señal de {coin} con dibujo: {e}")
    try:
        bot.send_message(chat_id, texto, reply_markup=markup)
    except Exception as e:
        print(f"No pude enviar la señal de {coin} ni como texto: {e}")

def adoptar_posicion(ex, p, modo, precio=None):
    """Empieza a gestionar una posición que el bot no abrió (modo 'trailing' o 'vigilar')."""
    lado = posiciones.lado_orden(p['lado'])
    if precio is None:
        precio = float(ex.fetch_ticker(p['market_symbol'])['last'])
    pos, nota = posiciones.crear_posicion_adoptada(lado, p['entrada'], precio, SL_PORCENTAJE, modo)
    lev = p['apalancamiento'] or APALANCAMIENTO_AUTO
    margen = margen_de_posicion(ex, p)
    v = posiciones.variacion(lado, p['entrada'], precio, margen, lev)
    pos.update({'coin': p['coin'], 'market_symbol': p['market_symbol'], 'margen': margen,
                'apalancamiento': lev, 'contratos': p['contratos'], 'abierta_ts': 0, 'id': 'adoptada',
                'ultimo_precio': precio, 'sl_notificado': pos['sl'], 'aviso_error': 0,
                'open_type': p.get('open_type'), 'position_id': p.get('position_id'),
                'liquidacion': p.get('liquidacion'),
                'ultimo_escalon': int(v['pct_margen'] / posiciones.ESCALON_PNL_PCT),
                'ultimo_aviso_ts': time.time()})
    with _lock_pos:
        posiciones_gestionadas[p['coin']] = pos
    modos.guardar(p['coin'], lado, p['entrada'], modo)
    return pos, (nota if modo == 'trailing' else None)

def teclado_posicion(coin, pos=None, gestionada=True):
    m = InlineKeyboardMarkup(row_width=2)
    if gestionada and pos is not None:
        trailing_on = pos.get('modo', 'trailing') != 'vigilar'
        m.add(InlineKeyboardButton("🔄 Actualizar", callback_data=f"pos_act_{coin}"),
              InlineKeyboardButton("🔒 Asegurar entrada", callback_data=f"pos_be_{coin}"))
        m.add(InlineKeyboardButton("❌ Cerrar ahora", callback_data=f"pos_cl_{coin}"),
              InlineKeyboardButton("📈 Trailing: " + ("ON ✅" if trailing_on else "OFF"), callback_data=f"pos_tr_{coin}"))
    else:
        m.add(InlineKeyboardButton("✅ Gestionar con trailing", callback_data=f"padopt_{coin}_trailing"),
              InlineKeyboardButton("👀 Solo vigilar", callback_data=f"padopt_{coin}_vigilar"))
        m.add(InlineKeyboardButton("❌ Cerrar ahora", callback_data=f"pos_cl_{coin}"),
              InlineKeyboardButton("🙈 Ignorar", callback_data=f"pign_{coin}"))
    return m

def vista_posicion(ex, p):
    """(texto, teclado) de una posición abierta, gestionada o no."""
    coin = p['coin']
    precio = float(ex.fetch_ticker(p['market_symbol'])['last'])
    pos = posiciones_gestionadas.get(coin)
    if pos:
        pos['ultimo_precio'] = precio
        return (posiciones.texto_posicion(coin, pos, precio, pos['margen'], pos['apalancamiento'], p.get('liquidacion')),
                teclado_posicion(coin, pos, True))
    lev = p['apalancamiento'] or APALANCAMIENTO_AUTO
    base = {'lado': posiciones.lado_orden(p['lado']), 'entrada': p['entrada'], 'sl': 0}
    return (posiciones.texto_posicion(coin, base, precio, margen_de_posicion(ex, p), lev, p.get('liquidacion'), gestionada=False),
            teclado_posicion(coin, None, False))

def enviar_oferta_adopcion(ex, p):
    try:
        texto, markup = vista_posicion(ex, p)
        enviar_dueno(
            "🔎 Detecté una posición abierta que el bot todavía no gestiona (¿la abriste tú?):\n\n" + texto +
            f"\n\n¿Qué hago?\n• Trailing: pongo un stop a {SL_PORCENTAJE}% de tu entrada que sube con el precio; "
            f"si el precio lo toca, cierro a mercado.\n• Solo vigilar: te aviso de lo que sube o baja y de posibles "
            f"salidas, sin cerrar nada por mi cuenta.", markup)
    except Exception as e:
        print(f"No pude ofrecer la posición de {p.get('coin')}: {e}")

def detectar_posiciones_nuevas(ex):
    """Busca en MEXC posiciones abiertas que el bot no gestiona (las abiertas a mano o por una orden límite
    ejecutada) y te ofrece gestionarlas con botones. Cada posición se ofrece una sola vez."""
    abiertas = leer_todas_las_posiciones(ex)
    vivas = {p['coin'] for p in abiertas}
    for p in abiertas:
        coin = p['coin']
        if coin in posiciones_gestionadas:
            continue
        if time.time() - ultima_orden_ts.get(coin, 0) < 45:
            continue      # la acaba de abrir el bot y se registra sola
        clave = (p['lado'], round(p['entrada'], 8))
        if posiciones_avisadas.get(coin) == clave:
            continue
        posiciones_avisadas[coin] = clave
        recordado = modos.buscar(coin, posiciones.lado_orden(p['lado']), p['entrada'])
        if recordado == 'ignorar':
            continue          # ya dijiste que no quieres que la gestione
        if recordado in ('trailing', 'vigilar'):
            pos, nota = adoptar_posicion(ex, p, recordado)
            enviar_dueno(f"🔁 Reinicié, pero recuerdo tu elección para {coin}: "
                         + ("gestiono con trailing." if recordado == 'trailing' else "solo vigilo (no cierro nada por mi cuenta).")
                         + (f"\n⚠️ {nota}" if nota else "") + "\n\n"
                         + posiciones.texto_posicion(coin, pos, pos['ultimo_precio'], pos['margen'], pos['apalancamiento'], pos.get('liquidacion')),
                         teclado_posicion(coin, pos, True))
            continue
        if ADOPTAR_MANUALES_AUTO and coin in MONEDAS_OPERABLES:
            # Adopción automática: solo monedas operables (BTC nunca se opera, solo es indicador).
            # Nunca cierra solo por adoptarla (lo garantiza crear_posicion_adoptada).
            pos, nota = adoptar_posicion(ex, p, 'trailing')
            enviar_dueno(f"🤖 Adopté sola tu posición manual de {coin} con trailing.\n"
                         f"Entrada: ${posiciones.fmt_precio(pos['entrada'])} | Stop del bot: ${posiciones.fmt_precio(pos['sl'])}"
                         + (f"\n⚠️ {nota}" if nota else "") + "\n\n"
                         + posiciones.texto_posicion(coin, pos, pos['ultimo_precio'], pos['margen'], pos['apalancamiento'], pos.get('liquidacion')),
                         teclado_posicion(coin, pos, True))
            continue
        enviar_oferta_adopcion(ex, p)
    for coin in [c for c in posiciones_avisadas if c not in vivas]:
        posiciones_avisadas.pop(coin, None)
    modos.olvidar_cerradas(vivas)

def evaluar_salida(coin, pos, ganancia_pct):
    """Lee 15m (y cada 15 min las señales de 1H) y devuelve motivos para sugerir cerrar. Nunca cierra solo."""
    try:
        ex = crear_instancia_exchange('swap')
        ahora = int(time.time() * 1000)
        crudas = ex.fetch_ohlcv(pos['market_symbol'], timeframe='15m', since=ahora - 130 * 900000, limit=130)
        cierres = [x[4] for x in senales.solo_cerradas(crudas, 900000, ahora)]
        ema9 = indicadores.ultima_ema(cierres, 9) if len(cierres) >= 25 else None
        ema21 = indicadores.ultima_ema(cierres, 21) if len(cierres) >= 25 else None
        rsi15 = indicadores.rsi(cierres) if len(cierres) >= 15 else None
        contraria = None
        if time.time() - pos.get('ultima_eval_senal', 0) >= 900:
            pos['ultima_eval_senal'] = time.time()
            contrario = 'VENTA' if pos['lado'] == 'buy' else 'COMPRA'
            for s in detectar_rompimiento(coin, 'swap'):
                if s.get('tipo') == contrario and s.get('veredicto') in ('VERDADERO', 'PROBABLE'):
                    contraria = s
                    break
        return posiciones.sugerir_salida(pos['lado'], ganancia_pct, rsi15, ema9, ema21, contraria)
    except Exception as e:
        print(f"No pude evaluar la salida de {coin}: {e}")
        return []

def vigilar_movimiento(coin, pos, precio):
    """Te avisa (con botones) cada vez que la posición cambia 10 % de tu margen, y cuando hay motivos para salir."""
    ahora = time.time()
    v = posiciones.variacion(pos['lado'], pos['entrada'], precio, pos['margen'], pos['apalancamiento'])
    # Control de ganancia/pérdida: avisa cuando la posición ENTRA en ganancia o en pérdida.
    estado_pnl = 'ganancia' if v['pnl_usdt'] > 0 else ('perdida' if v['pnl_usdt'] < 0 else None)
    if estado_pnl is not None:
        if 'estado_pnl' not in pos:
            pos['estado_pnl'] = estado_pnl  # primera lectura: marca sin avisar
        elif pos['estado_pnl'] != estado_pnl:
            pos['estado_pnl'] = estado_pnl
            if estado_pnl == 'ganancia':
                enviar_dueno(f"🟢 {coin} entró en GANANCIA (${v['pnl_usdt']:+.2f}). Precio actual: ${_p(precio)}")
            else:
                enviar_dueno(f"🔴 {coin} entró en PÉRDIDA (${v['pnl_usdt']:+.2f}). Precio actual: ${_p(precio)}")
    esc = posiciones.escalon_nuevo(v['pct_margen'], pos.get('ultimo_escalon', 0))
    if esc is not None and ahora - pos.get('ultimo_aviso_ts', 0) >= posiciones.MIN_SEG_ENTRE_AVISOS:
        pos['ultimo_escalon'] = esc
        pos['ultimo_aviso_ts'] = ahora
        titulo = "📈 Tu posición va a favor" if v['pnl_usdt'] >= 0 else "📉 Tu posición va en contra"
        enviar_dueno(f"{titulo}\n\n" + posiciones.texto_posicion(coin, pos, precio, pos['margen'], pos['apalancamiento'], pos.get('liquidacion')),
                     teclado_posicion(coin, pos, True))
    if (ahora - pos.get('ultima_sugerencia_ts', 0) >= posiciones.SEG_ENTRE_SUGERENCIAS
            and ahora - pos.get('ultima_eval_salida', 0) >= INTERVALO_EVAL_SALIDA_SEG):
        pos['ultima_eval_salida'] = ahora
        motivos = evaluar_salida(coin, pos, v['pct_precio'])
        if motivos:
            pos['ultima_sugerencia_ts'] = ahora
            m = InlineKeyboardMarkup(row_width=2)
            m.add(InlineKeyboardButton("❌ Cerrar ahora", callback_data=f"pos_cl_{coin}"),
                  InlineKeyboardButton("✋ Mantener", callback_data=f"pos_clno_{coin}"))
            m.add(InlineKeyboardButton("🔒 Asegurar entrada", callback_data=f"pos_be_{coin}"))
            if pos.get('adoptada'):
                encabezado = f"🚨🚨 SALIR {coin} 🚨🚨\n\n⚠️ Es una posición adoptada (la abriste tú): el bot recomienda salir ahora."
            else:
                encabezado = f"💡 Posible momento de salir de {coin}"
            enviar_dueno(encabezado + "\n\n" + "\n".join(f"• {x}" for x in motivos) + "\n\n"
                         + posiciones.texto_posicion(coin, pos, precio, pos['margen'], pos['apalancamiento'], pos.get('liquidacion')), m)

def cerrar_desde_boton(ex, coin):
    """Cierra a mercado una posición (la gestione el bot o no). Devuelve (ok, mensaje_si_no_ok)."""
    ms = f"{coin}/USDT:USDT"
    p = leer_posicion(ex, ms)
    if not p:
        with _lock_pos:
            posiciones_gestionadas.pop(coin, None)
        return False, f"ℹ️ Ya no veo una posición abierta de {coin}."
    lado = posiciones.lado_orden(p['lado'])
    lev = p['apalancamiento'] or APALANCAMIENTO_AUTO
    precio = float(ex.fetch_ticker(ms)['last'])
    cerrar_posicion_mercado(ex, {'market_symbol': ms, 'lado': lado, 'contratos': p['contratos'], 'apalancamiento': lev,
                                 'open_type': p.get('open_type'), 'position_id': p.get('position_id')})
    pos = posiciones_gestionadas.get(coin) or {'lado': lado, 'entrada': p['entrada'], 'margen': margen_de_posicion(ex, p),
                                               'apalancamiento': lev, 'sl': 0, 'id': 'manual'}
    finalizar_posicion(coin, pos, precio, "Cierre desde Telegram (botón)")
    return True, None

def accion_posicion(call, datos):
    """Botones de posiciones: pos_act / pos_be / pos_cl / pos_clok / pos_clno / pos_tr / padopt / pign."""
    chat = call.message.chat.id
    accion = datos[0]
    ex = crear_instancia_exchange('swap')

    if accion == 'padopt' and len(datos) >= 3:
        coin, modo = datos[1], datos[2]
        if modo not in ('trailing', 'vigilar'):
            bot.answer_callback_query(call.id, "Opción no válida.")
            return
        if coin in posiciones_gestionadas:
            bot.answer_callback_query(call.id, "Ya la estoy gestionando.")
            return
        p = leer_posicion(ex, f"{coin}/USDT:USDT")
        if not p:
            bot.answer_callback_query(call.id, "Ya no hay posición.")
            bot.send_message(chat, f"ℹ️ Ya no veo una posición abierta de {coin}.")
            return
        pos, nota = adoptar_posicion(ex, p, modo)
        bot.answer_callback_query(call.id, "Listo.")
        intro = (f"✅ Gestiono tu posición de {coin} con trailing." if modo == 'trailing'
                 else f"👀 Vigilo tu posición de {coin}. No cerraré nada por mi cuenta.")
        if nota:
            intro += f"\n⚠️ {nota}"
        bot.send_message(chat, intro + "\n\n" + posiciones.texto_posicion(coin, pos, pos['ultimo_precio'], pos['margen'], pos['apalancamiento'], pos.get('liquidacion')),
                         reply_markup=teclado_posicion(coin, pos, True))
        return

    if accion == 'pign' and len(datos) >= 2:
        bot.answer_callback_query(call.id, "Ok.")
        try:
            p_ign = leer_posicion(ex, f"{datos[1]}/USDT:USDT")
            if p_ign:
                modos.guardar(datos[1], posiciones.lado_orden(p_ign['lado']), p_ign['entrada'], 'ignorar')
        except Exception as e:
            print(f"No pude recordar que ignoras {datos[1]}: {e}")
        bot.send_message(chat, f"🙈 Ok, no gestiono tu posición de {datos[1]}. Usa /posiciones cuando quieras verla.")
        return

    if accion != 'pos' or len(datos) < 3:
        bot.answer_callback_query(call.id, "Opción no reconocida.")
        return
    sub, coin = datos[1], datos[2]
    ms = f"{coin}/USDT:USDT"

    if sub == 'act':
        p = leer_posicion(ex, ms)
        if not p:
            bot.answer_callback_query(call.id, "Ya no hay posición.")
            return
        texto, markup = vista_posicion(ex, p)
        bot.answer_callback_query(call.id, "Actualizado.")
        try:
            bot.edit_message_text(texto, chat, call.message.message_id, reply_markup=markup)
        except Exception as e:
            if 'not modified' not in str(e):
                bot.send_message(chat, texto, reply_markup=markup)

    elif sub == 'be':
        pos = posiciones_gestionadas.get(coin)
        if not pos:
            bot.answer_callback_query(call.id, "No la gestiono todavía.")
            bot.send_message(chat, f"ℹ️ Primero pulsa «Gestionar con trailing» en tu posición de {coin}; después podrás asegurar la entrada.")
            return
        if pos.get('modo', 'trailing') == 'vigilar':
            bot.answer_callback_query(call.id, "Trailing apagado.")
            bot.send_message(chat, f"ℹ️ El trailing de {coin} está apagado. Enciéndelo con el botón «Trailing» para que el bot cuide el stop.")
            return
        precio = float(ex.fetch_ticker(ms)['last'])
        ok, msg = posiciones.asegurar_entrada(pos, precio)
        bot.answer_callback_query(call.id, "Entrada asegurada ✅" if ok else "No se pudo.")
        bot.send_message(chat, ("🔒 " if ok else "ℹ️ ") + msg)

    elif sub == 'cl':
        p = leer_posicion(ex, ms)
        if not p:
            bot.answer_callback_query(call.id, "Ya no hay posición.")
            return
        texto, _ = vista_posicion(ex, p)
        m = InlineKeyboardMarkup(row_width=2)
        m.add(InlineKeyboardButton("✅ Sí, cerrar a mercado", callback_data=f"pos_clok_{coin}"),
              InlineKeyboardButton("↩️ No, mantener", callback_data=f"pos_clno_{coin}"))
        bot.answer_callback_query(call.id, "Confirma el cierre.")
        bot.send_message(chat, f"⚠️ ¿Cierro {coin} a mercado ahora?\n\n" + texto, reply_markup=m)

    elif sub == 'mt':
        pos = posiciones_gestionadas.get(coin)
        if not pos or pos.get('modo', 'trailing') == 'vigilar':
            bot.answer_callback_query(call.id, "No hay nada que mantener.")
            return
        if pos.get('sl_duro_activo'):
            bot.answer_callback_query(call.id, "Ya la mantengo.")
            return
        bot.answer_callback_query(call.id, "Mantengo la posición.")
        activar_stop_duro(coin, pos)

    elif sub == 'clno':
        bot.answer_callback_query(call.id, "Se mantiene abierta.")
        bot.send_message(chat, f"✋ Ok, dejo abierta tu posición de {coin}.")

    elif sub == 'clok':
        bot.answer_callback_query(call.id, "Cerrando...")
        try:
            ok, msg = cerrar_desde_boton(ex, coin)
        except Exception as e:
            bot.send_message(chat, f"❌ No pude cerrar {coin}: {e}\nCiérrala manualmente en MEXC.")
            return
        if not ok:
            bot.send_message(chat, msg)

    elif sub == 'tr':
        pos = posiciones_gestionadas.get(coin)
        if not pos:
            bot.answer_callback_query(call.id, "No la gestiono todavía.")
            return
        if pos.get('modo', 'trailing') != 'vigilar':
            pos['modo'] = 'vigilar'
            msg = "👀 Trailing APAGADO: ya no muevo ni activo el stop del bot. Sigues con el SL/TP que tengas en MEXC."
        else:
            precio = float(ex.fetch_ticker(ms)['last'])
            nuevo, nota = posiciones.crear_posicion_adoptada(pos['lado'], pos['entrada'], precio, SL_PORCENTAJE, 'trailing')
            for k in ('sl', 'sl_inicial', 'riesgo', 'mejor', 'modo'):
                pos[k] = nuevo[k]
            pos['sl_notificado'] = nuevo['sl']
            msg = f"📈 Trailing ENCENDIDO: stop en ${_p(nuevo['sl'])} (recalculado desde el precio actual)." + (f"\n⚠️ {nota}" if nota else "")
        bot.answer_callback_query(call.id, "Listo.")
        modos.guardar(coin, pos['lado'], pos['entrada'], pos.get('modo', 'trailing'))
        p = leer_posicion(ex, ms)
        if p:
            texto, markup = vista_posicion(ex, p)
            bot.send_message(chat, msg + "\n\n" + texto, reply_markup=markup)
        else:
            bot.send_message(chat, msg)

    else:
        bot.answer_callback_query(call.id, "Opción no reconocida.")

def types_msg(call):
    """Convierte un callback en algo con .chat.id para reutilizar los comandos."""
    class _M:
        chat = call.message.chat
    return _M()

def analisis_de_posicion(ex, p):
    """Línea de análisis del mercado frente a una posición (None si no se pudo leer)."""
    try:
        lado = posiciones.lado_orden(p['lado'])
        v15, v1h, v4h, vbtc = obtener_velas_zona(p['coin'], ex)
        r = posiciones.rasgos_stop(lado, v15, v1h, v4h, vbtc)
        return posiciones.texto_analisis(posiciones.diagnostico_stop(lado, r)) if r else None
    except Exception as e:
        print(f"No pude analizar {p.get('coin')}: {e}")
        return None

_ultimo_error_activas = ['']

def resumen_activas(con_analisis=True):
    """(n, texto) de las operaciones abiertas en MEXC Futuros. n es None si no se pudo leer."""
    abiertas, ex, error = None, None, None
    for intento in (1, 2):                       # MEXC a veces falla un instante: se reintenta una vez
        try:
            ex = crear_instancia_exchange('swap')
            abiertas = leer_todas_las_posiciones(ex)
            break
        except Exception as e:
            error = e
            time.sleep(1.5)
    if abiertas is None:
        _ultimo_error_activas[0] = str(error)[:80]
        return None, f"⚠️ No pude leer tus operaciones en MEXC ahora mismo ({error}). Intenta de nuevo en unos segundos."
    try:
        lineas = []
        for p in abiertas:
            try:
                precio = float(ex.fetch_ticker(p['market_symbol'])['last'])
                linea = posiciones.linea_activa(p, precio)
                an = analisis_de_posicion(ex, p) if con_analisis else None
                lineas.append(linea + (f"\n   🧭 {an}" if an else ""))
            except Exception as e:
                lineas.append(f"{p['coin']} {p['lado']} (no pude leer su precio: {e})")
        return len(abiertas), posiciones.texto_activas(lineas)
    except Exception as e:
        return None, f"⚠️ No pude leer tus operaciones en MEXC ahora mismo ({e})."

@bot.message_handler(commands=['activas'], func=es_dueno)
def cmd_activas(message):
    global ULTIMO_CHAT_ID
    ULTIMO_CHAT_ID = message.chat.id
    n, texto = resumen_activas()
    m = None
    if n:
        m = InlineKeyboardMarkup(row_width=1)
        m.add(InlineKeyboardButton("🎛️ Ver con botones (cerrar, asegurar...)", callback_data="activas_ver"))
    bot.send_message(message.chat.id, texto, reply_markup=m)

def enviar_toggle_autoadopt(chat_id):
    """Botón ON/OFF para adoptar solas las manuales (solo ETH/ZEC, nunca BTC)."""
    m = InlineKeyboardMarkup(row_width=1)
    m.add(InlineKeyboardButton(f"🤖 Adoptar mis manuales: {'ON ✅' if ADOPTAR_MANUALES_AUTO else 'OFF ⏸️'}", callback_data="autoadopt_toggle"))
    bot.send_message(chat_id, "Adoptar mis manuales (solo operables: ETH, ZEC, PAXG, UKOIL; nunca BTC): el bot adopta sola cada posición manual nueva con trailing.", reply_markup=m)

@bot.message_handler(commands=['posiciones'], func=es_dueno)
def ver_posiciones(message):
    global ULTIMO_CHAT_ID
    ULTIMO_CHAT_ID = message.chat.id
    try:
        ex = crear_instancia_exchange('swap')
        abiertas = leer_todas_las_posiciones(ex)
    except Exception as e:
        bot.send_message(message.chat.id, f"⚠️ No pude leer tus posiciones en MEXC ahora mismo ({e}). Intenta de nuevo en unos segundos.")
        return
    if not abiertas:
        bot.send_message(message.chat.id, "📭 No tienes posiciones abiertas en MEXC.")
        enviar_toggle_autoadopt(message.chat.id)
        return
    for p in abiertas:
        try:
            texto, markup = vista_posicion(ex, p)
            bot.send_message(message.chat.id, texto, reply_markup=markup)
        except Exception as e:
            bot.send_message(message.chat.id, f"⚠️ No pude mostrar {p['coin']}: {e}")
    enviar_toggle_autoadopt(message.chat.id)

@bot.message_handler(commands=['saldo'], func=es_dueno)
def ver_saldo(message):
    global ULTIMO_CHAT_ID
    ULTIMO_CHAT_ID = message.chat.id
    try:
        ex = crear_instancia_exchange('swap')
        bal = ex.fetch_balance()
    except Exception as e:
        bot.send_message(message.chat.id, f"⚠️ No pude leer tu saldo en MEXC ahora mismo ({e}). Intenta de nuevo en unos segundos.")
        return
    usdt = (bal.get('USDT') or {}) if isinstance(bal, dict) else {}
    total = usdt.get('total')
    libre = usdt.get('free')
    usado = usdt.get('used')
    lineas = ["💰 SALDO MEXC FUTUROS"]
    if total is not None:
        lineas.append(f"Total: ${total:.2f} USDT")
    if libre is not None:
        lineas.append(f"Disponible: ${libre:.2f} USDT")
    if usado is not None:
        lineas.append(f"En uso (margen): ${usado:.2f} USDT")
    if total is None and libre is None and usado is None:
        lineas.append("No pude desglosar el saldo en USDT; revisa MEXC.")
    try:
        ex_spot = crear_instancia_exchange('spot')
        bal_spot = ex_spot.fetch_balance()
        usdt_spot = (bal_spot.get('USDT') or {}) if isinstance(bal_spot, dict) else {}
        lineas.append("")
        lineas.append("📊 SPOT")
        if usdt_spot.get('total') is not None:
            lineas.append(f"Total: ${usdt_spot['total']:.2f} USDT")
        if usdt_spot.get('free') is not None:
            lineas.append(f"Disponible: ${usdt_spot['free']:.2f} USDT")
        if usdt_spot.get('total') is None and usdt_spot.get('free') is None:
            lineas.append("Sin saldo USDT en spot.")
    except Exception:
        lineas.append("")
        lineas.append("📊 SPOT: no pude leerlo ahora mismo.")
    try:
        abiertas = leer_todas_las_posiciones(ex)
    except Exception:
        abiertas = []
    if abiertas:
        lineas.append("")
        lineas.append("📌 Posiciones abiertas:")
        pnl_total = 0.0
        for p in abiertas:
            try:
                precio = float(ex.fetch_ticker(p['market_symbol'])['last'])
            except Exception:
                precio = p['entrada']
            margen = p['margen'] if p['margen'] > 0 else margen_de_posicion(ex, p)
            pct, pnl = senales.pnl_estimado(p['lado'], p['entrada'], precio, margen, p['apalancamiento'])
            pnl_total += pnl
            lineas.append(f"{p['coin']} {'LONG 🟢' if p['lado'] == 'buy' else 'SHORT 🔴'} | PnL {pct:+.2f}% (${pnl:+.2f})")
        lineas.append(f"PnL total no realizado: ${pnl_total:+.2f}")
    else:
        lineas.append("")
        lineas.append("Sin posiciones abiertas.")
    bot.send_message(message.chat.id, "\n".join(lineas))

def enviar_aviso_inicio():
    avisar(f"🟢 Bot iniciado.\n• Operar: {', '.join(MONEDAS_OPERABLES)} | {APALANCAMIENTO_AUTO}x | margen {' / '.join(f'${m:g}' for m in MONTOS_PERMITIDOS)}\n"
           f"• Reportes cada 15 min: {', '.join(MONEDAS_REPORTE)}\n• Límite de pérdida diaria: ${LIMITE_PERDIDA_DIARIA:.2f}\n• Usa /posiciones para ver y manejar tus posiciones.")
@bot.message_handler(commands=['start', 'menu'], func=es_dueno)
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
    n_activas, _ = resumen_activas(con_analisis=False)
    markup.add(InlineKeyboardButton(f"📌 Operaciones activas ({'?' if n_activas is None else n_activas})", callback_data="activas_x"))
    markup.add(InlineKeyboardButton("📊 Backtest 30 días", callback_data="backtest_go"))
    linea_activas = ("📌 Operaciones activas en MEXC Futuros: " + (f"no pude leerlas ahora ({_ultimo_error_activas[0]})" if n_activas is None else str(n_activas)))
    bot.send_message(message.chat.id, "📈 **PANEL DE SEÑALES - MEXC** 🟢\n\n" + linea_activas + "\n\nComandos:\n• /menu - Panel\n• /operar - Operar manual\n• /analisis - Análisis técnico\n• /predicciones - Predicciones 5 min\n• /activas - Cuántas operaciones tienes abiertas en MEXC\n• /posiciones - Tus posiciones con botones\n• /estado - Posiciones y pérdida del día\n• /saldo - Tu saldo en MEXC y ganancia/pérdida abierta\n• /mercado - Qué ve el bot ahora (puntos de entrada)\n• /senales on|off - Avisos de entrada\n• /sensibilidad - Estricta o normal\n• /vigilar ETH 3500 - Aviso al llegar a un precio\n• /aciertos - Historial de aciertos\n• /backtest - Probar la estrategia con datos pasados", reply_markup=markup, parse_mode="Markdown")

@bot.message_handler(commands=['operar'], func=es_dueno)
def menu_operar(message):
    global ULTIMO_CHAT_ID
    ULTIMO_CHAT_ID = message.chat.id
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("⚡ Futuros (MEXC)", callback_data="menu_futuros")
    )
    bot.send_message(message.chat.id, "⚙️ **CENTRAL DE OPERACIONES (FUTUROS PERPETUOS)** 🟢", reply_markup=markup, parse_mode="Markdown")

@bot.message_handler(commands=['analisis'], func=es_dueno)
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
        InlineKeyboardButton("🐸 PEPE", callback_data="ana_PEPE"),
        InlineKeyboardButton("🥇 PAXG (Oro)", callback_data="ana_PAXG"),
        InlineKeyboardButton("🛢️ UKOIL (Brent)", callback_data="ana_UKOIL")
    )
    bot.send_message(message.chat.id, "🔍 **Selecciona el activo para análisis técnico:**", reply_markup=markup, parse_mode="Markdown")

@bot.message_handler(commands=['predicciones'], func=es_dueno)
def menu_predicciones(message):
    global ULTIMO_CHAT_ID
    ULTIMO_CHAT_ID = message.chat.id
    markup = InlineKeyboardMarkup(row_width=3)
    markup.add(*[InlineKeyboardButton(f"🔮 {c}", callback_data=f"pred_{c}") for c in MONEDAS_PREDICCION])
    bot.send_message(message.chat.id, "🔮 **PREDICCIONES 5 MINUTOS** 🔮\n\nElige el activo para analizar:", reply_markup=markup, parse_mode="Markdown")

_backtest_en_curso = False

def _correr_backtest(chat_id, args):
    """Backtest en hilo aparte (puede tardar minutos): avisa en el mismo chat al terminar."""
    global _backtest_en_curso
    try:
        monedas, dias, tf = [], 30, "15m"
        for a in args:
            au = a.upper()
            if au in MONEDAS_OPERABLES + ["BTC"]:
                monedas.append(au)
            elif au in ("15M", "1H"):
                tf = au.lower()
            elif au.isdigit():
                dias = max(7, min(365, int(au)))
        if not monedas:
            monedas = list(MONEDAS_OPERABLES)
        bot.send_message(chat_id, f"⏳ Calculando backtest {tf} ({dias} días) para {', '.join(monedas)}... te voy avisando moneda por moneda cuando cada una esté lista.")
        ex = crear_instancia_exchange('swap')
        resultados = []
        for coin in monedas:
            # Cada moneda aislada: si una falla, las demás igual llegan y el TOTAL igual se manda
            try:
                res = backtest.ejecutar(ex, coin, dias, tf, SIN_FILTRO_BTC)
            except Exception as e:
                res = {"coin": coin, "error": f"Falló inesperadamente: {e}"}
            resultados.append(res)
            try:
                bot.send_message(chat_id, backtest.formatear(res))
            except Exception:
                pass  # un envío fallido no debe matar el resto del backtest
        ok = [r for r in resultados if not r.get("error")]
        if ok:
            tot_n = sum(r["n"] for r in ok)
            tot_r = round(sum(r["net_r"] for r in ok), 2)
            bot.send_message(chat_id, f"TOTAL: {tot_n} operaciones | Neto: {tot_r:+.2f}R")
        bot.send_message(chat_id, "⚠️ El pasado no garantiza el futuro. Sin comisiones ni deslizamiento. Mide la estrategia, no los avisos.")
    except Exception as e:
        bot.send_message(chat_id, f"❌ El backtest falló: {e}")
    finally:
        _backtest_en_curso = False

def lanzar_backtest(chat_id, args):
    """Lanza el backtest en hilo aparte si no hay otro corriendo."""
    global _backtest_en_curso
    if _backtest_en_curso:
        bot.send_message(chat_id, "⏳ Ya hay un backtest corriendo, espera a que termine.")
        return
    _backtest_en_curso = True
    threading.Thread(target=_correr_backtest, args=(chat_id, args), daemon=True).start()

@bot.message_handler(commands=['backtest'], func=es_dueno)
def menu_backtest(message):
    args = (message.text or "").split()[1:]
    lanzar_backtest(message.chat.id, args)

@bot.message_handler(commands=['estado'], func=es_dueno)
def estado_posiciones(message):
    global ULTIMO_CHAT_ID
    ULTIMO_CHAT_ID = message.chat.id
    _rotar_dia()
    lineas = ["📊 ESTADO DEL BOT", f"Pérdida acumulada hoy: ${perdida_acumulada_dia:.2f} / ${LIMITE_PERDIDA_DIARIA:.2f}", ""]
    if not posiciones_gestionadas:
        lineas.append("Sin posiciones abiertas gestionadas por el bot.")
    for coin, p in posiciones_gestionadas.items():
        largo = p['lado'] == 'buy'
        ultimo = p.get('ultimo_precio', p['entrada'])
        pct, pnl = senales.pnl_estimado(p['lado'], p['entrada'], ultimo, p['margen'], p['apalancamiento'])
        lineas.append(f"{coin} {'LONG 🟢' if largo else 'SHORT 🔴'} | entrada ${_p(p['entrada'])} | último ${_p(ultimo)}")
        lineas.append(f"   Stop del bot: ${_p(p['sl'])} | PnL aprox: {pct:+.2f}% (${pnl:+.2f})")
    bot.send_message(message.chat.id, "\n".join(lineas))

def registrar_prediccion_historial(coin, pred):
    try:
        ts = int(time.time() * 1000)
        historial.registrar({
            'id': f"pred-{coin}-{ts // 300000}", 'tipo': 'prediccion', 'symbol': coin,
            'direccion': pred['direccion'], 'precio': float(pred['precio']), 'ts': ts,
            'prob_sube': pred['prob_sube'], 'prob_baja': pred['prob_baja'],
            'confianza': pred['confianza'], 'atr_pct': pred['atr_pct']})
    except Exception as e:
        print(f"No pude registrar la predicción en el historial: {e}")

def registrar_senal_historial(coin, s):
    try:
        historial.registrar({
            'id': f"senal-{coin}-{s['subtipo']}-{int(s['ts'])}", 'tipo': 'senal', 'symbol': coin,
            'tipo_orden': s['tipo'], 'direccion': s['tipo'], 'precio': float(s['precio']),
            'ts': int(time.time() * 1000), 'veredicto': s['veredicto'], 'subtipo': s['subtipo'],
            'sl_pct': float(s['sl_pct']), 'tp_pct': float(s['tp_pct']),
            'puntos': s['puntos'], 'total': s['total']})
    except Exception as e:
        print(f"No pude registrar la señal en el historial: {e}")

def resolver_pendientes():
    """Evalúa con datos reales de MEXC las predicciones (a 5 min) y las señales (SL o TP primero)."""
    ahora = int(time.time() * 1000)
    pendientes = historial.pendientes(ahora)
    if not pendientes:
        return
    ex = crear_instancia_exchange('swap')
    for ev in pendientes:
        ms = f"{ev['symbol']}/USDT:USDT"
        try:
            if ev['tipo'] == 'prediccion':
                precio = float(ex.fetch_ticker(ms)['last'])
                historial.actualizar(ev['id'], historial.evaluar_prediccion(ev, precio, ahora))
            else:
                inicio = (ev['ts'] // 300000 + 1) * 300000  # primera vela de 5m completa tras la señal
                velas = [v for v in ex.fetch_ohlcv(ms, timeframe='5m', since=inicio, limit=60) if v[0] >= inicio]
                res = historial.simular_senal(ev['tipo_orden'], ev['precio'], ev['sl_pct'], ev['tp_pct'], velas)
                if res:
                    historial.actualizar(ev['id'], {'resultado': res})
                elif ahora - ev['ts'] > historial.HORIZONTE_SENAL_MS:
                    historial.actualizar(ev['id'], {'resultado': 'NEUTRO'})
        except Exception as e:
            print(f"No pude evaluar {ev.get('id')}: {e}")

def bucle_historial():
    """Cada 15 min registra en silencio una predicción de BTC, ETH y ZEC y evalúa las pendientes."""
    time.sleep(45)
    ultimo_registro = {}
    while True:
        try:
            ahora = time.time()
            for coin in MONEDAS_REPORTE:
                if ahora - ultimo_registro.get(coin, 0) >= 900:
                    ultimo_registro[coin] = ahora
                    pred = analizar_prediccion_5m(coin)
                    if pred:
                        registrar_prediccion_historial(coin, pred)
            resolver_pendientes()
        except Exception as e:
            print(f"Error en el historial de aciertos: {e}")
        time.sleep(60)

@bot.message_handler(commands=['senales'], func=es_dueno)
def cmd_senales(message):
    global ULTIMO_CHAT_ID
    ULTIMO_CHAT_ID = message.chat.id
    arg = (message.text.split()[1:] or [''])[0].lower()
    if arg in ('on', 'off'):
        avisos.poner_activo(arg == 'on')
    c = avisos.config()
    bot.send_message(message.chat.id,
                     f"🔔 Avisos de entrada: {'ACTIVADOS ✅' if c['activo'] else 'PAUSADOS ⏸️'}\n"
                     f"Sensibilidad: {c['sensibilidad'].upper()}\nAvisos enviados hoy: {avisos_hoy['n']}/{avisos.MAX_AVISOS_DIA}\n\n"
                     "Uso: /senales on | /senales off\nCambiar rigor: /sensibilidad estricta | normal")

@bot.message_handler(commands=['sensibilidad'], func=es_dueno)
def cmd_sensibilidad(message):
    global ULTIMO_CHAT_ID
    ULTIMO_CHAT_ID = message.chat.id
    arg = (message.text.split()[1:] or [''])[0].lower()
    if arg and not avisos.poner_sensibilidad(arg):
        bot.send_message(message.chat.id, "Usa: /sensibilidad estricta  o  /sensibilidad normal")
        return
    c = avisos.config()
    bot.send_message(message.chat.id,
                     f"🎚️ Sensibilidad actual: {c['sensibilidad'].upper()}\n"
                     "• estricta: solo avisa señales VERDADERAS (pocas, más fiables)\n"
                     "• normal: avisa también las PROBABLES (más avisos, menos fiables)\n\n"
                     "Cambiar: /sensibilidad estricta | normal")

@bot.message_handler(commands=['vigilar'], func=es_dueno)
def cmd_vigilar(message):
    global ULTIMO_CHAT_ID
    ULTIMO_CHAT_ID = message.chat.id
    args = message.text.split()[1:]
    chat = message.chat.id
    if args and args[0].lower() in ('borrar', 'off'):
        n = avisos.borrar_vigilancias(args[1] if len(args) > 1 else None) if len(args) > 1 else avisos.borrar_vigilancias(None)
        bot.send_message(chat, f"🗑️ Vigilancias borradas: {n}")
        return
    if len(args) >= 2:
        coin = args[0].upper()
        try:
            nivel = float(args[1].replace(',', '.'))
            precio = float(crear_instancia_exchange('swap').fetch_ticker(f"{coin}/USDT:USDT")['last'])
        except Exception:
            bot.send_message(chat, "No pude leer ese precio. Ejemplo: /vigilar ETH 3500")
            return
        ok, msg = avisos.agregar_vigilancia(coin, nivel, precio)
        if ok:
            bot.send_message(chat, f"👀 Vigilando {coin}: te aviso cuando {'suba a' if msg == 'arriba' else 'baje a'} ${_p(nivel)} (ahora ${_p(precio)}).")
        else:
            bot.send_message(chat, f"⚠️ {msg}")
        return
    lista = avisos.config()['vigilancias']
    if not lista:
        bot.send_message(chat, "👀 No vigilas ningún nivel.\nEjemplo: /vigilar ETH 3500\nBorrar: /vigilar borrar")
    else:
        bot.send_message(chat, "👀 Niveles vigilados:\n" + "\n".join(
            f"• {v['coin']} {'↑' if v['lado'] == 'arriba' else '↓'} ${_p(v['nivel'])}" for v in lista) + "\n\nBorrar: /vigilar borrar [MONEDA]")

@bot.message_handler(commands=['mercado'], func=es_dueno)
def cmd_mercado(message):
    global ULTIMO_CHAT_ID
    ULTIMO_CHAT_ID = message.chat.id
    c = avisos.config()
    lineas = [f"🧭 MERCADO AHORA (avisos {'ON' if c['activo'] else 'OFF'}, {c['sensibilidad']})", ""]
    ex = crear_instancia_exchange('swap')
    for coin in MONEDAS_TRADING:
        try:
            v15, v1h, v4h, vbtc = obtener_velas_zona(coin, ex)
            lineas.append(avisos.resumen_mercado(coin, v15[-1][4], avisos.evaluar_zona(coin, v15, v1h, v4h, vbtc)))
            mov = avisos.resumen_movimiento(coin, avisos.evaluar_movimiento(coin, v15, v1h, v4h, vbtc))
            if mov:
                lineas.append("   " + mov)
        except Exception as e:
            lineas.append(f"• {coin}: no pude leer el mercado ({e})")
    ctx = contexto_noticias()
    if ctx:
        lineas.append(f"📰 Noticia reciente que puede mover a BTC: {ctx}")
    lineas += ["", "Un 'PUNTO DE ENTRADA' llega solo con botones; esto es para mirar cuando quieras."]
    bot.send_message(message.chat.id, "\n".join(lineas))

@bot.message_handler(commands=['aciertos'], func=es_dueno)
def ver_aciertos(message):
    global ULTIMO_CHAT_ID
    ULTIMO_CHAT_ID = message.chat.id
    bot.send_message(message.chat.id, historial.resumen_texto())

@bot.callback_query_handler(func=es_dueno)
def callback_query(call):
    global ULTIMO_CHAT_ID
    ULTIMO_CHAT_ID = call.message.chat.id
    try:
        datos = call.data.split("_")
        if not datos:
            return
        accion = datos[0]

        # === PREDICCIONES 5M ===
        if accion == "pred" and len(datos) >= 2:
            coin = datos[1]
            bot.answer_callback_query(call.id, f"Analizando {coin} en 5m...")
            msg = bot.send_message(call.message.chat.id, f"🔮 **Analizando {coin} en gráfico de 5 minutos...**", parse_mode="Markdown")
            
            pred = analizar_prediccion_5m(coin)
            bot.delete_message(call.message.chat.id, msg.message_id)
            
            if pred:
                registrar_prediccion_historial(coin, pred)
                obj = prediccion.objetivos(pred['precio'], pred['atr_pct'], pred.get('res15'), pred.get('sop15'))
                operable = coin in MONEDAS_OPERABLES and pred['direccion'] in ('SUBE', 'BAJA')
                cuadro = prediccion.cuadro_veredicto(coin, pred, obj, operable)
                markup = None
                if operable:
                    tipo = 'COMPRA' if pred['direccion'] == 'SUBE' else 'VENTA'
                    senales_pendientes[(coin, tipo)] = {'tipo': tipo, 'precio': pred['precio'], 'sl_pct': SL_PORCENTAJE,
                                                        'tp_pct': round(SL_PORCENTAJE * senales.TP_MULTIPLO_R, 2), 'creada': time.time()}
                    markup = teclado_entrada(coin, tipo)
                bot.send_message(call.message.chat.id, cuadro, reply_markup=markup, parse_mode="Markdown")   # solo la respuesta; el análisis queda dentro del bot
            else:
                bot.send_message(call.message.chat.id, f"❌ No se pudo analizar {coin}.", parse_mode="Markdown")

        # === REPORTE TÉCNICO POR MONEDA / ANÁLISIS TÉCNICO ===
        elif accion in ("ver", "ana") and len(datos) >= 2:
            coin = datos[1]
            bot.answer_callback_query(call.id, f"Analizando {coin}...")
            analisis = obtener_analisis_con_reintentos(coin, 'swap')
            if analisis.get('estado') == "FALLA EN EXCHANGE":
                bot.send_message(call.message.chat.id, f"⚠️ MEXC no respondió para {coin}/USDT (error temporal del exchange). Intenta de nuevo en unos segundos.")
                return
            t4h = obtener_tendencia_4h(coin, 'swap')
            sentimiento = obtener_sentimiento_mercado()
            titulo = "🔔 REPORTE TÉCNICO 🔔" if accion == "ver" else "🔔 ANÁLISIS TÉCNICO 🔔"
            bot.send_message(call.message.chat.id, construir_reporte(titulo, coin, analisis, t4h, sentimiento), parse_mode="Markdown")

        # === CONFIRMACIÓN TRADING AUTOMÁTICO (Sí/No) ===
        elif accion == "conf" and len(datos) >= 3:
            if datos[1] == "no":
                coin = datos[2]
                bot.answer_callback_query(call.id, "Operación descartada.")
                bot.send_message(call.message.chat.id, f"❌ **Operación descartada para {coin}.** El bot sigue monitoreando.", parse_mode="Markdown")
                return
            
            coin = datos[1]
            tipo = datos[2]
            
            bot.answer_callback_query(call.id, "Selecciona el monto...")
            montos = MONTOS_PERMITIDOS
            m = InlineKeyboardMarkup(row_width=3)
            botones = []
            for monto in montos:
                botones.append(InlineKeyboardButton(
                    f"${monto:.2f}",
                    callback_data=f"pre_{coin}_{tipo}_{monto}"
                ))
            m.add(*botones)
            m.add(InlineKeyboardButton("❌ Cancelar", callback_data=f"conf_no_{coin}_{tipo}"))
            
            rep = (
                f"🎯 **AUTORIZADO:** {coin}/USDT\n"
                f"📈 **Dirección:** {'COMPRA (LONG)' if tipo == 'COMPRA' else 'VENTA (SHORT)'}\n\n"
                f"💰 **Elige el monto a operar:**\n"
                f"⚡ Apalancamiento: **{APALANCAMIENTO_AUTO}x**"
            )
            bot.send_message(call.message.chat.id, rep, reply_markup=m, parse_mode="Markdown")

        # === PEDIR CONFIRMACIÓN antes de abrir la orden (nada se ejecuta sin este paso) ===
        elif accion == "pre" and len(datos) >= 4:
            coin, tipo, monto = datos[1], datos[2], float(datos[3])
            if monto not in MONTOS_PERMITIDOS:
                bot.answer_callback_query(call.id, "Monto no permitido.")
                return
            pend = senales_pendientes.get((coin, tipo))
            vigente = bool(pend) and (time.time() - pend['creada'] <= SENAL_VIGENCIA_SEG)
            sl_txt = f"{pend['sl_pct']}% | TP techo {pend['tp_pct']}%" if vigente else f"{SL_PORCENTAJE}% (por defecto)"
            m = InlineKeyboardMarkup(row_width=2)
            m.add(InlineKeyboardButton("✅ CONFIRMAR y ejecutar", callback_data=f"mont_{coin}_{tipo}_{monto}"),
                  InlineKeyboardButton("❌ Cancelar", callback_data=f"conf_no_{coin}_{tipo}"))
            bot.answer_callback_query(call.id, "Confirma para ejecutar")
            bot.send_message(call.message.chat.id,
                             f"⚠️ CONFIRMA LA OPERACIÓN (dinero real)\n\n"
                             f"🪙 {coin}/USDT | {'COMPRA (LONG)' if tipo == 'COMPRA' else 'VENTA (SHORT)'}\n"
                             f"💰 Margen: ${monto:g} × {APALANCAMIENTO_AUTO}x = posición de ≈ ${monto * APALANCAMIENTO_AUTO:g}\n"
                             f"🛡️ SL {sl_txt} | el stop sube con el precio\n"
                             f"🔔 Al tocar el stop te CONSULTO antes de cerrar; en MEXC queda un stop de emergencia {posiciones.EXTRA_STOP_DURO_PCT:g}% más lejos.\n\n"
                             "Si no pulsas Confirmar, no se ejecuta nada.", reply_markup=m)

        # === MONTO SELECCIONADO (ejecutar con el apalancamiento automático) ===
        elif accion == "mont" and len(datos) >= 4:
            coin = datos[1]
            tipo = datos[2]
            monto = float(datos[3])

            bot.answer_callback_query(call.id, f"Ejecutando {tipo} de {coin}...")
            msg_espera = bot.send_message(call.message.chat.id, f"⏳ **Ejecutando orden {tipo} para {coin}...**\nPor favor espera.", parse_mode="Markdown")

            side = 'buy' if tipo == 'COMPRA' else 'sell'
            # SL/TP de la señal si sigue vigente; si no, los valores por defecto
            pend = senales_pendientes.get((coin, tipo))
            vigente = bool(pend) and (time.time() - pend['creada'] <= SENAL_VIGENCIA_SEG)

            exito, precio, margen_usado, lev_usado, tipo_usado, sl, tp, resultado = ejecutar_orden_con_gestion_riesgo_real(
                symbol=coin,
                mercado='swap',
                side=side,
                margen_usdt=monto,
                apalancamiento=APALANCAMIENTO_AUTO,
                tipo_orden='market',
                zona_precio=None,
                sl_pct=pend['sl_pct'] if vigente else None,
                tp_pct=pend['tp_pct'] if vigente else None,
                precio_referencia=pend['precio'] if vigente else None
            )

            bot.delete_message(call.message.chat.id, msg_espera.message_id)

            if exito:
                registrar_operacion(coin, tipo_usado, side, precio, margen_usado, lev_usado, sl, tp, resultado.get('id', 'N/A'), 'ABIERTA')
                senales_pendientes.pop((coin, tipo), None)
                bot.send_message(call.message.chat.id, texto_orden_ejecutada("¡ORDEN AUTOMÁTICA EJECUTADA!", coin, side, precio, margen_usado, lev_usado, tipo_usado, sl, tp, resultado), parse_mode="Markdown")
            else:
                bot.send_message(call.message.chat.id, f"❌ **Fallo al ejecutar:**\n\n{resultado}", parse_mode="Markdown")

        # === GESTIONAR UNA POSICIÓN EXISTENTE TRAS UN REINICIO ===
        elif accion == "adopt" and len(datos) >= 2:
            # Botones antiguos (mensajes enviados antes de esta versión): se redirigen al flujo nuevo
            if datos[1] == "no" and len(datos) >= 3:
                accion_posicion(call, ['pign', datos[2]])
            else:
                accion_posicion(call, ['padopt', datos[1], 'trailing'])

        # === POSICIONES: botones del monitoreo ===
        elif accion == "activas":
            bot.answer_callback_query(call.id, "Leyendo tus operaciones...")
            if datos[1:2] == ["ver"]:
                ver_posiciones(types_msg(call))
            else:
                n, texto = resumen_activas()
                m = None
                if n:
                    m = InlineKeyboardMarkup(row_width=1)
                    m.add(InlineKeyboardButton("🎛️ Ver con botones (cerrar, asegurar...)", callback_data="activas_ver"))
                bot.send_message(call.message.chat.id, texto, reply_markup=m)

        # === ADOPTAR MANUALES AUTOMÁTICO: ON/OFF ===
        elif accion == "autoadopt":
            nuevo = cambiar_adoptar_manuales()
            bot.answer_callback_query(call.id, f"Adoptar mis manuales: {'ON' if nuevo else 'OFF'}")
            bot.send_message(call.message.chat.id,
                             f"🤖 Adoptar mis manuales: {'ON ✅' if nuevo else 'OFF ⏸️'}\n"
                             + ("El bot adoptará solas tus posiciones manuales de ETH y ZEC con trailing (las detecta cada 60 s)." if nuevo else "El bot ya no adoptará solas tus posiciones manuales; te las seguirá ofreciendo con botones."))

        elif accion in ("pos", "padopt", "pign"):
            accion_posicion(call, datos)

        # === BACKTEST DESDE EL MENÚ ===
        elif accion == "backtest":
            bot.answer_callback_query(call.id, "Backtest en curso...")
            lanzar_backtest(call.message.chat.id, [])

        # === MENÚ FUTUROS ===
        elif call.data == "menu_futuros":
            bot.answer_callback_query(call.id, "Futuros MEXC...")
            m = InlineKeyboardMarkup(row_width=2)
            m.add(*[InlineKeyboardButton(f"⚡ {c}", callback_data=f"opc_fut_{c}") for c in MONEDAS_OPERABLES])
            bot.send_message(call.message.chat.id, "⚡ **Selecciona Activo para Futuros (MEXC):**", reply_markup=m, parse_mode="Markdown")

        # === SELECCIÓN DE MONEDA FUTUROS ===
        elif len(datos) == 3 and datos[0] == "opc":
            mercado_tipo, coin = datos[1], datos[2]
            if mercado_tipo == "fut":
                m_lev = InlineKeyboardMarkup(row_width=3)
                m_lev.add(
                    InlineKeyboardButton("1x", callback_data=f"lev_{coin}_1"),
                    InlineKeyboardButton("5x", callback_data=f"lev_{coin}_5"),
                    InlineKeyboardButton("10x", callback_data=f"lev_{coin}_10"),
                    InlineKeyboardButton("20x", callback_data=f"lev_{coin}_20")
                )
                bot.send_message(call.message.chat.id, f"⚙️ **Elige Apalancamiento para {coin} (MEXC):**", reply_markup=m_lev, parse_mode="Markdown")

        # === SELECCIÓN DE APALANCAMIENTO ===
        elif accion == "lev" and len(datos) == 3:
            coin, lev = datos[1], int(datos[2])
            bot.answer_callback_query(call.id, f"Tipo de orden para {coin}...")
            m_tipo = InlineKeyboardMarkup(row_width=2)
            m_tipo.add(
                InlineKeyboardButton("🚀 Mercado", callback_data=f"tipo_fut_{coin}_{lev}_market"),
                InlineKeyboardButton("⏳ Límite", callback_data=f"tipo_fut_{coin}_{lev}_limit")
            )
            bot.send_message(call.message.chat.id, f"⚙️ **Tipo de Orden para {coin} ({lev}x):**", reply_markup=m_tipo, parse_mode="Markdown")

        # === SELECCIÓN DE TIPO DE ORDEN ===
        elif accion == "tipo" and len(datos) == 5:
            coin, lev, tipo_o = datos[2], int(datos[3]), datos[4]
            if tipo_o == "market":
                bot.answer_callback_query(call.id, "Selecciona margen...")
                m_mar_fut = InlineKeyboardMarkup(row_width=3)
                m_mar_fut.row_width = 2
                m_mar_fut.add(*[
                    InlineKeyboardButton(f"🟢 LONG ${mt:.2f}", callback_data=f"ejec_fut_{coin}_{lev}_market_none_{mt}")
                    for mt in MONTOS_PERMITIDOS
                ])
                m_mar_fut.add(*[
                    InlineKeyboardButton(f"🔴 SHORT ${mt:.2f}", callback_data=f"ejec_fut_{coin}_{lev}_market_short_{mt}")
                    for mt in MONTOS_PERMITIDOS
                ])
                bot.send_message(call.message.chat.id, f"💵 **Margen para Mercado {coin} ({lev}x):**", reply_markup=m_mar_fut, parse_mode="Markdown")
            else:
                bot.answer_callback_query(call.id, "Selecciona zona...")
                m_zona = InlineKeyboardMarkup(row_width=2)
                m_zona.add(
                    InlineKeyboardButton("🟢 Comprar en Soporte", callback_data=f"ejec_fut_{coin}_{lev}_limit_soporte_{MONTOS_PERMITIDOS[0]}"),
                    InlineKeyboardButton("🔴 Vender en Resistencia", callback_data=f"ejec_fut_{coin}_{lev}_limit_resistencia_{MONTOS_PERMITIDOS[0]}")
                )
                bot.send_message(call.message.chat.id, f"🎯 **Zona para orden Límite de {coin} ({lev}x):**", reply_markup=m_zona, parse_mode="Markdown")

        # === EJECUCIÓN MANUAL ===
        elif accion == "ejec" and len(datos) >= 7:
            mercado_tipo = datos[1]
            coin = datos[2]
            lev = int(datos[3]) if datos[3] != 'none' else 1
            tipo_orden = datos[4]
            zona = datos[5]
            margen = float(datos[6])
            side_manual = 'buy' if zona in ['none', 'soporte'] else 'sell'

            if datos[7:8] != ['ok']:      # paso de CONFIRMACIÓN: sin pulsar Confirmar no se ejecuta nada
                m_ok = InlineKeyboardMarkup(row_width=2)
                m_ok.add(InlineKeyboardButton("✅ CONFIRMAR y ejecutar", callback_data=call.data + "_ok"),
                         InlineKeyboardButton("❌ Cancelar", callback_data=f"conf_no_{coin}_{'COMPRA' if side_manual == 'buy' else 'VENTA'}"))
                bot.answer_callback_query(call.id, "Confirma para ejecutar")
                bot.send_message(call.message.chat.id,
                                 f"⚠️ CONFIRMA LA OPERACIÓN (dinero real)\n\n🪙 {coin} | {'COMPRA (LONG)' if side_manual == 'buy' else 'VENTA (SHORT)'}\n"
                                 f"📋 Orden: {tipo_orden.upper()} | {lev}x | margen ${margen:g}\n\n"
                                 "Si no pulsas Confirmar, no se ejecuta nada.", reply_markup=m_ok)
                return

            msg_espera = bot.send_message(call.message.chat.id, f"⏳ **Ejecutando orden {tipo_orden.upper()} para {coin}...**", parse_mode="Markdown")
            mercado_ccxt = 'swap' if mercado_tipo == 'fut' else 'spot'

            exito, precio, margen_usado, lev_usado, tipo_usado, sl, tp, resultado = ejecutar_orden_con_gestion_riesgo_real(
                symbol=coin,
                mercado=mercado_ccxt,
                side=side_manual,
                margen_usdt=margen,
                apalancamiento=lev,
                tipo_orden=tipo_orden,
                zona_precio=zona if zona in ('soporte', 'resistencia') else None
            )

            bot.delete_message(call.message.chat.id, msg_espera.message_id)

            if exito:
                registrar_operacion(coin, tipo_usado, side_manual, precio, margen_usado, lev_usado, sl, tp, resultado.get('id', 'N/A'), 'ABIERTA')
                bot.send_message(call.message.chat.id, texto_orden_ejecutada("¡ORDEN EJECUTADA CON ÉXITO!", coin, side_manual, precio, margen_usado, lev_usado, tipo_usado, sl, tp, resultado), parse_mode="Markdown")
            else:
                bot.send_message(call.message.chat.id, f"❌ **Fallo al ejecutar:**\n\n{resultado}", parse_mode="Markdown")

        else:
            bot.answer_callback_query(call.id, "Opción no reconocida.")
            
    except Exception as e:
        print(f"Error en callback: {e}")
        bot.send_message(call.message.chat.id, f"⚠️ **Error interno:** {str(e)}")

intrusos_avisados = set()

def registrar_intento_no_autorizado(obj):
    """Ignora en silencio a cualquiera que no sea el dueño, lo deja en el log y te avisa una vez."""
    try:
        user = getattr(obj, "from_user", None)
        uid = getattr(user, "id", None)
        uname = getattr(user, "username", None)
        contenido = (getattr(obj, "text", None) or getattr(obj, "data", None) or "<sin texto>")
        print(f"[BLOQUEADO] Intento no autorizado de id={uid} usuario={uname}: {str(contenido)[:60]!r}")
        if uid is not None and uid not in intrusos_avisados:
            intrusos_avisados.add(uid)
            bot.send_message(DUENO_ID, f"🚨 Alguien intentó usar tu bot y fue bloqueado.\nID: {uid}\nUsuario: @{uname}")
    except Exception as e:
        print(f"Error registrando intento no autorizado: {e}")

@bot.message_handler(func=lambda m: True, content_types=['text', 'photo', 'document', 'sticker', 'voice', 'video', 'audio', 'location', 'contact'])
def bloquear_mensajes_no_autorizados(message):
    if es_dueno(message):
        return
    registrar_intento_no_autorizado(message)

@bot.callback_query_handler(func=lambda c: True)
def bloquear_botones_no_autorizados(call):
    try:
        bot.answer_callback_query(call.id)
    except Exception:
        pass
    registrar_intento_no_autorizado(call)

def iniciar_hilos():
    hilo_keep_alive = threading.Thread(target=bucle_keep_alive, daemon=True)
    hilo_keep_alive.start()
    hilo_reportes = threading.Thread(target=bucle_reportes_automaticos, daemon=True)
    hilo_reportes.start()
    hilo_gestion = threading.Thread(target=bucle_gestion_posiciones, daemon=True)
    hilo_gestion.start()
    hilo_trading = threading.Thread(target=bucle_trading_automatico, daemon=True)
    hilo_trading.start()
    hilo_historial = threading.Thread(target=bucle_historial, daemon=True)
    hilo_historial.start()
    threading.Thread(target=bucle_avisos_dinamicos, daemon=True).start()

if __name__ == "__main__":
    print("Iniciando Bot...")
    inicializar_mercados()
    avisos.cargar()
    enviar_aviso_inicio()
    iniciar_hilos()
    hilo_bot = threading.Thread(target=lambda: bot.infinity_polling(), daemon=True)
    hilo_bot.start()
    puerto = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=puerto)      