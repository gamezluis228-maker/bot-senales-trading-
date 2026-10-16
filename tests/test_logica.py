"""Pruebas de la lógica pura del bot (indicadores, señales, tamaño y trailing).

Se ejecutan sin red ni Telegram:  python3 tests/test_logica.py
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import indicadores as ind  # noqa: E402
import senales as s  # noqa: E402

HORA = 3_600_000
T0 = 1_700_000_000_000
ok_n = fallos = 0


def check(nombre, condicion):
    global ok_n, fallos
    print(("PASS " if condicion else "FAIL ") + nombre)
    ok_n += bool(condicion)
    fallos += (not condicion)


# ---------------------------------------------------------------- generadores
def velas_desde_cierres(cierres, seed=0, mecha=0.15, vol=1000.0):
    rng = np.random.default_rng(seed)
    out, prev = [], cierres[0]
    for i, c in enumerate(cierres):
        o = prev
        h = max(o, c) + rng.uniform(0, mecha)
        l = min(o, c) - rng.uniform(0, mecha)
        out.append([T0 + i * HORA, o, h, l, c, vol * rng.uniform(0.8, 1.2)])
        prev = c
    return out


def contexto_alcista(techo=100.0, seed=1):
    rng = np.random.default_rng(seed)
    tend = np.linspace(80, techo - 1.0, 250) + rng.normal(0, 0.25, 250)
    rango = techo - 1.0 + 0.6 * np.sin(np.arange(24) / 2.5) + rng.normal(0, 0.15, 24)
    return list(tend) + list(rango)


def con_vela(velas, o, h, l, c, v):
    return velas + [[velas[-1][0] + HORA, o, h, l, c, v]]


# ---------------------------------------------------------------- indicadores
rng = np.random.default_rng(7)
check("EMA de una serie constante es constante", abs(ind.ultima_ema([5.0] * 100, 20) - 5.0) < 1e-9)
check("RSI de una serie que solo sube = 100", ind.rsi(np.arange(1, 60)) == 100.0)
check("RSI de una serie que solo baja = 0", ind.rsi(np.arange(60, 1, -1)) == 0.0)
rsi_rec = ind.rsi(list(np.linspace(50, 60, 30)) + [60.0] * 5 + list(np.linspace(60, 70, 30)))
check("RSI usa las velas MÁS RECIENTES (sube al final => alto)", rsi_rec > 70)
check("ATR de rango constante = el rango",
      abs(ind.atr([11] * 60, [9] * 60, [10] * 60) - 2.0) < 1e-9)
t = np.linspace(100, 160, 120) + rng.normal(0, 0.3, 120)
r = ind.adx_serie(t + 0.5, t - 0.5, t)
check("ADX alto y +DI > -DI en tendencia fuerte", r["adx"][-1] > 40 and r["pdi"][-1] > r["mdi"][-1])
lado = 100 + np.sin(np.linspace(0, 30, 120)) * 2 + rng.normal(0, 0.3, 120)
r = ind.adx_serie(lado + 0.5, lado - 0.5, lado)
check("ADX bajo en mercado lateral", r["adx"][-1] < 25)
check("ADX sin datos suficientes = 0", ind.adx([1, 2, 3], [1, 2, 3], [1, 2, 3]) == 0.0)

# ---------------------------------------------------------------- velas cerradas
velas = [[T0, 1, 1, 1, 1, 1], [T0 + HORA, 1, 1, 1, 1, 1], [T0 + 2 * HORA, 1, 1, 1, 1, 1]]
check("solo_cerradas descarta la vela en curso",
      len(s.solo_cerradas(velas, HORA, T0 + 2 * HORA + 1000)) == 2)

# ---------------------------------------------------------------- señales
base = velas_desde_cierres(contexto_alcista())
check("sin ruptura no hay señales", s.evaluar("ETH", base) == [])

fuerte = con_vela(base, 99.8, 101.9, 99.7, 101.8, 3200)
res = s.evaluar("ETH", fuerte)
check("rompimiento fuerte: COMPRA por rompimiento de resistencia",
      len(res) >= 1 and res[0]["tipo"] == "COMPRA" and res[0]["subtipo"] == "ROMPIMIENTO_RESISTENCIA")
check("rompimiento fuerte no es DÉBIL y suma 5 puntos o más",
      res[0]["veredicto"] in ("VERDADERO", "PROBABLE") and res[0]["puntos"] >= 5)
check("el checklist reconoce el volumen alto", res[0]["checklist"][0][0] is True)
check("plan de riesgo: SL entre 0.6% y 2% y TP = 3 x SL",
      0.6 <= res[0]["sl_pct"] <= 2.0 and abs(res[0]["tp_pct"] - 3 * res[0]["sl_pct"]) < 0.02)

debil = con_vela(base, 99.8, 103.0, 99.7, 100.5, 900)
res = s.evaluar("ETH", debil)
check("rompimiento con poco volumen y mecha larga = DÉBIL",
      len(res) >= 1 and res[0]["veredicto"] == "DEBIL")

trampa = con_vela(base, 99.7, 101.8, 99.5, 99.6, 2000)
res = s.evaluar("ETH", trampa)
check("falso rompimiento de resistencia => VENTA (no DÉBIL)",
      len(res) >= 1 and res[0]["tipo"] == "VENTA" and res[0]["subtipo"] == "FALSO_ROMPIMIENTO_RESISTENCIA"
      and res[0]["veredicto"] != "DEBIL")

sig = con_vela(fuerte, 101.8, 102.4, 101.6, 102.2, 1600)
retest = con_vela(sig, 100.2, 101.4, 99.95, 101.2, 1500)
res = s.evaluar("ETH", retest)
check("retest con rebote => COMPRA RETEST_RESISTENCIA",
      len(res) >= 1 and res[0]["subtipo"] == "RETEST_RESISTENCIA" and res[0]["tipo"] == "COMPRA")
perdio = con_vela(sig, 102.1, 102.3, 99.2, 99.5, 1500)
check("si pierde el nivel no hay retest", all(x["subtipo"] != "RETEST_RESISTENCIA" for x in s.evaluar("ETH", perdio)))

rng2 = np.random.default_rng(3)
tend = np.linspace(120, 101.0, 250) + rng2.normal(0, 0.25, 250)
rango = 101.0 + 0.6 * np.sin(np.arange(24) / 2.5) + rng2.normal(0, 0.15, 24)
bajista = velas_desde_cierres(list(tend) + list(rango), seed=3)
res = s.evaluar("ZEC", con_vela(bajista, 100.3, 100.4, 98.2, 98.3, 3000))
check("rompimiento de soporte => VENTA", len(res) >= 1 and res[0]["tipo"] == "VENTA"
      and res[0]["subtipo"] == "ROMPIMIENTO_SOPORTE")

# ---------------------------------------------------------------- plan de riesgo
check("SL mínimo 0.6%", s.plan_riesgo("LONG", 100.0, 99.9, 0.01)[0] == 0.6)
check("SL máximo 2%", s.plan_riesgo("LONG", 100.0, 90.0, 0.5)[0] == 2.0)

# ---------------------------------------------------------------- tamaño en contratos
c, err = s.dimensionar_contratos(1.5, 20, 3000, 0.01)
check("ETH $3000, $1.50 a 20x = 1 contrato", err is None and abs(c - 1.0) < 1e-9)
c, err = s.dimensionar_contratos(1.5, 20, 3400, 0.01)
check("ETH $3400: sube a 1 contrato (margen ≈ $1.70)", err is None and c == 1.0)
c, err = s.dimensionar_contratos(1.5, 20, 5000, 0.01)
check("ETH $5000: se rechaza con mensaje claro", c == 0.0 and err and "necesitas" in err)
c, err = s.dimensionar_contratos(1.5, 20, 1220, 0.01)
check("ZEC $1220: 2.46 contratos exactos", err is None and abs(c - 30 / 12.2) < 1e-9)

# ---------------------------------------------------------------- trailing
p = s.nueva_posicion("buy", 100.0, 98.5)
check("riesgo inicial = distancia al SL", abs(p["riesgo"] - 1.5) < 1e-9)
check("precio cae al stop => CERRAR por STOP LOSS", s.avanzar_posicion(dict(p), 98.4) == ("CERRAR", "STOP LOSS"))
a, _ = s.avanzar_posicion(p, 100.5)
check("long: al subir el precio el stop sube", a == "SUBIR_SL" and abs(p["sl"] - 99.0) < 1e-9)
s.avanzar_posicion(p, 101.6)
check("long: con ganancia de 1R el stop protege la entrada", p["sl"] >= 100.0)
sl_prev = p["sl"]
a, _ = s.avanzar_posicion(p, 101.0)
check("el stop nunca retrocede", p["sl"] == sl_prev and a == "MANTENER")
a, motivo = s.avanzar_posicion(p, p["sl"] - 0.01)
check("al caer al stop protegido => TRAILING STOP", a == "CERRAR" and "TRAILING" in motivo)

ps = s.nueva_posicion("sell", 100.0, 101.5)
s.avanzar_posicion(ps, 99.4)
check("short: al bajar el precio el stop baja", ps["sl"] < 101.5)
s.avanzar_posicion(ps, 98.3)
check("short: con ganancia de 1R el stop protege la entrada", ps["sl"] <= 100.0)
check("short: precio sube al stop => CERRAR", s.avanzar_posicion(ps, ps["sl"] + 0.01)[0] == "CERRAR")

pct, usd = s.pnl_estimado("buy", 100.0, 101.0, 1.5, 20)
check("PnL estimado long +1% a 20x con $1.50 = $0.30", abs(pct - 1.0) < 1e-9 and abs(usd - 0.30) < 1e-9)
pct, usd = s.pnl_estimado("sell", 100.0, 101.0, 1.5, 20)
check("PnL estimado short -1% a 20x con $1.50 = -$0.30", abs(pct + 1.0) < 1e-9 and abs(usd + 0.30) < 1e-9)

print(f"\n{ok_n} OK, {fallos} fallos")
sys.exit(1 if fallos else 0)
