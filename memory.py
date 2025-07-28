import os
import redis

# الاتصال بقاعدة بيانات Redis
r = redis.from_url(os.getenv("REDIS_URL"))

# حفظ صفقة في الذاكرة
def save_trade(symbol, entry_price, exit_price, reason, result, percent):
    text = (
        f"{symbol} | دخول: {round(entry_price, 4)} | "
        f"خروج: {round(exit_price, 4)} | "
        f"{result} ({round(percent, 2)}%) | سبب: {reason}"
    )
    r.lpush("nems:trades", text)
    r.ltrim("nems:trades", 0, 49)  # يحتفظ بآخر 50 صفقة فقط