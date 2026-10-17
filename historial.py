"""Historial de aciertos: guarda cada predicción y señal y anota, con datos reales de MEXC, si se cumplió.

Archivo JSON Lines (un evento por línea). La ruta se puede cambiar con la variable de entorno
HISTORIAL_PATH. En Render el disco es efímero: sin un Disk persistente el historial se
reinicia en cada despliegue.
"""
import json
import os
import threading

RUTA = os.getenv("HISTORIAL_PATH", "historial_aciertos.jsonl")
ESPERA_PREDICCION_MS = 5 * 60 * 1000          # una predicción se evalúa 5 min después
CADUCIDAD_PREDICCION_MS = 20 * 60 * 1000      # si el bot estuvo caído, se descarta (precio ya no sirve)
HORIZONTE_SENAL_MS = 4 * 3600 * 1000          # una señal se da por "neutra" si en 4 h no toca SL ni TP
RETENCION_MS = 30 * 24 * 3600 * 1000
_lock = threading.Lock()


def todos():
    with _lock:
        return _leer()


def _leer():
    if not os.path.exists(RUTA):
        return []
    eventos = []
    with open(RUTA, "r", encoding="utf-8") as f:
        for linea in f:
            linea = linea.strip()
            if linea:
                try:
                    eventos.append(json.loads(linea))
                except ValueError:
                    continue
    return eventos


def _escribir(eventos):
    tmp = RUTA + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        for e in eventos:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
    os.replace(tmp, RUTA)


def registrar(evento):
    """Agrega un evento si su 'id' no existe. Devuelve True si lo guardó."""
    with _lock:
        eventos = _leer()
        if any(e.get("id") == evento["id"] for e in eventos):
            return False
        evento = dict(evento, resuelto=False)
        eventos.append(evento)
        corte = evento["ts"] - RETENCION_MS
        _escribir([e for e in eventos if e.get("ts", 0) >= corte])
        return True


def actualizar(id_evento, campos):
    with _lock:
        eventos = _leer()
        for e in eventos:
            if e.get("id") == id_evento:
                e.update(campos)
                e["resuelto"] = True
        _escribir(eventos)


def pendientes(ahora_ms):
    """Eventos sin resolver que ya se pueden evaluar (las señales se revisan siempre)."""
    salida = []
    for e in todos():
        if e.get("resuelto"):
            continue
        if e["tipo"] == "prediccion" and e["ts"] + ESPERA_PREDICCION_MS <= ahora_ms:
            salida.append(e)
        elif e["tipo"] == "senal":
            salida.append(e)
    return salida


def evaluar_prediccion(ev, precio_final, ahora_ms):
    """Compara la predicción con el precio 5 min después. Si es demasiado tarde la descarta."""
    if ahora_ms - ev["ts"] > CADUCIDAD_PREDICCION_MS:
        return {"descartado": True}
    delta = (precio_final - ev["precio"]) / ev["precio"] * 100
    if ev["direccion"] == "SUBE":
        acierto = delta > 0
    elif ev["direccion"] == "BAJA":
        acierto = delta < 0
    else:  # LATERAL: acierta si casi no se movió
        acierto = abs(delta) < 0.5 * ev.get("atr_pct", 0.2)
    return {"precio_final": precio_final, "delta_pct": round(delta, 4), "subio": delta > 0,
            "acierto": bool(acierto), "descartado": False}


def simular_senal(tipo, entrada, sl_pct, tp_pct, velas):
    """Recorre velas de 5m posteriores a la señal. Devuelve 'TP', 'SL' o None si aún no decide.
    Si una misma vela toca ambos niveles se asume el SL primero (criterio conservador)."""
    largo = tipo == "COMPRA"
    sl = entrada * (1 - sl_pct / 100) if largo else entrada * (1 + sl_pct / 100)
    tp = entrada * (1 + tp_pct / 100) if largo else entrada * (1 - tp_pct / 100)
    for v in velas:
        alto, bajo = v[2], v[3]
        if (bajo <= sl) if largo else (alto >= sl):
            return "SL"
        if (alto >= tp) if largo else (bajo <= tp):
            return "TP"
    return None


def _pct(a, b):
    return f"{a / b * 100:.0f}%" if b else "—"


def resumen_texto(eventos=None):
    ev = todos() if eventos is None else eventos
    preds = [e for e in ev if e["tipo"] == "prediccion" and e.get("resuelto") and not e.get("descartado")]
    sens = [e for e in ev if e["tipo"] == "senal" and e.get("resuelto")]
    pend = [e for e in ev if not e.get("resuelto")]
    L = ["📒 HISTORIAL DE ACIERTOS", ""]

    L.append(f"🔮 PREDICCIONES evaluadas a 5 min: {len(preds)}")
    dirs = [e for e in preds if e["direccion"] in ("SUBE", "BAJA")]
    if dirs:
        L.append(f"   Acierto de dirección (sube/baja): {sum(e['acierto'] for e in dirs)}/{len(dirs)} = "
                 f"{_pct(sum(e['acierto'] for e in dirs), len(dirs))}")
        for conf in ("ALTA", "MEDIA", "BAJA"):
            g = [e for e in dirs if e.get("confianza") == conf]
            if g:
                L.append(f"   · confianza {conf}: {sum(e['acierto'] for e in g)}/{len(g)} = {_pct(sum(e['acierto'] for e in g), len(g))}")
        L.append("   Calibración (lo que dijo vs lo que pasó):")
        tramos = [(30, 39), (40, 47), (48, 52), (53, 60), (61, 70)]
        for lo, hi in tramos:
            g = [e for e in preds if lo <= e.get("prob_sube", 50) <= hi]
            if len(g) >= 5:
                dijo = sum(e["prob_sube"] for e in g) / len(g)
                paso = sum(1 for e in g if e["subio"]) / len(g) * 100
                L.append(f"   · dijo ~{dijo:.0f}% de subir → subió {paso:.0f}% de las veces (n={len(g)})")
        if len(preds) < 50:
            L.append("   ⚠️ Muestra pequeña: no saques conclusiones todavía (conviene ≥100).")
    else:
        L.append("   Aún no hay predicciones evaluadas (se evalúan 5 min después de generarse).")

    L += ["", f"🚨 SEÑALES resueltas: {len(sens)}"]
    decididas = [e for e in sens if e.get("resultado") in ("TP", "SL")]
    neutras = len(sens) - len(decididas)
    if decididas:
        gan = sum(1 for e in decididas if e["resultado"] == "TP")
        L.append(f"   Llegaron al TP antes que al SL: {gan}/{len(decididas)} = {_pct(gan, len(decididas))} (neutras: {neutras})")
        for nombre, campo in (("veredicto", "veredicto"), ("tipo de señal", "subtipo")):
            valores = sorted({e.get(campo) for e in decididas if e.get(campo)})
            for val in valores:
                g = [e for e in decididas if e.get(campo) == val]
                L.append(f"   · {val}: {sum(1 for e in g if e['resultado'] == 'TP')}/{len(g)} = "
                         f"{_pct(sum(1 for e in g if e['resultado'] == 'TP'), len(g))}")
        if len(decididas) < 30:
            L.append("   ⚠️ Muestra pequeña: una racha corta no demuestra nada.")
    else:
        L.append("   Aún no hay señales con resultado (se resuelven al tocar SL o TP, máx. 4 h).")
    L += ["", f"⏳ Pendientes de evaluar: {len(pend)}",
          "ℹ️ Las predicciones se registran solas cada 15 min para BTC, ETH y ZEC."]
    return "\n".join(L)
