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
            estrategia = f"• **Entrada (Short):** ${precio_actual:,.2f}\n• **Stop Loss (SL):** ${sl_short:,.2f}\n• **Take Profit (TP):** ${tp_short:,.2f}"
        elif ema9 > ema21 and es_alcista_1h:
            trend_filter = "Impulso Alcista Sólido (1H + 15m)"
            accion = "🟢 COMPRA / LONG (EMA 9 > 21)"
            estrategia = f"• **Entrada (Long):** ${precio_actual:,.2f}\n• **Stop Loss (SL):** ${sl_long:,.2f}\n• **Take Profit (TP):** ${tp_long:,.2f}"
        elif ema9 < ema21 and not es_alcista_1h:
            trend_filter = "Impulso Bajista Sólido (1H + 15m)"
            accion = "🔴 VENTA / SHORT (EMA 9 < 21)"
            estrategia = f"• **Entrada (Short):** ${precio_actual:,.2f}\n• **Stop Loss (SL):** ${sl_short:,.2f}\n• **Take Profit (TP):** ${tp_short:,.2f}"

        # Cálculo de RSI clásico (14)
        cierres = df_15m['close'].values
        cambios = [cierres[i] - cierres[i-1] for i in range(1, len(cierres))]
        ganancias = [c if c > 0 else 0 for c in cambios]
        perdidas = [-c if c < 0 else 0 for c in cambios]
        avg_ganancia = sum(ganancias[-14:]) / 14 if len(ganancias) >= 14 else 1
        avg_perdida = sum(perdidas[-14:]) / 14 if len(perdidas) >= 14 else 1
        rsi = 100 if avg_perdida == 0 else 100 - (100 / (1 + (avg_ganancia / avg_perdida)))

        mensaje = (
            f"⚡ **FUTUROS BINGX: {symbol}**\n\n"
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

def radar_market():
    # Lista ampliada con las 15 criptomonedas más volátiles y de mayor volumen en BingX Futuros
    symbols = [
        "BTC/USDT", "ETH/USDT", "SOL/USDT", "XRP/USDT", "ZEC/USDT",
        "NEAR/USDT", "APT/USDT", "SUI/USDT", "DOGE/USDT", "AVAX/USDT",
        "RENDER/USDT", "PEPE/USDT", "LINK/USDT", "FET/USDT", "INJ/USDT"
    ]
    oportunidades = []
    
    try:
        exchange = ccxt.bingx({
            'enableRateLimit': True,
            'timeout': 5000,
        })
        for symbol in symbols:
            target_symbol = f"{symbol}:USDT"
            try:
                ohlcv_15m = exchange.fetch_ohlcv(target_symbol, timeframe='15m', limit=50)
                if not ohlcv_15m or len(ohlcv_15m) < 30:
                    continue
                    
                df = pd.DataFrame(ohlcv_15m, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                precio = df['close'].iloc[-1]
                
                ema9 = df['close'].ewm(span=9, adjust=False).mean().iloc[-1]
                ema21 = df['close'].ewm(span=21, adjust=False).mean().iloc[-1]
                
                vol_prom = df['volume'].rolling(window=15).mean().iloc[-1]
                vol_act = df['volume'].iloc[-1]
                
                if ema9 > ema21 and vol_act > (vol_prom * 1.1):
                    oportunidades.append(f"🟢 **{symbol}**: Alcista con Volumen (${precio:,.2f})")
                elif ema9 < ema21 and vol_act > (vol_prom * 1.1):
                    oportunidades.append(f"🔴 **{symbol}**: Bajista con Volumen (${precio:,.2f})")
            except Exception:
                continue
                
        if not oportunidades:
            return None
            
        return "📡 **¡ALERTA DE OPORTUNIDAD INSTITUCIONAL!**:\n\n" + "\n".join(oportunidades)
        
    except Exception as e:
        return None

def calculate_risk(margen_usdt=10, symbol="BTC/USDT", sl_porcentaje=1):
    try:
        margen = float(margen_usdt)
        
        exchange = ccxt.bingx({
            'enableRateLimit': True,
            'timeout': 5000,
        })
        target_symbol = f"{symbol}:USDT" if ":USDT" not in symbol else symbol
        ohlcv = exchange.fetch_ohlcv(target_symbol, timeframe='15m', limit=30)
        
        if ohlcv and len(ohlcv) >= 14:
            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            precio = df['close'].iloc[-1]
            tr0 = abs(df['high'] - df['low'])
            tr1 = abs(df['high'] - df['close'].shift())
            tr2 = abs(df['low'] - df['close'].shift())
            tr = pd.concat([tr0, tr1, tr2], axis=1).max(axis=1)
            atr = tr.rolling(window=14).mean().iloc[-1]
            volatility_pct = (atr / precio) * 100
        else:
            volatility_pct = 0.3

        if volatility_pct > 0.5:
            base_lev = 10
        elif volatility_pct > 0.25:
            base_lev = 15
        else:
            base_lev = 20

        if margen <= 15:
            apalancamiento_sugerido = min(base_lev + 5, 25)
        elif margen <= 50:
            apalancamiento_sugerido = base_lev
        else:
            apalancamiento_sugerido = max(base_lev // 2, 5)

        riesgo_usd = margen * (float(sl_porcentaje) / 100)
        posicion_total = margen * apalancamiento_sugerido

        return (
            f"🧮 **GESTIÓN DE RIESGO INTELIGENTE (Adaptativa)**\n\n"
            f"🪙 **Activo Analizado:** {symbol}\n"
            f"💵 **Margen Asignado:** ${margen:,.2f}\n"
            f"📊 **Volatilidad del Mercado (ATR %):** {volatility_pct:.2f}%\n"
            f"⚡ **Apalancamiento Sugerido:** {apalancamiento_sugerido}x\n"
            f"🛡️ **Riesgo Máximo ({sl_porcentaje}%):** ${riesgo_usd:,.2f}\n"
            f"🎯 **Tamaño de Posición Total:** ${posicion_total:,.2f}\n"
            f"💡 *Apalancamiento ajustado en tiempo real según la volatilidad y tu margen.*"
        )
    except Exception as e:
        return f"⚠️ Error al calcular riesgo: {str(e)}. Usa el formato: `/riesgo 10`"
            
