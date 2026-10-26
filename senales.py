"""Lógica de señales (rompimiento verdadero / falso), plan de riesgo y trailing.

Todo son funciones puras (sin red ni Telegram) para poder probarlas con datos simulados.
Formato de vela: [timestamp_ms, abierta, maxima, minima, cierre, volumen].
IMPORTANTE: las señales se evalúan SOLO con velas cerradas (ver solo_cerradas).
"""
import numpy as np

import indicadores as ind

# --- Parámetros de la estrategia ---
VENTANA_NIVEL = 24        # velas previas usadas para el soporte/resistencia
BUFFER_ATR = 0.10         # el cierre debe superar el nivel por al menos 0.1 ATR
TOL_TOQUE_ATR = 0.25      # tolerancia para contar un "toque" del nivel
VOL_REL_MIN = 1.5         # volumen mínimo vs promedio de las 20 velas previas
SL_MIN_PCT = 0.6          # el stop nunca más cerca que 0.6 %
SL_MAX_PCT = 2.0          # a 20x, 2 % = 40 % del margen; la liquidación ronda el 5 %
TP_MULTIPLO_R = 3.0       # take profit lejano (techo); la salida normal es el trailing
COLCHON_COMISION = 0.001  # al proteger ganancia, el stop va 0.1 % más allá de la entrada
UMBRAL_VERDADERO = 0.75   # fracción de puntos para llamarlo VERDADERO
UMBRAL_PROBABLE = 0.55

_RANGO = {"VERDADERO": 2, "PROBABLE": 1, "DEBIL": 0}


def solo_cerradas(velas, tf_ms, ahora_ms):
    """Descarta la vela en curso: solo velas cuyo cierre ya ocurrió."""
    return [v for v in velas if v[0] + tf_ms <= ahora_ms]


def tendencia(cierres):
    """ALCISTA / BAJISTA / NEUTRAL según EMA 20 y EMA 50."""
    if len(cierres) < 55:
        return "NEUTRAL"
    e20 = ind.ultima_ema(cierres, 20)
    e50 = ind.ultima_ema(cierres, 50)
    ultimo = float(cierres[-1])
    if e20 > e50 and ultimo > e50:
        return "ALCISTA"
    if e20 < e50 and ultimo < e50:
        return "BAJISTA"
    return "NEUTRAL"


def _metricas(velas):
    """Métricas de la ÚLTIMA vela de la lista (la vela de confirmación)."""
    a = np.asarray(velas, dtype=float)
    if len(a) < VENTANA_NIVEL + 30:
        return None
    o, h, l, c, v = a[:, 1], a[:, 2], a[:, 3], a[:, 4], a[:, 5]
    atr_val = ind.atr(h, l, c, 14)
    rango = h[-1] - l[-1]
    if atr_val <= 0 or rango <= 0:
        return None
    res, sop, t_res, t_sop = ind.niveles(h[:-1], l[:-1], atr_val, VENTANA_NIVEL, TOL_TOQUE_ATR)
    vol_prom = float(v[-21:-1].mean())
    ax = ind.adx_serie(h, l, c, 14)
    adx_val = float(ax["adx"][-1]) if ax is not None else 0.0
    adx_sube = bool(ax is not None and len(ax["adx"]) >= 4 and ax["adx"][-1] > ax["adx"][-4])
    e20 = ind.ultima_ema(c, 20)
    return {
        "ts": int(a[-1, 0]), "o": float(o[-1]), "h": float(h[-1]), "l": float(l[-1]),
        "c": float(c[-1]), "c_prev": float(c[-2]), "v": float(v[-1]),
        "atr": float(atr_val), "rango": float(rango),
        "cuerpo": float(abs(c[-1] - o[-1])),
        "mecha_sup": float(h[-1] - max(o[-1], c[-1])),
        "mecha_inf": float(min(o[-1], c[-1]) - l[-1]),
        "res": res, "sop": sop, "t_res": t_res, "t_sop": t_sop,
        "vol_rel": float(v[-1] / vol_prom) if vol_prom > 0 else 0.0,
        "ema20": e20, "ema50": ind.ultima_ema(c, 50), "ema200": ind.ultima_ema(c, 200),
        "tend1h": tendencia(c),
        "rsi": ind.rsi(c, 14), "adx": adx_val, "adx_sube": adx_sube,
        "cambio_3": float((c[-1] - c[-4]) / c[-4] * 100),
        "dist_ema20_atr": float((c[-1] - e20) / atr_val),
    }


def _veredicto(puntos, total):
    f = puntos / total if total else 0
    if f >= UMBRAL_VERDADERO:
        return "VERDADERO"
    if f >= UMBRAL_PROBABLE:
        return "PROBABLE"
    return "DEBIL"


def plan_riesgo(direccion, entrada, referencia_sl, margen_atr):
    """SL estructural (más allá de la referencia) acotado entre SL_MIN y SL_MAX.
    Devuelve (sl_pct, tp_pct) en % del precio de entrada."""
    if direccion == "LONG":
        dist = entrada - (referencia_sl - margen_atr)
    else:
        dist = (referencia_sl + margen_atr) - entrada
    sl_pct = min(max(dist / entrada * 100.0, SL_MIN_PCT), SL_MAX_PCT)
    return round(sl_pct, 2), round(sl_pct * TP_MULTIPLO_R, 2)


def _checklist_ruptura(m, direccion, tend4h, tend_btc):
    largo = direccion == "LONG"
    r = m["cuerpo"] / m["rango"]
    mecha = (m["mecha_sup"] if largo else m["mecha_inf"]) / m["rango"]
    items = [
        (m["vol_rel"] >= VOL_REL_MIN, f"Volumen {m['vol_rel']:.1f}x del promedio (mín {VOL_REL_MIN}x)"),
        (r >= 0.5 and mecha <= 0.3, f"Cierre fuerte (cuerpo {r*100:.0f}%, mecha contraria {mecha*100:.0f}%)"),
        (m["tend1h"] == ("ALCISTA" if largo else "BAJISTA"), f"Tendencia 1H EMA20/50: {m['tend1h']}"),
        (tend4h == ("ALCISTA" if largo else "BAJISTA"), f"Tendencia 4H EMA20/50: {tend4h}"),
        (m["adx"] >= 20 and m["adx_sube"], f"ADX {m['adx']:.1f} (≥20 y subiendo)"),
    ]
    if largo:
        items.append((50 <= m["rsi"] < 75, f"RSI {m['rsi']:.1f} (zona 50-75)"))
        items.append((m["dist_ema20_atr"] <= 2.5 and m["cambio_3"] < 3.0,
                      f"No extendido ({m['dist_ema20_atr']:.1f} ATR de EMA20, {m['cambio_3']:+.1f}% en 3 velas)"))
        items.append((m["t_res"] >= 2, f"Resistencia probada ({m['t_res']} toques)"))
    else:
        items.append((25 < m["rsi"] <= 50, f"RSI {m['rsi']:.1f} (zona 25-50)"))
        items.append((m["dist_ema20_atr"] >= -2.5 and m["cambio_3"] > -3.0,
                      f"No extendido ({m['dist_ema20_atr']:.1f} ATR de EMA20, {m['cambio_3']:+.1f}% en 3 velas)"))
        items.append((m["t_sop"] >= 2, f"Soporte probado ({m['t_sop']} toques)"))
    if tend_btc is not None:
        contra = "BAJISTA" if largo else "ALCISTA"
        items.append((tend_btc != contra, f"BTC 1H no está en contra ({tend_btc})"))
    return items


def _armar(m, direccion, subtipo, descripcion, titulos, items, nivel, ref_sl, margen_atr, extra=None):
    puntos = sum(1 for ok, _ in items if ok)
    total = len(items)
    veredicto = _veredicto(puntos, total)
    sl_pct, tp_pct = plan_riesgo(direccion, m["c"], ref_sl, margen_atr)
    largo = direccion == "LONG"
    senal = {
        "tipo": "COMPRA" if largo else "VENTA",
        "direccion": direccion,
        "emoji": "🟢" if largo else "🔴",
        "subtipo": subtipo,
        "descripcion": descripcion,
        "titulo": titulos[veredicto],
        "veredicto": veredicto,
        "puntos": puntos, "total": total,
        "checklist": [(bool(ok), txt) for ok, txt in items],
        "nivel": float(nivel),
        "precio": m["c"], "ts": m["ts"], "atr": m["atr"],
        "sl_pct": sl_pct, "tp_pct": tp_pct,
        "rsi": round(m["rsi"], 1), "adx": round(m["adx"], 1), "vol_rel": round(m["vol_rel"], 2),
        "ema20": m["ema20"], "ema50": m["ema50"], "ema200": m["ema200"],
        "resistencia": m["res"], "soporte": m["sop"],
    }
    if extra:
        senal.update(extra)
    return senal


def _ruptura(m, direccion, tend4h, tend_btc):
    """Cierre de la vela más allá del nivel (rompimiento). None si no hubo rompimiento."""
    largo = direccion == "LONG"
    buf = BUFFER_ATR * m["atr"]
    if largo:
        if not (m["c"] > m["res"] + buf and m["c_prev"] <= m["res"]):
            return None
        nivel = m["res"]
        titulos = {"VERDADERO": "ROMPIMIENTO VERDADERO ✅", "PROBABLE": "ROMPIMIENTO PROBABLE ⚠️",
                   "DEBIL": "ROMPIMIENTO DÉBIL ❌ (probable falso, no operar)"}
        desc = "Rompimiento de resistencia (cierre de 1H por encima)"
        sub = "ROMPIMIENTO_RESISTENCIA"
    else:
        if not (m["c"] < m["sop"] - buf and m["c_prev"] >= m["sop"]):
            return None
        nivel = m["sop"]
        titulos = {"VERDADERO": "ROMPIMIENTO VERDADERO ✅", "PROBABLE": "ROMPIMIENTO PROBABLE ⚠️",
                   "DEBIL": "ROMPIMIENTO DÉBIL ❌ (probable falso, no operar)"}
        desc = "Rompimiento de soporte (cierre de 1H por debajo)"
        sub = "ROMPIMIENTO_SOPORTE"
    items = _checklist_ruptura(m, direccion, tend4h, tend_btc)
    return _armar(m, direccion, sub, desc, titulos, items, nivel, nivel, 0.5 * m["atr"])


def _trampa(m, direccion, tend4h, tend_btc):
    """Falso rompimiento: la vela perfora el nivel pero cierra de vuelta dentro (mecha de
    rechazo). Trampa en resistencia -> SHORT; trampa en soporte -> LONG."""
    largo = direccion == "LONG"  # LONG = trampa bajista en soporte
    buf = BUFFER_ATR * m["atr"]
    if largo:
        if not (m["l"] < m["sop"] - buf and m["c"] > m["sop"] and m["mecha_inf"] / m["rango"] >= 0.4):
            return None
        nivel, mecha, toques = m["sop"], m["mecha_inf"] / m["rango"], m["t_sop"]
        extremo = m["l"]
        cierre_zona = (m["h"] - m["c"]) / m["rango"] <= 0.4
        rsi_ok = m["rsi"] <= 45
        sin_tend = not (m["tend1h"] == "BAJISTA" and m["adx"] >= 25)
        btc_ok = tend_btc is None or tend_btc != "BAJISTA"
        t4_ok = tend4h != "BAJISTA"
        sub = "FALSO_ROMPIMIENTO_SOPORTE"
        desc = "Falso rompimiento de soporte (trampa bajista, mecha de rechazo abajo)"
        txt_tend = "Sin tendencia bajista fuerte en 1H"
    else:
        if not (m["h"] > m["res"] + buf and m["c"] < m["res"] and m["mecha_sup"] / m["rango"] >= 0.4):
            return None
        nivel, mecha, toques = m["res"], m["mecha_sup"] / m["rango"], m["t_res"]
        extremo = m["h"]
        cierre_zona = (m["c"] - m["l"]) / m["rango"] <= 0.4
        rsi_ok = m["rsi"] >= 55
        sin_tend = not (m["tend1h"] == "ALCISTA" and m["adx"] >= 25)
        btc_ok = tend_btc is None or tend_btc != "ALCISTA"
        t4_ok = tend4h != "ALCISTA"
        sub = "FALSO_ROMPIMIENTO_RESISTENCIA"
        desc = "Falso rompimiento de resistencia (trampa alcista, mecha de rechazo arriba)"
        txt_tend = "Sin tendencia alcista fuerte en 1H"
    items = [
        (mecha >= 0.6, f"Mecha de rechazo {mecha*100:.0f}% del rango (mín 60%)"),
        (cierre_zona, "La vela cierra en el extremo opuesto a la mecha"),
        (m["vol_rel"] >= 1.3, f"Volumen {m['vol_rel']:.1f}x del promedio (mín 1.3x)"),
        (rsi_ok, f"RSI {m['rsi']:.1f} ({'≤45' if largo else '≥55'})"),
        (sin_tend, txt_tend),
        (toques >= 2, f"Nivel probado ({toques} toques)"),
        (t4_ok, f"Tendencia 4H no está a favor del rompimiento ({tend4h})"),
    ]
    if tend_btc is not None:
        items.append((btc_ok, f"BTC 1H no empuja el rompimiento ({tend_btc})"))
    titulos = {"VERDADERO": "FALSO ROMPIMIENTO CONFIRMADO ✅", "PROBABLE": "POSIBLE FALSO ROMPIMIENTO ⚠️",
               "DEBIL": "FALSO ROMPIMIENTO DÉBIL ❌"}
    return _armar(m, direccion, sub, desc, titulos, items, nivel, extremo, 0.25 * m["atr"])


def _cruce_ema_rsi(cierres, m, direccion, tend4h, tend_btc):
    """Cruce EMA 9/21 con filtro RSI y EMA200 (entrada y salida).

    LONG: EMA9 cruza sobre EMA21 en la última vela cerrada, RSI < 65 y
    precio sobre EMA200. SHORT: lo contrario (RSI > 35, precio bajo EMA200).
    La señal contraria sirve también como aviso de salida.
    """
    largo = direccion == "LONG"
    if len(cierres) < 201:
        return None
    e9 = ind.ema(cierres, 9)
    e21 = ind.ema(cierres, 21)
    if np.isnan(e9[-1]) or np.isnan(e9[-2]) or np.isnan(e21[-1]) or np.isnan(e21[-2]):
        return None
    if largo:
        cruzo = e9[-2] <= e21[-2] and e9[-1] > e21[-1]
        rsi_ok = m["rsi"] < 65
        tend_ok = m["c"] > m["ema200"]
        desc = "Cruce EMA 9 sobre EMA 21 con RSI < 65 (entrada LONG)"
        sub = "CRUCE_EMA_RSI_LONG"
        titulos = {"VERDADERO": "CRUCE EMA LONG ✅", "PROBABLE": "CRUCE EMA LONG ⚠️",
                   "DEBIL": "CRUCE EMA LONG DÉBIL ❌"}
    else:
        cruzo = e9[-2] >= e21[-2] and e9[-1] < e21[-1]
        rsi_ok = m["rsi"] > 35
        tend_ok = m["c"] < m["ema200"]
        desc = "Cruce EMA 9 bajo EMA 21 con RSI > 35 (entrada SHORT)"
        sub = "CRUCE_EMA_RSI_SHORT"
        titulos = {"VERDADERO": "CRUCE EMA SHORT ✅", "PROBABLE": "CRUCE EMA SHORT ⚠️",
                   "DEBIL": "CRUCE EMA SHORT DÉBIL ❌"}
    if not cruzo:
        return None
    items = [
        (True, f"Cruce EMA 9/21 en la última vela cerrada (EMA9 {e9[-1]:.2f} vs EMA21 {e21[-1]:.2f})"),
        (rsi_ok, f"RSI {m['rsi']:.1f} ({'< 65' if largo else '> 35'})"),
        (tend_ok, f"Precio {'sobre' if largo else 'bajo'} EMA200 ({m['ema200']:.2f})"),
    ]
    if tend_btc is not None:
        contra = "BAJISTA" if largo else "ALCISTA"
        items.append((tend_btc != contra, f"BTC 1H no está en contra ({tend_btc})"))
    senal = _armar(m, direccion, sub, desc, titulos, items, m["c"], m["c"], 0.5 * m["atr"])
    senal["sl_pct"] = 1.5
    senal["tp_pct"] = 3.0
    senal["salida"] = "Cruce contrario, stop -1,5% o meta +3%"
    return senal


def _retest(velas, direccion, tend4h, tend_btc, m_actual):
    """Rompimiento reciente (hasta 6 velas atrás) + regreso al nivel que rebota.
    Es la entrada de mejor calidad: stop corto y nivel ya validado."""
    largo = direccion == "LONG"
    a = np.asarray(velas, dtype=float)
    for k in range(2, 8):
        sub = velas[: len(velas) - k + 1]
        mk = _metricas(sub)
        if mk is None:
            continue
        rup = _ruptura(mk, direccion, tend4h, tend_btc)
        if rup is None:
            continue
        nivel = rup["nivel"]
        atr_val = m_actual["atr"]
        tol = TOL_TOQUE_ATR * atr_val
        despues = a[len(velas) - k + 1:]  # velas posteriores al rompimiento, incluida la actual
        if len(despues) == 0:
            continue
        if largo:
            mantuvo = bool((despues[:, 4] > nivel - tol).all())
            toco = m_actual["l"] <= nivel + tol and m_actual["l"] >= nivel - 0.5 * atr_val
            rebote = m_actual["c"] > nivel and m_actual["c"] > m_actual["o"]
        else:
            mantuvo = bool((despues[:, 4] < nivel + tol).all())
            toco = m_actual["h"] >= nivel - tol and m_actual["h"] <= nivel + 0.5 * atr_val
            rebote = m_actual["c"] < nivel and m_actual["c"] < m_actual["o"]
        if not (mantuvo and toco and rebote):
            continue
        items = list(rup["checklist"]) + [(True, f"Retest del nivel y rebote (rompimiento hace {k-1} vela(s))")]
        items = [(ok, txt) for ok, txt in items]
        puntos = sum(1 for ok, _ in items if ok)
        total = len(items)
        veredicto = _veredicto(puntos, total)
        sl_pct, tp_pct = plan_riesgo(direccion, m_actual["c"], nivel, 0.5 * atr_val)
        titulos = {"VERDADERO": "RETEST CONFIRMADO ✅", "PROBABLE": "RETEST PROBABLE ⚠️",
                   "DEBIL": "RETEST DÉBIL ❌ (no operar)"}
        res = dict(rup)
        res.update({
            "subtipo": "RETEST_RESISTENCIA" if largo else "RETEST_SOPORTE",
            "descripcion": ("Retest de resistencia rota (ahora soporte) con rebote" if largo
                            else "Retest de soporte roto (ahora resistencia) con rechazo"),
            "titulo": titulos[veredicto], "veredicto": veredicto,
            "puntos": puntos, "total": total, "checklist": [(bool(ok), t) for ok, t in items],
            "precio": m_actual["c"], "ts": m_actual["ts"], "atr": atr_val,
            "sl_pct": sl_pct, "tp_pct": tp_pct,
            "rsi": round(m_actual["rsi"], 1), "adx": round(m_actual["adx"], 1),
            "vol_rel": round(m_actual["vol_rel"], 2),
            "ema20": m_actual["ema20"], "ema50": m_actual["ema50"], "ema200": m_actual["ema200"],
            "resistencia": m_actual["res"], "soporte": m_actual["sop"],
        })
        return res
    return None


def evaluar(simbolo, v1h, v4h=None, vbtc=None):
    """Evalúa la última vela CERRADA de 1H. Devuelve una lista de señales (puede estar
    vacía), de mayor a menor calidad. v4h y vbtc son opcionales (velas cerradas)."""
    m = _metricas(v1h)
    if m is None:
        return []
    tend4h = tendencia([x[4] for x in v4h]) if v4h else "NEUTRAL"
    tend_btc = None
    if vbtc and simbolo != "BTC":
        tend_btc = tendencia([x[4] for x in vbtc])
    señales = []
    for direccion in ("LONG", "SHORT"):
        r = _retest(v1h, direccion, tend4h, tend_btc, m)
        if r is not None:
            señales.append(r)
        else:
            r = _ruptura(m, direccion, tend4h, tend_btc)
            if r is not None:
                señales.append(r)
        t = _trampa(m, direccion, tend4h, tend_btc)
        if t is not None and t["veredicto"] != "DEBIL":
            señales.append(t)
        c = _cruce_ema_rsi([x[4] for x in v1h], m, direccion, tend4h, tend_btc)
        if c is not None:
            señales.append(c)
    for s in señales:
        s["simbolo"] = simbolo
        s["tendencia_1h"] = m["tend1h"]
        s["tendencia_4h"] = tend4h
        s["tendencia_btc"] = tend_btc
    señales.sort(key=lambda s: (_RANGO[s["veredicto"]], s["puntos"] / s["total"]), reverse=True)
    return señales



# ----------------------------------------------------------------------------
# Tamaño de la posición
# ----------------------------------------------------------------------------
def dimensionar_contratos(margen_usdt, apalancamiento, precio, tamano_contrato,
                          min_contratos=1.0, tope_margen=5.0):
    """Convierte margen x apalancamiento en contratos (MEXC opera en contratos, no en monedas).
    Devuelve (contratos, mensaje_error). Si el margen no alcanza para el mínimo de 1 contrato,
    se permite subirlo hasta 1.5x del margen pedido (y nunca más que el tope)."""
    if precio <= 0 or tamano_contrato <= 0 or apalancamiento <= 0:
        return 0.0, "Datos inválidos para calcular el tamaño."
    exactos = (margen_usdt * apalancamiento) / (precio * tamano_contrato)
    if exactos >= min_contratos:
        return exactos, None
    margen_necesario = min_contratos * precio * tamano_contrato / apalancamiento
    if margen_necesario <= min(tope_margen, margen_usdt * 1.5):
        return float(min_contratos), None
    return 0.0, (f"Con ${margen_usdt:.2f} a {apalancamiento}x no alcanza para el mínimo de "
                 f"{min_contratos:g} contrato (necesitas ≈ ${margen_necesario:.2f} de margen).")


def pnl_estimado(lado, entrada, salida, margen, apalancamiento):
    """(% de precio, USDT) estimado antes de comisiones."""
    if entrada <= 0:
        return 0.0, 0.0
    pct = (salida - entrada) / entrada * 100.0 if lado == "buy" else (entrada - salida) / entrada * 100.0
    return pct, margen * apalancamiento * pct / 100.0



# ----------------------------------------------------------------------------
# Gestión de la posición: stop que sigue al precio
# ----------------------------------------------------------------------------
def nueva_posicion(lado, entrada, sl, tp=None):
    """lado: 'buy' (long) o 'sell' (short)."""
    return {"lado": lado, "entrada": float(entrada), "riesgo": abs(float(entrada) - float(sl)),
            "sl_inicial": float(sl), "sl": float(sl), "tp": tp, "mejor": float(entrada)}


def avanzar_posicion(pos, precio):
    """Actualiza la posición con el último precio. Devuelve (accion, motivo):
      'CERRAR'   -> el precio tocó el stop vigente
      'SUBIR_SL' -> el stop se movió a favor (long: sube, short: baja)
      'MANTENER' -> sin cambios
    Regla: el stop siempre queda a una distancia igual al riesgo inicial detrás del
    mejor precio alcanzado, solo avanza (nunca retrocede) y, al ganar 1x el riesgo,
    protege la entrada (+ comisión)."""
    largo = pos["lado"] == "buy"
    riesgo = pos["riesgo"]
    if riesgo <= 0:
        return "MANTENER", ""
    if (largo and precio <= pos["sl"]) or ((not largo) and precio >= pos["sl"]):
        if abs(pos["sl"] - pos["sl_inicial"]) < 1e-12:
            return "CERRAR", "STOP LOSS"
        protegido = pos["sl"] >= pos["entrada"] if largo else pos["sl"] <= pos["entrada"]
        return "CERRAR", "TRAILING STOP (ganancia protegida)" if protegido else "STOP AJUSTADO"
    if largo:
        pos["mejor"] = max(pos["mejor"], precio)
        candidato = pos["mejor"] - riesgo
        if pos["mejor"] >= pos["entrada"] + riesgo:
            candidato = max(candidato, pos["entrada"] * (1 + COLCHON_COMISION))
        if candidato > pos["sl"] + 0.05 * riesgo:
            pos["sl"] = candidato
            return "SUBIR_SL", ""
    else:
        pos["mejor"] = min(pos["mejor"], precio)
        candidato = pos["mejor"] + riesgo
        if pos["mejor"] <= pos["entrada"] - riesgo:
            candidato = min(candidato, pos["entrada"] * (1 - COLCHON_COMISION))
        if candidato < pos["sl"] - 0.05 * riesgo:
            pos["sl"] = candidato
            return "SUBIR_SL", ""
    return "MANTENER", ""
