import os
import requests
import redis
from utils import get_candles

r = redis.from_url(os.getenv("REDIS_URL"))
CONFIDENCE_KEY = "nems:confidence"
FREEZE_PREFIX = "nems:freeze:"

def get_top_markets(limit=50):
    try:
        res = requests.get("https://api.bitvavo.com/v2/markets")
        markets = res.json()
        return [m["market"] for m in markets if m["market"].endswith("-EUR")][:limit]
    except:
        return []

def analyze_trend(candles):
    closes = [float(c[4]) for c in candles]
    highs = [float(c[2]) for c in candles]
    lows = [float(c[3]) for c in candles]
    volumes = [float(c[5]) for c in candles]

    high = max(highs)
    low = min(lows)
    last = closes[-1]

    position = (last - low) / (high - low) * 100  # نسبة بين القاع والقمة
    slope = (closes[-1] - closes[0]) / closes[0] * 100
    volatility = (high - low) / low * 100
    wave = (max(closes) - min(closes)) / low * 100
    volume_spike = volumes[-1] > (sum(volumes[:-5]) / len(volumes[:-5])) * 2  # ارتفاع بالحجم

    return {
        "position": round(position, 1),
        "slope": round(slope, 2),
        "volatility": round(volatility, 2),
        "wave": round(wave, 2),
        "last": last,
        "volume_spike": volume_spike
    }

def pick_best_symbol():
    frozen = set(k.decode().split(FREEZE_PREFIX)[-1] for k in r.scan_iter(f"{FREEZE_PREFIX}*"))
    top = get_top_markets()

    for symbol in top:
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

            # الذكاء هنا: اختيار قاع منخفض + ميل إيجابي + حركة عنيفة + حجم مرتفع
            if pos < 20 and slope > -1 and wave > 5 and vol > 2 and spike:
                if confidence >= 1.0:
                    reason = f"🔥 {symbol} Pos={pos}% Slope={slope}% Wave={wave}% Vol={vol}%"
                    return symbol, reason, trend

            # شرط راقب فقط: قاع متوسط وثقة مرتفعة
            elif pos < 30 and confidence >= 1.7:
                continue

        except Exception as e:
            continue

    return None, None, None