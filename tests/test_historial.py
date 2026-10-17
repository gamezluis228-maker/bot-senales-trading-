"""Pruebas del historial de aciertos. Ejecutar: python3 tests/test_historial.py"""
import os, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import historial as H

ok = fails = 0
def check(n, c):
    global ok, fails
    print(("PASS " if c else "FAIL ") + n); ok += bool(c); fails += (not c)

H.RUTA = os.path.join(tempfile.mkdtemp(), "h.jsonl")
T0 = 1_700_000_000_000
M = 60_000
pred = lambda i, d, p, prob, conf="MEDIA": {"id": f"p{i}", "tipo": "prediccion", "symbol": "ETH", "direccion": d,
    "precio": p, "ts": T0 + i * 10 * M, "prob_sube": prob, "confianza": conf, "atr_pct": 0.2}

check("registrar guarda el evento", H.registrar(pred(1, "SUBE", 100.0, 62)))
check("no duplica el mismo id", not H.registrar(pred(1, "SUBE", 100.0, 62)))
check("predicción aún no vence a los 4 min", not H.pendientes(T0 + 10 * M + 4 * M))
check("predicción vence a los 5 min", len(H.pendientes(T0 + 10 * M + 5 * M)) == 1)

ev = H.todos()[0]
r = H.evaluar_prediccion(ev, 100.3, ev["ts"] + 5 * M)
check("SUBE y el precio subió => acierto", r["acierto"] and r["subio"])
check("SUBE y el precio bajó => fallo", not H.evaluar_prediccion(ev, 99.8, ev["ts"] + 5 * M)["acierto"])
check("LATERAL acierta si casi no se movió", H.evaluar_prediccion(dict(ev, direccion="LATERAL"), 100.05, ev["ts"] + 5 * M)["acierto"])
check("BAJA y el precio bajó => acierto", H.evaluar_prediccion(dict(ev, direccion="BAJA"), 99.5, ev["ts"] + 5 * M)["acierto"])
check("evaluar demasiado tarde => se descarta", H.evaluar_prediccion(ev, 100.3, ev["ts"] + 60 * M).get("descartado"))

H.actualizar("p1", r)
check("actualizar marca como resuelto", H.todos()[0]["resuelto"] is True)
check("lo resuelto no vuelve a pendientes", not H.pendientes(T0 + 999 * M))

v = lambda alto, bajo: [0, 0, alto, bajo, 0, 0]
check("COMPRA toca TP (+3%) => TP", H.simular_senal("COMPRA", 100, 1.5, 3, [v(101, 99.5), v(103.2, 100)]) == "TP")
check("COMPRA toca SL (-1.5%) => SL", H.simular_senal("COMPRA", 100, 1.5, 3, [v(100.5, 98.4)]) == "SL")
check("VENTA toca TP (-3%) => TP", H.simular_senal("VENTA", 100, 1.5, 3, [v(100.5, 96.9)]) == "TP")
check("VENTA toca SL (+1.5%) => SL", H.simular_senal("VENTA", 100, 1.5, 3, [v(101.6, 99.9)]) == "SL")
check("misma vela toca SL y TP => SL (conservador)", H.simular_senal("COMPRA", 100, 1.5, 3, [v(103.5, 98.0)]) == "SL")
check("sin tocar nada => None", H.simular_senal("COMPRA", 100, 1.5, 3, [v(101, 99.5)]) is None)

for i in range(2, 12):
    H.registrar(pred(i, "SUBE", 100.0, 62, "ALTA")); e = [x for x in H.todos() if x["id"] == f"p{i}"][0]
    H.actualizar(f"p{i}", H.evaluar_prediccion(e, 100.2 if i % 2 == 0 else 99.9, e["ts"] + 5 * M))
H.registrar({"id": "s1", "tipo": "senal", "symbol": "ETH", "direccion": "LONG", "tipo_orden": "COMPRA", "precio": 100.0,
             "ts": T0, "veredicto": "VERDADERO", "subtipo": "ROMPIMIENTO_REAL_RESISTENCIA"})
H.actualizar("s1", {"resultado": "TP"})
txt = H.resumen_texto()
check("resumen muestra el acierto de dirección", "Acierto de dirección" in txt and "confianza ALTA" in txt)
check("resumen muestra la calibración con n suficiente", "dijo ~62% de subir" in txt)
check("resumen muestra el resultado de señales por veredicto", "VERDADERO: 1/1" in txt)
check("avisa de muestra pequeña", "Muestra pequeña" in txt)
check("resumen vacío no falla", "Aún no hay predicciones" in H.resumen_texto([]))
print(f"\n{ok} OK, {fails} fallos"); sys.exit(1 if fails else 0)
