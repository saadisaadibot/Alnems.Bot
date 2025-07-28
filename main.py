import time
import json
import os
import redis
import threading
import requests
from flask import Flask, request, jsonify
from market_scanner import pick_best_symbol
from bitvavo_client.bitvavo import Bitvavo

app = Flask(__name__)
r = redis.from_url(os.getenv("REDIS_URL"))

BITVAVO = Bitvavo({
    'APIKEY': os.getenv("BITVAVO_API_KEY"),
    'APISECRET': os.getenv("BITVAVO_API_SECRET"),
    'RESTURL': 'https://api.bitvavo.com/v2',
    'WSURL': 'wss://ws.bitvavo.com/v2'
})

BUY_AMOUNT_EUR = float(os.getenv("BUY_AMOUNT_EUR", 10))
IN_TRADE_KEY = "nems:in_trade"
IS_RUNNING_KEY = "scanner:enabled"
TRADES_KEY = "nems:trades"

CHAT_ID = os.getenv("CHAT_ID")
BOT_TOKEN = os.getenv("BOT_TOKEN")

def send_message(text):
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": CHAT_ID, "text": text})
    except Exception as e:
        print("فشل إرسال الرسالة:", e)

def fetch_price(symbol):
    try:
        price = BITVAVO.tickerPrice({"market": symbol})
        return float(price["price"])
    except:
        return None

def buy(symbol, entry_price):
    amount = round(BUY_AMOUNT_EUR / entry_price, 6)
    response = BITVAVO.placeOrder(symbol, {
        "side": "buy",
        "orderType": "market",
        "amount": str(amount)
    })
    return response, amount

def sell(symbol, amount):
    response = BITVAVO.placeOrder(symbol, {
        "side": "sell",
        "orderType": "market",
        "amount": str(amount)
    })
    return response

def watch(symbol, entry_price, reason):
    max_price = entry_price
    while True:
        price = fetch_price(symbol)
        if not price:
            time.sleep(1)
            continue

        max_price = max(max_price, price)
        change = (price - entry_price) / entry_price * 100

        if change >= 1.5:
            result = "ربح"
            percent = change
            break
        elif change <= -1:
            result = "خسارة"
            percent = change
            break

        time.sleep(1)

    balances = BITVAVO.balance(symbol.split("-")[0])
    amount = float(balances[0].get("available", 0))
    if amount > 0:
        sell(symbol, round(amount, 6))

    r.delete(IN_TRADE_KEY)

    # سجل الصفقة
    trade = {
        "symbol": symbol,
        "entry_price": entry_price,
        "exit_price": price,
        "result": result,
        "percent": round(percent, 2)
    }
    r.rpush(TRADES_KEY, json.dumps(trade))

def run_loop():
    r.set(IS_RUNNING_KEY, 1)
    while True:
        if r.get(IS_RUNNING_KEY) != b"1":
            print("⏸️ البوت موقوف مؤقتاً.")
            time.sleep(5)
            continue

        if r.get(IN_TRADE_KEY):
            time.sleep(3)
            continue

        symbol, reason, score = pick_best_symbol()
        if score < 1:
            print("❌ لا يوجد فرصة قوية حالياً.")
            time.sleep(30)
            continue

        print(f"✅ فرصة على {symbol} | {reason} | Score={score}")
        price = fetch_price(symbol)
        if not price:
            time.sleep(5)
            continue

        r.set(IN_TRADE_KEY, symbol)
        send_message(f"🚀 شراء {symbol} بسبب: {reason}")
        response, amount = buy(symbol, price)
        watch(symbol, price, reason)

@app.route("/", methods=["POST"])
def telegram_webhook():
    data = request.json
    if not data or "message" not in data:
        return jsonify({"status": "no message"}), 200

    text = data["message"].get("text", "").strip().lower()

    if text == "stop":
        r.set(IS_RUNNING_KEY, 0)
        send_message("⛔ تم إيقاف البوت مؤقتاً.")
    elif text == "play":
        r.set(IS_RUNNING_KEY, 1)
        send_message("✅ تم تشغيل البوت.")
    elif text == "شو عم تعمل":
        status = r.get(IS_RUNNING_KEY)
        reply = "🤖 البوت يعمل حالياً." if status == b"1" else "⏸️ البوت موقوف حالياً."
        send_message(reply)
    elif text == "الملخص":
        trades = r.lrange(TRADES_KEY, 0, -1)
        total = len(trades)
        win = 0
        loss = 0
        profit = 0.0

        for t in trades:
            data = json.loads(t)
            profit += data["percent"]
            if data["result"] == "ربح":
                win += 1
            else:
                loss += 1

        summary = f"""📊 ملخص التداول:
عدد الصفقات: {total}
✅ ربح: {win}
❌ خسارة: {loss}
📈 الربح الكلي: {round(profit, 2)}%
"""
        send_message(summary)

    return jsonify({"status": "ok"}), 200

if __name__ == "__main__":
    threading.Thread(target=run_loop).start()
    app.run(host="0.0.0.0", port=8000)