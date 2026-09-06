# --- 2. MOTOR DE EJECUCIÓN CON TP (8%) Y SL (4%) EN BINGX ---
def ejecutar_orden_bingx(symbol, mercado, side, margen_usdt):
    try:
        # Forzamos la lectura de las variables de entorno de Render directamente
        env_api_key = os.getenv("BINGX_API_KEY")
        env_secret_key = os.getenv("BINGX_SECRET_KEY")

        if not env_api_key or not env_secret_key:
            return False, 0, "ERROR NUEVO: Las variables BINGX_API_KEY o SECRET_KEY no se leen en Render."

        temp_exchange = ccxt.bingx({
            'apiKey': env_api_key,
            'secret': env_secret_key,
            'enableRateLimit': True,
            'options': {'defaultType': 'swap'}
        })

        if mercado == 'swap':
            market_symbol = f"{symbol}/USDT:USDT"
            temp_exchange.options['defaultType'] = 'swap'
            
            position_side = 'LONG' if side == 'buy' else 'SHORT'
            try:
                temp_exchange.set_leverage(5, market_symbol, {'side': position_side, 'marginCoin': 'USDT'})
            except:
                pass
        else:
            market_symbol = f"{symbol}/USDT"
            temp_exchange.options['defaultType'] = 'spot'
            position_side = None

        ticker = temp_exchange.fetch_ticker(market_symbol)
        precio_actual = ticker['last']
        amount_tokens = margen_usdt / precio_actual

        params = {}
        if mercado == 'swap':
            if side == 'buy':
                stop_loss_price = precio_actual * (1 - 0.04)
                take_profit_price = precio_actual * (1 + 0.08)
            else:
                stop_loss_price = precio_actual * (1 + 0.04)
                take_profit_price = precio_actual * (1 - 0.08)
            
            params['stopLossPrice'] = temp_exchange.price_to_precision(market_symbol, stop_loss_price)
            params['takeProfitPrice'] = temp_exchange.price_to_precision(market_symbol, take_profit_price)
            params['positionSide'] = position_side

        orden = temp_exchange.create_order(
            symbol=market_symbol,
            type='market',
            side=side,
            amount=amount_tokens,
            params=params
        )
        return True, precio_actual, orden
    except Exception as e:
        return False, 0, str(e)
