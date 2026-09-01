import ccxt
import pandas as pd

def analizar_mercado_symbol(symbol="BTC/USDT"):
    try:
        exchange = ccxt.kucoinfutures()
        target_symbol = f"{symbol}:USDT" if ":USDT" not in symbol else symbol
        
        ohlcv_15m = exchange.fetch_ohlcv(target_symbol, timeframe='15m', limit=100)
        ohlcv_1h = exchange.fetch_ohlcv(target_symbol, timeframe='1h', limit=24)
        
        if not ohlcv_15m or len(ohlcv_15m) < 50 or not ohlcv_1h:
            return f"⚠️ No hay suficientes datos en Futuros de KuCoin para {symbol}."

        df_15m = pd.DataFrame(ohlcv_15m, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        precio_actual = df_15m['close'].iloc[-1]

        df_1h = pd.DataFrame(ohlcv_1h, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        tendencia_1h = "ALCISTA 🟢" if df_1h['close'].iloc[-1] > df_1h['open'].iloc[-1] else "BAJISTA 🔴"

        df_15m['EMA_5'] = df_15m['close'].ewm(span=5, adjust=False).mean()
        df_15m['EMA_10'] = df_15m['close'].ewm(span=10, adjust=False).mean()
        df_15m['EMA_30'] = df_15m['close'].ewm(span=30, adjust=False).mean()
        
        ema5 = df_15m['EMA_5'].iloc[-1]
        ema10 = df_15m['EMA_10'].iloc[-1]
        ema30 = df_15m['EMA_30'].iloc[-1]

        resistencia = df_15m['high'].iloc[-20:].max()
        soporte = df_15m['low'].iloc[-20:].min()

        # Filtro de ATR y Volumen
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

        if ema5 > ema10 and ema10 > ema30 and precio_actual > resistencia * 0.995 and tiene_volumen:
            trend_filter = "ALCISTA (Ruptura con Volumen 🚀)"
            accion = "🟢 COMPRA / LONG (¡Ruptura Validada!)"
            estrategia = f"• **Entrada (Long):** ${precio_actual:,.2f}\n• **Stop Loss (SL):** ${sl_long:,.2f}\n• **Take Profit (TP):** ${tp_long:,.2f}"
        elif ema5 < ema10 and ema10 < ema30 and precio_actual < soporte * 1.005 and tiene_volumen:
            trend_filter = "BAJISTA (Caída con Volumen 🩸)"
            accion = "🔴 VENTA / SHORT (¡Ruptura Validada!)"
            estrategia = f"• **Entrada (Short):** ${precio_actual:,.2f}\n• **Stop Loss (SL):** ${sl_short:,.2f}\n• **Take Profit (TP):** ${tp_short:,.2f}"
        elif ema5 > ema10:
            trend_filter = "Impulso Alcista Moderado"
            accion = "🟢 COMPRA / LONG (EMA 5 > 10)"
            estrategia = f"• **Entrada (Long):** ${precio_actual:,.2f}\n• **Stop Loss (SL):** ${sl_long:,.2f}\n• **Take Profit (TP):** ${tp_long:,.2f}"
        elif ema5 < ema10:
            trend_filter = "Impulso Bajista Moderado"
            accion = "🔴 VENTA / SHORT (EMA 5 < 10)"
            estrategia = f"• **Entrada (Short):** ${precio_actual:,.2f}\n• **Stop Loss (SL):** ${sl_short:,.2f}\n• **Take Profit (TP):** ${tp_short:,.2f}"

        cierres = df_15m['close'].values
        cambios = [cierres[i] - cierres[i-1] for i in range(1, len(cierres))]
        ganancias = [c if c > 0 else 0 for c in cambios]
        perdidas = [-c if c < 0 else 0 for c in cambios]
        avg_ganancia = sum(ganancias[-14:]) / 14 if len(ganancias) >= 14 else 1
        avg_perdida = sum(perdidas[-14:]) / 14 if len(perdidas) >= 14 else 1
        rsi = 100 if avg_perdida == 0 else 100 - (100 / (1 + (avg_ganancia / avg_perdida)))

        mensaje = (
            f"⚡ **FUTUROS KUCOIN: {symbol}**\n\n"
            f"💵 **Precio Actual:** ${precio_actual:,.2f}\n"
            f"🌅 **Tendencia Macro (1H):** {tendencia_1h}\n"
            f"📊 **Estructura (15m):** {trend_filter}\n"
            f"📈 **RSI (15m):** {rsi:.1f} | **ATR:** {atr:.2f}\n\n"
            f"🧱 **Resistencia:** ${resistencia:,.2f}\n"
            f"🟡 **Soporte:** ${soporte:,.2f}\n\n"
            f"🎯 **SEÑAL DE OPERACIÓN:**\n{accion}\n{estrategia}\n\n"
            f"⚠️ *Filtro de volatilidad institucional activo.*"
        )
        return mensaje

    except Exception as e:
        return f"❌ Error al analizar {symbol}: {str(e)}"

def escanear_radar():
    symbols = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "XRP/USDT"]
    oportunidades = []
    
    try:
        exchange = ccxt.kucoinfutures()
        for symbol in symbols:
            target_symbol = f"{symbol}:USDT"
            ohlcv_15m = exchange.fetch_ohlcv(target_symbol, timeframe='15m', limit=100)
            if not ohlcv_15m or len(ohlcv_15m) < 50:
                continue
                
            df = pd.DataFrame(ohlcv_15m, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            precio = df['close'].iloc[-1]
            
            ema5 = df['close'].ewm(span=5, adjust=False).mean().iloc[-1]
            ema10 = df['close'].ewm(span=10, adjust=False).mean().iloc[-1]
            ema30 = df['close'].ewm(span=30, adjust=False).mean().iloc[-1]
            
            vol_prom = df['volume'].rolling(window=20).mean().iloc[-1]
            vol_act = df['volume'].iloc[-1]
            
            # Criterio de radar: tendencia clara y buen volumen
            if ema5 > ema10 and ema10 > ema30 and vol_act > (vol_prom * 1.1):
                oportunidades.append(f"🟢 **{symbol}**: Tendencia Alcista con Volumen (Precio: ${precio:,.2f})")
            elif ema5 < ema10 and ema10 < ema30 and vol_act > (vol_prom * 1.1):
                oportunidades.append(f"🔴 **{symbol}**: Tendencia Bajista con Volumen (Precio: ${precio:,.2f})")
                
        if not oportunidades:
            return "📡 **RADAR DE MERCADO**: Ninguna criptomoneda cumple con los filtros estrictos en este momento. Mercado en pausa o lateral."
            
        return "📡 **RADAR DE OPORTUNIDADES INSTITUCIONALES**:\n\n" + "\n".join(oportunidades)
        
    except Exception as e:
        return f"❌ Error al ejecutar el radar: {str(e)}"

def calcular_riesgo(margen_usdt=10, apalancamiento_dummy=10, sl_porcentaje=1):
    try:
        margen = float(margen_usdt)
        
        if margen <= 15:
            apalancamiento_sugerido = 20
        elif margen <= 50:
            apalancamiento_sugerido = 10
        else:
            apalancamiento_sugerido = 5

        riesgo_usd = margen * (float(sl_porcentaje) / 100)
        posicion_total = margen * apalancamiento_sugerido

        return (
            f"🧮 **GESTIÓN DE RIESGO INTELIGENTE**\n\n"
            f"💵 **Margen Asignado:** ${margen:,.2f}\n"
            f"⚡ **Apalancamiento Sugerido:** {apalancamiento_sugerido}x\n"
            f"🛡️ **Riesgo Máximo ({sl_porcentaje}%):** ${riesgo_usd:,.2f}\n"
            f"🎯 **Tamaño de Posición Total:** ${posicion_total:,.2f}\n"
            f"💡 *Calculado automáticamente según tu margen para proteger tu capital.*"
        )
    except ValueError:
        return "⚠️ Usa el formato correcto, por ejemplo: `/riesgo 10`"

analyze_market = analizar_mercado_symbol
calculate_risk = calcular_riesgo
radar_market = escanear_radar
