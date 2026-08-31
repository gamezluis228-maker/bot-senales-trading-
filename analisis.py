import ccxt

def analizar_mercado_symbol(symbol="BTC/USDT"):
    try:
        # Conectar con KuCoin mediante CCXT para obtener datos reales del mercado
        exchange = ccxt.kucoin()
        
        # Obtener las últimas velas (Timeframe de 1 hora para análisis técnico)
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe='1h', limit=50)
        
        if not ohlcv or len(ohlcv) < 20:
            return f"⚠️ No se pudieron obtener suficientes datos de KuCoin para {symbol}."

        # Extraer precios de cierre
        cierres = [vela[4] for vela in ohlcv]
        precio_actual = cierres[-1]
        
        # Calcular un RSI básico de forma interna
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

        # Calcular soportes y resistencias dinámicos basados en máximos y mínimos recientes
        maximos = [vela[2] for vela in ohlcv[-20:]]
        minimos = [vela[1] for vela in ohlcv[-20:]]
        resistencia = max(maximos)
        soporte = min(minimos)

        # Lógica de recomendación de Trading basada en RSI y Acción de Precio
        accion = "⏳ ESPERAR (Mercado Lateral / Sin dirección clara)"
        estrategia = "El precio se encuentra operando en rango. Se recomienda esperar la ruptura de soportes o resistencias."
        
        # Distancias aproximadas para Stop Loss y Take Profit
        sl_compra = round(precio_actual * 0.985, 2)  # 1.5% abajo
        tp_compra = round(precio_actual * 1.03, 2)   # 3% arriba
        
        sl_venta = round(precio_actual * 1.015, 2)   # 1.5% arriba
        tp_venta = round(precio_actual * 0.97, 2)    # 3% abajo

        if rsi < 35:
            accion = "🟢 COMPRAR (LONG) - Sobreventa"
            estrategia = (
                f"• **Señal:** Posible rebote alcista por sobreventa en KuCoin.\n"
                f"• **Zona de Entrada:** ${precio_actual:,.2f}\n"
                f"• **Stop Loss (SL):** ${sl_compra:,.2f}\n"
                f"• **Take Profit (TP):** ${tp_compra:,.2f}"
            )
        elif rsi > 65:
            accion = "🔴 VENDER (SHORT) - Sobrecompra"
            estrategia = (
                f"• **Señal:** Posible caída o corrección por sobrecompra.\n"
                f"• **Zona de Entrada:** ${precio_actual:,.2f}\n"
                f"• **Stop Loss (SL):** ${sl_venta:,.2f}\n"
                f"• **Take Profit (TP):** ${tp_venta:,.2f}"
            )

        # Construir el mensaje final limpio y profesional
        mensaje = (
            f"📊 **ANÁLISIS INTELIGENTE KUCOIN: {symbol}**\n\n"
            f"💵 **Precio Actual:** ${precio_actual:,.2f}\n"
            f"📈 **RSI (1H):** {rsi:.1f}\n\n"
            f"🧱 **Resistencia:** ${resistencia:,.2f}\n"
            f"🟡 **Soporte:** ${soporte:,.2f}\n\n"
            f"🎯 **RECOMENDACIÓN:**\n{accion}\n\n"
            f"{estrategia}\n\n"
            f"⚠️ *Gestiona siempre tu riesgo adecuadamente.*"
        )
        return mensaje

    except Exception as e:
        return f"❌ Error al conectar con KuCoin: {str(e)}"

# Alias de compatibilidad por si el bot llama a calculate_risk o calcular_riesgo
def calcular_riesgo(capital_usdt, sl_porcentaje=2):
    try:
        capital = float(capital_usdt)
        riesgo_usd = capital * (sl_porcentaje / 100)
        msg = (
            f"🧮 **GESTIÓN DE RIESGO**\n\n"
            f"💰 **Capital Base:** ${capital:,.2f}\n"
            f"🛡️ **Riesgo por operación ({sl_porcentaje}%):** ${riesgo_usd:,.2f}\n"
            f"💡 *Recomendación:* No arriesgues más del 2% de tu cuenta total por posición."
        )
        return msg
    except ValueError:
        return "⚠️ Usa el formato correcto, por ejemplo: `/riesgo 1000`"

calculate_risk = calcular_riesgo
analyze_market = analizar_mercado_symbol
