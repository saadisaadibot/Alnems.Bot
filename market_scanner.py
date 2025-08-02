import requests
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
        print("📩 رد Bitvavo:", res.status_code)
        all_markets = [m["market"] for m in res.json()]
        volumes = []

        for m in all_markets:
            try:
                candles = get_candles(m, interval="1m", limit=30)
                if len(candles) < 10:
                    continue
                volume = sum(float(c[5]) for c in candles)
                volumes.append((m, volume))
            except Exception as e:
                print(f"❌ خطأ أثناء جلب الشموع لـ {m}:", str(e))
                continue

        sorted_markets = sorted(volumes, key=lambda x: x[1], reverse=True)
        print("📊 Top 40 by volume:")
        for m, vol in sorted_markets[:limit]:
            print(f" - {m}: {vol:.0f}")
        return [m[0] for m in sorted_markets[:limit]]

    except Exception as e:
        print("❌ خطأ أثناء جلب الأسواق:", str(e))
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

    if now - last_fetch > 300:
        print("📊 تحديث قائمة العملات...")
        cached_top = get_top_markets()
        last_fetch = now

    frozen = set(k.decode().split(FREEZE_PREFIX)[-1] for k in r.scan_iter(f"{FREEZE_PREFIX}*"))
    params = load_params()
    candidates = []

    for symbol in cached_top:
        if symbol in frozen:
            continue

        try:
            candles = get_candles(symbol, interval="1m", limit=60)
            if len(candles) < 40:
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

            # 🔍 Volume Spike - دقيق: 3 شموع أخيرة مقابل 30 سابقة
            volumes = [float(c[5]) for c in candles]
            recent = sum(volumes[-3:]) / 3
            past = sum(volumes[-33:-3]) / 30 if len(volumes) >= 36 else 0
            if recent > past * 2:
                score += 2  # ✅ نعطيه نقطتين لأنه أقوى مؤشر
                debug.append("✅ Volume Spike (3min vs 30min)")
            else:
                debug.append("❌ Volume Spike")

            if score >= 4 and confidence >= 1.0:
                candidates.append((symbol, score, debug, trend))

        except Exception as e:
            print(f"⚠️ خطأ في {symbol}: {e}")
            continue

    if candidates:
        best = max(candidates, key=lambda x: x[1])  # اختار الأعلى نقاط
        reason = f"🔥 {best[0]} | نقاط={best[1]} | " + " | ".join(best[2])
        return best[0], reason, best[3]

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