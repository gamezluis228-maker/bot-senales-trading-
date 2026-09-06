import telebot
import ccxt
from flask import Flask

# Configuración inicial de tu bot y exchange (BingX)
bot = telebot.TeleBot("TU_TOKEN_DE_TELEGRAM")
exchange = ccxt.bingx({
    'apiKey': 'TU_API_KEY',
    'secret': 'TU_SECRET_KEY',
    'enableRateLimit': True,
    'options': {'defaultType': 'swap'} # Por defecto futuros perpetuos
})

# --- FUNCIÓN DE ANÁLISIS Y EJECUCIÓN CON STOP LOSS ---
def procesar_operacion_segura(symbol, tipo_mercado, side, amount_usdt):
    try:
        # 1. Ajustar el símbolo según el mercado (Swap o Spot)
        if tipo_mercado == 'swap':
            market_symbol = f"{symbol}:USDT"
            exchange.options['defaultType'] = 'swap'
            exchange.set_leverage(5, market_symbol) # Apalancamiento base
        else:
            market_symbol = symbol
            exchange.options['defaultType'] = 'spot'

        # 2. Obtener el precio actual del mercado
        ticker = exchange.fetch_ticker(market_symbol)
        precio_actual = ticker['last']

        # 3. Calcular la cantidad de tokens según el margen elegido ($1 a $20)
        amount_tokens = amount_usdt / precio_actual

        # 4. Configurar el Stop Loss estricto al 4%
        params = {}
        if tipo_mercado == 'swap':
            if side == 'buy':
                stop_loss_price = precio_actual * (1 - 0.04) # 4% abajo
            else:
                stop_loss_price = precio_actual * (1 + 0.04) # 4% arriba
            
            params['stopLossPrice'] = exchange.price_to_precision(market_symbol, stop_loss_price)

        # 5. Ejecutar la orden en BingX
        orden = exchange.create_order(
            symbol=market_symbol,
            type='market',
            side=side,
            amount=amount_tokens,
            params=params
        )
        
        return True, precio_actual, orden
    except Exception as e:
        return False, 0, str(e)

# --- COMANDO EN TELEGRAM PARA DISPARAR LA OPERACIÓN ---
@bot.callback_query_handler(func=lambda call: True)
attr_callback(call):
    # Aquí es donde el usuario selecciona la moneda y el tipo de mercado (Spot o Futuros)
    datos = call.data.split("_") # Ejemplo: "APT_swap_buy_10"
    simbolo = datos[0]
    mercado = datos[1]  # 'swap' o 'spot'
    accion = datos[2]   # 'buy' o 'sell'
    margen = float(datos[3]) # Entre 1 y 20 USDT

    bot.answer_callback_query(call.id, "Ejecutando validaciones y orden...")

    # Ejecutar la orden con la función segura
    exito, precio, resultado = procesar_operacion_segura(simbolo, mercado, accion, margen)

    if exito:
        bot.send_message(
            call.message.chat.id, 
            f"✅ **¡Operación Exitosa en BingX!**\n\n"
            f"• Activo: {simbolo}\n"
            f"• Mercado: {mercado.upper()}\n"
            f"• Margen: ${margen} USDT\n"
            f"• Precio de entrada: {precio}\n"
            f"• Stop Loss (4%): Activado 🛡️"
        )
    else:
        bot.send_message(call.message.chat.id, f"❌ Error al ejecutar la orden: {resultado}")
        
