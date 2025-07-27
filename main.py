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
        if len(candles) < 10:
            return

        closes = [float(c[4]) for c in candles]
        sma, upper, lower = compute_bollinger_bands(closes)

        current_price = get_price(symbol)
        if not current_price:
            return

        # شرط القرب من الحد السفلي
        if current_price > lower * 1.02:
            return

        # تحقق من الشمعة الأخيرة صاعدة
        latest = candles[-1]
        open_, close = float(latest[1]), float(latest[4])
        if close <= open_:
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
        send_message(f"✅ اشترينا {base} (النمس 🐆)")

        # ✅ راقب للبيع
        threading.Thread(target=watch_sell, args=(symbol, current_price)).start()

    except Exception as e:
        print(f"❌ تحليل {symbol}:", e)

# ✅ مراقبة البيع
def watch_sell(symbol, buy_price):
    try:
        peak = buy_price
        while True:
            time.sleep(0.5)
            current = get_price(symbol)
            if not current:
                continue

            change = (current - buy_price) / buy_price * 100
            peak = max(peak, current)
            retrace = (current - peak) / peak * 100

            if change <= -2:
                break
            if peak > buy_price * 1.03 and retrace <= -1:
                break

        base = symbol.split("-")[0]
        payload = {
            "market": symbol,
            "side": "sell",
            "orderType": "market",
            "amount": str(BUY_AMOUNT)
        }
        BITVAVO.placeOrder(payload)
        send_message(f"🚪 بيعنا {base} (النمس 🐆)")
    except Exception as e:
        print(f"❌ بيع {symbol}:", e)

# ✅ جلب Top 30 عملة حسب حجم التداول
def get_top_30():
    try:
        tickers = BITVAVO.ticker24h({})
        if isinstance(tickers, str):
            tickers = json.loads(tickers)

        filtered = []
        for t in tickers:
            if t.get("market", "").endswith("-EUR") and "volume" in t:
                filtered.append(t)

        top = sorted(filtered, key=lambda x: float(x["volume"]), reverse=True)
        return [t["market"] for t in top[:30]]

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