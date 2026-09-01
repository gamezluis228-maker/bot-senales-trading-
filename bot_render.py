@bot.message_handler(commands=['radar'])
def handle_radar(message):
    # Verificación opcional de tu whitelist de seguridad si ya la tienes en el archivo
    if message.from_user.id != TU_ID_DE_TELEGRAM:
        return
    
    # Ejecutamos la función de radar que trajimos desde analisis.py
    resultado_radar = radar_market()
    bot.reply_to(message, resultado_radar, parse_mode='Markdown')
