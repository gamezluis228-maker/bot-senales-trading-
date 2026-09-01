import ccxt
import pandas as pd

def analizar_mercado_symbol(symbol="BTC/USDT"):
    try:
        exchange = ccxt.kucoinfutures()
        target_symbol = f"{symbol}:USDT" if ":USDT" not in symbol else symbol
        
        # Descargar temporalidad de 1H para sesgo macro y 15m para scalping
        ohlcv_15m = exchange.fetch_ohlcv(target_symbol, timeframe='15m', limit=100)
        ohlcv_1h = exchange.fetch_ohlcv(target_symbol, timeframe='1h', limit=24)
        
        if not ohlcv_15m or len(ohlcv_15m) < 50 or not ohlcv_1h:
            return f"⚠️ No hay suficientes datos en Futuros de KuCoin para {symbol}."

        # DataFrame de 15m para EMAs y precios actuales
        df_15m = pd.DataFrame(ohlcv_15m, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        precio_actual = df_15m['close'].iloc[-1]

        # DataFrame de 1h para la vela macro de la mañana / tendencia general
        df_1h = pd.DataFrame(ohlcv_1h, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        tendencia_1h = "ALCISTA 🟢" if df_1h['close'].iloc[-1] > df_1h['open'].iloc[-1] else "BAJISTA 🔴"

        # Cálculo de EMAs (5, 10, 30) en 15m
        df_15m['EMA_5'] = df_15m['close'].ewm(span=5, adjust=False).mean()
        df_15m['EMA_10'] = df_15m['close'].ewm(span=10, adjust=False).mean()
        df_15m['EMA_30'] = df_15m['close'].ewm(span=30, adjust=False).mean()
        
        ema5 = df_15m['EMA_5'].iloc[-1]
        ema10 = df_15m['EMA_10'].iloc[-1]
        ema30 = df_15m['EMA_30'].iloc[-1]

        # Soportes y Resistencias
        resistencia = df_15m['high'].iloc[-20:].max()
        soporte = df_15m['low'].iloc[-20:].min()

        # Lógica de señales de entrada y rupturas
        trend_filter = "NEUTRAL"
        accion = "⏳ MERCADO LATERAL / ESPERAR RUPTURA"
        estrategia = f"• **Soporte Clave:** ${soporte:,.2f}\n• **Resistencia Clave:** ${resistencia:,.2f}\n• Esperar rompimiento con volumen."
        
        sl_long = round(precio_actual * 0.99, 2)
        tp_long = round(precio_actual * 1.02, 2)
        sl_short = round(precio_actual * 1.01, 2)
        tp_short = round(precio_actual * 0.98, 2)

        # Validar cruce de EMAs y rupturas
        if ema5 > ema10 and ema10 > ema30 and precio_actual > resistencia * 0.995:
            trend_filter = "ALCISTA (Ruptura de Resistencia)"
            accion = "🟢 COMPRA / LONG (¡Posible Ruptura!)"
            estrategia = f"• **Entrada (Long):** ${precio_actual:,.2f}\n• **Stop Loss (SL):** ${sl_long:,.2f}\n• **Take Profit (TP):** ${tp_long:,.2f}"
        elif ema5 < ema10 and ema10 < ema30 and precio_actual < soporte * 1.005:
            trend_filter = "BAJISTA (Ruptura de Soporte)"
            accion = "🔴 VENTA / SHORT (¡Caída Confirmada!)"
            estrategia = f"• **Entrada (Short):** ${precio_actual:,.2f}\n• **Stop Loss (SL):** ${sl_short:,.2f}\n• **Take Profit (TP):** ${tp_short:,.2f}"
        elif ema5 > ema10:
            trend_filter = "Impulso Alcista Moderado"
            accion = "🟢 COMPRA / LONG (EMA 5 > 10)"
            estrategia = f"• **Entrada (Long):** ${precio_actual:,.2f}\n• **Stop Loss (SL):** ${sl_long:,.2f}\n• **Take Profit (TP):** ${tp_long:,.2f}"
        elif ema5 < ema10:
            trend_filter = "Impulso Bajista Moderado"
            accion = "🔴 VENTA / SHORT (EMA 5 < 10)"
            estrategia = f"• **Entrada (Short):** ${precio_actual:,.2f}\n• **Stop Loss (SL):** ${sl_short:,.2f}\n• **Take Profit (TP):** ${tp_short:,.2f}"

        # RSI de 15m
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
            f"📈 **RSI (15m):** {rsi:.1f}\n\n"
            f"🧱 **Resistencia:** ${resistencia:,.2f}\n"
            f"🟡 **Soporte:** ${soporte:,.2f}\n\n"
            f"🎯 **SEÑAL DE OPERACIÓN:**\n{accion}\n{estrategia}\n\n"
            f"⚠️ *Usa gestión de riesgo adecuada.*"
        )
        return mensaje

    except Exception as e:
        return f"❌ Error al analizar {symbol}: {str(e)}"

def calcular_riesgo(capital_usdt, sl_porcentaje=1):
    try:
        capital = float(capital_usdt)
        riesgo_usd = capital * (sl_porcentaje / 100)
        return (
            f"🧮 **GESTIÓN DE RIESGO (FUTUROS)**\n\n"
            f"💰 **Capital:** ${capital:,.2f}\n"
            f"🛡️ **Riesgo Máximo ({sl_porcentaje}%):** ${riesgo_usd:,.2f}\n"
            f"💡 *Ajusta tu apalancamiento acorde al stop loss.*"
        )
    except ValueError:
        return "⚠️ Usa el formato correcto, por ejemplo: `/riesgo 1000`"

analyze_market = analizar_mercado_symbol
calculate_risk = calcular_riesgo

 