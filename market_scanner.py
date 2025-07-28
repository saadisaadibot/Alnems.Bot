import os
import redis
from bitvavo_client.bitvavo import Bitvavo
from utils import get_rsi, get_volume_spike

# إعداد الاتصال بـ Redis
r = redis.from_url(os.getenv("REDIS_URL"))

# إعداد الاتصال بـ Bitvavo
BITVAVO = Bitvavo({
    'APIKEY'   : os.getenv("BITVAVO_API_KEY"),
    'APISECRET': os.getenv("BITVAVO_API_SECRET"),
    'RESTURL'  : 'https://api.bitvavo.com/v2',
    'WSURL'    : 'wss://ws.bitvavo.com/v2'
})

# الدالة الرئيسية لاختيار أفضل عملة
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
            # جلب بيانات السوق
            ticker = BITVAVO.ticker24h({"market": symbol})
            price_change_raw = ticker.get("priceChangePercentage")
            volume_raw = ticker.get("volume")

            if price_change_raw is None or volume_raw is None:
                print(f"⛔ بيانات ناقصة لـ {symbol}")
                continue

            price_change = float(price_change_raw)
            volume = float(volume_raw)

            if price_change <= 1 or volume < 500:
                continue

            # جلب الشموع
            candles = BITVAVO.candles(symbol, "1m", {"limit": 10})
            spike = get_volume_spike(candles)
            rsi = get_rsi(symbol)

            print(f"🔍 {symbol} | Change={price_change:.2f}% | Volume={volume:.0f} | RSI={rsi:.2f} | Spike={spike}")

            if not spike or rsi >= level:
                continue

            candidates.append((symbol, rsi, price_change))

        except Exception as e:
            print(f"⚠️ خطأ أثناء تحليل {symbol}: {e}")
            continue

    if not candidates:
        return None, None, None

    candidates.sort(key=lambda x: x[1])
    best = candidates[0]
    return best[0], f"RSI={best[1]}, Change={best[2]}", best[2]