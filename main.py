import os
import time
import threading
import redis
import requests
from flask import Flask, request, jsonify
from bitvavo_client.bitvavo import Bitvavo
from market_scanner import pick_best_symbol
from memory import save_trade, adjust_rsi
from utils import fetch_price

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
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

def send_message(text):
    try:
        requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", data={"chat_id": CHAT_ID, "text": text})
    except:
        pass

def buy(symbol):
    try:
        if r.hexists("entry", symbol):
            return None, None

        price = fetch_price(symbol)
        if not price:
            return None, None

        amount = round(BUY_AMOUNT_EUR / price, 6)
        body = {
            "market": symbol,
            "side": "buy",
            "orderType": "market",
            "amount": str(amount),
            "operatorId": ""
        }

        result = BITVAVO.placeOrder(body)
        if "error" in result or float(result.get("filledAmount", 0)) == 0:
            return None, None

        executed_price = float(result.get("avgExecutionPrice", price))
        r.hset("entry", symbol, executed_price)
        r.hset("peak", symbol, executed_price)
        r.hset("orders", symbol, "شراء")
        send_message(f"{symbol.split('-')[0]} 🤖 {executed_price}")
        return result, executed_price

    except Exception as e:
        print("خطأ في الشراء:", e)
        return None, None

def sell(symbol, amount, entry_price, reason):
    try:
        result = BITVAVO.placeOrder({
            "market": symbol,
            "side": "sell",
            "orderType": "market",
            "amount": str(amount),
            "operatorId": ""
        })
        price = fetch_price(symbol)
        profit = (price - entry_price) / entry_price * 100
        status = "✅" if profit >= 0 else "❌"
        send_message(f"{symbol.split('-')[0]} {round(profit, 2)}% {status}")
        save_trade(symbol, entry_price, price, reason, status, profit)
        adjust_rsi("success" if profit > 0 else "fail")
        r.delete(IN_TRADE_KEY)
        return result
    except Exception as e:
        print("خطأ في البيع:", e)
        return None

def watch(symbol, entry_price, reason):
    max_price = entry_price
    while True:
        price = fetch_price(symbol)
        if not price:
            time.sleep(1)
            continue

        max_price = max(max_price, price)
        change = (price - entry_price) / entry_price * 100
        if change >= 1.5 or change <= -1:
            break
        time.sleep(1)

    balances = BITVAVO.balance(symbol.split("-")[0])
    amount = float(balances[0].get("available", 0))
    if amount > 0:
        sell(symbol, round(amount, 6), entry_price, reason)

def run_loop():
    r.set(IS_RUNNING_KEY, 1)
    while True:
        if r.get(IS_RUNNING_KEY) != b"1":
            time.sleep(5)
            continue
        if r.get(IN_TRADE_KEY):
            time.sleep(3)
            continue

        symbol, reason, score = pick_best_symbol()
        if not symbol:
            time.sleep(20)
            continue

        order, price = buy(symbol)
        if not order:
            continue
        r.set(IN_TRADE_KEY, symbol)
        watch(symbol, price, reason)

@app.route("/", methods=["POST"])
def telegram_webhook():
    data = request.json
    if not data or "message" not in data:
        return jsonify({"status": "no message"}), 200

    text = data["message"].get("text", "").strip().lower()

    if text == "stop":
        r.set(IS_RUNNING_KEY, 0)
        send_message("⛔ تم الإيقاف.")
    elif text == "play":
        r.set(IS_RUNNING_KEY, 1)
        send_message("✅ تم التشغيل.")
    elif text == "شو عم تعمل":
        running = r.get(IS_RUNNING_KEY) == b"1"
        trade = r.get(IN_TRADE_KEY)
        msg = "✅ يعمل\n" if running else "⏸️ موقوف\n"
        msg += f"صفقة على {trade.decode()}" if trade else "لا صفقات حالياً"
        send_message(msg)
    elif text == "reset":
        r.delete(IN_TRADE_KEY)
        send_message("✅ تم مسح الصفقة.")
    elif text == "الملخص":
        trades = r.lrange("nems:trades", 0, -1)
        if not trades:
            send_message("لا صفقات مسجلة.")
        else:
            msg = "📊 آخر الصفقات:\n"
            for t in trades[-10:][::-1]:
                msg += f"• {t.decode()}\n"
            send_message(msg)

    return jsonify({"status": "ok"}), 200

if __name__ == "__main__":
    threading.Thread(target=run_loop).start()
    app.run(host="0.0.0.0", port=8000)