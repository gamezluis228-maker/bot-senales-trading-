import requests

def get_kucoin_candles(symbol, timeframe='15min', limit=50):
    url = f"https://api.kucoin.com/api/v1/market/candles?type={timeframe}&symbol={symbol}&limit={limit}"
    try:
        r = requests.get(url, timeout=15)
        data = r.json()
        if data.get('data'):
            candles = []
            for c in data['data']:
                candles.append({
                    'time': int(c[0]),
                    'open': float(c[1]),
                    'close': float(c[2]),
                    'high': float(c[3]),
                    'low': float(c[4]),
                    'volume': float(c[5])
                })
            candles.reverse()
            return candles
        return None
    except Exception as e:
        print(f"Error candles: {e}")
        return None

def get_kucoin_stats(symbol):
    url = f"https://api.kucoin.com/api/v1/market/stats?symbol={symbol}"
    try:
        r = requests.get(url, timeout=10)
        data = r.json()
        if data.get('data'):
            d = data['data']
            return {
                'price': float(d.get('last', 0)),
                'change24h': float(d.get('changeRate', 0)) * 100,
                'high24h': float(d.get('high', 0)),
                'low24h': float(d.get('low', 0)),
                'vol24h': float(d.get('vol', 0)),
                'buy': float(d.get('buy', 0)),
                'sell': float(d.get('sell', 0))
            }
        return None
    except Exception as e:
        print(f"Error stats: {e}")
        return None

def calcular_rsi(candles, periodo=14):
    if len(candles) < periodo + 1:
        return 50
    ganancias = []
    perdidas = []
    for i in range(1, periodo + 1):
        cambio = candles[-i]['close'] - candles[-(i+1)]['close']
        if cambio > 0:
            ganancias.append(cambio)
            perdidas.append(0)
        else:
            ganancias.append(0)
            perdidas.append(abs(cambio))
    avg_ganancia = sum(ganancias) / periodo
    avg_perdida = sum(perdidas) / periodo
    if avg_perdida == 0:
        return 100
    rs = avg_ganancia / avg_perdida
    return 100 - (100 / (1 + rs))

def calcular_ema(candles, periodo=20):
    if len(candles) < periodo:
        return candles[-1]['close']
    k = 2 / (periodo + 1)
    ema = sum(c['close'] for c in candles[:periodo]) / periodo
    for c in candles[periodo:]:
        ema = c['close'] * k + ema * (1 - k)
    return ema

def calcular_sma(candles, periodo=20):
    if len(candles) < periodo:
        return candles[-1]['close']
    return sum(c['close'] for c in candles[-periodo:]) / periodo

def calcular_atr(candles, periodo=14):
    if len(candles) < periodo + 1:
        return candles[-1]['close'] * 0.02
    tr_list = []
    for i in range(1, periodo + 1):
        high = candles[-i]['high']
        low = candles[-i]['low']
        prev_close = candles[-(i+1)]['close']
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        tr_list.append(tr)
    return sum(tr_list) / periodo

def detectar_tendencia(candles):
    if len(candles) < 20:
        return "NEUTRO"
    ema20 = calcular_ema(candles, 20)
    sma20 = calcular_sma(candles, 20)
    precio_actual = candles[-1]['close']
    if precio_actual > ema20 * 1.02 and ema20 > sma20:
        return "ALCISTA"
    elif precio_actual < ema20 * 0.98 and ema20 < sma20:
        return "BAJISTA"
    else:
        return "LATERAL"

def calcular_volumen_analisis(candles):
    if len(candles) < 10:
        return 0
    vol_reciente = sum(c['volume'] for c in candles[-5:]) / 5
    vol_anterior = sum(c['volume'] for c in candles[-10:-5]) / 5
    if vol_anterior == 0:
        return 0
    return ((vol_reciente - vol_anterior) / vol_anterior) * 100

def generar_senal(par):
    candles = get_kucoin_candles(par, timeframe='15min', limit=50)
    stats = get_kucoin_stats(par)
    if not candles or not stats:
        return {
            'tipo': 'NEUTRO',
            'par': par,
            'mensaje': '⚠️ No se pudieron obtener datos del mercado.',
            'data': stats
        }
    rsi = calcular_rsi(candles)
    ema20 = calcular_ema(candles, 20)
    sma20 = calcular_sma(candles, 20)
    tendencia = detectar_tendencia(candles)
    volumen_cambio = calcular_volumen_analisis(candles)
    atr = calcular_atr(candles)
    precio = stats['price']
    highs = [c['high'] for c in candles[-96:]] if len(candles) >= 96 else [c['high'] for c in candles]
    lows = [c['low'] for c in candles[-96:]] if len(candles) >= 96 else [c['low'] for c in candles]
    max_24h = max(highs) if highs else stats['high24h']
    min_24h = min(lows) if lows else stats['low24h']
    rango = max_24h - min_24h
    posicion_rango = ((precio - min_24h) / rango * 100) if rango > 0 else 50
    senal = {
        'tipo': 'NEUTRO',
        'par': par,
        'precio': precio,
        'rsi': round(rsi, 2),
        'ema20': round(ema20, 2),
        'tendencia': tendencia,
        'volumen_cambio': round(volumen_cambio, 2),
        'posicion_rango': round(posicion_rango, 1),
        'data': stats
    }
    if rsi < 35 and posicion_rango < 30 and tendencia in ["ALCISTA", "LATERAL"]:
        tp = precio * 1.02
        sl = min(precio - atr * 1.5, precio * 0.985)
        if stats['change24h'] < -3:
            contexto = f"Bajó {stats['change24h']:.2f}% en 24h y está en {posicion_rango:.0f}% del rango. Posible rebote."
        elif stats['change24h'] > 2:
            contexto = f"Tendencia alcista con retroceso. RSI en zona de compra ({rsi:.1f})."
        else:
            contexto = f"Acumulación detectada. RSI {rsi:.1f} (sobrevendido). Rango: {posicion_rango:.0f}%."
        senal.update({
            'tipo': 'LONG',
            'tp': round(tp, 2),
            'sl': round(sl, 2),
            'contexto': contexto,
            'confianza': 'ALTA' if (rsi < 25 and volumen_cambio > 20) else 'MEDIA'
        })
        return senal
    elif rsi > 65 and posicion_rango > 70 and tendencia in ["BAJISTA", "LATERAL"]:
        tp = precio * 0.98
        sl = max(precio + atr * 1.5, precio * 1.015)
        if stats['change24h'] > 5:
            contexto = f"Subió {stats['change24h']:.2f}% en 24h y está en {posicion_rango:.0f}% del rango. Posible corrección."
        elif stats['change24h'] < -2:
            contexto = f"Tendencia bajista con rebote. RSI en zona de venta ({rsi:.1f})."
        else:
            contexto = f"Distribución detectada. RSI {rsi:.1f} (sobrecomprado). Rango: {posicion_rango:.0f}%."
        senal.update({
            'tipo': 'SHORT',
            'tp': round(tp, 2),
            'sl': round(sl, 2),
            'contexto': contexto,
            'confianza': 'ALTA' if (rsi > 75 and volumen_cambio > 20) else 'MEDIA'
        })
        return senal
    else:
        if tendencia == "ALCISTA":
            contexto = f"Tendencia alcista pero sin punto de entrada óptimo. RSI: {rsi:.1f}. Esperar retroceso."
        elif tendencia == "BAJISTA":
            contexto = f"Tendencia bajista pero sin punto de entrada óptimo. RSI: {rsi:.1f}. Esperar rebote."
        else:
            contexto = f"Mercado lateral. RSI: {rsi:.1f}. Sin señal clara. Esperar ruptura."
        senal.update({
            'tipo': 'NEUTRO',
            'contexto': contexto,
            'confianza': 'BAJA'
        })
        return senal

def formatear_senal(senal):
    data = senal['data']
    par = senal['par']
    if senal['tipo'] == 'NEUTRO':
        emoji = "⚪"
        texto = f"""{emoji} SIN SEÑAL - {par}

💰 Precio: ${data['price']:.2f}
📊 Cambio 24h: {data['change24h']:+.2f}%
📈 Máx 24h: ${data['high24h']:.2f}
📉 Mín 24h: ${data['low24h']:.2f}
📦 Volumen: {data['vol24h']:,.0f}

{senal['contexto']}

⏱ Temporalidad: 15m - 1H
⚠️ Gestión de riesgo obligatoria
🚀 Nunca inviertas más del 2%"""
        return texto
    emoji = "🟢" if senal['tipo'] == 'LONG' else "🔴"
    direccion = "ENTRADA LONG" if senal['tipo'] == 'LONG' else "ENTRADA SHORT"
    texto = f"""{emoji} {direccion} - {par}

💰 Precio: ${data['price']:.2f}
📊 Cambio 24h: {data['change24h']:+.2f}%
📈 Máx 24h: ${data['high24h']:.2f}
📉 Mín 24h: ${data['low24h']:.2f}
📦 Volumen: {data['vol24h']:,.0f}

📈 {senal['contexto']}

🎯 TP: ${senal['tp']:.2f}
🛑 SL: ${senal['sl']:.2f}

⏱ Temporalidad: 15m - 1H
⚠️ Gestión de riesgo obligatoria
🚀 Nunca inviertas más del 2%"""
    return texto
          
