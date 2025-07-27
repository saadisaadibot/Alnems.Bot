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

# ✅ شموع 1m
def get_candles(symbol, limit=10):
    try:
        res = BITVAVO.candles(symbol, {'interval': '1m', 'limit': limit})
        if isinstance(res, str):
            res = json.loads(res)
        return res
    except:
        return []

# ✅ تحليل ومراقبة الشراء
def analyze(symbol):
    try:
        candles = get_candles(symbol, 6)
        if len(candles) < 6:
            return

        last_6 = candles[-6:]
        reds = [float(c[4]) < float(c[1]) for c in last_6]
        green = float(last_6[-1][4]) > float(last_6[-1][1])

        if sum(reds[:-1]) >= 5 and green:
            open_, close = float(last_6[-1][1]), float(last_6[-1][4])
            if ((close - open_) / open_) * 100 < 0.3:
                return

            # ✅ تنفيذ الشراء
            base = symbol.split("-")[0]
            buy_price = get_price(symbol)
            payload = {
                "market": symbol,
                "side": "buy",
                "orderType": "market",
                "amount": str(BUY_AMOUNT)
            }
            BITVAVO.placeOrder(payload)
            send_message(f"✅ اشترينا {base} 🚀 بعد {sum(reds[:-1])} شمعات حمراء + خضراء")

            threading.Thread(target=watch_sell, args=(symbol, buy_price)).start()

    except Exception as e:
        print(f"❌ analyze {symbol}:", e)

# ✅ مراقبة البيع
def watch_sell(symbol, buy_price):
    try:
        while True:
            time.sleep(0.5)
            current = get_price(symbol)
            if not current:
                continue

            change = (current - buy_price) / buy_price * 100
            if change >= 1 or change <= -0.5:
                base = symbol.split("-")[0]
                payload = {
                    "market": symbol,
                    "side": "sell",
                    "orderType": "market",
                    "amount": str(BUY_AMOUNT)
                }
                BITVAVO.placeOrder(payload)
                send_message(f"🚪 بيعنا {base} (النمس 🐆) - تغيير: {round(change, 2)}%")
                break
    except Exception as e:
        print(f"❌ sell {symbol}:", e)

# ✅ جلب العملات التي تحقق شرط 5 حمر + خضراء
def get_top_30_red_green():
    try:
        print("🔍 فحص الشموع...")
        tickers = BITVAVO.ticker24h({})
        if isinstance(tickers, str):
            tickers = json.loads(tickers)

        candidates = []
        for t in tickers:
            symbol = t.get("market", "")
            if not symbol.endswith("-EUR"):
                continue

            candles = get_candles(symbol, 10)
            if len(candles) < 6:
                continue

            last_6 = candles[-6:]
            reds = [float(c[4]) < float(c[1]) for c in last_6]
            green = float(last_6[-1][4]) > float(last_6[-1][1])

            if sum(reds[:-1]) >= 5 and green:
                candidates.append((symbol, sum(reds[:-1])))

        sorted_top = sorted(candidates, key=lambda x: x[1], reverse=True)[:30]
        final = [s[0] for s in sorted_top]
        print("✅ العملات المختارة:", final)
        return final
    except Exception as e:
        print("🔴 خطأ في get_top_30_red_green:", e)
        return []

# ✅ حلقة التحديث كل 5 دقائق
def update_watchlist():
    while True:
        try:
            print("🔁 تحديث قائمة المراقبة...")
            r.delete(WATCHLIST_KEY)
            symbols = get_top_30_red_green()
            for s in symbols:
                r.sadd(WATCHLIST_KEY, s)
            time.sleep(300)  # كل 5 دقائق
        except Exception as e:
            print("❌ تحديث القائمة:", e)

# ✅ المراقبة اللحظية
def monitor_loop():
    while True:
        try:
            for symbol in r.smembers(WATCHLIST_KEY):
                symbol = symbol.decode()
                threading.Thread(target=analyze, args=(symbol,)).start()
                time.sleep(3)
        except Exception as e:
            print("❌ المراقبة:", e)

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
    threading.Thread(target=update_watchlist).start()
    threading.Thread(target=monitor_loop).start()
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))