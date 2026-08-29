import os
import telebot
from flask import Flask, request
from analisis import generar_senal, formatear_senal, get_kucoin_stats

TOKEN = "8962151587:AAG1AyLxwREUtTBd-visJBGhAs4CaOzQx1I"
bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

COINS = {
    'BTC-USDT': 'BTC',
    'ETH-USDT': 'ETH',
    'BNB-USDT': 'BNB',
    'SOL-USDT': 'SOL',
    'XRP-USDT': 'XRP'
}

def teclado_principal():
    markup = telebot.types.InlineKeyboardMarkup(row_width=2)
    btn1 = telebot.types.InlineKeyboardButton("👤 User Info", callback_data='user_info')
    btn2 = telebot.types.InlineKeyboardButton("📈 Señales", callback_data='senales')
    btn3 = telebot.types.InlineKeyboardButton("₿ BTC", callback_data='precio_BTC-USDT')
    btn4 = telebot.types.InlineKeyboardButton("Ξ ETH", callback_data='precio_ETH-USDT')
    btn5 = telebot.types.InlineKeyboardButton("⚡ SOL", callback_data='precio_SOL-USDT')
    btn6 = telebot.types.InlineKeyboardButton("❌ XRP", callback_data='precio_XRP-USDT')
    markup.add(btn1, btn2)
    markup.add(btn3, btn4)
    markup.add(btn5, btn6)
    return markup

def teclado_senales():
    markup = telebot.types.InlineKeyboardMarkup(row_width=2)
    for par, nombre in COINS.items():
        btn = telebot.types.InlineKeyboardButton(nombre, callback_data=f'senal_{par}')
        markup.add(btn)
    btn_volver = telebot.types.InlineKeyboardButton("🔙 Volver", callback_data='volver')
    markup.add(btn_volver)
    return markup

@bot.message_handler(commands=['start'])
def cmd_start(message):
    bot.send_message(
        message.chat.id,
        "🤖 *Bot Señales TRADING*\n\n💎 Selecciona una opción:",
        parse_mode='Markdown',
        reply_markup=teclado_principal()
    )

@bot.message_handler(commands=['señal', 'senal'])
def cmd_senal(message):
    bot.send_message(
        message.chat.id,
        "📈 *Análisis Técnico Avanzado*\n\nElige un par:",
        parse_mode='Markdown',
        reply_markup=teclado_senales()
    )

@bot.message_handler(commands=['precio'])
def cmd_precio(message):
    bot.send_message(
        message.chat.id,
        "💰 *Precio y Rango*\n\nElige una cripto:",
        parse_mode='Markdown',
        reply_markup=teclado_senales()
    )

@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    chat_id = call.message.chat.id
    if call.data == 'user_info':
        user = call.from_user
        info = f"""👤 *User Info*

🆔 ID: `{user.id}`
👤 Nombre: {user.first_name}
📝 Username: @{user.username if user.username else 'N/A'}
🌐 Lenguaje: {user.language_code}"""
        bot.answer_callback_query(call.id)
        bot.send_message(chat_id, info, parse_mode='Markdown')
    elif call.data == 'senales':
        bot.answer_callback_query(call.id, "Cargando análisis...")
        bot.send_message(
            chat_id,
            "📈 *Análisis Técnico Avanzado*\n\nElige un par:",
            parse_mode='Markdown',
            reply_markup=teclado_senales()
        )
    elif call.data == 'volver':
        bot.answer_callback_query(call.id)
        bot.send_message(
            chat_id,
            "💎 Selecciona una opción:",
            reply_markup=teclado_principal()
        )
    elif call.data.startswith('precio_'):
        par = call.data.replace('precio_', '')
        bot.answer_callback_query(call.id, f"Consultando {par}...")
        stats = get_kucoin_stats(par)
        if stats:
            nombre = COINS.get(par, par)
            rango = stats['high24h'] - stats['low24h']
            posicion = ((stats['price'] - stats['low24h']) / rango * 100) if rango > 0 else 50
            texto = f"""💰 *{nombre}/USDT*

📊 Precio: `${stats['price']:.2f}`
📈 Cambio 24h: `{stats['change24h']:+.2f}%`
🔺 Máx 24h: `${stats['high24h']:.2f}`
🔻 Mín 24h: `${stats['low24h']:.2f}`
📦 Volumen: `{stats['vol24h']:,.0f}`

📍 Posición en rango: `{posicion:.1f}%`
💵 Bid: `{stats['buy']:.2f}` | Ask: `{stats['sell']:.2f}`"""
            bot.send_message(chat_id, texto, parse_mode='Markdown')
        else:
            bot.send_message(chat_id, "⚠️ Error obteniendo datos.")
    elif call.data.startswith('senal_'):
        par = call.data.replace('senal_', '')
        bot.answer_callback_query(call.id, f"Analizando {par}...")
        msg = bot.send_message(chat_id, "⏳ Analizando mercado...")
        try:
            senal = generar_senal(par)
            texto = formatear_senal(senal)
            bot.delete_message(chat_id, msg.message_id)
            bot.send_message(chat_id, texto)
        except Exception as e:
            bot.delete_message(chat_id, msg.message_id)
            bot.send_message(chat_id, f"⚠️ Error en el análisis: `{str(e)}`", parse_mode='Markdown')
            print(f"Error generando señal para {par}: {e}")

@bot.message_handler(func=lambda message: True)
def handle_text(message):
    texto = message.text.upper()
    for par, nombre in COINS.items():
        if nombre in texto:
            bot.send_message(message.chat.id, f"📊 Analizando *{nombre}*...", parse_mode='Markdown')
            try:
                senal = generar_senal(par)
                bot.send_message(message.chat.id, formatear_senal(senal))
            except Exception as e:
                bot.send_message(message.chat.id, f"⚠️ Error: {e}")
            return
    bot.send_message(message.chat.id, "🤖 Usa /start para ver el menú.", reply_markup=teclado_principal())

@app.route('/' + TOKEN, methods=['POST'])
def webhook():
    update = telebot.types.Update.de_json(request.stream.read().decode("utf-8"))
    bot.process_new_updates([update])
    return "OK", 200

@app.route("/")
def index():
    return "🤖 Bot Señales TRADING está activo!", 200

if __name__ == "__main__":
    print("🤖 Configurando webhook...")
    bot.remove_webhook()
    WEBHOOK_URL = os.environ.get('RENDER_EXTERNAL_URL', '')
    if WEBHOOK_URL:
        bot.set_webhook(url=WEBHOOK_URL + '/' + TOKEN)
        print(f"✅ Webhook configurado")
    else:
        print("⚠️ RENDER_EXTERNAL_URL no definida")
    port = int(os.environ.get('PORT', 5000))
    app.run(host="0.0.0.0", port=port)
