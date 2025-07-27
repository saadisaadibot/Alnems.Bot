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

def place_market_buy(symbol):
    try:
        price = get_price(symbol)
        if not price:
            send_message(f"❌ لم نتمكن من جلب سعر {symbol}")
            return

        amount = round(BUY_AMOUNT / price, 4)
        payload = {
            "market": symbol,
            "side": "buy",
            "orderType": "market",
            "amount": str(amount)
        }
        result = BITVAVO.placeOrder(payload)
        if "orderId" in result:
            r.set(TRADE_LOCK, symbol, ex=600)
            r.hset("entry", symbol, price)
            r.hset("source", symbol, "manual")
            send_message(f"✅ تم شراء {symbol} بنجاح.")
            threading.Thread(target=watch_trade, args=(symbol, price)).start()
        else:
            send_message(f"❌ فشل في الشراء: {result}")
    except Exception as e:
        send_message(f"❌ استثناء في الشراء: {e}")

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

@app.route('/webhook', methods=['POST'])
def webhook():
    msg = request.json.get("message", {}).get("text", "")
    if not msg:
        return "ok"

    msg = msg.strip().upper()
    if msg.startswith("اشتر") or msg.startswith("اشتري"):
        try:
            parts = msg.split()
            coin = parts[1].upper()
            if not coin.endswith("-EUR"):
                symbol = f"{coin}-EUR"
            else:
                symbol = coin
            if r.get(TRADE_LOCK):
                send_message("⚠️ هناك صفقة حالياً قيد التنفيذ، الرجاء الانتظار.")
            else:
                place_market_buy(symbol)
        except:
            send_message("❌ صيغة الأمر غير صحيحة. أرسل: اشتري ADA يا نمس")

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
    r.delete(TRADE_LOCK)
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))