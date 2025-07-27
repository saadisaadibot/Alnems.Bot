import os
import json
import time
import redis
import threading
import requests
from flask import Flask, request
from statistics import mean
from bitvavo_client.bitvavo import Bitvavo

app = Flask(__name__)
r = redis.from_url(os.getenv("REDIS_URL"))

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

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
BUY_AMOUNT = 10
WATCHLIST_KEY = "scalper:watchlist"

def send_message(text):
    try:
        requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", data={
            "chat_id": CHAT_ID, "text": text
        })
    except: pass

def get_price(symbol):
    try:
        res = BITVAVO.tickerPrice(symbol)
        if isinstance(res, str): res = json.loads(res)
        return float(res['price'])
    except: return None

def get_candles(symbol):
    try:
        res = BITVAVO.candles(symbol, {'interval': '1m', 'limit': 10})
        if isinstance(res, str): res = json.loads(res)
        return res
    except: return []

# ✅ تحقق من شروط الشراء
def is_valid_entry(candles):
    if len(candles) < 6: return False
    reds = 0
    for c in candles[:-1]:
        if float(c[4]) < float(c[1]): reds += 1
        else: break

    if reds < 5: return False  # نحتاج على الأقل 5 حمر
    last = candles[-1]
    open_, close = float(last[1]), float(last[4])
    if close <= open_: return False
    if ((close - open_) / open_) * 100 < 0.3: return False
    return True

# ✅ تنفيذ شراء ومتابعة البيع
def buy_and_watch(symbol):
    try:
        current_price = get_price(symbol)
        if not current_price: return

        base = symbol.split("-")[0]
        payload = {
            "market": symbol,
            "side": "buy",
            "orderType": "market",
            "amount": str(BUY_AMOUNT)
        }
        BITVAVO.placeOrder(payload)
        send_message(f"✅ اشترينا {base} 🚀 (النمس - الأرجوحة السريعة™️)")

        # ✅ المراقبة للبيع
        threading.Thread(target=watch_sell, args=(symbol, current_price)).start()

    except Exception as e:
        print(f"❌ شراء {symbol}:", e)

def watch_sell(symbol, buy_price):
    try:
        while True:
            time.sleep(0.5)
            current = get_price(symbol)
            if not current: continue

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
        send_message(f"🚪 بيعنا {base} - التغيير: {round(change,2)}%")
    except Exception as e:
        print(f"❌ بيع {symbol}:", e)

# ✅ جلب العملات المرشحة حسب 5 شمعات حمراء
def get_candidates():
    try:
        print("🔍 البحث عن عملات 5 حمر + خضراء...")
        tickers = BITVAVO.ticker24h({})
        if isinstance(tickers, str): tickers = json.loads(tickers)

        result = []
        for t in tickers:
            market = t.get("market", "")
            if not market.endswith("-EUR"): continue

            candles = get_candles(market)
            if is_valid_entry(candles):
                result.append(market)

        selected = result[:30]
        print("✅ العملات المختارة:", selected)
        return selected
    except Exception as e:
        print("❌ خطأ في get_candidates:", e)
        return []

# ✅ تحديث قائمة المراقبة كل دقيقتين
def update_watchlist():
    while True:
        try:
            r.delete(WATCHLIST_KEY)
            top = get_candidates()
            for symbol in top:
                r.sadd(WATCHLIST_KEY, symbol)
            time.sleep(120)
        except Exception as e:
            print("❌ خطأ في تحديث القائمة:", e)

# ✅ مراقبة العملات كل 3 ثواني
def monitor_loop():
    while True:
        try:
            for symbol in r.smembers(WATCHLIST_KEY):
                symbol = symbol.decode()
                candles = get_candles(symbol)
                if is_valid_entry(candles):
                    buy_and_watch(symbol)
                time.sleep(3)
        except Exception as e:
            print("❌ خطأ في المراقبة:", e)

@app.route("/webhook", methods=["POST"])
def webhook():
    msg = request.json.get("message", {}).get("text", "")
    if "شو عم تعمل" in msg:
        coins = r.smembers(WATCHLIST_KEY)
        msg = "📊 العملات تحت المراقبة:\n"
        msg += "\n".join([c.decode() for c in coins]) if coins else "لا شيء حالياً"
        send_message(msg)
    return "ok"

if __name__ == '__main__':
    threading.Thread(target=update_watchlist).start()
    threading.Thread(target=monitor_loop).start()
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))