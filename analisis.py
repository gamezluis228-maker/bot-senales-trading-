import ccxt
import pandas as pd
import numpy as np

exchange = ccxt.kucoin({'enableRateLimit': True})

def fetch_data(symbol, timeframe, limit=100):
    try:
        formatted_symbol = f"{symbol}/USDT"
        ohlcv = exchange.fetch_ohlcv(formatted_symbol, timeframe=timeframe, limit=limit)
        return pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    except Exception as e:
        print(f"Error fetching data for {symbol}: {e}")
        return None

def calculate_rsi(df, period=14):
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def analizar_mercado_symbol(symbol):
    df_1h = fetch_data(symbol, '1h')
    df_15m = fetch_data(symbol, '15m')
    if df_1h is None or df_15m is None:
        return f"⚠️ Error al conectar con KuCoin para {symbol}."

    current_price = df_15m['close'].iloc[-1]
    df_15m['rsi'] = calculate_rsi(df_15m)
    current_rsi = round(df_15m['rsi'].iloc[-1], 2)

    resistance = df_15m['high'].tail(20).max()
    support = df_15m['low'].tail(20).min()

    df_1h['ema20'] = df_1h['close'].ewm(span=20, adjust=False).mean()
    macro_bullish = current_price > df_1h['ema20'].iloc[-1]

    if current_price >= resistance and current_rsi > 50 and macro_bullish:
        signal = "🟢 COMPRA (LONG)"
        entry = current_price
        sl = round(entry * 0.985, 2)
        tp1 = round(entry * 1.015, 2)
        tp2 = round(entry * 1.030, 2)
        detail = "Ruptura de Resistencia confirmada en 1H."
    elif current_price <= support and current_rsi < 50 and not macro_bullish:
        signal = "🔴 VENTA (SHORT)"
        entry = current_price
        sl = round(entry * 1.015, 2)
        tp1 = round(entry * 0.985, 2)
        tp2 = round(entry * 0.970, 2)
        detail = "Ruptura de Soporte confirmada en 1H."
    else:
        signal = "⚪ SIN SEÑAL - MERCADO LATERAL"
        entry, sl, tp1, tp2 = current_price, 0, 0, 0
        detail = "Mercado en rango. Esperar ruptura."

    msg = f"📊 **ANÁLISIS DE MERCADO: {symbol}/USDT**\n\n"
    msg += f"💵 **Precio Actual:** ${current_price:.2f}\n"
    msg += f"📈 **RSI (15m):** {current_rsi}\n\n"
    msg += f"🧱 **Resistencia:** ${resistance:.2f}\n"
    msg += f"🚧 **Soporte:** ${support:.2f}\n\n"
    msg += f"🚥 **Estado:** {signal}\n"
    msg += f"💡 **Diagnóstico:** {detail}\n\n"

    if sl != 0:
        msg += f"📌 **Punto de Entrada:** ${entry:.2f}\n"
        msg += f"🛑 **Stop Loss (SL):** ${sl:.2f}\n"
        msg += f"🎯 **Take Profit 1:** ${tp1:.2f}\n"
        msg += f"🎯 **Take Profit 2:** ${tp2:.2f}\n"

    return msg

def calcular_riesgo(capital_usdt, sl_percent=1.5):
    try:
        capital = float(capital_usdt)
        risk_amount = round(capital * (sl_percent / 100), 2)
        msg = f"🧮 **GESTIÓN DE RIESGO**\n\n"
        msg += f"💰 **Capital Base:** ${capital:.2f} USDT\n"
        msg += f"⚡ **Apalancamiento Sugerido:** 5x - 10x\n"
        msg += f"📦 **Tamaño de Posición (5x):** ${capital * 5:.2f} USDT\n"
        msg += f"🛑 **Pérdida Máxima al SL ({sl_percent}%):** -${risk_amount:.2f} USDT\n\n"
        msg += f"⚠️ **Recomendación:** No usar apalancamiento mayor a 10x."
        return msg
    except ValueError:
        return "⚠️ Uso correcto: /riesgo 1000"

