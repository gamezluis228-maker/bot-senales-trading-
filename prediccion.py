"""Probabilidad de que el precio suba o baje en los próximos 5-15 min (lógica pura, sin red).

IMPORTANTE: es una estimación heurística a partir de indicadores, NO una probabilidad calibrada
con datos históricos. A este horizonte el mercado es casi una moneda al aire, por eso el
resultado se limita a 30 %-70 %: el bot nunca dirá "90 % seguro".
Entradas: velas CERRADAS en formato ccxt [[ts, abierta, maxima, minima, cierre, volumen], ...].
"""
import math

import numpy as np

import indicadores as ind

K = 0.12                      # pendiente de la curva: puntaje máximo (~6.5) => ~69 %
P_MIN, P_MAX = 0.30, 0.70     # tope de honestidad
ADX_TENDENCIA = 20            # por debajo, el mercado está lateral y se reduce la confianza
ESCALA_LATERAL = 0.6
UMBRAL_DIRECCION = 0.55       # >=55 % => "sube"; <=45 % => "baja"; en medio => lateral


def _signo(x, tol=0.0):
    return 1 if x > tol else (-1 if x < -tol else 0)


def estimar(v5, v15=None, v1h=None):
    """Devuelve un dict con probabilidades y los factores usados, o None si faltan datos."""
    if v5 is None or len(v5) < 30:
        return None
    a5 = np.array(v5, dtype=float)
    o, h, l, c, v = a5[:, 1], a5[:, 2], a5[:, 3], a5[:, 4], a5[:, 5]
    cierre = float(c[-1])
    ema9, ema21 = ind.ultima_ema(c, 9), ind.ultima_ema(c, 21)
    rsi5 = ind.rsi(c)
    adx5 = ind.adx(h, l, c)
    atr5 = ind.atr(h, l, c)
    vprom = float(v[-11:-1].mean())
    vol_rel = float(v[-1] / vprom) if vprom > 0 else 0.0

    factores = []  # (nombre, voto -1/0/1, peso)
    factores.append(("Precio vs EMA9 (5m)", _signo(cierre - ema9), 1.0))
    factores.append(("EMA9 vs EMA21 (5m)", _signo(ema9 - ema21), 1.0))
    factores.append(("Impulso de las últimas 5 velas", _signo(cierre - float(c[-6])), 0.5))
    # RSI: a favor del impulso, pero un extremo sugiere agotamiento (reversión)
    if rsi5 >= 75:
        voto_rsi = -0.5
    elif rsi5 <= 25:
        voto_rsi = 0.5
    elif rsi5 > 55:
        voto_rsi = 1
    elif rsi5 < 45:
        voto_rsi = -1
    else:
        voto_rsi = 0
    factores.append(("RSI (5m)", voto_rsi, 1.0))
    # Volumen: solo cuenta si la última vela viene con volumen superior al promedio
    voto_vol = _signo(float(c[-1] - o[-1])) if vol_rel > 1.0 else 0
    factores.append(("Volumen confirma la última vela", voto_vol, 1.0))
    if v15 is not None and len(v15) >= 25:
        c15 = [x[4] for x in v15]
        factores.append(("Tendencia 15m (EMA9/21)", _signo(ind.ultima_ema(c15, 9) - ind.ultima_ema(c15, 21)), 1.0))
    if v1h is not None and len(v1h) >= 55:
        c1h = [x[4] for x in v1h]
        factores.append(("Tendencia 1H (EMA21/50)", _signo(ind.ultima_ema(c1h, 21) - ind.ultima_ema(c1h, 50)), 1.0))

    puntaje = sum(voto * peso for _, voto, peso in factores)
    escala = 1.0 if adx5 >= ADX_TENDENCIA else ESCALA_LATERAL
    p_sube = 1.0 / (1.0 + math.exp(-K * puntaje * escala))
    p_sube = min(P_MAX, max(P_MIN, p_sube))
    p_baja = 1.0 - p_sube

    if p_sube >= UMBRAL_DIRECCION:
        direccion = "SUBE"
    elif p_sube <= 1 - UMBRAL_DIRECCION:
        direccion = "BAJA"
    else:
        direccion = "LATERAL"
    ventaja = abs(p_sube - 0.5)
    confianza = "ALTA" if ventaja >= 0.12 else ("MEDIA" if ventaja >= 0.05 else "BAJA")

    return {
        "direccion": direccion,
        "prob_sube": int(round(p_sube * 100)),
        "prob_baja": int(round(p_baja * 100)),
        "confianza": confianza,
        "puntaje": round(puntaje, 2),
        "factores": factores,
        "puntos_alcista": sum(1 for _, voto, _ in factores if voto > 0),
        "puntos_bajista": sum(1 for _, voto, _ in factores if voto < 0),
        "rsi": float(rsi5), "adx": float(adx5), "ema9": ema9, "ema21": ema21,
        "atr_pct": float(atr5 / cierre * 100) if cierre else 0.0,
        "vol_rel": vol_rel, "volumen": float(v[-1]), "volumen_promedio": vprom,
        "lateral": adx5 < ADX_TENDENCIA,
    }
