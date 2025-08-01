import os
import time
import redis
import json
from utils import get_candles

r = redis.from_url(os.getenv("REDIS_URL"))
CONFIDENCE_KEY = "nems:confidence"
FREEZE_PREFIX = "nems:freeze:"
PARAMS_KEY = "nems:strategy_params"
last_fetch = 0
cached_top = []

# ⚙️ تحميل أو إنشاء المعايير الديناميكية
def load_params():
    default = {
        "pos_max": 25,
        "slope_min": -1,
        "wave_min": 4,
        "vol_min": 1.5,
        "min_score": 3
    }
    saved = r.hgetall(PARAMS_KEY)
    for k, v in default.items():
        if k not in saved:
            r.hset(PARAMS_KEY, k, v)
    return {k: float(saved.get(k.encode(), v)) for k, v in default.items()}

# 📊 تحديث توب 40 بناءً على حجم التداول آخر 30 دقيقة
def get_top_markets(limit=40):
    print("🚀 دخل فعليًا إلى get_top_markets()")
    try:
        res = requests.get("https://api.bitvavo.com/v2/markets")
        all_markets = [m["market"] for m in res.json() if m["market"].endswith("-EUR")]
        volumes = []

        for m in all_markets:
            try:
                candles = get_candles(m, interval="1m", limit=30)
                if len(candles) < 10:
                    continue
                volume = sum(float(c[5]) for c in candles)
                volumes.append((m, volume))
            except:
                continue

        sorted_markets = sorted(volumes, key=lambda x: x[1], reverse=True)
        print("📊 Top 40 by volume:", [f"{m[0]}: {round(m[1], 2)}" for m in sorted_markets[:40]])
        return [m[0] for m in sorted_markets[:limit]]
    except:
        return []

# 🧠 تحليل المؤشرات للشموع
def analyze_trend(candles):
    closes = [float(c[4]) for c in candles]
    highs = [float(c[2]) for c in candles]
    lows = [float(c[3]) for c in candles]
    volumes = [float(c[5]) for c in candles]

    high = max(highs)
    low = min(lows)
    last = closes[-1]

    return {
        "position": round((last - low) / (high - low) * 100, 1),
        "slope": round((closes[-1] - closes[0]) / closes[0] * 100, 2),
        "volatility": round((high - low) / low * 100, 2),
        "wave": round((max(closes) - min(closes)) / low * 100, 2),
        "volume_spike": volumes[-1] > (sum(volumes[:-5]) / len(volumes[:-5])) * 2
    }

# 🧠 اختيار العملة بناءً على نظام النقاط الذكي
def pick_best_symbol():
    global last_fetch, cached_top
    now = time.time()

    # كل 10 دقائق يحدث قائمة العملات النشطة
    if now - last_fetch > 10:
        print("📊 تحديث قائمة العملات...")
        cached_top = get_top_markets()
        last_fetch = now

    frozen = set(k.decode().split(FREEZE_PREFIX)[-1] for k in r.scan_iter(f"{FREEZE_PREFIX}*"))
    params = load_params()

    for symbol in cached_top:
        if symbol in frozen:
            continue

        try:
            candles = get_candles(symbol, interval="1m", limit=60)
            if len(candles) < 30:
                continue

            trend = analyze_trend(candles)
            confidence = float(r.hget(CONFIDENCE_KEY, symbol) or 1.0)

            score = 0
            debug = []

            if trend["position"] < params["pos_max"]:
                score += 1
                debug.append(f"✅ Pos={trend['position']}%")
            else:
                debug.append(f"❌ Pos={trend['position']}%")

            if trend["slope"] > params["slope_min"]:
                score += 1
                debug.append(f"✅ Slope={trend['slope']}%")
            else:
                debug.append(f"❌ Slope={trend['slope']}%")

            if trend["wave"] > params["wave_min"]:
                score += 1
                debug.append(f"✅ Wave={trend['wave']}%")
            else:
                debug.append(f"❌ Wave={trend['wave']}%")

            if trend["volatility"] > params["vol_min"]:
                score += 1
                debug.append(f"✅ Vol={trend['volatility']}%")
            else:
                debug.append(f"❌ Vol={trend['volatility']}%")

            if trend["volume_spike"]:
                score += 1
                debug.append(f"✅ Volume Spike")
            else:
                debug.append(f"❌ Volume Spike")

            if score >= params["min_score"] and confidence >= 1.0:
                reason = f"🔥 {symbol} | نقاط={score} | " + " | ".join(debug)
                return symbol, reason, trend

        except Exception as e:
            print(f"⚠️ خطأ في {symbol}: {e}")
            continue

    return None, None, None
# 📋 عرض أقوى العملات حتى لو لم تصل للحد الأدنى للنقاط
def get_top_candidates(limit=5):
    global last_fetch, cached_top
    now = time.time()

    if now - last_fetch > 600:
        cached_top = get_top_markets()
        last_fetch = now

    frozen = set(k.decode().split(FREEZE_PREFIX)[-1] for k in r.scan_iter(f"{FREEZE_PREFIX}*"))
    params = load_params()
    results = []

    for symbol in cached_top:
        if symbol in frozen:
            continue
        try:
            candles = get_candles(symbol, interval="1m", limit=60)
            if len(candles) < 30:
                continue

            trend = analyze_trend(candles)
            score = 0
            debug = []

            if trend["position"] < params["pos_max"]:
                score += 1
                debug.append(f"✅ Pos")
            else:
                debug.append(f"❌ Pos")

            if trend["slope"] > params["slope_min"]:
                score += 1
                debug.append(f"✅ Slope")
            else:
                debug.append(f"❌ Slope")

            if trend["wave"] > params["wave_min"]:
                score += 1
                debug.append(f"✅ Wave")
            else:
                debug.append(f"❌ Wave")

            if trend["volatility"] > params["vol_min"]:
                score += 1
                debug.append(f"✅ Vol")
            else:
                debug.append(f"❌ Vol")

            if trend["volume_spike"]:
                score += 1
                debug.append(f"✅ Spike")
            else:
                debug.append(f"❌ Spike")

            results.append((symbol, score, debug))
        except:
            continue

    sorted_results = sorted(results, key=lambda x: x[1], reverse=True)
    return sorted_results[:limit]