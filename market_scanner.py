import os
import redis
from bitvavo_client.bitvavo import Bitvavo
from utils import get_rsi, get_volume_spike

# الاتصال بـ Redis و Bitvavo
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
            # شرط السعر + الفوليوم
            ticker = BITVAVO.ticker24h({"market": symbol})
            price_change = float(ticker.get("priceChangePercentage", 0))
            volume = float(ticker.get("volume", 0))

            if price_change <= 1 or volume < 500:
                continue

            # جلب الشموع وتحليل الزخم
            candles = BITVAVO.candles(symbol, "1m", {"limit": 10})
            if not get_volume_spike(candles):
                continue

            # فحص RSI بعد التأكد من الزخم
            rsi = get_rsi(symbol)
            if rsi >= level:
                continue

            candidates.append((symbol, rsi, price_change))

        except:
            continue

    if not candidates:
        return None, None, None

    # ترتيب حسب أقل RSI = فرصة ارتداد أقوى
    candidates.sort(key=lambda x: x[1])
    best = candidates[0]
    return best[0], f"RSI={best[1]}, Change={best[2]}", best[2]