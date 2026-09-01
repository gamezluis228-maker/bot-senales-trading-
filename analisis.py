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
            
            if ema5 > ema10 and ema10 > ema30 and vol_act > (vol_prom * 1.1):
                oportunidades.append(f"🟢 **{symbol}**: Tendencia Alcista con Volumen (Precio: ${precio:,.2f})")
            elif ema5 < ema10 and ema10 < ema30 and vol_act > (vol_prom * 1.1):
                oportunidades.append(f"🔴 **{symbol}**: Tendencia Bajista con Volumen (Precio: ${precio:,.2f})")
                
        if not oportunidades:
            return None  # Retorna vacío para que el automático se calle
            
        return "📡 **¡ALERTA DE OPORTUNIDAD INSTITUCIONAL!**:\n\n" + "\n".join(oportunidades)
        
    except Exception as e:
        return None
