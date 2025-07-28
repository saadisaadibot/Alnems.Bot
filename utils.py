def get_rsi(candles, period=14):
    if len(candles) < period + 1:
        return 50  # حيادي في حال البيانات ناقصة

    closes = [float(c[4]) for c in candles]
    gains = []
    losses = []

    for i in range(1, len(closes)):
        diff = closes[i] - closes[i - 1]
        if diff > 0:
            gains.append(diff)
        else:
            losses.append(abs(diff))

    avg_gain = sum(gains[-period:]) / period if gains else 0.0001
    avg_loss = sum(losses[-period:]) / period if losses else 0.0001

    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return round(rsi, 2)

def get_volume_spike(candles, multiplier=1.5):
    if len(candles) < 6:
        return False
    volumes = [float(c[5]) for c in candles[:-1]]
    avg_volume = sum(volumes) / len(volumes)
    last_volume = float(candles[-1][5])
    return last_volume > avg_volume * multiplier

def fetch_price(symbol):
    from bitvavo_client.bitvavo import Bitvavo
    import os

    bitvavo = Bitvavo({
        'APIKEY': os.getenv("BITVAVO_API_KEY"),
        'APISECRET': os.getenv("BITVAVO_API_SECRET"),
        'RESTURL': 'https://api.bitvavo.com/v2',
        'WSURL': 'wss://ws.bitvavo.com/v2'
    })

    try:
        price = bitvavo.tickerPrice({"market": symbol})
        return float(price["price"])
    except:
        return None