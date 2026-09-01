import time
import telebot
from analisis import analyze_market, calculate_risk, radar_market

TOKEN = "7983691656:AAHEfXF1W2x1W2x... (tu token real)"
TU_CHAT_ID = "tu_chat_id_real"

bot = telebot.TeleBot(TOKEN)

@bot.message_handler(commands=['start'])
def handle_start(message):
    bot.reply_to(message, "🤖 ¡Bot de Trading Activo!\nComandos disponibles:\n• `/analisis BTC/USDT`\n• `/riesgo 10`\n• `/radar`", parse_mode='Markdown')

@bot.message_handler(commands=['analisis'])
def handle_analisis(message):
    try:
        partes = message.text.split()
        symbol = partes[1].upper() if len(partes) > 1 else "BTC/USDT"
        if not symbol.endswith("/USDT"):
            symbol += "/USDT"
            
        bot.reply_to(message, f"🔍 Analizando {symbol} en KuCoin Futuros...", parse_mode='Markdown')
        resultado = analyze_market(symbol)
        bot.reply_to(message, resultado, parse_mode='Markdown')
    except Exception as e:
        bot.reply_to(message, "⚠️ Uso correcto: `/analisis ETH/USDT`", parse_mode='Markdown')

@bot.message_handler(commands=['riesgo'])
def handle_riesgo(message):
    try:
        partes = message.text.split()
        if len(partes) < 2:
            bot.reply_to(message, "⚠️ **Debes indicar tu margen.**\nEjemplo:\n• `/riesgo 10`\n• `/riesgo 15 ETH`", parse_mode='Markdown')
            return
            
        margen = partes[1]
        symbol = partes[2].upper() if len(partes) > 2 else "BTC/USDT"
        if not symbol.endswith("/USDT"):
            symbol += "/USDT"
            
        resultado = calculate_risk(margen_usdt=margen, symbol=symbol)
        bot.reply_to(message, resultado, parse_mode='Markdown')
    except Exception as e:
        bot.reply_to(message, "⚠️ Usa el formato correcto, por ejemplo: `/riesgo 10`", parse_mode='Markdown')

@bot.message_handler(commands=['radar'])
def handle_radar(message):
    bot.reply_to(message, "📡 *Escaneando altcoins en KuCoin...*", parse_mode='Markdown')
    resultado_radar = radar_market()
    
    if resultado_radar:
        bot.reply_to(message, resultado_radar, parse_mode='Markdown')
    else:
        bot.reply_to(message, "📡 **RADAR DE MERCADO**: Ninguna altcoin cumple con los filtros estrictos en este momento. Mercado en calma.", parse_mode='Markdown')

def background_auto_analyzer():
    time.sleep(30)
    while True:
        try:
            bot.send_message(TU_CHAT_ID, "⏰ **REPORTE AUTOMÁTICO (15M)**\n*Revisando pulso de Bitcoin...*", parse_mode='Markdown')
            resultado_btc = analyze_market("BTC/USDT")
            bot.send_message(TU_CHAT_ID, resultado_btc, parse_mode='Markdown')
        except Exception as e:
            print(f"Error en tarea automática: {e}")
        
        time.sleep(900)

if __name__ == '__main__':
    import threading
    hilo_auto = threading.Thread(target=background_auto_analyzer)
    hilo_auto.daemon = True
    hilo_auto.start()
    
    print("Bot iniciado correctamente y escuchando...")
    bot.infinity_polling()
