import os
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from analisis import analyze_market, radar_market, calculate_risk

TOKEN = os.getenv("TELEGRAM_TOKEN")
if not TOKEN:
    raise ValueError("⚠️ No se encontró el TELEGRAM_TOKEN en las variables de entorno.")

bot = telebot.TeleBot(TOKEN)

# 15 Activos del radar
SYMBOLS = [
    "BTC/USDT", "ETH/USDT", "SOL/USDT", "XRP/USDT", "ZEC/USDT",
    "NEAR/USDT", "APT/USDT", "SUI/USDT", "DOGE/USDT", "AVAX/USDT",
    "RENDER/USDT", "PEPE/USDT", "LINK/USDT", "FET/USDT", "INJ/USDT"
]

def get_main_keyboard():
    markup = InlineKeyboardMarkup(row_width=2)
    for i in range(0, len(SYMBOLS), 2):
        row = [InlineKeyboardButton(SYMBOLS[i], callback_data=f"analyze_{SYMBOLS[i]}")]
        if i + 1 < len(SYMBOLS):
            row.append(InlineKeyboardButton(SYMBOLS[i+1], callback_data=f"analyze_{SYMBOLS[i+1]}"))
        markup.row(*row)
    markup.row(InlineKeyboardButton("📡 Radar Mercado (15 Activos)", callback_data="radar_all"))
    return markup

def get_margin_keyboard(symbol):
    """Crea la cuadrícula de botones de 1 a 20 USDT para seleccionar margen."""
    markup = InlineKeyboardMarkup(row_width=5)
    # Filas de 1 a 20 USDT organizadas en 5 columnas
    row1 = [InlineKeyboardButton(f"{i}$", callback_data=f"margin_{i}_{symbol}") for i in range(1, 6)]
    row2 = [InlineKeyboardButton(f"{i}$", callback_data=f"margin_{i}_{symbol}") for i in range(6, 11)]
    row3 = [InlineKeyboardButton(f"{i}$", callback_data=f"margin_{i}_{symbol}") for i in range(11, 16)]
    row4 = [InlineKeyboardButton(f"{i}$", callback_data=f"margin_{i}_{symbol}") for i in range(16, 21)]
    
    markup.row(*row1)
    markup.row(*row2)
    markup.row(*row3)
    markup.row(*row4)
    markup.row(InlineKeyboardButton("⚡ Confirmar y Ejecutar en BingX", callback_data=f"exec_{symbol}"))
    return markup

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    texto = (
        "🤖 **BÓT PROFESIONAL DE SEÑALES Y RIESGO**\n\n"
        "Selecciona abajo la criptomoneda que deseas analizar en vivo o lanza el radar global para barrer el mercado con el filtro ADX:"
    )
    bot.send_message(message.chat.id, texto, reply_markup=get_main_keyboard(), parse_mode="Markdown")

@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    data = call.data
    chat_id = call.message.chat.id
    
    if data == "radar_all":
        bot.answer_callback_query(call.id, "Escaneando las 15 criptomonedas...")
        bot.send_message(chat_id, "📡 Escaneando el mercado institucional con filtro ADX...")
        resultado_radar = radar_market()
        if resultado_radar:
            bot.send_message(chat_id, resultado_radar, parse_mode="Markdown")
        else:
            bot.send_message(chat_id, "📡 **RADAR:** Las altcoins están en rango actualmente o sin suficiente volumen. Pausa defensiva activa.", parse_mode="Markdown")
            
    elif data.startswith("analyze_"):
        symbol = data.replace("analyze_", "")
        bot.answer_callback_query(call.id, f"Analizando {symbol}...")
        
        # Primero enviamos el análisis técnico con sus niveles y riesgo base
        analisis_msg = analyze_market(symbol)
        bot.send_message(chat_id, analisis_msg, parse_mode="Markdown")
        
        selector_msg = f"⚙️ Selecciona el margen en USDT que deseas destinar para operar **{symbol}**:"
        bot.send_message(chat_id, selector_msg, reply_markup=get_margin_keyboard(symbol), parse_mode="Markdown")
        
    elif data.startswith("margin_"):
        parts = data.split("_")
        monto = parts[1]
        symbol = f"{parts[2]}/{parts[3]}"
        
        bot.answer_callback_query(call.id, f"Margen seleccionado: {monto} USDT")
        # Calculamos el riesgo adaptativo en base al monto elegido por el usuario
        calculo_riesgo = calculate_risk(margen_usdt=monto, symbol=symbol, sl_porcentaje=1)
        bot.send_message(chat_id, f"✅ **Configuración actualizada para {symbol}**\n\n{calculo_riesgo}", parse_mode="Markdown")
        
    elif data.startswith("exec_"):
        symbol = data.replace("exec_", "")
        bot.answer_callback_query(call.id, "Preparando orden en BingX...")
        bot.send_message(chat_id, f"🚀 *[SIMULACIÓN/CONEXIÓN]* Enviando orden de ejecución para **{symbol}** a BingX bajo los parámetros aprobados.", parse_mode="Markdown")

if __name__ == "__main__":
    print("🤖 Bot de Telegram iniciado correctamente con botones de margen y radar.")
    bot.infinity_polling()
