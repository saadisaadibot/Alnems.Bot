import os
import redis
import json

r = redis.from_url(os.getenv("REDIS_URL"))

TRADE_KEY = "nems:trades"
STATUS_KEY = "nems:is_in_trade"
CONFIDENCE_KEY = "nems:confidence"

# 🧠 تخزين الصفقة في الذاكرة
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

    # نعلم حسب نتيجة الصفقة
    success = percent >= 0
    update_confidence(symbol, success)

# 🔁 تعديل ثقة العملة بناءً على نتيجة الصفقة
def update_confidence(symbol, success):
    current = float(r.hget(CONFIDENCE_KEY, symbol) or 1.0)
    if success:
        new = current + 0.2
    else:
        new = max(0.5, current - 0.3)
    r.hset(CONFIDENCE_KEY, symbol, round(new, 2))

# 🔎 عرض أفضل العملات حسب الثقة
def get_top_confident(limit=10):
    all_conf = r.hgetall(CONFIDENCE_KEY)
    sorted_conf = sorted(
        [(k.decode(), float(v)) for k, v in all_conf.items()],
        key=lambda x: x[1],
        reverse=True
    )
    return sorted_conf[:limit]

# 🧹 ممكن نستخدم لاحقًا لتنظيف العملات المنسية
def cleanup_confidence(min_threshold=0.6):
    all_conf = r.hgetall(CONFIDENCE_KEY)
    for k, v in all_conf.items():
        if float(v) < min_threshold:
            r.hdel(CONFIDENCE_KEY, k)