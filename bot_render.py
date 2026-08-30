import os
import asyncio
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from analisis import analyze_market, calculate_risk

# Leer token desde archivo secret y limpiar saltos de linea
TOKEN = ""
try:
    with open('/etc/secrets/bot_token.txt', 'r') as f:
        raw = f.read()
        # Elimina saltos de linea, espacios y une todo
        TOKEN = raw.replace('\n', '').replace('\r', '').replace(' ', '').strip()
except:
    TOKEN = os.getenv("TELEGRAM_TOKEN", "").replace('\n', '').replace('\r', '').replace(' ', '').strip()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_text = (
        "🤖 **¡Bot de Señales de Trading Activo!**\n\n"
        "Comandos disponibles:\n"
        "• `/btc` - Análisis técnico de Bitcoin\n"
        "• `/eth` - Análisis técnico de Ethereum\n"
        "• `/sol` - Análisis técnico de Solana\n"
        "• `/analisis <MONEDA>` - Análisis personalizado\n"
        "• `/riesgo <CAPITAL>` - Calculadora de riesgo"
    )
    await update.message.reply_text(welcome_text, parse_mode='Markdown')

async def analyze_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.args:
        symbol = context.args[0].upper()
    else:
        cmd = update.message.text.replace("/", "").upper()
        symbol = cmd if cmd in ["BTC", "ETH", "SOL"] else None
    
    if not symbol:
        await update.message.reply_text("🔍 Uso: /analisis <MONEDA> o /btc /eth /sol")
        return
        
    await update.message.reply_text(f"🔍 Analizando {symbol}...")
    result = analyze_market(symbol)
    await update.message.reply_text(result, parse_mode='Markdown')

async def risk_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("⚠️ Indica el capital: /riesgo <CAPITAL>")
        return

    capital = context.args[0]
    result = calculate_risk(capital)
    await update.message.reply_text(result, parse_mode='Markdown')

def main():
    if not TOKEN:
        print("❌ Error: No se encontro el token del bot")
        return

    print("🚀 Bot iniciado correctamente...")
    application = Application.builder().token(TOKEN).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler(["btc", "eth", "sol", "analisis"], analyze_cmd))
    application.add_handler(CommandHandler("riesgo", risk_cmd))
    
    application.run_polling()

if __name__ == "__main__":
    main()
