import redis
import os
import time

r = redis.from_url(os.getenv("REDIS_URL"))

def save_trade(symbol, entry, exit, reason, result, percent):
    text = f"{symbol} | {reason} | {result} | {round(percent, 2)}%"
    r.lpush("nems:trades", text)
    r.ltrim("nems:trades", 0, 49)

def adjust_rsi(result):
    key = "nems:rsi_level"
    current = int(r.get(key) or 46)

    if result == "fail" and current > 30:
        r.set(key, current - 1)
    elif result == "success" and current < 60:
        r.set(key, current + 1)