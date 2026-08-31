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
    try:
        formatted_symbol = f"{symbol}/USDT"
        ticker = exchange.fetch_ticker(formatted_symbol)
        current_price = ticker.get('last', 0)
        change_24h = ticker.get('percentage', 0)
        high_24h = ticker.get('high', 0)
        low_24h = ticker.get('low', 0)
        volume_24h = ticker.get('quoteVolume', ticker.get('baseVolume', 0))
    except Exception:
        current_price, change_24h, high_24h, low_24h, volume_24h = 0, 0, 0, 0, 0

    df_15m = fetch_data(symbol, '15m', limit=50)
    current_rsi = 50.0
    if df_15m is not None and not df_15m.empty:
        df_15m['rsi'] = calculate_rsi(df_15m)
        if not df_15m['rsi'].empty and not np.isnan(df_15m['rsi'].iloc[-1]):
            current_rsi = round(df_15m['rsi'].iloc[-1], 1)

    if current_rsi > 60:
        estado = f"🟢 COMPRA - {symbol}-USDT"
        diagnostico = f"Tendencia alcista. RSI: {current_rsi}. Impulso comprador activo."
    elif current_rsi < 40:
        estado = f"🔴 VENTA - {symbol}-USDT"
        diagnostico = f"Presión bajista. RSI: {current_rsi}. Vigilar soporte cercano."
    else:
        estado = f"⚪ SIN SEÑAL - {symbol}-USDT"
        diagnostico = f"Mercado lateral. RSI: {current_rsi}. Sin señal clara. Esperar ruptura."

    change_str = f"+{change_24h:.2f}%" if change_24h >= 0 else f"{change_24h:.2f}%"

    msg = f"{estado}\n\n"
    msg += f"💵 Precio: ${current_price:,.2f}\n"
    msg += f"📊 Cambio 24h: {change_str}\n"
    msg += f"📈 Máx 24h: ${high_24h:,.2f}\n"
    msg += f"📉 Mín 24h: ${low_24h:,.2f}\n"
    msg += f"📦 Volumen: {volume_24h:,.0f}\n\n"
    msg += f"{diagnostico}\n\n"
    msg += f"⏱️ Temporalidad: 15m - 1H\n"
    msg += f"⚠️ Gestión de riesgo obligatoria\n"
    msg += f"🚀 Nunca inviertas más del 2%"

    return msg

# Alias para compatibilidad con ambos nombres de funciones
analyze_market = analizar_mercado_symbol

def calcular_riesgo(capital_usdt, sl_percent=1.5):
    try:
        capital = float(capital_usdt)
        risk_amount = round(capital * (sl_percent / 100), 2)
        msg = f"🧮 **GESTIÓN DE RIESGO**\n\n"
        msg += f"💰 **Capital Base:** ${capital:,.2f} USDT\n"
        msg += f"⚡ **Apalancamiento Sugerido:** 5x - 10x\n"
        msg += f"📦 **Tamaño de Posición (5x):** ${capital * 5:,.2f} USDT\n"
        msg += f"🛑 **Pérdida Máxima al SL ({sl_percent}%):** -${risk_amount:,.2f} USDT\n\n"
        msg += f"⚠️ **Recomendación:** No usar apalancamiento mayor a 10x."
        return msg
    except ValueError:
        return "⚠️ Uso correcto: /riesgo 1000"
# Alias para que reconozca calculate_risk en inglés
calculate_risk = calcular_riesgo
