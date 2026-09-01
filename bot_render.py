import os
import threading
from flask import Flask
import telebot
from analisis import analyze_market, calculate_risk, radar_market

# 1. Servidor Flask para cumplir con el requisito de Web Service de Render
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot de Trading Activo 24/7 🚀"

def run_flask():
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

# 2. Inicialización del Bot de Telegram
TOKEN = os.environ.get("TELEGRAM_TOKEN")
bot = telebot.TeleBot(TOKEN)

@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.reply_to(message, "🤖 Bot privado iniciado y operando 24/7...", parse_mode='Markdown')

@bot.message_handler(commands=['radar'])
def handle_radar(message):
    bot.reply_to(message, "📡 *Escaneando el mercado institucional...*", parse_mode='Markdown')
    resultado_radar = radar_market()
    bot.reply_to(message, resultado_radar, parse_mode='Markdown')

# 3. Ejecución concurrente (Flask en hilo secundario + Bot con skip_pending)
if __name__ == '__main__':
    t = threading.Thread(target=run_flask)
    t.daemon = True
    t.start()
    
    print("🤖 Bot privado iniciado y operando 24/7...")
    bot.infinity_polling(skip_pending=True)
