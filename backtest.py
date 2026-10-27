"""Backtest de la estrategia REAL del bot sobre velas cerradas de MEXC.

No es una copia de la estrategia: llama a senales._cruce_ema_rsi, la misma
función que usa el bot en vivo dentro de evaluar(), vela por vela, sin mirar
al futuro (solo velas cerradas hasta cada punto). Mide la señal de cruce
EMA 9/21 + RSI (VERDADERO/PROBABLE), que es la que genera la mayoría de
entradas.

Reglas de la simulación (iguales a la operación en vivo):
- Entrada: al cierre de la vela donde se detecta la señal (en vivo la señal
  llega cuando esa vela cierra y se entra al precio siguiente, casi igual).
- Una sola posición a la vez por moneda (el bot no abre otra encima).
- Salidas: stop y meta de la propia señal (cruce: -1,5% / +3%), o cruce
  contrario VERDADERO/PROBABLE (cierre de esa vela). Si en una vela tocan
  stop y meta a la vez, se cuenta el stop (criterio conservador).
- Sin comisiones ni deslizamiento. El pasado NO garantiza el futuro.
- Mide la estrategia, no los avisos (sin filtro de sensibilidad, sin cupo
  diario de 8 avisos y sin la regla de 90 minutos entre avisos).
"""

import time
from bisect import bisect_right

import numpy as np

import indicadores as ind
import senales

TF_MS = {"15m": 900000, "1h": 3600000, "4h": 14400000}
VENTANA = 300          # velas primarias que ve cada evaluación (como en vivo)
VENTANA_CTX = 120      # velas 4H / BTC 1H de contexto
VEREDICTOS_VALIDOS = ("VERDADERO", "PROBABLE")


def fetch_serie(ex, market_symbol, timeframe, dias):
    """Velas CERRADAS de MEXC, paginando (límite 1000 por llamada)."""
    tf_ms = TF_MS[timeframe]
    ahora = int(time.time() * 1000)
    desde = ahora - int(dias * 86400 * 1000)
    out = []
    since = desde
    while True:
        lote = ex.fetch_ohlcv(market_symbol, timeframe, since=since, limit=1000)
        if not lote:
            break
        out.extend([v for v in lote if v[0] >= since])
        if len(lote) < 1000 or len(out) > 25000:
            break
        since = lote[-1][0] + tf_ms
    # Solo velas ya cerradas, sin duplicados, ordenadas
    vistos = set()
    limpias = []
    for v in out:
        if v[0] + tf_ms <= ahora and v[0] not in vistos:
            vistos.add(v[0])
            limpias.append([float(x) for x in v])
    limpias.sort(key=lambda v: v[0])
    return limpias


def _es_cruce_valido(s):
    return (s.get("subtipo", "").startswith("CRUCE_EMA_RSI")
            and s.get("veredicto") in VEREDICTOS_VALIDOS)


def _cruces_directos(v_prim, ts, tend4h, tend_btc):
    """Señales de cruce con la función REAL de senales (_cruce_ema_rsi), sin pasar
    por evaluar() (que además calcula niveles, ADX y volumen para los otros
    tipos de señal que el backtest no usa). RSI, EMA200, ADX y volumen SÍ se
    calculan de verdad con las mismas fórmulas que _metricas; el resto de
    campos que _armar copia a la señal son metadatos de pantalla que el
    backtest no lee. El resultado es idéntico al cruce que devolvería evaluar()."""
    cierres = [v[4] for v in v_prim]
    c = cierres[-1]
    arr = np.asarray(cierres, dtype=float)
    h = np.asarray([v[2] for v in v_prim], dtype=float)
    l = np.asarray([v[3] for v in v_prim], dtype=float)
    vol = np.asarray([v[5] for v in v_prim], dtype=float)
    ax = ind.adx_serie(h, l, arr, 14)
    adx_val = float(ax["adx"][-1]) if ax is not None else 0.0
    vol_prom = float(vol[-21:-1].mean()) if len(vol) > 21 else 0.0
    vol_rel = float(vol[-1] / vol_prom) if vol_prom > 0 else 0.0
    m = {"c": float(c), "rsi": float(ind.rsi(arr, 14)),
         "ema200": float(ind.ultima_ema(arr, 200)),
         "atr": 1.0, "ema20": float(c), "ema50": float(c), "res": float(c), "sop": float(c),
         "adx": adx_val, "vol_rel": vol_rel, "ts": int(ts)}
    out = []
    for direccion in ("LONG", "SHORT"):
        try:
            s = senales._cruce_ema_rsi(cierres, m, direccion, tend4h, tend_btc)
        except Exception:
            s = None
        if s is not None and _es_cruce_valido(s):
            out.append(s)
    return out


def _candidato_cruce(i, e9, e21, precio):
    """¿Vale la pena evaluar esta vela? Solo si las EMA 9/21 cruzaron entre las
    últimas 3 velas o están muy pegadas (≤0,2% del precio). La EMA de la ventana
    de 300 velas que usa evaluar() converge con la de la serie completa tras
    cientos de velas, así que este filtro es un superconjunto seguro: nunca
    deja fuera una vela donde evaluar() encontraría un cruce, pero evita
    evaluar las miles de velas donde es imposible (eso era lo que tardaba)."""
    for k in (i, i - 1, i - 2):
        if k < 1:
            continue
        a9, a21, b9, b21 = e9[k], e21[k], e9[k - 1], e21[k - 1]
        if np.isnan(a9) or np.isnan(a21) or np.isnan(b9) or np.isnan(b21):
            continue
        if (b9 <= b21 and a9 > a21) or (b9 >= b21 and a9 < a21):
            return True
        if abs(a9 - a21) <= 0.002 * precio:
            return True
    return False


def ejecutar(ex, coin, dias=60, timeframe="15m", sin_filtro_btc=()):
    """Corre el backtest de una moneda. Devuelve un dict con métricas y operaciones."""
    ms = f"{coin}/USDT:USDT"
    try:
        prim = fetch_serie(ex, ms, timeframe, dias)
        ctx4h = fetch_serie(ex, ms, "4h", dias)
        btc1h = None
        if coin != "BTC" and coin not in sin_filtro_btc:
            btc1h = fetch_serie(ex, "BTC/USDT:USDT", "1h", dias)
    except Exception as e:
        return {"coin": coin, "error": f"No pude leer velas de MEXC: {e}"}
    if len(prim) < VENTANA + 50:
        return {"coin": coin, "error": f"Datos insuficientes: solo {len(prim)} velas {timeframe}"}
    ts4h = [v[0] for v in ctx4h]
    tsbtc = [v[0] for v in btc1h] if btc1h else []
    # EMAs de la serie completa (una sola vez): pre-filtro barato. Antes se
    # llamaba a senales.evaluar en CADA vela y eso tardaba minutos; ahora solo
    # se evalúan las velas donde pudo haber un cruce.
    cierres = np.asarray([v[4] for v in prim], dtype=float)
    e9_full = ind.ema(cierres, 9)
    e21_full = ind.ema(cierres, 21)

    trades = []
    pos = None  # {dir, entrada, sl, tp, sl_pct, ts_entrada}

    def _cerrar(salida, motivo):
        nonlocal pos
        entrada = pos["entrada"]
        if pos["dir"] == "LONG":
            r = ((salida - entrada) / entrada * 100) / pos["sl_pct"]
        else:
            r = ((entrada - salida) / entrada * 100) / pos["sl_pct"]
        trades.append({"ts_entrada": pos["ts"], "dir": pos["dir"], "entrada": entrada,
                       "salida": salida, "motivo": motivo, "r": round(r, 2)})
        pos = None

    for i in range(VENTANA, len(prim)):
        vela = prim[i]
        ts = vela[0]
        if pos is not None:
            # Salida por stop/meta: no necesita evaluar nada
            alto, bajo = vela[2], vela[3]
            if pos["dir"] == "LONG":
                if bajo <= pos["sl"]:
                    _cerrar(pos["sl"], "STOP")
                    continue
                if alto >= pos["tp"]:
                    _cerrar(pos["tp"], "META")
                    continue
            else:
                if alto >= pos["sl"]:
                    _cerrar(pos["sl"], "STOP")
                    continue
                if bajo <= pos["tp"]:
                    _cerrar(pos["tp"], "META")
                    continue
            if not _candidato_cruce(i, e9_full, e21_full, vela[4]):
                continue
        elif not _candidato_cruce(i, e9_full, e21_full, vela[4]):
            continue
        v_prim = prim[max(0, i - VENTANA + 1):i + 1]
        k4 = bisect_right(ts4h, ts)
        v4h = ctx4h[max(0, k4 - VENTANA_CTX):k4] if k4 else None
        vbtc = None
        if btc1h:
            kb = bisect_right(tsbtc, ts)
            vbtc = btc1h[max(0, kb - VENTANA_CTX):kb] if kb else None
        tend4h = senales.tendencia([x[4] for x in v4h]) if v4h else "NEUTRAL"
        tend_btc = senales.tendencia([x[4] for x in vbtc]) if vbtc else None
        cruces = _cruces_directos(v_prim, ts, tend4h, tend_btc)
        if pos is None:
            if not cruces:
                continue
            s = cruces[0]  # evaluar ya las ordena de mayor a menor calidad
            entrada = vela[4]
            sl_pct = float(s.get("sl_pct") or 1.5)
            tp_pct = float(s.get("tp_pct") or 3.0)
            if s["tipo"] == "COMPRA":
                sl, tp = entrada * (1 - sl_pct / 100), entrada * (1 + tp_pct / 100)
                direccion = "LONG"
            else:
                sl, tp = entrada * (1 + sl_pct / 100), entrada * (1 - tp_pct / 100)
                direccion = "SHORT"
            pos = {"dir": direccion, "entrada": entrada, "sl": sl, "tp": tp,
                   "sl_pct": sl_pct, "ts": ts, "subtipo": s["subtipo"]}
            continue
        contrario = "VENTA" if pos["dir"] == "LONG" else "COMPRA"
        if any(s["tipo"] == contrario for s in cruces):
            _cerrar(vela[4], "CRUCE CONTRARIO")
    if pos is not None:
        # Operación abierta al final de los datos: se cierra al último cierre
        entrada = pos["entrada"]
        salida = prim[-1][4]
        if pos["dir"] == "LONG":
            r = ((salida - entrada) / entrada * 100) / pos["sl_pct"]
        else:
            r = ((entrada - salida) / entrada * 100) / pos["sl_pct"]
        trades.append({"ts_entrada": pos["ts"], "dir": pos["dir"], "entrada": entrada,
                       "salida": salida, "motivo": "ABIERTA AL FINAL", "r": round(r, 2)})

    n = len(trades)
    ganadas = [t for t in trades if t["r"] > 0]
    perdidas = [t for t in trades if t["r"] <= 0]
    bruto_g = sum(t["r"] for t in ganadas)
    bruto_p = sum(t["r"] for t in perdidas)
    net_r = round(bruto_g + bruto_p, 2)
    racha = max_r = 0
    for t in trades:
        racha = racha + 1 if t["r"] <= 0 else 0
        max_r = max(max_r, racha)
    return {"coin": coin, "timeframe": timeframe, "dias": dias,
            "desde": prim[VENTANA][0], "hasta": prim[-1][0], "n_velas": len(prim),
            "trades": trades, "n": n, "ganadas": len(ganadas), "perdidas": len(perdidas),
            "win_pct": round(100 * len(ganadas) / n, 1) if n else 0.0,
            "net_r": net_r, "expectativa": round(net_r / n, 2) if n else 0.0,
            "pf": round(bruto_g / abs(bruto_p), 2) if bruto_p else 0.0,
            "max_rachas_perd": max_r}


def _fecha(ts):
    return time.strftime("%d/%m", time.gmtime(ts / 1000))


def formatear(res):
    """Texto corto del resultado de una moneda."""
    if res.get("error"):
        return f"• {res['coin']}: {res['error']}"
    lineas = [f"📊 BACKTEST {res['coin']} ({res['timeframe']}, {_fecha(res['desde'])} → {_fecha(res['hasta'])}, {res['n_velas']} velas)",
              f"Operaciones: {res['n']} | Ganadas: {res['ganadas']} | Perdidas: {res['perdidas']} | Acierto: {res['win_pct']}%",
              f"Neto: {res['net_r']:+.2f}R | Esperanza por operación: {res['expectativa']:+.2f}R | Factor ganancia: {res['pf']} | Peor racha: {res['max_rachas_perd']} perdidas seguidas"]
    for t in res["trades"][-5:]:
        lineas.append(f"  {_fecha(t['ts_entrada'])} {t['dir']} {t['motivo']}: {t['r']:+.2f}R")
    return "\n".join(lineas)
