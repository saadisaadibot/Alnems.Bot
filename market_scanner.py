import os
import redis
from bitvavo_client.bitvavo import Bitvavo
from utils import get_rsi

r = redis.from_url(os.getenv("REDIS_URL"))

BITVAVO = Bitvavo({
    'APIKEY': os.getenv("BITVAVO_API_KEY"),
    'APISECRET': os.getenv("BITVAVO_API_SECRET"),
    'RESTURL': 'https://api.bitvavo.com/v2',
    'WSURL': 'wss://ws.bitvavo.com/v2'
})

def pick_best_symbol():
    level = int(r.get("nems:rsi_level") or 46)
    try:
        markets = BITVAVO.markets()
    except:
        return None, None, None

    candidates = []

    for market in markets:
        symbol = market.get("market", "")
        if not symbol.endswith("-EUR"):
            continue

        try:
            ticker = BITVAVO.ticker24h({"market": symbol})
            price_change = float(ticker.get("priceChangePercentage", 0))
            volume = float(ticker.get("volume", 0))

            if price_change > 1 and volume > 1000:
                rsi = get_rsi(symbol)
                if rsi < level:
                    candidates.append((symbol, rsi, price_change))
        except:
            continue

    if not candidates:
        return None, None, None

    # ترتيب حسب أقل RSI
    candidates.sort(key=lambda x: x[1])
    best = candidates[0]
    return best[0], f"RSI={best[1]}, Change={best[2]}", best[2]