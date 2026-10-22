"""Avisos de entrada: filtro de sensibilidad, zona de entrada por retroceso (pullback), vigilancia de
niveles y configuración persistente. Funciones puras (sin red ni Telegram); se prueban con datos simulados:
    python3 tests/test_avisos.py
Formato de vela: [timestamp_ms, abierta, maxima, minima, cierre, volumen] (solo velas CERRADAS).
"""
import json
import os
import threading

import numpy as np

import indicadores as ind
import senales

RUTA_CONFIG = os.getenv("CONFIG_AVISOS_PATH", "config_avisos.json")
SENSIBILIDADES = ("estricta", "normal")
MIN_VELAS_15M = 60
TOL_ZONA_ATR = 0.25          # "tocó la EMA 21" = a menos de 0.25 ATR(15m)
MAX_EXTENSION_ATR = 1.5      # no entrar si el precio ya se alejó >1.5 ATR(1H) de la EMA 20 (1H)
ADX_MIN = 20.0
ESPERA_ZONA_SEG = 5400       # no repetir un aviso de zona (misma moneda y dirección) antes de 90 min
MAX_AVISOS_DIA = 8           # tope de avisos de entrada por día (anti-ruido)
MAX_VIGILANCIAS = 10
_lock = threading.Lock()

_CFG = {"activo": True, "sensibilidad": "estricta", "vigilancias": []}


# --- Configuración persistente ---------------------------------------------------------------
def config():
    with _lock:
        return json.loads(json.dumps(_CFG))


def cargar(ruta=None):
    ruta = ruta or RUTA_CONFIG
    try:
        with open(ruta, "r", encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        return
    with _lock:
        if isinstance(d.get("activo"), bool):
            _CFG["activo"] = d["activo"]
        if d.get("sensibilidad") in SENSIBILIDADES:
            _CFG["sensibilidad"] = d["sensibilidad"]
        if isinstance(d.get("vigilancias"), list):
            _CFG["vigilancias"] = [v for v in d["vigilancias"] if _vig_valida(v)][:MAX_VIGILANCIAS]


def _guardar(ruta=None):
    ruta = ruta or RUTA_CONFIG
    try:
        tmp = ruta + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(_CFG, f, ensure_ascii=False)
        os.replace(tmp, ruta)
    except OSError:
        pass                       # sin disco no pasa nada: la config vive en memoria


def _vig_valida(v):
    return (isinstance(v, dict) and isinstance(v.get("coin"), str) and v.get("lado") in ("arriba", "abajo")
            and isinstance(v.get("nivel"), (int, float)) and v["nivel"] > 0)


def poner_activo(valor, ruta=None):
    with _lock:
        _CFG["activo"] = bool(valor)
        _guardar(ruta)


def poner_sensibilidad(valor, ruta=None):
    """Devuelve True si el valor es válido."""
    valor = (valor or "").lower()
    if valor not in SENSIBILIDADES:
        return False
    with _lock:
        _CFG["sensibilidad"] = valor
        _guardar(ruta)
    return True


def reiniciar_config():
    with _lock:
        _CFG.update({"activo": True, "sensibilidad": "estricta", "vigilancias": []})


# --- Filtro por sensibilidad ------------------------------------------------------------------
def pasa_filtro(veredicto, sensibilidad):
    """estricta: solo VERDADERO. normal: VERDADERO y PROBABLE. DEBIL nunca se avisa."""
    if sensibilidad == "normal":
        return veredicto in ("VERDADERO", "PROBABLE")
    return veredicto == "VERDADERO"


def cupo_disponible(avisos_hoy):
    return avisos_hoy < MAX_AVISOS_DIA


def puede_repetir(ultimo_ts, ahora, espera=ESPERA_ZONA_SEG):
    return ultimo_ts is None or ahora - ultimo_ts >= espera


# --- Vigilancia de niveles ---------------------------------------------------------------------
def agregar_vigilancia(coin, nivel, precio_actual, ruta=None):
    """Avisa cuando el precio CRUCE el nivel. Devuelve (ok, mensaje)."""
    if nivel <= 0 or precio_actual <= 0:
        return False, "Precio inválido."
    if abs(nivel - precio_actual) / precio_actual < 0.0005:
        return False, "Ese nivel está pegado al precio actual."
    lado = "arriba" if nivel > precio_actual else "abajo"
    with _lock:
        if len(_CFG["vigilancias"]) >= MAX_VIGILANCIAS:
            return False, f"Máximo {MAX_VIGILANCIAS} vigilancias. Borra alguna con /vigilar borrar."
        _CFG["vigilancias"].append({"coin": coin.upper(), "nivel": float(nivel), "lado": lado})
        _guardar(ruta)
    return True, lado


def borrar_vigilancias(coin=None, ruta=None):
    with _lock:
        antes = len(_CFG["vigilancias"])
        _CFG["vigilancias"] = [v for v in _CFG["vigilancias"] if coin and v["coin"] != coin.upper()]
        _guardar(ruta)
        return antes - len(_CFG["vigilancias"])


def revisar_vigilancias(precios, ruta=None):
    """precios: {'ETH': 3500.0}. Devuelve las vigilancias cumplidas y las elimina."""
    cumplidas = []
    with _lock:
        quedan = []
        for v in _CFG["vigilancias"]:
            p = precios.get(v["coin"])
            if p is not None and ((v["lado"] == "arriba" and p >= v["nivel"]) or (v["lado"] == "abajo" and p <= v["nivel"])):
                cumplidas.append(dict(v, precio=p))
            else:
                quedan.append(v)
        if cumplidas:
            _CFG["vigilancias"] = quedan
            _guardar(ruta)
    return cumplidas


# --- Zona de entrada por retroceso --------------------------------------------------------------
_TITULOS = {
    "COMPRA": {"VERDADERO": "Zona de COMPRA: retroceso a la EMA 21 con rebote",
               "PROBABLE": "Posible zona de compra (faltan confirmaciones)",
               "DEBIL": "Sin zona de compra clara"},
    "VENTA": {"VERDADERO": "Zona de VENTA: rebote a la EMA 21 con rechazo",
              "PROBABLE": "Posible zona de venta (faltan confirmaciones)",
              "DEBIL": "Sin zona de venta clara"},
}


def evaluar_zona(simbolo, v15, v1h, v4h=None, vbtc=None):
    """Busca un buen PUNTO DE ENTRADA a favor de la tendencia: retroceso a la EMA 21 (15m) con vela de
    rebote, tendencia 1H/4H alineada, ADX con fuerza, RSI sano, precio no extendido y BTC sin oponerse.
    Evalúa solo la dirección de la tendencia 1H. Devuelve una lista (0 o 1 señal) con el mismo formato
    que senales.evaluar, para reutilizar mensajes y botones."""
    if len(v15) < MIN_VELAS_15M or len(v1h) < 60:
        return []
    a = np.asarray(v15, dtype=float)
    o, h, l, c = a[:, 1], a[:, 2], a[:, 3], a[:, 4]
    atr15 = ind.atr(h, l, c, 14)
    if atr15 <= 0:
        return []
    c1 = np.asarray([x[4] for x in v1h], dtype=float)
    h1 = np.asarray([x[2] for x in v1h], dtype=float)
    l1 = np.asarray([x[3] for x in v1h], dtype=float)
    tend1h = senales.tendencia(c1)
    if tend1h == "NEUTRAL":
        return []
    largo = tend1h == "ALCISTA"
    tend4h = senales.tendencia([x[4] for x in v4h]) if v4h else "NEUTRAL"
    tend_btc = senales.tendencia([x[4] for x in vbtc]) if (vbtc and simbolo != "BTC") else None

    ema9, ema21 = ind.ultima_ema(c, 9), ind.ultima_ema(c, 21)
    e20, e50, e200 = ind.ultima_ema(c1, 20), ind.ultima_ema(c1, 50), ind.ultima_ema(c1, 200)
    atr1h = ind.atr(h1, l1, c1, 14)
    ax = ind.adx_serie(h1, l1, c1, 14)
    adx = float(ax["adx"][-1]) if ax is not None else 0.0
    rsi15 = ind.rsi(c, 14)
    precio = float(c[-1])
    tol = TOL_ZONA_ATR * atr15
    ext = (precio - e20) / atr1h if atr1h > 0 else 0.0

    if largo:
        tocó = bool(np.any(l[-3:] <= ema21 + tol))
        rebote = bool(c[-1] > o[-1] and c[-1] > ema21)
        rsi_ok = 38 <= rsi15 <= 58
        ordenadas = bool(e20 > e50 > e200) if len(c1) >= 200 else bool(e20 > e50)
        no_extendido = ext <= MAX_EXTENSION_ATR
        btc_ok = tend_btc != "BAJISTA"
        ref_sl = float(np.min(l[-8:]))
        direccion = "LONG"
    else:
        tocó = bool(np.any(h[-3:] >= ema21 - tol))
        rebote = bool(c[-1] < o[-1] and c[-1] < ema21)
        rsi_ok = 42 <= rsi15 <= 62
        ordenadas = bool(e20 < e50 < e200) if len(c1) >= 200 else bool(e20 < e50)
        no_extendido = ext >= -MAX_EXTENSION_ATR
        btc_ok = tend_btc != "ALCISTA"
        ref_sl = float(np.max(h[-8:]))
        direccion = "SHORT"

    sentido = "alcista" if largo else "bajista"
    items = [
        (True, f"Tendencia 1H {sentido} (EMA 20/50)"),
        (tend4h == ("ALCISTA" if largo else "BAJISTA"), f"Tendencia 4H {sentido}"),
        (ordenadas, "EMAs 20/50/200 ordenadas en 1H"),
        (adx >= ADX_MIN, f"ADX 1H {adx:.0f} (mínimo {ADX_MIN:.0f}: hay tendencia)"),
        (tocó, "Retroceso hasta la EMA 21 (15m)" if largo else "Rebote hasta la EMA 21 (15m)"),
        (rebote, "Vela 15m de rebote sobre la EMA 21" if largo else "Vela 15m de rechazo bajo la EMA 21"),
        (rsi_ok, f"RSI 15m en zona sana ({rsi15:.0f})"),
        (no_extendido, "Precio no extendido respecto a la EMA 20 (1H)"),
        (btc_ok, "BTC no va en contra" if tend_btc is not None else "BTC (sin dato)"),
    ]
    puntos = sum(1 for ok, _ in items if ok)
    veredicto = senales._veredicto(puntos, len(items))
    if not (tocó and rebote):          # sin retroceso y rebote todavía no es "punto de entrada"
        veredicto = "DEBIL"
    sl_pct, tp_pct = senales.plan_riesgo(direccion, precio, ref_sl, 0.1 * atr15)
    tipo = "COMPRA" if largo else "VENTA"
    return [{
        "tipo": tipo, "direccion": direccion, "emoji": "🟢" if largo else "🔴",
        "subtipo": "zona", "tf": "15m",
        "descripcion": ("Entrada a favor de la tendencia tras un retroceso corto: stop pequeño, "
                        "la salida la lleva el trailing."),
        "titulo": _TITULOS[tipo][veredicto], "veredicto": veredicto,
        "puntos": puntos, "total": len(items),
        "checklist": [(bool(ok), txt) for ok, txt in items],
        "nivel": float(ema21), "precio": precio, "ts": int(a[-1, 0]), "atr": float(atr15),
        "sl_pct": sl_pct, "tp_pct": tp_pct,
        "rsi": round(float(rsi15), 1), "adx": round(adx, 1),
        "ema20": e20, "ema50": e50, "ema200": e200,
        "tendencia_1h": tend1h, "tendencia_4h": tend4h, "tendencia_btc": tend_btc,
        "simbolo": simbolo,
    }]


def resumen_mercado(simbolo, precio, senales_zona):
    """Texto corto para /mercado: qué ve el bot ahora en una moneda."""
    if not senales_zona:
        return f"• {simbolo} ${precio:,.2f}: sin tendencia 1H clara → sin zona de entrada."
    s = senales_zona[0]
    falta = [t for ok, t in s["checklist"] if not ok]
    estado = {"VERDADERO": "✅ PUNTO DE ENTRADA", "PROBABLE": "🟡 casi", "DEBIL": "⏳ esperando"}[s["veredicto"]]
    txt = f"• {simbolo} ${precio:,.2f} ({s['tipo']}): {estado} — {s['puntos']}/{s['total']}"
    if falta:
        txt += "\n   Falta: " + "; ".join(falta[:3])
    return txt


# --- Movimiento fuerte (el mercado se mueve YA) ----------------------------------------------------------------
MOV_ATR_NORMAL = 1.5         # movimiento mínimo en 3 h, en múltiplos del rango normal (ATR 1H)
MOV_ATR_ESTRICTA = 2.0       # por debajo de esto la señal nunca pasa de PROBABLE


def evaluar_movimiento(simbolo, v15, v1h, v4h=None, vbtc=None):
    """Detecta una caída o subida FUERTE en curso, aunque las EMAs lentas (1H/4H) todavía no hayan girado.
    Es el caso que el filtro de retroceso no ve: el mercado se desploma o se dispara sin dar un rebote a la EMA 21.
    Entras A FAVOR del movimiento ya en marcha (riesgo de rebote: por eso el stop es corto).
    Devuelve una lista (0 o 1 señal) con el mismo formato que senales.evaluar."""
    if len(v15) < MIN_VELAS_15M or len(v1h) < 60:
        return []
    c1 = np.asarray([x[4] for x in v1h], dtype=float)
    h1 = np.asarray([x[2] for x in v1h], dtype=float)
    l1 = np.asarray([x[3] for x in v1h], dtype=float)
    vol1 = np.asarray([x[5] for x in v1h], dtype=float)
    atr1 = ind.atr(h1, l1, c1, 14)
    if atr1 <= 0:
        return []
    mov = float(c1[-1] - c1[-4])                       # últimas 3 velas de 1H cerradas
    fuerza = abs(mov) / atr1
    if fuerza < MOV_ATR_NORMAL:
        return []
    baja = mov < 0
    a = np.asarray(v15, dtype=float)
    o, h, l, c = a[:, 1], a[:, 2], a[:, 3], a[:, 4]
    atr15 = ind.atr(h, l, c, 14)
    if atr15 <= 0:
        return []
    ema9, ema21 = ind.ultima_ema(c, 9), ind.ultima_ema(c, 21)
    sigue = bool(c[-1] < ema9 < ema21) if baja else bool(c[-1] > ema9 > ema21)
    cuerpo_ult = float(c[-1] - o[-1])
    rebote = (cuerpo_ult > 0.8 * atr15) if baja else (cuerpo_ult < -0.8 * atr15)   # vela fuerte en contra del movimiento
    prom = float(vol1[-23:-3].mean()) if len(vol1) >= 23 else 0.0
    vol_rel = float(vol1[-3:].mean() / prom) if prom > 0 else 1.0
    e20 = ind.ultima_ema(c1, 20)
    perdio_ema20 = bool(c1[-1] < e20) if baja else bool(c1[-1] > e20)
    tend_btc = senales.tendencia([x[4] for x in vbtc]) if (vbtc and simbolo != "BTC") else None
    btc_ok = tend_btc != ("ALCISTA" if baja else "BAJISTA")
    pct = mov / float(c1[-4]) * 100
    ax = ind.adx_serie(h1, l1, c1, 14)
    adx = float(ax["adx"][-1]) if ax is not None else 0.0
    verbo = "cayendo" if baja else "subiendo"
    items = [
        (fuerza >= MOV_ATR_ESTRICTA, f"Movimiento fuerte: {pct:+.1f}% en 3 h ({fuerza:.1f}x el rango normal)"),
        (sigue, "EMAs 9/21 (15m) alineadas con el movimiento"),
        (vol_rel >= 1.2, f"Volumen elevado (x{vol_rel:.1f})"),
        (not rebote, "Sin rebote fuerte en curso"),
        (perdio_ema20, "Precio " + ("bajo" if baja else "sobre") + " la EMA 20 (1H)"),
        (btc_ok, "BTC no se opone" if tend_btc is not None else "BTC (sin dato)"),
    ]
    puntos = sum(1 for ok, _ in items if ok)
    veredicto = senales._veredicto(puntos, len(items))
    if fuerza < MOV_ATR_ESTRICTA and veredicto == "VERDADERO":
        veredicto = "PROBABLE"
    if not sigue:
        veredicto = "DEBIL"                              # sin continuidad en 15m, no entrar
    precio = float(c[-1])
    direccion = "SHORT" if baja else "LONG"
    ref_sl = float(np.max(h[-6:])) if baja else float(np.min(l[-6:]))
    sl_pct, tp_pct = senales.plan_riesgo(direccion, precio, ref_sl, 0.1 * atr15)
    tipo = "VENTA" if baja else "COMPRA"
    titulos = {"VERDADERO": f"Mercado {verbo.upper()} fuerte: oportunidad de {tipo}",
               "PROBABLE": f"Mercado {verbo} con fuerza: posible {tipo}",
               "DEBIL": f"Movimiento sin continuidad: no entrar"}
    return [{
        "tipo": tipo, "direccion": direccion, "emoji": "🔴" if baja else "🟢",
        "subtipo": "movimiento", "tf": "15m",
        "descripcion": ("Entras a favor de un movimiento que ya está en marcha: no esperes un retroceso. "
                        "Si rebota, el stop es corto."),
        "titulo": titulos[veredicto], "veredicto": veredicto,
        "puntos": puntos, "total": len(items),
        "checklist": [(bool(ok), txt) for ok, txt in items],
        "nivel": float(ema21), "precio": precio, "ts": int(a[-1, 0]), "atr": float(atr15),
        "sl_pct": sl_pct, "tp_pct": tp_pct,
        "rsi": round(float(ind.rsi(c, 14)), 1), "adx": round(adx, 1),
        "ema20": e20, "ema50": ind.ultima_ema(c1, 50), "ema200": ind.ultima_ema(c1, 200),
        "tendencia_1h": senales.tendencia(c1), "tendencia_4h": senales.tendencia([x[4] for x in v4h]) if v4h else "NEUTRAL",
        "tendencia_btc": tend_btc, "simbolo": simbolo,
    }]


def resumen_movimiento(simbolo, senales_mov):
    """Línea para /mercado si hay un movimiento fuerte en curso (None si no)."""
    if not senales_mov or senales_mov[0]["veredicto"] == "DEBIL":
        return None
    s = senales_mov[0]
    return f"🔥 {simbolo}: {s['titulo']} ({s['puntos']}/{s['total']})"


# --- Alerta corta y directa ------------------------------------------------------------------------------------------
_FUERZA_AL = {"VERDADERO": "FUERTE", "PROBABLE": "MEDIA", "DEBIL": "DÉBIL"}


def texto_alerta(coin, s, lider_tipo=None):
    """Alerta de entrada en pocas líneas: qué hacer, a qué precio, dónde el stop y la meta. Sin listas de indicadores."""
    largo = s["tipo"] == "COMPRA"
    p = s["precio"]
    sl = p * (1 - s["sl_pct"] / 100) if largo else p * (1 + s["sl_pct"] / 100)
    tp = p * (1 + s["tp_pct"] / 100) if largo else p * (1 - s["tp_pct"] / 100)
    fmt = lambda x: f"{x:,.2f}" if abs(x) >= 1 else f"{x:.6f}"
    L = [f"{'🟢 COMPRA' if largo else '🔴 VENTA'} {coin}  |  Fuerza: {_FUERZA_AL.get(s['veredicto'], 'DÉBIL')}",
         s["titulo"],
         f"💵 Entrada ≈ ${fmt(p)}",
         f"🛑 Stop ${fmt(sl)} ({'-' if largo else '+'}{s['sl_pct']}%)  |  🎯 Meta ${fmt(tp)}"]
    if lider_tipo and lider_tipo == s["tipo"] and coin != "BTC":
        L.append(f"👑 BTC también va {'al alza' if largo else 'a la baja'}")
    motivos = [t for ok, t in s["checklist"] if ok][:2]
    if motivos:
        L.append("Por qué: " + "; ".join(motivos))
    return "\n".join(L)
