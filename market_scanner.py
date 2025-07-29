import time
import redis
from utils import get_candles, calculate_rsi

r = redis.from_url(os.getenv("REDIS_URL"))
RSI_LEVEL_KEY = "nems:rsi_level"

def pick_best_symbol():
    rsi_threshold = int(r.get(RSI_LEVEL_KEY) or 46)
    markets = ["BTC-EUR", "ETH-EUR", "XRP-EUR", "ADA-EUR", "DOGE-EUR"]

    for symbol in markets:
        candles = get_candles(symbol, interval="1m", limit=15)
        if len(candles) < 15:
            continue

        rsi = calculate_rsi(candles)
        volume = sum(float(c[5]) for c in candles[-3:])

        if rsi <= rsi_threshold and volume > 1000:
            return symbol, f"RSI={rsi}", rsi

    return None, None, None