import ccxt
import pandas as pd

def analizar_mercado_symbol(symbol="BTC/USDT"):
    try:
        # Conectar a los FUTUROS de KuCoin
        exchange = ccxt.kucoinfutures()
        target_symbol = f"{symbol}:USDT" if ":USDT" not in symbol else symbol
        
        # Descargar velas de 15m (como en tu gráfico)
        ohlcv = exchange.fetch_ohlcv(target_symbol, timeframe='15m', limit=100)
        
        if not ohlcv or len(ohlcv) < 50:
            return f"⚠️ No hay suficientes datos en Futuros de KuCoin para {symbol}."

        # Convertir a DataFrame
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        precio_actual = df['close'].iloc[-1]

        # --- CÁLCULO DE EMAs CON PURA MATEMÁTICA DE PANDAS ---
        df['EMA_5'] = df['close'].ewm(span=5, adjust=False).mean()
        df['EMA_10'] = df['close'].ewm(span=10, adjust=False).mean()
        df['EMA_30'] = df['close'].ewm(span=30, adjust=False).mean()
        
        ema5 = df['EMA_5'].iloc[-1]
        ema10 = df['EMA_10'].iloc[-1]
        ema30 = df['EMA_30'].iloc[-1]

        # --- LÓGICA DE TENDENCIA Y SEÑALES ---
        trend_filter = "NEUTRAL"
        accion = "⏳ MERCADO LATERAL / ESPERAR"
        estrategia = "• Sin señal clara de cruce de EMAs."
        
        sl_long = round(precio_actual * 0.99, 2)
        tp_long = round(precio_actual * 1.02, 2)
        sl_short = round(precio_actual * 1.01, 2)
        tp_short = round(precio_actual * 0.98, 2)

        # Condición Alcista (Golden Cross aproximado con EMAs)
        if ema5 > ema10 and ema10 > ema30 and precio_actual > ema30:
            trend_filter = "ALCISTA (Impulso EMA)"
            accion = "🟢 COMPRA / LONG"
            estrategia = f"• **Entrada (Long):** ${precio_actual:,.2f}\n• **Stop Loss (SL):** ${sl_long:,.2f}\n• **Take Profit (TP):** ${tp_long:,.2f}"
            
        # Condición Bajista (Death Cross aproximado con EMAs)
        elif ema5 < ema10 and ema10 < ema30 and precio_actual < ema30:
            trend_filter = "BAJISTA (Caída EMA)"
            accion = "🔴 VENTA / SHORT"
            estrategia = f"• **Entrada (Short):** ${precio_actual:,.2f}\n• **Stop Loss (SL):** ${sl_short:,.2f}\n• **Take Profit (TP):** ${tp_short:,.2f}"

        # Cálculo de RSI
        cierres = df['close'].values
        cambios = [cierres[i] - cierres[i-1] for i in range(1, len(cierres))]
        ganancias = [c if c > 0 else 0 for c in cambios]
        perdidas = [-c if c < 0 else 0 for c in cambios]
        avg_ganancia = sum(ganancias[-14:]) / 14 if len(ganancias) >= 14 else 1
        avg_perdida = sum(perdidas[-14:]) / 14 if len(perdidas) >= 14 else 1
        if avg_perdida == 0: rsi = 100
        else: rs = avg_ganancia / avg_perdida; rsi = 100 - (100 / (1 + rs))

        maximos = df['high'].iloc[-20:].values
        minimos = df['low'].iloc[-20:].values
        resistencia = max(maximos)
        soporte = min(minimos)

        mensaje = (
            f"⚡ **FUTUROS KUCOIN: {symbol} (15m)**\n\n"
            f"💵 **Precio de Index/Mark:** ${precio_actual:,.2f}\n"
            f"📊 **Tendencia (EMA 5/10/30):** {trend_filter}\n"
            f"📈 **RSI (15m):** {rsi:.1f}\n\n"
            f"🧱 **Resistencia:** ${resistencia:,.2f}\n"
            f"🟡 **Soporte:** ${soporte:,.2f}\n\n"
            f"🎯 **SEÑAL DE ENTRADA:**\n{accion}\n{estrategia}\n\n"
            f"⚠️ *Usa gestión de riesgo y apalancamiento moderado.*"
        )
        return mensaje

    except Exception as e:
        return f"❌ Error al conectar con Futuros de KuCoin: {str(e)}"

def calcular_riesgo(capital_usdt, sl_porcentaje=1):
    try:
        capital = float(capital_usdt)
        riesgo_usd = capital * (sl_porcentaje / 100)
        return (
            f"🧮 **GESTIÓN DE RIESGO (FUTUROS)**\n\n"
            f"💰 **Capital:** ${capital:,.2f}\n"
            f"🛡️ **Riesgo Máximo ({sl_porcentaje}%):** ${riesgo_usd:,.2f}\n"
            f"💡 *Ajusta tu apalancamiento para que tu liquidación esté lejos del Stop Loss.*"
        )
    except ValueError:
        return "⚠️ Usa el formato correcto, por ejemplo: `/riesgo 1000`"

analyze_market = analizar_mercado_symbol
calculate_risk = calcular_riesgo
