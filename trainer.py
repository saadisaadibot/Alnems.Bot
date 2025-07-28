import redis
import json
from collections import Counter

r = redis.from_url("YOUR_REDIS_URL")  # عدّل حسب مشروعك

TRADES_KEY = "nems:trades"
WEIGHTS_KEY = "nems:weights"

def analyze_trades():
    trades = r.lrange(TRADES_KEY, 0, -1)
    if not trades:
        print("❌ لا يوجد صفقات لتحليلها.")
        return

    good_signals = Counter()
    bad_signals = Counter()

    for t in trades:
        trade = json.loads(t)
        signals = trade["entry_reason"].split(" + ")
        result = trade["result"]

        for s in signals:
            if result == "ربح":
                good_signals[s] += 1
            else:
                bad_signals[s] += 1

    final_weights = {}
    all_signals = set(good_signals.keys()).union(bad_signals.keys())

    for s in all_signals:
        g = good_signals[s]
        b = bad_signals[s]
        total = g + b if g + b > 0 else 1
        final_weights[s] = round((g - b) / total, 2)

    r.set(WEIGHTS_KEY, json.dumps(final_weights, ensure_ascii=False))
    print("✅ تم تحديث الأوزان بناءً على نتائج الصفقات.")

if __name__ == "__main__":
    analyze_trades()
