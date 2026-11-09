"""Pruebas del freno anti-baneo de Binance (rama binance, solo análisis).

Sin dependencias externas: telebot, ccxt y flask se sustituyen por dobles
antes de importar bot_render, así la prueba corre en cualquier máquina sin
tocar la red ni Binance. Para correrla: python tests/test_baneo_binance.py
"""
import os
import sys
import types
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# --- Dobles de telebot / ccxt / flask (no instalados en todas partes) --------
telebot_mod = types.ModuleType("telebot")
telebot_types = types.ModuleType("telebot.types")


class _Boton:
    def __init__(self, *a, **k):
        pass


class _Teclado:
    def __init__(self, *a, **k):
        self.botones = []

    def add(self, *a):
        self.botones.extend(a)


telebot_types.InlineKeyboardMarkup = _Teclado
telebot_types.InlineKeyboardButton = _Boton


class _TeleBot:
    def __init__(self, token):
        self.token = token
        self.enviados = []

    def message_handler(self, *a, **k):
        def deco(f):
            return f
        return deco

    def callback_query_handler(self, *a, **k):
        def deco(f):
            return f
        return deco

    def send_message(self, chat_id, texto, **k):
        self.enviados.append((chat_id, texto))

    def infinity_polling(self, *a, **k):
        pass


telebot_mod.TeleBot = _TeleBot
telebot_mod.types = telebot_types
sys.modules["telebot"] = telebot_mod
sys.modules["telebot.types"] = telebot_types


class _BinanceFalso:
    """Doble de ccxt.binance: fetch_ohlcv/load_markets los define la prueba."""
    def __init__(self, config=None):
        self.config = config or {}

    def fetch_ohlcv(self, *a, **k):
        raise NotImplementedError("doble sin configurar")

    def load_markets(self, *a, **k):
        return {}


ccxt_mod = types.ModuleType("ccxt")
ccxt_mod.binance = _BinanceFalso
sys.modules["ccxt"] = ccxt_mod


class _Flask:
    def __init__(self, *a, **k):
        pass

    def run(self, *a, **k):
        pass


flask_mod = types.ModuleType("flask")
flask_mod.Flask = _Flask
sys.modules["flask"] = flask_mod

os.environ["TEL_TOKEN"] = "123456:TOKEN_DE_PRUEBA"

import bot_render  # noqa: E402

MENSAJE_BANEO_REAL = (
    'binance 418 Unknown {"code":-1003,"msg":"Way too many requests; '
    'IP(74.220.51.161) banned until 1794201898588. Please use the websocket '
    'for live updates to avoid bans."}'
)

FALLAS = []


def check(nombre, condicion, detalle=""):
    if condicion:
        print(f"  OK  {nombre}")
    else:
        print(f"  MAL {nombre} {detalle}")
        FALLAS.append(nombre)


def reset_baneo():
    bot_render._BANEO_BINANCE_HASTA = 0.0
    bot_render._ULTIMO_AVISO_BANEO_TS = 0.0


class IntercambioFalso:
    """Intercambio con contador de llamadas para verificar que no se toca la red."""
    def __init__(self, comportamiento):
        self.comportamiento = comportamiento
        self.llamadas_fetch = 0
        self.llamadas_load = 0

    def fetch_ohlcv(self, *a, **k):
        self.llamadas_fetch += 1
        return self.comportamiento(*a, **k)

    def load_markets(self, *a, **k):
        self.llamadas_load += 1
        return self.comportamiento(*a, **k)


def velas_falsas(n, precio=75000.0):
    import numpy as np
    rng = np.random.default_rng(7)
    retornos = rng.normal(0.0002, 0.001, n)
    cierres = precio * (1 + retornos).cumprod()
    ahora = int(time.time() * 1000)
    velas = []
    for i, c in enumerate(cierres):
        velas.append([ahora - (n - i) * 3600000, c * 0.999, c * 1.001, c * 0.998, c, 10.0])
    return velas


def test_parsea_hora_del_baneo():
    reset_baneo()
    assert bot_render._registrar_baneo_binance(MENSAJE_BANEO_REAL) is True
    # 1794201898588 ms -> 1794201898 s + 60 s de margen
    check("parsea la hora del baneo",
          abs(bot_render._BANEO_BINANCE_HASTA - (1794201898 + 60)) < 1,
          f"quedó en {bot_render._BANEO_BINANCE_HASTA}")
    check("queda bloqueado tras el baneo", bot_render._binance_bloqueado())


def test_no_toca_la_red_durante_el_baneo():
    reset_baneo()
    falso = IntercambioFalso(lambda *a, **k: (_ for _ in ()).throw(Exception(MENSAJE_BANEO_REAL)))
    protegido = bot_render._proteger_instancia(falso)
    try:
        protegido.fetch_ohlcv("BTC/USDT:USDT", timeframe="1h", limit=260)
        check("primera llamada con baneo lanza error", False)
    except Exception:
        check("primera llamada con baneo lanza error", True)
    llamadas_tras_primera = falso.llamadas_fetch
    try:
        protegido.fetch_ohlcv("BTC/USDT:USDT", timeframe="1h", limit=260)
        check("segunda llamada no toca la red", False)
    except Exception as e:
        check("segunda llamada no toca la red",
              falso.llamadas_fetch == llamadas_tras_primera and "bloqueado" in str(e).lower(),
              f"llamadas={falso.llamadas_fetch} error={e}")
    try:
        protegido.load_markets()
        check("load_markets tampoco toca la red", False)
    except Exception:
        check("load_markets tampoco toca la red", falso.llamadas_load == 0)


def test_error_normal_no_es_baneo():
    reset_baneo()
    falso = IntercambioFalso(lambda *a, **k: (_ for _ in ()).throw(Exception("timeout de red")))
    protegido = bot_render._proteger_instancia(falso)
    for _ in range(2):
        try:
            protegido.fetch_ohlcv("BTC/USDT:USDT", timeframe="1h", limit=10)
        except Exception:
            pass
    check("error normal no registra baneo",
          falso.llamadas_fetch == 2 and not bot_render._binance_bloqueado(),
          f"llamadas={falso.llamadas_fetch}")


def test_sin_reintentos_ante_baneo():
    reset_baneo()
    falso = IntercambioFalso(lambda *a, **k: (_ for _ in ()).throw(Exception(MENSAJE_BANEO_REAL)))
    protegido = bot_render._proteger_instancia(falso)
    original = bot_render.crear_instancia_exchange
    bot_render.crear_instancia_exchange = lambda mercado="swap": protegido
    try:
        a = bot_render.obtener_analisis_con_reintentos("BTC", "swap")
        check("reintentos ante baneo devuelven FALLA",
              a.get("estado") == "FALLA EN EXCHANGE")
        check("ante baneo solo hay 1 llamada (sin reintentos)",
              falso.llamadas_fetch == 1, f"llamadas={falso.llamadas_fetch}")
    finally:
        bot_render.crear_instancia_exchange = original


def test_camino_feliz_sigue_funcionando():
    reset_baneo()
    falso = IntercambioFalso(lambda *a, **k: velas_falsas(k.get("limit", 100)))
    protegido = bot_render._proteger_instancia(falso)
    original = bot_render.crear_instancia_exchange
    bot_render.crear_instancia_exchange = lambda mercado="swap": protegido
    try:
        a = bot_render.obtener_analisis_binance("BTC", "swap")
        check("camino feliz devuelve análisis normal",
              a.get("estado") != "FALLA EN EXCHANGE" and a.get("precio", 0) > 0,
              f"estado={a.get('estado')} precio={a.get('precio')}")
    finally:
        bot_render.crear_instancia_exchange = original


if __name__ == "__main__":
    print("Pruebas anti-baneo de Binance:")
    test_parsea_hora_del_baneo()
    test_no_toca_la_red_durante_el_baneo()
    test_error_normal_no_es_baneo()
    test_sin_reintentos_ante_baneo()
    test_camino_feliz_sigue_funcionando()
    if FALLAS:
        print(f"\nFALLARON: {FALLAS}")
        sys.exit(1)
    print("\nTodas pasaron.")
