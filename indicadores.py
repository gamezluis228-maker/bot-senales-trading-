"""Indicadores técnicos con numpy (sin pandas).

Todas las funciones aceptan listas o arrays. Los cálculos de RSI, ATR y ADX usan el
suavizado de Wilder (el estándar de TradingView y de los exchanges).
"""
import numpy as np


def ema(valores, periodo):
    """Media móvil exponencial. Se siembra con la media simple de las primeras `periodo`
    velas (igual que TradingView). Devuelve un array del mismo largo; las primeras
    `periodo - 1` posiciones son NaN cuando hay datos suficientes."""
    v = np.asarray(valores, dtype=float)
    n = len(v)
    if n == 0:
        return v
    alpha = 2.0 / (periodo + 1)
    out = np.full(n, np.nan)
    if n >= periodo:
        out[periodo - 1] = v[:periodo].mean()
        inicio = periodo
    else:
        out[0] = v[0]
        inicio = 1
    for i in range(inicio, n):
        out[i] = alpha * v[i] + (1 - alpha) * out[i - 1]
    return out


def ultima_ema(valores, periodo):
    """Último valor de la EMA como float (o 0.0 si no hay datos)."""
    e = ema(valores, periodo)
    return float(e[-1]) if len(e) else 0.0


def rsi(cierres, periodo=14):
    """RSI de Wilder sobre TODA la serie (el valor devuelto es el de la última vela)."""
    c = np.asarray(cierres, dtype=float)
    if len(c) < periodo + 1:
        return 50.0
    d = np.diff(c)
    ganancias = np.where(d > 0, d, 0.0)
    perdidas = np.where(d < 0, -d, 0.0)
    media_g = ganancias[:periodo].mean()
    media_p = perdidas[:periodo].mean()
    for i in range(periodo, len(d)):
        media_g = (media_g * (periodo - 1) + ganancias[i]) / periodo
        media_p = (media_p * (periodo - 1) + perdidas[i]) / periodo
    if media_p == 0:
        return 100.0 if media_g > 0 else 50.0
    return float(100 - 100 / (1 + media_g / media_p))


def _rango_verdadero(altos, bajos, cierres):
    h = np.asarray(altos, dtype=float)
    l = np.asarray(bajos, dtype=float)
    c = np.asarray(cierres, dtype=float)
    cierre_prev = c[:-1]
    return np.maximum.reduce([
        h[1:] - l[1:],
        np.abs(h[1:] - cierre_prev),
        np.abs(l[1:] - cierre_prev),
    ])


def atr(altos, bajos, cierres, periodo=14):
    """ATR de Wilder (último valor)."""
    if len(cierres) < 2:
        return 0.0
    tr = _rango_verdadero(altos, bajos, cierres)
    if len(tr) < periodo:
        return float(tr.mean())
    valor = tr[:periodo].mean()
    for x in tr[periodo:]:
        valor = (valor * (periodo - 1) + x) / periodo
    return float(valor)


def adx_serie(altos, bajos, cierres, periodo=14):
    """ADX de Wilder. Devuelve {'adx', 'pdi', 'mdi'} como arrays alineados al final
    de la serie, o None si no hay datos suficientes (se necesitan ~2*periodo velas)."""
    h = np.asarray(altos, dtype=float)
    l = np.asarray(bajos, dtype=float)
    c = np.asarray(cierres, dtype=float)
    if len(c) < 2 * periodo + 2:
        return None
    sube = h[1:] - h[:-1]
    baja = l[:-1] - l[1:]
    mas_dm = np.where((sube > baja) & (sube > 0), sube, 0.0)
    menos_dm = np.where((baja > sube) & (baja > 0), baja, 0.0)
    tr = _rango_verdadero(h, l, c)
    m = len(tr)

    def suma_wilder(x):
        s = np.empty(m - periodo + 1)
        s[0] = x[:periodo].sum()
        for i in range(1, len(s)):
            s[i] = s[i - 1] - s[i - 1] / periodo + x[periodo - 1 + i]
        return s

    tr_s = suma_wilder(tr)
    mas_s = suma_wilder(mas_dm)
    menos_s = suma_wilder(menos_dm)
    with np.errstate(divide="ignore", invalid="ignore"):
        pdi = np.where(tr_s > 0, 100.0 * mas_s / tr_s, 0.0)
        mdi = np.where(tr_s > 0, 100.0 * menos_s / tr_s, 0.0)
        suma_di = pdi + mdi
        dx = np.where(suma_di > 0, 100.0 * np.abs(pdi - mdi) / suma_di, 0.0)
    if len(dx) < periodo:
        return None
    adx_arr = np.empty(len(dx) - periodo + 1)
    adx_arr[0] = dx[:periodo].mean()
    for i in range(1, len(adx_arr)):
        adx_arr[i] = (adx_arr[i - 1] * (periodo - 1) + dx[periodo - 1 + i]) / periodo
    return {"adx": adx_arr, "pdi": pdi, "mdi": mdi}


def adx(altos, bajos, cierres, periodo=14):
    """Último valor del ADX (0.0 si no hay datos suficientes)."""
    r = adx_serie(altos, bajos, cierres, periodo)
    if r is None or len(r["adx"]) == 0:
        return 0.0
    return float(r["adx"][-1])


def niveles(altos, bajos, atr_valor, n=24, tolerancia_atr=0.25):
    """Resistencia (máximo) y soporte (mínimo) de las últimas `n` velas recibidas, y
    cuántas velas tocaron cada nivel (dentro de `tolerancia_atr` x ATR).
    Pasa SOLO velas anteriores a la vela de confirmación."""
    hh = np.asarray(altos[-n:], dtype=float)
    ll = np.asarray(bajos[-n:], dtype=float)
    resistencia = float(hh.max())
    soporte = float(ll.min())
    tol = tolerancia_atr * atr_valor
    toques_res = int((hh >= resistencia - tol).sum())
    toques_sop = int((ll <= soporte + tol).sum())
    return resistencia, soporte, toques_res, toques_sop
