import os
import redis
from bitvavo_client.bitvavo import Bitvavo

r = redis.from_url(os.getenv("REDIS_URL"))

BITVAVO = Bitvavo({
    'APIKEY'   : os.getenv("BITVAVO_API_KEY"),
    'APISECRET': os.getenv("BITVAVO_API_SECRET"),
    'RESTURL'  : 'https://api.bitvavo.com/v2',
    'WSURL'    : 'wss://ws.bitvavo.com/v2'
})

def get_rsi(symbol, interval="1m", limit=100):
    try:
        candles = BITVAVO.candles(symbol, interval, {"limit": limit})
        closes = [float(c[4]) for c in candles]
    except:
        return 50

    if len(closes) < 15:
        return 50

    gains = []
    losses = []

    for i in range(1, len(closes)):
        delta = closes[i] - closes[i - 1]
        gains.append(max(delta, 0))
        losses.append(max(-delta, 0))

    avg_gain = sum(gains[-14:]) / 14
    avg_loss = sum(losses[-14:]) / 14 or 0.0001

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