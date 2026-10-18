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

print(f"\n{ok} OK, {fails} fallos")
sys.exit(1 if fails else 0)
