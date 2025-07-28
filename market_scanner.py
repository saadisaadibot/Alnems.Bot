import time
from bitvavo_client.bitvavo import Bitvavo
import os

BITVAVO = Bitvavo({
    'APIKEY': os.getenv("BITVAVO_API_KEY"),
    'APISECRET': os.getenv("BITVAVO_API_SECRET"),
    'RESTURL': 'https://api.bitvavo.com/v2',
    'WSURL': 'wss://ws.bitvavo.com/v2'
})

def get_candles(symbol, interval="1m", limit=20):
    try:
        candles = BITVAVO.candles(symbol, interval, {"limit": limit})
        return candles
    except:
        return []

def get_rsi(candles, period=14):
    if len(candles) < period + 1:
        return 50
    gains, losses = [], []
    for i in range(-period, -1):
        diff = float(candles[i][4]) - float(candles[i - 1][4])
        if diff > 0:
            gains.append(diff)
        else:
            losses.append(abs(diff))
    avg_gain = sum(gains) / period if gains else 0.0001
    avg_loss = sum(losses) / period if losses else 0.0001
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def get_volume_spike(candles, multiplier=2.0):
    if len(candles) < 6:
        return False
    volumes = [float(c[5]) for c in candles[:-1]]
    avg_volume = sum(volumes) / len(volumes)
    last_volume = float(candles[-1][5])
    return last_volume > avg_volume * multiplier

def get_bullish_candle(prev_candle, curr_candle):
    prev_close = float(prev_candle[4])
    curr_open = float(curr_candle[1])
    curr_close = float(curr_candle[4])
    return curr_close > curr_open and curr_close > prev_close

def meets_smart_conditions(candles):
    if len(candles) < 15:
        return False

    rsi = get_rsi(candles)
    volume_ok = get_volume_spike(candles)
    bullish = get_bullish_candle(candles[-2], candles[-1])

    # استراتيجية تعليم ذاتي أولية: شروط سهلة
    if rsi < 60 and volume_ok and bullish:
        return True
    return False

def pick_best_symbol():
    symbols = []
    try:
        markets = BITVAVO.markets()
        symbols = [m["market"] for m in markets if m["quote"] == "EUR" and "-" in m["market"]]
    except:
        return None, "خطأ تحميل الرموز", 0

    best_score = 0
    best_symbol = None
    best_reason = ""

    for symbol in symbols:
        candles = get_candles(symbol)
        if not candles:
            continue

        if meets_smart_conditions(candles):
            rsi = get_rsi(candles)
            vol_ratio = float(candles[-1][5]) / (sum([float(c[5]) for c in candles[:-1]]) / len(candles[:-1]))
            score = (100 - rsi) * vol_ratio
            if score > best_score:
                best_score = score
                best_symbol = symbol
                best_reason = f"RSI={round(rsi,1)} | Volume spike={round(vol_ratio,1)}"

    if best_symbol:
        return best_symbol, best_reason, best_score
    return None, "لا يوجد فرصة قوية حالياً.", 0