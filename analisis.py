import ccxt

def analizar_mercado_symbol(symbol="BTC/USDT"):
    try:
        # Conectar específicamente a los FUTUROS de KuCoin
        exchange = ccxt.kucoinfutures()
        
        # El formato para futuros perpetuos en KuCoin con CCXT lleva ':USDT'
        target_symbol = f"{symbol}:USDT" if ":USDT" not in symbol else symbol
        
        ohlcv = exchange.fetch_ohlcv(target_symbol, timeframe='1h', limit=50)
        
        if not ohlcv or len(ohlcv) < 20:
            return f"⚠️ No hay suficientes datos en Futuros de KuCoin para {symbol}."

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

        # Definir niveles de entrada, Stop Loss y Take Profit para Futuros
        if rsi < 40:
            accion = "🟢 COMPRA / LONG (Sobreventa en Futuros)"
            sl = round(precio_actual * 0.985, 2)
            tp = round(precio_actual * 1.03, 2)
            estrategia = f"• **Entrada (Long):** ${precio_actual:,.2f}\n• **Stop Loss (SL):** ${sl:,.2f}\n• **Take Profit (TP):** ${tp:,.2f}"
        elif rsi > 60:
            accion = "🔴 VENTA / SHORT (Sobrecompra en Futuros)"
            sl = round(precio_actual * 1.015, 2)
            tp = round(precio_actual * 0.97, 2)
            estrategia = f"• **Entrada (Short):** ${precio_actual:,.2f}\n• **Stop Loss (SL):** ${sl:,.2f}\n• **Take Profit (TP):** ${tp:,.2f}"
        else:
            accion = "⏳ MERCADO LATERAL / ESPERAR"
            estrategia = "• Sin señal clara en el libro de futuros. Esperar ruptura."

        mensaje = (
            f"⚡ **FUTUROS KUCOIN: {symbol}**\n\n"
            f"💵 **Precio de Index/Mark:** ${precio_actual:,.2f}\n"
            f"📈 **RSI (1H):** {rsi:.1f}\n\n"
            f"🧱 **Resistencia:** ${resistencia:,.2f}\n"
            f"🟡 **Soporte:** ${soporte:,.2f}\n\n"
            f"🎯 **SEÑAL DE APALANCAMIENTO:**\n{accion}\n{estrategia}\n\n"
            f"⚠️ *Usa gestión de riesgo y apalancamiento moderado.*"
        )
        return mensaje

    except Exception as e:
        return f"❌ Error al conectar con Futuros de KuCoin: {str(e)}"

def calcular_riesgo(capital_usdt, sl_porcentaje=2):
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
