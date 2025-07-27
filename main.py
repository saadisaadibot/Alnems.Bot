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
IN_TRADE_KEY = "scalp:in_trade"
STOP_KEY = "scalp:stop"
WATCHLIST_KEY = "scalp:watchlist"
PROFITS_KEY = "scalp:profits"

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
        url = f"https://api.bitvavo.com/v2/{symbol}/candles?interval=1m&limit=6"
        res = requests.get(url)
        if res.status_code != 200:
            return []
        return res.json()
    except:
        return []

def score_symbol(symbol):
    candles = get_candles(symbol)
    if len(candles) < 5:
        return None

    red_count = 0
    drop = 0
    volume = 0
    for c in candles[:-1]:
        open_, close = float(c[1]), float(c[4])
        if close < open_:
            red_count += 1
        drop += open_ - close
        volume += float(c[5])

    if red_count == 0:
        return None

    score = red_count * 2 + drop * 10 + volume * 0.001
    return score

def pick_top1():
    tickers = BITVAVO.ticker24h({})
    if isinstance(tickers, str):
        tickers = json.loads(tickers)

    best = None
    best_score = -1

    for t in tickers:
        symbol = t.get("market", "")
        if not symbol.endswith("-EUR"):
            continue

        score = score_symbol(symbol)
        if score and score > best_score:
            best = symbol
            best_score = score

    return best

def trade_cycle():
    if r.exists(STOP_KEY):
        return

    if r.exists(IN_TRADE_KEY):
        return

    symbol = pick_top1()
    if not symbol:
        return

    try:
        payload = {
            "market": symbol,
            "side": "buy",
            "orderType": "market",
            "amount": str(BUY_AMOUNT)
        }
        BITVAVO.placeOrder(payload)
        r.set(IN_TRADE_KEY, symbol)
        base = symbol.split("-")[0]
        send_message(f"✅ اشترينا {base} مباشرة بعد {symbol} (النمس 🐆)")
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

        r.delete(IN_TRADE_KEY)
        base = symbol.split("-")[0]
        send_message(f"🚪 بيعنا {base} - النسبة: {round(change, 2)}%")

        # سجل الربح
        log_profit(base, change)

        # دورة جديدة
        time.sleep(1)
        trade_cycle()

    except Exception as e:
        print("❌ watch_sell:", e)
        r.delete(IN_TRADE_KEY)

def log_profit(coin, percent):
    try:
        profits = json.loads(r.get(PROFITS_KEY) or "{}")
        profits[str(time.time())] = {"coin": coin, "percent": round(percent, 2)}
        r.set(PROFITS_KEY, json.dumps(profits))
    except:
        pass

@app.route('/webhook', methods=['POST'])
def webhook():
    msg = request.json.get("message", {}).get("text", "").lower()
    if "stop" in msg:
        r.set(STOP_KEY, "1")
        send_message("⛔️ تم إيقاف الشراء.")
    elif "play" in msg:
        r.delete(STOP_KEY)
        send_message("✅ تم استئناف الشراء.")
        trade_cycle()
    elif "الملخص" in msg:
        profits = json.loads(r.get(PROFITS_KEY) or "{}")
        if not profits:
            send_message("لا يوجد صفقات بعد.")
        else:
            total = 0
            msg = "📊 ملخص الصفقات:\n"
            for p in profits.values():
                coin = p['coin']
                percent = p['percent']
                total += percent
                msg += f"{coin}: {percent}%\n"
            msg += f"\n📈 إجمالي الربح: {round(total, 2)}%"
            send_message(msg)
    elif "شو عم تعمل" in msg:
        s = r.get(IN_TRADE_KEY)
        if s:
            send_message(f"📍 حالياً داخل صفقة: {s.decode()}")
        else:
            send_message("⏳ لا يوجد صفقة حالياً.")
    return "ok"

def loop_forever():
    while True:
        try:
            if not r.exists(IN_TRADE_KEY) and not r.exists(STOP_KEY):
                trade_cycle()
            time.sleep(5)
        except Exception as e:
            print("❌ main loop error:", e)

if __name__ == '__main__':
    send_message("🐾 النمس بدأ - نسخة الأرجوحة السريعة!")
    threading.Thread(target=loop_forever).start()
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))