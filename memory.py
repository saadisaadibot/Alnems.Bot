import redis
import os
import json

r = redis.from_url(os.getenv("REDIS_URL"))

TRADE_KEY = "last_trade"
STATUS_KEY = "is_in_trade"
RSI_KEY = "nems:rsi_level"

def save_trade(symbol, price, side):
    trade = {
        "symbol": symbol,
        "price": price,
        "side": side
    }
    r.set(TRADE_KEY, json.dumps(trade))

def get_last_trade():
    data = r.get(TRADE_KEY)
    if not data:
        return None
    return json.loads(data)

def is_in_trade():
    return r.get(STATUS_KEY) == b"1"

def set_in_trade():
    r.set(STATUS_KEY, "1")

def clear_trade():
    r.set(STATUS_KEY, "0")

def adjust_rsi(outcome):
    try:
        current = int(r.get(RSI_KEY) or 46)
        if outcome == "win" and current < 70:
            r.set(RSI_KEY, current + 1)
        elif outcome == "loss" and current > 30:
            r.set(RSI_KEY, current - 1)
    except:
        pass