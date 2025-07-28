import os
import redis
from bitvavo_client.bitvavo import Bitvavo
from utils import get_rsi, get_volume_spike

r = redis.from_url(os.getenv("REDIS_URL"))

BITVAVO = Bitvavo({
    'APIKEY': os.getenv("BITVAVO_API_KEY"),
    'APISECRET': os.getenv("BITVAVO_API_SECRET"),
    'RESTURL': 'https://api.bitvavo.com/v2',
    'WSURL': 'wss://ws.bitvavo.com/v2'
})

def pick_best_symbol():
    rsi_level = int(r.get("nems:rsi_level") or 46)
    try:
        markets = BITVAVO.markets()
    except:
        return None, None, None

    candidates = []

    for m in markets:
        if not isinstance(m, dict):
            continue

        symbol = m.get("market", "")
        if not symbol.endswith("-EUR"):
            continue

        try:
            candles = BITVAVO.candles(symbol, "1m", {"limit": 15})
            if not candles or len(candles) < 10:
                continue

            if not get_volume_spike(candles):
                continue

            rsi = get_rsi(candles)
            if rsi >= rsi_level:
                continue

            price_change = (float(candles[-1][4]) - float(candles[0][4])) / float(candles[0][4]) * 100

            candidates.append((symbol, rsi, price_change))
        except:
            continue

    if not candidates:
        return None, None, None

    candidates.sort(key=lambda x: x[1])  # أقل RSI أولاً
    best = candidates[0]
    return best[0], f"RSI={best[1]}, Change={best[2]:.2f}%", best[2]