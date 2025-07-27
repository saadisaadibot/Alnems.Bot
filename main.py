import os
import json
import time
import redis
import threading
import requests
from flask import Flask, request
from bitvavo_client.bitvavo import Bitvavo

app = Flask(__name__)
r = redis.from_url(os.getenv("REDIS_URL"))

# ✅ جلب المفاتيح من environment وتحقق منها
key = os.getenv("BITVAVO_API_KEY")
secret = os.getenv("BITVAVO_API_SECRET")

if not key or not secret:
    print("❌ تأكد من وجود BITVAVO_API_KEY و BITVAVO_API_SECRET في إعدادات Railway")
    exit()

# ✅ إنشاء الكائن
BITVAVO = Bitvavo({
    'APIKEY': key,
    'APISECRET': secret,
    'RESTURL': 'https://api.bitvavo.com/v2',
    'WSURL': 'wss://ws.bitvavo.com/v2/'
})

# إعدادات عامة
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
BUY_AMOUNT = 10  # باليورو
WATCHLIST_KEY = "scalper:watchlist"

# ✅ إرسال رسالة تيليغرام
def send_message(text):
    try:
        requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", data={
            "chat_id": CHAT_ID,
            "text": text
        })
    except:
        pass

# ✅ جلب Top 30 من Bitvavo
def get_top_30():
    try:
        tickers = BITVAVO.ticker24h({})
        if isinstance(tickers, str):
            tickers = json.loads(tickers)
        top = sorted(
            [t for t in tickers if t["market"].endswith("-EUR")],
            key=lambda x: float(x["priceChangePercentage"]),
            reverse=True
        )
        return [t["market"] for t in top[:30]]
    except Exception as e:
        print("🔴 خطأ جلب العملات:", e)
        return []

# ✅ السعر الحالي
def get_price(symbol):
    try:
        res = BITVAVO.tickerPrice(symbol)
        if isinstance(res, str):
            res = json.loads(res)
        return float(res['price'])
    except:
        return None

# ✅ شموع 1m
def get_candles(symbol):
    try:
        res = BITVAVO.candles(symbol, {'interval': '1m', 'limit': 3})
        if isinstance(res, str):
            res = json.loads(res)
        return res
    except:
        return []

# ✅ التحليل والشراء
def analyze(symbol):
    try:
        candles = get_candles(symbol)
        if len(candles) < 3:
            return

        latest = candles[-1]
        open_, high, low, close = map(float, latest[1:5])

        current_price = get_price(symbol)
        if not current_price:
            return

        lower = min(float(c[3]) for c in candles)
        if current_price > lower * 1.02:
            return

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
        send_message(f"✅ اشترينا {base} 🧠 (النمس)")

        # ✅ تابع للمراقبة
        threading.Thread(target=watch_sell, args=(symbol, current_price)).start()

    except Exception as e:
        print(f"❌ تحليل {symbol}:", e)

# ✅ متابعة البيع
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
        send_message(f"🚪 بيعنا {base} 🔁 (النمس)")
    except Exception as e:
        print(f"❌ بيع {symbol}:", e)

# ✅ حلقة النمس
def run_bot():
    while True:
        try:
            r.delete(WATCHLIST_KEY)
            top = get_top_30()
            for symbol in top:
                r.sadd(WATCHLIST_KEY, symbol)
            time.sleep(30)

            for symbol in r.smembers(WATCHLIST_KEY):
                symbol = symbol.decode()
                threading.Thread(target=analyze, args=(symbol,)).start()
                time.sleep(3)
        except Exception as e:
            print("🔴 حلقة النمس:", e)

# ✅ أمر "شو عم تعمل"
@app.route('/', methods=['POST'])
def webhook():
    msg = request.json.get("message", {}).get("text", "")
    if "شو عم تعمل" in msg:
        coins = r.smembers(WATCHLIST_KEY)
        msg = "🕵️ العملات تحت المراقبة:\n"
        msg += "\n".join([c.decode() for c in coins]) if coins else "لا شيء حالياً"
        send_message(msg)
    return "ok"

# ✅ تشغيل السيرفر
if __name__ == '__main__':
    threading.Thread(target=run_bot).start()
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))