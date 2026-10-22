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
# --- respuesta directa con objetivos -------------------------------------------------------------------------
o = P.objetivos(81843.6, 0.15)
check("objetivos: 1 ATR y 2 ATR a cada lado", abs(o["sube1"] - 81843.6 * 1.0015) < 1e-6 and abs(o["baja2"] - 81843.6 * (1 - 0.003)) < 1e-6)
check("objetivos: invalidación a 1 ATR en contra", abs(o["invalida_sube"] - o["baja1"]) < 1e-9 and abs(o["invalida_baja"] - o["sube1"]) < 1e-9)
o2 = P.objetivos(100.0, 1.0, resistencia=100.4, soporte=99.7)
check("una resistencia cercana frena el objetivo de subida", o2["sube1"] == 100.4 and o2["notas"] and "Resistencia" in o2["notas"][0])
check("un soporte cercano frena el objetivo de bajada", o2["baja1"] == 99.7 and any("Soporte" in n for n in o2["notas"]))
o3 = P.objetivos(100.0, 1.0, resistencia=105.0, soporte=95.0)
check("niveles lejanos no cambian los objetivos", o3["sube1"] == 101.0 and o3["baja1"] == 99.0 and o3["notas"] == [])
pred = {"precio": 2423.45, "direccion": "SUBE", "prob_sube": 54, "prob_baja": 46, "confianza": "BAJA", "rsi": 59.6, "adx": 18.6,
        "sma5": 2424.0, "sma10": 2420.0, "volumen": 948698.0, "volumen_promedio": 781984.0, "atr_pct": 0.15,
        "puntos_alcista": 5, "puntos_bajista": 2, "factores": [("Precio vs EMA9 (5m)", 1, 1.0), ("RSI", -1, 1.0)]}
ob = P.objetivos(pred["precio"], pred["atr_pct"])
c_ = P.cuadro_veredicto("ETH", pred, ob, True)
check("el veredicto va en un cuadro aparte (bloque de código)", c_.startswith("```") and "┌" not in c_ and "│" not in c_)
check("el cuadro dice SUBE con su probabilidad y la fuerza", "ETH   ▲ SUBE   54%" in c_ and "Fuerza: DÉBIL" in c_)
check("el cuadro trae precio, dos objetivos e invalidación", "Ahora     $2,423.45" in c_ and "Objetivo1 $2,427.09 (+0.15%)" in c_ and "Objetivo2 $2,430.72 (+0.30%)" in c_ and "Invalida  $2,419.81" in c_)
check("las líneas del cuadro son cortas (caben en el móvil)", max(len(x) for x in c_.split("```")[1].strip().splitlines()) <= 32)
check("fuera del cuadro: plan y pedir monto", "Plan: COMPRA (LONG)" in c_ and "Elige el monto" in c_ and "Señal débil" in c_)
cb = P.cuadro_veredicto("ETH", dict(pred, direccion="BAJA", prob_baja=61, confianza="ALTA"), ob, True)
check("BAJA: cuadro con ▼, objetivos a la baja e invalidación al alza", "▼ BAJA   61%" in cb and "Fuerza: FUERTE" in cb and "Objetivo1 $2,419.81 (-0.15%)" in cb and "Invalida  $2,427.09" in cb and "VENTA (SHORT)" in cb)
check("moneda no operable (SOL) lo aclara", "solo opera BTC, ETH, ZEC" in P.cuadro_veredicto("SOL", pred, ob, False))
cl = P.cuadro_veredicto("ETH", dict(pred, direccion="LATERAL"), ob, True)
check("lateral: sin dirección, se inclina a un lado, techo y piso, sin ofrecer operar", "SIN DIRECCIÓN" in cl and "Se inclina a SUBIR" in cl and "Techo" in cl and "Piso" in cl and "Elige el monto" not in cl and "mejor no entrar" in cl)
a_ = P.texto_directo("ETH", pred, ob)
check("el análisis de siempre sigue en otro mensaje, con los dos escenarios", a_.startswith("📋 ANÁLISIS ETH") and "Si SUBE: $2,427.09" in a_ and "Si BAJA: $2,419.81" in a_)
check("el análisis conserva RSI, ADX, volumen y factores", "RSI (5m): 59.6" in a_ and "ADX (5m): 18.6" in a_ and "Volumen: 948698" in a_ and "🟢 Precio vs EMA9" in a_ and "🔴 RSI" in a_)

print(f"\n{ok} OK, {fails} fallos"); sys.exit(1 if fails else 0)
