import redis
import os
import json

r = redis.from_url(os.getenv("REDIS_URL"))

TRADE_KEY = "nems:trades"
CONFIDENCE_KEY = "nems:confidence"
STRATEGY_KEY = "nems:strategy"

# ✅ تخزين الصفقة في الذاكرة
def save_trade(symbol, entry_price, exit_price, reason, result, percent):
    trade = {
        "symbol": symbol,
        "entry": round(entry_price, 6),
        "exit": round(exit_price, 6),
        "result": result,
        "percent": round(percent, 2),
        "reason": reason
    }
    r.lpush(TRADE_KEY, json.dumps(trade))
    r.ltrim(TRADE_KEY, 0, 49)  # نحفظ آخر 50 صفقة فقط

    # تعديل الثقة
    success = percent >= 0
    update_confidence(symbol, success)

    # تعديل الاستراتيجية إذا كان لدينا 3 صفقات على الأقل
    if r.llen(TRADE_KEY) >= 3:
        adjust_strategy_from_trade()

# 🔁 تعديل ثقة العملة بناءً على نتيجة الصفقة
def update_confidence(symbol, success):
    current = float(r.hget(CONFIDENCE_KEY, symbol) or 1.0)
    if success:
        new = current + 0.2
    else:
        new = max(current - 0.3, 0.5)
    r.hset(CONFIDENCE_KEY, symbol, round(new, 2))

# 🧠 تعديل الاستراتيجية بناءً على آخر 3 صفقات
def adjust_strategy_from_trade():
    trades = [json.loads(x) for x in r.lrange(TRADE_KEY, 0, 2)]
    if len(trades) < 3:
        return

    wins = sum(1 for t in trades if t["result"] == "win")
    losses = 3 - wins

    if wins >= 2:
        # ✅ رفع الحدة: تقليل الشروط لتجريب فرص أكثر
        r.hincrbyfloat(STRATEGY_KEY, "position", -1)
        r.hincrbyfloat(STRATEGY_KEY, "slope", -0.2)
        r.hincrbyfloat(STRATEGY_KEY, "wave", -0.3)
        r.hincrbyfloat(STRATEGY_KEY, "volatility", -0.2)
    else:
        # ❌ تقليل المخاطرة: جعل الشروط أكثر تحفظًا
        r.hincrbyfloat(STRATEGY_KEY, "position", 1)
        r.hincrbyfloat(STRATEGY_KEY, "slope", 0.2)
        r.hincrbyfloat(STRATEGY_KEY, "wave", 0.3)
        r.hincrbyfloat(STRATEGY_KEY, "volatility", 0.2)

    # حصر القيم ضمن حدود معقولة
    clamp("position", 10, 35)
    clamp("slope", -5, 5)
    clamp("wave", 1, 15)
    clamp("volatility", 1, 10)

# 🔒 تثبيت القيم بين حدين
def clamp(key, min_val, max_val):
    try:
        val = float(r.hget(STRATEGY_KEY, key))
        if val < min_val:
            r.hset(STRATEGY_KEY, key, min_val)
        elif val > max_val:
            r.hset(STRATEGY_KEY, key, max_val)
    except:
        pass

# 🥇 جلب العملات الأعلى ثقة
def get_top_confident(limit=5):
    raw = r.hgetall(CONFIDENCE_KEY)
    parsed = [(k.decode(), float(v)) for k, v in raw.items()]
    top = sorted(parsed, key=lambda x: x[1], reverse=True)
    return top[:limit]

# 🧹 تنظيف العملات ذات الثقة المنخفضة
def cleanup_confidence(threshold=0.5):
    raw = r.hgetall(CONFIDENCE_KEY)
    for k, v in raw.items():
        try:
            if float(v) <= threshold:
                r.hdel(CONFIDENCE_KEY, k)
        except:
            continue