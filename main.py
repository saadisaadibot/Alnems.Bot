import os
import json
import time
import redis
import threading
import requests
import statistics
from flask import Flask, request
from bitvavo_client.bitvavo import Bitvavo

app = Flask(__name__)
r = redis.from_url(os.getenv("REDIS_URL"))

# إعداد المفاتيح
key = os.getenv("BITVAVO_API_KEY")
secret = os.getenv("BITVAVO_API_SECRET")

if not key or not secret:
    print("❌ تأكد من وجود BITVAVO_API_KEY و BITVAVO_API_SECRET")
    exit()

BITVAVO = Bitvavo({
    'APIKEY': key,
    'APISECRET': secret,
    'RESTURL': 'https://api.bitvavo.com/v2',
    'WSURL': 'wss://ws.bitvavo.com/v2/'
})

# إعدادات عامة
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
BUY_AMOUNT = 10
WATCHLIST_KEY = "scalper:watchlist"

def send_message(text):
    try:
        requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", data={
            "chat_id": CHAT_ID,
            "text": text
        })
    except:
        pass

# ✅ السعر الحالي
def get_price(symbol):
    try:
        res = BITVAVO.tickerPrice(symbol)
        if isinstance(res, str):
            res = json.loads(res)
        return float(res['price'])
    except:
        return None

# ✅ شموع 1m (10 شموع)
def get_candles(symbol):
    try:
        res = BITVAVO.candles(symbol, {'interval': '1m', 'limit': 10})
        if isinstance(res, str):
            res = json.loads(res)
        return res
    except:
        return []

# ✅ حساب حدود بولينجر بناءً على 10 شموع
def compute_bollinger_bands(closes):
    sma = statistics.mean(closes)
    std_dev = statistics.stdev(closes)
    upper = sma + 2 * std_dev
    lower = sma - 2 * std_dev
    return sma, upper, lower

# ✅ التحليل والشراء
def analyze(symbol):
    try:
        candles = get_candles(symbol)
        if len(candles) < 6:
            return

        current_price = get_price(symbol)
        if not current_price:
            return

        # ✅ تحقق من 5 شمعات حمراء
        last_6 = candles[-6:]
        last_5_red = all(float(c[4]) < float(c[1]) for c in last_6[:-1])
        if not last_5_red:
            return

        # ✅ تحقق من الشمعة الأخيرة خضراء وقوية
        last = last_6[-1]
        open_, close = float(last[1]), float(last[4])
        if close <= open_:
            return
        if ((close - open_) / open_) * 100 < 0.3:
            return

        # ✅ تنفيذ الشراء
        base = symbol.split("-")[0]
        payload = {
            "market": symbol,
            "side": "buy",
            "orderType": "market",
            "amount": str(BUY_AMOUNT)
        }
        BITVAVO.placeOrder(payload)
        send_message(f"✅ اشترينا {base} 🚀 بعد 5 حمر + شمعة خضراء")

        # ✅ المراقبة للبيع
        threading.Thread(target=watch_sell, args=(symbol, current_price)).start()

    except Exception as e:
        print(f"❌ تحليل {symbol}:", e)

# ✅ مراقبة البيع
def watch_sell(symbol, buy_price):
    try:
        while True:
            time.sleep(0.5)
            current = get_price(symbol)
            if not current:
                continue

            change = (current - buy_price) / buy_price * 100

            if change >= 1:
                break  # ✅ الربح تحقق
            if change <= -0.5:
                break  # ❌ ستوب لوس

        base = symbol.split("-")[0]
        payload = {
            "market": symbol,
            "side": "sell",
            "orderType": "market",
            "amount": str(BUY_AMOUNT)
        }
        BITVAVO.placeOrder(payload)
        send_message(f"🚪 بيعنا {base} (النمس 🐆) - نسبة التغيير: {round(change, 2)}%")
    except Exception as e:
        print(f"❌ بيع {symbol}:", e)

# ✅ جلب Top 30 عملة حسب حجم التداول
# ✅ جلب Top 30 عملة تحتوي على 5 شمعات حمراء وتداول جيد
def get_top_30():
    try:
        print("🔍 فلترة العملات حسب 5 شمعات حمراء وتداول جيد...")
        tickers = BITVAVO.ticker24h({})
        if isinstance(tickers, str):
            tickers = json.loads(tickers)

        symbols = []
        for t in tickers:
            market = t.get("market", "")
            if not market.endswith("-EUR"):
                continue

            candles = get_candles(market)
            if len(candles) < 6:
                continue

            last_6 = candles[-6:]
            last_5_red = all(float(c[4]) < float(c[1]) for c in last_6[:-1])
            if not last_5_red:
                continue

            # حساب مجموع حجم التداول في آخر 5 شمعات
            volume_sum = sum(float(c[5]) for c in last_6[:-1])
            if volume_sum < 3000:
                continue

            symbols.append((market, volume_sum))

        # ترتيب حسب الحجم واختيار أفضل 30
        top = sorted(symbols, key=lambda x: x[1], reverse=True)[:30]
        selected = [s[0] for s in top]
        print("✅ العملات المختارة:", selected)
        return selected

    except Exception as e:
        print("🔴 خطأ في get_top_30:", e)
        return []

# ✅ حلقة التحديث والمراقبة
def run_bot():
    while True:
        try:
            print("🔁 تحديث قائمة المراقبة...")
            r.delete(WATCHLIST_KEY)
            top = get_top_30()
            for symbol in top:
                r.sadd(WATCHLIST_KEY, symbol)
            time.sleep(30)
        except Exception as e:
            print("❌ خطأ في تحديث القائمة:", e)

def monitor_loop():
    while True:
        try:
            for symbol in r.smembers(WATCHLIST_KEY):
                symbol = symbol.decode()
                threading.Thread(target=analyze, args=(symbol,)).start()
                time.sleep(3)
        except Exception as e:
            print("❌ خطأ في المراقبة:", e)

# ✅ أمر "شو عم تعمل"
@app.route('/webhook', methods=['POST'])
def webhook():
    msg = request.json.get("message", {}).get("text", "")
    if "شو عم تعمل" in msg:
        coins = r.smembers(WATCHLIST_KEY)
        msg = "🕵️ العملات تحت المراقبة:\n"
        msg += "\n".join([c.decode() for c in coins]) if coins else "لا شيء حالياً"
        send_message(msg)
    return "ok"

# ✅ تشغيل البوت
if __name__ == '__main__':
    threading.Thread(target=run_bot).start()
    threading.Thread(target=monitor_loop).start()
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))