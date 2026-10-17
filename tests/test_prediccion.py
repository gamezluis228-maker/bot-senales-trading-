"""Pruebas de la estimación de probabilidad (datos simulados). Ejecutar: python3 tests/test_prediccion.py"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import numpy as np
import prediccion as P

ok = fails = 0
def check(n, c):
    global ok, fails
    print(("PASS " if c else "FAIL ") + n); ok += bool(c); fails += (not c)

def velas(precios, tf_ms, vol=100.0, vol_final=None):
    out = []
    prev = precios[0]
    for i, c in enumerate(precios):
        o = prev; h = max(o, c) * 1.0005; l = min(o, c) * 0.9995
        v = vol_final if (vol_final and i == len(precios) - 1) else vol
        out.append([i * tf_ms, o, h, l, c, v]); prev = c
    return out

n = 130
rng = np.random.default_rng(1)
sube = list(100 * np.cumprod(1 + 0.0015 + rng.normal(0, 0.0004, n)))
baja = list(100 * np.cumprod(1 - 0.0015 + rng.normal(0, 0.0004, n)))
plano = list(100 + rng.normal(0, 0.05, n))
f = lambda s, tf: velas(s, tf, vol=100, vol_final=200)

e = P.estimar(f(sube, 300000), f(sube[:80], 900000), f(sube[:100], 3600000))
check("tendencia alcista -> probabilidad de subir > 55 %", e["direccion"] == "SUBE" and e["prob_sube"] > 55)
check("probabilidades suman 100", e["prob_sube"] + e["prob_baja"] == 100)
check("nunca supera el tope de 70 %", e["prob_sube"] <= 70)
e2 = P.estimar(f(baja, 300000), f(baja[:80], 900000), f(baja[:100], 3600000))
check("tendencia bajista -> probabilidad de bajar > 55 %", e2["direccion"] == "BAJA" and e2["prob_baja"] > 55 and e2["prob_baja"] <= 70)
e3 = P.estimar(f(plano, 300000), f(plano[:80], 900000), f(plano[:100], 3600000))
check("mercado plano -> probabilidades cercanas a 50/50", 40 <= e3["prob_sube"] <= 60)
check("mercado plano marcado como lateral (ADX bajo)", e3["lateral"] is True)
check("sin datos suficientes -> None", P.estimar(velas(sube[:10], 300000)) is None)
check("funciona sin 15m ni 1H (menos factores)", P.estimar(f(sube, 300000))["factores"].__len__() == 5)
# RSI extremo resta ventaja al impulso (agotamiento)
salto = list(100 * np.cumprod(1 + 0.006 + rng.normal(0, 0.0002, n)))
e4 = P.estimar(f(salto, 300000), f(salto[:80], 900000), f(salto[:100], 3600000))
check("RSI extremo reduce la confianza respecto a una subida ordenada", e4["prob_sube"] <= e["prob_sube"])
check("incluye movimiento típico (ATR %) positivo", e["atr_pct"] > 0)
print(f"\n{ok} OK, {fails} fallos"); sys.exit(1 if fails else 0)
