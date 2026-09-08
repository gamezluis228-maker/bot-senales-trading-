import os
import logging
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# Configuración de logs para ver la actividad en Render
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# 1. Cargar Variables de Entorno desde Render
TELEGRAM_TOKEN = os.getenv("BITGET_TELEGRAM_TOKEN")
API_KEY = os.getenv("BITGET_API_KEY")
SECRET_KEY = os.getenv("BITGET_SECRET_KEY")
PASSPHRASE = os.getenv("BITGET_PASSPHRASE")

# Validar que el token exista para evitar conflictos
if not TELEGRAM_TOKEN:
    raise ValueError("CRÍTICO: No se encontró BITGET_TELEGRAM_TOKEN en las variables de Render.")

# 2. Comandos del Bot
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🤖 ¡Bot de Trading para Bitget activo y en ejecución!")

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if API_KEY and SECRET_KEY and PASSPHRASE:
        await update.message.reply_text("✅ Credenciales de Bitget configuradas correctamente.")
    else:
        await update.message.reply_text("⚠️ Faltan credenciales de Bitget (API Key, Secret o Passphrase).")

# 3. Inicializar y ejecutar el bot
def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    # Handlers de comandos
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("status", status))

    print("🚀 Iniciando Bot de Bitget...")
    app.run_polling()

if __name__ == "__main__":
    main()
