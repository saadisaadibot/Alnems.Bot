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
IS_RUNNING = "scalper:is_running"
TRADE_LOG = "scalper:profits"

# ✅ التفعيل المبدئي
r.set(IS_RUNNING, "1")

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

def count_red_candles_from_end(candles):
    count = 0
    for c in reversed(candles):
        if float(c[4]) < float(c[1]):
            count += 1
        else:
            break
    return count

def get_top_1():
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

        top = sorted(candidates, key=lambda x: x[1], reverse=True)
        return top[0][0] if top else None
    except:
        return None

def start_trade_cycle():
    if not r.get(IS_RUNNING):
        return
    if r.get(IS_IN_TRADE):
        return
    symbol = get_top_1()
    if not symbol:
        return

    try:
        BITVAVO.placeOrder({
            "market": symbol,
            "side": "buy",
            "orderType": "market",
            "amount": str(BUY_AMOUNT)
        })
        r.set(IS_IN_TRADE, symbol, ex=300)
        send_message(f"✅ اشترينا {symbol} (النمس 🐆)")
        threading.Thread(target=watch_sell, args=(symbol, get_price(symbol))).start()
    except Exception as e:
        print("❌ فشل في الشراء:", e)

def watch_sell(symbol, buy_price):
    try:
        while True:
            time.sleep(0.5)
            current = get_price(symbol)
            if not current:
                continue
            change = (current - buy_price) / buy_price * 100
            if change >= 1.5 or change <= -0.5:
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

        # تسجيل الصفقة
        log = {
            "symbol": symbol,
            "profit": round(change, 2),
            "ts": int(time.time())
        }
        r.rpush(TRADE_LOG, json.dumps(log))

        # البدء بدورة جديدة
        threading.Thread(target=delayed_start_trade).start()

    except Exception as e:
        print("❌ watch_sell:", e)
        r.delete(IS_IN_TRADE)

def delayed_start_trade():
    time.sleep(1)
    start_trade_cycle()

@app.route('/webhook', methods=['POST'])
def webhook():
    msg = request.json.get("message", {}).get("text", "").lower()
    if "stop" in msg:
        r.delete(IS_RUNNING)
        send_message("⛔ تم إيقاف الشراء.")
    elif "play" in msg:
        r.set(IS_RUNNING, "1")
        send_message("▶️ تم تفعيل الشراء.")
        threading.Thread(target=start_trade_cycle).start()
    elif "الملخص" in msg:
        trades = [json.loads(r.lindex(TRADE_LOG, i)) for i in range(r.llen(TRADE_LOG))]
        if not trades:
            send_message("لا توجد صفقات بعد.")
        else:
            total = sum(t['profit'] for t in trades)
            win = [t for t in trades if t['profit'] > 0]
            loss = [t for t in trades if t['profit'] <= 0]
            msg = f"""📊 ملخص Scalper:
الصفقات: {len(trades)}
✅ أرباح: {len(win)}
❌ خسائر: {len(loss)}
📈 الربح الصافي: {round(total, 2)}%"""
            send_message(msg)
    return "ok"

if __name__ == '__main__':
    send_message("🐾 النمس بدأ - نسخة الأرجوحة السريعة!")
    threading.Thread(target=start_trade_cycle).start()
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))