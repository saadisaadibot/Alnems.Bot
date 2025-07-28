import os
import time
import threading
import redis
import requests
from flask import Flask
from market_scanner import pick_best_symbol
from memory import save_trade, is_in_trade, set_in_trade, clear_trade
from utils import BITVAVO

app = Flask(__name__)
r = redis.from_url(os.getenv("REDIS_URL"))
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
BUY_AMOUNT_EUR = float(os.getenv("BUY_AMOUNT_EUR", 10))

def send_message(text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    data = {"chat_id": CHAT_ID, "text": text}
    try:
        requests.post(url, data=data)
    except Exception as e:
        print(f"❌ Telegram Error: {e}")

def fetch_price(symbol):
    try:
        data = BITVAVO.tickerPrice({"market": symbol})
        return float(data["price"])
    except:
        return None

def buy(symbol):
    price = fetch_price(symbol)
    if not price:
        return None, None

    amount = round(BUY_AMOUNT_EUR / price, 6)
    try:
        order = BITVAVO.placeOrder({
            "market": symbol,
            "side": "buy",
            "orderType": "market",
            "amount": str(amount),
            "operatorId": ""  # المفتاح الفارغ
        })
        return price, amount
    except Exception as e:
        print(f"❌ Buy Failed: {e}")
        return None, None

def sell(symbol, amount):
    try:
        order = BITVAVO.placeOrder({
            "market": symbol,
            "side": "sell",
            "orderType": "market",
            "amount": str(amount),
            "operatorId": ""
        })
        return True
    except Exception as e:
        print(f"❌ Sell Failed: {e}")
        return False

def run_loop():
    while True:
        if is_in_trade():
            time.sleep(10)
            continue

        symbol, reason, score = pick_best_symbol()
        if not symbol:
            print("❌ لا توجد فرصة حالياً")
            time.sleep(10)
            continue

        price, amount = buy(symbol)
        if not price:
            send_message(f"🚫 فشل شراء {symbol}")
            time.sleep(10)
            continue

        set_in_trade(symbol, price, amount)
        send_message(f"شراء = \"{symbol}\" 🤖")

        # متابعة الربح أو الخسارة
        while True:
            time.sleep(15)
            current = fetch_price(symbol)
            if not current:
                continue

            change = (current - price) / price * 100
            if abs(change) >= 1:  # ربح أو خسارة 1%
                if sell(symbol, amount):
                    profit_str = f"{change:+.2f}%"
                    send_message(f"بيع = \"{symbol}\" {profit_str}")
                clear_trade()
                break

threading.Thread(target=run_loop).start()