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
BOUGHT_KEY = "scalper:bought"
IN_TRADE_KEY = "scalper:in_trade"

def send_message(text):
    try:
        requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", data={
            "chat_id": CHAT_ID,
            "text": text
        })
    except:
        pass

def get_price(symbol):
    try:
        res = BITVAVO.tickerPrice(symbol)
        if isinstance(res, str):
            res = json.loads(res)
        return float(res['price'])
    except:
        return None

def get_candles(symbol):
    try:
        res = BITVAVO.candles(symbol, {'interval': '1m', 'limit': 10})
        if isinstance(res, str):
            res = json.loads(res)
        return res
    except:
        return []

def analyze(symbol):
    try:
        # لا تدخل إذا في صفقة مفتوحة
        if r.get(IN_TRADE_KEY) == b"1":
            return
        if r.sismember(BOUGHT_KEY, symbol):
            return

        candles = get_candles(symbol)
        if len(candles) < 6:
            return

        current_price = get_price(symbol)
        if not current_price:
            return

        last_6 = candles[-6:]
        reds = [c for c in last_6[:-1] if float(c[4]) < float(c[1])]
        if len(reds) < 4:
            return

        last = last_6[-1]
        open_, close = float(last[1]), float(last[4])
        if close <= open_:
            return
        if ((close - open_) / open_) * 100 < 0.3:
            return

        base = symbol.split("-")[0]
        payload = {
            "market": symbol,
            "side": "buy",
            "orderType": "market",
            "amount": str(BUY_AMOUNT)
        }
        BITVAVO.placeOrder(payload)
        send_message(f"✅ اشترينا {base} 🚀 بعد {len(reds)} شمعات حمراء + خضراء")

        r.sadd(BOUGHT_KEY, symbol)
        r.set(IN_TRADE_KEY, "1")

        threading.Thread(target=watch_sell, args=(symbol, current_price)).start()

    except Exception as e:
        print(f"❌ تحليل {symbol}:", e)

def watch_sell(symbol, buy_price):
    try:
        while True:
            time.sleep(0.5)
            current = get_price(symbol)
            if not current:
                continue

            change = (current - buy_price) / buy_price * 100
            if change >= 1 or change <= -0.5:
                break

        base = symbol.split("-")[0]
        payload = {
            "market": symbol,
            "side": "sell",
            "orderType": "market",
            "amount": str(BUY_AMOUNT)
        }
        BITVAVO.placeOrder(payload)
        send_message(f"🚪 بيعنا {base} (النمس 🐆) - نسبة التغيير: {round(change, 2)}%")

        r.srem(BOUGHT_KEY, symbol)
        r.set(IN_TRADE_KEY, "0")

    except Exception as e:
        print(f"❌ بيع {symbol}:", e)

# ✅ جلب Top 30 عملة تحتوي على أكبر عدد شمعات حمراء + خضراء
# ✅ جلب Top 30 عملة تحتوي على أكبر عدد شمعات حمراء
def get_top_30():
    try:
        print("🔍 فلترة العملات حسب عدد الشموع الحمراء المتتالية من النهاية...")
        tickers = BITVAVO.ticker24h({})
        if isinstance(tickers, str):
            tickers = json.loads(tickers)

        ranked = []
        for t in tickers:
            market = t.get("market", "")
            if not market.endswith("-EUR"):
                continue

            candles = get_candles(market)
            if len(candles) < 3:
                continue

            # نحسب عدد الشموع الحمراء من النهاية للخلف
            red_count = 0
            for c in reversed(candles):
                open_, close = float(c[1]), float(c[4])
                if close < open_:
                    red_count += 1
                else:
                    break  # توقف عند أول شمعة غير حمراء

            if red_count > 0:
                ranked.append((market, red_count))

        # ترتيب تنازلي حسب عدد الشموع الحمراء
        top = sorted(ranked, key=lambda x: x[1], reverse=True)[:30]
        selected = [s[0] for s in top]
        print("✅ العملات المختارة:", selected)
        return selected

    except Exception as e:
        print("🔴 خطأ في get_top_30:", e)
        return []

def run_bot():
    while True:
        try:
            print("🔁 تحديث قائمة المراقبة...")
            r.delete(WATCHLIST_KEY)
            top = get_top_30()
            for symbol in top:
                r.sadd(WATCHLIST_KEY, symbol)
            time.sleep(300)  # كل 5 دقائق
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

@app.route('/webhook', methods=['POST'])
def webhook():
    msg = request.json.get("message", {}).get("text", "")
    if "شو عم تعمل" in msg:
        coins = r.smembers(WATCHLIST_KEY)
        msg = "🕵️ العملات تحت المراقبة:\n"
        msg += "\n".join([c.decode() for c in coins]) if coins else "لا شيء حالياً"
        send_message(msg)
    return "ok"

if __name__ == '__main__':
    threading.Thread(target=run_bot).start()
    threading.Thread(target=monitor_loop).start()
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))