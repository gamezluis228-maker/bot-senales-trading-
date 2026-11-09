import json
import os
import re
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
import prediccion
import historial
import avisos
import backtest

# =============================================================================
# RAMA BINANCE — SOLO ANÁLISIS (no opera)
# ---------------------------------------------------------------------------
# Este bot NO abre ni cierra posiciones reales: no tiene claves de exchange,
# no hay botones Operar, no hay auto-adopción ni gestión de posiciones.
# Lee precios y velas PÚBLICAS de Binance (futuros USDT-M) y manda análisis,
# reportes y alertas de entrada y salida para que Luis opere a mano en
# Quantfury (que usa el precio real de Binance).
# Petróleo (Brent BZ / WTI CL): el código sigue presente pero DESACTIVADO
# (OIL_ENABLED = False) porque Binance no lista Brent ni WTI; falta decidir
# la fuente de petróleo. No borrar el código de petróleo.
# =============================================================================

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

# Solo análisis: no hay parámetros de operación (sin apalancamiento, sin márgenes,
# sin límite de pérdida diaria, sin monto mínimo: el bot no abre posiciones).
# Los niveles SL/TP que ves en las señales son de REFERENCIA para operar a mano.

INTERVALO_AVISOS_SEG = 120         # el bot busca oportunidades y niveles vigilados cada 2 min
lider_btc = {'tipo': None, 'ts': 0.0}   # última señal de BTC (el líder): COMPRA / VENTA

avisos_hoy = {'fecha': '', 'n': 0}  # contador diario de avisos de entrada (anti-ruido)
ultima_zona = {}                  # (moneda, tipo) -> hora del último aviso de zona
senales_enviadas = {}             # (moneda, subtipo) -> vela ya notificada (evita repetidas)
ultima_direccion_alertada = {}    # moneda -> última dirección alertada (COMPRA/VENTA), para el aviso SALIR cuando gira

# Petróleo (Brent BZ / WTI CL): el código sigue presente pero DESACTIVADO por
# defecto: Binance NO lista Brent ni WTI, así que no hay de dónde leerlos.
# Si Luis decide una fuente de petróleo, se pone OIL_ENABLED = True y se
# conecta esa fuente; mientras tanto BZ y CL no se vigilan ni se reportan.
# NO borrar el código de petróleo (señales, noticias, etiquetas).
OIL_ENABLED = False
MONEDAS_TRADING = ["BTC", "ETH", "ZEC", "PAXG"] + (["BZ", "CL"] if OIL_ENABLED else [])  # Señales y alertas (PAXG = oro tokenizado; BZ = Brent, CL = WTI solo si OIL_ENABLED)
MONEDAS_OPERABLES = []   # NADA es operable: el bot es solo análisis (BTC nunca se operó; ahora nada se opera)
SIN_FILTRO_BTC = ["PAXG", "BZ", "CL"]  # Oro, Brent y WTI: SIN filtro BTC y SIN avisos de "BTC manda" (muchas veces se mueven al revés de BTC)

# --- Red pública de noticias: el bot lee noticias y avisa, NUNCA pausa señales ---
# Fuentes RSS públicas, sin claves. Cripto: CoinDesk y CoinTelegraph.
# Petróleo: OilPrice (energía). Cada fuente lleva su nombre para citarla en el aviso.
# Si una noticia importante y reciente puede mover a BTC o al petróleo,
# se añade una advertencia a las señales y se manda un aviso. Las señales siempre se mandan.
FUENTES_NOTICIAS = [
    ("CoinDesk", "https://www.coindesk.com/arc/outboundfeeds/rss/"),
    ("CoinTelegraph", "https://cointelegraph.com/rss"),
]
FUENTES_NOTICIAS_PETROLEO = [
    ("OilPrice", "https://oilprice.com/rss/main"),
]
PALABRAS_NOTICIA = ["fed", "fomc", "powell", "cpi", "ppi", "inflation", "interest rate",
                    "rate hike", "rate cut", "sec", "etf", "tariff", "hack", "bankrupt",
                    "liquidation", "payroll", "gdp", "recession"]
# Solo palabras FUERTES para petróleo: "oil" solo no avisa (demasiado ruido).
PALABRAS_NOTICIA_PETROLEO = ["opec", "opep", "hormuz", "iran", "irán", "strike", "attack",
                            "ataque", "sanction", "sancion", "sanción", "production cut",
                            "recorte", "inventories", "inventarios", "eia", "brent",
                            "crude", "crudo", "saudi", "refinery", "refinería",
                            "guerra", "embargo", "output cut"]
VENTANA_NOTICIA_MIN = 120
# BTC SIN tope: Luis necesita estar atento a todo lo que mueva a BTC.
# Petróleo SÍ tiene tope (OilPrice publica mucho ruido): 5 avisos/día.
MAX_AVISOS_NOTICIAS_PETROLEO_DIA = 5
_cache_noticias = {"ts": 0.0, "titulares": []}
_vistas_noticias = None
_contador_noticias = {"dia": None, "n": 0}

def _leer_noticias():
    """Titulares recientes (<= VENTANA_NOTICIA_MIN) que pueden mover a BTC o al petróleo.
    Devuelve lista de (titulo, activo, fuente). Cache 10 min.
    Si las fuentes fallan, devuelve lo último en cache (o vacío): nunca rompe las señales."""
    ahora = time.time()
    if ahora - _cache_noticias["ts"] < 600:
        return _cache_noticias["titulares"]
    titulares = []
    fuentes = ([(f, u, PALABRAS_NOTICIA, "BTC") for f, u in FUENTES_NOTICIAS] +
               [(f, u, PALABRAS_NOTICIA_PETROLEO, "PETRÓLEO") for f, u in FUENTES_NOTICIAS_PETROLEO])
    for fuente, url, palabras, activo in fuentes:
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
                    if any(p in bajo for p in palabras):
                        titulares.append((titulo, activo, fuente))
        except Exception as e:
            print(f"No pude leer noticias de {url}: {e}")
    _unicos = []
    _vistos = set()
    for _t in titulares:
        if _t[0] not in _vistos:
            _vistos.add(_t[0])
            _unicos.append(_t)
    titulares = _unicos
    _cache_noticias["ts"] = ahora
    _cache_noticias["titulares"] = titulares
    return titulares

def contexto_noticias(preferido=None):
    """Primer titular importante reciente, o None.
    Si se pide un activo (p. ej. "PETRÓLEO"), prefiere ese; si no hay, usa el primero."""
    t = _leer_noticias()
    if preferido:
        for titulo, activo, _fuente in t:
            if activo == preferido:
                return titulo
    return t[0][0] if t else None

def avisar_noticias_nuevas():
    """Avisa una sola vez por titular nuevo importante.
    BTC SIN tope (Luis necesita estar atento). Petróleo con tope 5/día;
    lo que pasa del tope queda en /mercado. La primera lectura solo marca, no avisa."""
    global _vistas_noticias
    actuales = _leer_noticias()
    titulos_actuales = {t[0] for t in actuales}
    if _vistas_noticias is None:
        _vistas_noticias = titulos_actuales
        return
    nuevas = [t for t in actuales if t[0] not in _vistas_noticias]
    _vistas_noticias = titulos_actuales
    # Un mismo titular en dos fuentes (p. ej. CoinDesk y CoinTelegraph) avisa una sola vez
    _titulos_vistos = set()
    _unicas = []
    for _t in nuevas:
        if _t[0] not in _titulos_vistos:
            _titulos_vistos.add(_t[0])
            _unicas.append(_t)
    nuevas = _unicas
    if len(_vistas_noticias) > 100:
        _vistas_noticias = set(list(_vistas_noticias)[-50:])
    hoy = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if _contador_noticias["dia"] != hoy:
        _contador_noticias["dia"] = hoy
        _contador_noticias["n"] = 0
    for titulo, activo, fuente in nuevas:
        if activo == "PETRÓLEO":
            if _contador_noticias["n"] >= MAX_AVISOS_NOTICIAS_PETROLEO_DIA:
                continue
            _contador_noticias["n"] += 1
        etiqueta = "el PETRÓLEO (Brent y WTI)" if activo == "PETRÓLEO" else "BTC"
        avisar(f"📰 Noticia importante para {etiqueta}:\n{titulo}\nFuente: {fuente}\nEl bot sigue mandando señales; opera con cuidado.")

MONEDAS_REPORTE = list(MONEDAS_TRADING)
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

_hilo_local = threading.local()   # instancias ccxt por hilo (ccxt no es thread-safe)

# --- Protección anti-baneo de Binance (IP compartida de Render) ---------------
# Binance devuelve 418 / código -1003 "Way too many requests" y banea la IP
# saliente (compartida por muchos servicios de Render) hasta la hora que indica
# el propio mensaje ("banned until <milisegundos>"). Cada petición nueva
# durante el baneo LO ALARGA, así que cuando aparece un baneo el bot deja de
# tocar Binance hasta que pase la hora indicada y no reintenta. Sin esto, los
# reintentos de cada ciclo de 15 min + cada /menu alargaban el baneo sin fin
# (pasó la noche del 2026-11-08: baneo hasta la 01:24 de Caracas).
_BANEO_BINANCE_HASTA = 0.0      # epoch en segundos; 0 = sin baneo conocido
_MARGEN_BANEO_SEG = 60          # colchón extra al terminar el baneo
_ULTIMO_AVISO_BANEO_TS = 0.0    # último aviso de baneo mandado a Telegram

def _es_error_baneo(texto_o_error):
    """True si el texto/error es un baneo de Binance por exceso de peticiones."""
    texto = str(texto_o_error)
    return ("-1003" in texto) or ("banned until" in texto) or ("418" in texto and "binance" in texto.lower())

def _registrar_baneo_binance(texto_o_error):
    """Si el error es un baneo de Binance, guarda hasta cuándo no hay que tocar
    Binance. Devuelve True si era un baneo."""
    global _BANEO_BINANCE_HASTA
    texto = str(texto_o_error)
    if not _es_error_baneo(texto_o_error):
        return False
    m = re.search(r"banned until (\d+)", texto)
    if m:
        hasta = int(m.group(1)) / 1000.0 + _MARGEN_BANEO_SEG
    else:
        hasta = time.time() + 600  # sin hora en el mensaje: 10 min por defecto
    if hasta > _BANEO_BINANCE_HASTA:
        _BANEO_BINANCE_HASTA = hasta
    print(f"Binance baneó la IP hasta {time.strftime('%H:%M:%S', time.localtime(_BANEO_BINANCE_HASTA))}; no se tocará Binance hasta entonces.")
    return True

def _binance_bloqueado():
    """True mientras dure un baneo de Binance registrado."""
    return time.time() < _BANEO_BINANCE_HASTA

def _proteger_instancia(exchange):
    """Envuelve fetch_ohlcv y load_markets de una instancia ccxt para que:
    - si Binance tiene la IP baneada, falle rápido SIN tocar la red;
    - si una llamada devuelve un baneo, registre hasta cuándo no insistir.
    Cubre todos los hilos y todas las llamadas (reportes, señales, /menu)."""
    orig_fetch = exchange.fetch_ohlcv
    orig_load = exchange.load_markets

    def fetch_ohlcv_protegido(*args, **kwargs):
        if _binance_bloqueado():
            raise Exception(f"Binance bloqueado por baneo hasta {time.strftime('%H:%M:%S', time.localtime(_BANEO_BINANCE_HASTA))} (sin tocar la red)")
        try:
            return orig_fetch(*args, **kwargs)
        except Exception as e:
            _registrar_baneo_binance(e)
            raise

    def load_markets_protegido(*args, **kwargs):
        if _binance_bloqueado():
            raise Exception(f"Binance bloqueado por baneo hasta {time.strftime('%H:%M:%S', time.localtime(_BANEO_BINANCE_HASTA))} (sin tocar la red)")
        try:
            return orig_load(*args, **kwargs)
        except Exception as e:
            _registrar_baneo_binance(e)
            raise

    exchange.fetch_ohlcv = fetch_ohlcv_protegido
    exchange.load_markets = load_markets_protegido
    return exchange

# SIN CLAVES: el bot es solo análisis y lee precios/velas PÚBLICAS de Binance.
# No hay obtener_credenciales_* en esta rama: en Render solo hace falta TEL_TOKEN.
# (Las funciones de MEXC/Bybit se eliminaron; si algún día vuelve a operar,
#  habrá que reintroducirlas, nunca pegar claves en el chat.)
def crear_instancia_exchange(mercado='swap'):
    """Una instancia ccxt-binance por hilo (evita recargar los mercados en cada llamada).
    SOLO PÚBLICA: sin apiKey ni secret (el bot es solo análisis y no opera).
    'swap' = futuros USDT-M lineales de Binance (símbolos BTC/USDT:USDT, etc.).
    El argumento 'mercado' se conserva por compatibilidad."""
    cache = getattr(_hilo_local, "instancias", None)
    if cache is None:
        cache = _hilo_local.instancias = {}
    if mercado not in cache:
        config = {
            'enableRateLimit': True,
            'options': {'defaultType': 'future'}
        }
        cache[mercado] = _proteger_instancia(ccxt.binance(config))
    return cache[mercado]

exchange_default = crear_instancia_exchange('swap')

def inicializar_mercados():
    try:
        exchange_default.load_markets()
        print("¡Mercados de Binance cargados correctamente!")
    except Exception as e:
        print(f"Error al cargar mercados: {e}")

def home():
    return "Bot Activo - Binance Solo Análisis"

def bucle_keep_alive():
    # Solo mantiene despierto al bot: pega a la URL PUBLICA de Render cada 5 min.
    # Un ping a localhost NO cuenta como trafico para Render, por eso ya no se usa.
    # No toca senales, botones, estrategia ni ningun otro hilo.
    url = os.getenv("KEEPALIVE_URL") or RENDER_APP_URL
    if url:
        print(f"Keep-alive: ping a {url} cada 300s")
    else:
        print("Keep-alive: SIN URL publica (falta RENDER_EXTERNAL_URL); el bot puede dormirse")
    time.sleep(15)
    while True:
        try:
            if url:
                requests.get(url, timeout=10)
        except Exception as e:
            print(f"Error en Keep-Alive: {e}")
        time.sleep(300)

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

def obtener_analisis_binance(symbol, mercado='swap'):
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
    """Binance a veces responde 5xx o límite de tasa. Reintenta antes de rendirse.
    Si es un baneo (-1003/418) NO reintenta: cada intento alarga el baneo."""
    a = None
    for _ in range(intentos):
        a = obtener_analisis_binance(symbol, mercado)
        if a.get('estado') != "FALLA EN EXCHANGE":
            return a
        if _es_error_baneo(a.get('pausa', '')):
            return a
        time.sleep(espera)
    return a

def construir_reporte(titulo, coin, a, t4h, sentimiento):
    """Mismo formato de siempre, con las EMAs agregadas debajo de las tendencias."""
    return (
        f"{titulo}\n"
        f"⚡ Activo Binance: {coin}/USDT\n\n"
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
    global _ULTIMO_AVISO_BANEO_TS
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
                            print(f"Binance no respondió para {coin}: {a.get('pausa')}")
                            if ULTIMO_CHAT_ID:
                                if _es_error_baneo(a.get('pausa', '')):
                                    # Baneo: un solo aviso por episodio (cada 30 min),
                                    # no un aviso por moneda y por ciclo.
                                    if now_ts - _ULTIMO_AVISO_BANEO_TS > 1800:
                                        _ULTIMO_AVISO_BANEO_TS = now_ts
                                        bot.send_message(ULTIMO_CHAT_ID, f"⚠️ Binance bloqueó la IP por exceso de peticiones hasta las {time.strftime('%H:%M', time.localtime(_BANEO_BINANCE_HASTA))}. No insisto hasta entonces; los reportes vuelven solos.")
                                else:
                                    bot.send_message(ULTIMO_CHAT_ID, f"⚠️ Binance no respondió para {coin}/USDT (error temporal del exchange). Reintento en el próximo ciclo de 15 min.")
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

def avisar_salir_si_giro(coin, s, timeframe="15m"):
    """SALIR (solo análisis): si la señal nueva va en contra de la última dirección
    alertada para esa moneda, avisa que el setup anterior giró. No hay posiciones
    que cerrar: Luis opera a mano en Quantfury y decide él."""
    anterior = ultima_direccion_alertada.get(coin)
    nueva = s["tipo"]  # COMPRA / VENTA
    if anterior and anterior != nueva and avisos.pasa_filtro(s["veredicto"], avisos.config()["sensibilidad"]):
        texto = (f"🚨🚨 SALIR {coin} (solo análisis) 🚨🚨\n\n"
                 f"El setup giró: llegó señal contraria {s['veredicto']} ({s['titulo']}).\n"
                 f"Si operas {coin} a mano en Quantfury en la dirección anterior, este es el momento de revisar la salida.\n"
                 f"El bot no abre ni cierra nada: decide tú.\n\n"
                 + avisos.texto_alerta(coin, s))
        enviar_senal_con_grafico(DUENO_ID, coin, s, texto, None, timeframe=timeframe,
                                 caption_corta=f"📊 SALIR {coin} — el setup giró: nueva señal {s['tipo']}")
    ultima_direccion_alertada[coin] = nueva

def bucle_trading_automatico():
    """Bucle de SEÑALES (solo análisis): cada 15 min evalúa rompimientos y manda
    la alerta con su dibujo. No abre órdenes ni gestiona posiciones: el bot es
    solo lectura y Luis opera a mano en Quantfury."""
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
                            registrar_senal_historial(coin, senal)      # todas se registran (para /aciertos)
                            cfg = avisos.config()
                            if not cfg['activo'] or not avisos.pasa_filtro(senal['veredicto'], cfg['sensibilidad']) or not _cupo_avisos():
                                continue
                            markup = teclado_entrada(coin, senal['tipo'])
                            lider = None if coin in SIN_FILTRO_BTC else (lider_btc['tipo'] if time.time() - lider_btc['ts'] < 10800 else None)
                            texto = "🚨 SEÑAL 1H (solo análisis) 🚨\n\n" + avisos.texto_alerta(coin, senal, lider)
                            ctx = contexto_noticias("PETRÓLEO" if coin in ("BZ", "CL") else None)
                            if ctx:
                                texto += f"\n\n📰 Noticia que puede mover {'al mercado' if coin in SIN_FILTRO_BTC else 'a BTC'}: {ctx}"
                            texto += "\n\n🔒 Solo análisis: el bot no opera; si entras, lo haces tú a mano en Quantfury."
                            if ULTIMO_CHAT_ID:
                                enviar_senal_con_grafico(ULTIMO_CHAT_ID, coin, senal, texto, markup, timeframe="1h")
                            avisar_salir_si_giro(coin, senal, "1h")
                            avisos_hoy['n'] += 1
                            if coin == 'BTC':
                                lider_btc.update(tipo=senal['tipo'], ts=time.time())
                time.sleep(60)
        except Exception as e:
            print(f"Error en bucle de señales: {e}")
        time.sleep(15)

def teclado_entrada(coin, tipo):
    """Botones de una señal: solo ver el análisis o ignorarla. NO hay botones
    Operar: el bot es solo análisis y nunca abre órdenes."""
    m = InlineKeyboardMarkup(row_width=2)
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

def revisar_zonas(ex):
    """Busca oportunidades en las monedas vigiladas: (1) punto de entrada por
    retroceso a la EMA 21 y (2) movimiento fuerte en curso. Solo avisa (análisis):
    nunca abre ni cierra nada."""
    cfg = avisos.config()
    if not cfg['activo']:
        return
    for coin in MONEDAS_TRADING:
        try:
            v15, v1h, v4h, vbtc = obtener_velas_zona(coin, ex)
            candidatas = avisos.evaluar_zona(coin, v15, v1h, v4h, vbtc) + avisos.evaluar_movimiento(coin, v15, v1h, v4h, vbtc) + avisos.rupturas_15m(coin, v15, v1h, vbtc)
            for s in candidatas:
                clave = (coin, s['tipo'], s['subtipo'])
                ahora = time.time()
                if not avisos.pasa_filtro(s['veredicto'], 'normal') or not avisos.puede_repetir(ultima_zona.get(clave), ahora):
                    continue
                ultima_zona[clave] = ahora
                registrar_senal_historial(coin, s)
                if not avisos.pasa_filtro(s['veredicto'], cfg['sensibilidad']) or not _cupo_avisos():
                    continue
                texto = avisos.encabezado(s) + " (solo análisis)\n\n"
                lider = None if coin in SIN_FILTRO_BTC else (lider_btc['tipo'] if time.time() - lider_btc['ts'] < 10800 else None)
                texto += avisos.texto_alerta(coin, s, lider)
                ctx = contexto_noticias("PETRÓLEO" if coin in ("BZ", "CL") else None)
                if ctx:
                    texto += f"\n\n📰 Noticia que puede mover {'al mercado' if coin in SIN_FILTRO_BTC else 'a BTC'}: {ctx}"
                texto += "\n\n🔒 Solo análisis: el bot no opera; si entras, lo haces tú a mano en Quantfury."
                enviar_senal_con_grafico(DUENO_ID, coin, s, texto, teclado_entrada(coin, s['tipo']), timeframe="15m")
                avisar_salir_si_giro(coin, s, "15m")
                avisos_hoy['n'] += 1
                if coin == 'BTC' and avisos.pasa_filtro(s['veredicto'], cfg['sensibilidad']):
                    lider_btc.update(tipo=s['tipo'], ts=time.time())
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
def avisar(texto):
    try:
        if ULTIMO_CHAT_ID:
            bot.send_message(ULTIMO_CHAT_ID, texto)
    except Exception as e:
        print(f"No pude enviar aviso a Telegram: {e}")

def enviar_dueno(texto, markup=None):
    try:
        bot.send_message(DUENO_ID, texto, reply_markup=markup)
    except Exception as e:
        print(f"No pude enviar el mensaje a Telegram: {e}")

def enviar_senal_con_grafico(chat_id, coin, senal, texto, markup=None, timeframe="15m",
                             stop=None, meta=None, caption_corta=None):
    """Señal de entrada o de salida con el dibujo de la operación en vivo: velas
    cerradas + la vela en formación de Binance de esa moneda, EMAs, entrada/stop/meta,
    soporte/resistencia. Solo añade la foto: el texto, los botones y la estrategia
    quedan exactamente igual. Si el dibujo o la foto fallan, manda solo el texto:
    la señal nunca se pierde por el dibujo."""
    try:
        import io
        import grafico
        ex = crear_instancia_exchange('swap')
        ahora = int(time.time() * 1000)
        tf_ms = {"15m": 900000, "1h": 3600000}.get(timeframe, 900000)
        crudo = ex.fetch_ohlcv(f"{coin}/USDT:USDT", timeframe=timeframe,
                               since=ahora - 250 * tf_ms, limit=250)
        velas = senales.solo_cerradas(crudo, tf_ms, ahora)
        viva = crudo[-1] if crudo and velas and crudo[-1][0] != velas[-1][0] else None
        png = grafico.dibujar_operacion(coin, velas, senal, vela_viva=viva, stop=stop, meta=meta)
        foto = io.BytesIO(png)
        foto.name = f"{coin}_operacion.png"
        if len(texto) <= 1024:
            bot.send_photo(chat_id, foto, caption=texto, reply_markup=markup)
        else:
            if caption_corta is None:
                fmt = lambda x: f"{x:,.2f}" if abs(x) >= 1 else f"{x:.6f}"
                p = float(senal["precio"])
                largo = senal["direccion"] == "LONG"
                sl = p * (1 - senal["sl_pct"] / 100) if largo else p * (1 + senal["sl_pct"] / 100)
                tp = p * (1 + senal["tp_pct"] / 100) if largo else p * (1 - senal["tp_pct"] / 100)
                caption_corta = (f"📊 {coin} {senal['tipo']} — Entrada ${fmt(p)} · "
                                 f"Stop ${fmt(sl)} · Meta ${fmt(tp)}")
            bot.send_photo(chat_id, foto, caption=caption_corta)
            bot.send_message(chat_id, texto, reply_markup=markup)
        return
    except Exception as e:
        print(f"No pude enviar la señal de {coin} con dibujo: {e}")
    try:
        bot.send_message(chat_id, texto, reply_markup=markup)
    except Exception as e:
        print(f"No pude enviar la señal de {coin} ni como texto: {e}")

def texto_seguimiento():
    """Lista de seguimiento (solo análisis): precio actual de cada moneda vigilada.
    El bot no tiene posiciones: no hay nada que gestionar ni cerrar."""
    ex = crear_instancia_exchange('swap')
    lineas = ["👀 LISTA DE SEGUIMIENTO — solo análisis (el bot no opera)", ""]
    for coin in MONEDAS_TRADING:
        try:
            precio = float(ex.fetch_ticker(f"{coin}/USDT:USDT")['last'])
            lineas.append(f"• {coin}/USDT: ${_p(precio)}")
        except Exception as e:
            lineas.append(f"• {coin}: no pude leer el precio ({e})")
    lineas += ["", "Sin posiciones: el bot no abre ni gestiona nada. Operas tú a mano en Quantfury."]
    return "\n".join(lineas)

def cmd_activas(message):
    global ULTIMO_CHAT_ID
    ULTIMO_CHAT_ID = message.chat.id
    bot.send_message(message.chat.id, texto_seguimiento())

def ver_posiciones(message):
    global ULTIMO_CHAT_ID
    ULTIMO_CHAT_ID = message.chat.id
    bot.send_message(message.chat.id, texto_seguimiento() + "\n\n📌 /posiciones muestra lo mismo que /activas: la lista de seguimiento.\nEl bot no gestiona posiciones; las tuyas están en Quantfury.")

def ver_saldo(message):
    global ULTIMO_CHAT_ID
    ULTIMO_CHAT_ID = message.chat.id
    bot.send_message(message.chat.id,
                     "💰 SALDO — bot solo análisis\n\n"
                     "Este bot no tiene cuenta de exchange conectada: no hay claves, no hay saldo que leer.\n"
                     "Tu dinero está en Quantfury y lo ves en su app.\n\n"
                     f"El bot solo te manda análisis, reportes y alertas de {', '.join(MONEDAS_TRADING)}.")

def enviar_aviso_inicio():
    avisar(f"🟢 Bot iniciado (Binance, solo análisis).\n• Señales y reportes: {', '.join(MONEDAS_REPORTE)}\n• El bot NO opera: sin claves, sin órdenes, sin posiciones.\n• Operas tú a mano en Quantfury con el precio real de Binance.")

def mostrar_menu_principal(message):
    global ULTIMO_CHAT_ID
    ULTIMO_CHAT_ID = message.chat.id
    markup = InlineKeyboardMarkup(row_width=2)
    botones_ver = [
        InlineKeyboardButton("⚡ BTC", callback_data="ver_BTC"),
        InlineKeyboardButton("💎 ETH", callback_data="ver_ETH"),
        InlineKeyboardButton("🟣 SOL", callback_data="ver_SOL"),
        InlineKeyboardButton("🟠 DOGE", callback_data="ver_DOGE"),
        InlineKeyboardButton("🟡 ZEC", callback_data="ver_ZEC"),
        InlineKeyboardButton("🐸 PEPE", callback_data="ver_PEPE"),
    ]
    if OIL_ENABLED:
        botones_ver += [
            InlineKeyboardButton("🛢️ Brent", callback_data="ver_BZ"),
            InlineKeyboardButton("🛢️ WTI", callback_data="ver_CL"),
        ]
    markup.add(*botones_ver)
    markup.add(InlineKeyboardButton("👀 Lista de seguimiento", callback_data="activas_x"))
    markup.add(InlineKeyboardButton("📊 Backtest 30 días", callback_data="backtest_go"))
    cfg = avisos.config()
    linea = ("👀 Vigilando (solo análisis): " + ", ".join(MONEDAS_TRADING)
             + ("\n🛢️ Petróleo (Brent/WTI): desactivado — pendiente decidir la fuente." if not OIL_ENABLED else "\n🛢️ Petróleo: activado."))
    linea += chr(10) + f"🎚️ Sensibilidad: {cfg['sensibilidad'].upper()} " + ("(solo señales VERDADERAS)" if cfg['sensibilidad'] == 'estricta' else "(también señales PROBABLES)") + chr(10) + f"🔔 Avisos de entrada: {'ON' if cfg['activo'] else 'OFF'}"
    bot.send_message(message.chat.id, "📈 **PANEL DE SEÑALES - Binance (solo análisis)** 🟢\n\n" + linea + "\n\nComandos:\n• /menu - Panel\n• /analisis - Análisis técnico\n• /predicciones - Predicciones 5 min\n• /activas - Lista de seguimiento (precios)\n• /posiciones - Lista de seguimiento\n• /operar - El bot ya no opera (solo análisis)\n• /estado - Estado del bot\n• /saldo - Nota: sin cuenta conectada\n• /mercado - Qué ve el bot ahora (puntos de entrada)\n• /senales on|off - Avisos de entrada\n• /sensibilidad - Estricta o normal\n• /vigilar ETH 3500 - Aviso al llegar a un precio\n• /aciertos - Historial de aciertos\n• /backtest - Probar la estrategia con datos pasados", reply_markup=markup, parse_mode="Markdown")

def menu_operar(message):
    global ULTIMO_CHAT_ID
    ULTIMO_CHAT_ID = message.chat.id
    bot.send_message(message.chat.id,
                     "🔒 **Bot solo análisis**\n\n"
                     "Este bot ya no opera: no abre ni cierra posiciones.\n"
                     "Te manda análisis, reportes y alertas de entrada y salida para que operes tú a mano en Quantfury.\n\n"
                     "Mira /analisis o /mercado.", parse_mode="Markdown")

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
    )
    if OIL_ENABLED:
        markup.add(
            InlineKeyboardButton("🛢️ BZ (Brent)", callback_data="ana_BZ"),
            InlineKeyboardButton("🛢️ CL (WTI)", callback_data="ana_CL"),
        )
    bot.send_message(message.chat.id, "📊 **Análisis técnico** (solo análisis)\n\nElige la moneda:", reply_markup=markup, parse_mode="Markdown")

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
            if au in MONEDAS_TRADING:
                monedas.append(au)
            elif au in ("15M", "1H"):
                tf = au.lower()
            elif au.isdigit():
                dias = max(7, min(365, int(au)))
        if not monedas:
            monedas = list(MONEDAS_TRADING)
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

def estado_posiciones(message):
    global ULTIMO_CHAT_ID
    ULTIMO_CHAT_ID = message.chat.id
    c = avisos.config()
    lineas = ["📊 ESTADO DEL BOT (Binance, solo análisis)",
              f"Avisos de entrada: {'ON' if c['activo'] else 'OFF'}",
              f"Sensibilidad: {c['sensibilidad'].upper()}",
              f"Avisos enviados hoy: {avisos_hoy['n']}/{avisos.MAX_AVISOS_DIA}",
              f"Monedas vigiladas: {', '.join(MONEDAS_TRADING)}",
              "Petróleo (Brent/WTI): desactivado — pendiente decidir la fuente." if not OIL_ENABLED else "Petróleo (Brent/WTI): activado.",
              "",
              "Sin posiciones: el bot no opera."]
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
    """Evalúa con datos reales de Binance las predicciones (a 5 min) y las señales (SL o TP primero)."""
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
        lineas.append(f"📰 Noticia reciente que puede mover al mercado: {ctx}")
    lineas += ["", "Solo lectura: las señales de entrada llegan solas cuando se dan."]
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

        # Botones viejos de operar (mensajes de antes de esta versión): el bot ya no opera.
        if accion in ("pre", "mont", "adopt", "autoadopt", "pos", "padopt", "pign",
                      "menu_futuros", "opc", "lev", "tipo", "ejec"):
            bot.answer_callback_query(call.id, "🔒 Solo análisis: este bot no opera.")
            return

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
                cuadro = prediccion.cuadro_veredicto(coin, pred, obj, False)
                bot.send_message(call.message.chat.id, cuadro, parse_mode="Markdown")   # solo la respuesta; el análisis queda dentro del bot
            else:
                bot.send_message(call.message.chat.id, f"❌ No se pudo analizar {coin}.", parse_mode="Markdown")

        # === REPORTE TÉCNICO POR MONEDA / ANÁLISIS TÉCNICO ===
        elif accion in ("ver", "ana") and len(datos) >= 2:
            coin = datos[1]
            bot.answer_callback_query(call.id, f"Analizando {coin}...")
            analisis = obtener_analisis_con_reintentos(coin, 'swap')
            if analisis.get('estado') == "FALLA EN EXCHANGE":
                bot.send_message(call.message.chat.id, f"⚠️ Binance no respondió para {coin}/USDT (error temporal del exchange). Intenta de nuevo en unos segundos.")
                return
            t4h = obtener_tendencia_4h(coin, 'swap')
            sentimiento = obtener_sentimiento_mercado()
            titulo = "🔔 REPORTE TÉCNICO 🔔" if accion == "ver" else "🔔 ANÁLISIS TÉCNICO 🔔"
            bot.send_message(call.message.chat.id, construir_reporte(titulo, coin, analisis, t4h, sentimiento), parse_mode="Markdown")

        # === IGNORAR UNA SEÑAL / botones viejos de confirmar operación ===
        elif accion == "conf" and len(datos) >= 3:
            if datos[1] == "no":
                bot.answer_callback_query(call.id, "Señal ignorada.")
            else:
                bot.answer_callback_query(call.id, "🔒 Solo análisis: este bot no opera.")
            return

        # === LISTA DE SEGUIMIENTO ===
        elif accion == "activas":
            bot.answer_callback_query(call.id, "Lista de seguimiento...")
            bot.send_message(call.message.chat.id, texto_seguimiento())

        # === BACKTEST DESDE EL MENÚ ===
        elif accion == "backtest":
            bot.answer_callback_query(call.id, "Backtest en curso...")
            lanzar_backtest(call.message.chat.id, [])

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
