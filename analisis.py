#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MÓDULO DE ANÁLISIS TÉCNICO - KUCOIN FUTUROS
Indicadores: RSI, EMA, MACD, ATR, Bollinger, Estocástico, Volumen
"""

import requests
import numpy as np
from typing import Dict, List, Tuple, Optional
from datetime import datetime

# API KuCoin Futures
KUCOIN_FUTURES = "https://api-futures.kucoin.com"

# Símbolos en KuCoin Futures
PARES = {
    "BTC": "XBTUSDTM",
    "ETH": "ETHUSDTM",
    "SOL": "SOLUSDTM",
    "XRP": "XRPUSDTM",
    "BNB": "BNBUSDTM",
}

# Indicadores
RSI_PERIOD = 14
RSI_SOBRECOMPRA = 70
RSI_SOBREVENTA = 30
EMA_RAPIDA = 9
EMA_LENTA = 21
MACD_RAPIDO = 12
MACD_LENTO = 26
MACD_SIGNAL = 9
ATR_PERIOD = 14

# Capital y riesgo
CAPITAL_USDT = 10.0
RIESGO_MAX_PCT = 2.0


# =============================================================
# INDICADORES TÉCNICOS
# =============================================================

def calcular_rsi(precios: List[float], periodo: int = RSI_PERIOD) -> float:
    """RSI - Relative Strength Index"""
    if len(precios) < periodo + 1:
        return 50.0
    deltas = np.diff(precios)
    ganancias = np.where(deltas > 0, deltas, 0)
    perdidas = np.where(deltas < 0, -deltas, 0)
    avg_ganancia = np.mean(ganancias[-periodo:])
    avg_perdida = np.mean(perdidas[-periodo:])
    if avg_perdida == 0:
        return 100.0
    rs = avg_ganancia / avg_perdida
    return round(100 - (100 / (1 + rs)), 2)


def calcular_ema(precios: List[float], periodo: int) -> float:
    """EMA - Exponential Moving Average"""
    if len(precios) < periodo:
        return precios[-1] if precios else 0
    precios_np = np.array(precios)
    ema = np.mean(precios_np[:periodo])
    mult = 2 / (periodo + 1)
    for p in precios_np[periodo:]:
        ema = (p - ema) * mult + ema
    return round(ema, 2)


def calcular_macd(precios: List[float]) -> Tuple[float, float, float]:
    """MACD, Signal e Histograma"""
    if len(precios) < MACD_LENTO + MACD_SIGNAL:
        return 0.0, 0.0, 0.0
    ema_rap = calcular_ema(precios, MACD_RAPIDO)
    ema_len = calcular_ema(precios, MACD_LENTO)
    macd = ema_rap - ema_len
    signal = macd * 0.8
    hist = macd - signal
    return round(macd, 4), round(signal, 4), round(hist, 4)


def calcular_atr(velas: List[Dict], periodo: int = ATR_PERIOD) -> float:
    """ATR - Average True Range (volatilidad)"""
    if len(velas) < periodo + 1:
        return 0.0
    trs = []
    for i in range(1, len(velas)):
        h = float(velas[i]["high"])
        l = float(velas[i]["low"])
        c_prev = float(velas[i-1]["close"])
        trs.append(max(h - l, abs(h - c_prev), abs(l - c_prev)))
    return round(np.mean(trs[-periodo:]), 2)


def calcular_volumen_promedio(velas: List[Dict], periodo: int = 20) -> float:
    """Volumen promedio de las últimas N velas"""
    if len(velas) < periodo:
        return 0.0
    return round(np.mean([float(v["volume"]) for v in velas[-periodo:]]), 2)


def detectar_soporte_resistencia(velas: List[Dict], ventana: int = 20) -> Tuple[float, float]:
    """Soporte y resistencia recientes"""
    if len(velas) < ventana:
        return 0.0, 0.0
    highs = [float(v["high"]) for v in velas[-ventana:]]
    lows = [float(v["low"]) for v in velas[-ventana:]]
    return round(min(lows), 2), round(max(highs), 2)


def calcular_bollinger(precios: List[float], periodo: int = 20, mult: float = 2.0) -> Tuple[float, float, float]:
    """Bandas de Bollinger"""
    if len(precios) < periodo:
        return precios[-1], precios[-1], precios[-1]
    sma = np.mean(precios[-periodo:])
    std = np.std(precios[-periodo:])
    return round(sma - mult * std, 2), round(sma, 2), round(sma + mult * std, 2)


def calcular_stochastic(precios_high, precios_low, precios_close, periodo: int = 14) -> Tuple[float, float]:
    """Estocástico %K y %D"""
    if len(precios_close) < periodo:
        return 50.0, 50.0
    high_max = max(precios_high[-periodo:])
    low_min = min(precios_low[-periodo:])
    close = precios_close[-1]
    if high_max == low_min:
        return 50.0, 50.0
    k = 100 * (close - low_min) / (high_max - low_min)
    d = k * 0.8
    return round(k, 2), round(d, 2)


# =============================================================
# OBTENER DATOS DE KUCOIN FUTUROS
# =============================================================

def obtener_velas(simbolo: str, timeframe: str = "15min", limite: int = 100) -> Optional[List[Dict]]:
    """Obtiene velas de KuCoin Futures"""
    try:
        url = f"{KUCOIN_FUTURES}/api/v1/kline/query"
        params = {"symbol": simbolo, "granularity": timeframe, "maxCount": limite}
        r = requests.get(url, params=params, timeout=15)
        data = r.json()
        if data.get("code") == "200000" and data.get("data"):
            velas = []
            for v in data["data"]:
                velas.append({
                    "timestamp": int(v[0]),
                    "open": float(v[1]),
                    "close": float(v[2]),
                    "high": float(v[3]),
                    "low": float(v[4]),
                    "volume": float(v[5])
                })
            return velas
        return None
    except Exception as e:
        print(f"[ERROR] Velas {simbolo}: {e}")
        return None


def obtener_ticker(simbolo: str) -> Optional[Dict]:
    """Obtiene ticker actual de futuros"""
    try:
        url = f"{KUCOIN_FUTURES}/api/v1/ticker"
        r = requests.get(url, params={"symbol": simbolo}, timeout=10)
        data = r.json()
        if data.get("code") == "200000" and data.get("data"):
            return data["data"]
        return None
    except Exception as e:
        print(f"[ERROR] Ticker {simbolo}: {e}")
        return None


# =============================================================
# ANÁLISIS COMPLETO + SEÑALES
# =============================================================

def analizar_par(par_codigo: str, timeframe: str = "15min") -> Optional[Dict]:
    """
    Analiza un par completo y devuelve:
    - Señal de entrada/salida
    - Indicadores
    - Apalancamiento recomendado
    - SL / TP / Liquidación
    """
    simbolo = PARES.get(par_codigo.upper())
    if not simbolo:
        return None

    velas = obtener_velas(simbolo, timeframe, 100)
    ticker = obtener_ticker(simbolo)
    if not velas or not ticker:
        return None

    precios_cierre = [v["close"] for v in velas]
    precios_high = [v["high"] for v in velas]
    precios_low = [v["low"] for v in velas]
    precio_actual = float(ticker.get("price", precios_cierre[-1]))

    # Indicadores
    rsi = calcular_rsi(precios_cierre)
    ema_rap = calcular_ema(precios_cierre, EMA_RAPIDA)
    ema_len = calcular_ema(precios_cierre, EMA_LENTA)
    macd, macd_sig, macd_hist = calcular_macd(precios_cierre)
    atr = calcular_atr(velas)
    vol_actual = float(velas[-1]["volume"])
    vol_promedio = calcular_volumen_promedio(velas)
    soporte, resistencia = detectar_soporte_resistencia(velas)
    bb_inf, bb_mid, bb_sup = calcular_bollinger(precios_cierre)
    stoch_k, stoch_d = calcular_stochastic(precios_high, precios_low, precios_cierre)

    cambio_24h = float(ticker.get("changeRate", 0)) * 100
    max_24h = float(ticker.get("high", 0))
    min_24h = float(ticker.get("low", 0))
    vol_24h = float(ticker.get("vol", 0))

    # LÓGICA DE SEÑALES
    señal = "NEUTRAL"
    direccion = "➡️"
    confianza = 0
    razones_entrada = []
    razones_salida = []
    alerta = False

    # SEÑAL DE COMPRA (LARGO)
    cond_compra = 0
    if rsi < RSI_SOBREVENTA:
        cond_compra += 1
        razones_entrada.append(f"RSI sobrevendido ({rsi})")
    if ema_rap > ema_len:
        cond_compra += 1
        razones_entrada.append("EMA9 cruza arriba de EMA21")
    if macd > macd_sig and macd_hist > 0:
        cond_compra += 1
        razones_entrada.append("MACD alcista")
    if vol_actual > vol_promedio * 1.3:
        cond_compra += 1
        razones_entrada.append("Volumen confirmando")
    if precio_actual <= bb_inf * 1.002:
        cond_compra += 1
        razones_entrada.append("Precio en banda inferior de Bollinger")
    if stoch_k < 20:
        cond_compra += 1
        razones_entrada.append("Estocástico sobrevendido")

    if cond_compra >= 4:
        señal = "COMPRA"
        direccion = "🟢"
        confianza = min(40 + cond_compra * 10, 95)
        alerta = True
    elif cond_compra >= 2:
        señal = "COMPRA_DEBIL"
        direccion = "🟡"
        confianza = min(30 + cond_compra * 8, 60)

    # SEÑAL DE VENTA (CORTO)
    cond_venta = 0
    if rsi > RSI_SOBRECOMPRA:
        cond_venta += 1
        razones_entrada.append(f"RSI sobrecomprado ({rsi})")
    if ema_rap < ema_len:
        cond_venta += 1
        razones_entrada.append("EMA9 cruza abajo de EMA21")
    if macd < macd_sig and macd_hist < 0:
        cond_venta += 1
        razones_entrada.append("MACD bajista")
    if vol_actual > vol_promedio * 1.3:
        cond_venta += 1
        razones_entrada.append("Volumen confirmando")
    if precio_actual >= bb_sup * 0.998:
        cond_venta += 1
        razones_entrada.append("Precio en banda superior de Bollinger")
    if stoch_k > 80:
        cond_venta += 1
        razones_entrada.append("Estocástico sobrecomprado")

    if cond_venta >= 4:
        señal = "VENTA"
        direccion = "🔴"
        confianza = min(40 + cond_venta * 10, 95)
        alerta = True
    elif cond_venta >= 2 and señal == "NEUTRAL":
        señal = "VENTA_DEBIL"
        direccion = "🟠"
        confianza = min(30 + cond_venta * 8, 60)

    # SEÑALES DE SALIDA
    if señal in ["COMPRA", "COMPRA_DEBIL"]:
        if rsi > 65:
            razones_salida.append("RSI elevado - considerar cierre parcial")
        if precio_actual >= resistencia * 0.998:
            razones_salida.append("Precio en resistencia - tomar ganancias")
        if precio_actual >= bb_sup * 0.995:
            razones_salida.append("Precio en banda superior de Bollinger")
        if stoch_k > 80 and stoch_d > 75:
            razones_salida.append("Estocástico sobrecomprado - salir")

    elif señal in ["VENTA", "VENTA_DEBIL"]:
        if rsi < 35:
            razones_salida.append("RSI bajo - considerar cierre parcial")
        if precio_actual <= soporte * 1.002:
            razones_salida.append("Precio en soporte - tomar ganancias")
        if precio_actual <= bb_inf * 1.005:
            razones_salida.append("Precio en banda inferior de Bollinger")
        if stoch_k < 20 and stoch_d < 25:
            razones_salida.append("Estocástico sobrevendido - salir")

    # APALANCAMIENTO según volatilidad
    volatilidad_pct = (atr / precio_actual) * 100 if precio_actual else 0
    if volatilidad_pct < 0.3:
        apalancamiento = 10
        riesgo_nivel = "BAJO"
    elif volatilidad_pct < 0.6:
        apalancamiento = 7
        riesgo_nivel = "MEDIO"
    elif volatilidad_pct < 1.0:
        apalancamiento = 5
        riesgo_nivel = "ALTO"
    else:
        apalancamiento = 3
        riesgo_nivel = "MUY ALTO"

    # SL / TP / Liquidación
    sl_dist = atr * 2
    tp_dist = atr * 3
    if señal in ["COMPRA", "COMPRA_DEBIL"]:
        sl = precio_actual - sl_dist
        tp = precio_actual + tp_dist
        liq = precio_actual * (1 - (1 / apalancamiento) * 0.9)
    elif señal in ["VENTA", "VENTA_DEBIL"]:
        sl = precio_actual + sl_dist
        tp = precio_actual - tp_dist
        liq = precio_actual * (1 + (1 / apalancamiento) * 0.9)
    else:
        sl = tp = liq = 0

    margen = CAPITAL_USDT / apalancamiento
    tamaño_pos = CAPITAL_USDT * apalancamiento

    return {
        "par": par_codigo.upper(),
        "simbolo": simbolo,
        "timeframe": timeframe,
        "precio": round(precio_actual, 2),
        "señal": señal,
        "direccion": direccion,
        "confianza": confianza,
        "alerta": alerta,
        "rsi": rsi,
        "ema_rapida": ema_rap,
        "ema_lenta": ema_len,
        "macd": macd,
        "macd_signal": macd_sig,
        "macd_hist": macd_hist,
        "atr": atr,
        "volatilidad_pct": round(volatilidad_pct, 4),
        "bb_inf": bb_inf,
        "bb_mid": bb_mid,
        "bb_sup": bb_sup,
        "stoch_k": stoch_k,
        "stoch_d": stoch_d,
        "soporte": soporte,
        "resistencia": resistencia,
        "volumen": round(vol_actual, 2),
        "volumen_prom": vol_promedio,
        "cambio_24h": round(cambio_24h, 2),
        "max_24h": round(max_24h, 2),
        "min_24h": round(min_24h, 2),
        "vol_24h": round(vol_24h, 2),
        "apalancamiento": apalancamiento,
        "riesgo_nivel": riesgo_nivel,
        "margen": round(margen, 2),
        "tamaño_posicion": round(tamaño_pos, 2),
        "stop_loss": round(sl, 2) if sl else 0,
        "take_profit": round(tp, 2) if tp else 0,
        "liquidacion": round(liq, 2) if liq else 0,
        "razones_entrada": razones_entrada,
        "razones_salida": razones_salida,
        "hora": datetime.now().strftime("%H:%M:%S")
    }


def escanear_todos(timeframe: str = "15min") -> List[Dict]:
    """Escanea todos los pares y devuelve solo los que tienen señal fuerte"""
    resultados = []
    for par in PARES.keys():
        data = analizar_par(par, timeframe)
        if data and data["alerta"]:
            resultados.append(data)
    return resultados


# =============================================================
# FORMATO DE MENSAJE PARA TELEGRAM
# =============================================================

def formatear_mensaje(data: Dict) -> str:
    """Convierte el análisis en mensaje de Telegram"""
    par = data["par"]
    s = data["señal"]
    d = data["direccion"]

    if s == "NEUTRAL":
        titulo = f"{d} <b>SIN SEÑAL - {par}-USDT</b>"
        cuerpo = f"""
<i>Mercado lateral. RSI: {data['rsi']}. Sin señal clara. Esperar ruptura.</i>

<b>Condiciones para entrada:</b>
  • RSI < 30 + EMA alcista + MACD positivo → <b>COMPRA</b>
  • RSI > 70 + EMA bajista + MACD negativo → <b>VENTA</b>
"""
    elif s == "COMPRA":
        titulo = f"🟢 <b>SEÑAL DE COMPRA - {par}-USDT</b>"
        cuerpo = f"""
<b>Precio entrada:</b> <code>${data['precio']:,.2f}</code>
<b>Confianza:</b> {data['confianza']}% {'█' * int(data['confianza']/10)}{'░' * (10-int(data['confianza']/10))}

<b>Indicadores:</b>
  • RSI: {data['rsi']} {'(Sobrevendido)' if data['rsi'] < 30 else '(Neutral)'}
  • EMA9: ${data['ema_rapida']:,.2f} | EMA21: ${data['ema_lenta']:,.2f}
  • MACD: {data['macd']} (Signal: {data['macd_signal']})
  • Estocástico: {data['stoch_k']}%
  • Bollinger: ${data['bb_inf']:,.2f} / ${data['bb_mid']:,.2f} / ${data['bb_sup']:,.2f}

<b>Niveles:</b>
  • Soporte: ${data['soporte']:,.2f}
  • Resistencia: ${data['resistencia']:,.2f}

<b>PLAN DE OPERACIÓN (10 USDT):</b>
  <b>Apalancamiento:</b> <code>{data['apalancamiento']}x</code> (Volatilidad: {data['riesgo_nivel']})
  <b>Margen requerido:</b> <code>${data['margen']:.2f} USDT</code>
  <b>Tamaño posición:</b> <code>${data['tamaño_posicion']:.2f} USDT</code>

<b>Stop Loss:</b> <code>${data['stop_loss']:,.2f}</code>
<b>Take Profit:</b> <code>${data['take_profit']:,.2f}</code>
<b>Liquidación:</b> <code>${data['liquidacion']:,.2f}</code>

<b>Razones de entrada:</b>
"""
        for r in data["razones_entrada"]:
            cuerpo += f"  ✅ {r}\n"

        if data["razones_salida"]:
            cuerpo += f"""
<b>Señales de salida anticipada:</b>
"""
            for r in data["razones_salida"]:
                cuerpo += f"  ⚠️ {r}\n"

    elif s == "VENTA":
        titulo = f"🔴 <b>SEÑAL DE VENTA - {par}-USDT</b>"
        cuerpo = f"""
<b>Precio entrada:</b> <code>${data['precio']:,.2f}</code>
<b>Confianza:</b> {data['confianza']}% {'█' * int(data['confianza']/10)}{'░' * (10-int(data['confianza']/10))}

<b>Indicadores:</b>
  • RSI: {data['rsi']} {'(Sobrecomprado)' if data['rsi'] > 70 else '(Neutral)'}
  • EMA9: ${data['ema_rapida']:,.2f} | EMA21: ${data['ema_lenta']:,.2f}
  • MACD: {data['macd']} (Signal: {data['macd_signal']})
  • Estocástico: {data['stoch_k']}%
  • Bollinger: ${data['bb_inf']:,.2f} / ${data['bb_mid']:,.2f} / ${data['bb_sup']:,.2f}

<b>Niveles:</b>
  • Soporte: ${data['soporte']:,.2f}
  • Resistencia: ${data['resistencia']:,.2f}

<b>PLAN DE OPERACIÓN (10 USDT):</b>
  <b>Apalancamiento:</b> <code>{data['apalancamiento']}x</code> (Volatilidad: {data['riesgo_nivel']})
  <b>Margen requerido:</b> <code>${data['margen']:.2f} USDT</code>
  <b>Tamaño posición:</b> <code>${data['tamaño_posicion']:.2f} USDT</code>

<b>Stop Loss:</b> <code>${data['stop_loss']:,.2f}</code>
<b>Take Profit:</b> <code>${data['take_profit']:,.2f}</code>
<b>Liquidación:</b> <code>${data['liquidacion']:,.2f}</code>

<b>Razones de entrada:</b>
"""
        for r in data["razones_entrada"]:
            cuerpo += f"  ✅ {r}\n"

        if data["razones_salida"]:
            cuerpo += f"""
<b>Señales de salida anticipada:</b>
"""
            for r in data["razones_salida"]:
                cuerpo += f"  ⚠️ {r}\n"

    else:  # DEBIL
        titulo = f"{d} <b>SEÑAL DÉBIL - {par}-USDT</b>"
        cuerpo = f"""
<b>Precio:</b> <code>${data['precio']:,.2f}</code>
<b>Confianza:</b> {data['confianza']}% (Débil, esperar confirmación)

<b>Indicadores:</b>
  • RSI: {data['rsi']}
  • EMA9: ${data['ema_rapida']:,.2f} | EMA21: ${data['ema_lenta']:,.2f}
  • MACD: {data['macd']}

<b>Recomendación:</b> Esperar más confirmación antes de entrar.
"""

    pie = f"""
━━━━━━━━━━━━━━━━━━━━
<b>GESTIÓN DE RIESGO</b>
━━━━━━━━━━━━━━━━━━━━
Temporalidad: {data['timeframe']}
Gestión de riesgo obligatoria
Nunca inviertas más del 2%

<i>{data['hora']}</i>
"""

    return titulo + "\n━━━━━━━━━━━━━━━━━━━━" + cuerpo + pie


if __name__ == "__main__":
    print("Probando análisis de BTC...")
    resultado = analizar_par("BTC", "15min")
    if resultado:
        print(formatear_mensaje(resultado))
    else:
        print("No se pudo obtener datos")
    
