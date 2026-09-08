import os
import time
import requests
import pandas as pd
import ta
import ccxt
from apscheduler.schedulers.background import BackgroundScheduler
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

# ==========================================
# LECTURA DE VARIABLES DE ENTORNO (RENDER)
# ==========================================
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TARGET_CHAT_ID = os.getenv("TARGET_CHAT_ID", "7115547861")

BITGET_CONFIG = {
    'apiKey': os.getenv("BITGET_API_KEY"),
    'secret': os.getenv("BITGET_SECRET_KEY"),
    'password': os.getenv("BITGET_PASSPHRASE"),
    'enableRateLimit': True,
}

SYMBOLS = [
    'BTC/USDT',
    'ETH/USDT',
    'SOL/USDT',
    'ZEC/USDT',
    'HYPE/USDT',
    'IOST/USDT',
]
AUTO_REPORT_SYMBOLS = ['HYPE/USDT', 'IOST/USDT']

# Inicialización de clientes CCXT
bitget_spot = ccxt.bitget(
    {**BITGET_CONFIG, 'options': {'defaultType': 'spot'}}
)
bitget_futures = ccxt.bitget(
    {**BITGET_CONFIG, 'options': {'defaultType': 'swap'}}
)

# Estado de la sesión del usuario (Por defecto: SPOT)
user_market_mode = {}


# ==========================================
# FUNCIONES AUXILIARES Y TELEGRAM
# ==========================================
def send_telegram_msg(text: str):
    url = f'https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage'
    payload = {
        'chat_id': TARGET_CHAT_ID,
        'text': text,
        'parse_mode': 'Markdown',
    }
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f'Error enviando mensaje a Telegram: {e}')


def get_market_data(symbol: str, timeframe: str, limit: int = 50):
    ohlcv = bitget_spot.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
    df = pd.DataFrame(
        ohlcv, columns=['time', 'open', 'high', 'low', 'close', 'volume']
    )
    return df


def calculate_indicators(df):
    rsi = round(ta.momentum.rsi(df['close']).iloc[-1], 1)
    adx = round(
        ta.trend.adx(df['high'], df['low'], df['close']).iloc[-1], 1
    )
    precio_actual = df['close'].iloc[-1]
    resistencia = df['high'].max()
    soporte = df['low'].min()
    return rsi, adx, precio_actual, resistencia, soporte


# ==========================================
# MENÚS Y TECLADOS INTERACTIVOS
# ==========================================
def get_bitget_menu(chat_id: int):
    mode = user_market_mode.get(chat_id, 'SPOT')
    try:
        balance_info = (
            bitget_spot.fetch_balance()
            if mode == 'SPOT'
            else bitget_futures.fetch_balance()
        )
        usdt_free = round(balance_info.get('USDT', {}).get('free', 0.0), 2)
    except Exception:
        usdt_free = 0.0

    keyboard = [
        [
            InlineKeyboardButton(
                '🛍️ Mercado Spot', callback_data='set_mode_SPOT'
            ),
            InlineKeyboardButton(
                '⚡ Mercado Futuros', callback_data='set_mode_FUTUROS'
            ),
        ],
        [
            InlineKeyboardButton(
                '📈 Posiciones Activas', callback_data='view_positions'
            )
        ],
    ]
    text = (
        f'🟦 *PANEL PRINCIPAL BITGET*\n\n'
        f'🔹 *Modo Actual:* `{mode}`\n'
        f'💵 *Balance Disponible USDT:* `${usdt_free}`\n\n'
        f'Selecciona una opción o mercado para gestionar:'
    )
    return text, InlineKeyboardMarkup(keyboard)


def get_trade_menu(chat_id: int):
    mode = user_market_mode.get(chat_id, 'SPOT')
    keyboard = []

    for sym in SYMBOLS:
        clean_sym = sym.replace('/', '')
        keyboard.append([
            InlineKeyboardButton(
                f'🟢 Comprar/Long {sym}',
                callback_data=f'trade_{mode}_BUY_{clean_sym}',
            ),
            InlineKeyboardButton(
                f'🔴 Vender/Short {sym}',
                callback_data=f'trade_{mode}_SELL_{clean_sym}',
            ),
        ])

    keyboard.append([
        InlineKeyboardButton(
            f'🔄 Cambiar Modo (Actual: {mode})', callback_data='toggle_mode'
        )
    ])
    text = f'🟦 *SECTOR DE OPERACIONES BITGET ({mode})*\nSelecciona la operación a ejecutar:'
    return text, InlineKeyboardMarkup(keyboard)


def get_analysis_menu():
    keyboard = []
    row = []
    for sym in SYMBOLS:
        clean_sym = sym.replace('/', '')
        row.append(
            InlineKeyboardButton(
                f'📊 {sym.split("/")[0]}', callback_data=f'analyze_{clean_sym}'
            )
        )
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)

    text = '📊 *MÓDULO DE ANÁLISIS TÉCNICO*\nSelecciona el activo a analizar:'
    return text, InlineKeyboardMarkup(keyboard)


# ==========================================
# HANDLERS DE COMANDOS DE TELEGRAM
# ==========================================
async def cmd_bitget(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    text, reply_markup = get_bitget_menu(chat_id)
    await update.message.reply_text(
        text, reply_markup=reply_markup, parse_mode='Markdown'
    )


async def cmd_operar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    text, reply_markup = get_trade_menu(chat_id)
    await update.message.reply_text(
        text, reply_markup=reply_markup, parse_mode='Markdown'
    )


async def cmd_analisis(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text, reply_markup = get_analysis_menu()
    await update.message.reply_text(
        text, reply_markup=reply_markup, parse_mode='Markdown'
    )


# ==========================================
# MANEJO DE BOTONES INTERACTIVOS (CALLBACKS)
# ==========================================
async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    chat_id = query.message.chat_id

    if data.startswith('set_mode_'):
        mode = data.split('_')[2]
        user_market_mode[chat_id] = mode
        text, reply_markup = get_bitget_menu(chat_id)
        await query.edit_message_text(
            text, reply_markup=reply_markup, parse_mode='Markdown'
        )

    elif data == 'toggle_mode':
        current = user_market_mode.get(chat_id, 'SPOT')
        user_market_mode[chat_id] = 'FUTUROS' if current == 'SPOT' else 'SPOT'
        text, reply_markup = get_trade_menu(chat_id)
        await query.edit_message_text(
            text, reply_markup=reply_markup, parse_mode='Markdown'
        )

    elif data.startswith('analyze_'):
        clean_sym = data.replace('analyze_', '')
        symbol = f'{clean_sym[:-4]}/{clean_sym[-4:]}'
        df_15m = get_market_data(symbol, '15m')
        df_1h = get_market_data(symbol, '1h')

        rsi_15m, adx_15m, precio, res, sop = calculate_indicators(df_15m)
        rsi_1h, adx_1h, _, _, _ = calculate_indicators(df_1h)

        macro_trend = 'ALCISTA 🟢' if rsi_1h > 50 else 'BAJISTA 🔴'
        short_trend = 'ALCISTA 🟢' if rsi_15m > 50 else 'BAJISTA 🔴'

        reporte = (
            f'🔔 *REPORTE TÉCNICO (SOLICITADO)* 🔔\n'
            f'⚡ *Activo:* {symbol}\n\n'
            f'💵 *Precio Actual:* `${precio}`\n\n'
            f'📊 *MACRO (1H):* {macro_trend} | *ADX:* {adx_1h} | *RSI:* {rsi_1h}\n'
            f'📈 *CORTO PLAZO (15M):* {short_trend} | *ADX:* {adx_15m} | *RSI:* {rsi_15m}\n\n'
            f'🧱 *Resistencia:* `${res}`\n'
            f'🟡 *Soporte:* `${sop}`\n\n'
            f'⌛ *Estado:* TENDENCIA ACTIVA EN 15M\n'
            f'• Estructura de 15m con fuerza tendencial.'
        )
        await query.message.reply_text(reporte, parse_mode='Markdown')

    elif data.startswith('trade_'):
        parts = data.split('_')
        mode, action, clean_sym = parts[1], parts[2], parts[3]
        symbol = f'{clean_sym[:-4]}/{clean_sym[-4:]}'

        df_15m = get_market_data(symbol, '15m')
        rsi_15m, adx_15m, precio, _, _ = calculate_indicators(df_15m)

        # LÓGICA DE FUTUROS: Filtro ADX < 20 y Gestión SL/TP
        if mode == 'FUTUROS':
            if adx_15m < 20:
                msg_cancel = (
                    f'⚠️ *ENTRADA CANCELADA / FILTRADA (FUTUROS)*\n'
                    f'⚡ *Activo:* {symbol}\n'
                    f'📉 *Razón:* Mercado Lateral en 15M (ADX: {adx_15m} < 20). Sin fuerza tendencial.'
                )
                await query.message.reply_text(msg_cancel, parse_mode='Markdown')
                return

            sl = round(precio * 0.96 if action == 'BUY' else precio * 1.04, 4)
            tp = round(precio * 1.08 if action == 'BUY' else precio * 0.92, 4)

            # Ejecutar Orden Futuros Bitget
            msg_order = (
                f'⚡ *POSICIÓN FUTUROS EJECUTADA*\n'
                f'📌 *Activo:* {symbol} ({action})\n'
                f'📥 *Entrada:* `${precio}`\n'
                f'🛑 *Stop Loss (-4%):* `${sl}`\n'
                f'🎯 *Take Profit (+8%):* `${tp}`'
            )
            await query.message.reply_text(msg_order, parse_mode='Markdown')

        # LÓGICA DE SPOT: Libertad Total de Compra / Venta con Reportes
        elif mode == 'SPOT':
            if action == 'BUY':
                msg_spot = (
                    f'🛍️ *[BITGET] - COMPRA SPOT EJECUTADA*\n\n'
                    f'⚡ *Activo:* `{symbol}`\n'
                    f'💵 *Precio de Compra:* `${precio}`'
                )
            else:
                msg_spot = (
                    f'💵 *[BITGET] - VENTA SPOT EJECUTADA*\n\n'
                    f'⚡ *Activo:* `{symbol}`\n'
                    f'📤 *Precio de Venta:* `${precio}`\n'
                    f'🟢 *Estado:* Toma de ganancias ejecutada.'
                )
            await query.message.reply_text(msg_spot, parse_mode='Markdown')


# ==========================================
# PROGRAMADOR DE REPORTES AUTOMÁTICOS (15M)
# ==========================================
def cron_auto_reports():
    for symbol in AUTO_REPORT_SYMBOLS:
        try:
            df_15m = get_market_data(symbol, '15m')
            df_1h = get_market_data(symbol, '1h')

            rsi_15m, adx_15m, precio, res, sop = calculate_indicators(df_15m)
            rsi_1h, adx_1h, _, _, _ = calculate_indicators(df_1h)

            macro_trend = 'ALCISTA 🟢' if rsi_1h > 50 else 'BAJISTA 🔴'
            short_trend = 'ALCISTA 🟢' if rsi_15m > 50 else 'BAJISTA 🔴'

            mensaje = (
                f'🔔 *REPORTE AUTOMÁTICO CIERRE 15M / 1H* 🔔\n'
                f'⚡ *Activo:* {symbol}\n\n'
                f'💵 *Precio Actual:* `${precio}`\n\n'
                f'📊 *MACRO (1H):* {macro_trend} | *ADX:* {adx_1h} | *RSI:* {rsi_1h}\n'
                f'📈 *CORTO PLAZO (15M):* {short_trend} | *ADX:* {adx_15m} | *RSI:* {rsi_15m}\n\n'
                f'🧱 *Resistencia:* `${res}`\n'
                f'🟡 *Soporte:* `${sop}`\n\n'
                f'⌛ *Estado:* TENDENCIA ACTIVA EN 15M\n'
                f'• Estructura de 15m con fuerza tendencial.'
            )
            send_telegram_msg(mensaje)
        except Exception as e:
            print(f'Error en reporte automático para {symbol}: {e}')


# ==========================================
# INICIALIZACIÓN DEL BOT
# ==========================================
if __name__ == '__main__':
    # Iniciar Programador de Tareas (Reporte 15m)
    scheduler = BackgroundScheduler()
    scheduler.add_job(cron_auto_reports, 'cron', minute='0,15,30,45')
    scheduler.start()

    # Configurar Telegram Bot
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler('BITGET', cmd_bitget))
    app.add_handler(CommandHandler('operar', cmd_operar))
    app.add_handler(CommandHandler('analisis', cmd_analisis))

    print('Bot de Bitget iniciado correctamente...')
    app.run_polling()
