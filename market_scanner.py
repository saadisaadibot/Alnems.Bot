import os
import time
import requests
import redis
from utils import get_candles

r = redis.from_url(os.getenv("REDIS_URL"))
CONFIDENCE_KEY = "nems:confidence"
FREEZE_PREFIX = "nems:freeze:"

last_fetch = 0
cached_top = []

# ✅ جلب أفضل 40 عملة حسب حجم التداول في آخر 30 دقيقة (يُحدّث كل 10 دقائق فقط)
def get_top_markets(limit=40):
    try:
        res = requests.get("https://api.bitvavo.com/v2/markets")
        all_markets = [m["market"] for m in res.json() if m["market"].endswith("-EUR")]
        market_volumes = []

        for market in all_markets:
            try:
                candles = get_candles(market, interval="1m", limit=30)
                if len(candles) < 10:
                    continue
                volume = sum(float(c[5]) for c in candles)
                market_volumes.append((market, volume))
            except Exception as e:
                print(f"خطأ بجمع شموع {market}: {e}")
                continue

        top = sorted(market_volumes, key=lambda x: x[1], reverse=True)
        return [m[0] for m in top[:limit]]
    except Exception as e:
        print(f"فشل في get_top_markets: {e}")
        return []

# ✅ تحليل ذكي لاتجاه السوق للعملة
def analyze_trend(candles):
    closes = [float(c[4]) for c in candles]
    highs = [float(c[2]) for c in candles]
    lows = [float(c[3]) for c in candles]
    volumes = [float(c[5]) for c in candles]

    high = max(highs)
    low = min(lows)
    last = closes[-1]

    position = (last - low) / (high - low) * 100
    slope = (closes[-1] - closes[0]) / closes[0] * 100
    volatility = (high - low) / low * 100
    wave = (max(closes) - min(closes)) / low * 100
    volume_spike = volumes[-1] > (sum(volumes[:-5]) / len(volumes[:-5])) * 2

    return {
        "position": round(position, 1),
        "slope": round(slope, 2),
        "volatility": round(volatility, 2),
        "wave": round(wave, 2),
        "last": last,
        "volume_spike": volume_spike
    }

# ✅ اختيار أفضل عملة للدخول بناءً على المؤشرات
def pick_best_symbol():
    global last_fetch, cached_top
    now = time.time()

    if now - last_fetch > 600:  # تحديث القائمة كل 10 دقائق
        print("📊 تحديث قائمة أفضل العملات...")
        cached_top = get_top_markets()
        last_fetch = now

    frozen = set(k.decode().split(FREEZE_PREFIX)[-1] for k in r.scan_iter(f"{FREEZE_PREFIX}*"))

    for symbol in cached_top:
        if symbol in frozen:
            continue

        try:
            candles = get_candles(symbol, interval="1m", limit=60)
            if len(candles) < 30:
                continue

            trend = analyze_trend(candles)
            confidence = float(r.hget(CONFIDENCE_KEY, symbol) or 1.0)

            pos = trend["position"]
            slope = trend["slope"]
            vol = trend["volatility"]
            wave = trend["wave"]
            spike = trend["volume_spike"]

            if pos < 20 and slope > -1 and wave > 5 and vol > 2 and spike:
                if confidence >= 1.0:
                    reason = f"🔥 {symbol} Pos={pos}% Slope={slope}% Wave={wave}% Vol={vol}%"
                    return symbol, reason, trend

        except Exception as e:
            print(f"❌ خطأ في تحليل {symbol}: {e}")
            continue

    return None, None, None