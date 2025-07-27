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
IS_RUNNING_KEY = "nems:is_running"
TRADE_LOCK = "nems:in_trade"
PROFITS_KEY = "nems:profits"

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

    scored = []
    for t in tickers:
        symbol = t.get("market", "")
        if not symbol.endswith("-EUR"):
            continue
        candles = get_candles(symbol)
        if len(candles) < 5:
            continue
        red_count = count_red_candles(candles)
        try:
            volume = float(t.get("volume", 0) or 0)
        except:
            volume = 0
        change = abs(float(t.get("priceChangePercentage", 0)))
        score = red_count * 2 + volume * 0.001 + change * 1
        scored.append((symbol, score))

    scored = sorted(scored, key=lambda x: x[1], reverse=True)
    return scored[0][0] if scored else None

def place_market_buy(symbol):
    try:
        price = get_price(symbol)
        if not price:
            send_message(f"❌ لم نتمكن من جلب سعر {symbol}")
            return False

        amount = round(BUY_AMOUNT / price, 4)
        payload = {
            "market": symbol,
            "side": "buy",
            "orderType": "market",
            "amount": str(amount)
        }

        result = BITVAVO.placeOrder(payload)
        if isinstance(result, str):
            result = json.loads(result)
        send_message(f"📦 رد بيتفافو: {result}")

        if "orderId" in result:
            r.set(TRADE_LOCK, symbol, ex=600)
            r.hset("entry", symbol, price)
            r.hset("source", symbol, "nems")
            send_message(f"✅ اشترينا {symbol.split('-')[0]} مباشرة بعد {symbol} (النمس 🐆)")
            threading.Thread(target=watch_trade, args=(symbol, price)).start()
            return True
        else:
            send_message(f"❌ فشل في الشراء: {result}")
            return False

    except Exception as e:
        send_message(f"❌ استثناء في الشراء: {e}")
        return False

def watch_trade(symbol, entry_price):
    while True:
        time.sleep(0.5)
        current = get_price(symbol)
        if not current:
            continue
        change = (current - entry_price) / entry_price * 100
        if change >= 1.5 or change <= -0.5:
            break

    BITVAVO.placeOrder({
        "market": symbol,
        "side": "sell",
        "orderType": "market",
        "amount": str(BUY_AMOUNT / entry_price)
    })

    r.delete(TRADE_LOCK)
    profit_eur = (current - entry_price) * (BUY_AMOUNT / entry_price)
    percent = (current - entry_price) / entry_price * 100

    r.hset(PROFITS_KEY, symbol, json.dumps({
        "entry": entry_price,
        "exit": current,
        "profit": round(profit_eur, 3),
        "percent": round(percent, 2)
    }))

    send_message(f"🚪 بيعنا {symbol} - النسبة: {round(percent, 2)}%")

    # Start next cycle
    if r.get(IS_RUNNING_KEY) == b"on":
        threading.Thread(target=start_cycle).start()

def start_cycle():
    try:
        if r.get(TRADE_LOCK):
            send_message("⚠️ دورة ملغية: صفقة جارية.")
            return
        if r.get(IS_RUNNING_KEY) != b"on":
            send_message("⚠️ دورة ملغية: النمس متوقف.")
            return
        symbol = select_best_symbol()
        if symbol:
            send_message(f"🎯 تم اختيار {symbol} كأفضل عملة.")
            place_market_buy(symbol)
        else:
            send_message("🚫 لم يتم العثور على عملة مناسبة.")
    except Exception as e:
        send_message(f"❌ start_cycle error: {e}")

@app.route('/webhook', methods=['POST'])
def webhook():
    msg = request.json.get("message", {}).get("text", "")
    if not msg:
        return "ok"

    if "stop" in msg.lower():
        r.set(IS_RUNNING_KEY, "off")
        send_message("⛔ تم إيقاف النمس عن الشراء.")
    elif "play" in msg.lower():
        r.set(IS_RUNNING_KEY, "on")
        send_message("✅ النمس بدأ - نسخة الأرجوحة السريعة!")
        threading.Thread(target=start_cycle).start()
    elif "الملخص" in msg:
        data = r.hgetall(PROFITS_KEY)
        if not data:
            send_message("لا يوجد صفقات بعد.")
            return "ok"

        total = 0
        count = 0
        summary = "📊 ملخص الأرباح:\n"
        for k, v in data.items():
            k = k.decode()
            v = json.loads(v)
            profit = v["profit"]
            percent = v["percent"]
            total += profit
            count += 1
            summary += f"{k}: {round(profit, 2)} EUR ({percent}%)\n"
        summary += f"\n📈 الإجمالي: {round(total, 2)} EUR عبر {count} صفقة"
        send_message(summary)

    return "ok"

if __name__ == '__main__':
    r.set(IS_RUNNING_KEY, "off")  # يبدأ مطفي
    r.delete(TRADE_LOCK)
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))