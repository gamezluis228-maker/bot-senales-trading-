import ccxt
import pandas as pd

def analyze_market(symbol="BTC/USDT"):
    try:
        # Configuración migrada a BingX Futuros
        exchange = ccxt.bingx({
            'enableRateLimit': True,
            'timeout': 5000,
        })
        target_symbol = f"{symbol}:USDT" if ":USDT" not in symbol else symbol
        
        ohlcv_15m = exchange.fetch_ohlcv(target_symbol, timeframe='15m', limit=100)
        ohlcv_1h = exchange.fetch_ohlcv(target_symbol, timeframe='1h', limit=24)
        
        if not ohlcv_15m or len(ohlcv_15m) < 50 or not ohlcv_1h:
            return f"⚠️ No hay suficientes datos en Futuros de BingX para {symbol}."

        df_15m = pd.DataFrame(ohlcv_15m, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        precio_actual = df_15m['close'].iloc[-1]

        df_1h = pd.DataFrame(ohlcv_1h, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        tendencia_1h = "ALCISTA 🟢" if df_1h['close'].iloc[-1] > df_1h['open'].iloc[-1] else "BAJISTA 🔴"
        es_alcista_1h = df_1h['close'].iloc[-1] > df_1h['open'].iloc[-1]

        # Actualizado a EMA 9 y EMA 21 (15m)
        df_15m['EMA_9'] = df_15m['close'].ewm(span=9, adjust=False).mean()
        df_15m['EMA_21'] = df_15m['close'].ewm(span=21, adjust=False).mean()
        
        ema9 = df_15m['EMA_9'].iloc[-1]
        ema21 = df_15m['EMA_21'].iloc[-1]

        resistencia = df_15m['high'].iloc[-20:].max()
        soporte = df_15m['low'].iloc[-20:].min()

        df_15m['tr0'] = abs(df_15m['high'] - df_15m['low'])
        df_15m['tr1'] = abs(df_15m['high'] - df_15m['close'].shift())
        df_15m['tr2'] = abs(df_15m['low'] - df_15m['close'].shift())
        df_15m['tr'] = df_15m[['tr0', 'tr1', 'tr2']].max(axis=1)
        atr = df_15m['tr'].rolling(window=14).mean().iloc[-1]

        volumen_promedio = df_15m['volume'].rolling(window=20).mean().iloc[-1]
        volumen_actual = df_15m['volume'].iloc[-1]
        tiene_volumen = volumen_actual > (volumen_promedio * 1.1)

        trend_filter = "NEUTRAL"
        accion = "⏳ MERCADO LATERAL / ESPERAR RUPTURA"
        estrategia = f"• **Soporte Clave:** ${soporte:,.2f}\n• **Resistencia Clave:** ${resistencia:,.2f}\n• Esperar rompimiento con volumen."
        
        sl_long = round(precio_actual - (atr * 1.5), 2)
        tp_long = round(precio_actual + (atr * 2.5), 2)
        sl_short = round(precio_actual + (atr * 1.5), 2)
        tp_short = round(precio_actual - (atr * 2.5), 2)

        # Lógica de decisión con filtro multi-temporalidad (1H + 15m con EMA 9/21)
        if ema9 > ema21 and es_alcista_1h and precio_actual > resistencia * 0.995 and tiene_volumen:
            trend_filter = "ALCISTA (Ruptura con Volumen 🚀)"
            accion = "🟢 COMPRA / LONG (¡Ruptura Validada con 1H!)"
            estrategia = f"• **Entrada (Long):** ${precio_actual:,.2f}\n• **Stop Loss (SL):** ${sl_long:,.2f}\n• **Take Profit (TP):** ${tp_long:,.2f}"
        elif ema9 < ema21 and not es_alcista_1h and precio_actual < soporte * 1.005 and tiene_volumen:
            trend_filter = "BAJISTA (Caída con Volumen 🩸)"
            accion = "🔴 VENTA / SHORT (¡Ruptura Validada con 1H!)"
            estrategia = f"•
