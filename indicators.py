def get_rsi(candles, period=14):
    if len(candles) < period + 1:
        return 50  # حيادي

    gains = []
    losses = []

    for i in range(-period, -1):
        diff = float(candles[i][4]) - float(candles[i - 1][4])
        if diff > 0:
            gains.append(diff)
        else:
            losses.append(abs(diff))

    avg_gain = sum(gains) / period if gains else 0.0001
    avg_loss = sum(losses) / period if losses else 0.0001

    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi

# ✅ خففنا شرط الفوليوم (من 2.5x إلى 1.5x)
def get_volume_spike(candles, multiplier=1.5):
    if len(candles) < 6:
        return False
    volumes = [float(c[5]) for c in candles[:-1]]
    avg_volume = sum(volumes) / len(volumes)
    last_volume = float(candles[-1][5])
    return last_volume > avg_volume * multiplier

# ✅ نفس الشرط لكن مع السماح بمرونة الدخول
def get_bullish_candle(prev_candle, curr_candle):
    prev_close = float(prev_candle[4])
    curr_open = float(curr_candle[1])
    curr_close = float(curr_candle[4])
    return curr_close > curr_open and curr_close > prev_close