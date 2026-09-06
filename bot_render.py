import os
import threading
import telebot
import ccxt
from flask import Flask

TOKEN = os.getenv("TELEGRAM_TOKEN")
API_KEY = os.getenv("BINGX_API_KEY")
SECRET_KEY = os.getenv("BINGX_SECRET_KEY")

bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

exchange = ccxt.bingx({
    'apiKey': API_KEY,
    'secret': SECRET_KEY,
    'enableRateLimit': True,
    'options': {'defaultType': 'swap'}
})

@app.route('/')
def home():
    return "Bot Activo"

# --- MANEJADOR DE MENSAJES DE TEXTO Y COMANDOS ---
@bot.message_handler(commands=['start', 'help'])
def enviar_bienvenida(message):
    bot.reply_to(message, "¡Hola! El bot está activo y conectado correctamente a Render.")

@bot.message_handler(func=lambda message: True)
def responder_texto(message):
    bot.reply_to(message, f"Recibido tu mensaje: {message.text}")


# --- MANEJADOR DE BOTONES ---
@bot.callback_query_handler(func=lambda call: True)
def callback_query(call):
    try:
        datos = call.data.split("_")
        if len(datos) < 4:
            bot.answer_callback_query(call.id, "Formato de botón no válido.")
            return

        simbolo = datos[0]
        mercado = datos[1]
        accion = datos[2]
        margen = float(datos[3])

        bot.answer_callback_query(call.id, "Procesando orden...")
        
        # Lógica rápida de respuesta para verificar que el botón ya opera
        bot.send_message(call.message.chat.id, f"✅ Procesando {accion.upper()} en {mercado.upper()} para {simbolo} por ${margen} USDT")
            
    except Exception as e:
        bot.send_message(call.message.chat.id, f"❌ Error: {str(e)}")


# --- INICIO DEL HILO DEL BOT ---
def arrancar_bot():
    bot.remove_webhook()
    bot.infinity_polling(skip_pending=True)

if __name__ == "__main__":
    t = threading.Thread(target=arrancar_bot)
    t.daemon = True
    t.start()

    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
    
