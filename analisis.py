import ccxt

def analizar_mercado_symbol(symbol="BTC/USDT"):
    try:
        exchange = ccxt.kucoin()
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe='1h', limit=50)
        
        if not ohlcv or len(ohlcv) < 20:
            return f"⚠️ No hay suficientes datos en KuCoin para {symbol}."

        cierres = [vela[4] for vela in ohlcv]
        precio_actual = cierres[-1]
        
        # Cálculo de RSI
        cambios = [cierres[i] - cierres[i-1] for i in range(1, len(cierres))]
        ganancias = [c if c > 0 else 0 for c in cambios]
        perdidas = [-c if c < 0 else 0 for c in cambios]
        
        avg_ganancia = sum(ganancias[-14:]) / 14 if len(ganancias) >= 14 else 1
        avg_perdida = sum(perdidas[-14:]) / 14 if len(perdidas) >= 14 else 1
        
        if avg_perdida == 0:
            rsi = 100
        else:
            rs = avg_ganancia / avg_perdida
            rsi = 100 - (100 / (1 + rs))

        maximos = [vela[2] for vela in ohlcv[-20:]]
        minimos = [vela[1] for vela in ohlcv[-20:]]
        resistencia = max(maximos)
        soporte = min(minimos)

        # Definir niveles según el RSI y precio
        if rsi < 40:
            accion = "🟢 COMPRA RECOMENDADA (LONG)"
            sl = round(precio_actual * 0.985, 2)
            tp = round(precio_actual * 1.03, 2)
            estrategia = f"• **Entrada:** ${precio_actual:,.2f}\n• **Stop Loss (SL):** ${sl:,.2f}\n• **Take Profit (TP):** ${tp:,.2f}"
        elif rsi > 60:
            accion = "🔴 VENTA RECOMENDADA (SHORT)"
            sl = round(precio_actual * 1.015, 2)
            tp = round(precio_actual * 0.97, 2)
            estrategia = f"• **Entrada:** ${precio_actual:,.2f}\n• **Stop Loss (SL):** ${sl:,.2f}\n• **Take Profit (TP):** ${tp:,.2f}"
        else:
            accion = "⏳ MERCADO LATERAL / ESPERAR"
            estrategia = "• Sin señal clara de entrada. Esperar ruptura de soporte o resistencia."

        mensaje = (
            f"📊 **ANÁLISIS KUCOIN: {symbol}**\n\n"
            f"💵 **Precio Actual:** ${precio_actual:,.2f}\n"
            f"📈 **RSI (1H):** {rsi:.1f}\n\n"
            f"🧱 **Resistencia:** ${resistencia:,.2f}\n"
            f"🟡 **Soporte:** ${soporte:,.2f}\n\n"
            f"🎯 **ESTRATEGIA:**\n{accion}\n{estrategia}\n\n"
            f"⚠️ *Gestiona tu riesgo adecuadamente (Max 2%).*"
        )
        return mensaje

    except Exception as e:
        return f"❌ Error al analizar en KuCoin: {str(e)}"

def calcular_riesgo(capital_usdt, sl_porcentaje=2):
    try:
        capital = float(capital_usdt)
        riesgo_usd = capital * (sl_porcentaje / 100)
        return (
            f"🧮 **GESTIÓN DE RIESGO**\n\n"
            f"💰 **Capital:** ${capital:,.2f}\n"
            f"🛡️ **Riesgo Máximo ({sl_porcentaje}%):** ${riesgo_usd:,.2f}\n"
            f"💡 *Protege tu capital operando con disciplina.*"
        )
    except ValueError:
        return "⚠️ Usa el formato correcto, por ejemplo: `/riesgo 1000`"

analyze_market = analizar_mercado_symbol
calculate_risk = calcular_riesgo
