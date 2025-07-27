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
IS_RUNNING_KEY = "scalper:running"
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
        url = f"https://api.bitvavo.com/v2/{symbol}/candles?interval=1m&limit=10"
        res = requests.get(url)
        if res.status_code != 200:
            return []
        return res.json()
    except:
        return []

def count_red_candles(candles):
    count = 0
    for c in reversed(candles):
        if float(c[4]) < float(c[1]):
            count += 1
    return count

def get_top_symbol():
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
            red_count = count_red_candles(candles)
            if red_count > 0:
                candidates.append((symbol, red_count))

        top = sorted(candidates, key=lambda x: x[1], reverse=True)
        if top:
            return top[0][0]
        return None
    except:
        return None

def buy(symbol):
    try:
        order = {
            "amount": str(BUY_AMOUNT),
            "market": symbol,
            "side": "buy",
            "orderType": "market",
            "operatorId": ""
        }
        result = BITVAVO._Bitvavo__request("POST", "/order", order)
        if "error" not in result:
            r.set(IS_IN_TRADE, symbol)
            send_message(f"✅ اشترينا {symbol.split('-')[0]} مباشرة بعد {symbol} (النمس 🐆)")
            threading.Thread(target=watch_sell, args=(symbol, get_price(symbol))).start()
        else:
            send_message(f"❌ فشل في الشراء: {result['error']['message']}")
    except Exception as e:
        send_message(f"❌ استثناء في الشراء: {e}")

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

        order = {
            "amount": str(BUY_AMOUNT),
            "market": symbol,
            "side": "sell",
            "orderType": "market",
            "operatorId": ""
        }
        result = BITVAVO._Bitvavo__request("POST", "/order", order)
        r.delete(IS_IN_TRADE)
        profit = round((get_price(symbol) - buy_price) * BUY_AMOUNT, 2)
        percent = round((get_price(symbol) - buy_price) / buy_price * 100, 2)
        send_message(f"🚪 بيعنا {symbol.split('-')[0]} - النسبة: {percent}% - الربح: €{profit}")
        r.rpush("scalper:profits", json.dumps({
            "symbol": symbol,
            "entry": buy_price,
            "exit": get_price(symbol),
            "profit": profit,
            "percent": percent
        }))
        # بعد البيع نبدأ دورة جديدة
        threading.Thread(target=main_loop).start()
    except Exception as e:
        r.delete(IS_IN_TRADE)
        send_message(f"❌ فشل في البيع: {e}")

def main_loop():
    if r.get(IS_RUNNING_KEY) != b"on":
        return
    if r.get(IS_IN_TRADE):
        return

    symbol = get_top_symbol()
    if symbol:
        buy(symbol)
    else:
        send_message("❌ لم يتم العثور على عملة مناسبة.")

@app.route('/webhook', methods=['POST'])
def webhook():
    msg = request.json.get("message", {}).get("text", "")
    if not msg:
        return "ok"

    if "stop" in msg:
        r.set(IS_RUNNING_KEY, "off")
        send_message("⛔️ تم إيقاف الشراء.")
    elif "play" in msg:
        r.set(IS_RUNNING_KEY, "on")
        send_message("✅ بدأ النمس - نسخة الأرجوحة السريعة!")
        threading.Thread(target=main_loop).start()
    elif "الملخص" in msg:
        profits = r.lrange("scalper:profits", 0, -1)
        if not profits:
            send_message("لا يوجد صفقات بعد.")
        else:
            total = 0
            text = "📊 ملخص الأرباح:\n"
            for p in profits:
                d = json.loads(p)
                total += d["profit"]
                text += f"{d['symbol']}: {round(d['percent'],2)}% | €{round(d['profit'],2)}\n"
            text += f"\n✅ الإجمالي: €{round(total, 2)}"
            send_message(text)
    return "ok"

if __name__ == '__main__':
    r.set(IS_RUNNING_KEY, "off")
    r.delete(IS_IN_TRADE)
    send_message("🐾 النمس بدأ - نسخة الأرجوحة السريعة!")
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))