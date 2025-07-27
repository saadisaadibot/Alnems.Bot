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
IS_IN_TRADE = "scalper:in_trade"
BUY_ENABLED = "scalper:enabled"
r.set(BUY_ENABLED, "true")

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
        url = f"https://api.bitvavo.com/v2/{symbol}/candles?interval=1m&limit=10"
        res = requests.get(url)
        if res.status_code != 200:
            return []
        return res.json()
    except:
        return []

def count_red_candles(candles):
    return sum(1 for c in candles if float(c[4]) < float(c[1]))

def select_best_symbol():
    tickers = BITVAVO.ticker24h({})
    if isinstance(tickers, str):
        tickers = json.loads(tickers)

    scores = []
    for t in tickers:
        symbol = t.get("market", "")
        if not symbol.endswith("-EUR"):
            continue
        candles = get_candles(symbol)
        if len(candles) < 5:
            continue
        red_count = count_red_candles(candles)
        total_drop = ((float(candles[0][1]) - float(candles[-1][4])) / float(candles[0][1])) * 100
        volume = float(t.get("volume", 0))
        score = red_count * 10 + total_drop + volume
        scores.append((symbol, score))

    top = sorted(scores, key=lambda x: x[1], reverse=True)
    return top[0][0] if top else None

def buy(symbol):
    try:
        if not r.get(BUY_ENABLED) or r.get(IS_IN_TRADE):
            return
        price = get_price(symbol)
        if not price:
            return

        order = {
            "market": symbol,
            "side": "buy",
            "orderType": "market",
            "amount": str(BUY_AMOUNT),
            "operatorId": ""
        }
        result = BITVAVO.placeOrder(order)
        if "error" in result:
            send_message(f"❌ فشل الشراء: {result['error']['message']}")
            return

        r.set(IS_IN_TRADE, symbol)
        r.set("entry_price", price)
        r.set("entry_symbol", symbol)
        send_message(f"✅ اشترينا {symbol.split('-')[0]} مباشرة بعد {symbol} (النمس 🐆)")
        threading.Thread(target=watch_sell, args=(symbol, price)).start()
    except Exception as e:
        send_message(f"❌ استثناء في الشراء: {e}")

def watch_sell(symbol, entry_price):
    try:
        while True:
            time.sleep(0.5)
            current = get_price(symbol)
            if not current:
                continue
            change = (current - entry_price) / entry_price * 100
            if change >= 1.5 or change <= -0.5:
                break

        order = {
            "market": symbol,
            "side": "sell",
            "orderType": "market",
            "amount": str(BUY_AMOUNT),
            "operatorId": ""
        }
        result = BITVAVO.placeOrder(order)
        r.delete(IS_IN_TRADE)
        if "error" not in result:
            send_message(f"✅ بيع {symbol} بنسبة {round(change, 2)}%")
            store_profit(symbol, entry_price, current, change)
        else:
            send_message(f"❌ فشل البيع: {result['error']['message']}")
    except Exception as e:
        send_message(f"❌ استثناء في البيع: {e}")
        r.delete(IS_IN_TRADE)
    finally:
        start_cycle()

def store_profit(symbol, entry, exit, percent):
    profits = {
        "entry": entry,
        "exit": exit,
        "percent": percent
    }
    r.rpush("scalper:profits", json.dumps(profits))

@app.route("/webhook", methods=["POST"])
def webhook():
    msg = request.json.get("message", {}).get("text", "")
    if "stop" in msg:
        r.set(BUY_ENABLED, "false")
        send_message("🛑 تم إيقاف الشراء.")
    elif "play" in msg:
        r.set(BUY_ENABLED, "true")
        send_message("▶️ تم تفعيل الشراء.")
        start_cycle()
    elif "الملخص" in msg:
        entries = r.lrange("scalper:profits", 0, -1)
        if not entries:
            send_message("لا توجد صفقات.")
        else:
            summary = "📊 ملخص الصفقات:\n"
            total = 0
            for e in entries:
                d = json.loads(e)
                summary += f"ربح: {round(d['percent'],2)}%\n"
                total += d['percent']
            summary += f"\n📈 الربح الكلي: {round(total, 2)}%"
            send_message(summary)
    return "ok"

def start_cycle():
    if not r.get(BUY_ENABLED):
        return
    symbol = select_best_symbol()
    if symbol:
        buy(symbol)

if __name__ == "__main__":
    send_message("🐾 النمس بدأ - نسخة الأرجوحة السريعة!")
    threading.Thread(target=start_cycle).start()
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))