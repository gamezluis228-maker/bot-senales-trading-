"""Pruebas de avisos.py.  Ejecutar: python3 tests/test_avisos.py"""
import os
import sys
import tempfile

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import avisos as A  # noqa: E402

ok = fails = 0


def check(n, c):
    global ok, fails
    print(("PASS " if c else "FAIL ") + n)
    ok += bool(c)
    fails += (not c)


def velas(cierres, tf_ms, ruido=0.002, seed=1):
    r = np.random.default_rng(seed)
    out, prev = [], cierres[0]
    for i, c in enumerate(cierres):
        o = prev
        h = max(o, c) * (1 + abs(r.normal(0, ruido)))
        l = min(o, c) * (1 - abs(r.normal(0, ruido)))
        out.append([i * tf_ms, o, h, l, c, 100.0])
        prev = c
    return out


def escenario(largo=True, rebote=True):
    s = 1 if largo else -1
    n1 = 300
    c1 = list(3000 * (1 + s * 0.0015) ** np.arange(n1))
    v1h = velas(c1, 3600000)
    v4h = velas(list(3000 * (1 + s * 0.005) ** np.arange(120)), 14400000)
    vbtc = velas(list(60000 * (1 + s * 0.001) ** np.arange(120)), 3600000)
    base = c1[-1]
    # 15m: tendencia, retroceso suave y vela final de rebote
    c15 = list(base * (1 + s * 0.0006) ** np.arange(-60, 0))
    pasos = [-s * 0.0015] * 4
    for p in pasos:
        c15.append(c15[-1] * (1 + p))
    v15 = velas(c15, 900000, ruido=0.0004)
    ult = v15[-1][4]
    if rebote:
        v15.append([v15[-1][0] + 900000, ult, ult * (1 + s * 0.0030), ult * (1 - s * 0.0003), ult * (1 + s * 0.0028), 100.0])
    else:
        v15.append([v15[-1][0] + 900000, ult, ult * 1.0003, ult * 0.9985, ult * (1 - s * 0.0010), 100.0])
    return v15, v1h, v4h, vbtc


# --- sensibilidad ---------------------------------------------------------------------------------
check("estricta: solo VERDADERO", A.pasa_filtro("VERDADERO", "estricta") and not A.pasa_filtro("PROBABLE", "estricta"))
check("normal: VERDADERO y PROBABLE", A.pasa_filtro("PROBABLE", "normal") and A.pasa_filtro("VERDADERO", "normal"))
check("DEBIL nunca se avisa", not A.pasa_filtro("DEBIL", "normal") and not A.pasa_filtro("DEBIL", "estricta"))
check("tope de avisos por día", A.cupo_disponible(A.MAX_AVISOS_DIA - 1) and not A.cupo_disponible(A.MAX_AVISOS_DIA))
check("espera entre avisos repetidos", A.puede_repetir(None, 100) and not A.puede_repetir(100, 200) and A.puede_repetir(100, 100 + A.ESPERA_ZONA_SEG))

# --- zona de entrada -----------------------------------------------------------------------------
for largo in (True, False):
    nombre = "LONG" if largo else "SHORT"
    v15, v1h, v4h, vbtc = escenario(largo)
    r = A.evaluar_zona("ETH", v15, v1h, v4h, vbtc)
    check(f"{nombre}: detecta zona con rebote y tendencia alineada", len(r) == 1 and r[0]["veredicto"] == "VERDADERO"
          and r[0]["tipo"] == ("COMPRA" if largo else "VENTA"))
    s = r[0] if r else {}
    check(f"{nombre}: trae SL/TP, checklist y campos que usa el mensaje del bot",
          s and 0.6 <= s["sl_pct"] <= 2.0 and s["tp_pct"] > s["sl_pct"] and len(s["checklist"]) == s["total"]
          and all(k in s for k in ("emoji", "titulo", "descripcion", "precio", "nivel", "puntos", "ema20", "ema50", "ema200", "rsi", "adx", "tendencia_4h", "ts", "subtipo")))
    v15b, *_ = escenario(largo, rebote=False)
    rb = A.evaluar_zona("ETH", v15b, v1h, v4h, vbtc)
    check(f"{nombre}: sin vela de rebote NO es punto de entrada", rb and rb[0]["veredicto"] == "DEBIL")
    contra = vbtc if False else escenario(not largo)[3]
    rc = A.evaluar_zona("ETH", v15, v1h, v4h, contra)
    check(f"{nombre}: BTC en contra baja la puntuación", rc and rc[0]["puntos"] < s["puntos"])
    r4 = A.evaluar_zona("ETH", v15, v1h, escenario(not largo)[2], vbtc)
    check(f"{nombre}: 4H en contra baja la puntuación", r4 and r4[0]["puntos"] < s["puntos"])

check("datos insuficientes => []", A.evaluar_zona("ETH", [], [], None, None) == [])
plano = velas([3000.0] * 300, 3600000, ruido=0.0)
check("mercado sin tendencia => []", A.evaluar_zona("ETH", velas([3000.0] * 80, 900000, 0.0), plano, None, None) == [])
txt = A.resumen_mercado("ETH", 3000, A.evaluar_zona("ETH", *escenario(True)))
check("/mercado muestra el estado", "PUNTO DE ENTRADA" in txt)
check("/mercado sin tendencia lo dice", "sin tendencia" in A.resumen_mercado("ZEC", 50.0, []))

# --- configuración y vigilancias ------------------------------------------------------------------
tmp = os.path.join(tempfile.mkdtemp(), "cfg.json")
A.reiniciar_config()
check("por defecto: activo y estricta", A.config()["activo"] and A.config()["sensibilidad"] == "estricta")
check("sensibilidad inválida se rechaza", not A.poner_sensibilidad("loca", tmp) and A.config()["sensibilidad"] == "estricta")
A.poner_sensibilidad("normal", tmp)
A.poner_activo(False, tmp)
A.agregar_vigilancia("eth", 3100, 3000, tmp)
A.reiniciar_config()
A.cargar(tmp)
c = A.config()
check("la configuración se guarda y se recupera", c["sensibilidad"] == "normal" and c["activo"] is False and c["vigilancias"][0]["coin"] == "ETH")
check("vigilancia hacia arriba", c["vigilancias"][0]["lado"] == "arriba")
check("nivel pegado al precio se rechaza", not A.agregar_vigilancia("ETH", 3000.5, 3000, tmp)[0])
A.agregar_vigilancia("ZEC", 40, 45, tmp)
check("no se cumple si el precio no cruza", A.revisar_vigilancias({"ETH": 3050, "ZEC": 41}, tmp) == [])
hit = A.revisar_vigilancias({"ETH": 3101, "ZEC": 41}, tmp)
check("se cumple al cruzar y se elimina (ETH sube a 3101)", len(hit) == 1 and hit[0]["coin"] == "ETH" and len(A.config()["vigilancias"]) == 1)
hit = A.revisar_vigilancias({"ZEC": 39.9}, tmp)
check("vigilancia hacia abajo (ZEC cae a 39.9)", len(hit) == 1 and hit[0]["coin"] == "ZEC" and A.config()["vigilancias"] == [])
for i in range(A.MAX_VIGILANCIAS):
    A.agregar_vigilancia("ETH", 3100 + i * 10, 3000, tmp)
check("tope de vigilancias", not A.agregar_vigilancia("ETH", 4000, 3000, tmp)[0])
check("borrar por moneda", A.borrar_vigilancias("ETH", tmp) == A.MAX_VIGILANCIAS and A.config()["vigilancias"] == [])
open(tmp, "w").write("{roto")
A.reiniciar_config()
A.cargar(tmp)
check("archivo dañado: se usan los valores por defecto", A.config()["sensibilidad"] == "estricta")


def velas_vol(cierres, tf_ms, seed=3, ruido=0.002, alto=6):
    r = np.random.default_rng(seed)
    out, prev = [], cierres[0]
    for i, c in enumerate(cierres):
        o = prev
        h = max(o, c) * (1 + abs(r.normal(0, ruido)))
        l = min(o, c) * (1 - abs(r.normal(0, ruido)))
        out.append([i * tf_ms, o, h, l, c, 100.0 * (2.5 if i >= len(cierres) - alto else 1)])
        prev = c
    return out


def escenario_mov(sig, paso=0.0105):
    """sig=-1: caída fuerte tras una subida lenta (las EMAs 1H/4H aún no giran). sig=+1: subida fuerte."""
    base = list(2500 * (1 + 0.0008 * (-sig)) ** np.arange(294))
    c1 = base + [base[-1] * (1 + sig * paso * k) for k in range(1, 7)]
    c15 = list(np.linspace(c1[-7], c1[-1], 60))
    c15 += [c15[-1] * (1 + sig * 0.0015 * k) for k in range(1, 5)]
    return (velas_vol(c15, 900000, 5, 0.0006), velas_vol(c1, 3600000), velas(list(2500 * (1.003) ** np.arange(120)), 14400000))


# --- movimiento fuerte ---------------------------------------------------------------------------------------
import senales  # noqa: E402
v15, v1, v4 = escenario_mov(-1)
check("caso real: en una caída fuerte la tendencia 1H aún dice NEUTRAL (por eso fallaba el aviso)", senales.tendencia([x[4] for x in v1]) == "NEUTRAL")
check("...y el filtro de retroceso no ve nada", A.evaluar_zona("ETH", v15, v1, v4, None) == [])
r = A.evaluar_movimiento("ETH", v15, v1, v4, None)
check("caída fuerte => oportunidad de VENTA verdadera", len(r) == 1 and r[0]["tipo"] == "VENTA" and r[0]["veredicto"] == "VERDADERO")
s = r[0]
check("trae stop corto, TP, checklist y campos del mensaje", 0.6 <= s["sl_pct"] <= 2.0 and s["tp_pct"] > s["sl_pct"] and s["subtipo"] == "movimiento"
      and all(k in s for k in ("emoji", "titulo", "descripcion", "precio", "nivel", "puntos", "ema20", "ema50", "ema200", "rsi", "adx", "tendencia_4h", "ts")))
check("el título habla de mercado cayendo", "CAYENDO" in s["titulo"] and "VENTA" in s["titulo"])
v15u, v1u, v4u = escenario_mov(1)
ru = A.evaluar_movimiento("ETH", v15u, v1u, v4u, None)
check("subida fuerte => oportunidad de COMPRA", len(ru) == 1 and ru[0]["tipo"] == "COMPRA" and ru[0]["veredicto"] == "VERDADERO")
v15s, v1s, v4s = escenario_mov(-1, paso=0.0006)
check("movimiento pequeño (<1.5x el rango normal) => nada", A.evaluar_movimiento("ETH", v15s, v1s, v4s, None) == [])
btc_sube = velas(list(60000 * (1.001) ** np.arange(120)), 3600000)
rb = A.evaluar_movimiento("ETH", v15, v1, v4, btc_sube)
check("BTC subiendo en contra de la caída baja la puntuación", rb and rb[0]["puntos"] < s["puntos"])
v15r = [list(x) for x in v15]; v15r[-1] = [v15r[-1][0], v15r[-1][1], v15r[-1][1] * 1.02, v15r[-1][3], v15r[-1][1] * 1.015, 100.0]
rr = A.evaluar_movimiento("ETH", v15r, v1, v4, None)
check("si ya hay un rebote fuerte, no es VERDADERO", rr and rr[0]["veredicto"] != "VERDADERO")
check("datos insuficientes => []", A.evaluar_movimiento("ETH", [], [], None, None) == [])
check("/mercado muestra el movimiento fuerte", "🔥 ETH" in A.resumen_movimiento("ETH", r) and A.resumen_movimiento("ETH", []) is None)

# --- alerta corta ---------------------------------------------------------------------------------------------
ta = A.texto_alerta("ETH", s)
check("la alerta dice qué hacer, entrada, stop y meta", ta.startswith("🔴 VENTA ETH") and "Entrada ≈" in ta and "Stop $" in ta and "Meta $" in ta and "Fuerza: FUERTE" in ta)
check("en una venta el stop queda por encima y la meta por debajo", float(ta.split("Stop $")[1].split(" ")[0].replace(",", "")) > s["precio"] > float(ta.split("Meta $")[1].split()[0].replace(",", "")))
check("la alerta es corta (máx. 7 líneas)", len(ta.splitlines()) <= 7)
check("añade la línea de BTC solo si BTC va en el mismo sentido", "👑 BTC también va a la baja" in A.texto_alerta("ETH", s, "VENTA") and "👑" not in A.texto_alerta("ETH", s, "COMPRA") and "👑" not in A.texto_alerta("BTC", s, "VENTA"))

# --- rupturas en 15m ---------------------------------------------------------------------------------------------
def _rango_y_ruptura(sig):
    """100 velas de 15m en rango (techo/piso tocados varias veces) y una vela final que rompe con fuerza y volumen."""
    r = np.random.default_rng(9); v = []
    for i in range(100):
        mid = 100.0 + 0.4 * np.sin(i / 3.0)
        o = mid - 0.1; c = mid + 0.1
        v.append([i * 900000, o, min(100.5, mid + 0.35), max(99.5, mid - 0.35), c, 100.0])
    ult = v[-1][4]
    if sig > 0:
        v.append([100 * 900000, 100.3, 101.7, 100.25, 101.6, 400.0])
    else:
        v.append([100 * 900000, 99.7, 99.75, 98.3, 98.4, 400.0])
    return v


for sg, tipo in ((1, "COMPRA"), (-1, "VENTA")):
    c15 = _rango_y_ruptura(sg)
    c1 = velas(list(100 * (1 + 0.001 * sg) ** np.arange(120)), 3600000)
    res = A.rupturas_15m("ETH", c15, c1, None)
    rr_ = [x for x in res if x["subtipo"].startswith("ROMPIMIENTO")]
    check(f"ruptura en 15m ({tipo}): se detecta con la vela cerrada de 15m", rr_ and rr_[0]["tipo"] == tipo and rr_[0]["tf"] == "15m")
    check(f"({tipo}) el título y la tendencia quedan etiquetados en 15m/1H",
          rr_ and rr_[0]["titulo"].endswith("(15m)") and any("Tendencia 15m" in t_ for _, t_ in rr_[0]["checklist"]) and not any("Tendencia 4H" in t_ for _, t_ in rr_[0]["checklist"]))
check("sin datos suficientes => []", A.rupturas_15m("ETH", [], [], None) == [])
check("encabezados según el tipo de señal", A.encabezado({"subtipo": "zona"}).startswith("📍") and A.encabezado({"subtipo": "movimiento"}).startswith("🔥")
      and "FALSO" in A.encabezado({"subtipo": "FALSO_ROMPIMIENTO_SOPORTE"}) and "RETEST" in A.encabezado({"subtipo": "RETEST_SOPORTE"})
      and "ROMPIMIENTO" in A.encabezado({"subtipo": "ROMPIMIENTO_RESISTENCIA"}))

print(f"\n{ok} OK, {fails} fallos")
sys.exit(1 if fails else 0)
