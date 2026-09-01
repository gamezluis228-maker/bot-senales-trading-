import os
import telebot
from analisis import analyze_market, calculate_risk, radar_market

# ==========================================
# 1. INICIALIZACIÓN DEL BOT
# ==========================================
# Asegúrate de que tu Token esté configurado en las variables de entorno de Render
TOKEN = os.environ.get("TELEGRAM_TOKEN", "TU_TOKEN_POR_DEFECTO")
bot = telebot.TeleBot(TOKEN)

# ==========================================
# 2. COMANDOS Y MANEJADORES
# ==========================================

@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.reply_to(message, "🤖 Bot privado iniciado y operando 24/7...", parse_mode='Markdown')

@bot.message_handler(commands=['radar'])
def handle_radar(message):
    # Mensaje de aviso de que está escaneando
    bot.reply_to(message, "📡 *Escaneando el mercado institucional...*", parse_mode='Markdown')
    
    # Ejecuta el análisis masivo desde analisis.py
    resultado_radar = radar_market()
    bot.reply_to(message, resultado_radar, parse_mode='Markdown')

# ==========================================
# 3. BLOQUE FINAL DE ARRANQUE
# ==========================================
if __name__ == '__main__':
    print("🤖 Bot privado iniciado y operando 24/7...")
    # skip_pending=True descarta cualquier sesión colgada anterior en Telegram
    bot.infinity_polling(skip_pending=True)
