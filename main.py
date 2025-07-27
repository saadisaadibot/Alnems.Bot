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

BITVAVO = Bitvavo({
    'APIKEY': os.getenv("BITVAVO_API_KEY"),
    'APISECRET': os.getenv("BITVAVO_API_SECRET"),
    'RESTURL': 'https://api.bitvavo.com/v2',
    'WSURL': 'wss://ws.bitvavo.com/v2/'
})

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
BUY_AMOUNT = 10
WATCHLIST_KEY = "scalper:watchlist"
IS_IN_TRADE = "scalper:in_trade"

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
        if not isinstance(res, list):
            print(f"🔴 شموع غير صالحة لـ {symbol}: {res}")
            return []
        return res
    except Exception as e:
        print(f"❌ فشل جلب الشموع لـ {symbol}:", e)
        return []

def count_red_candles_from_end(candles):
    count = 0
    for c in reversed(candles):
        if float(c[4]) < float(c[1]):
            count += 1
        else:
            break
    return count

def get_top_30():
    print("🔎 فلترة العملات حسب الشموع الحمراء المتتالية من النهاية...")
    try:
        tickers = BITVAVO.ticker24h({})
        if isinstance(tickers, str):
            tickers = json.loads(tickers)

        candidates = []
        for t in tickers:
            symbol = t.get("market", "")
            if not symbol.endswith("-EUR"):
                continue

            candles = get_candles(symbol)
            if len(candles) < 3:
                continue

            red_count = count_red_candles_from_end(candles)
            if red_count > 0:
                candidates.append((symbol, red_count))

        top = sorted(candidates, key=lambda x: x[1], reverse=True)[:30]
        selected = [s[0] for s in top]
        print("✅ العملات المختارة:", selected)
        return selected

    except Exception as e:
        print("❌ خطأ في get_top_30:", e)
        return []

def analyze(symbol):
    try:
        if r.get(IS_IN_TRADE):
            return

        candles = get_candles(symbol)
        if len(candles) < 6:
            return

        last = candles[-1]
        open_, close = float(last[1]), float(last[4])
        if close <= open_ or ((close - open_) / open_) * 100 < 0.3:
            return

        # تنفيذ شراء
        base = symbol.split("-")[0]
        payload = {
            "market": symbol,
            "side": "buy",
            "orderType": "market",
            "amount": str(BUY_AMOUNT)
        }
        BITVAVO.placeOrder(payload)
        r.set(IS_IN_TRADE, symbol, ex=300)
        send_message(f"✅ اشترينا {base} بعد {symbol} (النمس 🐆)")
        threading.Thread(target=watch_sell, args=(symbol, get_price(symbol))).start()

    except Exception as e:
        print(f"❌ analyze {symbol}:", e)

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

        BITVAVO.placeOrder({
            "market": symbol,
            "side": "sell",
            "orderType": "market",
            "amount": str(BUY_AMOUNT)
        })
        r.delete(IS_IN_TRADE)
        base = symbol.split("-")[0]
        send_message(f"🚪 بيعنا {base} - النسبة: {round(change, 2)}%")
    except Exception as e:
        print("❌ watch_sell:", e)
        r.delete(IS_IN_TRADE)

@app.route('/webhook', methods=['POST'])
def webhook():
    msg = request.json.get("message", {}).get("text", "")
    if "شو عم تعمل" in msg:
        coins = r.smembers(WATCHLIST_KEY)
        text = "🕵️ العملات تحت المراقبة:\n" + "\n".join(c.decode() for c in coins)
        send_message(text if coins else "لا يوجد حالياً")
    return "ok"

def update_watchlist():
    while True:
        try:
            r.delete(WATCHLIST_KEY)
            symbols = get_top_30()
            for s in symbols:
                r.sadd(WATCHLIST_KEY, s)
            time.sleep(300)
        except Exception as e:
            print("❌ update_watchlist:", e)

def monitor_loop():
    while True:
        try:
            for s in r.smembers(WATCHLIST_KEY):
                threading.Thread(target=analyze, args=(s.decode(),)).start()
                time.sleep(3)
        except Exception as e:
            print("❌ monitor_loop:", e)

if __name__ == '__main__':
    threading.Thread(target=update_watchlist).start()
    threading.Thread(target=monitor_loop).start()
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))