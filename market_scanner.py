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

# 🔀 دمج عملات من مصادر مختلفة
def collect_mixed_top_markets():
    print("🔍 بدء تجميع العملات من مصادر متنوعة...")
    try:
        res = requests.get("https://api.bitvavo.com/v2/markets")
        all_markets = [m["market"] for m in res.json() if "-EUR" in m["market"]]

        top_30min = []
        top_24h = []
        top_7d = []
        explosive = []

        for symbol in all_markets:
            try:
                base = symbol.replace("-EUR", "")

                # 🔸 آخر 30 دقيقة
                candles_30m = get_candles(symbol, interval="1m", limit=30)
                volume_30m = sum(float(c[5]) for c in candles_30m)
                top_30min.append((symbol, volume_30m))

                # 🔸 آخر 24 ساعة (15m * 96)
                candles_1d = get_candles(symbol, interval="15m", limit=96)
                volume_1d = sum(float(c[5]) for c in candles_1d)
                top_24h.append((symbol, volume_1d))

                # 🔸 آخر 7 أيام (1d)
                candles_7d = get_candles(symbol, interval="1d", limit=7)
                if len(candles_7d) >= 2:
                    start = float(candles_7d[0][4])
                    end = float(candles_7d[-1][4])
                    change = ((end - start) / start) * 100
                    top_7d.append((symbol, change))

                # 🔸 هل حصل انفجار بيومي؟ (أكثر من 10%)
                for c in candles_7d:
                    open_ = float(c[1])
                    close = float(c[4])
                    if (close - open_) / open_ * 100 >= 10:
                        explosive.append(symbol)
                        break

            except Exception as e:
                continue

        top_30min = sorted(top_30min, key=lambda x: x[1], reverse=True)[:10]
        top_24h = sorted(top_24h, key=lambda x: x[1], reverse=True)[:10]
        top_7d = sorted(top_7d, key=lambda x: x[1], reverse=True)[:10]

        combined = list(dict.fromkeys(
            [x[0] for x in top_30min + top_24h + top_7d] + explosive
        ))

        print(f"✅ تم تجميع {len(combined)} عملة.")
        return combined[:40]

    except Exception as e:
        print(f"❌ خطأ في جمع العملات: {e}")
        return []

# 🧠 اختيار العملة بناءً على نظام النقاط الذكي
def pick_best_symbol():
    global last_fetch, cached_top
    now = time.time()

    if now - last_fetch > 300:
        cached_top = collect_mixed_top_markets()
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
            notes = []

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

            # Volume Spike
            volumes = [float(c[5]) for c in candles]
            recent = sum(volumes[-3:]) / 3
            past = sum(volumes[-33:-3]) / 30 if len(volumes) >= 36 else 0
            if past > 0 and recent > past * 2:
                score += 2
                debug.append("✅ Volume Spike (3m>30m)")
                notes.append("🔼 نشاط مفاجئ")
            else:
                debug.append("❌ Volume Spike")

            if confidence < 0.5:
                notes.append("⚠️ ثقة منخفضة")
                continue

            if score >= 4:
                candidates.append((symbol, score, debug, trend, notes, confidence))

        except Exception as e:
            print(f"⚠️ خطأ في {symbol}: {e}")
            continue

    if candidates:
        best = max(candidates, key=lambda x: (x[1], x[5]))
        reason = f"🔥 {best[0]} | نقاط={best[1]} | " + " | ".join(best[2])
        if best[4]:
            reason += " | " + " ".join(best[4])
        return best[0], reason, best[3]

    return None, None, None

# 📋 عرض أقوى العملات حتى لو لم تصل للحد الأدنى للنقاط
def get_top_candidates(limit=5):
    global last_fetch, cached_top
    now = time.time()

    if now - last_fetch > 600:
        cached_top = collect_mixed_top_markets()
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