import requests
import numpy as np


# ===================== KUCOIN API =====================

def get_kucoin_candles(symbol, timeframe="1hour"):
    url = "https://api.kucoin.com/api/v1/market/candles"
    params = {"type": timeframe, "symbol": symbol}
    try:
        r = requests.get(url, params=params, timeout=15)
        data = r.json()
        if data.get("data"):
            candles = []
            for c in data["data"]:
                candles.append({
                    "time": int(c[0]),
                    "open": float(c[1]),
                    "close": float(c[2]),
                    "high": float(c[3]),
                    "low": float(c[4]),
                    "volume": float(c[5]),
                })
            candles.reverse()
            return candles
        return None
    except Exception as e:
        print(f"Error KuCoin candles: {e}")
        return None


def get_kucoin_price(symbol):
    url = "https://api.kucoin.com/api/v1/market/stats"
    params = {"symbol": symbol}
    try:
        r = requests.get(url, params=params, timeout=15)
        data = r.json()
        if data.get("data"):
            d = data["data"]
            return {
                "price": float(d.get("last", 0)),
                "change24h": float(d.get("changeRate", 0)) * 100,
                "high24h": float(d.get("high", 0)),
                "low24h": float(d.get("low", 0)),
                "vol24h": float(d.get("vol", 0)),
            }
        return None
    except Exception as e:
        print(f"Error KuCoin price: {e}")
        return None


# ===================== INDICADORES =====================

def calcular_rsi(candles, periodo=14):
    if len(candles) < periodo + 1:
        return 50
    closes = [c["close"] for c in candles]
    ganancias, perdidas = [], []
    for i in range(1, periodo + 1):
        cambio = closes[-i] - closes[-i - 1]
        ganancias.append(max(cambio, 0))
        perdidas.append(abs(min(cambio, 0)))
    avg_g = sum(ganancias) / periodo
    avg_p = sum(perdidas) / periodo
    if avg_p == 0:
        return 100
    rs = avg_g / avg_p
    return 100 - (100 / (1 + rs))


def calcular_sma(closes, periodo):
    if len(closes) < periodo:
        return closes[-1] if closes else 0
    return sum(closes[-periodo:]) / periodo


def calcular_ema(closes, periodo):
    if len(closes) < periodo:
        return closes[-1] if closes else 0
    ema = sum(closes[:periodo]) / periodo
    mult = 2 / (periodo + 1)
    for p in closes[periodo:]:
        ema = (p - ema) * mult + ema
    return ema


def calcular_macd(closes):
    ema12 = calcular_ema(closes, 12)
    ema26 = calcular_ema(closes, 26)
    macd = ema12 - ema26
    signal = calcular_ema(closes[-35:], 9)
    return macd, signal


def calcular_bollinger(closes, periodo=20):
    sma = calcular_sma(closes, periodo)
    std = np.std(closes[-periodo:]) if len(closes) >= periodo else 0
    return sma + 2*std, sma, sma - 2*std


def calcular_atr(candles, periodo=14):
    if len(candles) < periodo + 1:
        return 0
    tr_list = []
    for i in range(1, len(candles)):
        h = candles[i]["high"]
        l = candles[i]["low"]
        pc = candles[i-1]["close"]
        tr = max(h - l, abs(h - pc), abs(l - pc))
        tr_list.append(tr)
    return sum(tr_list[-periodo:]) / periodo


def calcular_vwap(candles):
    pv = 0
    vol = 0
    for c in candles:
        tp = (c["high"] + c["low"] + c["close"]) / 3
        pv += tp * c["volume"]
        vol += c["volume"]
    return pv / vol if vol > 0 else candles[-1]["close"]
    

# ===================== SOPORTE / RESISTENCIA =====================

def calcular_soporte_resistencia(candles, ventana=50):
    if len(candles) < ventana:
        ventana = len(candles)
    highs = [c["high"] for c in candles[-ventana:]]
    lows = [c["low"] for c in candles[-ventana:]]
    return min(lows), max(highs)


def detectar_ruptura(precio, soporte, resistencia, margen=0.005):
    if precio > resistencia * (1 + margen):
        return "RUPTURA_ALCISTA"
    elif precio < soporte * (1 - margen):
        return "RUPTURA_BAJISTA"
    return "DENTRO_RANGO"


# ===================== ANÁLISIS COMPLETO =====================

def analisis_completo(symbol):
    candles_1h = get_kucoin_candles(symbol, "1hour")
    price_data = get_kucoin_price(symbol)
    
    if not candles_1h or not price_data:
        return None
    
    closes = [c["close"] for c in candles_1h]
    precio = price_data["price"]
    
    rsi = calcular_rsi(candles_1h)
    sma20 = calcular_sma(closes, 20)
    sma50 = calcular_sma(closes, 50)
    macd, signal = calcular_macd(closes)
    upper, middle, lower = calcular_bollinger(closes)
    atr = calcular_atr(candles_1h)
    vwap = calcular_vwap(candles_1h)
    
    soporte, resistencia = calcular_soporte_resistencia(candles_1h)
    ruptura = detectar_ruptura(precio, soporte, resistencia)
    tendencia = "ALCISTA" if sma20 > sma50 else "BAJISTA"
    
    puntos = 0
    if rsi < 30: puntos += 2
    elif rsi < 40: puntos += 1
    elif rsi > 70: puntos -= 2
    elif rsi > 60: puntos -= 1
    
    if precio < lower: puntos += 2
    elif precio < middle: puntos += 1
    elif precio > upper: puntos -= 2
    elif precio > middle: puntos -= 1
    
    if macd > signal: puntos += 1
    else: puntos -= 1
    
    if sma20 > sma50: puntos += 1
    else: puntos -= 1
    
    if precio > vwap: puntos += 1
    else: puntos -= 1
    
    if puntos >= 3:
        tipo = "COMPRA"
        direccion = "ENTRA EN LARGO"
        emoji = "🟢"
    elif puntos >= 1:
        tipo = "COMPRA_DEBIL"
        direccion = "ENTRA EN LARGO (con precaucion)"
        emoji = "🟡"
    elif puntos <= -3:
        tipo = "VENTA"
        direccion = "ENTRA EN CORTO"
        emoji = "🔴"
    elif puntos <= -1:
        tipo = "VENTA_DEBIL"
        direccion = "ENTRA EN CORTO (con precaucion)"
        emoji = "🟠"
    else:
        rango = resistencia - soporte
        posicion = ((precio - soporte) / rango * 100) if rango > 0 else 50
        if 40 < posicion < 60 and abs(macd - signal) < atr * 0.5:
            tipo = "NEUTRAL"
            direccion = "NO OPERES - RANGO LATERAL"
            emoji = "⚪"
        else:
            tipo = "NEUTRAL"
            direccion = "NO OPERES - SIN SETUP"
            emoji = "⚪"
    
    if tipo in ["COMPRA", "COMPRA_DEBIL"]:
        tp = min(resistencia * 0.995, precio + (atr * 3))
        sl = max(soporte * 1.005, precio - (atr * 2.5))
    elif tipo in ["VENTA", "VENTA_DEBIL"]:
        tp = max(soporte * 1.005, precio - (atr * 3))
        sl = min(resistencia * 0.995, precio + (atr * 2.5))
    else:
        tp = resistencia
        sl = soporte
    
    if tipo in ["COMPRA", "COMPRA_DEBIL"]:
        rb = (tp - precio) / (precio - sl) if (precio - sl) > 0 else 0
    elif tipo in ["VENTA", "VENTA_DEBIL"]:
        rb = (precio - tp) / (sl - precio) if (sl - precio) > 0 else 0
    else:
        rb = 0
    
    contexto_parts = []
    if rsi < 30:
        contexto_parts.append("RSI en sobreventa — posible rebote")
    elif rsi > 70:
        contexto_parts.append("RSI en sobrecompra — posible correccion")
    if precio < lower:
        contexto_parts.append("Precio bajo banda inferior — zona de compra")
    elif precio > upper:
        contexto_parts.append("Precio sobre banda superior — zona de venta")
    if ruptura == "RUPTURA_ALCISTA":
        contexto_parts.append("RUPTURA ALCISTA detectada")
    elif ruptura == "RUPTURA_BAJISTA":
        contexto_parts.append("RUPTURA BAJISTA detectada")
    
    contexto = " | ".join(contexto_parts) if contexto_parts else "Sin senales adicionales"
    
    return {
        "tipo": tipo,
        "direccion": direccion,
        "emoji": emoji,
        "precio": precio,
        "rsi": rsi,
        "sma20": sma20,
        "sma50": sma50,
        "macd": macd,
        "signal_macd": signal,
        "bollinger": (upper, middle, lower),
        "vwap": vwap,
        "soporte": soporte,
        "resistencia": resistencia,
        "ruptura": ruptura,
        "atr": atr,
        "tendencia": tendencia,
        "tp": tp,
        "sl": sl,
        "rb": rb,
        "contexto": contexto,
        "puntos": puntos,
        "data_24h": price_data,
            }
    
