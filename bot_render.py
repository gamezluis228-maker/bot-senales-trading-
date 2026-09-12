import os
import threading
import time
import requests
import telebot
import ccxt
import numpy as np
from flask import Flask
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

TOKEN = os.getenv("TEL_TOKEN") or os.getenv("TELEGRAM_TOKEN") or os.getenv("TOKEN") or ""
API_KEY = os.getenv("BIT_API_KEY") or os.getenv("BITGET_API_KEY") or os.getenv("API_KEY") or ""
SECRET_KEY = os.getenv("BIT_SECRET_KEY") or os.getenv("BITGET_SECRET_KEY") or os.getenv("SECRET_KEY") or ""
PASSPHRASE = os.getenv("BIT_PASSPHRASE") or os.getenv("BITGET_PASSPHRASE") or os.getenv("PASSPHRASE") or ""

bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)
ULTIMO_CHAT_ID = 7115547861
posiciones_activas = []
bloqueo_posiciones = threading.Lock()

@app.route('/')
def home():
    return "Bot Activo - Bitget"

def crear_instancia_exchange(mercado='swap'):
    config = {
        'enableRateLimit': True,
        'options': {'defaultType': mercado, 'createMarketBuyOrderRequiresPrice': False},
        'apiKey': API_KEY,
        'secret': SECRET_KEY,
        'password': PASSPHRASE
    }
    return ccxt.bitget(config)

exchange = crear_instancia_exchange('swap')
def inicializar_mercados():
    try:
        exchange.load_markets()
        print("¡Mercados de Bitget cargados correctamente!")
    except Exception as e:
        print(f"Error al cargar mercados: {e}")

def calcular_rsi(closes, period=14):
    if len(closes) < period + 1:
        return 50.0
    deltas = np.diff(closes)
    seed = deltas[:period+1]
    up = seed[seed >= 0].sum() / period
    down = -seed[seed < 0].sum() / period
    if down == 0:
        return 100.0
    rs = up / down
    return float(100 - (100 / (1 + rs)))

def calcular_adx(highs, lows, closes, period=14):
    if len(closes) < period + 1:
        return 15.0
    highs, lows, closes = np.array(highs), np.array(lows), np.array(closes)
    tr = np.max(np.array([highs[1:] - lows[1:], np.abs(highs[1:] - closes[:-1]), np.abs(lows[1:] - closes[:-1])]), axis=0)
    atr = np.mean(tr[-period:])
    delta_high, delta_low = np.diff(highs), -np.diff(lows)
    plus_dm = np.where((delta_high > delta_low) & (delta_high > 0), delta_high, 0.0)
    minus_dm = np.where((delta_low > delta_high) & (delta_low > 0), delta_low, 0.0)
    plus_di = 100 * np.mean(plus_dm[-period:]) / (atr if atr != 0 else 1)
    minus_di = 100 * np.mean(minus_dm[-period:]) / (atr if atr != 0 else 1)
    dx = 100 * np.abs(plus_di - minus_di) / ((plus_di + minus_di) if (plus_di + minus_di) != 0 else 1)
    return float(dx)

def obtener_analisis_tecnico(symbol):
    try:
        market_symbol = f"{symbol}/USDT:USDT"
        ohlcv_1h = exchange.fetch_ohlcv(market_symbol, timeframe='1h', limit=30)
        closes_1h, highs_1h, lows_1h = [x[4] for x in ohlcv_1h], [x[2] for x in ohlcv_1h], [x[3] for x in ohlcv_1h]
        
        ohlcv_15m = exchange.fetch_ohlcv(market_symbol, timeframe='15m', limit=30)
        closes_15m, highs_15m, lows_15m = [x[4] for x in ohlcv_15m], [x[2] for x in ohlcv_15m], [x[3] for x in ohlcv_15m]
        
        adx_15m = calcular_adx(highs_15m, lows_15m, closes_15m)
        estado_mercado = "TENDENCIA ACTIVA EN 15M" if adx_15m > 20 else "MERCADO LATERAL / RANGO EN 15M"
        
        return {
            "precio": closes_1h[-1],
            "tendencia_1h": "ALCISTA 🟢" if closes_1h[-1] > closes_1h[-10] else "BAJISTA 🔴",
            "adx_1h": round(calcular_adx(highs_1h, lows_1h, closes_1h), 1),
            "rsi_1h": round(calcular_rsi(closes_1h), 1),
            "tendencia_15m": "ALCISTA 🟢" if closes_15m[-1] > closes_15m[-10] else "BAJISTA 🔴",
            "adx_15m": round(adx_15m, 1),
            "rsi_15m": round(calcular_rsi(closes_15m), 1),
            "resistencia": max(highs_1h[-10:]),
            "soporte": min(lows_1h[-10:]),
            "estado": estado_mercado,
            "pausa": "Fuerza tendencial óptima." if adx_15m > 20 else "Precaución por rango."
        }
    except Exception as e:
        return {"precio": 0.0, "tendencia_1h": "ERROR", "adx_1h": 0.0, "rsi_1h": 0.0, "tendencia_15m": "ERROR", "adx_15m": 0.0, "rsi_15m": 0.0, "resistencia": 0.0, "soporte": 0.0, "estado": "FALLA", "pausa": str(e)}

@bot.message_handler(commands=['start', 'menu'])
def mostrar_menu_principal(message):
    global ULTIMO_CHAT_ID
    ULTIMO_CHAT_ID = message.chat.id
    markup = InlineKeyboardMarkup(row_width=2)
    monedas = ["BTC", "ETH", "XRP", "ZEC"]
    botones = [InlineKeyboardButton(coin, callback_data=f"analisis_{coin}") for coin in monedas]
    markup.add(*botones)
    bot.send_message(message.chat.id, "🤖 **Menú de Cripto Señales Activo**\nSelecciona un activo:", reply_markup=markup, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda call: True)
def callback_query(call):
    global ULTIMO_CHAT_ID
    ULTIMO_CHAT_ID = call.message.chat.id
    try:
        datos = call.data.split("_")
        if datos[0] == "analisis" and len(datos) >= 2:
            coin = datos[1]
            bot.answer_callback_query(call.id, f"Analizando {coin}...")
            an = obtener_analisis_tecnico(coin)
            reporte = (
                f"⚡ **FUTUROS BITGET: {coin}/USDT**\n\n"
                f"💵 Precio: ${an['precio']:,.2f}\n"
                f"📊 **1H:** {an['tendencia_1h']} | ADX: {an['adx_1h']} | RSI: {an['rsi_1h']}\n"
                f"📈 **15M:** {an['tendencia_15m']} | ADX: {an['adx_15m']} | RSI: {an['rsi_15m']}\n"
                f"🧱 Resistencia: ${an['resistencia']:,.2f}\n"
                f"🟡 Soporte: ${an['soporte']:,.2f}\n\n"
                f"🎯 **{an['estado']}**"
            )
            bot.send_message(call.message.chat.id, reporte, parse_mode="Markdown")
    except Exception as e:
        bot.send_message(call.message.chat.id, f"❌ Error: {str(e)}")

def iniciar_bot_hilo():
    time.sleep(3)
    try:
        inicializar_mercados()
        print("¡Hilos secundarios iniciados correctamente!")
    except Exception as e:
        print(f"Error en hilos: {e}")

if __name__ == '__main__':
    threading.Thread(target=iniciar_bot_hilo, daemon=True).start()
    print("Iniciando servidor web y Bot de Telegram...")
    bot.infinity_polling()
