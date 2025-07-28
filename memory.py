import json
import time
import redis
from datetime import datetime

r = redis.from_url("YOUR_REDIS_URL")  # عدلها حسب مشروعك

def save_trade(symbol, entry_price, exit_price, entry_reason, result, percent, source="تلقائي"):
    trade_data = {
        "symbol": symbol,
        "entry_time": datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S'),
        "exit_time": datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S'),
        "entry_price": entry_price,
        "exit_price": exit_price,
        "entry_reason": entry_reason,
        "result": result,
        "percent": round(percent, 2),
        "source": source
    }

    # نخزن الصفقة في Redis ضمن قائمة
    trades_key = "nems:trades"
    r.rpush(trades_key, json.dumps(trade_data))