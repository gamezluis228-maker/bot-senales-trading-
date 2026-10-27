"""Backtest de la estrategia REAL del bot sobre velas cerradas de MEXC.

No es una copia de la estrategia: llama a senales.evaluar, la misma función que
usa el bot en vivo, vela por vela, sin mirar al futuro (solo velas cerradas
hasta cada punto). Mide la señal de cruce EMA 9/21 + RSI (VERDADERO/PROBABLE),
que es la que genera la mayoría de entradas.

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

    trades = []
    pos = None  # {dir, entrada, sl, tp, sl_pct, ts_entrada}
    for i in range(VENTANA, len(prim)):
        vela = prim[i]
        ts = vela[0]
        v_prim = prim[max(0, i - VENTANA + 1):i + 1]
        k4 = bisect_right(ts4h, ts)
        v4h = ctx4h[max(0, k4 - VENTANA_CTX):k4] if k4 else None
        vbtc = None
        if btc1h:
            kb = bisect_right(tsbtc, ts)
            vbtc = btc1h[max(0, kb - VENTANA_CTX):kb] if kb else None
        try:
            señales = senales.evaluar(coin, v_prim, v4h, vbtc)
        except Exception:
            continue
        cruces = [s for s in señales if _es_cruce_valido(s)]
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
        # Hay posición abierta: revisar salida en esta vela (posterior a la de entrada)
        alto, bajo = vela[2], vela[3]
        salida, motivo = None, None
        if pos["dir"] == "LONG":
            if bajo <= pos["sl"]:
                salida, motivo = pos["sl"], "STOP"
            elif alto >= pos["tp"]:
                salida, motivo = pos["tp"], "META"
        else:
            if alto >= pos["sl"]:
                salida, motivo = pos["sl"], "STOP"
            elif bajo <= pos["tp"]:
                salida, motivo = pos["tp"], "META"
        if salida is None:
            contrario = "VENTA" if pos["dir"] == "LONG" else "COMPRA"
            if any(s["tipo"] == contrario for s in cruces):
                salida, motivo = vela[4], "CRUCE CONTRARIO"
        if salida is None:
            continue
        entrada = pos["entrada"]
        if pos["dir"] == "LONG":
            r = ((salida - entrada) / entrada * 100) / pos["sl_pct"]
        else:
            r = ((entrada - salida) / entrada * 100) / pos["sl_pct"]
        trades.append({"ts_entrada": pos["ts"], "dir": pos["dir"], "entrada": entrada,
                       "salida": salida, "motivo": motivo, "r": round(r, 2)})
        pos = None
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
