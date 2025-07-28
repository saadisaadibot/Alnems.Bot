import os
import redis
from bitvavo_client.bitvavo import Bitvavo
from utils import get_rsi, get_volume_spike

r = redis.from_url(os.getenv("REDIS_URL"))

BITVAVO = Bitvavo({
    'APIKEY'   : os.getenv("BITVAVO_API_KEY"),
    'APISECRET': os.getenv("BITVAVO_API_SECRET"),
    'RESTURL'  : 'https://api.bitvavo.com/v2',
    'WSURL'    : 'wss://ws.bitvavo.com/v2'
})

def pick_best_symbol():
    level = int(r.get("nems:rsi_level") or 46)
    try:
        markets = BITVAVO.markets()
        print(f"✅ تم جلب عدد الأسواق: {len(markets)}")
    except Exception as e:
        print(f"❌ فشل جلب الأسواق: {e}")
        return None, None, None

    candidates = []

    for market_data in markets:
        if not isinstance(market_data, dict):
            continue

        symbol = market_data.get("market", "")
        if not symbol.endswith("-EUR"):
            continue

        try:
            candles = BITVAVO.candles(symbol, "1m", {"limit": 10})
            if len(candles) < 2:
                continue

            first = float(candles[0][4])
            last = float(candles[-1][4])
            price_change = ((last - first) / first) * 100
            volume_sum = sum(float(c[5]) for c in candles)

            if price_change <= 1 or volume_sum < 500:
                continue

            if not get_volume_spike(candles):
                continue

            rsi = get_rsi(symbol)
            if rsi >= level:
                continue

            candidates.append((symbol, rsi, price_change))

        except Exception as e:
            print(f"⚠️ تحليل فشل لـ {symbol}: {e}")
            continue

    if not candidates:
        return None, None, None

    candidates.sort(key=lambda x: x[1])
    best = candidates[0]
    return best[0], f"RSI={best[1]}, Change={best[2]}", best[2]