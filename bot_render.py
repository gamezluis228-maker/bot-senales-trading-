import os
import telebot
from flask import Flask, request
from analisis import get_kucoin_price, analisis_completo, formatear_señal, formatear_analisis, formatear_soporte, calcular_futuros, formatear_futuros

TOKEN = "8962151587:AAG1AyLxwREUtTBd-visJBGhAs4CaOzQx1I"
bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

COINS = {'BTC-USDT':'BTC','ETH-USDT':'ETH','BNB-USDT':'BNB','SOL-USDT':'SOL','XRP-USDT':'XRP'}

def teclado_principal():
    markup = telebot.types.InlineKeyboardMarkup()
    markup.add(telebot.types.InlineKeyboardButton("BTC",callback_data="precio_BTC"), telebot.types.InlineKeyboardButton("ETH",callback_data="precio_ETH"))
    markup.add(telebot.types.InlineKeyboardButton("SOL",callback_data="precio_SOL"), telebot.types.InlineKeyboardButton("XRP",callback_data="precio_XRP"))
    return markup

@app.route('/' + TOKEN, methods=['POST'])
def webhook():
    bot.process_new_updates([telebot.types.Update.de_json(request.stream.read().decode("utf-8"))])
    return "ok", 200

@bot.message_handler(commands=['start'])
def cmd_start(message):
    bot.send_message(message.chat.id, "🤖 *BOT TRADING - KUCOIN*\n\n`/precio BTC` → Precio\n`/analisis BTC` → Analisis tecnico\n`/soporte BTC` → Soporte/Resistencia + rupturas\n`/operar BTC` → Señal directa\n`/futuros 65000 100` → Calculadora\n\n⚠️ Bot educativo. Nunca mas del 2%.", parse_mode="Markdown", reply_markup=teclado_principal())

@bot.message_handler(commands=['precio'])
def cmd_precio(message):
    try:
        moneda = message.text.split()[1].upper()
        data = get_kucoin_price(f"{moneda}-USDT")
        if not data:
            bot.send_message(message.chat.id, f"No encontre {moneda}", parse_mode="Markdown")
            return
        emoji = "🟢" if data["change24h"] >= 0 else "🔴"
        bot.send_message(message.chat.id, f"💎 *{moneda}/USDT*\n💰 ${data['price']:,.2f}\n{emoji} 24h: {data['change24h']:+.2f}%\n📈 Max: ${data['high24h']:,.2f}\n📉 Min: ${data['low24h']:,.2f}\n📦 Vol: {data['vol24h']:,.0f}", parse_mode="Markdown")
    except:
        bot.send_message(message.chat.id, "❌ Uso: `/precio BTC`", parse_mode="Markdown")

@bot.message_handler(commands=['analisis'])
def cmd_analisis(message):
    try:
        moneda = message.text.split()[1].upper()
        msg = bot.send_message(message.chat.id, f"Analizando {moneda}...")
        res = analisis_completo(f"{moneda}-USDT")
        if not res:
            bot.edit_message_text(f"Error con {moneda}", chat_id=message.chat.id, message_id=msg.message_id)
            return
        bot.edit_message_text(formatear_analisis(res, f"{moneda}/USDT"), chat_id=message.chat.id, message_id=msg.message_id, parse_mode="Markdown")
    except:
        bot.send_message(message.chat.id, "❌ Uso: `/analisis BTC`", parse_mode="Markdown")

@bot.message_handler(commands=['soporte'])
def cmd_soporte(message):
    try:
        moneda = message.text.split()[1].upper()
        msg = bot.send_message(message.chat.id, f"Calculando {moneda}...")
        res = analisis_completo(f"{moneda}-USDT")
        if not res:
            bot.edit_message_text(f"Error con {moneda}", chat_id=message.chat.id, message_id=msg.message_id)
            return
        bot.edit_message_text(formatear_soporte(res, f"{moneda}/USDT"), chat_id=message.chat.id, message_id=msg.message_id, parse_mode="Markdown")
    except:
        bot.send_message(message.chat.id, "❌ Uso: `/soporte BTC`", parse_mode="Markdown")

@bot.message_handler(commands=['operar','señal'])
def cmd_operar(message):
    try:
        moneda = message.text.split()[1].upper()
        msg = bot.send_message(message.chat.id, f"Generando señal {moneda}...")
        res = analisis_completo(f"{moneda}-USDT")
        if not res:
            bot.edit_message_text(f"Error con {moneda}", chat_id=message.chat.id, message_id=msg.message_id)
            return
        bot.edit_message_text(formatear_señal(res, f"{moneda}/USDT"), chat_id=message.chat.id, message_id=msg.message_id, parse_mode="Markdown")
    except:
        bot.send_message(message.chat.id, "❌ Uso: `/operar BTC`", parse_mode="Markdown")

@bot.message_handler(commands=['futuros'])
def cmd_futuros(message):
    try:
        partes = message.text.split()
        plan = calcular_futuros(float(partes[1]), float(partes[2]))
        if not plan:
            bot.send_message(message.chat.id, "Error en calculo")
            return
        bot.send_message(message.chat.id, formatear_futuros(plan), parse_mode="Markdown")
    except:
        bot.send_message(message.chat.id, "❌ Uso: `/futuros 65000 100`", parse_mode="Markdown")

@bot.callback_query_handler(func=lambda call: True)
def callback_query(call):
    if call.data.startswith("precio_"):
        moneda = call.data.split("_")[1].upper()
        data = get_kucoin_price(f"{moneda}-USDT")
        if data:
            emoji = "🟢" if data["change24h"] >= 0 else "🔴"
            bot.send_message(call.message.chat.id, f"💎 {moneda}/USDT\n💰 ${data['price']:,.2f}\n{emoji} 24h: {data['change24h']:+.2f}%", parse_mode="Markdown")
    bot.answer_callback_query(call.id)

@app.route('/')
def index():
    return "Bot activo", 200

def iniciar_webhook():
    bot.remove_webhook()
    bot.set_webhook(url=(os.environ.get('RENDER_EXTERNAL_URL','') + '/' + TOKEN))

if __name__ == '__main__':
    iniciar_webhook()
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
    
