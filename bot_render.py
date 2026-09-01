@bot.message_handler(commands=['radar'])
def handle_radar(message):
    bot.reply_to(message, "📡 *Escaneando altcoins en KuCoin...*", parse_mode='Markdown')
    resultado_radar = radar_market()
    
    if resultado_radar:
        bot.reply_to(message, resultado_radar, parse_mode='Markdown')
    else:
        bot.reply_to(message, "📡 **RADAR DE MERCADO**: Ninguna altcoin cumple con los filtros estrictos en este momento. Mercado lateral o en pausa.", parse_mode='Markdown')

@bot.message_handler(commands=['riesgo'])
def handle_riesgo(message):
    try:
        partes = message.text.split()
        
        # Si el usuario solo escribió "/riesgo" sin darle el margen, le exigimos el valor
        if len(partes) < 2:
            bot.reply_to(message, "⚠️ **Debes indicar tu margen.**\nEjemplo correcto:\n• `/riesgo 10`\n• `/riesgo 15 ETH`", parse_mode='Markdown')
            return
            
        margen = partes[1]
        symbol = partes[2].upper() if len(partes) > 2 else "BTC/USDT"
        if not symbol.endswith("/USDT"):
            symbol += "/USDT"
            
        resultado = calculate_risk(margen_usdt=margen, symbol=symbol)
        bot.reply_to(message, resultado, parse_mode='Markdown')
    except Exception as e:
        bot.reply_to(message, "⚠️ Usa el formato correcto, por ejemplo: `/riesgo 10` o `/riesgo 10 ETH`", parse_mode='Markdown')
