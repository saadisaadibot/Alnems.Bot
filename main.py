import os
import time
import threading
import redis
import requests
from flask import Flask, request, jsonify
from bitvavo_client.bitvavo import Bitvavo

from market_scanner import pick_best_symbol
from memory import save_trade, is_in_trade, set_in_trade, clear_trade, adjust_rsi
from utils import fetch_price

app = Flask(__name__)
r = redis.from_url(os.getenv("REDIS_URL"))
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
BUY_AMOUNT_EUR = float(os.getenv("BUY_AMOUNT_EUR", 10))

BITVAVO = Bitvavo({
    'APIKEY': os.getenv("BITVAVO_API_KEY"),
    'APISECRET': os.getenv("BITVAVO_API_SECRET"),
    'RESTURL': 'https://api.bitvavo.com/v2',
    'WSURL': 'wss://ws.bitvavo.com/v2'
})

def send_message(text):
    try:
        requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", data={"chat_id": CHAT_ID, "text": text})
    except:
        pass

def buy(symbol):
    price = fetch_price(symbol)
    if not price:
        return None, None

    amount = round(BUY_AMOUNT_EUR / price, 6)
    try:
        order = BITVAVO.placeOrder(symbol, 'buy', 'market', {
            "amount": str(amount),
            "operatorId": ""
        })
        return price, order
    except Exception as e:
        send_message(f"❌ Buy Failed: {e}")
        return None, None

def sell(symbol):
    try:
        balance = BITVAVO.balance(symbol.replace("-EUR", ""))
        available = float(balance.get("available", 0))
        if available < 0.0001:
            return None

        order = BITVAVO.placeOrder(symbol, 'sell', 'market', {
            "amount": str(available),
            "operatorId": ""
        })
        return order
    except Exception as e:
        send_message(f"❌ Sell Failed: {e}")
        return None

def run_loop():
    while True:
        if not r.get("sniper_running") or r.get("sniper_running") != b"1":
            time.sleep(5)
            continue

        if is_in_trade():
            time.sleep(10)
            continue

        symbol, reason, change = pick_best_symbol()
        if not symbol:
            print("❌ لا توجد فرصة حالياً")
            time.sleep(15)
            continue

        send_message(f"شراء = {symbol.replace('-EUR','')} 🤖")
        buy_price, order = buy(symbol)

        if not order:
            continue

        set_in_trade(symbol)
        entry_time = time.time()
        time.sleep(60)  # الانتظار بعد الشراء

        sell_order = sell(symbol)
        if not sell_order:
            clear_trade()
            continue

        sell_price = float(sell_order['fills'][0]['price'])
        profit = ((sell_price - buy_price) / buy_price) * 100
        emoji = "🚀" if profit >= 0 else "💔"

        send_message(f"بيع = {symbol.replace('-EUR','')} {profit:.2f}% {emoji}")
        save_trade(symbol, buy_price, sell_price, profit)
        adjust_rsi(profit)
        clear_trade()
        time.sleep(10)

@app.route("/")
def index():
    return "Sniper bot is running."

@app.route("/start")
def start():
    r.set("sniper_running", "1")
    return "✅ Bot started."

@app.route("/stop")
def stop():
    r.set("sniper_running", "0")
    return "🛑 Bot stopped."

@app.route("/trades")
def trades():
    history = r.lrange("trade_history", 0, 9)
    return jsonify([t.decode() for t in history])

if __name__ == "__main__":
    threading.Thread(target=run_loop).start()
    app.run(host="0.0.0.0", port=8000)