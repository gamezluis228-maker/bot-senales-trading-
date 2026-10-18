"""Lógica pura para vigilar posiciones abiertas, también las que abres a mano (sin red ni Telegram).

Se prueba con datos simulados:  python3 tests/test_posiciones.py
"""
import math

import numpy as np

import indicadores as ind
import senales

ESCALON_PNL_PCT = 10.0          # avisa cada 10 % de ganancia/pérdida sobre el MARGEN
MIN_SEG_ENTRE_AVISOS = 180      # no más de un aviso de movimiento cada 3 min por posición
SEG_ENTRE_SUGERENCIAS = 1800    # no repetir una sugerencia de salida antes de 30 min
GANANCIA_MIN_EMA_PCT = 0.5      # el cruce de EMAs solo cuenta si ya vas ganando 0.5 % de precio
GANANCIA_MIN_RSI_PCT = 1.0      # el agotamiento del RSI solo cuenta si ya vas ganando 1 %
RSI_AGOTADO_LONG = 75
RSI_AGOTADO_SHORT = 25
EXTRA_STOP_DURO_PCT = 0.5       # el stop de emergencia (en MEXC) queda 0.5 % más lejos que el stop normal
CONSULTA_ESPERA_SEG = 180       # tiempo que el bot espera tu respuesta cuando el precio toca el stop
SEPARACION_MIN_ASEGURAR_PCT = 0.1   # el precio debe estar 0.1 % más allá del nuevo stop


def fmt_precio(x):
    try:
        x = float(x)
    except (TypeError, ValueError):
        return str(x)
    return f"{x:,.2f}" if abs(x) >= 1 else f"{x:.6f}"


def coin_de_simbolo(simbolo):
    return (simbolo or "").split("/")[0]


def lado_orden(lado_posicion):
    """'long' -> 'buy', 'short' -> 'sell' (como lo usa el resto del bot)."""
    return "buy" if lado_posicion == "long" else "sell"


def parsear_posicion(p):
    """Convierte una posición de ccxt en un dict simple; None si no hay contratos abiertos."""
    contratos = abs(float(p.get("contracts") or 0))
    if contratos <= 0:
        return None
    simbolo = p.get("symbol") or ""
    info = p.get("info") or {}
    liq = p.get("liquidationPrice")
    return {
        "coin": coin_de_simbolo(simbolo),
        "market_symbol": simbolo,
        "contratos": contratos,
        "lado": p.get("side"),                      # 'long' / 'short'
        "entrada": float(p.get("entryPrice") or 0),
        "apalancamiento": float(p.get("leverage") or 0),
        "margen": float(p.get("initialMargin") or p.get("collateral") or 0),
        "open_type": {"isolated": 1, "cross": 2}.get(p.get("marginMode")),   # None si no se sabe
        "position_id": info.get("positionId"),
        "liquidacion": float(liq) if liq else None,
    }


def variacion(lado, entrada, precio, margen, apalancamiento):
    """lado: 'buy'/'sell'. Devuelve % de precio, % sobre el margen y USDT estimados (sin comisiones)."""
    pct, pnl = senales.pnl_estimado(lado, entrada, precio, margen, apalancamiento)
    return {"pct_precio": pct, "pct_margen": pct * apalancamiento, "pnl_usdt": pnl}


def crear_posicion_adoptada(lado, entrada, precio, sl_pct, modo="trailing"):
    """Estado de gestión para una posición que el bot no abrió.
    Si el precio YA está más allá del stop por defecto (posición muy en contra), el stop se coloca
    a sl_pct del precio ACTUAL en vez de cerrarla de golpe: nunca cierra solo por haberla adoptado.
    Devuelve (pos, nota) con nota=None si no hubo ajuste."""
    f = sl_pct / 100.0
    largo = lado == "buy"
    sl = entrada * (1 - f) if largo else entrada * (1 + f)
    ya_pasado = precio <= sl if largo else precio >= sl
    nota = None
    if ya_pasado:
        sl = precio * (1 - f) if largo else precio * (1 + f)
        nota = ("Tu posición ya estaba más allá del stop habitual; puse el stop a "
                f"{sl_pct}% del precio ACTUAL para no cerrarla de golpe.")
    pos = senales.nueva_posicion(lado, entrada, sl, None)
    pos["riesgo"] = entrada * f          # distancia del trailing: siempre sl_pct de la entrada
    pos["mejor"] = float(precio)         # el trailing arranca desde el precio de hoy
    pos["modo"] = modo
    pos["adoptada"] = True
    return pos, nota


def asegurar_entrada(pos, precio):
    """Mueve el stop a tu precio de entrada (+ colchón de comisión). Devuelve (ok, mensaje)."""
    largo = pos["lado"] == "buy"
    objetivo = pos["entrada"] * (1 + senales.COLCHON_COMISION) if largo else pos["entrada"] * (1 - senales.COLCHON_COMISION)
    if (largo and pos["sl"] >= objetivo) or ((not largo) and pos["sl"] <= objetivo):
        return False, "Tu stop ya está en la entrada o mejor."
    sep = (precio - objetivo) / precio * 100 if largo else (objetivo - precio) / precio * 100
    if sep < SEPARACION_MIN_ASEGURAR_PCT:
        return False, ("Todavía no estás en ganancia suficiente: con el precio tan cerca de tu entrada "
                       "el stop se activaría de inmediato.")
    pos["sl"] = objetivo
    pos["sl_notificado"] = objetivo
    return True, f"Stop movido a ${fmt_precio(objetivo)} (tu entrada + comisión). Ya no puedes perder en esta operación."


def escalon_nuevo(pct_margen, ultimo):
    """Escalón actual (en pasos de ESCALON_PNL_PCT, truncado hacia 0). Devuelve el escalón si cambió, si no None."""
    actual = int(pct_margen / ESCALON_PNL_PCT)
    return actual if actual != ultimo else None


def sugerir_salida(lado, ganancia_pct, rsi15, ema9, ema21, senal_contraria):
    """Motivos (lista de textos) por los que podría convenir cerrar. Solo SUGIERE; decide el usuario.
    lado: 'buy'/'sell'. senal_contraria: dict de senales.evaluar en la dirección opuesta, o None."""
    largo = lado == "buy"
    motivos = []
    if senal_contraria:
        motivos.append(f"Señal contraria ({senal_contraria.get('veredicto', '?')}): {senal_contraria.get('titulo', 'cambio de dirección')}")
    if ganancia_pct >= GANANCIA_MIN_EMA_PCT and ema9 is not None and ema21 is not None:
        if (largo and ema9 < ema21) or ((not largo) and ema9 > ema21):
            motivos.append("Las EMAs 9/21 (15m) giraron en contra mientras vas ganando")
    if ganancia_pct >= GANANCIA_MIN_RSI_PCT and rsi15 is not None:
        if (largo and rsi15 >= RSI_AGOTADO_LONG) or ((not largo) and rsi15 <= RSI_AGOTADO_SHORT):
            motivos.append(f"RSI (15m) en {rsi15:.0f}: el movimiento puede estar agotado")
    return motivos


def texto_posicion(coin, pos, precio, margen, apalancamiento, liquidacion=None, gestionada=True):
    """Resumen legible de una posición (texto plano)."""
    largo = pos["lado"] == "buy"
    v = variacion(pos["lado"], pos["entrada"], precio, margen, apalancamiento)
    signo = "🟢" if v["pnl_usdt"] >= 0 else "🔴"
    L = [f"{'📈' if largo else '📉'} {coin} {'LONG 🟢' if largo else 'SHORT 🔴'} | {apalancamiento:g}x | margen ${margen:.2f}",
         f"💵 Entrada: ${fmt_precio(pos['entrada'])} | Precio ahora: ${fmt_precio(precio)}",
         f"{signo} Variación: {v['pct_precio']:+.2f}% del precio = {v['pct_margen']:+.1f}% de tu margen (≈ ${v['pnl_usdt']:+.2f}, antes de comisiones)"]
    if gestionada:
        modo = pos.get("modo", "trailing")
        if modo == "vigilar":
            L.append("👀 Modo: solo vigilar (el bot NO cierra nada por su cuenta)")
        else:
            protegido = pos["sl"] >= pos["entrada"] if largo else pos["sl"] <= pos["entrada"]
            dist = abs(precio - pos["sl"]) / precio * 100
            L.append(f"🛑 Stop del bot: ${fmt_precio(pos['sl'])} ({'ganancia protegida ✅' if protegido else 'protege contra pérdida'}; a {dist:.2f}% del precio)")
            if pos.get("adoptada"):
                L.append("ℹ️ Ese stop lo vigila el bot, no está puesto en MEXC: si el bot se cae, no actúa.")
    else:
        L.append("⚪ El bot NO la está gestionando todavía.")
    if liquidacion:
        d = abs(precio - liquidacion) / precio * 100
        L.append(f"⚠️ Liquidación ≈ ${fmt_precio(liquidacion)} (a {d:.2f}% del precio)")
    return "\n".join(L)


# --- Consulta al tocar el stop ------------------------------------------------------------------------
def rasgos_stop(lado, v15, v1h, v4h=None, vbtc=None):
    """Datos objetivos para decidir si el golpe al stop es un cambio real de tendencia o solo un respiro.
    Velas cerradas [ts, o, h, l, c, v]. Devuelve None si faltan datos."""
    if len(v15) < 30 or len(v1h) < 55:
        return None
    largo = lado == "buy"
    a = np.asarray(v15, dtype=float)
    c = a[:, 4]
    o, h, l, cl, vol = a[-1, 1], a[-1, 2], a[-1, 3], a[-1, 4], a[-1, 5]
    rango = (h - l) or 1e-12
    vol_prom = float(a[-21:-1, 5].mean())
    c1 = [x[4] for x in v1h]
    mecha_favor = (min(o, cl) - l) / rango if largo else (h - max(o, cl)) / rango
    return {
        "largo": largo, "precio": float(cl),
        "ema9": ind.ultima_ema(c, 9), "ema21": ind.ultima_ema(c, 21), "rsi15": ind.rsi(c, 14),
        "vol_rel": float(vol / vol_prom) if vol_prom > 0 else 1.0,
        "cuerpo_contra": bool(cl < o) if largo else bool(cl > o),
        "mecha_rechazo": float(mecha_favor),
        "tend1h": senales.tendencia(c1),
        "tend4h": senales.tendencia([x[4] for x in v4h]) if v4h else "NEUTRAL",
        "tend_btc": senales.tendencia([x[4] for x in vbtc]) if vbtc else None,
        "ema50_1h": ind.ultima_ema(c1, 50),
    }


def diagnostico_stop(lado, r):
    """Pesa evidencia EN CONTRA (cambio real) vs A FAVOR del respiro. Devuelve dict con recomendacion
    ('CERRAR' / 'MANTENER' / 'DUDA'), contra, respiro y score. Es una estimación, no una garantía:
    con 20x ante la duda se recomienda cerrar."""
    largo = lado == "buy"
    mal, bien = [], []
    if (largo and r["ema9"] < r["ema21"]) or ((not largo) and r["ema9"] > r["ema21"]):
        mal.append("EMAs 9/21 (15m) apuntan en contra")
    adverso = "BAJISTA" if largo else "ALCISTA"
    favor = "ALCISTA" if largo else "BAJISTA"
    if r["tend1h"] == adverso:
        mal.append("Tendencia 1H en contra de tu posición")
    elif r["tend1h"] == favor:
        bien.append("La tendencia 1H sigue a tu favor")
    if r["tend4h"] == adverso:
        mal.append("Tendencia 4H en contra")
    if r["tend_btc"] == adverso:
        mal.append("BTC se mueve en contra")
    if r["cuerpo_contra"] and r["vol_rel"] >= 1.5:
        mal.append(f"Vela 15m en contra con volumen alto (x{r['vol_rel']:.1f}): empuje real")
    if (largo and r["precio"] < r["ema50_1h"]) or ((not largo) and r["precio"] > r["ema50_1h"]):
        mal.append("El precio perdió la EMA 50 (1H)")
    if r["mecha_rechazo"] >= 0.5:
        bien.append("Mecha larga de rechazo en la última vela 15m")
    if (largo and r["rsi15"] <= 30) or ((not largo) and r["rsi15"] >= 70):
        bien.append(f"RSI 15m en {r['rsi15']:.0f}: movimiento estirado, posible rebote")
    if r["cuerpo_contra"] and r["vol_rel"] < 1.0:
        bien.append("El empujón en contra viene con poco volumen")
    score = len(mal) - len(bien)
    rec = "CERRAR" if score >= 2 else ("MANTENER" if score <= -2 else "DUDA")
    return {"recomendacion": rec, "contra": mal, "respiro": bien, "score": score}


def texto_consulta(coin, pos, precio, diag, sl_duro, motivo, gestion_en_mexc=True):
    """Mensaje que se envía cuando el precio toca el stop: análisis y recomendación. No se ha cerrado nada."""
    rec = diag["recomendacion"]
    consejo = {"CERRAR": "💡 Recomiendo CERRAR: el mercado parece ir en serio en contra.",
               "MANTENER": "💡 Recomiendo MANTENER: parece un respiro, no un cambio de tendencia.",
               "DUDA": "💡 Sin señal clara: con 20x lo prudente es CERRAR para proteger tu capital."}[rec]
    L = [f"⚠️ {coin}: el precio tocó tu stop ({motivo}) en ${fmt_precio(pos['sl'])}.",
         "NO he cerrado nada: decide tú.", ""]
    L.append(texto_posicion(coin, pos, precio, pos["margen"], pos["apalancamiento"], pos.get("liquidacion")))
    L.append("")
    if diag.get("sin_datos"):
        L.append("No pude leer el mercado para analizarlo.")
    else:
        L.append("🔴 En contra: " + ("; ".join(diag["contra"]) if diag["contra"] else "nada relevante"))
        L.append("🟢 A favor del respiro: " + ("; ".join(diag["respiro"]) if diag["respiro"] else "nada relevante"))
    L += ["", consejo, "(Es una estimación, no una garantía.)", "",
          f"🛑 Si pulsas Mantener, el stop de emergencia queda en ${fmt_precio(sl_duro)}"
          + (" (también puesto en MEXC)." if gestion_en_mexc else "."),
          f"⏱️ Si no respondes en {CONSULTA_ESPERA_SEG // 60} min NO cierro nada: mantengo hasta el stop de emergencia "
          "(ese es tu límite de pérdida)."]
    return "\n".join(L)


def linea_activa(p, precio):
    """Una línea por operación abierta: moneda, lado, apalancamiento y variación actual."""
    lado = lado_orden(p["lado"])
    lev = p["apalancamiento"] or 1
    v = variacion(lado, p["entrada"], precio, p["margen"], lev)
    signo = "🟢" if v["pnl_usdt"] >= 0 else "🔴"
    return (f"{signo} {p['coin']} {'LONG' if lado == 'buy' else 'SHORT'} {lev:g}x · entrada ${fmt_precio(p['entrada'])} "
            f"· ahora ${fmt_precio(precio)} · {v['pct_margen']:+.1f}% del margen (≈ ${v['pnl_usdt']:+.2f})")


def texto_activas(lineas):
    """Encabezado con el conteo de operaciones activas + una línea por operación."""
    n = len(lineas)
    if n == 0:
        return "📭 Operaciones activas en MEXC Futuros: 0"
    return f"📌 Operaciones activas en MEXC Futuros: {n}\n" + "\n".join(f"• {x}" for x in lineas)


def texto_analisis(diag):
    """Resumen corto del mercado frente a TU posición (para /activas)."""
    sc = diag["score"]
    if sc >= 2:
        t = "🔴 El mercado va en contra de tu posición. Si sigue así, considera cerrar."
    elif sc <= -1:
        t = "🟢 El mercado se ve a tu favor: tiene sentido mantener."
    else:
        t = "🟡 Señales mixtas: mantén el stop a mano y vigila."
    extra = []
    if diag["contra"]:
        extra.append("En contra: " + "; ".join(diag["contra"][:3]))
    if diag["respiro"]:
        extra.append("A favor: " + "; ".join(diag["respiro"][:3]))
    return t + ("\n      " + "\n      ".join(extra) if extra else "")
