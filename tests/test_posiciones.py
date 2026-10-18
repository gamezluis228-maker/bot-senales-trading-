"""Pruebas de la lógica pura de vigilancia de posiciones.  Ejecutar: python3 tests/test_posiciones.py"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import posiciones as P  # noqa: E402
import senales  # noqa: E402

ok = fails = 0


def check(n, c):
    global ok, fails
    print(("PASS " if c else "FAIL ") + n)
    ok += bool(c)
    fails += (not c)


# --- parsear_posicion -------------------------------------------------------
raw = {"symbol": "ETH/USDT:USDT", "contracts": 2, "side": "long", "entryPrice": 3000.0, "leverage": 20,
       "initialMargin": 3.0, "marginMode": "cross", "liquidationPrice": 2870.5, "info": {"positionId": 777}}
p = P.parsear_posicion(raw)
check("parsea moneda, lado, contratos y margen", p["coin"] == "ETH" and p["lado"] == "long" and p["contratos"] == 2 and p["margen"] == 3.0)
check("detecta margen cruzado (open_type 2) y el id de posición", p["open_type"] == 2 and p["position_id"] == 777)
check("guarda el precio de liquidación", p["liquidacion"] == 2870.5)
check("margen aislado => open_type 1", P.parsear_posicion(dict(raw, marginMode="isolated"))["open_type"] == 1)
check("modo de margen desconocido => None (el bot usa su valor por defecto)", P.parsear_posicion(dict(raw, marginMode=None))["open_type"] is None)
check("sin contratos => None", P.parsear_posicion(dict(raw, contracts=0)) is None)
check("lado_orden long->buy short->sell", P.lado_orden("long") == "buy" and P.lado_orden("short") == "sell")

# --- variación --------------------------------------------------------------
v = P.variacion("buy", 3000, 3030, 1.5, 20)
check("long +1 % de precio a 20x = +20 % del margen (+$0.30)", abs(v["pct_precio"] - 1) < 1e-9 and abs(v["pct_margen"] - 20) < 1e-9 and abs(v["pnl_usdt"] - 0.30) < 1e-9)
v = P.variacion("sell", 3000, 3030, 1.5, 20)
check("short con el precio subiendo 1 % = -20 % del margen", abs(v["pct_margen"] + 20) < 1e-9 and v["pnl_usdt"] < 0)

# --- adopción de posiciones abiertas a mano ---------------------------------
pos, nota = P.crear_posicion_adoptada("buy", 100.0, 100.5, 1.5)
check("long normal: stop a 1.5 % de la entrada y sin nota", abs(pos["sl"] - 98.5) < 1e-9 and nota is None)
check("el trailing arranca desde el precio actual y el riesgo es 1.5 % de la entrada", pos["mejor"] == 100.5 and abs(pos["riesgo"] - 1.5) < 1e-9)
acc, _ = senales.avanzar_posicion(pos, 100.5)
check("adoptar no cierra la posición en el primer chequeo", acc in ("MANTENER", "SUBIR_SL"))

pos, nota = P.crear_posicion_adoptada("buy", 100.0, 97.0, 1.5)       # ya 3 % en contra: pasó el stop por defecto
check("posición muy en contra: el stop se pone desde el precio ACTUAL", abs(pos["sl"] - 97.0 * 0.985) < 1e-9 and nota)
acc, _ = senales.avanzar_posicion(pos, 97.0)
check("...y NO se cierra de golpe al adoptarla", acc != "CERRAR")
acc, _ = senales.avanzar_posicion(pos, 95.0)
check("...pero sí se cierra si cae hasta ese stop", acc == "CERRAR")

pos, nota = P.crear_posicion_adoptada("sell", 100.0, 103.0, 1.5)     # short 3 % en contra
check("short muy en contra: stop desde el precio actual", abs(pos["sl"] - 103.0 * 1.015) < 1e-9 and nota)
acc, _ = senales.avanzar_posicion(pos, 103.0)
check("short: tampoco se cierra de golpe", acc != "CERRAR")

pos, _ = P.crear_posicion_adoptada("buy", 100.0, 103.0, 1.5)         # ya en ganancia
acc, _ = senales.avanzar_posicion(pos, 103.0)
check("posición ya en ganancia: el trailing sube el stop", acc == "SUBIR_SL" and pos["sl"] > 98.5)
check("modo por defecto 'trailing' y modo 'vigilar' configurable",
      pos["modo"] == "trailing" and P.crear_posicion_adoptada("buy", 100, 100, 1.5, "vigilar")[0]["modo"] == "vigilar")

# --- botón "asegurar entrada" ----------------------------------------------
pos, _ = P.crear_posicion_adoptada("buy", 100.0, 100.0, 1.5)
okb, msg = P.asegurar_entrada(pos, 100.05)
check("asegurar sin ganancia suficiente: lo rechaza y no mueve el stop", (not okb) and abs(pos["sl"] - 98.5) < 1e-9)
okb, msg = P.asegurar_entrada(pos, 101.0)
check("asegurar con ganancia: stop en entrada + comisión", okb and abs(pos["sl"] - 100.0 * 1.001) < 1e-9)
okb, msg = P.asegurar_entrada(pos, 102.0)
check("asegurar otra vez: avisa que ya está asegurada", (not okb) and "ya está" in msg)
pos, _ = P.crear_posicion_adoptada("sell", 100.0, 99.0, 1.5)
okb, _ = P.asegurar_entrada(pos, 99.0)
check("short: asegurar mueve el stop por debajo de la entrada", okb and abs(pos["sl"] - 100.0 * 0.999) < 1e-9)
acc, _ = senales.avanzar_posicion(pos, 99.0)
check("short asegurado: sin cierre inmediato", acc != "CERRAR")

# --- avisos por escalón de ganancia/pérdida ---------------------------------
check("primer escalón: +12 % del margen => 1", P.escalon_nuevo(12.0, 0) == 1)
check("sin cambio de escalón => None", P.escalon_nuevo(15.0, 1) is None)
check("pérdida -23 % => escalón -2", P.escalon_nuevo(-23.0, 0) == -2)
check("vuelve a 0 desde +1 también se avisa", P.escalon_nuevo(4.0, 1) == 0)

# --- sugerencias de salida --------------------------------------------------
check("sin motivos cuando todo va a favor", P.sugerir_salida("buy", 1.2, 55, 101, 100, None) == [])
m = P.sugerir_salida("buy", 0.8, 55, 99, 100, None)
check("long ganando con EMAs giradas en contra => sugiere salir", len(m) == 1 and "EMAs" in m[0])
check("EMAs en contra pero sin ganancia => no sugiere (evita cerrar por ruido)", P.sugerir_salida("buy", 0.1, 55, 99, 100, None) == [])
m = P.sugerir_salida("buy", 1.5, 80, 101, 100, None)
check("long con RSI agotado y ganancia => sugiere", len(m) == 1 and "RSI" in m[0])
m = P.sugerir_salida("sell", 1.5, 20, 99, 100, None)
check("short con RSI muy bajo y ganancia => sugiere", len(m) == 1 and "RSI" in m[0])
m = P.sugerir_salida("buy", -0.5, 50, 101, 100, {"veredicto": "VERDADERO", "titulo": "Rompió soporte"})
check("señal contraria confirmada => sugiere aunque estés en pérdida", len(m) == 1 and "Señal contraria" in m[0])

# --- texto -------------------------------------------------------------------
pos, _ = P.crear_posicion_adoptada("buy", 3000.0, 3030.0, 1.5)
t = P.texto_posicion("ETH", pos, 3030.0, 1.5, 20, liquidacion=2900.0)
check("el texto muestra variación en % de precio, % de margen y USDT", "+1.00%" in t and "+20.0%" in t and "+0.30" in t)
check("avisa que el stop de una posición adoptada vive en el bot", "no está puesto en MEXC" in t)
check("muestra la distancia a la liquidación", "Liquidación" in t and "2,900.00" in t)
t = P.texto_posicion("ETH", pos, 3030.0, 1.5, 20, gestionada=False)
check("posición no gestionada se indica como tal", "NO la está gestionando" in t)
pos["modo"] = "vigilar"
check("modo vigilar aclara que el bot no cierra nada", "NO cierra nada" in P.texto_posicion("ETH", pos, 3030.0, 1.5, 20))

# --- consulta al tocar el stop ---------------------------------------------------------------------------
base = {"largo": True, "precio": 100.0, "ema9": 101.0, "ema21": 100.0, "rsi15": 50.0, "vol_rel": 1.0, "cuerpo_contra": False,
        "mecha_rechazo": 0.1, "tend1h": "NEUTRAL", "tend4h": "NEUTRAL", "tend_btc": None, "ema50_1h": 95.0}
contra = dict(base, ema9=99.0, ema21=100.0, cuerpo_contra=True, vol_rel=2.0, tend1h="BAJISTA", tend4h="BAJISTA", tend_btc="BAJISTA", ema50_1h=105.0)
d = P.diagnostico_stop("buy", contra)
check("long con todo en contra => recomienda CERRAR", d["recomendacion"] == "CERRAR" and len(d["contra"]) >= 5)
resp = dict(base, tend1h="ALCISTA", mecha_rechazo=0.7, rsi15=24.0, cuerpo_contra=True, vol_rel=0.6)
d = P.diagnostico_stop("buy", resp)
check("long con rechazo, RSI estirado, poco volumen y 1H a favor => MANTENER", d["recomendacion"] == "MANTENER" and len(d["respiro"]) >= 3)
check("evidencia mixta => DUDA (con 20x se recomienda cerrar)", P.diagnostico_stop("buy", dict(base, tend1h="BAJISTA"))["recomendacion"] == "DUDA")
s_contra = dict(contra, largo=False, ema9=101.0, ema21=100.0, tend1h="ALCISTA", tend4h="ALCISTA", tend_btc="ALCISTA", ema50_1h=95.0, precio=100.0)
check("short con todo en contra => CERRAR", P.diagnostico_stop("sell", s_contra)["recomendacion"] == "CERRAR")
check("short: RSI sobrecomprado + rechazo => respiro", "RSI" in " ".join(P.diagnostico_stop("sell", dict(base, largo=False, rsi15=78.0, mecha_rechazo=0.6, ema9=99.0, ema21=100.0))["respiro"]))

def _velas(cierres, tf):
    return [[i * tf, c, c * 1.002, c * 0.998, c, 100.0] for i, c in enumerate(cierres)]
r = P.rasgos_stop("buy", _velas([100 + i * 0.1 for i in range(80)], 900000), _velas([100 + i * 0.5 for i in range(80)], 3600000))
check("rasgos_stop calcula EMAs, RSI y tendencia 1H", r and r["tend1h"] == "ALCISTA" and r["ema9"] > 0 and 0 <= r["rsi15"] <= 100)
check("rasgos_stop sin datos suficientes => None", P.rasgos_stop("buy", [], []) is None)
pos_t, _ = P.crear_posicion_adoptada("buy", 100.0, 98.4, 1.5); pos_t.update(margen=1.5, apalancamiento=20)
t = P.texto_consulta("ETH", pos_t, 98.4, P.diagnostico_stop("buy", contra), 97.8, "STOP LOSS")
check("el mensaje de consulta dice que NO cerró, recomienda y avisa del tiempo de espera",
      "NO he cerrado nada" in t and "Recomiendo CERRAR" in t and "3 min" in t and "97.80" in t)
check("con recomendación MANTENER, la espera mantiene (no cierra)", "mantengo hasta el stop de emergencia" in P.texto_consulta("ETH", pos_t, 98.4, P.diagnostico_stop("buy", resp), 97.8, "STOP LOSS"))

print(f"\n{ok} OK, {fails} fallos")
sys.exit(1 if fails else 0)
