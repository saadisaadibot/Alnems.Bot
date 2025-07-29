import redis
import os

r = redis.from_url(os.getenv("REDIS_URL"))
RSI_KEY = "nems:rsi_level"
TRADE_LOG = "nems:trades"

def save_trade(symbol, entry_price, exit_price, reason, result, percent):
    entry = f"{symbol} {result} ({percent:.2f}%)"
    r.lpush(TRADE_LOG, entry)
    r.ltrim(TRADE_LOG, 0, 49)

    # تعديل مستوى RSI حسب النتيجة
    current_rsi = int(r.get(RSI_KEY) or 45)
    if result == "ربح ✅" and current_rsi < 70:
        r.set(RSI_KEY, current_rsi + 1)
    elif result == "خسارة ❌" and current_rsi > 20:
        r.set(RSI_KEY, current_rsi - 1)