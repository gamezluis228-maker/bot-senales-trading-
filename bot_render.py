import os
import asyncio
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from analisis import analyze_market, calculate_risk

TOKEN = os.getenv("TELEGRAM_TOKEN")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_text = (
        "🤖 **¡Bot de Señales de Trading Activo!**\n\n"
        "Comandos disponibles:\n"
        "▫️ `/btc` - Análisis técnico de Bitcoin\n"
        "▫️ `/eth` - Análisis técnico de Ethereum\n"
        "▫️ `/sol` - Análisis técnico de Solana\n"
        "▫️ `/analisis <MONEDA>` - Análisis personalizado (ej: `/analisis XRP`)\n"
        "▫️ `/riesgo <CAPITAL>` - Calculadora de gestión de riesgo (ej: `/riesgo 100`)"
    )
    await update.message.reply_text(welcome_text, parse_mode="Markdown")

async def analyze_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.args:
        symbol = context.args[0].upper()
    else:
        cmd = update.message.text.replace("/", "").upper()
        symbol = cmd if cmd in ["BTC", "ETH", "SOL"] else "BTC"

    await update.message.reply_text(f"🔍 Analizando {symbol}/USDT en tiempo real...")
    result = analyze_market(symbol)
    await update.message.reply_text(result, parse_mode="Markdown")

async def risk_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("⚠️ Indica tu capital. Ejemplo: `/riesgo 50`", parse_mode="Markdown")
        return
    
    capital = context.args[0]
    result = calculate_risk(capital)
    await update.message.reply_text(result, parse_mode="Markdown")

def main():
    if not TOKEN:
        print("❌ Error: TELEGRAM_TOKEN no configurado.")
        return

    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("btc", analyze_cmd))
    app.add_handler(CommandHandler("eth", analyze_cmd))
    app.add_handler(CommandHandler("sol", analyze_cmd))
    app.add_handler(CommandHandler("analisis", analyze_cmd))
    app.add_handler(CommandHandler("riesgo", risk_cmd))

    print("🚀 Bot iniciado correctamente...")
    app.run_polling()

if __name__ == "__main__":
    main()
