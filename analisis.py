def escanear_radar():
    symbols = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "XRP/USDT"]
    oportunidades = []
    
    try:
        exchange = ccxt.kucoinfutures({
            'enableRateLimit': True,
            'timeout': 5000, # Límite de 5 segundos para que no se quede colgado
        })
        
        for symbol in symbols:
            target_symbol = f"{symbol}:USDT"
            try:
                ohlcv_15m = exchange.fetch_ohlcv(target_symbol, timeframe='15m', limit=50)
                if not ohlcv_15m or len(ohlcv_15m) < 30:
                    continue
                    
                df = pd.DataFrame(ohlcv_15m, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                precio = df['close'].iloc[-1]
                
                ema5 = df['close'].ewm(span=5, adjust=False).mean().iloc[-1]
                ema10 = df['close'].ewm(span=10, adjust=False).mean().iloc[-1]
                ema30 = df['close'].ewm(span=30, adjust=False).mean().iloc[-1]
                
                vol_prom = df['volume'].rolling(window=15).mean().iloc[-1]
                vol_act = df['volume'].iloc[-1]
                
                if ema5 > ema10 and ema10 > ema30 and vol_act > (vol_prom * 1.1):
                    oportunidades.append(f"🟢 **{symbol}**: Alcista con Volumen (${precio:,.2f})")
                elif ema5 < ema10 and ema10 < ema30 and vol_act > (vol_prom * 1.1):
                    oportunidades.append(f"🔴 **{symbol}**: Bajista con Volumen (${precio:,.2f})")
            except Exception:
                continue # Si falla una altcoin, salta a la siguiente sin congelar el bot
                
        if not oportunidades:
            return "📡 **RADAR DE MERCADO**: Las altcoins están en rango o sin suficiente volumen institucional en este momento."
            
        return "📡 **¡ALERTA DE OPORTUNIDAD EN ALTOCOINS!**:\n\n" + "\n".join(oportunidades)
        
    except Exception as e:
        return "📡 **RADAR**: El mercado está temporalmente inaccesible o en pausa."
