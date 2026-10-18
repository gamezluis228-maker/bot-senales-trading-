"""Lógica pura para vigilar posiciones abiertas, también las que abres a mano (sin red ni Telegram).

Se prueba con datos simulados:  python3 tests/test_posiciones.py
"""
import math

import senales

ESCALON_PNL_PCT = 10.0          # avisa cada 10 % de ganancia/pérdida sobre el MARGEN
MIN_SEG_ENTRE_AVISOS = 180      # no más de un aviso de movimiento cada 3 min por posición
SEG_ENTRE_SUGERENCIAS = 1800    # no repetir una sugerencia de salida antes de 30 min
GANANCIA_MIN_EMA_PCT = 0.5      # el cruce de EMAs solo cuenta si ya vas ganando 0.5 % de precio
GANANCIA_MIN_RSI_PCT = 1.0      # el agotamiento del RSI solo cuenta si ya vas ganando 1 %
RSI_AGOTADO_LONG = 75
RSI_AGOTADO_SHORT = 25
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
