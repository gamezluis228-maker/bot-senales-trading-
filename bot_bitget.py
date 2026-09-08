import os
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

# Configuración de logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

# Cargar el Token de Telegram dedicado para Bitget
TELEGRAM_BOT_TOKEN = os.getenv("BITGET_TELEGRAM_TOKEN")

if not TELEGRAM_BOT_TOKEN:
    raise ValueError(
        "Error: La variable de entorno BITGET_TELEGRAM_TOKEN no está configurada."
    )

# Estado global del bot
USER_MODES = {}  # Guarda el modo de mercado por usuario (SPOT o FUTUROS)

def get_user_mode(user_id: int) -> str:
    return USER_MODES.get(user_id, "SPOT")

# --- TECLADOS INTERACTIVOS ---

def main_keyboard():
    keyboard = [
        [
            InlineKeyboardButton("🛍️ Mercado Spot", callback_data="mode_spot"),
            InlineKeyboardButton("⚡ Mercado Futuros", callback_data="mode_futures"),
        ],
        [InlineKeyboardButton("📈 Posiciones Activas", callback_data="positions")],
    ]
    return InlineKeyboardMarkup(keyboard)

def operate_keyboard(mode: str):
    keyboard = [
        [
            InlineKeyboardButton("🟢 Comprar/Long BTC", callback_data="buy_btc"),
            InlineKeyboardButton("🔴 Vender/Short BTC", callback_data="sell_btc"),
        ],
        [
            InlineKeyboardButton("🟢 Comprar/Long ETH", callback_data="buy_eth"),
            InlineKeyboardButton("🔴 Vender/Short ETH", callback_data="sell_eth"),
        ],
        [
            InlineKeyboardButton("🟢 Comprar/Long SOL", callback_data="buy_sol"),
            InlineKeyboardButton("🔴 Vender/Short SOL", callback_data="sell_sol"),
        ],
        [
            InlineKeyboardButton("🟢 Comprar/Long ZEC", callback_data="buy_zec"),
            InlineKeyboardButton("🔴 Vender/Short ZEC", callback_data="sell_zec"),
        ],
        [
            InlineKeyboardButton("🟢 Comprar/Long HYPE", callback_data="buy_hype"),
            InlineKeyboardButton("🔴 Vender/Short HYPE", callback_data="sell_hype"),
        ],
        [
            InlineKeyboardButton("🟢 Comprar/Long IOST", callback_data="buy_iost"),
            InlineKeyboardButton("🔴 Vender/Short IOST", callback_data="sell_iost"),
        ],
        [
            InlineKeyboardButton(
                f"🔄 Cambiar Modo (Actual: {mode})", callback_data="toggle_mode"
            )
        ],
    ]
    return InlineKeyboardMarkup(keyboard)

# --- COMANDOS ---

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    mode = get_user_mode(user_id)
    text = (
        "🟦 *PANEL PRINCIPAL BITGET*\n\n"
        f"🔹 *Modo Actual:* {mode}\n"
        "💵 *Balance Disponible USDT:* $0.0\n\n"
        "Selecciona una opción o mercado para gestionar:"
    )
    await update.message.reply_text(
        text, parse_mode="Markdown", reply_markup=main_keyboard()
    )

async def operar_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    mode = get_user_mode(user_id)
    text = f"🟦 *SECTOR DE OPERACIONES BITGET ({mode})*\nSelecciona la operación a ejecutar:"
    await update.message.reply_text(
        text, parse_mode="Markdown", reply_markup=operate_keyboard(mode)
    )

async def analisis_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "📊 *ANÁLISIS DE MERCADO BITGET*\n\n"
        "⏳ *Estado:* MERCADO LATERAL / RANGO EN 15M (ADX < 20)\n"
        "• *Precaución:* Rango plano en corto plazo."
    )
    await update.message.reply_text(text, parse_mode="Markdown")

async def posiciones_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = "📈 *POSICIONES ACTIVAS BITGET*\n\nNo hay posiciones abiertas en este momento."
    await update.message.reply_text(text, parse_mode="Markdown")

# --- MANEJADOR DE BOTONES ---

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data = query.data

    if data == "mode_spot":
        USER_MODES[user_id] = "SPOT"
        await query.edit_message_text(
            "✅ Modo cambiado a *SPOT*.", parse_mode="Markdown"
        )
    elif data == "mode_futures":
        USER_MODES[user_id] = "FUTUROS"
        await query.edit_message_text(
            "⚡ Modo cambiado a *FUTUROS*.", parse_mode="Markdown"
        )
    elif data == "toggle_mode":
        current = get_user_mode(user_id)
        new_mode = "FUTUROS" if current == "SPOT" else "SPOT"
        USER_MODES[user_id] = new_mode
        await query.edit_message_text(
            f"🔄 Modo actualizado a *{new_mode}*. Vuelve a enviar /operar.",
            parse_mode="Markdown",
        )
    elif data == "positions":
        await query.edit_message_text(
            "📈 *POSICIONES ACTIVAS:* Sin posiciones abiertas.",
            parse_mode="Markdown",
        )
    else:
        await query.edit_message_text(
            f"🛠️ Función seleccionada: `{data}`.", parse_mode="Markdown"
        )

# --- INICIALIZACIÓN ---

def main():
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    # Comandos
    app.add_handler(CommandHandler(["start", "BITGET"], start_command))
    app.add_handler(CommandHandler("operar", operar_command))
    app.add_handler(CommandHandler(["analisis", "análisis"], analisis_command))
    app.add_handler(CommandHandler("posiciones", posiciones_command))

    # Botones
    app.add_handler(CallbackQueryHandler(button_handler))

    logging.info("Bot de Bitget iniciado correctamente con su token dedicado.")
    app.run_polling()

if __name__ == "__main__":
    main()
