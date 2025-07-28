import redis
import os
import json

r = redis.from_url(os.getenv("REDIS_URL"))
TRADE_KEY = "bot:current_trade"
RSI_KEY = "nems:rsi_level"

def is_in_trade():
    return r.exists(TRADE_KEY)

def set_in_trade(symbol, price, amount):
    data = {"symbol": symbol, "price": price, "amount": amount}
    r.set(TRADE_KEY, json.dumps(data))

def get_trade():
    try:
        return json.loads(r.get(TRADE_KEY))
    except:
        return None

def clear_trade():
    r.delete(TRADE_KEY)

def adjust_rsi(result):
    level = int(r.get(RSI_KEY) or 46)
    if result == "ربح ✅":
        level = max(level - 1, 30)
    else:
        level = min(level + 1, 70)
    r.set(RSI_KEY, level)