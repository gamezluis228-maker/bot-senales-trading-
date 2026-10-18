"""Recuerda el modo elegido para cada posición (trailing / vigilar / ignorar) entre reinicios del bot.

Archivo JSON; ruta configurable con MODOS_PATH. En Render el disco es efímero: sobrevive a reinicios
simples, pero para que sobreviva a los despliegues hace falta un Disk persistente.
Se identifica la posición por moneda + lado + precio de entrada (si cambia la entrada, se vuelve a preguntar).
"""
import json
import os
import threading

RUTA = os.getenv("MODOS_PATH", "modos_posiciones.json")
TOLERANCIA = 0.0005          # la entrada debe coincidir con una diferencia máxima de 0.05 %
VALIDOS = ("trailing", "vigilar", "ignorar")
_lock = threading.Lock()


def _leer():
    try:
        with open(RUTA, "r", encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _escribir(d):
    try:
        tmp = RUTA + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f)
        os.replace(tmp, RUTA)
    except OSError:
        pass                 # sin disco no pasa nada: solo se pierde el recuerdo


def guardar(coin, lado, entrada, modo):
    """lado: 'buy' / 'sell'."""
    if modo not in VALIDOS or not entrada:
        return
    with _lock:
        d = _leer()
        d[coin] = {"lado": lado, "entrada": float(entrada), "modo": modo}
        _escribir(d)


def buscar(coin, lado, entrada):
    """Modo recordado para esa posición, o None si no hay o la posición cambió."""
    with _lock:
        r = _leer().get(coin)
    if not r or r.get("lado") != lado or r.get("modo") not in VALIDOS or not entrada:
        return None
    if abs(float(entrada) - r["entrada"]) / r["entrada"] > TOLERANCIA:
        return None
    return r["modo"]


def olvidar_cerradas(coins_vivas):
    """Borra lo recordado de monedas que ya no tienen posición abierta."""
    with _lock:
        d = _leer()
        quedan = {c: v for c, v in d.items() if c in coins_vivas}
        if len(quedan) != len(d):
            _escribir(quedan)
