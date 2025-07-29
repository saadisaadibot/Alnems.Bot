import os
import requests
import redis
from statistics import mean
from utils import get_candles  # لازم ترجع 60 شمعة بدقة 1m

r = redis.from_url(os.getenv("REDIS_URL"))
FAKE_MEMORY = "nems:confidence"

def get_top_markets(limit=40):
    response = requests.get("https://api.bitvavo.com/v2/markets")
    markets = response.json()
    eur_markets = [m["market"] for m in markets if m["market"].endswith("-EUR")]
    return eur_markets[:limit]

def analyze_trend(candles):
    closes = [float(c[4]) for c in candles]
    highs = [float(c[2]) for c in candles]
    lows = [float(c[3]) for c in candles]

    high = max(highs)
    low = min(lows)
    last = closes[-1]

    position = (last - low) / (high - low) * 100  # قاع = 0، قمة = 100
    volatility = (high - low) / low * 100
    slope = (closes[-1] - closes[0]) / closes[0] * 100  # الميل العام

    wave_range = max(closes) - min(closes)
    wave_chance = (wave_range / low) * 100

    return {
        "position": round(position, 1),
        "volatility": round(volatility, 2),
        "slope": round(slope, 2),
        "last": last,
        "low": low,
        "high": high,
        "wave": round(wave_chance, 2)
    }

def pick_best_symbol():
    frozen = [k.decode().split(":")[-1] for k in r.scan_iter("nems:freeze:*")]
    top = get_top_markets()

    for symbol in top:
        if symbol in frozen:
            continue  # العملة مجمّدة مؤقتًا بسبب فشل شراء

        try:
            candles = get_candles(symbol, interval="1m", limit=60)
            if len(candles) < 30:
                continue

            trend = analyze_trend(candles)
            confidence = float(r.hget("nems:confidence", symbol) or 1.0)

            pos = trend["position"]
            wave = trend["wave"]
            slope = trend["slope"]
            volatility = trend["volatility"]

            if pos < 15 and slope > -2 and wave > 4 and volatility > 2:
                if confidence >= 1.0:
                    reason = f"📈 {symbol} Pos={pos}%, Slope={slope}%, Vol={volatility}%"
                    return symbol, reason, trend
            elif pos < 25 and confidence >= 1.5:
                continue  # راقب فقط

        except Exception as e:
            continue

    return None, None, None