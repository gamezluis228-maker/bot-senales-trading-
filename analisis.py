import ccxt
import pandas as pd
import pandas_ta as ta # Se ha añadido esta librería. Debes incluir 'pandas_ta' en tu requirements.txt

def analizar_mercado_symbol(symbol="BTC/USDT"):
    try:
        # Conectar a los FUTUROS de KuCoin
        exchange = ccxt.kucoinfutures()
        target_symbol = f"{symbol}:USDT" if ":USDT" not in symbol else symbol
        
        # --- CAMBIO IMPORTANTE: Timeframe a 15m (como en tu captura) ---
        # Aumentamos el límite a 100 velas para tener suficiente historial para las EMAs
        ohlcv = exchange.fetch_ohlcv(target_symbol, timeframe='15m', limit=100)
        
        if not ohlcv or len(ohlcv) < 50: # Aumentamos el mínimo de velas de seguridad
            return f"⚠️ No hay suficientes datos en Futuros de KuCoin para {symbol} (se necesitan al menos 50 velas de 15m)."

        # Convertimos los datos a un DataFrame de Pandas para facilitar los cálculos
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        
        precio_actual = df['close'].iloc[-1]

        # --- CÁLCULO DE EMAs (EMA 5, 10, 30) ---
        df.ta.ema(length=5, append=True)
        df.ta.ema(length=10, append=True)
        df.ta.ema(length=30, append=True)
        
        ema5 = df['EMA_5'].iloc[-1]
        ema10 = df['EMA_10'].iloc[-1]
        ema30 = df['EMA_30'].iloc[-1]

        # --- LÓGICA DE ENTRADA CON FILTRO DE EMAs ---
        trend_filter = "NEUTRAL"
        accion = "⏳ MERCADO LATERAL / ESPERAR"
        estrategia = "• Sin señal clara de cruce de EMAs."
        
        # Definir niveles de entrada, Stop Loss y Take Profit (ejemplos estándar para scalping)
        sl_long = round(precio_actual * 0.99, 2) # Stop Loss más ajustado para scalping
        tp_long = round(precio_actual * 1.02, 2) # Take Profit más ajustado para scalping
        sl_short = round(precio_actual * 1.01, 2)
        tp_short = round(precio_actual * 0.98, 2)

        # Condición de Golden Cross (Compra)
        if ema5 > ema10 and ema10 > ema30 and precio_actual > ema30:
            trend_filter = "ALCISTA (Golden Cross)"
            accion = "🟢 COMPRA / LONG (Inicio de impulso)"
            estrategia = f"• **Entrada (Long):** ${precio_actual:,.2f}\n• **Stop Loss (SL):** ${sl_long:,.2f}\n• **Take Profit (TP):** ${tp_long:,.2f}"
            
        # Condición de Death Cross (Venta)
        elif ema5 < ema10 and ema10 < ema30 and precio_actual < ema30:
            trend_filter = "BAJISTA (Death Cross)"
            accion = "🔴 VENTA / SHORT (Inicio de caída)"
            estrategia = f"• **Entrada (Short):** ${precio_actual:,.2f}\n• **Stop Loss (SL):** ${sl_short:,.2f}\n• **Take Profit (TP):** ${tp_short:,.2f}"

        # --- Cálculo de RSI (1H para contexto, o 15m para scalping puro. Usemos 1h para contexto) ---
        cierres = df['close'].values
        cambios = [cierres[i] - cierres[i-1] for i in range(1, len(cierres))]
        ganancias = [c if c > 0 else 0 for c in cambios]
        perdidas = [-c if c < 0 else 0 for c in cambios]
        avg_ganancia = sum(ganancias[-14:]) / 14
        avg_perdida = sum(perdidas[-14:]) / 14
        if avg_perdida == 0: rsi = 100
        else: rs = avg_ganancia / avg_perdida; rsi = 100 - (100 / (1 + rs))

        maximos = df['high'].iloc[-20:].values # Resistencia de 20 velas de 15m (5h)
        minimos = df['low'].iloc[-20:].values  # Soporte de 20 velas de 15m (5h)
        resistencia = max(maximos)
        soporte = min(minimos)

        # Mensaje final con el nuevo formato adaptado a tu gráfico
        mensaje = (
            f"⚡ **FUTUROS KUCOIN: {symbol} (15m)**\n\n"
            f"💵 **Precio de Index/Mark:** ${precio_actual:,.2f}\n"
            f"📊 **Filtro de Tendencia (EMA):** {trend_filter}\n"
            f"📈 **RSI (15m):** {rsi:.1f}\n\n"
            f"🧱 **Resistencia (5h):** ${resistencia:,.2f}\n"
            f"🟡 **Soporte (5h):** ${soporte:,.2f}\n\n"
            f"🎯 **SEÑAL DE ENTRADA (EMA 5/10):**\n{accion}\n{estrategia}\n\n"
            f"⚠️ *Usa gestión de riesgo y apalancamiento moderado.*"
        )
        return mensaje

    except Exception as e:
        return f"❌ Error al conectar con Futuros de KuCoin (asegúrate de tener pandas_ta): {str(e)}"

def calcular_riesgo(capital_usdt, sl_porcentaje=1): # Ajustado por defecto a 1% para scalping
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

    