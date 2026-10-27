"""Dibujo de la operación para las alertas de entrada: velas + EMAs + entrada/stop/meta
+ soporte/resistencia. Puro Pillow (liviano, sin matplotlib): el bot ya trae numpy y
Pillow se añade a requirements.txt.

Si el dibujo falla por cualquier motivo, quien llama debe mandar solo el texto:
la señal nunca se pierde por el dibujo.

Formato de vela: [timestamp_ms, abierta, maxima, minima, cierre, volumen]
(solo velas CERRADAS, como el resto del bot).
"""

import io

import numpy as np
from PIL import Image, ImageDraw, ImageFont

import indicadores as ind

ANCHO, ALTO = 900, 640
FONDO = (16, 20, 26)
REJILLA = (38, 46, 58)
TEXTO = (230, 233, 238)
VERDE = (38, 166, 154)
ROJO = (239, 83, 80)
EMA9 = (255, 213, 79)
EMA21 = (255, 112, 67)
EMA200 = (224, 224, 224)
ENTRADA = (0, 229, 255)
STOP = (255, 82, 82)
META = (105, 240, 174)
SOPORTE = (68, 138, 255)
RESISTENCIA = (171, 71, 188)
N_MOSTRAR = 80


def _fmt(x):
    return f"{x:,.2f}" if abs(x) >= 1 else f"{x:.6f}"


def _fuente(negrita, tam):
    for ruta in ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if negrita
                 else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                 "DejaVuSans-Bold.ttf" if negrita else "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(ruta, tam)
        except OSError:
            continue
    return ImageFont.load_default()


def _linea_punteada(dib, x0, x1, y, color):
    x = x0
    while x < x1:
        dib.line([(x, y), (min(x + 12, x1), y)], fill=color, width=2)
        x += 20


def dibujar_operacion(coin, velas, senal, n_mostrar=N_MOSTRAR, vela_viva=None, stop=None, meta=None):
    """Devuelve el PNG (bytes) con el dibujo de la operación.

    senal trae: tipo (COMPRA/VENTA), direccion (LONG/SHORT), precio, sl_pct, tp_pct,
    titulo; y opcionalmente soporte/resistencia (las señales de senales.py las traen;
    las de avisos no, y entonces se calculan de la ventana mostrada).
    velas son las CERRADAS; vela_viva (opcional) es la vela en formación de MEXC y se
    dibuja hueca con la etiqueta EN VIVO, para que el dibujo muestre el precio live
    del momento del envío y no solo el último cierre.
    stop/meta explícitos (para las alertas de salida, donde el stop es el trailing del
    bot y no hay meta fija): si vienen, se usan; si no, se calculan con sl_pct/tp_pct;
    una meta None no se dibuja.
    """
    if len(velas) < 10:
        raise ValueError("muy pocas velas para dibujar")
    largo = senal["direccion"] == "LONG"
    p = float(senal["precio"])
    if stop is None:
        stop = p * (1 - senal["sl_pct"] / 100) if largo else p * (1 + senal["sl_pct"] / 100)
    if meta is None and senal.get("tp_pct"):
        meta = p * (1 + senal["tp_pct"] / 100) if largo else p * (1 - senal["tp_pct"] / 100)

    v = list(velas[-max(n_mostrar, 30):])
    n = len(v)
    n_total = n + (1 if vela_viva else 0)
    cierres = np.asarray([x[4] for x in velas], dtype=float)
    altos = np.asarray([x[2] for x in v], dtype=float)
    bajos = np.asarray([x[3] for x in v], dtype=float)
    # EMAs sobre toda la historia recibida, recortadas a la ventana mostrada
    offset = len(cierres) - n
    emas = {}
    for periodo, color in ((9, EMA9), (21, EMA21), (200, EMA200)):
        if len(cierres) >= periodo:
            emas[periodo] = (ind.ema(cierres, periodo)[offset:], color)

    sop = senal.get("soporte") or None
    res = senal.get("resistencia") or None
    if not sop or not res:
        atr_val = float(senal.get("atr") or ind.atr(
            np.asarray([x[2] for x in velas], dtype=float),
            np.asarray([x[3] for x in velas], dtype=float), cierres, 14))
        res_c, sop_c, _, _ = ind.niveles(altos, bajos, atr_val)
        res = res or res_c
        sop = sop or sop_c

    lo = min(float(bajos.min()), p, sop, *(x for x in (stop, meta) if x is not None))
    hi = max(float(altos.max()), p, res, *(x for x in (stop, meta) if x is not None))
    if vela_viva:
        lo = min(lo, float(vela_viva[3]))
        hi = max(hi, float(vela_viva[2]))
    pad = (hi - lo) * 0.06 or 1.0
    lo -= pad
    hi += pad

    img = Image.new("RGB", (ANCHO, ALTO), FONDO)
    dib = ImageDraw.Draw(img)
    margen_izq, margen_der, top, abajo = 12, 158, 58, 34
    plot_ancho = ANCHO - margen_izq - margen_der
    plot_alto = ALTO - top - abajo

    def y_de(precio):
        return top + (hi - precio) / (hi - lo) * plot_alto

    def x_de(i):
        return margen_izq + (i + 0.5) * plot_ancho / n_total

    # Rejilla
    for k in range(5):
        y = top + plot_alto * k / 4
        dib.line([(margen_izq, y), (ANCHO - margen_der, y)], fill=REJILLA, width=1)

    # Velas
    ancho_cuerpo = max(2.0, plot_ancho / n_total * 0.7)
    for i, vela in enumerate(v):
        o, h, l, c = float(vela[1]), float(vela[2]), float(vela[3]), float(vela[4])
        color = VERDE if c >= o else ROJO
        x = x_de(i)
        dib.line([(x, y_de(h)), (x, y_de(l))], fill=color, width=1)
        dib.rectangle([x - ancho_cuerpo / 2, y_de(max(o, c)), x + ancho_cuerpo / 2, y_de(min(o, c))],
                      fill=color)
    if vela_viva:
        # Vela en formación: hueca, para distinguirla de las cerradas
        o, h, l, c = (float(vela_viva[k]) for k in (1, 2, 3, 4))
        color = VERDE if c >= o else ROJO
        x = x_de(n)
        dib.line([(x, y_de(h)), (x, y_de(l))], fill=color, width=1)
        dib.rectangle([x - ancho_cuerpo / 2, y_de(max(o, c)), x + ancho_cuerpo / 2, y_de(min(o, c))],
                      outline=color, width=2)
        etiqueta = "EN VIVO"
        fnt = _fuente(True, 12)
        ancho_txt = dib.textlength(etiqueta, font=fnt)
        dib.text((x - ancho_txt / 2, y_de(h) - 18), etiqueta, font=fnt, fill=ENTRADA)

    # EMAs (se saltan los NaN del inicio de cada serie)
    for periodo, (serie, color) in emas.items():
        pts = [(x_de(i), y_de(float(serie[i]))) for i in range(n) if np.isfinite(serie[i])]
        if len(pts) >= 2:
            dib.line(pts, fill=color, width=2)

    # Líneas de la operación: nombre + precio en la caja derecha; las cajas se
    # separan un mínimo para no taparse cuando dos niveles casi coinciden
    lineas = [(ENTRADA, "ENTRADA", p)]
    if stop:
        lineas.append((STOP, "STOP", stop))
    if meta:
        lineas.append((META, "META", meta))
    lineas.append((SOPORTE, "SOPORTE", sop))
    lineas.append((RESISTENCIA, "RESIST.", res))
    cajas = []
    for color, nombre, precio in lineas:
        y = min(max(y_de(precio), top), top + plot_alto)
        _linea_punteada(dib, margen_izq, ANCHO - margen_der, y, color)
        cajas.append([color, nombre, precio, y])
    cajas.sort(key=lambda c: c[3])
    for k in range(1, len(cajas)):
        if cajas[k][3] - cajas[k - 1][3] < 22:
            cajas[k][3] = min(cajas[k - 1][3] + 22, top + plot_alto - 9)
    for color, nombre, precio, y in cajas:
        dib.rectangle([ANCHO - margen_der + 4, y - 9, ANCHO - 6, y + 9], fill=color)
        dib.text((ANCHO - margen_der + 8, y - 7), f"{nombre} {_fmt(precio)}",
                 font=_fuente(False, 13), fill=(10, 10, 10))

    # Título y leyenda
    color_dir = VERDE if largo else ROJO
    dib.ellipse([margen_izq, 14, margen_izq + 16, 30], fill=color_dir)
    dib.text((margen_izq + 22, 12),
             f"{coin} {senal['tipo']}  —  {senal.get('titulo', '')}",
             font=_fuente(True, 20), fill=TEXTO)
    dib.text((margen_izq, 36),
             "   ".join(x for x in (f"Entrada ${_fmt(p)}",
                                    f"Stop ${_fmt(stop)}" if stop else None,
                                    f"Meta ${_fmt(meta)}" if meta else None) if x),
             font=_fuente(False, 15), fill=TEXTO)
    ley_x = margen_izq
    for nombre, color in (("EMA9", EMA9), ("EMA21", EMA21), ("EMA200", EMA200)):
        dib.line([(ley_x, ALTO - 18), (ley_x + 22, ALTO - 18)], fill=color, width=3)
        dib.text((ley_x + 26, ALTO - 26), nombre, font=_fuente(False, 13), fill=TEXTO)
        ley_x += 92

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
