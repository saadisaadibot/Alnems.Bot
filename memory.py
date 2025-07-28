import redis
import os
import json

r = redis.from_url(os.getenv("REDIS_URL"))

TRADE_KEY = "last_trade"
STATUS_KEY = "is_in_trade"
RSI_KEY = "nems:rsi_level"
HISTORY_KEY = "trade_history"

def save_trade(symbol, buy_price, sell_price, profit_pct):
    record = {
        "symbol": symbol,
        "buy_price": round(buy_price, 5),
        "sell_price": round(sell_price, 5),
        "profit_pct": round(profit_pct, 2),
    }
    # حفظ كـ JSON داخل Redis
    r.lpush(HISTORY_KEY, json.dumps(record))
    r.ltrim(HISTORY_KEY, 0, 9)  # الاحتفاظ بآخر 10 فقط

def get_last_trades():
    trades = r.lrange(HISTORY_KEY, 0, 9)
    return [json.loads(t.decode()) for t in trades]

def is_in_trade():
    return r.get(STATUS_KEY) == b"1"

def set_in_trade(symbol="unknown"):
    r.set(STATUS_KEY, "1")
    r.set(TRADE_KEY, symbol)

def clear_trade():
    r.set(STATUS_KEY, "0")
    r.delete(TRADE_KEY)

def adjust_rsi(profit_pct):
    try:
        current = int(r.get(RSI_KEY) or 46)
        if profit_pct < 0 and current < 70:
            r.set(RSI_KEY, current + 1)
        elif profit_pct >= 0 and current > 30:
            r.set(RSI_KEY, current - 1)
    except:
        pass