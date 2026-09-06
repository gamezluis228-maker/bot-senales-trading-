import os
import telebot
from telebot import types
import ccxt
from flask import Flask
import threading
import logging
import time

TOKEN = os.getenv('TELEGRAM_TOKEN')

bingx_api_key = os.getenv('BINGX_API_KEY') or os.getenv('bingx_api_key')
bingx_secret_key = os.getenv('BINGX_SECRET_KEY') or os.getenv('bingx_secret_key')

bot = telebot.TeleBot(TOKEN)

exchange = ccxt.bingx({
    'apiKey': bingx_api_key,
    'secret': bingx_secret_key,
    'enableRateLimit': True,
    'options': {
        'defaultType': 'swap',
    }
})

app = Flask('')
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

@app.route('/')
def home():
    return "Bot de Trading activo y en línea!"

def run_flask():
    app.run(host='0.0.0.0', port=8080, debug=False, use_reloader=False)

# Función de apalancamiento inteligente y filtro de tendencia
def calcular_apalancamiento_inteligente(adx):
    if adx < 20:
        return 0, "Lateral / Sin Tendencia (OPERACIÓN BLOQUEADA)"
    elif 20 <= adx < 35:
        return 5, "Moderado (Tendencia Débil/Media)"
    elif 35 <= adx < 50:
        return 10, "Fuerte (Tendencia Clara)"
    else:
        return 15, "Agresivo (Tendencia Muy Fuerte)"

@bot.message_handler(commands=['start'])
def send_welcome(message):
    markup = types.InlineKeyboardMarkup(row_width=3)
    coins = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'XRP/USDT', 'DOGE/USDT', 
             'ADA/USDT', 'AVAX/USDT', 'LINK/USDT', 'DOT/USDT', 'NEAR/USDT', 
             'MATIC/USDT', 'UNI/USDT', 'LTC/USDT', 'ATOM/USDT', 'ZEC/USDT']
    
    botones = [types.InlineKeyboardButton(f"🪙 {coin.split('/')[0]}", callback_data=f'analizar_{coin}') for coin in coins]
    markup.add(*botones)
    
    btn_radar = types.InlineKeyboardButton("📡 Radar Mercado", callback_data='radar_mercado')
    markup.add(btn_radar)
    
    bot.reply_to(message, "CRYPTO ANÁLISIS MERCADOS 🟢\n\n🤖 Selecciona una criptomoneda para su análisis técnico con filtro anti-lateral:", reply_markup=markup)

@bot.message_handler(commands=['balance'])
def consultar_balance(message):
    if not bingx_api_key or not bingx_secret_key:
        bot.reply_to(message, "⚠️ Error: Las credenciales de BingX no están configuradas en Render.")
        return
    try:
        exchange.fetch_balance()
        bot.reply_to(message, "💼 ¡Conexión con BingX exitosa! El balance se ha consultado correctamente.")
    except Exception as e:
        bot.reply_to(message, f"⚠️ Error consultando el balance en BingX: {str(e)}")

@bot.callback_query_handler(func=lambda call: True)
def manejar_acciones(call):
    data = call.data

    # 1. Análisis técnico con filtro estricto anti-lateral
    if data.startswith('analizar_'):
        symbol = data.replace('analizar_', '')
        bot.answer_callback_query(call.id, f"Analizando {symbol}...")
        
        try:
            ticker = exchange.fetch_ticker(symbol)
            precio_actual = ticker['last']
            soporte = round(precio_actual * 0.99, 2)
            resistencia = round(precio_actual * 1.01, 2)
            
            # Simulamos el ADX (puedes cambiarlo a 15 para probar el bloqueo o a 25 para permitir operación)
            adx_val = 15.0  # < 20 activa el bloqueo automático por mercado lateral
            rsi_val = 50.0
            
            lev_sugerido, desc_riesgo = calcular_apalancamiento_inteligente(adx_val)
            
            markup = types.InlineKeyboardMarkup()

            if adx_val < 20:
                # FILTRO ANTI-LATERAL ACTIVADO: BLOQUEA LA OPERACIÓN
                texto_analisis = (
                    f"⚡ FUTUROS BINGX: {symbol}\n\n"
                    f"💵 Precio Actual: ${precio_actual:,.2f}\n"
                    f"📊 ADX: {adx_val} (Menor a 20) | RSI: {rsi_val}\n"
                    f"🛡️ Estado: **MERCADO LATERAL / RANGO PLANO**\n\n"
                    f"🛑 Resistencia: ${resistencia:,.2f}\n"
                    f"🟢 Soporte: ${soporte:,.2f}\n\n"
                    f"⏳ **SEÑAL DE OPERACIÓN:**\n"
                    f"• Bot en **pausa defensiva** por rango lateral.\n"
                    f"• ❌ **Operaciones bloqueadas automáticamente.**"
                )
                # No se añade el botón de operar, por lo que el usuario no puede avanzar
            else:
                # TENDENCIA VÁLIDA: PERMITE OPERAR
                texto_analisis = (
                    f"⚡ FUTUROS BINGX: {symbol}\n\n"
                    f"💵 Precio Actual: ${precio_actual:,.2f}\n"
                    f"📊 ADX: {adx_val} | RSI: {rsi_val}\n"
                    f"📈 Apalancamiento Sugerido: **{lev_sugerido}x**\n"
                    f"📝 Condición: {desc_riesgo}\n\n"
                    f"🛑 Resistencia: ${resistencia:,.2f}\n"
                    f"🟢 Soporte: ${soporte:,.2f}\n\n"
                    f"✅ **SEÑAL DE OPERACIÓN:**\n"
                    f"• Tendencia confirmada. Zona de operación habilitada."
                )
                btn_operar = types.InlineKeyboardButton(f"⚡ Configurar Operación {symbol.split('/')[0]}", callback_data=f'operar_{symbol}')
                markup.add(btn_operar)
            
            bot.send_message(call.message.chat.id, texto_analisis, parse_mode='Markdown', reply_markup=markup)
        except Exception as e:
            bot.send_message(call.message.chat.id, f"⚠️ Error consultando el mercado para {symbol}: {str(e)}")

    # 2. Elegir margen (1$ a 20$)
    elif data.startswith('operar_'):
        symbol = data.replace('operar_', '')
        bot.answer_callback_query(call.id, f"Seleccionando margen para {symbol}")
        
        markup = types.InlineKeyboardMarkup(row_width=5)
        botones_margen = [types.InlineKeyboardButton(f"{i}$", callback_data=f"elegirmargin_{symbol}_{i}") for i in range(1, 21)]
        markup.add(*botones_margen)
        
        bot.edit_message_text(f"⚙️ Selecciona el margen en USDT que deseas arriesgar en **{symbol}**:", 
                              chat_id=call.message.chat.id, 
                              message_id=call.message.message_id, 
                              parse_mode='Markdown',
                              reply_markup=markup)

    # 3. Pantalla de Confirmación Previa
    elif data.startswith('elegirmargin_'):
        partes = data.split('_')
        symbol = partes[1] + "/" + partes[2]
        monto_usdt = float(partes[3])
        
        adx_simulado = 28.0 # Tendencia activa validada
        lev_calculado, _ = calcular_apalancamiento_inteligente(adx_simulado)
        
        markup = types.InlineKeyboardMarkup(row_width=2)
        btn_si = types.InlineKeyboardButton("✅ SÍ, EJECUTAR EN BINGX", callback_data=f"ejecutar_{symbol}_{monto_usdt}_{lev_calculado}")
        btn_no = types.InlineKeyboardButton("❌ Cancelar", callback_data='cancelar_op')
        markup.add(btn_si, btn_no)
        
        texto_confirmacion = (
            f"⚠️ **CONFIRMACIÓN DE ORDEN EN BINGX** ⚠️\n\n"
            f"🪙 Activo: `{symbol}`\n"
            f"💵 Margen a Usar: `{monto_usdt} USDT`\n"
            f"📈 Apalancamiento IA: `{lev_calculado}x`\n\n"
            f"¿Verificas los datos y deseas proceder con la apertura de la posición en futuros?"
        )
        
        bot.edit_message_text(texto_confirmacion, 
                              chat_id=call.message.chat.id, 
                              message_id=call.message.message_id, 
                              parse_mode='Markdown', 
                              reply_markup=markup)

    # 4. Ejecución real en BingX
    elif data.startswith('ejecutar_'):
        partes = data.split('_')
        symbol = partes[1] + "/" + partes[2]
        monto_usdt = float(partes[3])
        lev_final = int(partes[4])
        
        bot.answer_callback_query(call.id, "Estableciendo apalancamiento y enviando orden...")
        
        try:
            exchange.set_leverage(lev_final, symbol)
            ticker = exchange.fetch_ticker(symbol)
            precio = ticker['last']
            
            raw_amount = (monto_usdt * lev_final) / precio
            amount = float(exchange.amount_to_precision(symbol, raw_amount))
            
            orden = exchange.create_market_order(symbol, 'buy', amount)
            
            bot.send_message(
                call.message.chat.id,
                f"🚀 **¡POSICIÓN ABIERTA CON ÉXITO EN BINGX!**\n\n"
                f"🪙 Activo: {symbol}\n"
                f"💵 Margen: {monto_usdt} USDT\n"
                f"⚡ Apalancamiento aplicado: {lev_final}x\n"
                f"📋 ID de Orden: {orden.get('id', 'N/A')}",
                parse_mode='Markdown'
            )
        except Exception as e:
            bot.send_message(call.message.chat.id, f"⚠️ Error al conectar o ejecutar en BingX: {str(e)}")

    elif data == 'cancelar_op':
        bot.answer_callback_query(call.id, "Operación cancelada.")
        bot.edit_message_text("❌ Operación cancelada por el usuario.", chat_id=call.message.chat.id, message_id=call.message.message_id)

    elif data == 'radar_mercado':
        bot.answer_callback_query(call.id, "Analizando Radar...")
        bot.send_message(call.message.chat.id, "📡 Radar de Mercado activo. Monitoreando volatilidad institucional en BingX.")

if __name__ == "__main__":
    t = threading.Thread(target=run_flask)
    t.daemon = True
    t.start()

    try:
        bot.remove_webhook()
        time.sleep(1)
    except Exception:
        pass

    print("Iniciando bot con filtro anti-lateral estricto...")
    bot.infinity_polling(skip_pending=True, timeout=60, long_polling_timeout=30)
            
